"""
Encounter Normalization Service

Pulls raw encounter and diagnosis data from the connected OpenEMR database
and normalizes it into RAF Intelligence local tables for CMS submission
readiness.

Local tables written:
  - normalized_encounters
  - normalized_diagnoses

Local tables read:
  - emr_patient_matches   — maps internal patient_id -> OpenEMR pid
  - hcc_icd10_crosswalk   — maps icd10_code -> hcc_code, model_version

OpenEMR tables read (via openemr pool):
  - form_encounter
  - billing
  - users

All syncs are idempotent: INSERT IGNORE / ON DUPLICATE KEY UPDATE is used
throughout so repeated runs are safe.
"""

from __future__ import annotations

import logging
from typing import Any

from app.db import dynamic_db_cursor, raf_cursor
from app.services.encryption_service import decrypt
from app.services.hcc_mapping_service import map_icd10_batch

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _get_emr_connection_creds(connection_id: int) -> dict:
    """Fetch host/port/db/user/password from emr_connections for *connection_id*.

    The stored password is decrypted before being returned.

    Raises:
        ValueError: when no row exists for *connection_id*.
    """
    with raf_cursor() as cursor:
        cursor.execute(
            """
            SELECT db_host, db_port, db_name, db_user, db_password, db_type
            FROM   emr_connections
            WHERE  id = %s
            """,
            (connection_id,),
        )
        row = cursor.fetchone()

    if row is None:
        raise ValueError(
            f"_get_emr_connection_creds: no emr_connections row for id={connection_id}"
        )

    encrypted_pw = row.get("db_password") or ""
    try:
        plain_pw = decrypt(encrypted_pw) if encrypted_pw else ""
    except Exception as exc:
        raise ValueError(
            f"_get_emr_connection_creds: failed to decrypt password for connection_id={connection_id}: {exc}"
        ) from exc

    return {
        "host": row["db_host"],
        "port": int(row["db_port"] or 3306),
        "database": row["db_name"],
        "user": row["db_user"],
        "password": plain_pw,
        "db_type": row.get("db_type") or "mysql",
    }


def _build_pid_to_patient_map(tenant_id: str) -> dict[int, str]:
    if not tenant_id:
        raise ValueError(
            "_build_pid_to_patient_map: tenant_id is required — "
            "refusing to operate without tenant scope (HIPAA multi-tenant isolation)"
        )
    """
    Load the full emr_patient_matches table for a tenant into a dict keyed
    by openemr_pid so look-ups are O(1) during the sync loop.

    Returns: {openemr_pid (int): internal patient_id (str)}
    """
    with raf_cursor() as cursor:
        cursor.execute(
            """
            SELECT patient_id, emr_pid
            FROM   emr_patient_matches
            WHERE  tenant_id = %s
            """,
            (tenant_id,),
        )
        return {row["emr_pid"]: row["patient_id"] for row in cursor.fetchall()}


def _build_icd10_hcc_map(icd10_codes: list[str]) -> dict[str, dict]:
    """
    Build an ICD-10 → HCC mapping dict for the given codes using hccinfhir
    as the authoritative source (via hcc_mapping_service.map_icd10_batch).

    This replaces the previous implementation that read the
    ``hcc_icd10_crosswalk`` database table directly.  The table still exists
    for caching/reporting but must NOT be used as an authoritative source —
    see hcc_mapping_service.py for the full rationale.

    Returns: {icd10_code: {"hcc_code": str, "model_version": str}}
    """
    batch_result = map_icd10_batch(icd10_codes, model_version="V28")
    return {
        code: {
            "hcc_code": entry["hcc_code"],
            "model_version": entry["model_version"],
        }
        for code, entry in batch_result.items()
    }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def sync_encounters(tenant_id: str, connection_id: int) -> dict:
    """Pull all encounters from the EMR identified by *connection_id* and
    normalize them into `normalized_encounters`.

    Args:
        tenant_id: The RAF Intelligence tenant performing the sync.
        connection_id: The ``emr_connections.id`` that identifies which EMR
            database to connect to.  Credentials are fetched from that row and
            the stored password is decrypted before use.

    Mapping:
      form_encounter.encounter      -> openemr_encounter_id
      form_encounter.pid            -> openemr pid (resolved to patient_id via
                                        emr_patient_matches)
      form_encounter.date           -> encounter_date
      form_encounter.facility       -> facility
      form_encounter.reason         -> encounter_type
      users.npi                     -> provider_npi

    Returns:
      {"synced": int, "skipped": int, "errors": int}
    """
    if not tenant_id:
        raise ValueError(
            "sync_encounters: tenant_id is required — "
            "refusing to operate without tenant scope (HIPAA multi-tenant isolation)"
        )

    pid_map = _build_pid_to_patient_map(tenant_id)
    creds = _get_emr_connection_creds(connection_id)

    synced = skipped = errors = 0

    with dynamic_db_cursor(
        host=creds["host"],
        port=creds["port"],
        database=creds["database"],
        user=creds["user"],
        password=creds["password"],
        db_type=creds["db_type"],
        dictionary=True,
    ) as emr_cur:
        emr_cur.execute(
            """
            SELECT
                fe.id             AS fe_id,
                fe.encounter      AS openemr_encounter_id,
                fe.pid            AS pid,
                fe.date           AS encounter_date,
                fe.facility       AS facility,
                fe.reason         AS encounter_type,
                u.npi             AS provider_npi
            FROM   form_encounter fe
            LEFT JOIN users u ON u.id = fe.provider_id
            ORDER  BY fe.id
            """
        )
        rows = emr_cur.fetchall()

    with raf_cursor() as raf_cur:
        for row in rows:
            pid = row["pid"]
            patient_id = pid_map.get(pid)
            if patient_id is None:
                logger.debug(
                    "sync_encounters: no patient match for openemr pid=%s, skipping", pid
                )
                skipped += 1
                continue

            try:
                raf_cur.execute(
                    """
                    INSERT INTO normalized_encounters
                        (patient_id, tenant_id, openemr_encounter_id,
                         provider_npi, encounter_date, encounter_type,
                         facility, status)
                    VALUES
                        (%s, %s, %s, %s, %s, %s, %s, 'active')
                    ON DUPLICATE KEY UPDATE
                        provider_npi    = VALUES(provider_npi),
                        encounter_date  = VALUES(encounter_date),
                        encounter_type  = VALUES(encounter_type),
                        facility        = VALUES(facility),
                        status          = VALUES(status)
                    """,
                    (
                        patient_id,
                        tenant_id,
                        row["openemr_encounter_id"],
                        row["provider_npi"],
                        row["encounter_date"],
                        row["encounter_type"],
                        row["facility"],
                    ),
                )
                synced += 1
            except Exception as exc:
                logger.error(
                    "sync_encounters: failed to upsert encounter %s — %s",
                    row["openemr_encounter_id"],
                    exc,
                )
                errors += 1

    logger.info(
        "sync_encounters [tenant=%s connection_id=%s]: synced=%d skipped=%d errors=%d",
        tenant_id, connection_id, synced, skipped, errors,
    )
    return {"synced": synced, "skipped": skipped, "errors": errors}


def sync_diagnoses(tenant_id: str, connection_id: int) -> dict:
    """Pull all active ICD-10 billing records from the EMR identified by
    *connection_id*, resolve them to rows in `normalized_encounters`, enrich
    with HCC crosswalk data, and upsert into `normalized_diagnoses`.

    Args:
        tenant_id: The RAF Intelligence tenant performing the sync.
        connection_id: The ``emr_connections.id`` that identifies which EMR
            database to connect to.  Credentials are fetched from that row and
            the stored password is decrypted before use.

    A diagnosis is considered primary (is_primary=1) when the billing row
    has modifier='1' or is the first code on the encounter (lowest billing.id).

    Returns:
      {"synced": int, "skipped": int, "errors": int}
    """
    if not tenant_id:
        raise ValueError(
            "sync_diagnoses: tenant_id is required — "
            "refusing to operate without tenant scope (HIPAA multi-tenant isolation)"
        )

    pid_map = _build_pid_to_patient_map(tenant_id)
    creds = _get_emr_connection_creds(connection_id)

    # Load normalized_encounters keyed by openemr_encounter_id so we can
    # resolve encounter_id quickly without a per-row RAF query.
    with raf_cursor() as raf_cur:
        raf_cur.execute(
            """
            SELECT encounter_id, openemr_encounter_id, patient_id
            FROM   normalized_encounters
            WHERE  tenant_id = %s
            """,
            (tenant_id,),
        )
        enc_rows = raf_cur.fetchall()

    enc_map: dict[int, dict] = {
        row["openemr_encounter_id"]: {
            "encounter_id": row["encounter_id"],
            "patient_id": row["patient_id"],
        }
        for row in enc_rows
    }

    synced = skipped = errors = 0

    with dynamic_db_cursor(
        host=creds["host"],
        port=creds["port"],
        database=creds["database"],
        user=creds["user"],
        password=creds["password"],
        db_type=creds["db_type"],
        dictionary=True,
    ) as emr_cur:
        emr_cur.execute(
            """
            SELECT
                b.id        AS billing_id,
                b.encounter AS openemr_encounter_id,
                b.pid       AS pid,
                b.code      AS icd10_code,
                b.code_text AS description,
                b.modifier  AS modifier
            FROM   billing b
            WHERE  b.code_type = 'ICD10'
              AND  b.activity  = 1
            ORDER  BY b.encounter, b.id
            """
        )
        billing_rows = emr_cur.fetchall()

    # Build the authoritative HCC map from hccinfhir for all unique
    # ICD-10 codes in this batch.  This replaces the previous approach of
    # reading from the hcc_icd10_crosswalk table, which could silently lag
    # behind CMS model updates.  See hcc_mapping_service.py for details.
    unique_icd10_codes: list[str] = list(
        {(row["icd10_code"] or "").strip() for row in billing_rows if row["icd10_code"]}
    )
    hcc_map = _build_icd10_hcc_map(unique_icd10_codes)

    # Track the first billing_id per encounter to detect primary code.
    first_billing_per_enc: dict[int, int] = {}
    for row in billing_rows:
        enc_id = row["openemr_encounter_id"]
        if enc_id not in first_billing_per_enc:
            first_billing_per_enc[enc_id] = row["billing_id"]

    with raf_cursor() as raf_cur:
        for row in billing_rows:
            openemr_enc_id = row["openemr_encounter_id"]
            enc_info = enc_map.get(openemr_enc_id)
            if enc_info is None:
                logger.debug(
                    "sync_diagnoses: encounter %s not in normalized_encounters, skipping",
                    openemr_enc_id,
                )
                skipped += 1
                continue

            pid = row["pid"]
            patient_id = pid_map.get(pid)
            if patient_id is None:
                logger.debug(
                    "sync_diagnoses: no patient match for pid=%s, skipping", pid
                )
                skipped += 1
                continue

            icd10_code = (row["icd10_code"] or "").strip()
            hcc_info = hcc_map.get(icd10_code, {})

            # Primary: explicit modifier '1' OR first billing row for this encounter.
            modifier = str(row["modifier"] or "").strip()
            is_primary = 1 if (
                modifier == "1"
                or row["billing_id"] == first_billing_per_enc.get(openemr_enc_id)
            ) else 0

            try:
                raf_cur.execute(
                    """
                    INSERT INTO normalized_diagnoses
                        (encounter_id, patient_id, tenant_id, icd10_code,
                         description, is_primary, source,
                         hcc_code, model_version, status)
                    VALUES
                        (%s, %s, %s, %s, %s, %s, 'openemr', %s, %s, 'active')
                    ON DUPLICATE KEY UPDATE
                        description   = VALUES(description),
                        is_primary    = VALUES(is_primary),
                        hcc_code      = VALUES(hcc_code),
                        model_version = VALUES(model_version),
                        status        = VALUES(status)
                    """,
                    (
                        enc_info["encounter_id"],
                        patient_id,
                        tenant_id,
                        icd10_code,
                        row["description"],
                        is_primary,
                        hcc_info.get("hcc_code"),
                        hcc_info.get("model_version"),
                    ),
                )
                synced += 1
            except Exception as exc:
                logger.error(
                    "sync_diagnoses: failed to upsert diagnosis icd10=%s enc=%s — %s",
                    icd10_code, openemr_enc_id, exc,
                )
                errors += 1

    logger.info(
        "sync_diagnoses [tenant=%s connection_id=%s]: synced=%d skipped=%d errors=%d",
        tenant_id, connection_id, synced, skipped, errors,
    )

    # Emit an internal pipeline event so the auto-chain can trigger RAF
    # recalculation.  The import is deferred to avoid circular imports at
    # module load time.  The call is non-blocking (fires in a background thread).
    try:
        from app.services.event_emitter import emit_internal
        emit_internal(
            "normalization_completed",
            {
                "tenant_id": tenant_id,
                "patient_ids": list(pid_map.values()),
                "diagnoses_synced": synced,
                "diagnoses_skipped": skipped,
                "diagnoses_errors": errors,
            },
        )
    except Exception as _emit_exc:
        logger.error(
            "sync_diagnoses: failed to emit normalization_completed: %s", _emit_exc
        )

    return {"synced": synced, "skipped": skipped, "errors": errors}


def sync_all(tenant_id: str, connection_id: int) -> dict:
    """Run sync_encounters then sync_diagnoses in order.

    Encounters must be synced first so that normalized_encounters rows exist
    before diagnoses attempt to reference them.

    Args:
        tenant_id: The RAF Intelligence tenant performing the sync.
        connection_id: The ``emr_connections.id`` used for both sync steps.

    Returns:
      {
        "encounters": {"synced": int, "skipped": int, "errors": int},
        "diagnoses":  {"synced": int, "skipped": int, "errors": int},
      }
    """
    if not tenant_id:
        raise ValueError(
            "sync_all: tenant_id is required — "
            "refusing to operate without tenant scope (HIPAA multi-tenant isolation)"
        )
    enc_result = sync_encounters(tenant_id=tenant_id, connection_id=connection_id)
    diag_result = sync_diagnoses(tenant_id=tenant_id, connection_id=connection_id)
    return {"encounters": enc_result, "diagnoses": diag_result}


def get_encounter_diagnosis_bundle(tenant_id: str) -> list[dict]:
    if not tenant_id:
        raise ValueError(
            "get_encounter_diagnosis_bundle: tenant_id is required — "
            "refusing to operate without tenant scope (HIPAA multi-tenant isolation)"
        )
    """
    Return a flat list of encounter-diagnosis pairs formatted for CMS
    Bundle 2 submission readiness.

    Each dict contains:
      Encounter_ID   — internal normalized_encounters.encounter_id
      Patient_ID     — internal patient identifier
      DOS            — date of service (encounter_date)
      Provider_NPI   — rendering provider NPI
      ICD10_Code     — diagnosis code
      Primary_Flag   — 1 if primary diagnosis, 0 otherwise

    Only active encounters paired with active diagnoses are included.
    """
    with raf_cursor() as cursor:
        cursor.execute(
            """
            SELECT
                ne.encounter_id   AS Encounter_ID,
                ne.patient_id     AS Patient_ID,
                ne.encounter_date AS DOS,
                ne.provider_npi   AS Provider_NPI,
                nd.icd10_code     AS ICD10_Code,
                nd.is_primary     AS Primary_Flag
            FROM   normalized_encounters ne
            JOIN   normalized_diagnoses  nd
                   ON nd.encounter_id = ne.encounter_id
                  AND nd.tenant_id    = ne.tenant_id
            WHERE  ne.tenant_id  = %s
              AND  ne.status     = 'active'
              AND  nd.status     = 'active'
            ORDER  BY ne.encounter_date DESC, ne.encounter_id, nd.is_primary DESC
            """,
            (tenant_id,),
        )
        rows = cursor.fetchall()

    # Coerce date objects to ISO strings for JSON safety.
    result: list[dict] = []
    for row in rows:
        dos = row["DOS"]
        result.append(
            {
                "Encounter_ID": row["Encounter_ID"],
                "Patient_ID": row["Patient_ID"],
                "DOS": dos.isoformat() if hasattr(dos, "isoformat") else str(dos),
                "Provider_NPI": row["Provider_NPI"],
                "ICD10_Code": row["ICD10_Code"],
                "Primary_Flag": int(row["Primary_Flag"]),
            }
        )
    return result
