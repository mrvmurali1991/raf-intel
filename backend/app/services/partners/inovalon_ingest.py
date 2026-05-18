"""
Inovalon EROND ingestion pipeline.

Orchestrates the full flow:
  1. Look up RAF patient demographics.
  2. Submit a pull request to Inovalon and record it in ``inovalon_patient_pulls``.
  3. Parse the returned FHIR Bundle:
       - Condition resources → ICD-10 → HCC cross-walk → open suspects
       - DocumentReference resources → binary fetch → Gemini vision pipeline
       - Observation resources (LOINC) → ``raf_external_observations``

Design principles:
  - Idempotent: same ``inovalon_pull_id`` is a no-op (UNIQUE constraint in DB).
  - Never raises — all errors are caught, logged, and surfaced in the return dict.
  - DB writes use the standard ``raf_cursor()`` context manager.
"""
from __future__ import annotations

import json
import logging
from datetime import date, datetime, timezone
from typing import Any

from app.db import raf_cursor
from app.services.hccinfhir_utils import lookup_hcc
from app.services.partners.inovalon import InovalonClient

logger = logging.getLogger(__name__)

# ICD-10-CM system URI used by Inovalon FHIR resources.
_ICD10_SYSTEM = "http://hl7.org/fhir/sid/icd-10-cm"
# LOINC system URI.
_LOINC_SYSTEM = "http://loinc.org"


# ---------------------------------------------------------------------------
# Demographics lookup
# ---------------------------------------------------------------------------

def _get_patient_demographics(raf_patient_id: int) -> dict[str, Any] | None:
    """Return minimal demographics for a RAF patient, or None if not found."""
    with raf_cursor() as cur:
        cur.execute(
            """SELECT p.id, p.first_name, p.last_name, p.date_of_birth,
                      p.gender, p.member_id
               FROM   raf_patients p
               WHERE  p.id = %s
               LIMIT 1""",
            (raf_patient_id,),
        )
        row = cur.fetchone()
    if not row:
        return None
    if isinstance(row, dict):
        return row
    # mysql-connector returns tuple when dictionary=False
    cols = ["id", "first_name", "last_name", "date_of_birth", "gender", "member_id"]
    return dict(zip(cols, row))


# ---------------------------------------------------------------------------
# Pull-record persistence
# ---------------------------------------------------------------------------

def _upsert_pull_record(
    tenant_id: str,
    raf_patient_id: int,
    pull_id: str,
    status: str,
    submitted_at: str,
    resources_returned: dict | None = None,
    bundle_size_bytes: int = 0,
    error_text: str | None = None,
) -> int:
    """Insert or update an inovalon_patient_pulls row; return the row id."""
    with raf_cursor() as cur:
        cur.execute(
            """INSERT INTO inovalon_patient_pulls
                 (tenant_id, raf_patient_id, inovalon_pull_id, submitted_at,
                  completed_at, status, resources_returned,
                  bundle_size_bytes, error_text)
               VALUES (%s, %s, %s, %s, NULL, %s, %s, %s, %s)
               ON DUPLICATE KEY UPDATE
                 status             = VALUES(status),
                 resources_returned = VALUES(resources_returned),
                 bundle_size_bytes  = VALUES(bundle_size_bytes),
                 error_text         = VALUES(error_text),
                 completed_at       = CASE
                   WHEN VALUES(status) IN ('completed','failed')
                   THEN NOW() ELSE completed_at END,
                 id                 = LAST_INSERT_ID(id)""",
            (
                tenant_id,
                raf_patient_id,
                pull_id,
                submitted_at or datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
                status,
                json.dumps(resources_returned or {}),
                bundle_size_bytes,
                (error_text or "")[:2000] or None,
            ),
        )
        cur.execute("SELECT LAST_INSERT_ID() AS lid")
        row = cur.fetchone()
        return int(row["lid"] if isinstance(row, dict) else row[0])


# ---------------------------------------------------------------------------
# Condition → suspect
# ---------------------------------------------------------------------------

def _condition_to_suspect(
    tenant_id: str,
    raf_patient_id: int,
    measurement_year: int,
    resource: dict[str, Any],
) -> int | None:
    """Cross-walk a FHIR Condition to HCC and insert an open suspect.

    Returns the inserted/existing suspect id, or None on failure.
    """
    codings = (
        resource.get("code", {}).get("coding") or []
    )
    icd10 = next(
        (
            c["code"]
            for c in codings
            if c.get("system", "").rstrip("/") == _ICD10_SYSTEM.rstrip("/")
            and c.get("code")
        ),
        None,
    )
    if not icd10:
        return None

    hcc_info = lookup_hcc(icd10)
    if not hcc_info["maps_to_hcc"]:
        logger.debug("inovalon_ingest: ICD %s has no HCC mapping, skipping", icd10)
        return None

    hcc_code = hcc_info["hcc_codes"][0]  # primary CC mapping
    evidence_detail = json.dumps(
        {
            "source": "inovalon_erond",
            "icd10": icd10,
            "hcc": hcc_code,
            "label": (hcc_info["hcc_details"][0].get("label") if hcc_info["hcc_details"] else None),
        }
    )

    with raf_cursor() as cur:
        # Dedup: same tenant/patient/year/hcc/icd/open
        cur.execute(
            """SELECT id FROM raf_suspect_conditions
               WHERE tenant_id=%s AND patient_id=%s AND measurement_year=%s
                 AND suspect_hcc=%s AND suspect_icd10=%s AND status='open'
               LIMIT 1""",
            (tenant_id, raf_patient_id, measurement_year, int(hcc_code), icd10),
        )
        row = cur.fetchone()
        if row:
            return int(row["id"] if isinstance(row, dict) else row[0])

        cur.execute(
            """INSERT INTO raf_suspect_conditions
                 (tenant_id, patient_id, measurement_year, suspect_hcc,
                  suspect_icd10, evidence_type, evidence_detail,
                  confidence_score, status)
               VALUES (%s,%s,%s,%s,%s,'historical',%s,0.80,'open')""",
            (
                tenant_id,
                raf_patient_id,
                measurement_year,
                int(hcc_code),
                icd10,
                evidence_detail,
            ),
        )
        return int(cur.lastrowid)


# ---------------------------------------------------------------------------
# DocumentReference → Gemini vision
# ---------------------------------------------------------------------------

def _route_document_ref(
    tenant_id: str,
    raf_patient_id: int,
    client: Any,  # InovalonClient
    resource: dict[str, Any],
) -> bool:
    """Fetch the binary attachment and route bytes to the Gemini vision pipeline.

    Returns True when the Gemini call was dispatched without error.
    """
    contents = resource.get("content") or []
    url: str | None = None
    for c in contents:
        url = (c.get("attachment") or {}).get("url")
        if url:
            break
    if not url:
        logger.debug("inovalon_ingest: DocumentReference has no attachment URL")
        return False

    try:
        doc_bytes, content_type = client.fetch_binary(url)
    except Exception as exc:
        logger.warning("inovalon_ingest: binary fetch failed url=%s: %s", url, exc)
        return False

    from app.services.gemini_document_extractor import extract_from_document  # noqa: PLC0415

    result = extract_from_document(
        doc_bytes=doc_bytes,
        mime_type=content_type.split(";")[0].strip(),
        year=date.today().year,
        document_filename=resource.get("id", "inovalon_doc"),
        tenant_id=tenant_id,
    )
    suspects = result.get("suspects") or []
    logger.info(
        "inovalon_ingest: gemini vision returned %d suspects for patient %d",
        len(suspects),
        raf_patient_id,
    )
    return True


# ---------------------------------------------------------------------------
# Observation → raf_external_observations
# ---------------------------------------------------------------------------

def _store_observation(
    tenant_id: str,
    raf_patient_id: int,
    resource: dict[str, Any],
) -> bool:
    """Persist a FHIR Observation (LOINC lab) to raf_external_observations.

    Returns True on successful insert/dedup.
    """
    codings = (resource.get("code", {}).get("coding") or [])
    loinc_code = next(
        (
            c["code"]
            for c in codings
            if c.get("system", "").rstrip("/") == _LOINC_SYSTEM.rstrip("/")
            and c.get("code")
        ),
        None,
    )
    if not loinc_code:
        return False

    # Numeric value
    value_q = resource.get("valueQuantity") or {}
    value_numeric = value_q.get("value")
    units = (value_q.get("unit") or value_q.get("code") or "")[:32]
    value_text = None
    if value_numeric is None:
        value_text = str(resource.get("valueString") or "")[:500] or None

    observed_at = (
        resource.get("effectiveDateTime")
        or resource.get("effectiveInstant")
        or datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    )[:19]  # truncate to YYYY-MM-DD HH:MM:SS

    try:
        with raf_cursor() as cur:
            cur.execute(
                """INSERT INTO raf_external_observations
                     (tenant_id, raf_patient_id, loinc_code,
                      value_numeric, value_text, units, observed_at, source)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,'inovalon_erond')
                   ON DUPLICATE KEY UPDATE
                     value_numeric = VALUES(value_numeric),
                     value_text    = VALUES(value_text),
                     units         = VALUES(units)""",
                (
                    tenant_id,
                    raf_patient_id,
                    loinc_code,
                    value_numeric,
                    value_text,
                    units or None,
                    observed_at,
                ),
            )
        return True
    except Exception as exc:
        logger.warning(
            "inovalon_ingest: observation insert failed loinc=%s: %s",
            loinc_code, exc,
        )
        return False


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def ingest_patient_from_inovalon(
    tenant_id: str,
    raf_patient_id: int,
    sections: tuple[str, ...] | list[str] | None = None,
    measurement_year: int | None = None,
) -> dict[str, Any]:
    """Run the full Inovalon EROND ingestion pipeline for one patient.

    Idempotent — if this ``inovalon_pull_id`` already exists in
    ``inovalon_patient_pulls`` the function returns immediately with
    ``status: skipped``.

    Args:
        tenant_id: RAF tenant identifier.
        raf_patient_id: Primary key in ``raf_patients``.
        sections: Inovalon data sections to request.  Defaults to the
            five standard sections (conditions, medications, observations,
            encounters, documents).
        measurement_year: HCC measurement year.  Defaults to current year.

    Returns:
        Summary dict with keys ``pull_id``, ``status``, ``suspects_created``,
        ``docs_routed``, ``observations_stored``, and ``error`` (if any).
    """
    year = measurement_year or date.today().year
    _sections = sections or (
        "conditions", "medications", "observations", "encounters", "documents"
    )

    client = InovalonClient()
    if not client.is_configured:
        return {
            "pull_id": None,
            "status": "error",
            "suspects_created": 0,
            "docs_routed": 0,
            "observations_stored": 0,
            "error": "Inovalon credentials not configured",
        }

    # 1. Fetch demographics
    demographics = _get_patient_demographics(raf_patient_id)
    if not demographics:
        return {
            "pull_id": None,
            "status": "error",
            "suspects_created": 0,
            "docs_routed": 0,
            "observations_stored": 0,
            "error": f"Patient {raf_patient_id} not found",
        }

    # Build the demographics payload Inovalon expects
    demo_payload: dict[str, Any] = {
        "first_name": demographics.get("first_name") or "",
        "last_name": demographics.get("last_name") or "",
        "dob": str(demographics.get("date_of_birth") or ""),
        "gender": demographics.get("gender") or "",
        "member_id": str(demographics.get("member_id") or ""),
    }

    # 2. Submit pull
    try:
        pull_resp = client.pull_patient_record(demo_payload, sections=_sections)
    except Exception as exc:
        logger.error(
            "inovalon_ingest: pull request failed tenant=%s patient=%d: %s",
            tenant_id, raf_patient_id, exc,
        )
        return {
            "pull_id": None,
            "status": "error",
            "suspects_created": 0,
            "docs_routed": 0,
            "observations_stored": 0,
            "error": str(exc)[:500],
        }

    pull_id: str = pull_resp["pull_id"]
    submitted_at: str = pull_resp.get("submitted_at", "")

    # 3. Idempotency check — if pull_id already in DB, skip
    with raf_cursor() as cur:
        cur.execute(
            "SELECT id FROM inovalon_patient_pulls WHERE inovalon_pull_id=%s LIMIT 1",
            (pull_id,),
        )
        existing = cur.fetchone()
    if existing:
        logger.info(
            "inovalon_ingest: pull_id=%s already processed, skipping", pull_id
        )
        return {
            "pull_id": pull_id,
            "status": "skipped",
            "suspects_created": 0,
            "docs_routed": 0,
            "observations_stored": 0,
        }

    # 4. Persist initial pull record
    _upsert_pull_record(
        tenant_id=tenant_id,
        raf_patient_id=raf_patient_id,
        pull_id=pull_id,
        status=pull_resp.get("status", "submitted"),
        submitted_at=submitted_at,
    )

    # 5. Poll for completion (sync, best-effort for the initial call;
    #    production callers may prefer async polling via a Celery task)
    try:
        status_resp = client.get_pull_status(pull_id)
        pull_status = status_resp.get("status", "submitted")
        resources_returned = status_resp.get("resources_returned", {})
        bundle_size_bytes = status_resp.get("bundle_size_bytes", 0)
        _upsert_pull_record(
            tenant_id=tenant_id,
            raf_patient_id=raf_patient_id,
            pull_id=pull_id,
            status=pull_status,
            submitted_at=submitted_at,
            resources_returned=resources_returned,
            bundle_size_bytes=bundle_size_bytes,
        )
    except Exception as exc:
        logger.warning(
            "inovalon_ingest: pull status poll failed pull_id=%s: %s", pull_id, exc
        )
        pull_status = "submitted"
        resources_returned = {}
        bundle_size_bytes = 0

    # If not yet completed we return early — the caller can re-invoke later
    # or a Celery task can pick it up.
    if pull_status not in ("completed",):
        return {
            "pull_id": pull_id,
            "status": pull_status,
            "suspects_created": 0,
            "docs_routed": 0,
            "observations_stored": 0,
        }

    # 6. Download the FHIR Bundle (NDJSON)
    try:
        ndjson_bytes = client.download_bundle(pull_id)
    except Exception as exc:
        logger.error(
            "inovalon_ingest: bundle download failed pull_id=%s: %s", pull_id, exc
        )
        _upsert_pull_record(
            tenant_id=tenant_id,
            raf_patient_id=raf_patient_id,
            pull_id=pull_id,
            status="failed",
            submitted_at=submitted_at,
            error_text=str(exc),
        )
        return {
            "pull_id": pull_id,
            "status": "failed",
            "suspects_created": 0,
            "docs_routed": 0,
            "observations_stored": 0,
            "error": str(exc)[:500],
        }

    # 7. Parse NDJSON and route resources
    suspects_created = 0
    docs_routed = 0
    observations_stored = 0

    for line in ndjson_bytes.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            resource: dict[str, Any] = json.loads(line)
        except json.JSONDecodeError:
            continue

        resource_type = resource.get("resourceType", "")

        if resource_type == "Condition":
            sid = _condition_to_suspect(
                tenant_id=tenant_id,
                raf_patient_id=raf_patient_id,
                measurement_year=year,
                resource=resource,
            )
            if sid:
                suspects_created += 1

        elif resource_type == "DocumentReference":
            ok = _route_document_ref(
                tenant_id=tenant_id,
                raf_patient_id=raf_patient_id,
                client=client,
                resource=resource,
            )
            if ok:
                docs_routed += 1

        elif resource_type == "Observation":
            ok = _store_observation(
                tenant_id=tenant_id,
                raf_patient_id=raf_patient_id,
                resource=resource,
            )
            if ok:
                observations_stored += 1

    # 8. Update pull record with final counts
    _upsert_pull_record(
        tenant_id=tenant_id,
        raf_patient_id=raf_patient_id,
        pull_id=pull_id,
        status="completed",
        submitted_at=submitted_at,
        resources_returned={
            **(resources_returned or {}),
            "suspects_created": suspects_created,
            "docs_routed": docs_routed,
            "observations_stored": observations_stored,
        },
        bundle_size_bytes=bundle_size_bytes or len(ndjson_bytes),
    )

    logger.info(
        "inovalon_ingest: completed tenant=%s patient=%d pull=%s "
        "suspects=%d docs=%d obs=%d",
        tenant_id, raf_patient_id, pull_id,
        suspects_created, docs_routed, observations_stored,
    )

    return {
        "pull_id": pull_id,
        "status": "completed",
        "suspects_created": suspects_created,
        "docs_routed": docs_routed,
        "observations_stored": observations_stored,
    }
