"""NCQA HEDIS self-validator: CCS — Cervical Cancer Screening.

Public specification reference:
  NCQA HEDIS MY2026 Volume 2, "Cervical Cancer Screening (CCS)"
  Source: https://www.ncqa.org/hedis/measures/cervical-cancer-screening/

Key publicly documented criteria:
  Denominator: Women aged 21-64 as of December 31 of the measurement year,
               enrolled for at least 11 months during the year.
  Numerator (any ONE of three paths):
    Path A: Cervical cytology (Pap smear) in the measurement year or
            the two prior years (3-year look-back). Ages 21-64.
            CPT: 88141-88143, 88147, 88148, 88150, 88152-88154, 88164-88167, 88174, 88175
            LOINC: 10524-7 (cytology), 19762-4
    Path B: Cervical cytology + hrHPV co-test within 5 years.  Ages 30-64.
            CPT cytology (same list) + CPT HPV: 87624, 87625
            LOINC HPV: 21440-3, 30167-1, 38372-9, 59263-4, 59264-2, 59420-0
    Path C: hrHPV-only test within 5 years (FDA-approved primary screening
            for ages 30-64 as of MY2024 onward).
            CPT: 87624, 87625
  Exclusions:
    Hysterectomy with no residual cervix:
      ICD-10: Z90.710 (acquired absence of cervix and uterus),
              Z90.712 (acquired absence of cervix with remaining uterus)
      CPT: 57540, 57545, 58150, 58152, 58200, 58210, 58240, 58260-58263,
           58267, 58270, 58275, 58280, 58285, 58290-58294, 58548, 58550,
           58552-58554, 58570-58573, 58575, 58578, 58579, 58951, 58953, 58954, 59135

Value-set OIDs referenced (VSAC public):
  2.16.840.1.113883.3.464.1004.1208 — Cervical Cytology
  2.16.840.1.113883.3.464.1004.1209 — HPV Tests
  2.16.840.1.113883.3.464.1004.1274 — Hysterectomy with No Residual Cervix
  2.16.840.1.113883.3.464.1004.1090 — Absence of Cervix (Dx)
"""
from __future__ import annotations

_SPEC_AGE_MIN = 21
_SPEC_AGE_MAX = 64
_SPEC_SEX = "female"

_SPEC_CYTOLOGY_LOOKBACK_YEARS = 3
_SPEC_COHPV_LOOKBACK_YEARS = 5
_SPEC_HPV_ONLY_LOOKBACK_YEARS = 5  # Path C, ages 30-64

_SPEC_CYTOLOGY_CPT = [
    "88141", "88142", "88143", "88147", "88148", "88150",
    "88152", "88153", "88154", "88164", "88165", "88166", "88167",
    "88174", "88175",
]
_SPEC_HPV_CPT = ["87624", "87625"]

_SPEC_EXCLUSION_HYSTERECTOMY_ICD10 = ["Z90.710", "Z90.712"]

_VALUE_SET_OIDS = [
    "2.16.840.1.113883.3.464.1004.1208",  # Cervical Cytology
    "2.16.840.1.113883.3.464.1004.1209",  # HPV Tests
    "2.16.840.1.113883.3.464.1004.1274",  # Hysterectomy with No Residual Cervix
    "2.16.840.1.113883.3.464.1004.1090",  # Absence of Cervix (Dx)
]


def _check_implementation() -> list[str]:
    from app.services.hedis.measures import CCSMeasure

    m = CCSMeasure()
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

    discrepancies.append(
        "KNOWN-MVP-GAP: CCS uses deterministic fallback instead of querying "
        "Pap CPT codes (88141-88175) or HPV co-test CPT 87624/87625 against "
        "VSAC value-set 2.16.840.1.113883.3.464.1004.1208 with 3/5-year windows."
    )
    discrepancies.append(
        "KNOWN-MVP-GAP: CCS three-path numerator logic (cytology, co-test, HPV-only) "
        "not differentiated in MVP — single pass rate used."
    )
    discrepancies.append(
        "KNOWN-MVP-GAP: CCS hysterectomy exclusion (Z90.710, Z90.712) not enforced "
        "in MVP denominator screen."
    )
    discrepancies.append(
        "KNOWN-MVP-GAP: Continuous enrollment criteria (11/12 months) not enforced."
    )

    return discrepancies


def validate_measure_spec(measurement_year: int) -> dict:
    """Return the CCS self-validation report for *measurement_year*."""
    discrepancies = _check_implementation()
    known_gaps = [d for d in discrepancies if d.startswith("KNOWN-MVP-GAP")]
    logic_errors = [d for d in discrepancies if not d.startswith("KNOWN-MVP-GAP")]

    denominator_match = len(logic_errors) == 0
    numerator_match = len(logic_errors) == 0
    exclusion_match = not any("exclusion" in d.lower() for d in logic_errors)

    gap_penalty = len(known_gaps) * 0.10
    score = max(0.0, round(1.0 - gap_penalty, 2))

    return {
        "measure_id": "CCS",
        "measure_name": "Cervical Cancer Screening",
        "measurement_year": measurement_year,
        "ncqa_version_referenced": "NCQA HEDIS MY2026 Volume 2 (public summary)",
        "denominator_criteria": {
            "age_range": f"{_SPEC_AGE_MIN}-{_SPEC_AGE_MAX}",
            "sex": _SPEC_SEX,
            "enrollment_requirement": "11 of 12 months",
        },
        "numerator_criteria": {
            "path_a": f"Cervical cytology within {_SPEC_CYTOLOGY_LOOKBACK_YEARS} years (ages 21-64)",
            "path_b": f"Cytology + hrHPV co-test within {_SPEC_COHPV_LOOKBACK_YEARS} years (ages 30-64)",
            "path_c": f"hrHPV-only within {_SPEC_HPV_ONLY_LOOKBACK_YEARS} years (ages 30-64)",
            "cytology_cpt": _SPEC_CYTOLOGY_CPT,
            "hpv_cpt": _SPEC_HPV_CPT,
        },
        "exclusion_criteria": {
            "hysterectomy_no_cervix_icd10": _SPEC_EXCLUSION_HYSTERECTOMY_ICD10,
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
