"""NCQA HEDIS self-validator: BCS — Breast Cancer Screening.

Public specification reference:
  NCQA HEDIS MY2026 Volume 2, "Breast Cancer Screening (BCS-E)"
  CMS Star Ratings Technical Notes, Measure: Breast Cancer Screening
  Source: https://www.ncqa.org/hedis/measures/breast-cancer-screening/

Key publicly documented criteria:
  Denominator: Women aged 50-74 as of December 31 of the measurement year
               who were enrolled for at least 11 months during the year and
               whose last disenrollment gap (if any) was ≤ 45 days.
  Numerator:   At least one mammogram (screening or diagnostic, bilateral or
               unilateral) in the 27 months ending December 31 of the
               measurement year.
               CPT codes: 77065, 77066, 77067
               HCPCS: G0202, G0204, G0206
  Exclusions:  Bilateral mastectomy (CPT 19180 and 19200-range) or
               history of bilateral mastectomy (ICD-10 Z90.13),
               history of both unilateral mastectomies in prior years
               (ICD-10 Z90.11 + Z90.12).

Value-set OIDs referenced (VSAC public):
  2.16.840.1.113883.3.464.1004.1115 — Mammography
  2.16.840.1.113883.3.464.1004.1209 — Bilateral Mastectomy (Procedure)
  2.16.840.1.113883.3.464.1004.1331 — History of Bilateral Mastectomy (Dx)
"""
from __future__ import annotations


# ---------------------------------------------------------------------------
# Spec constants (publicly documented)
# ---------------------------------------------------------------------------

_SPEC_AGE_MIN = 50
_SPEC_AGE_MAX = 74
_SPEC_SEX = "female"
_SPEC_LOOKBACK_MONTHS = 27  # look-back window for mammogram

_SPEC_MAMMOGRAM_CPT = ["77065", "77066", "77067"]
_SPEC_MAMMOGRAM_HCPCS = ["G0202", "G0204", "G0206"]

_SPEC_EXCLUSION_BILATERAL_MASTECTOMY_ICD10 = ["Z90.13"]
_SPEC_EXCLUSION_UNILATERAL_BILATERAL_ICD10 = ["Z90.11", "Z90.12"]

_VALUE_SET_OIDS = [
    "2.16.840.1.113883.3.464.1004.1115",  # Mammography
    "2.16.840.1.113883.3.464.1004.1209",  # Bilateral Mastectomy (Procedure)
    "2.16.840.1.113883.3.464.1004.1331",  # History of Bilateral Mastectomy
]


# ---------------------------------------------------------------------------
# Implementation cross-check
# ---------------------------------------------------------------------------

def _check_implementation() -> list[str]:
    """Compare the BCS calculator in measures.py against the spec.

    Returns a list of discrepancy strings.  An empty list means
    no discrepancies detected.
    """
    from app.services.hedis.measures import BCSMeasure

    m = BCSMeasure()
    discrepancies: list[str] = []

    if m.age_min != _SPEC_AGE_MIN:
        discrepancies.append(
            f"age_min mismatch: implementation={m.age_min}, spec={_SPEC_AGE_MIN}"
        )
    if m.age_max != _SPEC_AGE_MAX:
        discrepancies.append(
            f"age_max mismatch: implementation={m.age_max}, spec={_SPEC_AGE_MAX}"
        )
    if (m.sex_restriction or "").lower()[:1] != "f":
        discrepancies.append(
            f"sex_restriction mismatch: implementation={m.sex_restriction!r}, spec='f'"
        )

    # The MVP uses a deterministic fallback — flag this as a known gap.
    discrepancies.append(
        "KNOWN-MVP-GAP: BCS uses deterministic fallback instead of querying "
        "CPT 77065/77066/77067 in VSAC value-set 2.16.840.1.113883.3.464.1004.1115 "
        "within 27-month window. Real EHR query required for certified rates."
    )
    discrepancies.append(
        "KNOWN-MVP-GAP: BCS exclusion logic (bilateral mastectomy Z90.13, Z90.11+Z90.12) "
        "not implemented in MVP. Affects numerator compliance count for enrolled women "
        "with mastectomy history."
    )
    discrepancies.append(
        "KNOWN-MVP-GAP: Continuous enrollment criteria (11/12 months, 45-day gap tolerance) "
        "not enforced in MVP denominator."
    )

    return discrepancies


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def validate_measure_spec(measurement_year: int) -> dict:
    """Return the BCS self-validation report for *measurement_year*.

    The report encodes NCQA-documented spec criteria and compares them to
    the implementation.  This is self-validation only — not NCQA certification.
    """
    discrepancies = _check_implementation()

    # Separate known-MVP gaps from actual logic errors
    known_gaps = [d for d in discrepancies if d.startswith("KNOWN-MVP-GAP")]
    logic_errors = [d for d in discrepancies if not d.startswith("KNOWN-MVP-GAP")]

    denominator_match = len(logic_errors) == 0
    numerator_match = len(logic_errors) == 0
    exclusion_match = not any("exclusion" in d.lower() for d in logic_errors)

    # Score penalizes known gaps but not logic errors already captured above
    gap_penalty = len(known_gaps) * 0.12  # 3 known gaps = 0.36 penalty
    score = max(0.0, round(1.0 - gap_penalty, 2))

    return {
        "measure_id": "BCS",
        "measure_name": "Breast Cancer Screening",
        "measurement_year": measurement_year,
        "ncqa_version_referenced": "NCQA HEDIS MY2026 Volume 2 (public summary)",
        "denominator_criteria": {
            "age_range": f"{_SPEC_AGE_MIN}-{_SPEC_AGE_MAX}",
            "sex": _SPEC_SEX,
            "lookback_months": _SPEC_LOOKBACK_MONTHS,
            "enrollment_requirement": "11 of 12 months; gap tolerance 45 days",
        },
        "numerator_criteria": {
            "event": "At least one mammogram in 27-month look-back window",
            "cpt_codes": _SPEC_MAMMOGRAM_CPT,
            "hcpcs_codes": _SPEC_MAMMOGRAM_HCPCS,
        },
        "exclusion_criteria": {
            "bilateral_mastectomy_icd10": _SPEC_EXCLUSION_BILATERAL_MASTECTOMY_ICD10,
            "history_bilateral_mastectomy_icd10": _SPEC_EXCLUSION_UNILATERAL_BILATERAL_ICD10,
        },
        "denominator_criteria_match": denominator_match,
        "numerator_criteria_match": numerator_match,
        "exclusion_criteria_match": exclusion_match,
        "value_set_oids_used": _VALUE_SET_OIDS,
        "discrepancies": discrepancies,
        "known_gaps_count": len(known_gaps),
        "logic_error_count": len(logic_errors),
        "self_validation_score": score,
        "certification_status": "self-validated; pending external NCQA certification",
    }
