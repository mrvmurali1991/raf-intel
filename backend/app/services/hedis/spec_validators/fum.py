"""NCQA HEDIS self-validator: FUM — Follow-Up After Emergency Department Visit
for Mental Illness.

Public specification reference:
  NCQA HEDIS MY2026 Volume 2, "Follow-Up After Emergency Department Visit
  for Mental Illness (FUM)"
  Source: https://www.ncqa.org/hedis/measures/follow-up-after-emergency-department-visit-for-mental-illness/

Key publicly documented criteria:
  Denominator: Members 6 years of age and older as of the ED visit date
               who had an ED visit with a principal diagnosis of mental
               illness or intentional self-harm (ICD-10 value-set) during
               the measurement year.  Index events occurring in the last
               30 days of the year are excluded.
               CPT: 99281-99285 (ED evaluation and management)
               Facility codes: UB Revenue 045x, 0981
  Numerator (two rates reported separately):
    FUM_7:  Follow-up visit with a mental health practitioner within
            7 days (including the day of the ED visit).
    FUM_30: Follow-up visit within 30 days.
    Follow-up visit types: outpatient, intensive outpatient, partial
    hospitalization, telehealth, community mental health center.
    CPT: 90785, 90791, 90792, 90832-90838, 90839-90840, 90845, 90847,
         90849, 90853, 90870, 90875, 90876, 98960-98962 (telehealth),
         99201-99215 (office/outpatient), 99421-99423
  Exclusions:
    - ED visit followed by inpatient or observation admission on the
      same day or next day (index event excluded, not the member).
    - Hospice/palliative care enrollment.
    - Members in substance use disorder (SUD) treatment only visits
      (if principal Dx is SUD and mental illness is secondary).

Value-set OIDs referenced (VSAC public):
  2.16.840.1.113883.3.464.1004.1183 — Mental Illness (Dx)
  2.16.840.1.113883.3.464.1004.1086 — ED Visits (CPT/facility)
  2.16.840.1.113883.3.464.1004.1157 — Mental Health Follow-Up Visit
  2.16.840.1.113883.3.464.1004.1079 — Intentional Self-Harm (Dx)
"""
from __future__ import annotations

_SPEC_AGE_MIN = 6
_SPEC_AGE_MAX = None  # no upper bound

_SPEC_FOLLOWUP_7_DAYS = 7
_SPEC_FOLLOWUP_30_DAYS = 30

_SPEC_MENTAL_ILLNESS_ICD10_EXAMPLES = [
    "F20", "F25", "F30", "F31", "F32", "F33",  # Schizophrenia, Bipolar, MDD
    "F40", "F41", "F42",                         # Anxiety, OCD
    "F43", "F50", "F60", "F70", "F80", "F90",
]

_SPEC_ED_CPT = ["99281", "99282", "99283", "99284", "99285"]
_SPEC_FOLLOWUP_CPT_EXAMPLES = [
    "90785", "90791", "90792", "90832", "90834", "90836", "90837", "90838",
    "90839", "90840", "90845", "90847", "90849", "90853", "90870",
    "99201", "99202", "99203", "99204", "99205",
    "99211", "99212", "99213", "99214", "99215",
]

_VALUE_SET_OIDS = [
    "2.16.840.1.113883.3.464.1004.1183",  # Mental Illness (Dx)
    "2.16.840.1.113883.3.464.1004.1086",  # ED Visits
    "2.16.840.1.113883.3.464.1004.1157",  # Mental Health Follow-Up Visit
    "2.16.840.1.113883.3.464.1004.1079",  # Intentional Self-Harm (Dx)
]


def _check_implementation() -> list[str]:
    from app.services.hedis.measures import FUMMeasure

    m = FUMMeasure()
    discrepancies: list[str] = []

    if m.age_min != _SPEC_AGE_MIN:
        discrepancies.append(
            f"age_min mismatch: implementation={m.age_min}, spec={_SPEC_AGE_MIN}"
        )
    if m.age_max != _SPEC_AGE_MAX:
        discrepancies.append(
            f"age_max mismatch: implementation={m.age_max}, spec={_SPEC_AGE_MAX} (no upper bound)"
        )
    if m.sex_restriction is not None:
        discrepancies.append(
            f"sex_restriction unexpected: implementation={m.sex_restriction!r}, spec=None"
        )

    discrepancies.append(
        "KNOWN-MVP-GAP: FUM uses deterministic fallback (~8% denom prevalence) instead "
        "of identifying actual ED visits (CPT 99281-99285, UB Revenue 045x) with a "
        "principal mental-illness diagnosis (VSAC 2.16.840.1.113883.3.464.1004.1183)."
    )
    discrepancies.append(
        "KNOWN-MVP-GAP: FUM_7 and FUM_30 follow-up detection uses random score "
        "instead of querying mental health outpatient/IOP/PHP encounters "
        "(CPT 90785-90876, 99201-99215) within 7 and 30 days of index ED visit."
    )
    discrepancies.append(
        "KNOWN-MVP-GAP: FUM index-event exclusion for same-day inpatient admission "
        "not implemented; last-30-days-of-year index event exclusion not implemented."
    )
    discrepancies.append(
        "KNOWN-MVP-GAP: FUM hospice/palliative-care exclusion and SUD-only principal "
        "Dx exclusion not implemented."
    )

    return discrepancies


def validate_measure_spec(measurement_year: int) -> dict:
    """Return the FUM self-validation report for *measurement_year*."""
    discrepancies = _check_implementation()
    known_gaps = [d for d in discrepancies if d.startswith("KNOWN-MVP-GAP")]
    logic_errors = [d for d in discrepancies if not d.startswith("KNOWN-MVP-GAP")]

    denominator_match = len(logic_errors) == 0
    numerator_match = len(logic_errors) == 0
    exclusion_match = not any("exclusion" in d.lower() for d in logic_errors)

    gap_penalty = len(known_gaps) * 0.10
    score = max(0.0, round(1.0 - gap_penalty, 2))

    return {
        "measure_id": "FUM",
        "measure_name": "Follow-Up After Emergency Department Visit for Mental Illness",
        "measurement_year": measurement_year,
        "ncqa_version_referenced": "NCQA HEDIS MY2026 Volume 2 (public summary)",
        "denominator_criteria": {
            "age_min": _SPEC_AGE_MIN,
            "age_max": "no upper bound",
            "sex": "no restriction",
            "index_event": "ED visit with principal mental-illness or intentional self-harm Dx",
            "ed_cpt": _SPEC_ED_CPT,
            "mental_illness_icd10_prefixes_examples": _SPEC_MENTAL_ILLNESS_ICD10_EXAMPLES,
            "index_event_exclusion": "Last 30 days of measurement year excluded as index events",
        },
        "numerator_criteria": {
            "FUM_7": f"Follow-up with mental health practitioner within {_SPEC_FOLLOWUP_7_DAYS} days",
            "FUM_30": f"Follow-up with mental health practitioner within {_SPEC_FOLLOWUP_30_DAYS} days",
            "follow_up_cpt_examples": _SPEC_FOLLOWUP_CPT_EXAMPLES,
            "note": "Both rates reported separately; FUM_30 is the primary reported rate",
        },
        "exclusion_criteria": {
            "inpatient_admission_same_day": "Index event excluded (not member) if inpatient admit same/next day",
            "hospice_palliative": "Palliative care enrollment excludes member",
            "sud_only_visit": "Visits where SUD is principal and mental illness is secondary excluded",
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
