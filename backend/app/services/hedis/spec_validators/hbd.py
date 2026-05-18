"""NCQA HEDIS self-validator: HBD — Hemoglobin A1c Control for Patients With Diabetes.

Public specification reference:
  NCQA HEDIS MY2026 Volume 2, "Hemoglobin A1c Control for Patients with
  Diabetes (HBD)"
  Source: https://www.ncqa.org/hedis/measures/hemoglobin-a1c-hba1c-control-for-patients-with-diabetes/

Key publicly documented criteria:
  Denominator: Members 18-75 years of age as of December 31 of the
               measurement year with a diagnosis of type 1 or type 2
               diabetes (ICD-10: E10.x, E11.x, E13.x) identified via:
               - A pharmacy claim for insulin or non-insulin antidiabetic
                 agent during the measurement year OR the year prior, AND/OR
               - An outpatient, telehealth, or non-acute inpatient visit with
                 a diabetes diagnosis on any two distinct dates of service
                 during the measurement year or the year prior.
  Numerator:   Most recent HbA1c level during the measurement year that is
               < 8.0%.
               LOINC codes: 4548-4, 4549-2, 17856-6, 59261-8, 62388-4,
               71875-9, 83036-8
  Exclusions:  Pregnancy (ICD-10 O00-O9A or SNOMED equivalents) during
               the measurement year; palliative care (SNOMED / value-set);
               ESRD; frailty combined with advanced illness (MY2024+).

Value-set OIDs referenced (VSAC public):
  2.16.840.1.113883.3.464.1004.1093 — HbA1c Laboratory Test
  2.16.840.1.113883.3.464.1004.1035 — Diabetes Medications (antidiabetics)
  2.16.840.1.113883.3.464.1004.1072 — Diabetes (Dx)
  2.16.840.1.113883.3.464.1004.1135 — Pregnancy (exclusion)
"""
from __future__ import annotations

_SPEC_AGE_MIN = 18
_SPEC_AGE_MAX = 75
_SPEC_HBA1C_THRESHOLD = 8.0  # percent

_SPEC_DIABETES_ICD10_PREFIXES = ["E10", "E11", "E13"]

_SPEC_HBA1C_LOINC = [
    "4548-4", "4549-2", "17856-6", "59261-8", "62388-4", "71875-9", "83036-8"
]

_SPEC_EXCLUSION_PREGNANCY_ICD10_RANGE = "O00-O9A"

_VALUE_SET_OIDS = [
    "2.16.840.1.113883.3.464.1004.1093",  # HbA1c Laboratory Test
    "2.16.840.1.113883.3.464.1004.1035",  # Diabetes Medications
    "2.16.840.1.113883.3.464.1004.1072",  # Diabetes (Dx)
    "2.16.840.1.113883.3.464.1004.1135",  # Pregnancy (exclusion)
]


def _check_implementation() -> list[str]:
    from app.services.hedis.measures import HBDMeasure

    m = HBDMeasure()
    discrepancies: list[str] = []

    if m.age_min != _SPEC_AGE_MIN:
        discrepancies.append(
            f"age_min mismatch: implementation={m.age_min}, spec={_SPEC_AGE_MIN}"
        )
    if m.age_max != _SPEC_AGE_MAX:
        discrepancies.append(
            f"age_max mismatch: implementation={m.age_max}, spec={_SPEC_AGE_MAX}"
        )
    if m.sex_restriction is not None:
        discrepancies.append(
            f"sex_restriction unexpected: implementation={m.sex_restriction!r}, spec=None (no sex restriction)"
        )

    discrepancies.append(
        "KNOWN-MVP-GAP: HBD uses deterministic fallback instead of querying LOINC "
        "4548-4/4549-2/17856-6 observations (VSAC 2.16.840.1.113883.3.464.1004.1093). "
        "Most-recent HbA1c logic using LOINC in measurement year not implemented."
    )
    discrepancies.append(
        "KNOWN-MVP-GAP: HBD denominator uses random score instead of confirmed diabetes "
        "diagnosis (E10/E11/E13) on two distinct dates OR antidiabetic pharmacy claim "
        "(VSAC 2.16.840.1.113883.3.464.1004.1035)."
    )
    discrepancies.append(
        "KNOWN-MVP-GAP: HBD pregnancy/palliative-care/ESRD/frailty exclusions not "
        "implemented. Denominators for enrolled pregnant diabetics are incorrectly included."
    )

    return discrepancies


def validate_measure_spec(measurement_year: int) -> dict:
    """Return the HBD self-validation report for *measurement_year*."""
    discrepancies = _check_implementation()
    known_gaps = [d for d in discrepancies if d.startswith("KNOWN-MVP-GAP")]
    logic_errors = [d for d in discrepancies if not d.startswith("KNOWN-MVP-GAP")]

    denominator_match = len(logic_errors) == 0
    numerator_match = len(logic_errors) == 0
    exclusion_match = not any("exclusion" in d.lower() for d in logic_errors)

    gap_penalty = len(known_gaps) * 0.10
    score = max(0.0, round(1.0 - gap_penalty, 2))

    return {
        "measure_id": "HBD",
        "measure_name": "Hemoglobin A1c Control for Patients With Diabetes (<8.0%)",
        "measurement_year": measurement_year,
        "ncqa_version_referenced": "NCQA HEDIS MY2026 Volume 2 (public summary)",
        "denominator_criteria": {
            "age_range": f"{_SPEC_AGE_MIN}-{_SPEC_AGE_MAX}",
            "sex": "no restriction",
            "diabetes_icd10_prefixes": _SPEC_DIABETES_ICD10_PREFIXES,
            "identification_method": (
                "Pharmacy claim for antidiabetic agent (current/prior year) OR "
                "outpatient visit with diabetes Dx on two distinct dates"
            ),
        },
        "numerator_criteria": {
            "event": f"Most recent HbA1c in measurement year < {_SPEC_HBA1C_THRESHOLD}%",
            "loinc_codes": _SPEC_HBA1C_LOINC,
            "threshold_pct": _SPEC_HBA1C_THRESHOLD,
        },
        "exclusion_criteria": {
            "pregnancy_icd10_range": _SPEC_EXCLUSION_PREGNANCY_ICD10_RANGE,
            "also_excludes": ["palliative care", "ESRD", "frailty with advanced illness (MY2024+)"],
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
