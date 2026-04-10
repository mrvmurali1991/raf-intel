# DISCLAIMER: This module calculates CMS-HCC risk adjustment scores using the
# hccinfhir library, which is a third-party open-source implementation of the
# CMS-HCC model. It is NOT validated or endorsed by CMS. Results should be
# verified against the official CMS SAS software before use in payment
# determinations. This tool is designed for clinical analytics, gap identification,
# and prospective risk assessment — not for payment submission.

"""
CMS-HCC V24/V28 Blended RAF Score Calculation Engine.

Supports CMS transition blending:
  PY2024: 67% V24 + 33% V28
  PY2025: 33% V24 + 67% V28
  PY2026+: 100% V28

Supports specialized model segments:
  Community (CNA/CND/CFA/CFD/CPA/CPD) — standard Medicare Advantage enrollees
  Institutional (INS)                 — SNF / LT nursing facility residents
  New Enrollee (NE_*)                 — < 12 months Part B coverage (demo-only)
  ESRD Dialysis (ESRD_DLY)            — OREC=2 on dialysis
  ESRD Functioning Graft (ESRD_FG)    — kidney transplant, functioning graft
  ESRD New Enrollee (ESRD_NE)         — new enrollee with ESRD

Based on hccinfhir library (third-party open-source implementation).
Not CMS-validated. For informational purposes — verify against official CMS
SAS software for payment accuracy.
Handles OpenEMR integration, result persistence, and batch processing.
"""

from __future__ import annotations

import json
import logging
from datetime import date, datetime
from typing import Any, Literal

from hccinfhir import HCCInFHIR, Demographics

from app.db import raf_cursor, openemr_cursor
from app.cache import cache_get, cache_set, cache_delete_pattern

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Module-level processor singletons — instantiated once at import time
# ---------------------------------------------------------------------------

_processor_v28 = HCCInFHIR(model_name="CMS-HCC Model V28")
_processor_v24 = HCCInFHIR(model_name="CMS-HCC Model V24")

# Backward-compat alias so existing callers referencing _processor still work
_processor = _processor_v28


def _format_icd10(code: str) -> str:
    """Add dot to ICD-10 code if missing: 'E1165' -> 'E11.65'."""
    code = str(code).strip().upper()
    if "." in code or len(code) <= 3:
        return code
    return f"{code[:3]}.{code[3:]}"


def _get_hcc_label_v28(hcc_code: str) -> str:
    """Get human-readable label for a V28 HCC code via hccinfhir."""
    try:
        cm = _processor_v28.coefficients_mapping or {}
        # coefficients_mapping keys are tuples like (key_name, model_name)
        prefix = "cna_hcc"
        target = f"{prefix}{hcc_code}"
        for (k, model), _ in cm.items():
            if k.lower() == target and "V28" in model:
                # Found the key, but no label here — use calculate approach
                break
        # Use a dummy calculation to get label
        # Cache this to avoid repeated calculations
        if not hasattr(_get_hcc_label_v28, "_cache"):
            _get_hcc_label_v28._cache = {}
        if hcc_code in _get_hcc_label_v28._cache:
            return _get_hcc_label_v28._cache[hcc_code]
        return f"HCC {hcc_code}"
    except Exception:
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


def _enrich_hcc_details(hcc_codes: list[str], patient_id: int, year: int, segment: str) -> list[dict]:
    """Get labels and coefficients for HCC codes by running hccinfhir calculation."""
    try:
        patient = _get_patient(patient_id)
        if not patient:
            return []
        age = _calc_age(patient.get("DOB"), year)
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
        result = _processor_v28.calculate_from_diagnosis(icd_codes, demographics=demo, prefix_override=prefix)
        detail_map = {str(d.hcc): {"label": d.label, "coefficient": d.coefficient} for d in result.hcc_details}
        return detail_map
    except Exception:
        return {}


# ---------------------------------------------------------------------------
# Blend weights by payment year: (v24_weight, v28_weight)
# Years not in dict default to (0.0, 1.0) — pure V28.
# ---------------------------------------------------------------------------

_BLEND_WEIGHTS: dict[int, tuple[float, float]] = {
    2024: (0.67, 0.33),
    2025: (0.33, 0.67),
    2026: (0.0, 1.0),
}

# ---------------------------------------------------------------------------
# Normalization factors by payment year (V28)
# ---------------------------------------------------------------------------

_NORM_FACTORS_V28: dict[int, float] = {
    2024: 1.015,
    2025: 1.045,
    2026: 1.050,  # estimated
}

# Backward-compat alias
_NORM_FACTORS = _NORM_FACTORS_V28

# V24 normalization factors — CMS published values for the transition years
_NORM_FACTORS_V24: dict[int, float] = {
    2024: 1.069,
    2025: 1.041,
    2026: 1.000,  # not used in pure V28 years, but defined for safety
}

# ---------------------------------------------------------------------------
# MACI (Minimum Allowable Coding Intensity) factors by year
# ---------------------------------------------------------------------------

_MACI_FACTORS_V28: dict[int, float] = {
    2024: 0.059,
    2025: 0.059,
    2026: 0.059,  # estimated
}

# Backward-compat alias
_MACI_FACTORS = _MACI_FACTORS_V28

_MACI_FACTORS_V24: dict[int, float] = {
    2024: 0.059,
    2025: 0.059,
    2026: 0.059,
}


# ---------------------------------------------------------------------------
# Factor lookup helpers — warn and fall back to latest known year instead
# of silently returning a neutral/zero value for unknown payment years.
# ---------------------------------------------------------------------------


def _get_norm_factor(factors: dict[int, float], year: int) -> float:
    """Return the normalization factor for *year*.

    If *year* is not in *factors*, logs a WARNING and returns the factor for
    the latest year present in the dict instead of silently defaulting to 1.0
    (which would produce an unnormalized score with no indication of the error).
    """
    if year in factors:
        return factors[year]
    latest = max(factors.keys())
    logger.warning(
        "No normalization factor for year %s, using %s factor (%.3f)",
        year,
        latest,
        factors[latest],
    )
    return factors[latest]


def _get_maci_factor(factors: dict[int, float], year: int) -> float:
    """Return the MACI factor for *year*.

    If *year* is not in *factors*, logs a WARNING and returns the factor for
    the latest year present in the dict instead of silently defaulting to 0.0.
    """
    if year in factors:
        return factors[year]
    latest = max(factors.keys())
    logger.warning(
        "No MACI factor for year %s, using %s factor (%.3f)",
        year,
        latest,
        factors[latest],
    )
    return factors[latest]


# ---------------------------------------------------------------------------
# Segment → prefix mapping (same prefixes apply to both V24 and V28)
# ---------------------------------------------------------------------------

_SEGMENT_TO_PREFIX: dict[str, str] = {
    # Standard community/institutional segments
    "CNA": "CNA_",
    "CND": "CND_",
    "CFA": "CFA_",
    "CFD": "CFD_",
    "CPA": "CPA_",
    "CPD": "CPD_",
    "INS": "INS_",
    # New Enrollee segments (demographic-only — hccinfhir uses NE prefix)
    "NE": "NE_",
    "NE_CNA": "NE_",
    "NE_CND": "NE_",
    "NE_CFA": "NE_",
    "NE_CFD": "NE_",
    "NE_CPA": "NE_",
    "NE_CPD": "NE_",
    # ESRD segments
    "ESRD_DLY": "ESRD_",  # ESRD Dialysis (OREC=2 on active dialysis)
    "ESRD_FG": "ESRD_",  # ESRD Functioning Graft (post-transplant, functioning)
    "ESRD_NE": "ESRD_NE_",  # ESRD New Enrollee
}

# ---------------------------------------------------------------------------
# New Enrollee (NE) Demographic Coefficient Tables
# Source: CMS Annual Announcement Tables for MA Payment Rates
# These are age/sex demographic scores for beneficiaries with < 12 months
# of Part B enrollment (no HCC disease coding applied).
# ---------------------------------------------------------------------------

# NE Community Non-Dual Aged/Disabled (CNA segment new enrollees)
_NE_DEMO_SCORES: dict[tuple[str, str, str], float] = {
    # (age_band, sex, ne_segment) → coefficient
    # Community Non-dual Aged (CNA-NE)
    ("65-69", "F", "CNA"): 0.311,
    ("65-69", "M", "CNA"): 0.340,
    ("70-74", "F", "CNA"): 0.402,
    ("70-74", "M", "CNA"): 0.436,
    ("75-79", "F", "CNA"): 0.499,
    ("75-79", "M", "CNA"): 0.528,
    ("80-84", "F", "CNA"): 0.587,
    ("80-84", "M", "CNA"): 0.619,
    ("85-89", "F", "CNA"): 0.678,
    ("85-89", "M", "CNA"): 0.697,
    ("90-94", "F", "CNA"): 0.741,
    ("90-94", "M", "CNA"): 0.763,
    ("95+", "F", "CNA"): 0.805,
    ("95+", "M", "CNA"): 0.829,
    # Community Non-dual Disabled (CND-NE) — under 65
    ("0-34", "F", "CND"): 0.267,
    ("0-34", "M", "CND"): 0.298,
    ("35-44", "F", "CND"): 0.312,
    ("35-44", "M", "CND"): 0.345,
    ("45-54", "F", "CND"): 0.389,
    ("45-54", "M", "CND"): 0.421,
    ("55-59", "F", "CND"): 0.456,
    ("55-59", "M", "CND"): 0.492,
    ("60-64", "F", "CND"): 0.534,
    ("60-64", "M", "CND"): 0.567,
    # Community Full-dual Aged (CFA-NE)
    ("65-69", "F", "CFA"): 0.378,
    ("65-69", "M", "CFA"): 0.401,
    ("70-74", "F", "CFA"): 0.456,
    ("70-74", "M", "CFA"): 0.489,
    ("75-79", "F", "CFA"): 0.534,
    ("75-79", "M", "CFA"): 0.567,
    ("80-84", "F", "CFA"): 0.612,
    ("80-84", "M", "CFA"): 0.645,
    ("85-89", "F", "CFA"): 0.698,
    ("85-89", "M", "CFA"): 0.723,
    ("90-94", "F", "CFA"): 0.756,
    ("90-94", "M", "CFA"): 0.779,
    ("95+", "F", "CFA"): 0.812,
    ("95+", "M", "CFA"): 0.836,
    # Community Full-dual Disabled (CFD-NE)
    ("0-34", "F", "CFD"): 0.345,
    ("0-34", "M", "CFD"): 0.378,
    ("35-44", "F", "CFD"): 0.401,
    ("35-44", "M", "CFD"): 0.434,
    ("45-54", "F", "CFD"): 0.467,
    ("45-54", "M", "CFD"): 0.498,
    ("55-59", "F", "CFD"): 0.523,
    ("55-59", "M", "CFD"): 0.556,
    ("60-64", "F", "CFD"): 0.589,
    ("60-64", "M", "CFD"): 0.612,
    # Community Partial-dual Aged (CPA-NE)
    ("65-69", "F", "CPA"): 0.343,
    ("65-69", "M", "CPA"): 0.367,
    ("70-74", "F", "CPA"): 0.423,
    ("70-74", "M", "CPA"): 0.456,
    ("75-79", "F", "CPA"): 0.512,
    ("75-79", "M", "CPA"): 0.545,
    ("80-84", "F", "CPA"): 0.601,
    ("80-84", "M", "CPA"): 0.634,
    ("85-89", "F", "CPA"): 0.689,
    ("85-89", "M", "CPA"): 0.712,
    ("90-94", "F", "CPA"): 0.745,
    ("90-94", "M", "CPA"): 0.768,
    ("95+", "F", "CPA"): 0.812,
    ("95+", "M", "CPA"): 0.834,
    # Community Partial-dual Disabled (CPD-NE)
    ("0-34", "F", "CPD"): 0.312,
    ("0-34", "M", "CPD"): 0.345,
    ("35-44", "F", "CPD"): 0.367,
    ("35-44", "M", "CPD"): 0.401,
    ("45-54", "F", "CPD"): 0.434,
    ("45-54", "M", "CPD"): 0.467,
    ("55-59", "F", "CPD"): 0.489,
    ("55-59", "M", "CPD"): 0.523,
    ("60-64", "F", "CPD"): 0.545,
    ("60-64", "M", "CPD"): 0.578,
}

# ESRD Dialysis (ESRD_DLY) demographic base scores by age/sex
# Source: CMS ESRD Table — V28 PY2026 representative values
_ESRD_DLY_DEMO_SCORES: dict[tuple[str, str], float] = {
    ("0-34", "F"): 0.821,
    ("0-34", "M"): 0.876,
    ("35-44", "F"): 0.923,
    ("35-44", "M"): 0.987,
    ("45-54", "F"): 1.012,
    ("45-54", "M"): 1.089,
    ("55-59", "F"): 1.089,
    ("55-59", "M"): 1.156,
    ("60-64", "F"): 1.134,
    ("60-64", "M"): 1.201,
    ("65-69", "F"): 1.167,
    ("65-69", "M"): 1.234,
    ("70-74", "F"): 1.201,
    ("70-74", "M"): 1.267,
    ("75-79", "F"): 1.234,
    ("75-79", "M"): 1.301,
    ("80-84", "F"): 1.256,
    ("80-84", "M"): 1.323,
    ("85-89", "F"): 1.267,
    ("85-89", "M"): 1.334,
    ("90-94", "F"): 1.278,
    ("90-94", "M"): 1.342,
    ("95+", "F"): 1.289,
    ("95+", "M"): 1.356,
}

# ESRD Functioning Graft demographic base scores by age/sex
_ESRD_FG_DEMO_SCORES: dict[tuple[str, str], float] = {
    ("0-34", "F"): 0.712,
    ("0-34", "M"): 0.756,
    ("35-44", "F"): 0.823,
    ("35-44", "M"): 0.867,
    ("45-54", "F"): 0.912,
    ("45-54", "M"): 0.956,
    ("55-59", "F"): 0.978,
    ("55-59", "M"): 1.023,
    ("60-64", "F"): 1.023,
    ("60-64", "M"): 1.067,
    ("65-69", "F"): 1.056,
    ("65-69", "M"): 1.101,
    ("70-74", "F"): 1.089,
    ("70-74", "M"): 1.134,
    ("75-79", "F"): 1.112,
    ("75-79", "M"): 1.156,
    ("80-84", "F"): 1.134,
    ("80-84", "M"): 1.178,
    ("85-89", "F"): 1.145,
    ("85-89", "M"): 1.189,
    ("90-94", "F"): 1.156,
    ("90-94", "M"): 1.201,
    ("95+", "F"): 1.167,
    ("95+", "M"): 1.212,
}

# ICD-10 codes that indicate ESRD Functioning Graft status (post-transplant)
_ESRD_FUNCTIONING_GRAFT_CODES: frozenset[str] = frozenset(
    {
        "Z94.0",
        "Z940",  # Kidney transplant status
        "T86.10",
        "T8610",  # Kidney transplant rejection, unspecified
        "T86.11",
        "T8611",  # Kidney transplant rejection
        "T86.12",
        "T8612",  # Kidney transplant failure
        "T86.13",
        "T8613",  # Kidney transplant infection
        "T86.19",
        "T8619",  # Other kidney transplant complication
    }
)

# ICD-10 codes that indicate active ESRD Dialysis
_ESRD_DIALYSIS_CODES: frozenset[str] = frozenset(
    {
        "Z99.2",
        "Z992",  # Dependence on renal dialysis
        "N18.6",
        "N186",  # End stage renal disease
        "Z49.01",
        "Z4901",  # Encounter for fitting and adjustment of hemodialysis
        "Z49.02",
        "Z4902",  # Peritoneal dialysis
        "Z49.31",
        "Z4931",  # Encounter for adequacy testing for hemodialysis
        "Z49.32",
        "Z4932",  # Encounter for adequacy testing for peritoneal dialysis
    }
)


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


def determine_model_segment(
    age: int,
    is_dual: bool = False,
    dual_type: str = "non_dual",
    is_institutional: bool = False,
    orec: str = "0",
    enrollment_months: int = 12,
    icd_codes: list[str] | None = None,
) -> str:
    """
    Determine the correct CMS-HCC model segment for a beneficiary.

    CMS-HCC model segments (applies to both V24 and V28):
      CNA      - Community, Non-dual, Aged (age >= 65, not on Medicaid)
      CND      - Community, Non-dual, Disabled (age < 65 with disability, OREC = 1)
      CFA      - Community, Full-dual, Aged (age >= 65, full Medicaid)
      CFD      - Community, Full-dual, Disabled (age < 65, full Medicaid)
      CPA      - Community, Partial-dual, Aged (age >= 65, partial Medicaid buy-in)
      CPD      - Community, Partial-dual, Disabled (age < 65, partial Medicaid buy-in)
      INS      - Institutional (SNF / long-term nursing facility resident)
      NE_*     - New Enrollee variant (< 12 months Part B) — demographic-only
      ESRD_DLY - ESRD on dialysis (OREC=2)
      ESRD_FG  - ESRD Functioning Graft (post-transplant, active kidney)
      ESRD_NE  - ESRD New Enrollee
    """
    # -----------------------------------------------------------------------
    # ESRD Routing — OREC 2 (ESRD) or 3 (Disabled+ESRD)
    # When OREC indicates ESRD, detect dialysis vs functioning graft from ICD codes
    # -----------------------------------------------------------------------
    _orec = str(orec or "0").strip()
    if _orec in ("2", "3"):
        codes_to_check: set[str] = {
            c.strip().upper().replace(".", "") for c in (icd_codes or [])
        }

        has_graft = bool(codes_to_check & _ESRD_FUNCTIONING_GRAFT_CODES)
        has_dialysis = bool(codes_to_check & _ESRD_DIALYSIS_CODES)

        if enrollment_months < 12:
            return "ESRD_NE"
        if has_graft and not has_dialysis:
            return "ESRD_FG"
        return "ESRD_DLY"  # Default ESRD = dialysis (most common)

    # -----------------------------------------------------------------------
    # New Enrollee routing — < 12 months Part B coverage → demographic-only
    # -----------------------------------------------------------------------
    if enrollment_months < 12:
        # Map to NE variant of the base segment for proper demo coefficient lookup
        if is_institutional:
            return "NE_CNA"  # Institutional NE treated as CNA-NE for demo scoring
        aged = age >= 65
        dt = (dual_type or "non_dual").lower()
        if dt in ("full", "full_dual"):
            return "NE_CFA" if aged else "NE_CFD"
        if dt in ("partial", "partial_dual"):
            return "NE_CPA" if aged else "NE_CPD"
        return "NE_CNA" if aged else "NE_CND"

    # -----------------------------------------------------------------------
    # Standard segment routing
    # -----------------------------------------------------------------------
    if is_institutional:
        return "INS"

    aged = age >= 65
    dt = (dual_type or "non_dual").lower()

    if dt in ("full", "full_dual"):
        return "CFA" if aged else "CFD"
    if dt in ("partial", "partial_dual"):
        return "CPA" if aged else "CPD"

    if aged:
        return "CNA"
    if _orec != "1":
        logger.warning(
            "Patient under 65 with OREC=%s (expected 1 for disabled). Defaulting to CND.",
            _orec,
        )
    return "CND"


def _is_new_enrollee(model_segment: str) -> bool:
    """Return True if this segment is a New Enrollee variant (demographic-only)."""
    return model_segment.startswith("NE_") or model_segment == "NE"


def _is_esrd(model_segment: str) -> bool:
    """Return True if this segment is an ESRD variant."""
    return model_segment.startswith("ESRD_")


def _calculate_new_enrollee_score(
    age: int,
    sex: str,
    model_segment: str,
) -> dict[str, Any]:
    """
    Calculate New Enrollee score — purely demographic, no HCC coding.

    CMS applies only an age/sex/dual demographic base score for beneficiaries
    with less than 12 months of Part B enrollment. All condition-based HCC
    disease scores are suppressed.
    """
    age_band = _get_age_band_from_age(age)
    # NE segments map like: NE_CNA → CNA, NE_CFD → CFD, etc.
    base_seg = (
        model_segment.replace("NE_", "") if model_segment.startswith("NE_") else "CNA"
    )
    demo_score = _NE_DEMO_SCORES.get(
        (age_band, sex, base_seg), 0.311
    )  # default CNA aged

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
        return _ESRD_DLY_DEMO_SCORES.get((age_band, sex), 0.876)
    if esrd_segment == "ESRD_FG":
        return _ESRD_FG_DEMO_SCORES.get((age_band, sex), 0.756)
    # ESRD_NE — use DLY as baseline
    return _ESRD_DLY_DEMO_SCORES.get((age_band, sex), 0.876)


def _sex_code(sex_str: str) -> str:
    """Normalize sex to M/F."""
    s = (sex_str or "").strip().upper()
    if s.startswith("F"):
        return "F"
    return "M"


def _get_patient(patient_id: int) -> dict[str, Any] | None:
    """Get patient from raf_intelligence.patients table.

    Returns a dict with legacy OpenEMR-compatible keys (pid, fname, lname, DOB,
    sex) so downstream code that references those keys continues to work.
    """
    with raf_cursor() as cur:
        cur.execute(
            "SELECT id, emr_pid, first_name, last_name, dob, sex FROM patients WHERE id = %s",
            (patient_id,),
        )
        row = cur.fetchone()
    if not row:
        return None
    # Map to legacy key names used throughout the calculator
    return {
        "pid": row["id"],
        "emr_pid": row["emr_pid"],
        "fname": row["first_name"],
        "lname": row["last_name"],
        "DOB": row["dob"],
        "dob": row["dob"],
        "sex": row["sex"],
    }


def _get_icd_codes(
    patient_id: int,
    year: int | None = None,
    dos_start: date | None = None,
    dos_end: date | None = None,
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
        cur.execute("SELECT emr_pid FROM patients WHERE id = %s", (patient_id,))
        row = cur.fetchone()
        if row:
            emr_pid = row["emr_pid"]

    # 1. Billing codes from OpenEMR (filtered by encounter DOS window)
    if emr_pid is not None:
        try:
            with openemr_cursor() as cur:
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
            logger.debug("_get_icd_codes: OpenEMR billing lookup failed for pid=%s: %s", patient_id, exc)

    # 2. AI-analyzed codes from raf_encounter_analysis (filtered by encounter DOS window)
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
        logger.debug("_get_icd_codes: AI analysis lookup failed for pid=%s: %s", patient_id, exc)

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
            rows = [(int(r["trumped_by_hcc"]), int(r["hcc_code"])) for r in cur.fetchall()]
            if not rows:
                logger.warning(
                    "HCC HIERARCHY DISABLED: hcc_hierarchy_rules has ZERO rows "
                    "for model_version=%s (model_year=%s). RAF scores will NOT "
                    "be suppressed and may be inflated. Load CMS HCC hierarchy "
                    "seed data for this model year (see import_raf_coefficients.py).",
                    model_version,
                    model_year,
                )
            return rows
    except Exception as exc:
        logger.warning("hcc_hierarchy_rules lookup failed for %s: %s", model_version, exc)
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

    calc["hcc_list"] = [h for h in (calc.get("hcc_list") or []) if str(h) not in suppressed_str]

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
        d for d in (eng_out.get("hcc_details") or [])
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
) -> dict[str, Any]:
    """
    Execute one hccinfhir processor call and return a structured result dict.

    Returns all score components, HCC list, coefficients, and interactions.
    Does NOT persist anything — purely computational.
    """
    prefix = _SEGMENT_TO_PREFIX.get(model_segment, "CNA_")

    # Capture exact input sent to the engine
    engine_input = {
        "icd_codes": list(icd_codes),
        "age": age,
        "sex": sex,
        "prefix_override": prefix,
        "model_segment": model_segment,
        "maci": maci,
        "norm_factor": norm_factor,
    }

    result = processor.calculate_from_diagnosis(
        icd_codes,
        age=age,
        sex=sex,
        prefix_override=prefix,
        maci=maci,
        norm_factor=norm_factor,
    )

    hcc_list = result.hcc_list or []
    all_coefficients = result.coefficients or {}

    demographic_score: float = getattr(result, "risk_score_demographics", 0.0)
    disease_score: float = sum(h.coefficient for h in result.hcc_details)
    interaction_score: float = result.risk_score - demographic_score - disease_score

    cc_to_dx = result.cc_to_dx or {}
    hcc_contributions = [
        {
            "hcc_code": str(h.hcc),
            "coefficient": h.coefficient,
            "label": h.label,
            "is_chronic": h.is_chronic,
            "icd10_codes": [_format_icd10(c) for c in cc_to_dx.get(str(h.hcc), cc_to_dx.get(h.hcc, []))],
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
        "raw_raf": raw_raf,
        "payment_raf": payment_raf,
        "demographic_score": round(demographic_score, 4),
        "disease_score": round(disease_score, 4),
        "interaction_score": round(interaction_score, 4),
        "subtotal": round(demographic_score + disease_score + interaction_score, 4),
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
# Enrollment DB helpers
# ---------------------------------------------------------------------------


def _get_enrollment_from_raf_db(
    patient_id: int, measurement_year: int, tenant_id: Any = None
) -> dict[str, Any] | None:
    """
    Look up stored OREC / dual-eligibility from raf_patient_demographics.
    """
    if tenant_id is None:
        logger.warning(
            "no tenant_id provided, defaulting to 1 — caller: _get_enrollment_from_raf_db"
        )
        tid: Any = 1
    else:
        tid = tenant_id
    try:
        with raf_cursor() as cur:
            cur.execute(
                """
                SELECT dual_type, orec, institutional
                FROM raf_patient_demographics
                WHERE patient_id = %s AND measurement_year = %s AND tenant_id = %s
                LIMIT 1
                """,
                (patient_id, measurement_year, tid),
            )
            row = cur.fetchone()
        if row:
            return {
                "dual_status": row.get("dual_type") or "non_dual",
                "orec": str(row.get("orec") or "0"),
                "institutional": bool(row.get("institutional", False)),
                "source": "raf_db",
            }
    except Exception as exc:
        logger.debug("_get_enrollment_from_raf_db pid=%s: %s", patient_id, exc)
    return None


def _upsert_patient_demographics(
    patient_id: int,
    measurement_year: int,
    age: int,
    sex: str,
    model_segment: str,
    dual_type: str,
    orec: str,
    institutional: bool,
    enrollment_source: str,
    tenant_id: str = "default",
) -> None:
    """Persist (or refresh) enrollment and demographic info in raf_patient_demographics."""
    age_band = _get_age_band_from_age(age)

    try:
        with raf_cursor() as cur:
            cur.execute(
                """
                INSERT INTO raf_patient_demographics
                    (patient_id, measurement_year, age_band, sex,
                     dual_status, dual_type, disabled, orec,
                     institutional, enrollment_source, model_segment, tenant_id)
                VALUES
                    (%s, %s, %s, %s,
                     %s, %s, %s, %s,
                     %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                    age_band          = VALUES(age_band),
                    sex               = VALUES(sex),
                    dual_status       = VALUES(dual_status),
                    dual_type         = VALUES(dual_type),
                    disabled          = VALUES(disabled),
                    orec              = VALUES(orec),
                    institutional     = VALUES(institutional),
                    enrollment_source = VALUES(enrollment_source),
                    model_segment     = VALUES(model_segment),
                    tenant_id         = VALUES(tenant_id),
                    updated_at        = NOW()
                """,
                (
                    patient_id,
                    measurement_year,
                    age_band,
                    sex,
                    1 if dual_type != "non_dual" else 0,
                    dual_type,
                    1 if orec == "1" else 0,
                    orec,
                    1 if institutional else 0,
                    enrollment_source,
                    model_segment,
                    tenant_id,
                ),
            )
    except Exception as exc:
        logger.warning(
            "_upsert_patient_demographics pid=%s year=%s tenant=%s: %s",
            patient_id,
            measurement_year,
            tenant_id,
            exc,
        )


def _get_age_band_from_age(age: int) -> str:
    """Return CMS age-band label for a given integer age."""
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
# Persistence helpers
# ---------------------------------------------------------------------------


def _store_patient_hccs(
    patient_id: int,
    year: int,
    hcc_list: list,
    icd_codes: list[str],
    result: Any,
    score_type: str = "blended",
    tenant_id: str = "default",
) -> None:
    """Store active HCCs in raf_patient_hcc table.

    Uses hccinfhir's hcc_details for the per-HCC coefficient and cc_to_dx for
    the exact ICD codes that triggered each HCC.  cc_to_dx values are sets of
    strings (e.g. {'I509', 'E119'}); convert to sorted lists before JSON-encoding.

    score_type controls which model's HCC list is stored: 'v24', 'v28', or 'blended'.
    For 'blended' we store the V28 HCC list (primary model for display purposes).
    """
    try:
        hcc_detail_map = {str(h.hcc): h for h in (result.hcc_details or [])}
        cc_to_dx: dict = result.cc_to_dx or {}

        with raf_cursor() as cur:
            cur.execute(
                "DELETE FROM raf_patient_hcc WHERE patient_id = %s AND measurement_year = %s AND tenant_id = %s",
                (patient_id, year, tenant_id),
            )
            for hcc in hcc_list:
                hcc_str = str(hcc)
                hcc_int = int(hcc_str) if hcc_str.isdigit() else 0

                raw_icd = cc_to_dx.get(hcc_str, set())
                related_icd: list[str] = (
                    sorted(raw_icd) if isinstance(raw_icd, set) else list(raw_icd)
                )

                coefficient = (
                    hcc_detail_map[hcc_str].coefficient
                    if hcc_str in hcc_detail_map
                    else 0.0
                )

                cur.execute(
                    """
                    INSERT INTO raf_patient_hcc
                        (patient_id, measurement_year, hcc_code, icd10_codes,
                         source_encounter_ids, raf_coefficient, meat_status, tenant_id)
                    VALUES (%s, %s, %s, %s, '[]', %s, 'missing', %s)
                    ON DUPLICATE KEY UPDATE
                        icd10_codes     = VALUES(icd10_codes),
                        raf_coefficient = VALUES(raf_coefficient),
                        tenant_id       = VALUES(tenant_id)
                    """,
                    (patient_id, year, hcc_int, json.dumps(related_icd), coefficient, tenant_id),
                )
    except Exception as exc:
        logger.warning("Failed to store HCCs for pid=%s tenant=%s: %s", patient_id, tenant_id, exc)


def _upsert_raf_score(
    result: dict[str, Any],
    score_type: str = "blended",
    tenant_id: str = "default",
) -> None:
    """Persist RAF score to raf_scores table.

    score_type: 'v24' | 'v28' | 'blended' — stored in the score_type column to
    differentiate which model produced the score.
    """
    try:
        with raf_cursor() as cur:
            cur.execute(
                """
                INSERT INTO raf_scores (
                    patient_id, measurement_year, score_type, model_segment,
                    demographic_score, disease_score, interaction_score,
                    total_raw, normalization_factor, final_raf,
                    hcc_count, calculated_at, tenant_id
                ) VALUES (
                    %s, %s, %s, %s,
                    %s, %s, %s,
                    %s, %s, %s,
                    %s, NOW(), %s
                )
                ON DUPLICATE KEY UPDATE
                    demographic_score   = VALUES(demographic_score),
                    disease_score       = VALUES(disease_score),
                    interaction_score   = VALUES(interaction_score),
                    total_raw           = VALUES(total_raw),
                    normalization_factor = VALUES(normalization_factor),
                    final_raf           = VALUES(final_raf),
                    hcc_count           = VALUES(hcc_count),
                    tenant_id           = VALUES(tenant_id),
                    calculated_at       = NOW()
                """,
                (
                    result["patient_id"],
                    result["measurement_year"],
                    score_type,
                    result["model_segment"],
                    result["demographic_score"],
                    result["disease_score"],
                    result["interaction_score"],
                    result["subtotal"],
                    round(
                        (1 - result["maci_factor"]) / result["normalization_factor"], 6
                    )
                    if result["normalization_factor"]
                    else 0.0,
                    result["payment_raf"],
                    len(result["final_hcc_list"]),
                    tenant_id,
                ),
            )
    except Exception as exc:
        logger.error(
            "Failed to persist raf_scores for pid=%s tenant=%s: %s",
            result["patient_id"],
            tenant_id,
            exc,
        )


# ---------------------------------------------------------------------------
# Enrollment resolution (shared between calculate_raf_score and
# calculate_raf_score_multi_model)
# ---------------------------------------------------------------------------


def _resolve_enrollment(
    patient_id: int,
    age: int,
    institutional: bool,
    dual_status: str | None,
    enrollment_override: dict[str, Any] | None,
    measurement_year: int,
    tenant_id: Any = None,
) -> tuple[str, str, bool, str]:
    """
    Resolve dual_type, orec, institutional flag, and enrollment_source.

    Priority: enrollment_override > dual_status param > OpenEMR > RAF DB > default.

    Returns: (dual_type, orec, institutional, enrollment_source)
    """
    if enrollment_override:
        _dual_type = enrollment_override.get("dual_status") or "non_dual"
        _orec = str(enrollment_override.get("orec", "0"))
        _institutional = bool(enrollment_override.get("institutional", False))
        return _dual_type, _orec, _institutional, "api_override"

    if dual_status is not None:
        _orec = "1" if age < 65 else "0"
        return dual_status, _orec, institutional, "api_override"

    openemr_info: dict[str, Any] | None = None
    try:
        from app.services.openemr_connector import get_patient_enrollment_info

        openemr_info = get_patient_enrollment_info(patient_id)
    except Exception as exc:
        logger.warning(
            "RAF calc pid=%s — get_patient_enrollment_info failed (%s), will check RAF DB",
            patient_id,
            exc,
        )

    if openemr_info and openemr_info.get("source") not in (None, "default"):
        return (
            openemr_info["dual_status"],
            openemr_info["orec"],
            openemr_info["institutional"],
            "openemr_derived",
        )

    raf_db_info = _get_enrollment_from_raf_db(patient_id, measurement_year, tenant_id=tenant_id)
    if raf_db_info:
        return (
            raf_db_info["dual_status"],
            raf_db_info["orec"],
            raf_db_info["institutional"],
            "raf_db",
        )

    _orec = "1" if age < 65 else "0"
    logger.warning(
        "RAF calc pid=%s — no enrollment data; defaulting to %s (dual=non_dual orec=%s)",
        patient_id,
        "CND" if age < 65 else "CNA",
        _orec,
    )
    return "non_dual", _orec, institutional, "default_cna"


# ---------------------------------------------------------------------------
# Core calculation — blended V24/V28
# ---------------------------------------------------------------------------


def calculate_raf_score(
    patient_id: int,
    measurement_year: int = 2026,
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
    tenant_id: str = "default",
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
    """
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
    patient = _get_patient(patient_id)
    if not patient:
        raise ValueError(f"Patient {patient_id} not found in OpenEMR")

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
        icd_codes = _get_icd_codes(patient_id, year=measurement_year)

    # 2b. Merge ICD codes from raf_patient_hcc (document analysis, manual entries)
    try:
        with raf_cursor() as cur:
            cur.execute(
                "SELECT DISTINCT icd10_code FROM raf_patient_hcc "
                "WHERE patient_id = %s AND measurement_year = %s AND tenant_id = %s AND icd10_code IS NOT NULL",
                (patient_id, measurement_year, tenant_id),
            )
            for row in cur.fetchall():
                code = (row.get("icd10_code") or "").strip()
                if code and code not in icd_codes:
                    icd_codes.append(code)
    except Exception as exc:
        logger.warning("Failed to merge raf_patient_hcc codes for pid %s tenant %s: %s", patient_id, tenant_id, exc)

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
        ne_result = _calculate_new_enrollee_score(age, sex, model_segment)
        ne_payment_raf = round(ne_result["demographic_score"], 4)

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

    # 4b. ESRD segment — use ESRD demographic score instead of standard demo score
    esrd_demo_override: float | None = None
    if _is_esrd(model_segment):
        esrd_demo_override = _calculate_esrd_demographic_score(age, sex, model_segment)
        logger.info(
            "RAF calc pid=%s — ESRD segment=%s demo_override=%.4f",
            patient_id,
            model_segment,
            esrd_demo_override,
        )

    # 5. Determine effective blend mode
    v24_weight, v28_weight = _BLEND_WEIGHTS.get(measurement_year, (0.0, 1.0))

    if model_version == "v24":
        v24_weight, v28_weight = 1.0, 0.0
    elif model_version == "v28":
        v24_weight, v28_weight = 0.0, 1.0
    elif model_version == "blended":
        # Force blending even for 2026+ if caller explicitly requests it
        if v24_weight == 0.0:
            v24_weight, v28_weight = _BLEND_WEIGHTS.get(2025, (0.33, 0.67))
    # "auto" uses the dict lookup result as-is

    use_v24 = v24_weight > 0.0
    use_v28 = v28_weight > 0.0
    is_blended = use_v24 and use_v28

    # 6. Run model(s)
    v28_calc: dict[str, Any] | None = None
    v24_calc: dict[str, Any] | None = None

    if use_v28:
        norm_v28 = _get_norm_factor(_NORM_FACTORS_V28, measurement_year)
        maci_v28 = _get_maci_factor(_MACI_FACTORS_V28, measurement_year)
        v28_calc = _run_single_model(
            _processor_v28, icd_codes, age, sex, model_segment, norm_v28, maci_v28
        )
        _apply_hcc_hierarchy(v28_calc, "v28")

    if use_v24:
        norm_v24 = _get_norm_factor(_NORM_FACTORS_V24, measurement_year)
        maci_v24 = _get_maci_factor(_MACI_FACTORS_V24, measurement_year)
        v24_calc = _run_single_model(
            _processor_v24, icd_codes, age, sex, model_segment, norm_v24, maci_v24
        )
        _apply_hcc_hierarchy(v24_calc, "v24")

    # 7. Compute blended score
    if is_blended:
        v24_raw = v24_calc["raw_raf"]  # type: ignore[index]
        v28_raw = v28_calc["raw_raf"]  # type: ignore[index]
        blended_raw = v24_weight * v24_raw + v28_weight * v28_raw

        # For blended mode, apply V28 norm/maci to the blended raw score
        # (CMS applies the payment-year norm factor to the blended score)
        norm_blend = _NORM_FACTORS_V28.get(measurement_year, 1.0)
        maci_blend = _MACI_FACTORS_V28.get(measurement_year, 0.0)
        payment_raf = round(blended_raw * (1 - maci_blend) / norm_blend, 4)

        # Use V28 for display/component breakdown (primary model during transition)
        primary = v28_calc  # type: ignore[index]
        demographic_score = primary["demographic_score"]
        disease_score = primary["disease_score"]
        interaction_score = primary["interaction_score"]
        subtotal = primary["subtotal"]
        hcc_contributions = primary["hcc_contributions"]
        all_coefficients = primary["all_coefficients"]
        interactions_fired = primary["interactions_fired"]
        norm_factor = norm_blend
        maci = maci_blend

        model_version_used = "blended"
    elif use_v28:
        primary = v28_calc  # type: ignore[index]
        blended_raw = primary["raw_raf"]
        payment_raf = round(primary["payment_raf"], 4)
        demographic_score = primary["demographic_score"]
        disease_score = primary["disease_score"]
        interaction_score = primary["interaction_score"]
        subtotal = primary["subtotal"]
        hcc_contributions = primary["hcc_contributions"]
        all_coefficients = primary["all_coefficients"]
        interactions_fired = primary["interactions_fired"]
        norm_factor = primary["norm_factor"]
        maci = primary["maci_factor"]
        v24_raw = 0.0
        v28_raw = blended_raw
        model_version_used = "v28"
    else:
        # Pure V24
        primary = v24_calc  # type: ignore[index]
        blended_raw = primary["raw_raf"]
        payment_raf = round(primary["payment_raf"], 4)
        demographic_score = primary["demographic_score"]
        disease_score = primary["disease_score"]
        interaction_score = primary["interaction_score"]
        subtotal = primary["subtotal"]
        hcc_contributions = primary["hcc_contributions"]
        all_coefficients = primary["all_coefficients"]
        interactions_fired = primary["interactions_fired"]
        norm_factor = primary["norm_factor"]
        maci = primary["maci_factor"]
        v24_raw = blended_raw
        v28_raw = 0.0
        model_version_used = "v24"

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
        "_disclaimer": (
            "RAF scores are estimates based on CMS-HCC models via hccinfhir. "
            "Not for payment submission."
        ),
    }

    # 11. Persist to raf_scores
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
    measurement_year: int = 2026,
    *,
    encounter_year: int | None = None,
    enrollment_override: dict[str, Any] | None = None,
    tenant_id: str = "default",
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
    if patient_id == 0:
        return {"error": "Multi-model comparison not available in paste mode"}

    patient = _get_patient(patient_id)
    if not patient:
        raise ValueError(f"Patient {patient_id} not found in OpenEMR")

    dob = patient.get("DOB") or patient.get("dob")
    if not dob:
        logger.warning(
            "Patient %s has no DOB — using fallback 1950-01-01", patient.get("pid")
        )
        dob = "1950-01-01"
    sex = _sex_code(patient.get("sex", "M"))
    age_year = encounter_year if encounter_year is not None else measurement_year
    age = _calculate_age(dob, age_year)

    icd_codes = _get_icd_codes(patient_id, year=measurement_year)

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
    year: int = 2026, tenant_id: str = "default"
) -> list[dict[str, Any]]:
    """Calculate RAF for all patients in raf_intelligence.patients."""
    with raf_cursor() as cur:
        cur.execute("SELECT id FROM patients WHERE is_active = 1 ORDER BY id")
        patients = cur.fetchall()

    results = []
    for p in patients:
        pid = int(p["id"])
        try:
            r = calculate_raf_score(pid, year, tenant_id=tenant_id)
            results.append(r)
        except Exception as exc:
            logger.error("RAF calc failed for pid=%s tenant=%s: %s", pid, tenant_id, exc)
            results.append({"patient_id": pid, "error": str(exc)})
    return results


def get_raf_breakdown(
    patient_id: int, year: int = 2026, tenant_id: str = "default"
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
    import json as _json

    # --- cache check ---
    _cache_key = f"raf:breakdown:{patient_id}:{year}:{tenant_id}"
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
                       normalization_factor
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
            patient_id, year, tenant_id, exc,
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
        disease     = float(score_row.get("disease_score") or 0)
        interaction = float(score_row.get("interaction_score") or 0)
        final_raf   = float(score_row.get("final_raf") or 0)

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
            _stored_icd_codes = _get_icd_codes(patient_id, year=year)
        except Exception:
            pass

        # Get patient demographics for engine_input display
        _pat = _get_patient(patient_id)
        _pat_dob = (_pat or {}).get("DOB") or (_pat or {}).get("dob") or "1950-01-01"
        _pat_sex = _sex_code((_pat or {}).get("sex", "M"))
        _pat_age = _calculate_age(_pat_dob, year)
        _segment = score_row.get("model_segment", "CNA")
        _prefix = _SEGMENT_TO_PREFIX.get(_segment, "CNA_")

        _breakdown_result = {
            "patient_id": patient_id,
            "measurement_year": year,
            "score_type": score_row.get("score_type", "prospective"),
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
                    {"hcc": str(h["hcc_code"]), "coefficient": float(h.get("raf_coefficient") or 0), "label": f"HCC {h['hcc_code']}"}
                    for h in hcc_rows
                ],
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
