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
