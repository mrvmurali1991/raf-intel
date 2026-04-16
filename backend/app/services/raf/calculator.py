# DISCLAIMER: This module calculates CMS-HCC risk adjustment scores using the
# hccinfhir library, which is a third-party open-source implementation of the
# CMS-HCC model. It is NOT validated or endorsed by CMS. Results should be
# verified against the official CMS SAS software before use in payment
# determinations. This tool is designed for clinical analytics, gap identification,
# and prospective risk assessment — not for payment submission.

"""
CMS-HCC V24/V28 Blended RAF Score Calculation Engine.

Main orchestrator — imports from focused sub-modules:
  - icd_formatter       : ICD-10 code formatting, ESRD code sets
  - blend_weights       : blend weight tables, norm/MACI factors, lookups
  - enrollment_resolver : segment determination, enrollment resolution
  - score_persistence   : raf_scores, raf_patient_hcc, raf_patient_demographics upserts

The public surface (calculate_raf_score, calculate_raf_score_multi_model,
calculate_raf_for_all_patients, get_raf_breakdown, get_age_band) is unchanged
from the original monolith.
"""

from __future__ import annotations

import json
import logging
from datetime import date, datetime
from typing import Any, Literal

from hccinfhir import HCCInFHIR, Demographics  # noqa: F401 (Demographics re-exported for compat)

from app.db import raf_cursor, openemr_cursor
from app.cache import cache_get, cache_set, cache_delete_pattern
from app.services.cache_strategy import get_active_connection_id

from app.services.raf.icd_formatter import _format_icd10
from app.services.raf.blend_weights import (
    _BLEND_WEIGHTS,
    _PACE_BLEND_WEIGHTS,
    _NORM_FACTORS_V28,
    _NORM_FACTORS_V24,
    _NORM_FACTORS_V22,
    _NORM_FACTORS,
    _MACI_FACTORS_V28,
    _MACI_FACTORS_V24,
    _MACI_FACTORS,
    _get_norm_factor,
    _get_maci_factor,
)
from app.services.raf.enrollment_resolver import (
    _SEGMENT_TO_PREFIX,
    determine_model_segment,
    _is_new_enrollee,
    _is_esrd,
    _get_enrollment_from_raf_db,
    _resolve_enrollment,
)
from app.services.hcc_hierarchy import (
    V24_HIERARCHY_CHAINS,
    V28_HIERARCHY_CHAINS,
)
from app.services.raf.score_persistence import (
    _get_age_band_from_age,
    _store_patient_hccs,
    _upsert_raf_score,
    _upsert_patient_demographics,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Module-level processor singletons — instantiated once at import time
# ---------------------------------------------------------------------------

_processor_v28 = HCCInFHIR(model_name="CMS-HCC Model V28")
_processor_v24 = HCCInFHIR(model_name="CMS-HCC Model V24")
_processor_v22 = HCCInFHIR(model_name="CMS-HCC Model V22")
_processor_esrd_v24 = HCCInFHIR(model_name="CMS-HCC ESRD Model V24")

# Backward-compat alias so existing callers referencing _processor still work
_processor = _processor_v28

# ---------------------------------------------------------------------------
# New Enrollee (NE) Demographic Coefficient Tables
# Source: CMS Annual Announcement Tables for MA Payment Rates
# These are age/sex demographic scores for beneficiaries with < 12 months
# of Part B enrollment (no HCC disease coding applied).
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Official CMS V28 New Enrollee Demographic Coefficients
# Source: risk_adjustment_model v0.5.3 → CMS V28 2024 weights.csv
#
# CMS NE model has 4 segments based on two axes:
#   Medicaid: NMCAID (non-Medicaid) vs MCAID (Medicaid — full or partial dual)
#   Originally Disabled: NORIGDIS (not) vs ORIGDIS (originally disabled)
#
# Internal segment mapping:
#   CNA (non-dual aged)         → NE_NMCAID_NORIGDIS
#   CND (non-dual disabled)     → NE_NMCAID_ORIGDIS
#   CFA (full-dual aged)        → NE_MCAID_NORIGDIS
#   CFD (full-dual disabled)    → NE_MCAID_ORIGDIS
#   CPA (partial-dual aged)     → NE_MCAID_NORIGDIS
#   CPD (partial-dual disabled) → NE_MCAID_ORIGDIS
#
# Ages 65-69 use individual-age coefficients per CMS (not banded).
# ---------------------------------------------------------------------------

# CMS NE segment coefficients keyed by (age_key, sex, cms_ne_segment)
# age_key: individual age str for 65-69 ("65","66",...), age band otherwise
_NE_CMS_COEFFICIENTS: dict[str, dict[tuple[str, str], float]] = {
    # ── NE_NMCAID_NORIGDIS (CNA / non-Medicaid, not originally disabled) ──
    "NE_NMCAID_NORIGDIS": {
        ("0-34", "F"): 0.711, ("0-34", "M"): 0.409,
        ("35-44", "F"): 0.950, ("35-44", "M"): 0.669,
        ("45-54", "F"): 1.155, ("45-54", "M"): 0.906,
        ("55-59", "F"): 1.152, ("55-59", "M"): 0.984,
        ("60-64", "F"): 1.212, ("60-64", "M"): 1.057,
        ("65", "F"): 0.532, ("65", "M"): 0.567,
        ("66", "F"): 0.532, ("66", "M"): 0.576,
        ("67", "F"): 0.557, ("67", "M"): 0.617,
        ("68", "F"): 0.584, ("68", "M"): 0.678,
        ("69", "F"): 0.625, ("69", "M"): 0.684,
        ("70-74", "F"): 0.694, ("70-74", "M"): 0.808,
        ("75-79", "F"): 0.901, ("75-79", "M"): 1.049,
        ("80-84", "F"): 0.988, ("80-84", "M"): 1.245,
        ("85-89", "F"): 1.287, ("85-89", "M"): 1.516,
        ("90-94", "F"): 1.287, ("90-94", "M"): 1.516,
        ("95+", "F"): 1.287, ("95+", "M"): 1.516,
    },
    # ── NE_MCAID_NORIGDIS (CFA, CPA / Medicaid, not originally disabled) ──
    "NE_MCAID_NORIGDIS": {
        ("0-34", "F"): 1.025, ("0-34", "M"): 0.738,
        ("35-44", "F"): 1.303, ("35-44", "M"): 1.264,
        ("45-54", "F"): 1.415, ("45-54", "M"): 1.420,
        ("55-59", "F"): 1.289, ("55-59", "M"): 1.477,
        ("60-64", "F"): 1.396, ("60-64", "M"): 1.542,
        ("65", "F"): 0.986, ("65", "M"): 1.182,
        ("66", "F"): 0.990, ("66", "M"): 1.234,
        ("67", "F"): 1.004, ("67", "M"): 1.319,
        ("68", "F"): 1.004, ("68", "M"): 1.367,
        ("69", "F"): 1.004, ("69", "M"): 1.455,
        ("70-74", "F"): 1.043, ("70-74", "M"): 1.455,
        ("75-79", "F"): 1.128, ("75-79", "M"): 1.455,
        ("80-84", "F"): 1.342, ("80-84", "M"): 1.503,
        ("85-89", "F"): 1.563, ("85-89", "M"): 1.682,
        ("90-94", "F"): 1.712, ("90-94", "M"): 1.981,
        ("95+", "F"): 1.712, ("95+", "M"): 1.981,
    },
    # ── NE_NMCAID_ORIGDIS (CND / non-Medicaid, originally disabled) ──
    # Under-65 coefficients are 0.0 (can't be originally disabled under 65 in this segment)
    "NE_NMCAID_ORIGDIS": {
        ("65", "F"): 1.212, ("65", "M"): 1.057,
        ("66", "F"): 1.276, ("66", "M"): 1.155,
        ("67", "F"): 1.276, ("67", "M"): 1.155,
        ("68", "F"): 1.276, ("68", "M"): 1.155,
        ("69", "F"): 1.276, ("69", "M"): 1.297,
        ("70-74", "F"): 1.276, ("70-74", "M"): 1.297,
        ("75-79", "F"): 1.276, ("75-79", "M"): 1.297,
        ("80-84", "F"): 1.276, ("80-84", "M"): 1.297,
        ("85-89", "F"): 1.287, ("85-89", "M"): 1.516,
        ("90-94", "F"): 1.287, ("90-94", "M"): 1.516,
        ("95+", "F"): 1.287, ("95+", "M"): 1.516,
    },
    # ── NE_MCAID_ORIGDIS (CFD, CPD / Medicaid, originally disabled) ──
    "NE_MCAID_ORIGDIS": {
        ("65", "F"): 1.599, ("65", "M"): 1.727,
        ("66", "F"): 1.599, ("66", "M"): 1.959,
        ("67", "F"): 1.599, ("67", "M"): 1.959,
        ("68", "F"): 2.021, ("68", "M"): 1.959,
        ("69", "F"): 2.021, ("69", "M"): 1.959,
        ("70-74", "F"): 2.021, ("70-74", "M"): 1.959,
        ("75-79", "F"): 2.021, ("75-79", "M"): 2.813,
        ("80-84", "F"): 2.021, ("80-84", "M"): 2.813,
        ("85-89", "F"): 2.021, ("85-89", "M"): 2.813,
        ("90-94", "F"): 2.021, ("90-94", "M"): 2.813,
        ("95+", "F"): 2.021, ("95+", "M"): 2.813,
    },
}

# Internal segment → CMS NE segment mapping
# Note: ORIGDIS segments are for 65+ beneficiaries who originally qualified via
# disability (OREC=1). Under-65 disabled use the NORIGDIS segment.
# The ORIGDIS determination requires OREC and is handled in _calculate_new_enrollee_score.
_SEGMENT_TO_NE_CMS: dict[str, str] = {
    "CNA": "NE_NMCAID_NORIGDIS",
    "CND": "NE_NMCAID_NORIGDIS",   # under-65 disabled → NORIGDIS
    "CFA": "NE_MCAID_NORIGDIS",
    "CFD": "NE_MCAID_NORIGDIS",    # under-65 disabled → NORIGDIS
    "CPA": "NE_MCAID_NORIGDIS",    # partial dual = Medicaid
    "CPD": "NE_MCAID_NORIGDIS",    # under-65 disabled → NORIGDIS
}


def _ne_age_key(age: int) -> str:
    """Return NE-specific age key: individual age for 65-69, band otherwise."""
    if 65 <= age <= 69:
        return str(age)
    return _get_age_band_from_age(age)


# Backward-compat shim: flat dict used by tests and external callers.
# Populated from _NE_CMS_COEFFICIENTS using averaged 65-69 band for compat.
_NE_DEMO_SCORES: dict[tuple[str, str, str], float] = {}
for _seg_internal, _cms_seg in _SEGMENT_TO_NE_CMS.items():
    _coeffs = _NE_CMS_COEFFICIENTS[_cms_seg]
    for (_age_key, _sex), _val in _coeffs.items():
        # For individual ages 65-69, aggregate into "65-69" band via first-wins
        if _age_key in ("65", "66", "67", "68", "69"):
            _band_key = ("65-69", _sex, _seg_internal)
            if _band_key not in _NE_DEMO_SCORES:
                # Use age-67 as representative midpoint for backward compat
                _mid = _coeffs.get(("67", _sex), _val)
                _NE_DEMO_SCORES[_band_key] = _mid
        else:
            _NE_DEMO_SCORES[(_age_key, _sex, _seg_internal)] = _val

# Official CMS V28 ESRD Dialysis (DI) demographic base scores by age/sex
# Source: hccpy ESRDhcccoefn.csv — CMS V28 ESRD model coefficients
# GC (Graft Complication) and GI (Graft Failure) have identical demographic
# coefficients to DI in the current V28 ESRD model.
_ESRD_DLY_DEMO_SCORES: dict[tuple[str, str], float] = {
    ("0-34", "F"): 0.618,
    ("0-34", "M"): 0.527,
    ("35-44", "F"): 0.567,
    ("35-44", "M"): 0.502,
    ("45-54", "F"): 0.522,
    ("45-54", "M"): 0.478,
    ("55-59", "F"): 0.535,
    ("55-59", "M"): 0.495,
    ("60-64", "F"): 0.553,
    ("60-64", "M"): 0.498,
    ("65-69", "F"): 0.635,
    ("65-69", "M"): 0.562,
    ("70-74", "F"): 0.653,
    ("70-74", "M"): 0.611,
    ("75-79", "F"): 0.658,
    ("75-79", "M"): 0.634,
    ("80-84", "F"): 0.671,
    ("80-84", "M"): 0.652,
    ("85-89", "F"): 0.671,
    ("85-89", "M"): 0.663,
    ("90-94", "F"): 0.671,
    ("90-94", "M"): 0.663,
    ("95+", "F"): 0.671,
    ("95+", "M"): 0.663,
}

# Official CMS V28 ESRD Functioning Graft demographic base scores
# GC/GI segments share identical demographics with DI in V28
_ESRD_FG_DEMO_SCORES: dict[tuple[str, str], float] = {
    ("0-34", "F"): 0.618,
    ("0-34", "M"): 0.527,
    ("35-44", "F"): 0.567,
    ("35-44", "M"): 0.502,
    ("45-54", "F"): 0.522,
    ("45-54", "M"): 0.478,
    ("55-59", "F"): 0.535,
    ("55-59", "M"): 0.495,
    ("60-64", "F"): 0.553,
    ("60-64", "M"): 0.498,
    ("65-69", "F"): 0.635,
    ("65-69", "M"): 0.562,
    ("70-74", "F"): 0.653,
    ("70-74", "M"): 0.611,
    ("75-79", "F"): 0.658,
    ("75-79", "M"): 0.634,
    ("80-84", "F"): 0.671,
    ("80-84", "M"): 0.652,
    ("85-89", "F"): 0.671,
    ("85-89", "M"): 0.663,
    ("90-94", "F"): 0.671,
    ("90-94", "M"): 0.663,
    ("95+", "F"): 0.671,
    ("95+", "M"): 0.663,
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _calculate_age(dob: str | date | datetime, as_of_year: int | None = None) -> int:
    """Calculate age as of Feb 1 of measurement year (CMS convention)."""
    if isinstance(dob, str):
        dob = datetime.strptime(dob[:10], "%Y-%m-%d").date()
    elif isinstance(dob, datetime):
        dob = dob.date()
    ref = date(as_of_year or date.today().year, 2, 1)
    age = ref.year - dob.year - ((ref.month, ref.day) < (dob.month, dob.day))
    return max(0, age)


# Backward-compat alias used in tests and a few internal callers
_calc_age = _calculate_age


def _sex_code(sex_str: str) -> str:
    """Normalize sex to M/F."""
    s = (sex_str or "").strip().upper()
    if s.startswith("F"):
        return "F"
    return "M"


def _get_patient(patient_id: int, tenant_id: str = "") -> dict[str, Any] | None:
    """Get patient from raf_intelligence.patients table, with fallback to emr_patient_matches.

    Returns a dict with legacy OpenEMR-compatible keys (pid, fname, lname, DOB,
    sex) so downstream code that references those keys continues to work.

    FHIR patients are stored in emr_patient_matches (not in patients).  When the
    patients table has no row for *patient_id* we fall back to emr_patient_matches
    so that RAF calculations succeed for FHIR-sourced patients.
    """
    with raf_cursor() as cur:
        cur.execute(
            "SELECT id, emr_pid, first_name, last_name, dob, sex FROM patients WHERE id = %s AND tenant_id = %s",
            (patient_id, tenant_id),
        )
        row = cur.fetchone()
    if row:
        return {
            "pid": row["id"],
            "emr_pid": row["emr_pid"],
            "fname": row["first_name"],
            "lname": row["last_name"],
            "DOB": row["dob"],
            "dob": row["dob"],
            "sex": row["sex"],
        }

    # Fallback: FHIR patient stored in emr_patient_matches
    try:
        with raf_cursor() as cur:
            cur.execute(
                "SELECT epm.id, epm.first_name, epm.last_name, epm.date_of_birth, epm.sex "
                "FROM emr_patient_matches epm "
                "JOIN emr_connections ec ON ec.id = epm.connection_id "
                "WHERE epm.id = %s AND ec.is_active = 1 "
                "AND ec.connection_type IN ('fhir_r4', 'rest_api') LIMIT 1",
                (patient_id,),
            )
            fhir_row = cur.fetchone()
        if fhir_row:
            dob_raw = fhir_row.get("date_of_birth")
            dob_str = (
                dob_raw.isoformat()
                if hasattr(dob_raw, "isoformat")
                else (str(dob_raw) if dob_raw else None)
            )
            return {
                "pid": fhir_row["id"],
                "emr_pid": None,  # No OpenEMR pid; ICD codes come from raf_patient_hcc
                "fname": fhir_row.get("first_name") or "",
                "lname": fhir_row.get("last_name") or "",
                "DOB": dob_str,
                "dob": dob_str,
                "sex": fhir_row.get("sex") or "M",
                "data_source": "fhir",
            }
    except Exception as exc:
        logger.debug("_get_patient: FHIR fallback failed for pid=%s: %s", patient_id, exc)

    return None


def _get_icd_codes(
    patient_id: int,
    year: int | None = None,
    dos_start: date | None = None,
    dos_end: date | None = None,
    include_suspected: bool = False,
    tenant_id: str = "",
) -> list[str]:
    """Get unique ICD-10 codes from OpenEMR billing + AI analysis results.

    CMS compliance: diagnoses used for risk adjustment MUST come from the
    CMS data collection period only (encounters dated within the applicable
    sweep window). Mixing older diagnoses into a later payment year overstates
    RAF and violates CMS risk-adjustment rules.

    When *year* (measurement_year) is provided without an explicit DOS window,
    a mandatory default window is derived: Jan 1 of (year-1) through
    Dec 31 of year. Callers may override by passing *dos_start* / *dos_end*.

    *patient_id* is the raf_intelligence patients.id; we resolve emr_pid for
    OpenEMR clinical queries.
    """
    # CMS requires diagnoses from the data collection period only. If a
    # measurement year is specified but no DOS window was passed, derive the
    # default two-calendar-year window mandated by CMS.
    if year is not None and dos_start is None and dos_end is None:
        dos_start = date(year - 1, 1, 1)
        dos_end = date(year, 12, 31)

    codes: set[str] = set()

    # Resolve emr_pid for OpenEMR billing lookup
    emr_pid: int | None = None
    with raf_cursor() as cur:
        if tenant_id:
            cur.execute(
                "SELECT emr_pid FROM patients WHERE id = %s AND tenant_id = %s",
                (patient_id, tenant_id),
            )
        else:
            cur.execute("SELECT emr_pid FROM patients WHERE id = %s", (patient_id,))
        row = cur.fetchone()
        if row:
            emr_pid = row["emr_pid"]

    # 1. Billing codes from OpenEMR (filtered by encounter DOS window)
    if emr_pid is not None:
        try:
            with openemr_cursor(tenant_id=tenant_id) as cur:
                if dos_start is not None or dos_end is not None:
                    conditions = [
                        "b.pid = %s",
                        "b.code_type = 'ICD10'",
                        "b.activity = 1",
                    ]
                    params: list[Any] = [emr_pid]
                    if dos_start is not None:
                        conditions.append("fe.date >= %s")
                        params.append(str(dos_start))
                    if dos_end is not None:
                        conditions.append("fe.date <= %s")
                        params.append(str(dos_end) + " 23:59:59")
                    sql = (
                        "SELECT DISTINCT b.code FROM billing b "
                        "JOIN form_encounter fe ON b.encounter = fe.encounter AND b.pid = fe.pid "
                        "WHERE " + " AND ".join(conditions)
                    )
                    cur.execute(sql, tuple(params))
                else:
                    cur.execute(
                        "SELECT DISTINCT code FROM billing WHERE pid = %s AND code_type = 'ICD10' AND activity = 1",
                        (emr_pid,),
                    )
                for r in cur.fetchall():
                    if r.get("code"):
                        codes.add(r["code"])
        except Exception as exc:
            logger.debug(
                "_get_icd_codes: OpenEMR billing lookup failed for pid=%s: %s",
                patient_id,
                exc,
            )

    # 1b. Normalized encounter_diagnoses in RAF DB (covers direct_db + FHIR sources)
    try:
        with raf_cursor() as cur:
            ed_conditions = ["ed.patient_id = %s"]
            ed_params: list[Any] = [patient_id]
            if tenant_id:
                ed_conditions.append("ed.tenant_id = %s")
                ed_params.append(tenant_id)
            if dos_start is not None:
                ed_conditions.append("e.encounter_date >= %s")
                ed_params.append(str(dos_start))
            if dos_end is not None:
                ed_conditions.append("e.encounter_date <= %s")
                ed_params.append(str(dos_end) + " 23:59:59")
            sql = (
                "SELECT DISTINCT ed.icd10_code FROM encounter_diagnoses ed "
                "JOIN encounters e ON e.id = ed.encounter_id "
                "WHERE " + " AND ".join(ed_conditions)
            )
            cur.execute(sql, tuple(ed_params))
            for r in cur.fetchall():
                code = r.get("icd10_code")
                if code:
                    codes.add(code.strip())
    except Exception as exc:
        logger.debug("_get_icd_codes: encounter_diagnoses lookup failed for pid=%s: %s", patient_id, exc)

    # 2. AI-analyzed codes from raf_encounter_analysis (filtered by encounter DOS window)
    if not include_suspected:
        return list(codes)

    try:
        import json as _json

        with raf_cursor() as cur:
            if dos_start is not None or dos_end is not None:
                ea_conditions = [
                    "ea.patient_id = %s",
                    "ea.analysis_json IS NOT NULL",
                ]
                ea_params: list[Any] = [patient_id]
                if dos_start is not None:
                    ea_conditions.append("fe.date >= %s")
                    ea_params.append(str(dos_start))
                if dos_end is not None:
                    ea_conditions.append("fe.date <= %s")
                    ea_params.append(str(dos_end) + " 23:59:59")
                ea_sql = (
                    "SELECT ea.analysis_json FROM raf_encounter_analysis ea "
                    "JOIN form_encounter fe ON fe.encounter = ea.encounter_id "
                    "WHERE " + " AND ".join(ea_conditions)
                )
                cur.execute(ea_sql, tuple(ea_params))
            else:
                cur.execute(
                    "SELECT analysis_json FROM raf_encounter_analysis "
                    "WHERE patient_id = %s AND analysis_json IS NOT NULL",
                    (patient_id,),
                )
            for row in cur.fetchall():
                analysis = row.get("analysis_json")
                if isinstance(analysis, str):
                    try:
                        analysis = _json.loads(analysis)
                    except Exception:
                        continue
                if not isinstance(analysis, dict):
                    continue
                for dx in analysis.get("diagnoses", []):
                    code = dx.get("icd10_code") or dx.get("code") or ""
                    if code:
                        codes.add(code.strip())
    except Exception as exc:
        logger.debug(
            "_get_icd_codes: AI analysis lookup failed for pid=%s: %s", patient_id, exc
        )

    return list(codes)


# ---------------------------------------------------------------------------
# HCC hierarchy enforcement
# ---------------------------------------------------------------------------

# Map internal model_version label to the model_year stored in
# hcc_hierarchy_rules.
#
# EXPECTED SEED DATA:
#   The hcc_hierarchy_rules table is expected to be populated from the CMS
#   HCC hierarchy files for the given model year. In this repo, both
#   `scripts/import_raf_coefficients.py` (MODEL_YEAR=2024) and
#   `backend/app/seed_raf_demo.py` insert the V28 hierarchy rules with
#   model_year=2024. The schema column also defaults to 2024. No V24-era
#   rules (historically published under model_year 2020) are currently
#   seeded; to enable V24 hierarchy suppression, load the CMS V24 hierarchy
#   file into hcc_hierarchy_rules with model_year=2020.
#
# IMPORTANT: the values below MUST match the model_year values that actually
# exist in hcc_hierarchy_rules, otherwise `_load_hierarchy_rules()` returns
# zero rows and RAF scores will be silently inflated (no suppression).
_HIERARCHY_MODEL_YEAR = {"v24": 2020, "v28": 2024}

# Map model version labels to the embedded in-memory chain lists used as
# fallback when hcc_hierarchy_rules DB table is empty.
_HIERARCHY_CHAINS_FALLBACK = {
    "v24": V24_HIERARCHY_CHAINS,
    "v28": V28_HIERARCHY_CHAINS,
}


def _chains_to_rules(
    chains: list[tuple[int, ...]],
) -> list[tuple[int, int]]:
    """Convert a chain list to (trumping_hcc, trumped_hcc) pairs for _apply_hcc_hierarchy."""
    pairs: list[tuple[int, int]] = []
    for chain in chains:
        for i in range(1, len(chain)):
            trumped_hcc = chain[i]
            for j in range(i):
                trumping_hcc = chain[j]
                pairs.append((trumping_hcc, trumped_hcc))
    return pairs


def _load_hierarchy_rules(model_version: str) -> list[tuple[int, int]]:
    """Load (trumping_hcc, trumped_hcc) pairs from hcc_hierarchy_rules for the
    given model version. Returns an empty list on any error so that hierarchy
    enforcement fails safely (degrading to no suppression rather than crashing
    the RAF calculation)."""
    model_year = _HIERARCHY_MODEL_YEAR.get(model_version.lower())
    if model_year is None:
        logger.warning(
            "HCC HIERARCHY DISABLED: no _HIERARCHY_MODEL_YEAR mapping for "
            "model_version=%r; RAF scores will NOT have hierarchy suppression "
            "applied and may be inflated.",
            model_version,
        )
        return []
    try:
        with raf_cursor() as cur:
            cur.execute(
                "SELECT trumped_by_hcc, hcc_code FROM hcc_hierarchy_rules "
                "WHERE model_year = %s",
                (model_year,),
            )
            rows = [
                (int(r["trumped_by_hcc"]), int(r["hcc_code"])) for r in cur.fetchall()
            ]
            if not rows:
                logger.warning(
                    "hcc_hierarchy_rules is EMPTY for model_version=%s "
                    "(model_year=%s). Falling back to in-memory %s chains.",
                    model_version,
                    model_year,
                    model_version.upper(),
                )
                fallback_chains = _HIERARCHY_CHAINS_FALLBACK.get(
                    model_version.lower(), V28_HIERARCHY_CHAINS
                )
                return _chains_to_rules(fallback_chains)
            return rows
    except Exception as exc:
        logger.warning(
            "hcc_hierarchy_rules lookup failed for %s: %s", model_version, exc
        )
        return []


def _apply_hcc_hierarchy(calc: dict[str, Any], model_version: str) -> dict[str, Any]:
    """Enforce CMS-HCC hierarchy on a `_run_single_model` result.

    CMS HCC hierarchy: a more severe HCC suppresses ("trumps") less severe
    related HCCs so a patient is not double-counted for the same condition
    family (e.g., HCC 8 trumps HCC 9/10/11). Without this step, both parent
    and child HCCs would be summed and RAF would be overstated.

    The function loads rules from `hcc_hierarchy_rules`, computes the set of
    HCCs to suppress based on which trumping HCCs the patient actually has,
    then removes them from hcc_list / hcc_contributions / all_coefficients and
    recomputes disease_score, raw_raf and payment_raf. Mutates and returns
    *calc* in place.
    """
    rules = _load_hierarchy_rules(model_version)
    if not rules:
        return calc

    present: set[int] = set()
    for h in calc.get("hcc_list", []) or []:
        try:
            present.add(int(h))
        except (TypeError, ValueError):
            continue

    suppressed: set[int] = set()
    for trumping_hcc, trumped_hcc in rules:
        if trumping_hcc in present:
            suppressed.add(trumped_hcc)
    # Never suppress an HCC that the patient only has via hierarchy itself
    suppressed &= present

    if not suppressed:
        return calc

    suppressed_str = {str(h) for h in suppressed}
    removed_coef_total = 0.0
    new_contribs = []
    for contrib in calc.get("hcc_contributions", []) or []:
        if str(contrib.get("hcc_code")) in suppressed_str:
            removed_coef_total += float(contrib.get("coefficient") or 0.0)
        else:
            new_contribs.append(contrib)
    calc["hcc_contributions"] = new_contribs

    calc["hcc_list"] = [
        h for h in (calc.get("hcc_list") or []) if str(h) not in suppressed_str
    ]

    all_coef = calc.get("all_coefficients") or {}
    # Strip any coefficient key whose HCC number is suppressed (keys look like
    # "CNA_HCC8" or similar). Only remove if the key clearly maps to a
    # suppressed HCC number to avoid touching demographic coefficients.
    filtered_coef = {}
    for k, v in all_coef.items():
        drop = False
        for hcc_num in suppressed_str:
            if k.endswith("HCC" + hcc_num) or k.endswith("_" + hcc_num):
                drop = True
                break
        if not drop:
            filtered_coef[k] = v
    calc["all_coefficients"] = filtered_coef

    old_disease = float(calc.get("disease_score") or 0.0)
    new_disease = round(old_disease - removed_coef_total, 4)
    calc["disease_score"] = new_disease

    demographic_score = float(calc.get("demographic_score") or 0.0)
    interaction_score = float(calc.get("interaction_score") or 0.0)
    new_raw = round(demographic_score + new_disease + interaction_score, 4)
    calc["raw_raf"] = new_raw
    calc["subtotal"] = new_raw

    norm_factor = float(calc.get("norm_factor") or 1.0) or 1.0
    maci = float(calc.get("maci_factor") or 0.0)
    calc["payment_raf"] = round(new_raw * (1 - maci) / norm_factor, 4)

    # Mirror updates into the engine_output snapshot so audit trails stay consistent
    eng_out = calc.get("engine_output") or {}
    eng_out["hcc_list"] = [str(h) for h in calc["hcc_list"]]
    eng_out["hcc_details"] = [
        d
        for d in (eng_out.get("hcc_details") or [])
        if str(d.get("hcc")) not in suppressed_str
    ]
    eng_out["all_coefficients"] = filtered_coef
    eng_out["risk_score_raw"] = new_raw
    eng_out["risk_score_payment"] = calc["payment_raf"]
    calc["engine_output"] = eng_out

    logger.info(
        "HCC hierarchy (%s): suppressed %d HCC(s) %s — disease %.4f → %.4f",
        model_version,
        len(suppressed),
        sorted(suppressed),
        old_disease,
        new_disease,
    )
    return calc


# ---------------------------------------------------------------------------
# Core single-model calculation helper
# ---------------------------------------------------------------------------


def _run_single_model(
    processor: HCCInFHIR,
    icd_codes: list[str],
    age: int,
    sex: str,
    model_segment: str,
    norm_factor: float,
    maci: float,
    *,
    orec: str = "0",
    dual_elgbl_cd: str = "NA",
    new_enrollee: bool = False,
    institutional: bool = False,
    graft_months: int | None = None,
) -> dict[str, Any]:
    """
    Execute one hccinfhir processor call and return a structured result dict.

    Returns all score components, HCC list, coefficients, and interactions.
    Does NOT persist anything — purely computational.

    Passes orec, dual_elgbl_cd, new_enrollee, institutional, and graft_months
    to hccinfhir so it can auto-detect the correct coefficient prefix
    (DI_ for ESRD dialysis, GC_ for graft, CFA_ for full-dual, etc.).
    """
    prefix = _SEGMENT_TO_PREFIX.get(model_segment, "CNA_")

    # For ESRD-specific processors, let hccinfhir auto-detect the correct
    # prefix (DI_, GC_, DNE_, GNE_) from orec/demographics rather than
    # forcing a community prefix. The ESRD model has its own prefix logic.
    is_esrd_processor = "ESRD" in (processor.model_name or "")
    effective_prefix = None if is_esrd_processor else prefix

    # Capture exact input sent to the engine
    engine_input = {
        "icd_codes": list(icd_codes),
        "age": age,
        "sex": sex,
        "prefix_override": effective_prefix,
        "model_segment": model_segment,
        "maci": maci,
        "norm_factor": norm_factor,
        "orec": orec,
        "dual_elgbl_cd": dual_elgbl_cd,
    }

    result = processor.calculate_from_diagnosis(
        icd_codes,
        age=age,
        sex=sex,
        orec=orec,
        dual_elgbl_cd=dual_elgbl_cd,
        new_enrollee=new_enrollee,
        lti=institutional,
        graft_months=graft_months,
        prefix_override=effective_prefix,
        maci=maci,
        norm_factor=norm_factor,
    )

    hcc_list = result.hcc_list or []
    all_coefficients = result.coefficients or {}

    demographic_score: float = getattr(result, "risk_score_demographics", 0.0)
    disease_score: float = sum(h.coefficient or 0.0 for h in result.hcc_details)
    interaction_score: float = getattr(result, "risk_score_interaction", None)
    if interaction_score is None:
        interaction_score = result.risk_score - demographic_score - disease_score

    cc_to_dx = result.cc_to_dx or {}
    hcc_contributions = [
        {
            "hcc_code": str(h.hcc),
            "coefficient": h.coefficient,
            "label": h.label,
            "is_chronic": h.is_chronic,
            "icd10_codes": [
                _format_icd10(c)
                for c in cc_to_dx.get(str(h.hcc), cc_to_dx.get(h.hcc, []))
            ],
        }
        for h in result.hcc_details
    ]

    raw_raf = result.risk_score
    payment_raf = result.risk_score_payment

    # Capture exact output from the engine
    engine_output = {
        "risk_score_raw": raw_raf,
        "risk_score_payment": payment_raf,
        "risk_score_demographics": round(demographic_score, 4),
        "hcc_list": [str(h) for h in hcc_list],
        "hcc_details": [
            {"hcc": str(h.hcc), "coefficient": h.coefficient, "label": h.label}
            for h in result.hcc_details
        ],
        "all_coefficients": {k: round(v, 4) for k, v in all_coefficients.items()},
    }

    return {
        "raw_raf": max(0.0, raw_raf),
        "payment_raf": max(0.0, payment_raf),
        "demographic_score": max(0.0, round(demographic_score, 4)),
        "disease_score": max(0.0, round(disease_score, 4)),
        "interaction_score": max(0.0, round(interaction_score, 4)),
        "subtotal": max(0.0, round(demographic_score + disease_score + interaction_score, 4)),
        "hcc_list": [str(h) for h in hcc_list],
        "hcc_contributions": hcc_contributions,
        "all_coefficients": {k: round(v, 4) for k, v in all_coefficients.items()},
        "interactions_fired": {
            k: v for k, v in (result.interactions or {}).items() if v
        },
        "norm_factor": norm_factor,
        "maci_factor": maci,
        "engine_input": engine_input,
        "engine_output": engine_output,
        # Keep the raw hccinfhir result for persistence helpers
        "_result_obj": result,
    }


# ---------------------------------------------------------------------------
# New Enrollee and ESRD score helpers
# ---------------------------------------------------------------------------


def _calculate_new_enrollee_score(
    age: int,
    sex: str,
    model_segment: str,
    orec: str | None = None,
) -> dict[str, Any]:
    """
    Calculate New Enrollee score — purely demographic, no HCC coding.

    CMS applies only an age/sex/dual demographic base score for beneficiaries
    with less than 12 months of Part B enrollment. All condition-based HCC
    disease scores are suppressed.

    OREC (Original Reason for Entitlement Code) determines ORIGDIS segments:
      OREC=1 and age>=65 → originally disabled, now aged into Medicare.
    """
    # Validate / normalize sex
    if sex not in ("M", "F"):
        sex = _sex_code(sex)
    # Clamp age to valid range
    if age < 0:
        logger.warning("NE scoring: invalid age %d, clamping to 0", age)
        age = 0

    # NE segments map like: NE_CNA → CNA, NE_CFD → CFD, etc.
    base_seg = (
        model_segment.replace("NE_", "") if model_segment.startswith("NE_") else "CNA"
    )
    if base_seg not in _SEGMENT_TO_NE_CMS:
        logger.warning("NE scoring: unknown segment %s, defaulting to CNA", model_segment)
    # Determine CMS NE segment — check for Originally Disabled override
    cms_ne_seg = _SEGMENT_TO_NE_CMS.get(base_seg, "NE_NMCAID_NORIGDIS")
    if orec == "1" and age >= 65:
        # Originally disabled, now aged — use ORIGDIS segment
        if "NMCAID" in cms_ne_seg:
            cms_ne_seg = "NE_NMCAID_ORIGDIS"
        else:
            cms_ne_seg = "NE_MCAID_ORIGDIS"
    # Use individual-age lookup for 65-69 per CMS spec
    age_key = _ne_age_key(age)
    coeffs = _NE_CMS_COEFFICIENTS.get(cms_ne_seg, {})
    demo_score = coeffs.get((age_key, sex), 0.532)  # default: NMCAID F age 65

    return {
        "is_new_enrollee": True,
        "ne_segment": model_segment,
        "ne_base_segment": base_seg,
        "demographic_score": round(demo_score, 4),
        "disease_score": 0.0,
        "interaction_score": 0.0,
        "subtotal": round(demo_score, 4),
        "hcc_list": [],
        "hcc_contributions": [],
        "all_coefficients": {},
        "interactions_fired": {},
        "model_note": (
            "New Enrollee: less than 12 months Part B coverage. "
            "CMS applies demographic-only scoring — HCC disease codes are suppressed."
        ),
    }


def _calculate_esrd_demographic_score(
    age: int,
    sex: str,
    esrd_segment: str,
) -> float:
    """
    Return the ESRD demographic base score for the given segment.
    ESRD patients have separate, higher demographic base scores.
    """
    age_band = _get_age_band_from_age(age)
    if esrd_segment == "ESRD_DLY":
        return _ESRD_DLY_DEMO_SCORES.get((age_band, sex), 0.635)
    if esrd_segment == "ESRD_FG":
        return _ESRD_FG_DEMO_SCORES.get((age_band, sex), 0.635)
    # ESRD_NE — use DLY as baseline
    return _ESRD_DLY_DEMO_SCORES.get((age_band, sex), 0.635)


# ---------------------------------------------------------------------------
# HCC label/coefficient lookup helpers (kept for backward compat)
# ---------------------------------------------------------------------------


def _get_hcc_label_v28(hcc_code: str) -> str:
    """Get human-readable label for a V28 HCC code."""
    return f"HCC {hcc_code}"


def _get_hcc_coefficient_v28(hcc_code: str, segment: str = "CNA") -> float:
    """Get the coefficient for a V28 HCC code and segment."""
    try:
        cm = _processor_v28.coefficients_mapping or {}
        target = f"{segment.lower()}_hcc{hcc_code}"
        for (k, model), v in cm.items():
            if k.lower() == target and "V28" in model:
                return float(v)
    except Exception:
        pass
    return 0.0


def _enrich_hcc_details(
    hcc_codes: list[str], patient_id: int, year: int, segment: str, tenant_id: str = ""
) -> dict:
    """Get labels and coefficients for HCC codes by running hccinfhir calculation."""
    try:
        patient = _get_patient(patient_id, tenant_id=tenant_id)
        if not patient:
            return []
        age = _calculate_age(patient.get("DOB"), year)
        sex_raw = (patient.get("sex") or "").strip().upper()
        sex = "M" if sex_raw.startswith("M") else "F"
        # Get ICD codes from raf_patient_hcc
        icd_codes = []
        with raf_cursor() as cur:
            cur.execute(
                "SELECT icd10_codes FROM raf_patient_hcc WHERE patient_id=%s AND measurement_year=%s",
                (patient_id, year),
            )
            for row in cur.fetchall():
                codes = row["icd10_codes"]
                if isinstance(codes, str):
                    codes = json.loads(codes)
                icd_codes.extend(codes)
        if not icd_codes:
            return []
        demo = Demographics(age=age, sex=sex)
        prefix = f"{segment}_"
        result = _processor_v28.calculate_from_diagnosis(
            icd_codes, demographics=demo, prefix_override=prefix
        )
        detail_map = {
            str(d.hcc): {"label": d.label, "coefficient": d.coefficient}
            for d in result.hcc_details
        }
        return detail_map
    except Exception:
        return {}


# ---------------------------------------------------------------------------
# Core calculation — blended V24/V28
# ---------------------------------------------------------------------------


def calculate_raf_score(
    patient_id: int,
    measurement_year: int | None = None,
    dual_status: str | None = None,
    institutional: bool = False,
    *,
    encounter_year: int | None = None,
    enrollment_override: dict[str, Any] | None = None,
    model_version: Literal["v24", "v28", "blended", "auto"] = "auto",
    enrollment_months: int = 12,
    adl_data: dict[str, Any] | None = None,
    plan_type: str = "MA",
    sweep_period: str | None = None,
    dos_start: date | None = None,
    dos_end: date | None = None,
    tenant_id: str = "",  # Required — empty string will raise below
    require_meat: bool = True,
) -> dict[str, Any]:
    """
    Calculate RAF score for a patient using hccinfhir.

    Supports CMS transition blending:
      PY2024: 67% V24 + 33% V28
      PY2025: 33% V24 + 67% V28
      PY2026+: 100% V28 (no blend)

    Args:
        patient_id:          OpenEMR patient PID. Use 0 for paste / anonymous mode.
        measurement_year:    CMS payment year (default 2026).
        dual_status:         Legacy — Medicaid dual status. Prefer enrollment_override.
        institutional:       Legacy — True if SNF / nursing-facility resident.
        encounter_year:      Age calculation year (CMS Feb 1 rule). Defaults to
                             measurement_year.
        enrollment_override: Optional override dict. Keys: dual_status, orec, institutional.
        model_version:       "v24" | "v28" | "blended" | "auto" (default).
                             "auto" uses CMS transition rules for the payment year.
        enrollment_months:   Number of months of Part B enrollment. < 12 → New Enrollee
                             demographic-only model (disease scores suppressed).
        adl_data:            Optional ADL assessment dict for frailty adjustment
                             (used with PACE/FIDE-SNP plan types).
        plan_type:           CMS plan type string. "PACE" or "FIDE_SNP" triggers
                             frailty adjustment when adl_data is provided.
        sweep_period:        CMS RAF sweep window: "initial" | "midyear" | "final".
                             Filters ICD codes by date-of-service window.
        dos_start:           Optional manual date-of-service start filter.
        dos_end:             Optional manual date-of-service end filter.

    Returns a dict with:
        - All existing V28-era fields (backward compatible)
        - model_version: which model(s) were actually used
        - blend_weights: {"v24": float, "v28": float} when blending
        - v24_score / v28_score: individual raw scores when both ran
        - v24_hcc_list / v28_hcc_list: per-model HCC lists
        - blended_raw_score: weighted raw score before payment adjustments
        - new_enrollee: True if < 12 months enrollment (demographic-only)
        - esrd_segment: populated if patient is ESRD_DLY / ESRD_FG / ESRD_NE
        - frailty_adjustment: populated when PACE/FIDE-SNP + adl_data provided
        - sweep_period_applied: which sweep window was used for date filtering
        - concurrent_raf: the strict RAF score (MEAT enforced)
        - prospective_raf: the total opportunity score (including AI suspects)
        - suspected_raf_delta: (prospective_raf - concurrent_raf) numeric gap
    """
    if measurement_year is None:
        measurement_year = date.today().year
    if not tenant_id and patient_id != 0:
        raise ValueError(
            "calculate_raf_score: tenant_id is required for patient data access — "
            "refusing to compute RAF without tenant scope (HIPAA multi-tenant isolation)"
        )
    # -----------------------------------------------------------------------
    # Paste / anonymous mode (patient_id == 0)
    # -----------------------------------------------------------------------
    if patient_id == 0:
        logger.info("RAF calc pid=0 (paste mode) — defaulting to CNA")
        return {
            "patient_id": 0,
            "measurement_year": measurement_year,
            "model_segment": "CNA",
            "enrollment_info": {
                "dual_status": "non_dual",
                "orec": "0",
                "institutional": False,
                "source": "paste_mode_default",
            },
            "note": (
                "Paste mode: enrollment defaults to CNA (non_dual, aged). "
                "Pass enrollment_override via the API to change."
            ),
        }

    # 1. Get patient
    patient = _get_patient(patient_id, tenant_id=tenant_id)
    if not patient:
        raise ValueError(f"Patient {patient_id} not found")

    # 1a. Deceased patient guard — query deceased_date from patients table.
    # The column is added idempotently by the FHIR sync adapter; if it does
    # not yet exist the query falls back gracefully.
    _deceased_date: Any = None
    try:
        with raf_cursor() as _dc:
            _dc.execute(
                "SELECT deceased_date FROM patients WHERE id = %s AND tenant_id = %s LIMIT 1",
                (patient_id, tenant_id),
            )
            _d_row = _dc.fetchone()
            if _d_row:
                _deceased_date = _d_row.get("deceased_date")
    except Exception as _de:
        logger.debug("Could not query deceased_date for patient %s: %s", patient_id, _de)

    if _deceased_date is not None:
        from datetime import date as _date, datetime as _datetime
        # Normalise to a date object
        if isinstance(_deceased_date, str):
            try:
                _deceased_date = _datetime.strptime(_deceased_date[:10], "%Y-%m-%d").date()
            except ValueError:
                _deceased_date = None
        elif isinstance(_deceased_date, _datetime):
            _deceased_date = _deceased_date.date()

        if _deceased_date is not None:
            _year_start = _date(measurement_year, 1, 1)
            if _deceased_date < _year_start:
                # Died before the measurement year even started — zero RAF
                logger.warning(
                    "Patient %s deceased %s before measurement year %s — returning zero RAF",
                    patient_id, _deceased_date, measurement_year,
                )
                return {
                    "patient_id": patient_id,
                    "measurement_year": measurement_year,
                    "concurrent_raf": 0.0,
                    "payment_raf": 0.0,
                    "prospective_raf": 0.0,
                    "hcc_list": [],
                    "icd_codes": [],
                    "note": "deceased_before_year",
                    "deceased_date": str(_deceased_date),
                }
            # Died mid-year — RAF proceeds normally but deceased_date is
            # attached to the result so callers can prorate if needed.
            logger.info(
                "Patient %s deceased %s mid-year %s — RAF calculated; caller may prorate",
                patient_id, _deceased_date, measurement_year,
            )

    dob = patient.get("DOB") or patient.get("dob")
    if not dob:
        logger.warning(
            "Patient %s has no DOB — using fallback 1950-01-01", patient.get("pid")
        )
        dob = "1950-01-01"
    sex = _sex_code(patient.get("sex", "M"))
    age_year = encounter_year if encounter_year is not None else measurement_year
    age = _calculate_age(dob, age_year)

    # 2. Get ICD-10 codes (with optional date-of-service filtering for sweep periods)
    sweep_info: dict[str, Any] = {}
    if sweep_period or dos_start or dos_end:
        from app.services.sweep_periods import get_sweep_dates, filter_icd_codes_by_dos

        if sweep_period and not (dos_start and dos_end):
            dos_start, dos_end = get_sweep_dates(measurement_year, sweep_period)
        icd_codes = filter_icd_codes_by_dos(patient_id, dos_start, dos_end)
        sweep_info = {
            "sweep_period": sweep_period,
            "dos_start": str(dos_start) if dos_start else None,
            "dos_end": str(dos_end) if dos_end else None,
            "icd_codes_in_window": len(icd_codes),
        }
    else:
        icd_codes = _get_icd_codes(
            patient_id, year=measurement_year, include_suspected=False, tenant_id=tenant_id
        )

    # 2b. Merge ICD codes from raf_patient_hcc (document analysis, manual entries)
    # Require MEAT verification for strict billing codes if require_meat is True
    suspected_codes = set()
    try:
        with raf_cursor() as cur:
            meat_sql = (
                " AND meat_status IN ('complete', 'passed') " if require_meat else " "
            )
            cur.execute(
                "SELECT DISTINCT icd10_code FROM raf_patient_hcc "
                f"WHERE patient_id = %s AND measurement_year = %s AND tenant_id = %s AND icd10_code IS NOT NULL{meat_sql}",
                (patient_id, measurement_year, tenant_id),
            )
            for row in cur.fetchall():
                code = (row.get("icd10_code") or "").strip()
                if code and code not in icd_codes:
                    icd_codes.append(code)

            # Gather suspects for the separate prospective calculation track
            missing_meat_sql = " AND (meat_status IS NULL OR meat_status NOT IN ('complete', 'passed')) "
            cur.execute(
                "SELECT DISTINCT icd10_code FROM raf_patient_hcc "
                f"WHERE patient_id = %s AND measurement_year = %s AND tenant_id = %s AND icd10_code IS NOT NULL{missing_meat_sql}",
                (patient_id, measurement_year, tenant_id),
            )
            for row in cur.fetchall():
                code = (row.get("icd10_code") or "").strip()
                if code and code not in icd_codes:
                    suspected_codes.add(code)

            # Grab AI suspects
            ai_suspects = _get_icd_codes(
                patient_id,
                year=measurement_year,
                dos_start=dos_start if dos_start else None,
                dos_end=dos_end if dos_end else None,
                include_suspected=True,
                tenant_id=tenant_id,
            )
            for code in ai_suspects:
                if code not in icd_codes:
                    suspected_codes.add(code)

    except Exception as exc:
        logger.warning(
            "Failed to merge raf_patient_hcc codes for pid %s tenant %s: %s",
            patient_id,
            tenant_id,
            exc,
        )

    prospective_icd_codes = icd_codes + list(suspected_codes)

    # 3. Resolve enrollment info
    _dual_type, _orec, _institutional, enrollment_source = _resolve_enrollment(
        patient_id=patient_id,
        age=age,
        institutional=institutional,
        dual_status=dual_status,
        enrollment_override=enrollment_override,
        measurement_year=measurement_year,
        tenant_id=tenant_id,
    )

    # 4. Determine model segment (includes ESRD/NE routing)
    model_segment = determine_model_segment(
        age=age,
        is_dual=_dual_type != "non_dual",
        dual_type=_dual_type,
        is_institutional=_institutional,
        orec=_orec,
        enrollment_months=enrollment_months,
        icd_codes=icd_codes,
    )
    logger.info(
        "RAF calc pid=%s year=%s age=%s sex=%s segment=%s orec=%s dual=%s codes=%s enrollment_months=%s",
        patient_id,
        measurement_year,
        age,
        sex,
        model_segment,
        _orec,
        _dual_type,
        icd_codes,
        enrollment_months,
    )

    # 4a. New Enrollee short-circuit — demographic-only, no HCC disease scoring
    if _is_new_enrollee(model_segment):
        ne_result = _calculate_new_enrollee_score(age, sex, model_segment, orec=_orec)
        # Apply the same normalization + MACI adjustment used by all other payment models.
        # NE segments follow the V28 payment schedule (CMS-HCC V28 norm/MACI tables).
        _ne_norm = _get_norm_factor(_NORM_FACTORS_V28, measurement_year)
        _ne_maci = _get_maci_factor(_MACI_FACTORS_V28, measurement_year)
        ne_payment_raf = round(
            ne_result["demographic_score"] * (1 - _ne_maci) / _ne_norm, 4
        )

        _upsert_patient_demographics(
            patient_id=patient_id,
            measurement_year=measurement_year,
            age=age,
            sex=sex,
            model_segment=model_segment,
            dual_type=_dual_type,
            orec=_orec,
            institutional=_institutional,
            enrollment_source=enrollment_source,
            tenant_id=tenant_id,
        )

        return {
            "patient_id": patient_id,
            "measurement_year": measurement_year,
            "model_segment": model_segment,
            "age": age,
            "sex": sex,
            "icd_codes": icd_codes,
            "new_enrollee": True,
            "enrollment_months": enrollment_months,
            "demographic_score": ne_result["demographic_score"],
            "disease_score": 0.0,
            "interaction_score": 0.0,
            "subtotal": ne_result["demographic_score"],
            "raf_score": ne_payment_raf,
            "payment_raf": ne_payment_raf,
            "concurrent_raf": ne_payment_raf,
            "prospective_raf": ne_payment_raf,
            "suspected_raf_delta": 0.0,
            "raw_hcc_list": [],
            "final_hcc_list": [],
            "hcc_contributions": [],
            "all_coefficients": {},
            "interactions_fired": {},
            "model_version": "ne",
            "blend_weights": {"v24": 0.0, "v28": 0.0},
            "blended_raw_score": ne_payment_raf,
            "v24_score": None,
            "v28_score": None,
            "v24_hcc_list": None,
            "v28_hcc_list": None,
            "enrollment_info": {
                "dual_status": _dual_type,
                "orec": _orec,
                "institutional": _institutional,
                "source": enrollment_source,
                "enrollment_months": enrollment_months,
            },
            "model_note": ne_result["model_note"],
            "sweep_period_applied": sweep_info or None,
            "_disclaimer": "New Enrollee: demographic-only scoring per CMS rules.",
        }

    # 4b. ESRD segment — calculate ESRD demographic override for later application
    esrd_demo_override: float | None = None
    if _is_esrd(model_segment):
        esrd_demo_override = _calculate_esrd_demographic_score(age, sex, model_segment)
        logger.info(
            "RAF calc pid=%s — ESRD segment=%s demo_override=%.4f",
            patient_id,
            model_segment,
            esrd_demo_override,
        )

    # 4c. Map internal dual_type to hccinfhir dual_elgbl_cd codes.
    # CMS dual eligibility codes (00-10): full benefit = {02,04,08}, partial = {01,03,05,06}.
    # If the enrollment source provides a raw CMS code (e.g. "02"), pass it through directly.
    # Otherwise map our categorical labels to representative CMS codes.
    _dt_lower = (_dual_type or "non_dual").strip()
    if _dt_lower in ("00", "01", "02", "03", "04", "05", "06", "07", "08", "09", "10"):
        _dual_elgbl_cd = _dt_lower  # Raw CMS code — pass through directly
    elif _dt_lower.lower() in ("full", "full_dual"):
        _dual_elgbl_cd = "02"       # QMB Plus (full benefit dual)
    elif _dt_lower.lower() in ("partial", "partial_dual"):
        _dual_elgbl_cd = "01"       # QMB Only (partial benefit dual)
    else:
        _dual_elgbl_cd = "NA"       # non-dual

    _is_ne = _is_new_enrollee(model_segment)
    _is_inst = _institutional

    # 5. Determine effective blend mode
    # PACE organizations follow a separate, slower CMS transition schedule.
    # For PACE: the legacy side uses V24 (same 79-HCC model structure as V22/2017)
    # with V22 normalization factor (1.187). The blend weights reflect CMS PACE policy.
    is_pace = plan_type.upper() == "PACE"
    if is_pace:
        v24_weight, v28_weight = _PACE_BLEND_WEIGHTS.get(measurement_year, (0.0, 1.0))
        logger.info(
            "PACE plan — using V22 legacy + V28 blend for PY%s: legacy=%.0f%% V28=%.0f%%",
            measurement_year, v24_weight * 100, v28_weight * 100,
        )
    else:
        v24_weight, v28_weight = _BLEND_WEIGHTS.get(measurement_year, (0.0, 1.0))

    if model_version == "v24":
        v24_weight, v28_weight = 1.0, 0.0
    elif model_version == "v28":
        v24_weight, v28_weight = 0.0, 1.0
    elif model_version == "blended":
        # Force blending even for 2026+ if caller explicitly requests it
        if v24_weight == 0.0:
            source = _PACE_BLEND_WEIGHTS if is_pace else _BLEND_WEIGHTS
            v24_weight, v28_weight = source.get(measurement_year, (0.0, 1.0))
    # "auto" uses the dict/PACE lookup result as-is

    use_v24 = v24_weight > 0.0
    use_v28 = v28_weight > 0.0
    is_blended = use_v24 and use_v28

    # 6. Run model(s) — pass enrollment params so hccinfhir can auto-detect
    #    the correct coefficient prefix (DI_ for ESRD, CFA_ for dual, etc.)
    _is_esrd_seg = _is_esrd(model_segment)
    # Graft months for ESRD functioning graft patients — affects duration interactions
    # (GE65_DUR4_9, GE65_DUR10PL, etc.). Source from enrollment_override if available.
    _graft_months: int | None = None
    if enrollment_override and enrollment_override.get("graft_months") is not None:
        _graft_months = int(enrollment_override["graft_months"])
    elif model_segment == "ESRD_FG":
        # Functioning graft without explicit transplant date — default to 12 months
        # to enable basic graft duration interactions. This is conservative; callers
        # should provide actual graft_months via enrollment_override for accuracy.
        _graft_months = 12

    _enroll_kwargs: dict[str, Any] = {
        "orec": _orec,
        "dual_elgbl_cd": _dual_elgbl_cd,
        "new_enrollee": _is_ne,
        "institutional": _is_inst,
        "graft_months": _graft_months,
    }

    def _evaluate_track(codes_list: list[str]):
        eval_v28 = None
        eval_v24 = None

        if use_v28:
            n28 = _get_norm_factor(_NORM_FACTORS_V28, measurement_year)
            m28 = _get_maci_factor(_MACI_FACTORS_V28, measurement_year)
            eval_v28 = _run_single_model(
                _processor_v28, codes_list, age, sex, model_segment, n28, m28,
                **_enroll_kwargs,
            )
            _apply_hcc_hierarchy(eval_v28, "v28")

        if use_v24:
            if _is_esrd_seg:
                # ESRD patients: use dedicated CMS-HCC ESRD Model V24 with
                # ESRD-specific DI_/GC_ prefixes and coefficients.
                # hccinfhir auto-detects the correct ESRD prefix from orec.
                n24 = _get_norm_factor(_NORM_FACTORS_V24, measurement_year)
                m24 = _get_maci_factor(_MACI_FACTORS_V24, measurement_year)
                eval_v24 = _run_single_model(
                    _processor_esrd_v24, codes_list, age, sex, model_segment, n24, m24,
                    **_enroll_kwargs,
                )
                _apply_hcc_hierarchy(eval_v24, "v24")
            elif is_pace:
                # PACE: use actual V22 processor with V22 normalization factor.
                # hccinfhir ships CMS-HCC Model V22 with correct 79-HCC coefficients.
                n22 = _get_norm_factor(_NORM_FACTORS_V22, measurement_year)
                m24 = _get_maci_factor(_MACI_FACTORS_V24, measurement_year)
                eval_v24 = _run_single_model(
                    _processor_v22, codes_list, age, sex, model_segment, n22, m24,
                    **_enroll_kwargs,
                )
                _apply_hcc_hierarchy(eval_v24, "v24")
            else:
                n24 = _get_norm_factor(_NORM_FACTORS_V24, measurement_year)
                m24 = _get_maci_factor(_MACI_FACTORS_V24, measurement_year)
                eval_v24 = _run_single_model(
                    _processor_v24, codes_list, age, sex, model_segment, n24, m24,
                    **_enroll_kwargs,
                )
                _apply_hcc_hierarchy(eval_v24, "v24")

        # 7. Compute blended score
        if is_blended:
            # CMS requires blending at PAYMENT level, not RAW level.
            # Each model's score is normalized with its OWN factors first.
            p24 = eval_v24["payment_raf"]  # type: ignore[index]  # already normalized with V24 factors
            p28 = eval_v28["payment_raf"]  # type: ignore[index]  # already normalized with V28 factors
            p_raf = round(v24_weight * p24 + v28_weight * p28, 4)
            # Keep raw scores for reporting
            r24 = eval_v24["raw_raf"]  # type: ignore[index]
            r28 = eval_v28["raw_raf"]  # type: ignore[index]
            bl_raw = v24_weight * r24 + v28_weight * r28
            return {
                "payment_raf": p_raf,
                "blended_raw": bl_raw,
                "v24_raw": r24,
                "v28_raw": r28,
                "primary": eval_v28,
                "v24_calc": eval_v24,
                "v28_calc": eval_v28,
                "model": "blended",
            }
        elif use_v28:
            return {
                "payment_raf": round(eval_v28["payment_raf"], 4),
                "blended_raw": eval_v28["raw_raf"],  # type: ignore[index]
                "v24_raw": 0.0,
                "v28_raw": eval_v28["raw_raf"],
                "primary": eval_v28,  # type: ignore[index]
                "v24_calc": None,
                "v28_calc": eval_v28,
                "model": "v28",
            }
        else:
            return {
                "payment_raf": round(eval_v24["payment_raf"], 4),
                "blended_raw": eval_v24["raw_raf"],  # type: ignore[index]
                "v24_raw": eval_v24["raw_raf"],
                "v28_raw": 0.0,
                "primary": eval_v24,  # type: ignore[index]
                "v24_calc": eval_v24,
                "v28_calc": None,
                "model": "v24",
            }

    strict_res = _evaluate_track(icd_codes)
    prosp_res = _evaluate_track(prospective_icd_codes)

    payment_raf = strict_res["payment_raf"]
    prospective_raf = prosp_res["payment_raf"]
    suspected_raf_delta = round(prospective_raf - payment_raf, 4)

    primary = strict_res["primary"]
    blended_raw = strict_res["blended_raw"]
    v24_raw = strict_res["v24_raw"]
    v28_raw = strict_res["v28_raw"]
    model_version_used = strict_res["model"]
    v24_calc = strict_res["v24_calc"]
    v28_calc = strict_res["v28_calc"]

    demographic_score = primary["demographic_score"]  # type: ignore[index]
    disease_score = primary["disease_score"]  # type: ignore[index]
    interaction_score = primary["interaction_score"]  # type: ignore[index]
    subtotal = primary["subtotal"]  # type: ignore[index]

    # Apply ESRD demographic override — CMS ESRD model uses separate, higher
    # demographic base scores that differ from the standard community model.
    if esrd_demo_override is not None and esrd_demo_override != demographic_score:
        demo_delta = esrd_demo_override - demographic_score
        demographic_score = esrd_demo_override
        subtotal = round(subtotal + demo_delta, 4)
        logger.info(
            "RAF calc pid=%s — ESRD demo override applied: %.4f → %.4f (delta=%.4f)",
            patient_id, demographic_score - demo_delta, demographic_score, demo_delta,
        )
    hcc_contributions = primary["hcc_contributions"]  # type: ignore[index]
    all_coefficients = primary["all_coefficients"]  # type: ignore[index]
    interactions_fired = primary["interactions_fired"]  # type: ignore[index]
    norm_factor = primary["norm_factor"]  # type: ignore[index]
    maci = primary["maci_factor"]  # type: ignore[index]

    raf_score = round(blended_raw, 4)

    logger.info(
        "RAF score pid=%s model=%s → raw=%.4f payment=%.4f (demo=%.4f disease=%.4f int=%.4f) "
        "V24=%.4f(w=%.2f) V28=%.4f(w=%.2f)",
        patient_id,
        model_version_used,
        raf_score,
        payment_raf,
        demographic_score,
        disease_score,
        interaction_score,
        v24_raw if v24_calc else 0.0,
        v24_weight,
        v28_raw if v28_calc else 0.0,
        v28_weight,
    )

    # 8. Determine which HCC list/result object to persist (V28 when blended,
    #    otherwise whichever model ran)
    persist_result_obj = (v28_calc or v24_calc)["_result_obj"]  # type: ignore[index]
    persist_hcc_list = (v28_calc or v24_calc)["hcc_list"]  # type: ignore[index]

    _store_patient_hccs(
        patient_id,
        measurement_year,
        persist_hcc_list,
        icd_codes,
        persist_result_obj,
        score_type=model_version_used,
        tenant_id=tenant_id,
    )

    # 9. Persist demographics
    _upsert_patient_demographics(
        patient_id=patient_id,
        measurement_year=measurement_year,
        age=age,
        sex=sex,
        model_segment=model_segment,
        dual_type=_dual_type,
        orec=_orec,
        institutional=_institutional,
        enrollment_source=enrollment_source,
        tenant_id=tenant_id,
    )

    # 10. Apply frailty adjustment (PACE / FIDE-SNP only)
    frailty_info: dict[str, Any] | None = None
    if adl_data and plan_type.upper() in ("PACE", "FIDE_SNP", "FIDE-SNP"):
        try:
            from app.services.frailty_adjuster import apply_frailty_adjustment

            frailty_result = apply_frailty_adjustment(payment_raf, adl_data, plan_type)
            if frailty_result["applies"]:
                payment_raf = frailty_result["adjusted_payment_raf"]
                raf_score = payment_raf
                frailty_info = frailty_result

                prospective_frailty_result = apply_frailty_adjustment(
                    prospective_raf, adl_data, plan_type
                )
                prospective_raf = prospective_frailty_result["adjusted_payment_raf"]
                suspected_raf_delta = round(prospective_raf - payment_raf, 4)

                logger.info(
                    "RAF calc pid=%s — frailty applied plan=%s adj=%.4f",
                    patient_id,
                    plan_type,
                    payment_raf,
                )
        except Exception as exc:
            logger.warning("Frailty adjustment failed pid=%s: %s", patient_id, exc)

    # 11. Build result dict — backward compatible + new fields
    result_dict: dict[str, Any] = {
        "patient_id": patient_id,
        "measurement_year": measurement_year,
        "model_segment": model_segment,
        "age": age,
        "sex": sex,
        "icd_codes": icd_codes,
        "demographic_score": round(demographic_score, 4),
        "raw_hcc_list": persist_hcc_list,
        "final_hcc_list": persist_hcc_list,
        "disease_score": round(disease_score, 4),
        "interaction_score": round(interaction_score, 4),
        "subtotal": round(subtotal, 4),
        # Primary scores (backward compatible)
        "raf_score": raf_score,
        "payment_raf": payment_raf,
        "concurrent_raf": payment_raf,
        "prospective_raf": prospective_raf,
        "suspected_raf_delta": suspected_raf_delta,
        "normalization_factor": norm_factor,
        "maci_factor": maci,
        "hcc_contributions": hcc_contributions,
        "all_coefficients": all_coefficients,
        "interactions_fired": interactions_fired,
        # Blend metadata (new fields)
        "model_version": model_version_used,
        "blend_weights": {"v24": round(v24_weight, 4), "v28": round(v28_weight, 4)},
        "blended_raw_score": raf_score,
        "v24_score": round(v24_calc["raw_raf"], 4) if v24_calc else None,
        "v28_score": round(v28_calc["raw_raf"], 4) if v28_calc else None,
        "v24_hcc_list": v24_calc["hcc_list"] if v24_calc else None,
        "v28_hcc_list": v28_calc["hcc_list"] if v28_calc else None,
        # Enrollment metadata
        "enrollment_info": {
            "dual_status": _dual_type,
            "orec": _orec,
            "institutional": _institutional,
            "source": enrollment_source,
            "enrollment_months": enrollment_months,
        },
        # New Enrollee / ESRD flags
        "new_enrollee": False,
        "esrd_segment": model_segment if _is_esrd(model_segment) else None,
        # Frailty adjustment (PACE/FIDE-SNP)
        "frailty_adjustment": frailty_info,
        "plan_type": plan_type,
        # Sweep period applied
        "sweep_period_applied": sweep_info or None,
        # Deceased patient — present only when patient died mid-year so callers
        # can prorate the RAF score by months alive.  None for living patients.
        "deceased_date": str(_deceased_date) if _deceased_date is not None else None,
        "_disclaimer": (
            "RAF scores are estimates based on CMS-HCC models via hccinfhir. "
            "Not for payment submission."
        ),
    }

    # 12. Persist to raf_scores
    _upsert_raf_score(result_dict, score_type=model_version_used, tenant_id=tenant_id)

    # Invalidate any cached RAF breakdown for this patient so the next call
    # reflects the freshly calculated score.
    cache_delete_pattern(f"raf:breakdown:{patient_id}:{measurement_year}:*")

    return result_dict


# ---------------------------------------------------------------------------
# Multi-model detailed breakdown function
# ---------------------------------------------------------------------------


def calculate_raf_score_multi_model(
    patient_id: int,
    measurement_year: int | None = None,
    *,
    encounter_year: int | None = None,
    enrollment_override: dict[str, Any] | None = None,
    tenant_id: str = "",  # Required — empty string will raise below
) -> dict[str, Any]:
    """
    Calculate and return a detailed per-model breakdown for V24 vs V28.

    Unlike calculate_raf_score(), this always runs BOTH models (regardless of
    blend year) and returns a side-by-side comparison object. Intended for the
    model-comparison endpoint — does NOT persist results.

    Returns a dict with:
        - demographics (age, sex, segment)
        - blend_weights for the given measurement_year
        - v24: full single-model result
        - v28: full single-model result
        - blended: blended payment RAF and raw score
        - hcc_comparison: codes present in V24 only, V28 only, or both
    """
    if measurement_year is None:
        measurement_year = date.today().year
    if not tenant_id and patient_id != 0:
        raise ValueError(
            "calculate_raf_score_multi_model: tenant_id is required — "
            "refusing to compute multi-model RAF without tenant scope (HIPAA multi-tenant isolation)"
        )
    if patient_id == 0:
        return {"error": "Multi-model comparison not available in paste mode"}

    patient = _get_patient(patient_id, tenant_id=tenant_id)
    if not patient:
        raise ValueError(f"Patient {patient_id} not found")

    dob = patient.get("DOB") or patient.get("dob")
    if not dob:
        logger.warning(
            "Patient %s has no DOB — using fallback 1950-01-01", patient.get("pid")
        )
        dob = "1950-01-01"
    sex = _sex_code(patient.get("sex", "M"))
    age_year = encounter_year if encounter_year is not None else measurement_year
    age = _calculate_age(dob, age_year)

    icd_codes = _get_icd_codes(patient_id, year=measurement_year, tenant_id=tenant_id)

    _dual_type, _orec, _institutional, enrollment_source = _resolve_enrollment(
        patient_id=patient_id,
        age=age,
        institutional=False,
        dual_status=None,
        enrollment_override=enrollment_override,
        measurement_year=measurement_year,
        tenant_id=tenant_id,
    )

    model_segment = determine_model_segment(
        age=age,
        is_dual=_dual_type != "non_dual",
        dual_type=_dual_type,
        is_institutional=_institutional,
        orec=_orec,
    )

    # Run both models unconditionally
    norm_v28 = _NORM_FACTORS_V28.get(measurement_year, 1.0)
    maci_v28 = _MACI_FACTORS_V28.get(measurement_year, 0.0)
    v28_result = _run_single_model(
        _processor_v28, icd_codes, age, sex, model_segment, norm_v28, maci_v28
    )
    _apply_hcc_hierarchy(v28_result, "v28")

    norm_v24 = _NORM_FACTORS_V24.get(measurement_year, 1.0)
    maci_v24 = _MACI_FACTORS_V24.get(measurement_year, 0.0)
    v24_result = _run_single_model(
        _processor_v24, icd_codes, age, sex, model_segment, norm_v24, maci_v24
    )
    _apply_hcc_hierarchy(v24_result, "v24")

    v24_weight, v28_weight = _BLEND_WEIGHTS.get(measurement_year, (0.0, 1.0))
    blended_raw = (
        v24_weight * v24_result["raw_raf"] + v28_weight * v28_result["raw_raf"]
    )
    blended_payment = round(blended_raw * (1 - maci_v28) / norm_v28, 4)

    # HCC comparison
    v24_set = set(v24_result["hcc_list"])
    v28_set = set(v28_result["hcc_list"])
    hcc_comparison = {
        "v24_only": sorted(v24_set - v28_set),
        "v28_only": sorted(v28_set - v24_set),
        "in_both": sorted(v24_set & v28_set),
        "v24_total": len(v24_set),
        "v28_total": len(v28_set),
    }

    # Strip internal _result_obj before returning over the wire
    def _strip(d: dict) -> dict:
        return {k: v for k, v in d.items() if k != "_result_obj"}

    return {
        "patient_id": patient_id,
        "measurement_year": measurement_year,
        "model_segment": model_segment,
        "age": age,
        "sex": sex,
        "icd_codes": icd_codes,
        "blend_weights": {"v24": round(v24_weight, 4), "v28": round(v28_weight, 4)},
        "v24": _strip(v24_result),
        "v28": _strip(v28_result),
        "blended": {
            "raw_score": round(blended_raw, 4),
            "payment_raf": blended_payment,
            "v24_contribution": round(v24_weight * v24_result["raw_raf"], 4),
            "v28_contribution": round(v28_weight * v28_result["raw_raf"], 4),
        },
        "hcc_comparison": hcc_comparison,
        "enrollment_info": {
            "dual_status": _dual_type,
            "orec": _orec,
            "institutional": _institutional,
            "source": enrollment_source,
        },
        "_disclaimer": (
            "RAF scores are estimates based on CMS-HCC models via hccinfhir. "
            "Not for payment submission."
        ),
    }


# ---------------------------------------------------------------------------
# Batch + breakdown
# ---------------------------------------------------------------------------


def calculate_raf_for_all_patients(
    year: int | None = None,
    tenant_id: str = "",  # Required — empty string will raise below
) -> list[dict[str, Any]]:
    """Calculate RAF for all patients in raf_intelligence.patients."""
    if year is None:
        year = date.today().year
    if not tenant_id:
        raise ValueError(
            "calculate_raf_for_all_patients: tenant_id is required — "
            "refusing to batch-calculate RAF without tenant scope (HIPAA multi-tenant isolation)"
        )
    with raf_cursor() as cur:
        # Native patients
        cur.execute(
            "SELECT id FROM patients WHERE is_active = 1 AND tenant_id = %s ORDER BY id",
            (tenant_id,),
        )
        native_patients = cur.fetchall()

        # FHIR patients from emr_patient_matches that are not already in the
        # patients table (i.e. no linked internal row).  We use epm.id as the
        # patient_id reference, which is consistent with how the rest of the
        # codebase (patient_service, raf routers) addresses FHIR patients.
        cur.execute(
            """
            SELECT DISTINCT epm.id
            FROM emr_patient_matches epm
            JOIN emr_connections ec ON ec.id = epm.connection_id
            WHERE ec.is_active = 1
              AND ec.connection_type IN ('fhir_r4', 'rest_api')
              AND ec.tenant_id = %s
              AND epm.id NOT IN (
                  SELECT id FROM patients WHERE is_active = 1 AND tenant_id = %s
              )
            ORDER BY epm.id
            """,
            (tenant_id, tenant_id),
        )
        fhir_patients = cur.fetchall()

    all_patient_ids = [int(p["id"]) for p in native_patients] + [
        int(p["id"]) for p in fhir_patients
    ]

    results = []
    for pid in all_patient_ids:
        try:
            r = calculate_raf_score(pid, year, tenant_id=tenant_id)
            results.append(r)
        except Exception as exc:
            logger.error(
                "RAF calc failed for pid=%s tenant=%s: %s", pid, tenant_id, exc
            )
            results.append({"patient_id": pid, "error": str(exc)})
    return results


def get_raf_breakdown(
    patient_id: int,
    year: int = 2026,
    tenant_id: str = "",  # Required — empty string will raise below
) -> dict[str, Any]:
    """Return RAF breakdown, preferring stored demo data over a live calculation.

    When ``raf_scores`` has a row with hcc_count > 0 *or* ``raf_patient_hcc``
    has entries for the patient/year, we build the response directly from the
    stored data so that seeded HCC rows are always surfaced correctly.
    Otherwise we fall back to the live ``calculate_raf_score`` path.

    Results are cached in Redis for 2 minutes (key: raf:breakdown:{patient_id}:{year}:{tenant_id}).
    The cache is automatically invalidated whenever calculate_raf_score persists a new score for
    the same patient + year.
    """
    if not tenant_id:
        raise ValueError(
            "get_raf_breakdown: tenant_id is required — "
            "refusing to access RAF breakdown without tenant scope (HIPAA multi-tenant isolation)"
        )
    import json as _json

    # --- cache check ---
    _acid = get_active_connection_id(tenant_id)
    _cache_key = f"raf:breakdown:{patient_id}:{year}:{tenant_id}:{_acid}"
    _cached = cache_get(_cache_key)
    if _cached is not None:
        return _cached

    try:
        with raf_cursor() as cur:
            # 1. Try to find a stored score with meaningful HCC data
            cur.execute(
                """
                SELECT demographic_score, disease_score, interaction_score,
                       total_raw, final_raf, hcc_count, score_type, model_segment,
                       normalization_factor,
                       v24_score, v28_score, blended_raw_score,
                       blend_v24_weight, blend_v28_weight,
                       v24_hcc_count, v28_hcc_count
                FROM raf_scores
                WHERE patient_id = %s AND measurement_year = %s AND tenant_id = %s
                ORDER BY calculated_at DESC
                LIMIT 1
                """,
                (patient_id, year, tenant_id),
            )
            score_row = cur.fetchone()

            # 2. Try to find stored HCC entries
            cur.execute(
                """
                SELECT hcc_code, icd10_codes,
                       raf_coefficient, meat_status
                FROM raf_patient_hcc
                WHERE patient_id = %s AND measurement_year = %s AND tenant_id = %s
                  AND hcc_code > 0
                  AND (is_trumped = 0 OR is_trumped IS NULL)
                ORDER BY raf_coefficient DESC
                """,
                (patient_id, year, tenant_id),
            )
            hcc_rows = cur.fetchall()
    except Exception as exc:
        logger.error(
            "get_raf_breakdown stored-data lookup failed pid=%s year=%s tenant=%s: %s",
            patient_id,
            year,
            tenant_id,
            exc,
        )
        score_row = None
        hcc_rows = []

    # Use stored data when we have actual HCC entries or a score with hcc_count > 0
    use_stored = bool(hcc_rows) or (
        score_row is not None and int(score_row.get("hcc_count") or 0) > 0
    )

    if use_stored and score_row is not None:
        hcc_details = []
        for h in hcc_rows:
            codes = h.get("icd10_codes")
            if isinstance(codes, (bytes, str)):
                try:
                    codes = _json.loads(codes)
                except (ValueError, TypeError):
                    codes = [codes] if codes else []
            hcc_details.append(
                {
                    "hcc_code": str(h["hcc_code"]),
                    "hcc_label": f"HCC {h['hcc_code']}",
                    "coefficient": float(h.get("raf_coefficient") or 0.0),
                    "icd10_codes": codes or [],
                    "meat_status": h.get("meat_status") or "missing",
                }
            )

        demographic = float(score_row.get("demographic_score") or 0)
        disease = float(score_row.get("disease_score") or 0)
        interaction = float(score_row.get("interaction_score") or 0)
        final_raf = float(score_row.get("final_raf") or 0)

        # Reverse-engineer the combined adjustment factor from raw → final
        raw_total = demographic + disease + interaction
        stored_norm = float(score_row.get("normalization_factor") or 0)
        # If normalization_factor column stores the combined (1-maci)/norm value,
        # reverse it. Otherwise compute from raw vs final.
        if raw_total > 0 and final_raf > 0:
            combined_factor = round(final_raf / raw_total, 6)
        else:
            combined_factor = 1.0
        # Use current year's known factors as fallback
        maci_val = _get_maci_factor(_MACI_FACTORS_V28, year)
        norm_val = _get_norm_factor(_NORM_FACTORS_V28, year)

        # Collect ICD codes from the patient for the engine_input display
        _stored_icd_codes: list[str] = []
        try:
            _stored_icd_codes = _get_icd_codes(patient_id, year=year, tenant_id=tenant_id)
        except Exception:
            pass

        # Get patient demographics for engine_input display
        _pat = _get_patient(patient_id, tenant_id=tenant_id)
        _pat_dob = (_pat or {}).get("DOB") or (_pat or {}).get("dob") or "1950-01-01"
        _pat_sex = _sex_code((_pat or {}).get("sex", "M"))
        _pat_age = _calculate_age(_pat_dob, year)
        _segment = score_row.get("model_segment", "CNA")
        _prefix = _SEGMENT_TO_PREFIX.get(_segment, "CNA_")

        # --- Blend metadata from stored columns (added in migration 003) ---
        _v24_score = score_row.get("v24_score")
        _v28_score = score_row.get("v28_score")
        _blended_raw = score_row.get("blended_raw_score")
        _blend_v24_w = score_row.get("blend_v24_weight")
        _blend_v28_w = score_row.get("blend_v28_weight")
        _v24_hcc_count = score_row.get("v24_hcc_count")
        _v28_hcc_count = score_row.get("v28_hcc_count")

        # Determine stored model version label for display
        _score_type = score_row.get("score_type", "prospective")
        if _blend_v24_w is not None and float(_blend_v24_w or 0) > 0 and float(_blend_v28_w or 0) > 0:
            _stored_model_version = "blended"
        elif _blend_v28_w is not None and float(_blend_v28_w or 0) == 1.0:
            _stored_model_version = "v28"
        elif _blend_v24_w is not None and float(_blend_v24_w or 0) == 1.0:
            _stored_model_version = "v24"
        else:
            _stored_model_version = _score_type  # fall back to score_type column

        _breakdown_result = {
            "patient_id": patient_id,
            "measurement_year": year,
            "score_type": _score_type,
            "model_segment": _segment,
            "demographic_score": demographic,
            "disease_score": disease,
            "interaction_score": interaction,
            "total_raw": float(score_row.get("total_raw") or raw_total),
            "subtotal": round(raw_total, 4),
            "raf_score": final_raf,
            "final_raf": final_raf,
            "payment_raf": final_raf,
            "normalization_factor": norm_val,
            "maci_factor": maci_val,
            "combined_adjustment_factor": combined_factor,
            "age": _pat_age,
            "sex": _pat_sex,
            "icd_codes": _stored_icd_codes,
            # --- V24/V28 blend fields ---
            "model_version": _stored_model_version,
            "v24_score": float(_v24_score) if _v24_score is not None else None,
            "v28_score": float(_v28_score) if _v28_score is not None else None,
            "blended_raw_score": float(_blended_raw) if _blended_raw is not None else None,
            "blend_weights": {
                "v24": float(_blend_v24_w) if _blend_v24_w is not None else None,
                "v28": float(_blend_v28_w) if _blend_v28_w is not None else None,
            },
            "v24_hcc_count": int(_v24_hcc_count) if _v24_hcc_count is not None else None,
            "v28_hcc_count": int(_v28_hcc_count) if _v28_hcc_count is not None else None,
            "engine_input": {
                "icd_codes": _stored_icd_codes,
                "age": _pat_age,
                "sex": _pat_sex,
                "prefix_override": _prefix,
                "model_segment": _segment,
                "maci": maci_val,
                "norm_factor": norm_val,
            },
            "engine_output": {
                "risk_score_raw": raw_total,
                "risk_score_payment": final_raf,
                "risk_score_demographics": demographic,
                "hcc_list": [str(h["hcc_code"]) for h in hcc_rows],
                "hcc_details": [
                    {
                        "hcc": str(h["hcc_code"]),
                        "coefficient": float(h.get("raf_coefficient") or 0),
                        "label": f"HCC {h['hcc_code']}",
                    }
                    for h in hcc_rows
                ],
                "all_coefficients": {},
            },
            "hcc_count": len(hcc_details),
            "hcc_details": hcc_details,
            # Keep hcc_contributions alias for any callers that use it
            "hcc_contributions": [
                {
                    "hcc_code": d["hcc_code"],
                    "label": d["hcc_label"],
                    "coefficient": d["coefficient"],
                    "icd10_codes": d["icd10_codes"],
                    "meat_status": d["meat_status"],
                }
                for d in hcc_details
            ],
        }
        cache_set(_cache_key, _breakdown_result, ttl=120)
        return _breakdown_result

    # Fall back to live calculation
    result = calculate_raf_score(patient_id, year, tenant_id=tenant_id)
    # Frontend expects hcc_details with hcc_code, hcc_label, coefficient, icd10_codes, meat_status
    if "hcc_contributions" in result and "hcc_details" not in result:
        result["hcc_details"] = [
            {
                "hcc_code": h["hcc_code"],
                "hcc_label": h.get("label", f"HCC {h['hcc_code']}"),
                "coefficient": h.get("coefficient", 0.0),
                "icd10_codes": h.get("icd10_codes", []),
                "meat_status": h.get("meat_status", "missing"),
            }
            for h in result["hcc_contributions"]
        ]
    # calculate_raf_score already invalidated any stale breakdown key; now
    # store the freshly-shaped result so subsequent calls are served from cache.
    cache_set(_cache_key, result, ttl=120)
    return result


# ---------------------------------------------------------------------------
# Convenience aliases used by routers
# ---------------------------------------------------------------------------


def get_age_band(dob: str, year: int = 2026) -> str:
    """Return age band string."""
    age = _calculate_age(dob, year)
    if age < 35:
        return "0-34"
    if age < 45:
        return "35-44"
    if age < 55:
        return "45-54"
    if age < 60:
        return "55-59"
    if age < 65:
        return "60-64"
    if age < 70:
        return "65-69"
    if age < 75:
        return "70-74"
    if age < 80:
        return "75-79"
    if age < 85:
        return "80-84"
    if age < 90:
        return "85-89"
    if age < 95:
        return "90-94"
    return "95+"


# ---------------------------------------------------------------------------
# CMS SAS Reconciliation
# ---------------------------------------------------------------------------

_CMS_SAS_TOLERANCE = 0.01  # ±0.01 is the industry-standard acceptable delta


def reconcile_with_cms_sas(
    patient_id: int,
    measurement_year: int,
    cms_sas_score: float | None = None,
    tenant_id: str = "1",
) -> dict[str, Any]:
    """Compare our RAF calculation against CMS SAS expected values.

    Runs the full RAF calculation for the patient and, when a reference score
    from CMS's official SAS software is supplied, produces a side-by-side
    reconciliation report.

    Args:
        patient_id:       OpenEMR patient PID.
        measurement_year: CMS payment year (e.g. 2026).
        cms_sas_score:    The expected payment RAF from CMS SAS output.
                          Pass None to get our score only (no comparison).
        tenant_id:        Tenant scope for HIPAA multi-tenant isolation.

    Returns a reconciliation report with:
        - our_score:        our calculated payment RAF
        - cms_score:        the CMS SAS value (if provided, else None)
        - delta:            (our_score - cms_score), None when cms_sas_score not given
        - abs_delta:        absolute value of delta, None when not comparable
        - tolerance:        True when abs_delta <= ±0.01, None when not comparable
        - within_tolerance: human-readable verdict string
        - breakdown:        component-by-component details from our engine
        - model_version:    which CMS-HCC model(s) were used
        - blend_weights:    V24/V28 blend weights applied
        - enrollment_info:  segment, dual status, OREC, institutional flag
        - engine_input:     full audit input passed to hccinfhir
        - engine_output:    full hccinfhir raw output
        - disclaimer:       CMS non-endorsement notice
    """
    result = calculate_raf_score(
        patient_id,
        measurement_year,
        tenant_id=tenant_id,
    )

    our_score: float = round(float(result.get("payment_raf") or 0.0), 4)

    # Build component breakdown from what calculate_raf_score already returns
    hcc_contributions: list[dict[str, Any]] = result.get("hcc_contributions") or []
    breakdown: dict[str, Any] = {
        "demographic_score": result.get("demographic_score"),
        "disease_score": result.get("disease_score"),
        "interaction_score": result.get("interaction_score"),
        "normalization_factor": result.get("normalization_factor"),
        "maci_factor": result.get("maci_factor"),
        "model_segment": result.get("model_segment"),
        "new_enrollee": result.get("new_enrollee", False),
        "esrd_segment": result.get("esrd_segment"),
        "icd_codes": result.get("icd_codes", []),
        "hcc_list": result.get("final_hcc_list") or result.get("raw_hcc_list") or [],
        "hcc_count": len(hcc_contributions),
        "hcc_contributions": [
            {
                "hcc_code": h.get("hcc_code"),
                "label": h.get("label") or h.get("hcc_label"),
                "coefficient": h.get("coefficient"),
                "icd10_codes": h.get("icd10_codes", []),
            }
            for h in hcc_contributions
        ],
        "v24_score": result.get("v24_score"),
        "v28_score": result.get("v28_score"),
        "v24_hcc_list": result.get("v24_hcc_list"),
        "v28_hcc_list": result.get("v28_hcc_list"),
        "blended_raw_score": result.get("blended_raw_score"),
        "concurrent_raf": result.get("concurrent_raf"),
        "prospective_raf": result.get("prospective_raf"),
        "suspected_raf_delta": result.get("suspected_raf_delta"),
    }

    # Comparison logic — only computed when a reference score is provided
    delta: float | None = None
    abs_delta: float | None = None
    tolerance: bool | None = None
    within_tolerance_label: str

    if cms_sas_score is not None:
        cms_score_rounded = round(float(cms_sas_score), 4)
        delta = round(our_score - cms_score_rounded, 4)
        abs_delta = round(abs(delta), 4)
        tolerance = abs_delta <= _CMS_SAS_TOLERANCE
        if tolerance:
            within_tolerance_label = (
                f"PASS — delta {delta:+.4f} is within ±{_CMS_SAS_TOLERANCE}"
            )
        else:
            within_tolerance_label = (
                f"FAIL — delta {delta:+.4f} exceeds ±{_CMS_SAS_TOLERANCE}; "
                "review HCC mapping, ICD code dates, and enrollment segment"
            )
    else:
        cms_score_rounded = None  # type: ignore[assignment]
        within_tolerance_label = "N/A — no CMS SAS score provided for comparison"

    return {
        "patient_id": patient_id,
        "measurement_year": measurement_year,
        "our_score": our_score,
        "cms_score": cms_score_rounded if cms_sas_score is not None else None,
        "delta": delta,
        "abs_delta": abs_delta,
        "tolerance": tolerance,
        "within_tolerance": within_tolerance_label,
        "breakdown": breakdown,
        "model_version": result.get("model_version"),
        "blend_weights": result.get("blend_weights"),
        "enrollment_info": result.get("enrollment_info"),
        "engine_input": result.get("engine_input"),
        "engine_output": result.get("engine_output"),
        "disclaimer": result.get(
            "_disclaimer",
            "RAF scores are estimates based on CMS-HCC models via hccinfhir. "
            "Not for payment submission.",
        ),
    }


def reconcile_batch(
    patient_ids: list[int],
    measurement_year: int,
    cms_sas_scores: dict[int, float] | None = None,
    tenant_id: str = "1",
) -> list[dict[str, Any]]:
    """Run CMS SAS reconciliation for multiple patients.

    Args:
        patient_ids:      List of OpenEMR patient PIDs.
        measurement_year: CMS payment year.
        cms_sas_scores:   Optional mapping of {patient_id: cms_sas_score}.
                          Patients not present in the map are reconciled without
                          a reference score.
        tenant_id:        Tenant scope for HIPAA multi-tenant isolation.

    Returns:
        List of reconciliation report dicts in the same order as patient_ids.
        Each entry is the output of reconcile_with_cms_sas, extended with an
        ``error`` key (None on success, error message string on failure) so that
        one bad patient does not abort the entire batch.
    """
    cms_sas_scores = cms_sas_scores or {}
    reports: list[dict[str, Any]] = []

    for pid in patient_ids:
        try:
            report = reconcile_with_cms_sas(
                patient_id=pid,
                measurement_year=measurement_year,
                cms_sas_score=cms_sas_scores.get(pid),
                tenant_id=tenant_id,
            )
            report["error"] = None
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "reconcile_batch: pid=%s year=%s failed: %s",
                pid,
                measurement_year,
                exc,
            )
            report = {
                "patient_id": pid,
                "measurement_year": measurement_year,
                "our_score": None,
                "cms_score": cms_sas_scores.get(pid),
                "delta": None,
                "abs_delta": None,
                "tolerance": None,
                "within_tolerance": f"ERROR — {exc}",
                "breakdown": {},
                "model_version": None,
                "blend_weights": None,
                "enrollment_info": None,
                "engine_input": None,
                "engine_output": None,
                "disclaimer": None,
                "error": str(exc),
            }
        reports.append(report)

    return reports
