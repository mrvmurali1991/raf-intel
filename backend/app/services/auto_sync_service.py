"""
auto_sync_service.py

Reusable per-patient sync: pull one OpenEMR patient into RAF and return
the local RAF patient_id (or None on error / patient not found).

Public API
----------
    sync_patient_from_openemr(emr_pid: int) -> int | None

Behaviour
---------
1.  Check whether *emr_pid* already exists in the RAF patients VIEW.
    The VIEW bridges raf_intelligence → openemr.patient_data so a valid
    OpenEMR pid is always present; an *invalid* pid returns None.
2.  If the patient row exists, return the local id immediately (idempotent
    no-op when encounters/conditions were already synced).
3.  Pull encounters from openemr.form_encounter and upsert into
    raf_intelligence.normalized_encounters (INSERT IGNORE by encounter_id).
4.  Pull SOAP / clinical note text from openemr.form_soap + form_clinical_notes
    and write it into normalized_encounters.note_text for the matching
    encounter row.  If the column does not yet exist on the target table,
    it is added automatically via ALTER TABLE (idempotent).
5.  Pull active problems from openemr.lists (type='medical_problem') and
    upsert ICD-10-bearing rows into raf_intelligence.raf_suspect_conditions.
    For each ICD-10 the HCC category is resolved via hcc_mapping_service
    (hccinfhir under the hood) and stored in suspect_hcc.  Codes with no
    HCC mapping default to 0 with a log warning.
6.  Fire the pipeline chain (_handle_emr_sync_completed) so that AI/RAF
    scoring runs automatically after the sync completes.
7.  Log every step with structured logger keys:
      auto_sync.check, auto_sync.synced, auto_sync.encounter_upsert,
      auto_sync.notes_sync, auto_sync.condition_upsert, auto_sync.error
8.  Catch *all* exceptions and return None on error with full traceback logged.
"""
from __future__ import annotations

import logging
import traceback
from datetime import date
from typing import Optional

import mysql.connector

from app.db import openemr_cursor, raf_cursor

logger = logging.getLogger(__name__)

# ── helpers ──────────────────────────────────────────────────────────────────

def _current_year() -> int:
    return date.today().year


def _check_local_patient(emr_pid: int) -> Optional[int]:
    """Return local RAF patient id if *emr_pid* exists, else None."""
    with raf_cursor() as cur:
        cur.execute(
            "SELECT id FROM patients WHERE emr_pid = %s LIMIT 1",
            (str(emr_pid),),
        )
        row = cur.fetchone()
    return int(row["id"]) if row else None


def _age_band(dob, measurement_year: int) -> str:
    """Map DOB to a CMS-HCC age band string."""
    if not dob:
        return "65-69"
    age = measurement_year - dob.year
    bands = [
        (35, "0-34"), (45, "35-44"), (55, "45-54"), (60, "55-59"),
        (65, "60-64"), (70, "65-69"), (75, "70-74"), (80, "75-79"),
        (85, "80-84"), (90, "85-89"), (95, "90-94"),
    ]
    for upper, label in bands:
        if age < upper:
            return label
    return "95+"


def _ensure_demographics(local_pid: int, dob, sex: str | None) -> None:
    """Make sure raf_patient_demographics has a row for the current measurement
    year, satisfying the FK constraint that raf_suspect_conditions depends on."""
    measurement_year = _current_year()
    sex_norm = "F" if (sex or "").strip().lower().startswith("f") else "M"
    age_band = _age_band(dob, measurement_year)
    with raf_cursor() as cur:
        cur.execute(
            """
            INSERT INTO raf_patient_demographics
                (patient_id, measurement_year, age_band, sex, dual_status,
                 dual_type, disabled, orec, institutional, enrollment_source,
                 model_segment, tenant_id)
            VALUES (%s, %s, %s, %s, 0, 'non_dual', 0, '0', 0, 'derived',
                    'CNA', '1')
            ON DUPLICATE KEY UPDATE
                age_band = VALUES(age_band),
                sex      = VALUES(sex)
            """,
            (local_pid, measurement_year, age_band, sex_norm),
        )


def _insert_local_patient(emr_pid: int) -> Optional[int]:
    """Create a RAF patient row from openemr.patient_data and return its id.

    Returns None when the emr_pid does not exist in openemr.patient_data.
    Idempotent: re-runs return the existing id instead of inserting a duplicate.
    """
    with openemr_cursor() as cur:
        cur.execute(
            """
            SELECT pid, fname, lname, mname, DOB, sex, race, ethnicity,
                   language, street, city, state, postal_code,
                   COALESCE(NULLIF(phone_cell, ''), phone_home) AS phone,
                   email, pubpid
            FROM   patient_data
            WHERE  pid = %s
            LIMIT  1
            """,
            (emr_pid,),
        )
        src = cur.fetchone()

    if not src:
        return None

    with raf_cursor() as cur:
        # Recheck under the same connection in case a concurrent sync inserted
        # the row between _check_local_patient and here.
        cur.execute(
            "SELECT id FROM patients WHERE emr_pid = %s LIMIT 1",
            (str(emr_pid),),
        )
        existing = cur.fetchone()
        if existing:
            return int(existing["id"])

        cur.execute(
            """
            INSERT INTO patients (
                tenant_id, first_name, middle_name, last_name, dob, sex,
                race, ethnicity, preferred_language, address, city, state, zip,
                phone, email, mrn, emr_pid, data_source, is_active
            ) VALUES (
                '1', %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s, 'openemr', 1
            )
            """,
            (
                src.get("fname") or "",
                src.get("mname"),
                src.get("lname") or "",
                src.get("DOB"),
                src.get("sex"),
                src.get("race"),
                src.get("ethnicity"),
                src.get("language"),
                src.get("street"),
                src.get("city"),
                src.get("state"),
                src.get("postal_code"),
                src.get("phone"),
                src.get("email"),
                src.get("pubpid"),
                str(emr_pid),
            ),
        )
        new_id = cur.lastrowid

    logger.info(
        "auto_sync.patient_inserted",
        extra={"emr_pid": emr_pid, "local_pid": new_id},
    )
    return int(new_id) if new_id else None


def _ensure_note_text_column() -> None:
    """Add note_text TEXT NULL column to normalized_encounters if absent.

    Idempotent: swallows MySQL error 1060 (ER_DUP_FIELDNAME) if the column
    already exists so repeated calls are safe.
    """
    try:
        with raf_cursor() as cur:
            cur.execute(
                "ALTER TABLE normalized_encounters ADD COLUMN note_text TEXT NULL"
            )
        logger.info("auto_sync: added note_text column to normalized_encounters")
    except mysql.connector.Error as exc:
        if exc.errno == 1060:
            # Column already present — expected on second and subsequent runs.
            logger.debug("auto_sync: note_text column already exists (ok)")
        else:
            logger.warning("auto_sync: could not add note_text column: %s", exc)
    except Exception as exc:
        logger.warning("auto_sync: could not add note_text column: %s", exc)


def _sync_encounters(local_pid: int, emr_pid: int) -> int:
    """
    Pull encounters from openemr.form_encounter and upsert into
    raf_intelligence.normalized_encounters.

    Returns the number of rows upserted.
    """
    sql_pull = """
        SELECT
            fe.encounter                      AS encounter_id,
            fe.date                           AS encounter_date,
            COALESCE(fe.reason, '')           AS reason,
            COALESCE(fe.facility, '')         AS facility_name,
            COALESCE(
                CONCAT(u.fname, ' ', u.lname), ''
            )                                 AS provider_name
        FROM form_encounter fe
        LEFT JOIN users u ON u.id = fe.provider_id
        WHERE fe.pid = %s
        ORDER BY fe.date DESC
    """
    with openemr_cursor() as cur:
        cur.execute(sql_pull, (emr_pid,))
        rows = cur.fetchall()

    if not rows:
        return 0

    upserted = 0
    with raf_cursor() as cur:
        for r in rows:
            enc_date = r["encounter_date"]
            if hasattr(enc_date, "date"):
                enc_date = enc_date.date()
            cur.execute(
                """
                INSERT IGNORE INTO normalized_encounters
                    (openemr_encounter_id, patient_id, tenant_id, encounter_date,
                     encounter_type, facility)
                VALUES (%s, %s, '1', %s, 'office_visit', %s)
                """,
                (int(r["encounter_id"]), local_pid, str(enc_date), r["facility_name"] or None),
            )
            upserted += cur.rowcount

    logger.info(
        "auto_sync.encounter_upsert",
        extra={"emr_pid": emr_pid, "local_pid": local_pid, "upserted": upserted},
    )
    return upserted


def _sync_notes(local_pid: int, emr_pid: int) -> int:
    """Pull SOAP + clinical note text from OpenEMR and write to normalized_encounters.note_text.

    Joins form_soap → forms on (form_id / formdir='soap') to obtain the
    encounter number, then updates the matching normalized_encounters row.
    Falls back to form_clinical_notes when form_soap yields no text.

    Returns the number of encounter rows updated.
    """
    # Ensure the column exists before we try to UPDATE it.
    _ensure_note_text_column()

    sql_soap = """
        SELECT
            f.encounter                           AS encounter_id,
            CONCAT_WS('\n\n',
                IF(COALESCE(fs.subjective, '') <> '', CONCAT('S: ', fs.subjective), NULL),
                IF(COALESCE(fs.objective,  '') <> '', CONCAT('O: ', fs.objective),  NULL),
                IF(COALESCE(fs.assessment, '') <> '', CONCAT('A: ', fs.assessment), NULL),
                IF(COALESCE(fs.plan,       '') <> '', CONCAT('P: ', fs.plan),       NULL)
            )                                     AS note_text
        FROM form_soap fs
        JOIN forms f ON f.form_id = fs.id AND f.formdir = 'soap'
        WHERE fs.pid = %s
          AND fs.activity = 1
    """
    sql_cn = """
        SELECT
            fcn.encounter                         AS encounter_id,
            COALESCE(fcn.description, '')         AS note_text
        FROM form_clinical_notes fcn
        WHERE fcn.pid = %s
    """

    # Build encounter_id -> note_text map from OpenEMR; last writer wins if
    # multiple note rows exist for the same encounter.
    note_map: dict[int, str] = {}

    with openemr_cursor() as cur:
        cur.execute(sql_soap, (emr_pid,))
        for r in cur.fetchall():
            enc_id = r.get("encounter_id")
            txt = (r.get("note_text") or "").strip()
            if enc_id and txt:
                note_map[int(enc_id)] = txt

        # Augment / fill gaps with form_clinical_notes
        try:
            cur.execute(sql_cn, (emr_pid,))
            for r in cur.fetchall():
                enc_id = r.get("encounter_id")
                txt = (r.get("note_text") or "").strip()
                if enc_id and txt:
                    existing = note_map.get(int(enc_id), "")
                    combined = (existing + "\n\n" + txt).strip() if existing else txt
                    note_map[int(enc_id)] = combined
        except Exception as _fcn_exc:
            logger.debug("auto_sync._sync_notes: form_clinical_notes unavailable: %s", _fcn_exc)

    if not note_map:
        return 0

    updated = 0
    with raf_cursor() as cur:
        for openemr_enc_id, note_text in note_map.items():
            cur.execute(
                """
                UPDATE normalized_encounters
                   SET note_text = %s
                 WHERE openemr_encounter_id = %s
                   AND patient_id = %s
                """,
                (note_text, openemr_enc_id, local_pid),
            )
            updated += cur.rowcount

    logger.info(
        "auto_sync.notes_sync",
        extra={"emr_pid": emr_pid, "local_pid": local_pid, "updated": updated},
    )
    return updated


def _sync_conditions(local_pid: int, emr_pid: int) -> int:
    """
    Pull active medical problems from openemr.lists and upsert ICD-10-bearing
    rows into raf_intelligence.raf_suspect_conditions.

    Uses hcc_mapping_service to resolve suspect_hcc for each ICD-10 code via
    the authoritative hccinfhir engine.  Codes with no HCC mapping default to
    0 and log a warning.

    Returns the number of rows upserted.
    """
    sql_pull = """
        SELECT
            title                             AS diagnosis,
            diagnosis                         AS icd10_raw,
            YEAR(CURDATE())                   AS measurement_year
        FROM lists
        WHERE pid = %s
          AND type = 'medical_problem'
          AND activity = 1
          AND diagnosis IS NOT NULL
          AND diagnosis != ''
    """
    with openemr_cursor() as cur:
        cur.execute(sql_pull, (emr_pid,))
        rows = cur.fetchall()

    if not rows:
        return 0

    # Batch-resolve all ICD-10 codes to HCC using the authoritative service.
    from app.services.hcc_mapping_service import map_icd10_batch

    raw_codes = []
    for r in rows:
        raw = (r.get("icd10_raw") or "").strip()
        icd10 = raw.replace("ICD10:", "").replace("SNOMED:", "").strip()
        if icd10:
            raw_codes.append(icd10)

    hcc_map = {}
    if raw_codes:
        try:
            hcc_map = map_icd10_batch(raw_codes)
        except Exception as hcc_exc:
            logger.warning(
                "auto_sync._sync_conditions: batch HCC lookup failed (%s) — "
                "falling back to hcc=0 for all codes",
                hcc_exc,
            )

    upserted = 0
    measurement_year = _current_year()

    with raf_cursor() as cur:
        for r in rows:
            raw = (r.get("icd10_raw") or "").strip()
            # OpenEMR stores codes as "ICD10:F32.1" or bare "F32.1"
            icd10 = raw.replace("ICD10:", "").replace("SNOMED:", "").strip()
            if not icd10:
                continue

            # Resolve HCC via hccinfhir; normalise to dot-less for lookup
            icd10_key = icd10.upper().replace(".", "")
            hcc_entry = hcc_map.get(icd10_key)
            if hcc_entry:
                suspect_hcc = int(hcc_entry["hcc_code"])
            else:
                suspect_hcc = 0
                logger.warning(
                    "auto_sync._sync_conditions: no HCC mapping for ICD-10 %s "
                    "(pid=%s) — storing suspect_hcc=0",
                    icd10,
                    emr_pid,
                )

            # Only insert if not already present for this patient + icd10 + year
            cur.execute(
                """
                SELECT id FROM raf_suspect_conditions
                WHERE patient_id = %s
                  AND suspect_icd10 = %s
                  AND measurement_year = %s
                LIMIT 1
                """,
                (local_pid, icd10, measurement_year),
            )
            if cur.fetchone():
                continue

            cur.execute(
                """
                INSERT INTO raf_suspect_conditions
                    (patient_id, measurement_year, suspect_hcc, suspect_icd10,
                     evidence_type, evidence_detail, confidence_score,
                     status, tenant_id)
                VALUES
                    (%s, %s, %s, %s,
                     'historical',
                     JSON_OBJECT(
                         'source', 'openemr_problems',
                         'diagnosis', %s,
                         'nlp_evidence_sentence', %s
                     ),
                     0.7000,
                     'open', '1')
                """,
                (
                    local_pid,
                    measurement_year,
                    suspect_hcc,
                    icd10,
                    r.get("diagnosis", ""),
                    r.get("diagnosis", ""),   # also surfaces as tooltip evidence
                ),
            )
            upserted += cur.rowcount

    logger.info(
        "auto_sync.condition_upsert",
        extra={"emr_pid": emr_pid, "local_pid": local_pid, "upserted": upserted},
    )
    return upserted


def _fire_pipeline_chain(local_pid: int) -> None:
    """Trigger the 8-phase pipeline chain for tenant '1' after auto-sync.

    Uses connection_id=8 (the active OpenEMR direct-DB connection).
    Uses a unique sync_id derived from local_pid + timestamp so repeated
    syncs for the same patient each create a fresh pipeline run.

    All errors are caught and logged; the chain must never crash the sync.
    """
    import time as _time

    try:
        from app.services.pipeline_chain import _handle_emr_sync_completed

        sync_id = f"auto_sync_{local_pid}_{int(_time.time())}"
        _handle_emr_sync_completed({
            "tenant_id": "1",
            "connection_id": 8,   # active OpenEMR direct-DB connection
            "sync_id": sync_id,
            "sync_type": "auto_sync",
        })
        logger.info(
            "auto_sync.pipeline_fired",
            extra={"local_pid": local_pid, "sync_id": sync_id},
        )
    except Exception as chain_exc:
        logger.error(
            "auto_sync.pipeline_fire_failed pid=%s: %s",
            local_pid,
            chain_exc,
            exc_info=True,
        )


# ── public API ────────────────────────────────────────────────────────────────

def sync_patient_from_openemr(emr_pid: int) -> Optional[int]:
    """
    Pull one OpenEMR patient into RAF and return the local RAF patient_id.

    Call order:
        _check_local_patient / _insert_local_patient
        → _ensure_demographics
        → _sync_encounters
        → _sync_notes
        → _sync_conditions
        → _fire_pipeline_chain  (AI + RAF scoring)

    Parameters
    ----------
    emr_pid : int
        The OpenEMR patient PID (openemr.patient_data.pid).

    Returns
    -------
    int
        Local RAF patient id on success (idempotent — same id on repeat calls).
    None
        When the patient does not exist in OpenEMR or an error occurs.
    """
    try:
        logger.info("auto_sync.check", extra={"emr_pid": emr_pid})

        local_pid = _check_local_patient(emr_pid)

        if local_pid is not None:
            # Patient already exists in RAF — still re-sync child records so
            # repeated calls are fully idempotent at every layer.
            logger.info(
                "auto_sync.synced",
                extra={"emr_pid": emr_pid, "local_pid": local_pid, "action": "existing"},
            )
        else:
            # First time we've seen this OpenEMR pid — create the RAF patient
            # row from openemr.patient_data before syncing child records.
            local_pid = _insert_local_patient(emr_pid)
            if local_pid is None:
                logger.info(
                    "auto_sync.not_found",
                    extra={"emr_pid": emr_pid},
                )
                return None

        # Ensure raf_patient_demographics row exists for the current
        # measurement year — _sync_conditions has a FK on (patient_id,
        # measurement_year) referencing this table.
        with raf_cursor() as cur:
            cur.execute(
                "SELECT dob, sex FROM patients WHERE id = %s LIMIT 1",
                (local_pid,),
            )
            row = cur.fetchone() or {}
        _ensure_demographics(local_pid, row.get("dob"), row.get("sex"))

        _sync_encounters(local_pid, emr_pid)
        _sync_notes(local_pid, emr_pid)
        _sync_conditions(local_pid, emr_pid)

        logger.info(
            "auto_sync.synced",
            extra={"emr_pid": emr_pid, "local_pid": local_pid, "action": "complete"},
        )

        # Fire the pipeline chain AFTER all data is committed so the AI/RAF
        # pipeline sees the fresh note_text and updated suspect conditions.
        _fire_pipeline_chain(local_pid)

        return local_pid

    except Exception:  # noqa: BLE001
        logger.error(
            "auto_sync.error",
            extra={"emr_pid": emr_pid},
            exc_info=True,
        )
        logger.debug("auto_sync.traceback emr_pid=%s\n%s", emr_pid, traceback.format_exc())
        return None
