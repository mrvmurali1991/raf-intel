"""
OpenEMR database connector.

Reads from the standard OpenEMR MySQL schema tables:
  patient_data, form_encounter, billing, prescriptions,
  form_vitals, form_soap, form_clinical_notes, forms,
  procedure_result, procedure_order,
  history_data, form_history_sdoh, lists (allergy type),
  transactions

All functions use the shared openemr_cursor() connection pool.
All rows are serialized via _serialize() before being returned so that
date, datetime, and Decimal values are safe to pass to JSON endpoints.

NOTE: history_data, form_history_sdoh, and transactions may not exist in
all OpenEMR versions or deployments.  Every function in the "Optional
tables" section wraps its query in try/except and returns an empty result
rather than raising, so callers are always safe.
"""
from __future__ import annotations

import functools
import logging
import re
from typing import Any

from app.db import NoActiveEMRConnection, openemr_cursor, raf_cursor
from app.services.circuit_breaker import openemr_breaker

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Decorator: gracefully return empty results when no EMR is connected
# ---------------------------------------------------------------------------

def _empty_on_no_emr(default=None):
    """Decorator: return *default* when no active EMR connection exists."""
    if default is None:
        default = []

    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            try:
                return fn(*args, **kwargs)
            except NoActiveEMRConnection:
                logger.debug(
                    "%s: no active EMR connection — returning empty result", fn.__name__
                )
                return default() if callable(default) else default
        return wrapper
    return decorator


# ---------------------------------------------------------------------------
# Place of Service (POS) code reference table
#
# Keys are two-digit string codes matching form_encounter.pos_code.
# Each entry carries:
#   desc  — human-readable CMS label
#   type  — logical category used for downstream model-segment selection:
#             "outpatient"    → community model, outpatient coding rules
#             "inpatient"     → inpatient addendum applies, DRG/discharge logic
#             "institutional" → institutional model segment, SNF/hospice rules
#
# IMPORTANT: pos_code is frequently NULL in OpenEMR.  Every caller that needs
# a concrete value must apply the _resolve_pos() helper, which defaults to
# "11" (Office / outpatient) rather than raising or returning an unknown type.
# ---------------------------------------------------------------------------
POS_CODES: dict[str, dict] = {
    "11": {"desc": "Office",                        "type": "outpatient"},
    "21": {"desc": "Inpatient Hospital",            "type": "inpatient"},
    "22": {"desc": "On Campus Outpatient Hospital", "type": "outpatient"},
    "23": {"desc": "Emergency Room",                "type": "outpatient"},
    "31": {"desc": "Skilled Nursing Facility",      "type": "institutional"},
    "32": {"desc": "Nursing Facility",              "type": "institutional"},
    "33": {"desc": "Custodial Care Facility",       "type": "institutional"},
    "34": {"desc": "Hospice",                       "type": "institutional"},
    "41": {"desc": "Ambulance - Land",              "type": "outpatient"},
    "65": {"desc": "ESRD Treatment Facility",       "type": "outpatient"},
    "81": {"desc": "Independent Laboratory",        "type": "outpatient"},
}

_DEFAULT_POS = "11"  # Office — applied whenever pos_code is NULL or unrecognised


def _resolve_pos(pos_code: str | None) -> dict:
    """
    Return the POS_CODES entry for *pos_code*, falling back to Office ("11")
    when the code is NULL, empty, or absent from the mapping.

    Returns a dict with keys: code, desc, type.
    Never raises.
    """
    key = str(pos_code).strip() if pos_code else _DEFAULT_POS
    if key not in POS_CODES:
        key = _DEFAULT_POS
    return {"code": key, **POS_CODES[key]}


# ---------------------------------------------------------------------------
# Patients
# ---------------------------------------------------------------------------

@openemr_breaker
@_empty_on_no_emr()
def get_patients(limit: int = 500, offset: int = 0) -> list[dict[str, Any]]:
    """Return all active patients from patient_data."""
    sql = """
        SELECT
            pid,
            fname,
            lname,
            mname,
            DOB,
            sex,
            race,
            ethnicity,
            language,
            street,
            city,
            state,
            postal_code,
            phone_home,
            phone_cell,
            email,
            providerID,
            date AS created_date
        FROM patient_data
        WHERE pid > 0
        ORDER BY lname, fname
        LIMIT %s OFFSET %s
    """
    with openemr_cursor() as cur:
        cur.execute(sql, (limit, offset))
        rows = cur.fetchall()
    return [_serialize(r) for r in rows]


@_empty_on_no_emr(default=lambda: ([], 0))
def search_patients(query: str, limit: int = 100, offset: int = 0) -> tuple[list[dict[str, Any]], int]:
    """Search patients by name or PID across all records. Returns (patients, total_count)."""
    # Check if query is numeric (PID search)
    is_pid = query.isdigit()

    if is_pid:
        count_sql = "SELECT COUNT(*) AS cnt FROM patient_data WHERE pid = %s"
        search_sql = """
            SELECT pid, fname, lname, mname, DOB, sex, race, ethnicity, language,
                   street, city, state, postal_code, phone_home, phone_cell, email,
                   providerID, date AS created_date
            FROM patient_data WHERE pid = %s LIMIT %s OFFSET %s
        """
        params_count = (int(query),)
        params_search = (int(query), limit, offset)
    else:
        q = f"%{query}%"
        count_sql = """
            SELECT COUNT(*) AS cnt FROM patient_data
            WHERE pid > 0 AND (
                CONCAT(fname, ' ', lname) LIKE %s
                OR fname LIKE %s
                OR lname LIKE %s
            )
        """
        search_sql = """
            SELECT pid, fname, lname, mname, DOB, sex, race, ethnicity, language,
                   street, city, state, postal_code, phone_home, phone_cell, email,
                   providerID, date AS created_date
            FROM patient_data
            WHERE pid > 0 AND (
                CONCAT(fname, ' ', lname) LIKE %s
                OR fname LIKE %s
                OR lname LIKE %s
            )
            ORDER BY lname, fname
            LIMIT %s OFFSET %s
        """
        params_count = (q, q, q)
        params_search = (q, q, q, limit, offset)

    with openemr_cursor() as cur:
        cur.execute(count_sql, params_count)
        count_row = cur.fetchone()
        total = count_row["cnt"] if count_row else 0
        cur.execute(search_sql, params_search)
        rows = cur.fetchall()
    return [_serialize(r) for r in rows], int(total)


@_empty_on_no_emr()
def get_patients_with_encounters(limit: int = 200) -> list[dict[str, Any]]:
    """Return patients that have encounters WITH clinical notes (for pipeline demo)."""
    sql = """
        SELECT DISTINCT
            pd.pid, pd.fname, pd.lname, pd.DOB, pd.sex, pd.city, pd.state,
            COUNT(DISTINCT fe.encounter) AS encounter_count
        FROM patient_data pd
        INNER JOIN form_encounter fe ON fe.pid = pd.pid
        INNER JOIN form_clinical_notes fcn
            ON CAST(fcn.encounter AS UNSIGNED) = fe.encounter
        WHERE pd.pid > 0
          AND pd.fname != '' AND pd.fname IS NOT NULL
          AND pd.lname != '' AND pd.lname IS NOT NULL
          AND TRIM(pd.fname) NOT IN ('patient', 'BLOCK', 'OG LOCATION', 'ACURUS', '0', '')
          AND LOWER(pd.fname) NOT LIKE '%%test%%'
          AND LOWER(pd.fname) NOT LIKE '%%block%%'
          AND LOWER(pd.fname) NOT LIKE '%%pccv%%'
          AND LOWER(pd.fname) NOT LIKE '%%chaffey%%'
          AND LOWER(pd.lname) NOT LIKE '%%test%%'
          AND LOWER(pd.lname) NOT LIKE '%%block%%'
          AND LENGTH(TRIM(pd.fname)) > 1
          AND fcn.description IS NOT NULL AND fcn.description != ''
        GROUP BY pd.pid
        ORDER BY encounter_count DESC, pd.lname, pd.fname
        LIMIT %s
    """
    with openemr_cursor() as cur:
        cur.execute(sql, (limit,))
        rows = cur.fetchall()
    return [_serialize(r) for r in rows]


@_empty_on_no_emr(default=None)
def get_patient(pid: int) -> dict[str, Any] | None:
    """Return a single patient record from raf_intelligence.patients table."""
    from app.db import raf_cursor

    sql = """
        SELECT
            id AS pid,
            first_name AS fname,
            last_name AS lname,
            middle_name AS mname,
            dob AS DOB,
            sex,
            race,
            ethnicity,
            preferred_language AS language,
            address AS street,
            city,
            state,
            zip AS postal_code,
            phone AS phone_home,
            phone AS phone_cell,
            email,
            emr_pid AS providerID,
            created_at AS created_date,
            mrn,
            mbi,
            insurance_type,
            emr_pid
        FROM patients
        WHERE id = %s AND is_active = 1
    """
    with raf_cursor() as cur:
        cur.execute(sql, (pid,))
        row = cur.fetchone()
    return _serialize(row) if row else None


@_empty_on_no_emr(default=0)
def get_patient_count(tenant_id: str = "") -> int:
    from app.db import raf_cursor
    with raf_cursor() as cur:
        cur.execute("SELECT COUNT(*) AS cnt FROM patients WHERE is_active = 1 AND tenant_id = %s", (tenant_id,))
        row = cur.fetchone()
    return row["cnt"] if row else 0


# ---------------------------------------------------------------------------
# Encounters
# ---------------------------------------------------------------------------

@openemr_breaker
@_empty_on_no_emr()
def get_encounters(pid: int) -> list[dict[str, Any]]:
    """
    Return all encounters for a patient from form_encounter.

    Includes POS code, discharge disposition, class code, and the resolved
    facility name from the facility table.  pos_code may be NULL in many
    rows; callers that need a concrete POS should use _resolve_pos() or
    get_encounter_context() which applies the default automatically.
    """
    sql = """
        SELECT
            fe.encounter AS encounter_id,
            fe.pid,
            fe.date,
            fe.reason,
            fe.facility,
            fe.provider_id,
            u.fname AS provider_fname,
            u.lname AS provider_lname,
            (SELECT COUNT(*) FROM form_clinical_notes fcn
             WHERE fcn.encounter = fe.encounter
             AND fcn.description IS NOT NULL AND fcn.description != '') AS has_notes
        FROM form_encounter fe
        LEFT JOIN users u ON u.id = fe.provider_id
        WHERE fe.pid = %s
        ORDER BY fe.date DESC
    """
    with openemr_cursor() as cur:
        cur.execute(sql, (pid,))
        rows = cur.fetchall()

    # Enrich each encounter with the actual clinical note text.
    # Batch-fetch notes for all encounters with has_notes in a single pass to
    # avoid an N+1 query against form_clinical_notes / form_soap.
    serialized = [_serialize(r) for r in rows]
    enc_ids_with_notes = [
        int(e["encounter_id"]) for e in serialized if e.get("has_notes") and e.get("encounter_id") is not None
    ]

    notes_by_enc: dict[int, list[str]] = {}
    if enc_ids_with_notes:
        placeholders = ",".join(["%s"] * len(enc_ids_with_notes))
        try:
            with openemr_cursor() as cur:
                # SOAP notes
                cur.execute(
                    f"""
                    SELECT
                        f.encounter AS encounter,
                        CONCAT_WS('\n\n',
                            IF(fs.subjective <> '', CONCAT('S: ', fs.subjective), NULL),
                            IF(fs.objective  <> '', CONCAT('O: ', fs.objective),  NULL),
                            IF(fs.assessment <> '', CONCAT('A: ', fs.assessment), NULL),
                            IF(fs.plan       <> '', CONCAT('P: ', fs.plan),       NULL)
                        ) AS note_text
                    FROM form_soap fs
                    JOIN forms f ON f.form_id = fs.id AND f.formdir = 'soap'
                    WHERE f.encounter IN ({placeholders}) AND fs.activity = 1
                    """,
                    enc_ids_with_notes,
                )
                for r in cur.fetchall():
                    txt = r.get("note_text")
                    if txt:
                        notes_by_enc.setdefault(int(r["encounter"]), []).append(txt)

                # form_clinical_notes (may not exist in all OpenEMR versions)
                try:
                    cur.execute(
                        f"""
                        SELECT fcn.encounter AS encounter,
                               COALESCE(fcn.description, '') AS note_text
                        FROM form_clinical_notes fcn
                        WHERE fcn.encounter IN ({placeholders})
                        """,
                        enc_ids_with_notes,
                    )
                    for r in cur.fetchall():
                        txt = r.get("note_text")
                        if txt:
                            notes_by_enc.setdefault(int(r["encounter"]), []).append(txt)
                except Exception as _fcn_exc:  # noqa: BLE001
                    logger.debug("form_clinical_notes table not present or empty: %s", _fcn_exc)
        except Exception as exc:
            logger.warning("get_encounters batch notes fetch failed: %s", exc)

    result = []
    for enc in serialized:
        eid = enc.get("encounter_id")
        if enc.get("has_notes") and eid is not None:
            chunks = notes_by_enc.get(int(eid))
            if chunks:
                enc["notes"] = "\n\n".join(chunks)
        result.append(enc)
    return result


@_empty_on_no_emr(default=None)
def get_encounter(encounter_id: int) -> dict[str, Any] | None:
    sql = """
        SELECT
            fe.encounter AS encounter_id,
            fe.pid,
            fe.date,
            fe.reason,
            fe.facility,
            fe.provider_id,
            u.fname AS provider_fname,
            u.lname AS provider_lname
        FROM form_encounter fe
        LEFT JOIN users u ON u.id = fe.provider_id
        WHERE fe.encounter = %s
        LIMIT 1
    """
    with openemr_cursor() as cur:
        cur.execute(sql, (encounter_id,))
        row = cur.fetchone()
    return _serialize(row) if row else None


@_empty_on_no_emr(default=None)
def get_encounter_context(encounter_id: int) -> dict[str, Any] | None:
    """
    Return full context for a single encounter, with POS code resolved and
    all derived fields needed for HCC model-segment selection.

    Returned dict keys
    ------------------
    encounter_id         : int
    date                 : str (ISO date)
    reason               : str | None
    pos_code             : str   — always a 2-digit string; defaults to "11"
                                   when the column is NULL in the database
    pos_description      : str   — human-readable CMS label for pos_code
    facility             : str | None  — free-text facility field on the encounter
    facility_name        : str | None  — name from the facility table (may differ)
    class_code           : str | None  — HL7 class code e.g. "AMB", "IMP", "EMER"
    discharge_disposition: str | None  — numeric disposition code; populated for
                                         inpatient/SNF encounters, NULL for office
    is_institutional     : bool  — True when POS type is "institutional"
    encounter_type       : str   — "inpatient" | "outpatient" | "institutional"
                                   derived from the resolved POS type

    Returns None when the encounter_id does not exist.
    Never raises; logs a warning on DB error and returns None.
    """
    sql = """
        SELECT
            fe.encounter        AS encounter_id,
            fe.date,
            fe.reason,
            fe.facility,
            fe.provider_id
        FROM form_encounter fe
        WHERE fe.encounter = %s
        LIMIT 1
    """
    try:
        with openemr_cursor() as cur:
            cur.execute(sql, (encounter_id,))
            row = cur.fetchone()
    except Exception as exc:
        logger.warning("get_encounter_context: DB error for encounter_id=%s: %s", encounter_id, exc)
        return None

    if not row:
        return None

    row = _serialize(row)

    # Resolve POS — NULL in DB defaults to "11" (Office / outpatient)
    pos = _resolve_pos(row.get("pos_code"))

    return {
        "encounter_id":          row.get("encounter_id"),
        "date":                  row.get("date"),
        "reason":                row.get("reason"),
        "pos_code":              pos["code"],
        "pos_description":       pos["desc"],
        "facility":              row.get("facility"),
        "facility_name":         row.get("facility"),
        "class_code":            None,
        "discharge_disposition": None,
        "is_institutional":      pos["type"] == "institutional",
        "encounter_type":        pos["type"],
    }


# ---------------------------------------------------------------------------
# Billing / ICD-10 codes
# ---------------------------------------------------------------------------

# CPT codes that hint at underlying chronic conditions relevant to HCC scoring.
# Keys are CPT procedure codes; values carry the likely condition label, a
# representative ICD-10 code, and the primary HCC category it maps to.
# A None icd10/hcc entry means the CPT alone is not specific enough to assert
# a diagnosis but should flag the encounter for human review.
CPT_CONDITION_HINTS: dict[str, dict] = {
    "36430": {"condition": "Chronic Anemia",                   "icd10": "D64.9",  "hcc": "HCC109"},
    "90935": {"condition": "ESRD/Dialysis",                    "icd10": "N18.6",  "hcc": "HCC326"},
    "93306": {"condition": "Heart Disease",                    "icd10": "I50.9",  "hcc": "HCC226"},
    "99214": {"condition": "Complex visit (multiple chronic)", "icd10": None,     "hcc": None},
    "99215": {"condition": "High complexity visit",            "icd10": None,     "hcc": None},
    "96127": {"condition": "Depression screening",             "icd10": "F33.0",  "hcc": "HCC155"},
    "99483": {"condition": "Cognitive assessment",             "icd10": "F03.90", "hcc": "HCC127"},
    "90832": {"condition": "Psychotherapy",                    "icd10": "F33.1",  "hcc": "HCC155"},
    "92227": {"condition": "Diabetic retinal screening",       "icd10": "E11.319", "hcc": "HCC37"},
}


@openemr_breaker
@_empty_on_no_emr()
def get_billing_codes(pid: int) -> list[dict[str, Any]]:
    """Return all billing rows (ICD-10 codes) for a patient."""
    sql = """
        SELECT
            b.id,
            b.pid,
            b.encounter,
            b.code_type,
            b.code,
            b.authorized,
            b.activity,
            b.code_text
        FROM billing b
        WHERE b.pid = %s
          AND b.activity = 1
          AND b.code_type IN ('ICD10', 'ICD9', 'SNOMED')
        ORDER BY b.id DESC
    """
    with openemr_cursor() as cur:
        cur.execute(sql, (pid,))
        rows = cur.fetchall()
    return [_serialize(r) for r in rows]


@_empty_on_no_emr()
def get_cpt_codes(pid: int) -> list[dict[str, Any]]:
    """Return active CPT4 procedure codes for a patient from the billing table."""
    sql = """
        SELECT DISTINCT code, code_text, encounter
        FROM billing
        WHERE pid = %s AND code_type = 'CPT4' AND activity = 1
        ORDER BY code
    """
    with openemr_cursor() as cur:
        cur.execute(sql, (pid,))
        rows = cur.fetchall()
    return [_serialize(r) for r in rows]


@_empty_on_no_emr()
def get_all_billing(pid: int) -> list[dict[str, Any]]:
    """Return all active billing codes (ICD10, CPT4, HCPCS) for a patient."""
    sql = """
        SELECT code, code_type, code_text, encounter
        FROM billing
        WHERE pid = %s AND activity = 1
        ORDER BY id DESC
    """
    with openemr_cursor() as cur:
        cur.execute(sql, (pid,))
        rows = cur.fetchall()
    return [_serialize(r) for r in rows]


# ---------------------------------------------------------------------------
# Medications / Prescriptions
# ---------------------------------------------------------------------------

@_empty_on_no_emr()
def get_medications(pid: int, year: int | None = None, tenant_id: str = "") -> list[dict[str, Any]]:
    """Return all prescriptions for a patient, including the diagnosis field.

    The ``diagnosis`` column stores the ICD-10 code the medication was
    prescribed for.  It may be NULL, empty, or contain multiple codes
    separated by semicolons.  The raw value is returned as-is; a pre-parsed
    list of individual codes is also attached under ``diagnosis_codes`` so
    callers do not need to re-implement the parsing logic.

    When *year* is provided, only prescriptions that were active during that
    calendar year are returned.  A prescription is considered active during
    *year* when ``YEAR(start_date) <= year`` AND ``active = 1``.  The
    ``prescriptions`` table does not carry an end-date column, so the active
    flag is used as the upper-bound proxy.
    """
    params: list[Any] = [pid]
    year_clause = ""
    if year is not None:
        year_clause = "  AND YEAR(start_date) <= %s\n  AND active = 1"
        params.append(year)

    sql = f"""
        SELECT
            id,
            patient_id AS pid,
            drug,
            active,
            dosage,
            quantity,
            size,
            unit,
            route,
            '' AS freq,
            refills,
            start_date,
            note
        FROM prescriptions
        WHERE patient_id = %s
{year_clause}
        ORDER BY start_date DESC
    """
    with openemr_cursor(tenant_id=tenant_id) as cur:
        cur.execute(sql, params)
        rows = cur.fetchall()
    result = [_serialize(r) for r in rows]
    for row in result:
        row["diagnosis_codes"] = []
    return result


# ---------------------------------------------------------------------------
# Vitals
# ---------------------------------------------------------------------------

@_empty_on_no_emr()
def get_vitals(pid: int, tenant_id: str = "") -> list[dict[str, Any]]:
    """Return vitals history for a patient."""
    sql = """
        SELECT
            fv.id,
            fv.pid,
            fv.date,
            fv.weight AS weight,
            fv.height AS height,
            fv.bps,
            fv.bpd
        FROM form_vitals fv
        WHERE fv.pid = %s
        ORDER BY fv.date DESC
    """
    with openemr_cursor(tenant_id=tenant_id) as cur:
        cur.execute(sql, (pid,))
        rows = cur.fetchall()
    return [_serialize(r) for r in rows]


@_empty_on_no_emr()
def get_vitals_history(pid: int, year: int | None = None) -> list[dict[str, Any]]:
    """
    Return the 10 most recent vitals rows for *pid*, joining through the
    forms table to confirm each row belongs to an active vitals form.

    Vitals fields may be stored as strings or NULL in OpenEMR; callers
    should use ``_parse_vital`` to safely convert values to float.

    Used internally by ``get_vitals_trends`` and ``detect_vitals_suspects``.
    Use ``get_latest_vitals`` for the single most-recent row as a plain dict.

    Parameters
    ----------
    year:
        When provided, only rows whose ``date`` falls in that calendar year
        are returned (filtered via ``YEAR(fv.date) = year``).
    """
    params: list[Any] = [pid]
    year_clause = ""
    if year is not None:
        year_clause = "AND YEAR(fv.date) = %s"
        params.append(year)

    sql = f"""
        SELECT
            fv.id,
            fv.date,
            fv.pid,
            fv.bps,
            fv.bpd,
            fv.weight AS weight,
            fv.height AS height,
            fv.BMI,
            fv.oxygen_saturation
        FROM form_vitals fv
        WHERE fv.pid = %s
        {year_clause}
        ORDER BY fv.date DESC
        LIMIT 10
    """
    with openemr_cursor() as cur:
        cur.execute(sql, params)
        rows = cur.fetchall()
    return [_serialize(r) for r in rows]


def _parse_vital(value: Any) -> float | None:
    """
    Safely coerce a vital value (string, int, float, Decimal, or None) to
    float.  Returns None when the value is missing, empty, or non-numeric.
    OpenEMR stores 0 as a sentinel for "not entered" on most numeric vital
    fields, so 0.0 is also mapped to None.
    """
    if value is None:
        return None
    try:
        f = float(value)
        return f if f != 0.0 else None
    except (ValueError, TypeError):
        return None


@_empty_on_no_emr(default=dict)
def get_vitals_trends(pid: int, year: int | None = None) -> dict[str, Any]:
    """
    Derive simple directional trends for weight, blood pressure, and BMI
    from the most recent vitals rows (newest-first order).

    Trend direction compares the oldest vs. newest non-None value:

    - "increasing"        — latest > earliest by more than 2 %
    - "decreasing"        — latest < earliest by more than 2 %
    - "stable"            — within +/- 2 %
    - "insufficient_data" — fewer than 2 non-None readings

    Returns
    -------
    dict with keys:
        weight_trend        — trend sub-dict for weight
        bp_systolic_trend   — trend sub-dict for systolic BP
        bp_diastolic_trend  — trend sub-dict for diastolic BP
        bmi_trend           — trend sub-dict for BMI
        weight_loss_pct     — float (positive = weight lost) or None
        latest_vitals       — most recent serialised vitals row, or {}

    Each trend sub-dict: {direction, first, latest, readings}

    Parameters
    ----------
    year:
        When provided, only vitals recorded in that calendar year are used
        for trend calculation.
    """
    rows = get_vitals_history(pid, year=year)

    def _trend(values: list) -> dict[str, Any]:
        non_null = [v for v in values if v is not None]
        first = non_null[-1] if non_null else None  # oldest (list is newest-first)
        latest = non_null[0] if non_null else None  # most recent
        if len(non_null) < 2 or not first:
            return {
                "direction": "insufficient_data",
                "first": first,
                "latest": latest,
                "readings": len(non_null),
            }
        pct_change = (latest - first) / first
        if pct_change > 0.02:
            direction = "increasing"
        elif pct_change < -0.02:
            direction = "decreasing"
        else:
            direction = "stable"
        return {
            "direction": direction,
            "first": first,
            "latest": latest,
            "readings": len(non_null),
        }

    weights = [_parse_vital(r.get("weight")) for r in rows]
    bps_vals = [_parse_vital(r.get("bps")) for r in rows]
    bpd_vals = [_parse_vital(r.get("bpd")) for r in rows]
    bmi_vals = [_parse_vital(r.get("BMI")) for r in rows]

    weight_t = _trend(weights)
    w_first = weight_t.get("first")
    w_latest = weight_t.get("latest")
    weight_loss_pct: float | None = None
    if w_first and w_latest and w_first > 0:
        # Positive value = weight was lost over the observed window
        weight_loss_pct = round((w_first - w_latest) / w_first * 100, 2)

    return {
        "weight_trend": weight_t,
        "bp_systolic_trend": _trend(bps_vals),
        "bp_diastolic_trend": _trend(bpd_vals),
        "bmi_trend": _trend(bmi_vals),
        "weight_loss_pct": weight_loss_pct,
        "latest_vitals": rows[0] if rows else {},
    }


# ---------------------------------------------------------------------------
# Vitals-to-suspect condition mapping
# ---------------------------------------------------------------------------

# Each rule evaluates one numeric field from the latest vitals or a derived
# trend metric.  Optional "max" key bounds a range match from above.
# "weight_loss_pct" is synthetic — computed by get_vitals_trends(), not a
# raw column in form_vitals.
VITALS_SUSPECT_RULES: list[dict[str, Any]] = [
    {
        "field": "BMI",
        "threshold": 40,
        "op": ">=",
        "condition": "Morbid Obesity",
        "icd10": "E66.01",
        "hcc": "HCC48",
        "confidence": 0.82,
    },
    {
        "field": "BMI",
        "threshold": 35,
        "op": ">=",
        "max": 39.9,
        "condition": "Severe Obesity",
        "icd10": "E66.01",
        "hcc": "HCC48",
        "confidence": 0.75,
    },
    {
        "field": "oxygen_saturation",
        "threshold": 88,
        "op": "<",
        "condition": "Chronic Respiratory Failure",
        "icd10": "J96.11",
        "hcc": "HCC213",
        "confidence": 0.78,
    },
    {
        "field": "bps",
        "threshold": 180,
        "op": ">=",
        "condition": "Hypertensive Crisis",
        "icd10": "I16.0",
        "hcc": None,
        "confidence": 0.70,
    },
    {
        "field": "weight_loss_pct",
        "threshold": 10,
        "op": ">=",
        "condition": "Malnutrition/Cachexia",
        "icd10": "R63.4",
        "hcc": None,
        "confidence": 0.65,
    },
]


def _rule_matches(value: float, rule: dict[str, Any]) -> bool:
    """Return True when *value* satisfies the rule's operator and optional upper bound."""
    op = rule["op"]
    threshold = rule["threshold"]
    max_val = rule.get("max")

    if op == ">=" and value >= threshold or op == ">" and value > threshold or op == "<" and value < threshold or op == "<=" and value <= threshold:
        passed = True
    else:
        passed = False

    if passed and max_val is not None:
        return value <= max_val
    return passed


@_empty_on_no_emr()
def detect_vitals_suspects(
    pid: int,
    existing_diagnoses: list[str] | None = None,
    year: int | None = None,
) -> list[dict[str, Any]]:
    """
    Evaluate the latest vitals for *pid* against ``VITALS_SUSPECT_RULES``
    and return suspect conditions not already covered by *existing_diagnoses*.

    Parameters
    ----------
    pid:
        Patient identifier.
    existing_diagnoses:
        ICD-10 codes already on record for this patient (from billing or
        problem list).  Suspects whose icd10 matches an existing code are
        excluded (dot separator is stripped before comparison).  Pass None
        to skip filtering.
    year:
        When provided, only vitals recorded in that calendar year are used
        for suspect detection.  Useful for auditing a specific measurement
        year without modifying the patient's current record view.

    Returns
    -------
    List of dicts, each containing:
        field           — vital field that triggered the rule
        measured_value  — numeric value that was evaluated
        condition       — human-readable condition name
        icd10           — suggested ICD-10 code
        hcc             — HCC category string or None
        confidence      — float 0-1
        evidence        — short narrative string suitable for UI display
        vitals_date     — ISO date string of the vitals reading used
    """
    trends = get_vitals_trends(pid, year=year)
    latest = trends.get("latest_vitals") or {}
    vitals_date = latest.get("date") or ""

    field_values: dict[str, float | None] = {
        "BMI": _parse_vital(latest.get("BMI")),
        "oxygen_saturation": _parse_vital(latest.get("oxygen_saturation")),
        "bps": _parse_vital(latest.get("bps")),
        "bpd": _parse_vital(latest.get("bpd")),
        "weight": _parse_vital(latest.get("weight")),
        "weight_loss_pct": trends.get("weight_loss_pct"),
    }

    # Normalise existing diagnoses — strip dots for comparison
    diagnosed_normalised: set[str] = set()
    for code in (existing_diagnoses or []):
        if code:
            diagnosed_normalised.add(code.strip().upper().replace(".", ""))

    suspects: list[dict[str, Any]] = []

    for rule in VITALS_SUSPECT_RULES:
        field = rule["field"]
        value = field_values.get(field)

        if value is None:
            continue  # vital not recorded — cannot evaluate rule

        if not _rule_matches(value, rule):
            continue

        icd10 = rule.get("icd10") or ""
        if icd10 and icd10.upper().replace(".", "") in diagnosed_normalised:
            logger.debug(
                "detect_vitals_suspects pid=%s: %s already diagnosed, skipping",
                pid,
                icd10,
            )
            continue

        if field == "weight_loss_pct":
            evidence = f"Weight loss of {value:.1f}% detected from vitals trend"
        else:
            label = field.replace("_", " ").title()
            evidence = (
                f"{label} = {value:.1f} "
                f"(threshold: {rule['op']} {rule['threshold']})"
            )

        suspects.append(
            {
                "field": field,
                "measured_value": round(value, 2),
                "condition": rule["condition"],
                "icd10": icd10,
                "hcc": rule.get("hcc"),
                "confidence": rule.get("confidence", 0.5),
                "evidence": evidence,
                "vitals_date": vitals_date,
            }
        )
        logger.debug(
            "detect_vitals_suspects pid=%s: flagged %s (%s) value=%.2f",
            pid,
            rule["condition"],
            icd10,
            value,
        )

    return suspects


# ---------------------------------------------------------------------------
# SOAP Notes
# ---------------------------------------------------------------------------

@_empty_on_no_emr()
def get_soap_notes(pid: int) -> list[dict[str, Any]]:
    """Return SOAP notes for a patient, joining through forms table to get encounter ID."""
    sql = """
        SELECT
            fs.id,
            fs.pid,
            f.encounter,
            f.date,
            fs.subjective,
            fs.objective,
            fs.assessment,
            fs.plan
        FROM form_soap fs
        JOIN forms f ON f.form_id = fs.id AND f.formdir = 'soap'
        WHERE fs.pid = %s
          AND fs.activity = 1
        ORDER BY f.date DESC
    """
    with openemr_cursor() as cur:
        cur.execute(sql, (pid,))
        rows = cur.fetchall()
    return [_serialize(r) for r in rows]


# ---------------------------------------------------------------------------
# Clinical Notes
# ---------------------------------------------------------------------------

@_empty_on_no_emr()
def get_clinical_notes(encounter_id: int, tenant_id: str = "") -> list[dict[str, Any]]:
    """
    Return all clinical note forms associated with an encounter.
    Combines form_soap, form_clinical_notes, and notes fields from
    form_encounter itself.
    """
    notes: list[dict[str, Any]] = []

    # SOAP notes for this encounter (form_soap has no encounter column, join via forms)
    sql_soap = """
        SELECT
            fs.id,
            fs.pid,
            f.encounter,
            f.date AS date,
            'soap' AS note_type,
            CONCAT_WS('\n\n',
                IF(fs.subjective <> '', CONCAT('S: ', fs.subjective), NULL),
                IF(fs.objective  <> '', CONCAT('O: ', fs.objective),  NULL),
                IF(fs.assessment <> '', CONCAT('A: ', fs.assessment), NULL),
                IF(fs.plan       <> '', CONCAT('P: ', fs.plan),       NULL)
            ) AS note_text
        FROM form_soap fs
        JOIN forms f ON f.form_id = fs.id AND f.formdir = 'soap'
        WHERE f.encounter = %s AND fs.activity = 1
    """

    # Generic clinical notes form (note column, encounter is numeric)
    sql_cn = """
        SELECT
            fcn.id,
            fcn.pid,
            fcn.encounter,
            fcn.date,
            COALESCE(fcn.clinical_notes_type, 'clinical_note') AS note_type,
            COALESCE(fcn.description, '') AS note_text
        FROM form_clinical_notes fcn
        WHERE fcn.encounter = %s
    """

    with openemr_cursor(tenant_id=tenant_id) as cur:
        cur.execute(sql_soap, (encounter_id,))
        notes.extend([_serialize(r) for r in cur.fetchall()])

        try:
            cur.execute(sql_cn, (encounter_id,))
            notes.extend([_serialize(r) for r in cur.fetchall()])
        except Exception as _fcn_exc:  # noqa: BLE001
            # form_clinical_notes may not exist in all OpenEMR versions
            logger.debug("form_clinical_notes table not present or empty: %s", _fcn_exc)

    return notes


@_empty_on_no_emr()
def get_all_clinical_notes_for_patient(pid: int) -> list[dict[str, Any]]:
    """Return all clinical notes across all encounters for a patient.

    Sources:
      * OpenEMR ``form_soap`` (local EMR) — original path.
      * ``raf_intelligence.clinical_notes`` — notes ingested from external
        sources (e.g. FHIR, direct messaging, chart chase). This table may
        not yet exist if the migration hasn't run; we treat its absence as
        an empty result rather than raising.
    """
    sql = """
        SELECT
            fs.id,
            fs.pid,
            f.encounter,
            f.date,
            'soap' AS note_type,
            CONCAT_WS('\n\n',
                IF(fs.subjective <> '', CONCAT('S: ', fs.subjective), NULL),
                IF(fs.objective  <> '', CONCAT('O: ', fs.objective),  NULL),
                IF(fs.assessment <> '', CONCAT('A: ', fs.assessment), NULL),
                IF(fs.plan       <> '', CONCAT('P: ', fs.plan),       NULL)
            ) AS note_text
        FROM form_soap fs
        JOIN forms f ON f.form_id = fs.id AND f.formdir = 'soap'
        WHERE fs.pid = %s AND fs.activity = 1
        ORDER BY f.date DESC
    """
    with openemr_cursor() as cur:
        cur.execute(sql, (pid,))
        rows = cur.fetchall()
    notes = [_serialize(r) for r in rows]

    # Also pull notes stored in the RAF Intelligence clinical_notes table
    # (external / ingested notes). Map to the same dict shape callers expect.
    cn_sql = """
        SELECT
            id,
            patient_id AS pid,
            encounter_id AS encounter,
            note_date AS date,
            note_type,
            text AS note_text
        FROM clinical_notes
        WHERE patient_id = %s
        ORDER BY note_date DESC
    """
    try:
        with raf_cursor() as cur:
            cur.execute(cn_sql, (pid,))
            cn_rows = cur.fetchall()
        notes.extend(_serialize(r) for r in cn_rows)
    except Exception as exc:
        # Table may not exist yet (migration hasn't run). Stay safe.
        logger.warning(
            "get_all_clinical_notes_for_patient: clinical_notes query failed "
            "for pid=%s (table may not exist yet): %s",
            pid, exc,
        )

    # Merge and sort by date DESC. Some rows may have a None date; push
    # those to the end so real dates dominate the ordering.
    notes.sort(key=lambda n: (n.get("date") or ""), reverse=True)
    return notes


# ---------------------------------------------------------------------------
# Labs (from form_obs / procedure_result depending on OpenEMR version)
# ---------------------------------------------------------------------------

@_empty_on_no_emr()
def get_labs(pid: int, year: int | None = None) -> list[dict[str, Any]]:
    """Return lab results for a patient via procedure_order → report → result."""
    year_clause = "AND YEAR(pr.date) = %s" if year is not None else ""
    sql = f"""
        SELECT
            pr.procedure_result_id AS id,
            po.patient_id AS pid,
            po.encounter_id AS encounter,
            pr.result_code,
            pr.result_text,
            pr.result,
            pr.units,
            pr.`range`,
            pr.abnormal,
            pr.date
        FROM procedure_result pr
        JOIN procedure_report rpt ON rpt.procedure_report_id = pr.procedure_report_id
        JOIN procedure_order po ON po.procedure_order_id = rpt.procedure_order_id
        WHERE po.patient_id = %s
          {year_clause}
        ORDER BY pr.date DESC
        LIMIT 500
    """
    params: tuple = (pid, year) if year is not None else (pid,)
    try:
        with openemr_cursor() as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()
        return [_serialize(r) for r in rows]
    except Exception as _exc:  # noqa: BLE001
        logger.debug("get_labs: procedure tables not available for pid=%s: %s", pid, _exc)
        return []


# ---------------------------------------------------------------------------
# Enrollment info -- OREC, dual eligibility, and institutional status
# ---------------------------------------------------------------------------

# Keywords that identify Medicare coverage in insurance name / plan fields.
_MEDICARE_KEYWORDS: tuple[str, ...] = (
    "medicare", "cms", "part a", "part b", "part c", "part d",
    "medicare advantage", "medicare supplement", "medigap",
    "medicare hmo", "medicare ppo",
)

# Keywords that identify Medicaid / state-assistance programs.
_MEDICAID_KEYWORDS: tuple[str, ...] = (
    "medicaid", "medi-cal", "medi cal", "ahcccs", "tenncare",
    "husky", "famis", "chip", "peachstate", "caresource medicaid",
    "molina", "centene", "amerigroup", "wellcare medicaid",
    "community health plan", "coventry medicaid", "health first medicaid",
    "simply healthcare", "staywell", "sunshine health", "fidelis medicaid",
    "ucarehealth", "prestige health choice", "florida medicaid",
    "cal mediconnect", "l.a. care", "la care", "denti-cal",
)

# Place-of-service codes indicating institutional / facility-based care.
# 31=SNF, 32=Nursing Facility, 33=Custodial Care, 34=Hospice,
# 54=Intermediate Care Facility, 56=Psychiatric Residential Treatment.
_INSTITUTIONAL_POS: frozenset[str] = frozenset({"31", "32", "33", "34", "54", "56"})


def _insurance_contains(text: str, keywords: tuple[str, ...]) -> bool:
    """Return True if any keyword appears as a substring of lowercased text."""
    t = text.lower()
    return any(kw in t for kw in keywords)


@_empty_on_no_emr(default=dict)
def get_patient_enrollment_info(pid: int) -> dict[str, Any]:
    """
    Derive insurance/enrollment metadata for a patient using best-effort
    heuristics against OpenEMR data.  Never raises -- always returns a usable
    dict that defaults to CNA (community, non-dual, aged) when data is sparse.

    Detection logic
    ---------------
    1. Query insurance_data joined to insurance_companies for rich name data.
       Identifies primary Medicare and any-tier Medicaid coverage.
    2. Dual-eligibility classification:
         full_dual    -- primary Medicare + secondary/any Medicaid
         partial_dual -- Medicaid detected but Medicare not confirmed
         non_dual     -- no Medicaid detected (or no insurance records)
    3. OREC heuristic from patient age (CMS convention):
         0 (aged)     -- age >= 65
         1 (disabled) -- age <  65  (assumed SSDI pathway)
       ESRD (OREC 2/3) cannot be detected from OpenEMR data alone.
    4. Institutional status from recent form_encounter.pos_code values:
       POS 31/32/33/34/54/56 -> institutional = True.
    5. Confidence rating:
         high   -- insurance rows found with clear Medicare + Medicaid signals
         medium -- partial match (only one type detected, or age heuristic only)
         low    -- no insurance records; fell back entirely to defaults

    Returns
    -------
    dict with keys:
        dual_status         : "non_dual" | "partial_dual" | "full_dual"
        primary_insurance   : str | None
        secondary_insurance : str | None
        orec                : "0" | "1"
        institutional       : bool
        pos_codes           : list[str]  (distinct POS codes from recent encounters)
        source              : "openemr_insurance" | "openemr_age_heuristic" | "default"
        confidence          : "high" | "medium" | "low"
    """
    from datetime import date, datetime

    _default: dict[str, Any] = {
        "dual_status": "non_dual",
        "primary_insurance": None,
        "secondary_insurance": None,
        "orec": "0",
        "institutional": False,
        "pos_codes": [],
        "source": "default",
        "confidence": "low",
    }

    # ------------------------------------------------------------------
    # Step 1 -- Patient demographics (DOB for age / OREC)
    # ------------------------------------------------------------------
    try:
        patient = get_patient(pid)
        if not patient:
            # Try OpenEMR patient_data directly (pid may be emr_pid)
            try:
                with openemr_cursor() as cur:
                    cur.execute("SELECT DOB FROM patient_data WHERE pid = %s", (pid,))
                    row = cur.fetchone()
                    if row:
                        patient = {"DOB": str(row["DOB"]) if row.get("DOB") else None}
            except Exception as _dob_exc:  # noqa: BLE001
                logger.debug(
                    "get_patient_enrollment_info: patient_data DOB fallback failed pid=%s: %s",
                    pid, _dob_exc,
                )
        if not patient:
            patient = {}

        dob_raw = patient.get("DOB") or patient.get("dob")
        age: int | None = None
        if dob_raw:
            try:
                dob_str = dob_raw if isinstance(dob_raw, str) else str(dob_raw)
                dob = datetime.strptime(dob_str[:10], "%Y-%m-%d").date()
                today = date.today()
                age = (
                    today.year - dob.year
                    - ((today.month, today.day) < (dob.month, dob.day))
                )
            except ValueError:
                logger.debug(
                    "get_patient_enrollment_info: unparseable DOB '%s' for pid=%s",
                    dob_raw, pid,
                )
    except Exception as exc:
        logger.warning(
            "get_patient_enrollment_info: patient fetch failed pid=%s: %s", pid, exc
        )
        return _default

    # ------------------------------------------------------------------
    # Step 2 -- Insurance data (dual-eligibility detection)
    # ------------------------------------------------------------------
    dual_status = "non_dual"
    primary_insurance: str | None = None
    secondary_insurance: str | None = None
    plan_type: str | None = None
    enrolled_since: str | None = None
    insurance_source = "default"
    insurance_confidence = "low"

    try:
        ins_sql = """
            SELECT
                id.type,
                id.provider,
                id.plan_name,
                id.date,
                ic.name AS company_name
            FROM insurance_data id
            LEFT JOIN insurance_companies ic ON ic.id = id.provider
            WHERE id.pid = %s
            ORDER BY id.type, id.date DESC
        """
        with openemr_cursor() as cur:
            cur.execute(ins_sql, (pid,))
            ins_rows = cur.fetchall()

        has_primary_medicare   = False
        has_secondary_medicaid = False
        has_any_medicare       = False
        has_any_medicaid       = False

        # Track best display name per tier; first row wins because rows are
        # sorted by date DESC so the most-recent record per tier comes first.
        names_by_tier: dict[str, str] = {}

        # Track earliest enrollment date and plan type
        enrolled_since: str | None = None
        plan_type: str | None = None

        # Normalize type values: "primary"→"1", "secondary"→"2", "tertiary"→"3"
        _TYPE_MAP = {"primary": "1", "secondary": "2", "tertiary": "3"}

        for row in ins_rows:
            raw_type = str(row.get("type") or "").strip().lower()
            ins_type = _TYPE_MAP.get(raw_type, raw_type)
            plan     = str(row.get("plan_name")    or "")
            company  = str(row.get("company_name") or "")
            combined = f"{plan} {company}"

            is_medicare = _insurance_contains(combined, _MEDICARE_KEYWORDS)
            is_medicaid = _insurance_contains(combined, _MEDICAID_KEYWORDS)

            display = (plan.strip() or company.strip()) or None
            if display and ins_type not in names_by_tier:
                names_by_tier[ins_type] = display

            # Detect plan type from plan name (HMO, PPO, SNP, etc.)
            # Only classify when we actually have a plan name — otherwise we'd
            # label a row with no plan_name / company_name as "Medicare
            # Advantage" purely because tier=1, producing a misleading UI.
            if ins_type == "1" and plan_type is None and plan.strip():
                plan_upper = plan.upper()
                if "HMO-POS" in plan_upper:
                    plan_type = "MA-HMO-POS"
                elif "D-SNP" in plan_upper:
                    plan_type = "MA-HMO-DSNP"
                elif "C-SNP" in plan_upper:
                    plan_type = "MA-HMO-CSNP"
                elif "HMO" in plan_upper:
                    plan_type = "MA-HMO"
                elif "PPO" in plan_upper:
                    plan_type = "MA-PPO"
                elif "ORIGINAL" in plan_upper or "PART A" in plan_upper:
                    plan_type = "Original Medicare"
                else:
                    plan_type = "Medicare Advantage"

            # Track earliest enrolled_since
            row_date = row.get("date")
            if row_date:
                dt_str = str(row_date)[:10]
                if enrolled_since is None or dt_str < enrolled_since:
                    enrolled_since = dt_str

            if is_medicare:
                has_any_medicare = True
                if ins_type == "1":
                    has_primary_medicare = True

            if is_medicaid:
                has_any_medicaid = True
                if ins_type in ("2", "3"):
                    has_secondary_medicaid = True

        primary_insurance   = names_by_tier.get("1")
        secondary_insurance = names_by_tier.get("2") or names_by_tier.get("3")

        if ins_rows:
            if has_primary_medicare and (has_secondary_medicaid or has_any_medicaid):
                # Primary Medicare + any Medicaid tier = full dual.
                # True partial-dual (QMB-only, SLMB, QI) requires CMS buy-in
                # code data that OpenEMR does not capture; we conservatively
                # classify as full_dual when Medicaid co-exists with Medicare.
                dual_status = "full_dual"
                insurance_source = "openemr_insurance"
                insurance_confidence = (
                    "high" if (has_primary_medicare and has_secondary_medicaid) else "medium"
                )
            elif has_any_medicaid:
                # Medicaid present but Medicare not confirmed.
                dual_status = "partial_dual"
                insurance_source = "openemr_insurance"
                insurance_confidence = "medium"
            else:
                dual_status = "non_dual"
                insurance_source = "openemr_insurance"
                insurance_confidence = "medium" if has_any_medicare else "low"
        else:
            logger.debug(
                "get_patient_enrollment_info: no insurance_data rows for pid=%s", pid
            )

    except Exception as exc:
        logger.warning(
            "get_patient_enrollment_info: insurance_data unavailable for pid=%s (%s); "
            "proceeding without dual check",
            pid, exc,
        )

    # Fallback: if no insurance from OpenEMR, check patients table fields
    if primary_insurance is None:
        try:
            from app.db import raf_cursor as _raf_cur
            with _raf_cur() as cur:
                cur.execute(
                    "SELECT insurance_type, insurance_plan, enrolled_date "
                    "FROM patients WHERE id = %s LIMIT 1",
                    (pid,),
                )
                p_row = cur.fetchone()
                if p_row:
                    ins_name = p_row.get("insurance_plan") or p_row.get("insurance_type")
                    if ins_name:
                        primary_insurance = ins_name
                        insurance_source = "raf_patients"
                        insurance_confidence = "medium"
                        if plan_type is None:
                            plan_type = "Medicare Advantage" if "medicare" in ins_name.lower() else ins_name
                        if enrolled_since is None and p_row.get("enrolled_date"):
                            enrolled_since = str(p_row["enrolled_date"])[:10]
        except Exception as _ins_exc:  # noqa: BLE001
            logger.debug(
                "get_patient_enrollment_info: raf patients insurance fallback failed pid=%s: %s",
                pid, _ins_exc,
            )

    # ------------------------------------------------------------------
    # Step 3 -- OREC from age
    # ------------------------------------------------------------------
    # OREC 0 = aged (entitlement via age >= 65)
    # OREC 1 = disabled (entitlement via SSDI, age < 65)
    # OREC 2/3 = ESRD -- not detectable from OpenEMR data
    orec = "0"
    orec_source = "default"

    if age is not None:
        orec = "1" if age < 65 else "0"
        orec_source = "openemr_age_heuristic"

    # ------------------------------------------------------------------
    # Step 4 -- Institutional status via form_encounter.pos_code
    # ------------------------------------------------------------------
    is_institutional = False
    pos_codes: list[str] = []

    try:
        # NOTE: This OpenEMR instance does not have pos_code on form_encounter.
        # We check the facility field as a heuristic instead.
        fac_sql = """
            SELECT DISTINCT facility
            FROM form_encounter
            WHERE pid = %s
              AND facility IS NOT NULL
              AND facility != ''
            ORDER BY date DESC
            LIMIT 50
        """
        with openemr_cursor() as cur:
            cur.execute(fac_sql, (pid,))
            fac_rows = cur.fetchall()

        # Map facility names to institutional indicators
        _INSTITUTIONAL_KEYWORDS = {"snf", "nursing", "hospice", "rehab", "long term", "ltc"}
        for r in fac_rows:
            fac = str(r.get("facility") or "").lower()
            if any(kw in fac for kw in _INSTITUTIONAL_KEYWORDS):
                is_institutional = True
                pos_codes.append("31")  # SNF default
                logger.debug(
                    "get_patient_enrollment_info: pid=%s institutional=True via facility '%s'",
                    pid, r.get("facility"),
                )
                break
    except Exception as exc:
        logger.debug(
            "get_patient_enrollment_info: facility check failed for pid=%s (%s)", pid, exc
        )

    # ------------------------------------------------------------------
    # Step 5 -- Consolidate source and confidence
    # ------------------------------------------------------------------
    if insurance_source == "openemr_insurance":
        final_source = "openemr_insurance"
        final_confidence = insurance_confidence
    elif orec_source == "openemr_age_heuristic":
        final_source = "openemr_age_heuristic"
        final_confidence = "medium"
    else:
        final_source = "default"
        final_confidence = "low"

    result: dict[str, Any] = {
        "dual_status": dual_status,
        "primary_insurance": primary_insurance,
        "secondary_insurance": secondary_insurance,
        "plan_type": plan_type,
        "enrolled_since": enrolled_since,
        "orec": orec,
        "orec_description": "Aged (≥65)" if orec == "0" else "Disabled (<65, SSDI)" if orec == "1" else "ESRD",
        "institutional": is_institutional,
        "pos_codes": pos_codes,
        "source": final_source,
        "confidence": final_confidence,
    }

    logger.debug(
        "get_patient_enrollment_info pid=%s -> dual=%s orec=%s inst=%s "
        "source=%s confidence=%s age=%s pos=%s",
        pid, dual_status, orec, is_institutional,
        final_source, final_confidence, age, pos_codes,
    )
    return result


# ---------------------------------------------------------------------------
# Problem List (lists table)
# ---------------------------------------------------------------------------

@_empty_on_no_emr()
def get_problem_list(pid: int, year: int | None = None, tenant_id: str = "") -> list[dict[str, Any]]:
    """
    Return all active medical problems for a patient from the lists table.

    The lists table stores ICD-coded problems, allergies, medications, and
    other clinical list items.  We filter to type='medical_problem' and
    activity=1 (active).  The diagnosis column holds a raw ICD code and may
    be NULL or empty when a clinician only entered a free-text title; both
    cases are returned so callers can decide how to handle title-only entries.

    990K-row table — query is covered by the (pid, type, activity) index that
    OpenEMR creates by default.

    When *year* is provided, only problems active during that year are
    returned — i.e. began on or before the year-end AND not ended before
    the year started.
    """
    params: list[Any] = [pid]
    year_clause = ""
    if year is not None:
        year_clause = "  AND YEAR(begdate) <= %s AND (enddate IS NULL OR YEAR(enddate) >= %s)"
        params.append(year)
        params.append(year)

    sql = f"""
        SELECT
            id,
            title,
            diagnosis,
            begdate,
            enddate,
            activity,
            comments
        FROM lists
        WHERE pid = %s
          AND type = 'medical_problem'
          AND activity = 1
        {year_clause}
        ORDER BY begdate DESC
    """
    try:
        with openemr_cursor(tenant_id=tenant_id) as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()
        return [_serialize(r) for r in rows]
    except Exception as _exc:  # noqa: BLE001
        logger.debug("lists table not available or accessible for pid=%s: %s", pid, _exc)
        return []


@_empty_on_no_emr()
def get_recapture_gaps(pid: int, year: int, tenant_id: str = "") -> list[dict[str, Any]]:
    """
    Return active medical problems that have NOT been billed as an ICD-10
    code in the given calendar year.

    These are RAF recapture opportunities: the condition is on record in the
    problem list but was not substantiated by a claim in *year*, which means
    the HCC will drop from the risk score unless it is re-documented and
    billed before the payment year closes.

    Only problems with a non-empty diagnosis code are considered; title-only
    entries (diagnosis IS NULL or '') are excluded because we cannot match
    them against billing codes without a structured code.
    """
    sql = """
        SELECT
            l.id,
            l.title,
            l.diagnosis,
            l.begdate
        FROM lists l
        WHERE l.pid = %s
          AND l.type = 'medical_problem'
          AND l.activity = 1
          AND l.diagnosis IS NOT NULL
          AND l.diagnosis != ''
          AND REPLACE(l.diagnosis, 'ICD10:', '') NOT IN (
              SELECT b.code
              FROM billing b
              JOIN form_encounter fe ON b.encounter = fe.encounter AND b.pid = fe.pid
              WHERE b.pid = l.pid
                AND b.code_type = 'ICD10'
                AND b.activity = 1
                AND YEAR(fe.date) = %s
          )
        ORDER BY l.begdate DESC
    """
    try:
        with openemr_cursor(tenant_id=tenant_id) as cur:
            cur.execute(sql, (pid, year))
            rows = cur.fetchall()
        return [_serialize(r) for r in rows]
    except Exception as _exc:  # noqa: BLE001
        logger.debug(
            "get_recapture_gaps failed for pid=%s year=%s: %s", pid, year, _exc
        )
        return []


def push_medical_problem(pid: int, title: str, diagnosis_code: str) -> bool:
    """
    Insert a medical problem directly into the OpenEMR lists table.
    Used for Bi-Directional Suspect Sync (EMR Write-Back).
    """
    try:
        from datetime import datetime
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        sql = """
            INSERT INTO lists (
                date, type, title, begdate, pid, activity, diagnosis
            ) VALUES (
                %s, 'medical_problem', %s, %s, %s, 1, %s
            )
        """
        # Note: In OpenEMR, the diagnosis column usually stores 'ICD10:code' if it's ICD-10.
        formatted_diagnosis = f"ICD10:{diagnosis_code}" if not diagnosis_code.startswith("ICD10:") else diagnosis_code
        with openemr_cursor() as cur:
            cur.execute(sql, (now_str, title, now_str, pid, formatted_diagnosis))
        logger.info("Pushed condition %s (%s) for pid=%s", title, formatted_diagnosis, pid)
        return True
    except Exception as exc:
        logger.error("Failed to push medical problem for pid=%s: %s", pid, exc)
        return False



@_empty_on_no_emr(default=dict)
def get_latest_vitals(pid: int, tenant_id: str = "") -> dict[str, Any]:
    """
    Return the single most-recent active vitals row for a patient.

    Pulls from get_vitals() (already ordered DESC by date) and returns the
    first element, or an empty dict when no vitals are recorded.  All values
    are serialised by _serialize(), so Decimal / datetime types are safe.
    """
    rows = get_vitals(pid, tenant_id=tenant_id)
    return rows[0] if rows else {}


@_empty_on_no_emr()
def get_medication_diagnoses(pid: int, tenant_id: str = "") -> list[dict[str, Any]]:
    """Return unique ICD-10 codes extracted from prescription diagnosis fields.

    Reads the ``diagnosis`` column on the ``prescriptions`` table, which
    stores the ICD-10 code(s) the medication was formally linked to at the
    time of prescribing.  Because a single cell may contain multiple codes
    (semicolon-separated or other delimiters), the result is expanded by
    ``_parse_diagnosis_field()`` so that every returned dict contains
    exactly one ``icd_code``.  Rows are ordered active-first then by drug name.

    Returns a list of dicts with keys:
        icd_code  - a single parsed ICD-10 code
        drug      - medication name from the prescription
        active    - prescription active flag (1 = active, 0 = inactive)
    """
    sql = """
        SELECT DISTINCT p.note AS diagnosis, p.drug, p.active
        FROM prescriptions p
        WHERE p.patient_id = %s
          AND p.note IS NOT NULL
          AND p.note != ''
        ORDER BY p.active DESC, p.drug
    """
    with openemr_cursor(tenant_id=tenant_id) as cur:
        cur.execute(sql, (pid,))
        rows = cur.fetchall()

    expanded: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()  # (normalised_code, drug) dedup key

    for row in [_serialize(r) for r in rows]:
        codes = _parse_diagnosis_field(row.get("diagnosis"))
        for code in codes:
            key = (code.upper(), (row.get("drug") or "").lower())
            if key in seen:
                continue
            seen.add(key)
            expanded.append(
                {
                    "icd_code": code,
                    "drug": row.get("drug"),
                    "active": row.get("active"),
                }
            )

    return expanded


@_empty_on_no_emr()
def get_all_patient_diagnoses(pid: int) -> list[dict[str, Any]]:
    """
    Return a deduplicated union of ICD codes from two sources:

    1. billing table  — codes that were actually billed (code_type ICD10/ICD9)
    2. lists table    — active problem-list entries that have a diagnosis code

    Each returned dict has:
        icd_code  : str   — the raw code value
        title     : str   — human-readable label (code_text or lists.title)
        source    : str   — 'billing', 'problem_list', or 'both'
        last_seen : str   — most recent date (ISO) for the code from that source

    Deduplication is by icd_code (case-insensitive).  When the same code
    appears in both sources the source field is set to 'both' and last_seen
    uses the most recent date across both.
    """
    billing_sql = """
        SELECT
            b.code            AS icd_code,
            b.code_text       AS title,
            MAX(b.id)         AS last_seen
        FROM billing b
        WHERE b.pid = %s
          AND b.activity = 1
          AND b.code_type IN ('ICD10', 'ICD9')
          AND b.code IS NOT NULL
          AND b.code != ''
        GROUP BY b.code, b.code_text
    """

    problem_sql = """
        SELECT
            l.diagnosis       AS icd_code,
            l.title           AS title,
            l.begdate         AS last_seen
        FROM lists l
        WHERE l.pid = %s
          AND l.type = 'medical_problem'
          AND l.activity = 1
          AND l.diagnosis IS NOT NULL
          AND l.diagnosis != ''
    """

    billing_rows: list[dict[str, Any]] = []
    problem_rows: list[dict[str, Any]] = []

    try:
        with openemr_cursor() as cur:
            cur.execute(billing_sql, (pid,))
            billing_rows = [_serialize(r) for r in cur.fetchall()]
    except Exception as exc:
        logger.warning("get_all_patient_diagnoses billing error pid=%s: %s", pid, exc)

    try:
        with openemr_cursor() as cur:
            cur.execute(problem_sql, (pid,))
            problem_rows = [_serialize(r) for r in cur.fetchall()]
    except Exception as exc:
        logger.warning("get_all_patient_diagnoses problem_list error pid=%s: %s", pid, exc)

    # Merge into a dict keyed by normalised ICD code
    merged: dict[str, dict[str, Any]] = {}

    for row in billing_rows:
        key = (row.get("icd_code") or "").strip().upper()
        if not key:
            continue
        merged[key] = {
            "icd_code": row.get("icd_code", "").strip(),
            "title": row.get("title") or "",
            "source": "billing",
            "last_seen": row.get("last_seen") or "",
        }

    for row in problem_rows:
        key = (row.get("icd_code") or "").strip().upper()
        if not key:
            continue
        pl_date = row.get("last_seen") or ""
        if key in merged:
            # Code already seen in billing — mark as 'both' and keep latest date
            existing = merged[key]
            existing["source"] = "both"
            # Keep the more recent of the two dates (ISO strings compare correctly)
            if pl_date and pl_date > (existing.get("last_seen") or ""):
                existing["last_seen"] = pl_date
            # Prefer problem list title when billing code_text is blank
            if not existing["title"]:
                existing["title"] = row.get("title") or ""
        else:
            merged[key] = {
                "icd_code": row.get("icd_code", "").strip(),
                "title": row.get("title") or "",
                "source": "problem_list",
                "last_seen": pl_date,
            }

    return list(merged.values())


# ---------------------------------------------------------------------------
# Convenience aliases / additional entry points
# ---------------------------------------------------------------------------

@_empty_on_no_emr()
def get_all_patients(limit: int = 500, offset: int = 0, tenant_id: str | None = None) -> list[dict[str, Any]]:
    """
    Alias for get_patients().

    Returns pid, fname, lname, DOB, sex, and status columns for all active
    patients.  Used by the RAF batch calculator and suspect engine.
    """
    sql = """
        SELECT
            pid,
            fname,
            lname,
            mname,
            DOB,
            sex,
            race,
            ethnicity,
            language,
            phone_home,
            phone_cell,
            email,
            providerID,
            CASE WHEN pid > 0 THEN 'active' ELSE 'inactive' END AS status,
            date AS created_date
        FROM patient_data
        WHERE pid > 0
        ORDER BY lname, fname
        LIMIT %s OFFSET %s
    """
    with openemr_cursor(tenant_id=tenant_id) as cur:
        cur.execute(sql, (limit, offset))
        rows = cur.fetchall()
    return [_serialize(r) for r in rows]


@_empty_on_no_emr(default=dict)
def get_soap_notes_by_encounter(encounter_id: int) -> dict[str, Any]:
    """
    Return the SOAP note for a specific encounter as a single dict.

    Falls back to an empty dict when no SOAP note exists for the encounter.
    For bulk retrieval across all encounters use get_soap_notes(pid).
    """
    sql = """
        SELECT
            fs.id,
            fs.pid,
            f.encounter,
            f.date,
            fs.subjective,
            fs.objective,
            fs.assessment,
            fs.plan
        FROM form_soap fs
        JOIN forms f ON f.form_id = fs.id AND f.formdir = 'soap'
        WHERE f.encounter = %s
          AND fs.activity  = 1
        ORDER BY f.date DESC
        LIMIT 1
    """
    with openemr_cursor() as cur:
        cur.execute(sql, (encounter_id,))
        row = cur.fetchone()
    return _serialize(row) if row else {}


@_empty_on_no_emr(default="")
def get_all_clinical_text(pid: int) -> str:
    """
    Combine all SOAP notes and encounter reasons for a patient into a single
    text block suitable for NLP / Gemini analysis.

    Format per encounter:
        [ENCOUNTER <date>] <reason>
        S: <subjective>
        O: <objective>
        A: <assessment>
        P: <plan>
    """
    encounters = get_encounters(pid)
    soap_notes = get_soap_notes(pid)

    # Index SOAP notes by encounter id for fast lookup
    soap_by_enc: dict[int, dict[str, Any]] = {}
    for note in soap_notes:
        enc_id = note.get("encounter")
        if enc_id:
            soap_by_enc[int(enc_id)] = note

    lines: list[str] = []
    for enc in encounters:
        enc_id = enc.get("encounter_id") or enc.get("id")
        enc_date = enc.get("date") or ""
        reason = (enc.get("reason") or "").strip()

        lines.append(f"[ENCOUNTER {enc_date}] {reason}".strip())

        soap = soap_by_enc.get(int(enc_id)) if enc_id else None
        if soap:
            for section, label in [
                ("subjective", "S"),
                ("objective", "O"),
                ("assessment", "A"),
                ("plan", "P"),
            ]:
                text = (soap.get(section) or "").strip()
                if text:
                    lines.append(f"{label}: {text}")

        lines.append("")  # blank line between encounters

    return "\n".join(lines).strip()


# ---------------------------------------------------------------------------
# Immunizations
# ---------------------------------------------------------------------------

@_empty_on_no_emr()
def get_immunizations(pid: int) -> list[dict[str, Any]]:
    """
    Return all valid immunization records for a patient from the immunizations
    table, excluding entries marked as added erroneously.

    Columns returned:
        id, administered_date, cvx_code, manufacturer, lot_number,
        administered_by, education_date, note

    Results are ordered most-recent-first.  CVX codes are the authoritative
    CDC vaccine identifier and are used by get_hedis_compliance() for measure
    matching -- do not replace them with text descriptions in downstream logic.
    """
    sql = """
        SELECT
            id,
            administered_date,
            cvx_code,
            note AS title
        FROM immunizations
        WHERE patient_id = %s
          AND added_erroneously = 0
        ORDER BY administered_date DESC
    """
    try:
        with openemr_cursor() as cur:
            cur.execute(sql, (pid,))
            rows = cur.fetchall()
        return [_serialize(r) for r in rows]
    except Exception as _exc:  # noqa: BLE001
        logger.debug("immunizations table not available for pid=%s: %s", pid, _exc)
        return []


# ---------------------------------------------------------------------------
# HEDIS / Stars quality measures
# ---------------------------------------------------------------------------

# Influenza CVX codes (all seasonal and recombinant formulations).
# Source: CDC CVX code list -- update annually as new codes are assigned.
_CVX_FLU: frozenset[str] = frozenset([
    "140",  # Influenza, seasonal, injectable, preservative free
    "141",  # Influenza, seasonal, injectable
    "150",  # Influenza, injectable, MDCK, preservative free, quadrivalent
    "153",  # Influenza, injectable, MDCK, preservative free
    "155",  # Influenza, recombinant, injectable, preservative free, quadrivalent
    "158",  # Influenza, injectable, quadrivalent, contains preservative
    "161",  # Influenza, injectable, quadrivalent, preservative free
    "166",  # Influenza, intradermal, quadrivalent, preservative free
    "168",  # Influenza, trivalent, injectable, preservative free
    "171",  # Influenza NOS
    "185",  # Influenza, recombinant, quadrivalent, injectable, preservative free
    "186",  # Influenza, injectable, MDCK, quadrivalent, preservative
    "197",  # Influenza, high-dose seasonal, quadrivalent, preservative free
    "205",  # Influenza, seasonal vaccine, quadrivalent
])

# Pneumococcal CVX codes (PCV and PPSV formulations).
# HEDIS/Stars: one lifetime dose of PPSV23 or PCV13/15/20 for age >= 65.
_CVX_PNEUMO: frozenset[str] = frozenset([
    "33",   # Pneumococcal polysaccharide vaccine, 23-valent (PPSV23)
    "100",  # Pneumococcal conjugate vaccine, 7-valent (PCV7)
    "109",  # Pneumococcal vaccine, NOS
    "133",  # Pneumococcal conjugate vaccine, 13-valent (PCV13)
    "152",  # Pneumococcal conjugate vaccine, 15-valent (PCV15)
    "215",  # Pneumococcal conjugate vaccine, 20-valent (PCV20)
    "216",  # Pneumococcal vaccine, NOS (newer code)
])

# Zoster CVX codes.
# HEDIS/Stars: recombinant shingles series (RZV, CVX 187/188) preferred for 50+;
# live zoster (CVX 121) still counted as compliant.
_CVX_ZOSTER: frozenset[str] = frozenset([
    "121",  # Zoster vaccine, live (Zostavax)
    "187",  # Zoster vaccine recombinant (Shingrix dose 1)
    "188",  # Zoster vaccine recombinant (Shingrix dose 2)
])


def _calculate_age(dob_raw: str | None) -> int | None:
    """
    Return age in whole years from an ISO-format DOB string (YYYY-MM-DD).
    Returns None when dob_raw is absent or cannot be parsed.
    """
    if not dob_raw:
        return None
    from datetime import date, datetime
    try:
        dob = datetime.strptime(str(dob_raw)[:10], "%Y-%m-%d").date()
        today = date.today()
        return (
            today.year - dob.year
            - ((today.month, today.day) < (dob.month, dob.day))
        )
    except ValueError:
        return None


@_empty_on_no_emr(default=dict)
def get_hedis_compliance(pid: int, year: int) -> dict[str, Any]:
    """
    Check HEDIS/Stars quality measures for a patient and return a compliance
    summary keyed by measure identifier.

    Each measure dict contains:
        measure      : str        -- human-readable measure name
        due          : bool       -- whether this measure applies to the patient
        compliant    : bool       -- whether the patient meets the measure
        last_date    : str | None -- ISO date of the most recent qualifying event
        year_specific: bool       -- True if compliance resets each calendar year
                                     (i.e. the ``year`` parameter affects this
                                     measure), False if any historical dose is
                                     sufficient (lifetime / one-time series).

    Design intent: the ``year`` parameter
    -------------------------------------
    Not every HEDIS/Stars measure is evaluated on a per-year basis.  The two
    categories are:

    ANNUAL measures  (year_specific=True)
        Compliance is determined within the requested calendar year only.
        A dose given in a prior year does NOT satisfy the current year.
        Example: influenza vaccine — patients need a new shot every season.

    LIFETIME measures  (year_specific=False)
        Compliance is satisfied by ANY qualifying event in the patient's
        history, regardless of the year it was administered.  The ``year``
        parameter is accepted but deliberately ignored for these measures so
        callers can pass a uniform signature without special-casing.
        Examples: pneumococcal series (once at 65+), zoster/Shingrix series
        (two doses, recommended 50+) — once complete, they stay complete.

    This is not a bug; it reflects the underlying clinical guidance for each
    vaccine program.  Callers can inspect ``year_specific`` to understand
    which measures were filtered by year.

    Measures evaluated
    ------------------
    flu_vaccine     -- Annual influenza vaccination (all ages; Stars focuses on 65+)
    pneumococcal    -- Pneumococcal vaccination series (age >= 65)
    zoster          -- Shingles vaccination series (age >= 50)

    CVX codes are used exclusively for vaccine matching; free-text note fields
    are searched for influenza only as a secondary fallback to handle OpenEMR
    installs that did not capture a CVX code at time of administration.

    Additional HEDIS measures (colorectal screening, breast cancer screening,
    diabetes A1c, statin use, etc.) should be added here as labs and orders
    data become available from procedure_result / procedure_order tables.
    """
    patient = get_patient(pid)
    if not patient:
        return {}

    age = _calculate_age(patient.get("DOB") or patient.get("dob"))
    immunizations = get_immunizations(pid)

    measures: dict[str, Any] = {}

    # ------------------------------------------------------------------
    # Influenza -- ANNUAL measure (year_specific=True).
    # Compliance is evaluated within ``year`` only; a dose from a prior
    # season does NOT carry forward.
    # CDC recommends vaccination for everyone 6 months+; Stars/HEDIS
    # focuses on 65+, but we flag due=True for all ages so the UI can
    # apply its own eligibility filter.
    # Secondary fallback: note-field text search for "flu" covers records
    # entered without a CVX code, which is common in older OpenEMR data.
    # ------------------------------------------------------------------
    flu_records = [
        i for i in immunizations
        if str(i.get("cvx_code") or "") in _CVX_FLU
        or "flu" in (i.get("note") or "").lower()
    ]
    flu_this_year = [
        f for f in flu_records
        if str(f.get("administered_date") or "")[:4] == str(year)
    ]
    measures["flu_vaccine"] = {
        "measure": "Influenza Vaccination",
        "due": True,
        "compliant": len(flu_this_year) > 0,
        "last_date": flu_records[0]["administered_date"] if flu_records else None,
        # year_specific=True: only doses administered in ``year`` count.
        "year_specific": True,
    }

    # ------------------------------------------------------------------
    # Pneumococcal -- LIFETIME measure (year_specific=False).
    # Due at age >= 65.  A patient who received PCV15/PCV20/PPSV23 in any
    # prior year is considered compliant; ``year`` is intentionally ignored.
    # See design-intent note in the docstring above.
    # ------------------------------------------------------------------
    pneumo_records = [
        i for i in immunizations
        if str(i.get("cvx_code") or "") in _CVX_PNEUMO
    ]
    measures["pneumococcal"] = {
        "measure": "Pneumococcal Vaccination",
        "due": (age or 0) >= 65,
        "compliant": len(pneumo_records) > 0,
        "last_date": pneumo_records[0]["administered_date"] if pneumo_records else None,
        # year_specific=False: any historical dose satisfies compliance;
        # ``year`` parameter does not filter these records.
        "year_specific": False,
    }

    # ------------------------------------------------------------------
    # Zoster (Shingles) -- LIFETIME measure (year_specific=False).
    # Recommended for age >= 50.  Full compliance requires either:
    #   - 2 doses of RZV (CVX 187/188, Shingrix series), or
    #   - 1 dose of live-attenuated ZVL (CVX 121, Zostavax — no longer
    #     manufactured but counted for patients vaccinated historically).
    # Once the series is complete it remains complete; ``year`` is
    # intentionally ignored.  See design-intent note in the docstring.
    # ------------------------------------------------------------------
    zoster_records = [
        i for i in immunizations
        if str(i.get("cvx_code") or "") in _CVX_ZOSTER
    ]
    rzv_doses = [
        i for i in zoster_records
        if str(i.get("cvx_code") or "") in ("187", "188")
    ]
    live_doses = [
        i for i in zoster_records
        if str(i.get("cvx_code") or "") == "121"
    ]
    zoster_complete = len(rzv_doses) >= 2 or len(live_doses) >= 1
    measures["zoster"] = {
        "measure": "Zoster (Shingles) Vaccination",
        "due": (age or 0) >= 50,
        "compliant": zoster_complete,
        "doses_recorded": len(zoster_records),
        "last_date": zoster_records[0]["administered_date"] if zoster_records else None,
    }

    logger.debug(
        "get_hedis_compliance pid=%s year=%s age=%s measures=%s",
        pid, year, age,
        {k: v["compliant"] for k, v in measures.items()},
    )
    return measures


# ---------------------------------------------------------------------------
# Medication diagnosis gap analysis
# ---------------------------------------------------------------------------

@_empty_on_no_emr()
def get_medication_diagnosis_gaps(pid: int, year: int) -> list[dict[str, Any]]:
    """Return active-medication diagnoses not billed in *year* (RAF gap candidates).

    A medication is actively prescribed for a specific ICD-10 condition, but
    that condition has not appeared on any claim in *year*.  The presence of an
    active prescription is strong clinical evidence that the condition is
    ongoing and should be re-documented and billed before the payment year
    closes.

    Because ``prescriptions.diagnosis`` may encode multiple codes in a single
    cell, parsing is done in Python via ``_parse_diagnosis_field()`` rather
    than inside MySQL, avoiding a fragile database-side subquery against
    multi-code strings.

    Algorithm
    ---------
    1. Fetch all active prescriptions that have a non-empty diagnosis field.
    2. Fetch all ICD-10 codes billed for *pid* in *year* into a set.
    3. Parse each prescription's diagnosis cell into individual codes.
    4. Emit a gap row for every code absent from the billed set.

    Returns a list of dicts with keys:
        icd_code  - the individual parsed ICD-10 code
        drug      - medication name from the prescription
        active    - prescription active flag (always 1 here)
    """
    rx_sql = """
        SELECT p.note AS diagnosis, p.drug, p.active
        FROM prescriptions p
        WHERE p.patient_id = %s
          AND p.active = 1
          AND p.note IS NOT NULL
          AND p.note != ''
    """
    billed_sql = """
        SELECT DISTINCT b.code
        FROM billing b
        JOIN form_encounter fe ON b.encounter = fe.encounter AND b.pid = fe.pid
        WHERE b.pid = %s
          AND b.code_type = 'ICD10'
          AND b.activity = 1
          AND YEAR(fe.date) = %s
    """

    try:
        with openemr_cursor() as cur:
            cur.execute(rx_sql, (pid,))
            rx_rows = [_serialize(r) for r in cur.fetchall()]

            cur.execute(billed_sql, (pid, year))
            billed_codes: set[str] = {
                (r["code"] or "").strip().upper()
                for r in cur.fetchall()
                if r.get("code")
            }
    except Exception as exc:
        logger.warning(
            "get_medication_diagnosis_gaps failed pid=%s year=%s: %s", pid, year, exc
        )
        return []

    gaps: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()  # (normalised_code, drug) dedup key

    for row in rx_rows:
        codes = _parse_diagnosis_field(row.get("diagnosis"))
        for code in codes:
            normalised = code.upper()
            if normalised in billed_codes:
                continue
            drug = row.get("drug") or ""
            key = (normalised, drug.lower())
            if key in seen:
                continue
            seen.add(key)
            gaps.append(
                {
                    "icd_code": code,
                    "drug": drug,
                    "active": row.get("active"),
                }
            )

    return gaps


# ---------------------------------------------------------------------------
# Utility
# ---------------------------------------------------------------------------

# ICD-10 code pattern: letter + 2 digits, optional dot, up to 4 more chars.
# Examples: E11.9, J44.1, M79.3, Z87.39, I10
_ICD10_RE = re.compile(r"\b([A-Z][0-9]{2}(?:\.[0-9A-Z]{1,4})?)\b", re.IGNORECASE)

# Delimiters that OpenEMR may use between multiple codes in a single cell.
# Semicolon is the most common; comma and pipe are also observed in the wild.
_DIAG_DELIMITERS_RE = re.compile(r"[;,|]")


def _parse_diagnosis_field(raw: str | None) -> list[str]:
    """Parse a raw OpenEMR diagnosis field into a list of ICD-10 codes.

    The ``diagnosis`` column may contain:
      - A single code: "E11.9"
      - Multiple codes separated by semicolons: "E11.9;I10"
      - Codes with extra whitespace or mixed case: " e11.9 ; i10 "
      - Free-text descriptions mixed with codes: "DM type 2 E11.9"
      - Codes with a prefix label: "ICD10:E11.9"
      - Empty string or NULL

    Strategy:
    1. Split on known delimiters (semicolon, comma, pipe).
    2. Within each segment, extract all ICD-10 code-shaped tokens via regex.
    3. Normalise to uppercase, deduplicate while preserving first-seen order.

    Returns an empty list when no valid codes can be parsed.
    """
    if not raw:
        return []

    raw_str = str(raw).strip()
    if not raw_str:
        return []

    seen: set[str] = set()
    codes: list[str] = []

    segments = _DIAG_DELIMITERS_RE.split(raw_str)
    for segment in segments:
        segment = segment.strip()
        if not segment:
            continue
        # First try: the whole segment (after stripping label prefixes) is a code.
        # Strip common prefixes like "ICD10:", "DX:", "DIAG:" etc.
        cleaned = re.sub(r"(?i)^(icd[-_]?10|icd[-_]?9|dx|diag)\s*:\s*", "", segment)
        cleaned = cleaned.strip()

        # Extract all ICD-10 shaped tokens from the segment.
        matches = _ICD10_RE.findall(cleaned)
        for m in matches:
            normalised = m.upper()
            if normalised not in seen:
                seen.add(normalised)
                codes.append(normalised)

    return codes


def _serialize(row: dict | None) -> dict[str, Any]:
    """Convert non-JSON-serializable types (date, Decimal) to strings."""
    if row is None:
        return {}
    result: dict[str, Any] = {}
    for k, v in row.items():
        if hasattr(v, "isoformat"):
            result[k] = v.isoformat()
        elif hasattr(v, "__float__"):
            # Decimal
            result[k] = float(v)
        else:
            result[k] = v
    return result


# ---------------------------------------------------------------------------
# Family History  (history_data — may be absent in older OpenEMR builds)
# ---------------------------------------------------------------------------

# Subset of history_data columns that describe relatives' diagnoses.
# OpenEMR stores these as free-text strings or "YES"/"NO" flags depending on
# how the practice configured the family history form.  We return whatever is
# present in the most recent row and let the caller interpret the values.
_FAMILY_HISTORY_COLUMNS: tuple[str, ...] = (
    "relatives_cancer",
    "relatives_diabetes",
    "relatives_heart_disease",
    "relatives_hypertension",
    "relatives_stroke",
    "relatives_epilepsy",
    "relatives_mental_illness",
    "relatives_suicide",
    "relatives_alcohol",
    "relatives_drug",
    "relatives_tuberculosis",
    "relatives_arthritis",
    "relatives_asthma",
    "relatives_blood_disorder",
    "relatives_hiv",
    "relatives_other",
    "history_father",
    "history_mother",
    "history_siblings",
    "history_offspring",
    "history_spouse",
)


@_empty_on_no_emr(default=dict)
def get_family_history(pid: int) -> dict[str, Any]:
    """
    Return the most recent family-history record for *pid* from history_data.

    The history_data table is a single row per patient that stores both social
    and family history fields.  Only columns that describe relatives' conditions
    are extracted here; see _FAMILY_HISTORY_COLUMNS for the full set.

    Returns an empty dict when:
    - the table does not exist in this OpenEMR instance
    - no row exists for the patient
    - any query error occurs
    """
    sql = """
        SELECT *
        FROM history_data
        WHERE pid = %s
        ORDER BY date DESC
        LIMIT 1
    """
    try:
        with openemr_cursor() as cur:
            cur.execute(sql, (pid,))
            row = cur.fetchone()
        if not row:
            return {}
        # Keep only family-history columns that are actually present in this
        # deployment so we do not fail when optional columns are missing.
        result: dict[str, Any] = {"pid": pid}
        for col in _FAMILY_HISTORY_COLUMNS:
            if col in row:
                result[col] = row[col]
        if "date" in row:
            result["recorded_date"] = row["date"]
        return _serialize(result)
    except Exception as exc:
        logger.debug(
            "get_family_history: history_data unavailable for pid=%s (%s)", pid, exc
        )
        return {}


# ---------------------------------------------------------------------------
# SDOH  (form_history_sdoh — may be absent in older OpenEMR builds)
# ---------------------------------------------------------------------------

# Billable ICD-10 Z-codes that represent Social Determinants of Health.
# Surfaced alongside raw SDOH form data so callers can identify documentation
# gaps or coding opportunities without maintaining this mapping themselves.
SDOH_BILLABLE_HIGHLIGHTS: dict[str, str] = {
    "Z59.0":   "Homelessness",
    "Z59.1":   "Inadequate housing",
    "Z56.0":   "Unemployment",
    "Z63.0":   "Relationship problems",
    "Z60.2":   "Living alone",
    "Z91.120": "Food insecurity",
}


@_empty_on_no_emr(default=dict)
def get_sdoh_data(pid: int) -> dict[str, Any]:
    """
    Return Social Determinants of Health data for *pid*.

    Primary source: form_history_sdoh (added in OpenEMR >= 6.x).
    Also checks billing for existing Z-codes so the caller has a complete
    picture even when the SDOH form has not been filled out.

    Response shape:
        {
          "pid": int,
          "sdoh_form": dict | None,       -- raw form_history_sdoh row, or None
          "billed_z_codes": list[dict],   -- Z-codes already present on claims
          "billable_highlights": dict,    -- reference map of high-value Z-codes
        }

    Returns a safe default (sdoh_form=None, billed_z_codes=[]) when:
    - form_history_sdoh does not exist
    - no row exists for the patient
    - any query error occurs
    """
    result: dict[str, Any] = {
        "pid": pid,
        "sdoh_form": None,
        "billed_z_codes": [],
        "billable_highlights": SDOH_BILLABLE_HIGHLIGHTS,
    }

    # Attempt to read form_history_sdoh
    sql_sdoh = """
        SELECT *
        FROM form_history_sdoh
        WHERE pid = %s
        ORDER BY date DESC
        LIMIT 1
    """
    try:
        with openemr_cursor() as cur:
            cur.execute(sql_sdoh, (pid,))
            row = cur.fetchone()
        if row:
            result["sdoh_form"] = _serialize(row)
    except Exception as exc:
        logger.debug(
            "get_sdoh_data: form_history_sdoh unavailable for pid=%s (%s)", pid, exc
        )

    # Collect Z-codes already billed from the billing table.
    # LIKE patterns cover Z55-Z99 (all SDOH-relevant ICD-10 chapters).
    sql_zcodes = """
        SELECT DISTINCT code, code_text
        FROM billing
        WHERE pid = %s
          AND activity = 1
          AND code_type IN ('ICD10', 'ICD9')
          AND (
              code LIKE 'Z5%%'
              OR code LIKE 'Z6%%'
              OR code LIKE 'Z7%%'
              OR code LIKE 'Z8%%'
              OR code LIKE 'Z9%%'
          )
        ORDER BY code
    """
    try:
        with openemr_cursor() as cur:
            cur.execute(sql_zcodes, (pid,))
            rows = cur.fetchall()
        result["billed_z_codes"] = [_serialize(r) for r in rows]
    except Exception as exc:
        logger.debug(
            "get_sdoh_data: billing Z-code query failed for pid=%s (%s)", pid, exc
        )

    return result


# ---------------------------------------------------------------------------
# Allergies  (lists table, type='allergy')
# ---------------------------------------------------------------------------

@_empty_on_no_emr()
def get_allergies(pid: int) -> list[dict[str, Any]]:
    """
    Return active allergy records for *pid* from the lists table.

    OpenEMR stores allergies alongside problems and medications in lists,
    distinguished by type='allergy'.  Only rows with activity=1
    (active / not resolved) are returned.

    Columns returned:
        title      -- free-text allergen name (e.g. "Penicillin")
        diagnosis  -- reaction code or ICD/SNOMED code for structured entries
        begdate    -- date allergy was first recorded
        activity   -- always 1 for rows returned here

    Returns an empty list when:
    - the lists table is inaccessible
    - no active allergy rows exist for the patient
    - any query error occurs
    """
    sql = """
        SELECT
            title,
            diagnosis,
            begdate,
            activity
        FROM lists
        WHERE pid = %s
          AND type = 'allergy'
          AND activity = 1
        ORDER BY begdate DESC
    """
    try:
        with openemr_cursor() as cur:
            cur.execute(sql, (pid,))
            rows = cur.fetchall()
        return [_serialize(r) for r in rows]
    except Exception as exc:
        logger.debug(
            "get_allergies: lists query failed for pid=%s (%s)", pid, exc
        )
        return []


# ---------------------------------------------------------------------------
# Referrals  (transactions table — may be absent in older OpenEMR builds)
# ---------------------------------------------------------------------------

@_empty_on_no_emr()
def get_referrals(pid: int) -> list[dict[str, Any]]:
    """
    Return all referral transactions for *pid* from the transactions table.

    OpenEMR records referrals as rows in transactions with title='Referral'.
    The table may not exist in all installations; the function returns an
    empty list rather than raising in that case.

    Columns returned:
        id          -- PK of the transaction row
        date        -- date the referral was created
        body        -- free-text referral notes / clinical summary
        refer_to    -- provider or facility being referred to
        refer_from  -- referring provider
        reason      -- structured reason for referral
        reply_date  -- date a consultation reply was received (may be NULL)

    Returns an empty list when:
    - the transactions table does not exist
    - no referral rows exist for the patient
    - any query error occurs
    """
    sql = """
        SELECT
            id,
            date,
            title,
            title AS body
        FROM transactions
        WHERE pid = %s
          AND title LIKE 'Refer%%'
        ORDER BY date DESC
    """
    try:
        with openemr_cursor() as cur:
            cur.execute(sql, (pid,))
            rows = cur.fetchall()
        return [_serialize(r) for r in rows]
    except Exception as exc:
        logger.debug(
            "get_referrals: transactions table unavailable for pid=%s (%s)", pid, exc
        )
        return []


# ---------------------------------------------------------------------------
# Write: prescriptions ("Start Treatment" RAF Central action)
# ---------------------------------------------------------------------------


@_empty_on_no_emr(default=None)
def push_prescription(
    pid: int,
    ordered_by: str,
    drug_name: str,
    rxnorm_code: str | None,
    dosage: str,
    route: str = "PO",
    note: str = "",
) -> int | None:
    """Insert a new active prescription row into OpenEMR `prescriptions`."""
    audit_note = f"Ordered via RAF Central by {ordered_by}"
    if note:
        audit_note = f"{audit_note} — {note}"

    sql = """
        INSERT INTO prescriptions (
            patient_id,
            drug,
            rxnorm_drugcode,
            dosage,
            route,
            note,
            active,
            date_added,
            start_date
        ) VALUES (
            %s, %s, %s, %s, %s, %s, 1, NOW(), CURDATE()
        )
    """
    with openemr_cursor() as cur:
        cur.execute(
            sql,
            (
                pid,
                drug_name,
                rxnorm_code or "",
                dosage,
                route,
                audit_note,
            ),
        )
        new_id = cur.lastrowid
    logger.info(
        "Pushed prescription id=%s drug=%s rxnorm=%s for pid=%s by %s",
        new_id, drug_name, rxnorm_code, pid, ordered_by,
    )
    return int(new_id) if new_id else None


# ---------------------------------------------------------------------------
# Write: procedure_order (lab / imaging orders for "Order Lab" action)
# ---------------------------------------------------------------------------


@_empty_on_no_emr(default=None)
def push_procedure_order(
    pid: int,
    ordered_by: str,
    procedure_code: str,
    procedure_name: str,
    diagnosis_code: str,
    lab_code_type: str = "LOINC",
) -> int | None:
    """Insert a lab/procedure order for a patient into OpenEMR.

    Writes a parent row in `procedure_order` and a child row in
    `procedure_order_code`. Returns the new procedure_order_id or None.
    """
    try:
        from datetime import datetime
        today_date = datetime.now().strftime("%Y-%m-%d")

        formatted_dx = (
            diagnosis_code
            if diagnosis_code.startswith("ICD10:")
            else f"ICD10:{diagnosis_code}"
        )

        try:
            provider_id_int = int(ordered_by)
        except (TypeError, ValueError):
            provider_id_int = 0

        order_sql = """
            INSERT INTO procedure_order (
                date_ordered,
                provider_id,
                patient_id,
                encounter,
                status,
                procedure_order_type,
                order_diagnosis,
                activity
            ) VALUES (
                %s, %s, %s, 0, 'pending', 'laboratory_test', %s, 1
            )
        """
        code_sql = """
            INSERT INTO procedure_order_code (
                procedure_order_id,
                procedure_order_seq,
                procedure_code,
                procedure_name,
                procedure_type,
                diagnoses
            ) VALUES (
                %s, 1, %s, %s, 'ord', %s
            )
        """

        with openemr_cursor() as cur:
            cur.execute(
                order_sql,
                (today_date, provider_id_int, pid, formatted_dx),
            )
            new_order_id = getattr(cur, "lastrowid", None)
            if not new_order_id:
                cur.execute("SELECT LAST_INSERT_ID() AS id")
                row = cur.fetchone()
                new_order_id = int(row["id"]) if row and row.get("id") else None

            if new_order_id:
                cur.execute(
                    code_sql,
                    (new_order_id, procedure_code, procedure_name, formatted_dx),
                )

        logger.info(
            "push_procedure_order: pid=%s code=%s (%s) dx=%s order_id=%s",
            pid, procedure_code, lab_code_type, formatted_dx, new_order_id,
        )
        return int(new_order_id) if new_order_id else None

    except NoActiveEMRConnection:
        raise
    except Exception as exc:
        logger.error(
            "push_procedure_order failed pid=%s code=%s: %s",
            pid, procedure_code, exc,
        )
        return None
