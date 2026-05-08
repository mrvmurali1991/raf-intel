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
4.  Pull active problems from openemr.lists (type='medical_problem') and
    upsert ICD-10-bearing rows into raf_intelligence.raf_suspect_conditions.
5.  Log every step with structured logger keys:
      auto_sync.check, auto_sync.synced, auto_sync.encounter_upsert,
      auto_sync.condition_upsert, auto_sync.error
6.  Catch *all* exceptions and return None on error with full traceback logged.
"""
from __future__ import annotations

import logging
import traceback
from datetime import date
from typing import Optional

from app.db import openemr_cursor, raf_cursor

logger = logging.getLogger(__name__)

# ── helpers ──────────────────────────────────────────────────────────────────

def _current_year() -> int:
    return date.today().year


def _check_local_patient(emr_pid: int) -> Optional[int]:
    """Return local RAF patient id if *emr_pid* exists in the patients VIEW, else None."""
    with raf_cursor() as cur:
        cur.execute(
            "SELECT id FROM patients WHERE emr_pid = %s LIMIT 1",
            (str(emr_pid),),
        )
        row = cur.fetchone()
    return int(row["id"]) if row else None


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
            enc_id = f"EMR_{emr_pid}_enc_{r['encounter_id']}"
            enc_date = r["encounter_date"]
            if hasattr(enc_date, "date"):
                enc_date = enc_date.date()
            cur.execute(
                """
                INSERT IGNORE INTO normalized_encounters
                    (encounter_id, patient_id, tenant_id, encounter_date,
                     encounter_type, facility_name)
                VALUES (%s, %s, '1', %s, 'office_visit', %s)
                """,
                (enc_id, local_pid, str(enc_date), r["facility_name"] or None),
            )
            upserted += cur.rowcount

    logger.info(
        "auto_sync.encounter_upsert",
        extra={"emr_pid": emr_pid, "local_pid": local_pid, "upserted": upserted},
    )
    return upserted


def _sync_conditions(local_pid: int, emr_pid: int) -> int:
    """
    Pull active medical problems from openemr.lists and upsert ICD-10-bearing
    rows into raf_intelligence.raf_suspect_conditions.

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

    upserted = 0
    measurement_year = _current_year()

    with raf_cursor() as cur:
        for r in rows:
            raw = (r.get("icd10_raw") or "").strip()
            # OpenEMR stores codes as "ICD10:F32.1" or bare "F32.1"
            icd10 = raw.replace("ICD10:", "").replace("SNOMED:", "").strip()
            if not icd10:
                continue
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
                    (%s, %s, 0, %s,
                     'historical',
                     JSON_OBJECT('source', 'openemr_problems',
                                 'diagnosis', %s),
                     0.7000,
                     'open', '1')
                """,
                (local_pid, measurement_year, icd10, r.get("diagnosis", "")),
            )
            upserted += cur.rowcount

    logger.info(
        "auto_sync.condition_upsert",
        extra={"emr_pid": emr_pid, "local_pid": local_pid, "upserted": upserted},
    )
    return upserted


# ── public API ────────────────────────────────────────────────────────────────

def sync_patient_from_openemr(emr_pid: int) -> Optional[int]:
    """
    Pull one OpenEMR patient into RAF and return the local RAF patient_id.

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
            # Patient already present in the VIEW — still sync child records
            # so repeated calls are fully idempotent at every layer.
            logger.info(
                "auto_sync.synced",
                extra={"emr_pid": emr_pid, "local_pid": local_pid, "action": "existing"},
            )
        else:
            # pid not in openemr.patient_data → not exposed by VIEW
            logger.info(
                "auto_sync.not_found",
                extra={"emr_pid": emr_pid},
            )
            return None

        _sync_encounters(local_pid, emr_pid)
        _sync_conditions(local_pid, emr_pid)

        logger.info(
            "auto_sync.synced",
            extra={"emr_pid": emr_pid, "local_pid": local_pid, "action": "complete"},
        )
        return local_pid

    except Exception:  # noqa: BLE001
        logger.error(
            "auto_sync.error",
            extra={"emr_pid": emr_pid},
            exc_info=True,
        )
        logger.debug("auto_sync.traceback emr_pid=%s\n%s", emr_pid, traceback.format_exc())
        return None
