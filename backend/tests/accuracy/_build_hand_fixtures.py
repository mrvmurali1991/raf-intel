"""Generate the 20 hand-crafted FHIR bundles used as the fallback corpus.

Run once to populate ``fixtures/synthea_bundles/hand/``. The output is
committed to the repo so CI doesn't depend on this script.

Each bundle is intentionally minimal — just what
``bundle_to_score_input`` needs: a ``Patient``, one ``Encounter``, and
one ``Condition`` per ICD-10 code, all ICD codes tagged with the
``http://hl7.org/fhir/sid/icd-10-cm`` system.
"""
from __future__ import annotations

import json
from pathlib import Path

HAND_DIR = Path(__file__).resolve().parent / "fixtures" / "synthea_bundles" / "hand"

# --------------------------------------------------------------------------
# Cases — chosen so we exercise:
#   - hierarchy trumping (diabetes w/ complications vs without)
#   - interaction terms (DIABETES + CHF etc.)
#   - high-weight cancer HCCs
#   - ESRD-bordering CKD cases
#   - lone-HCC sanity checks
#   - a female patient (breast cancer) and elderly male (prostate)
# --------------------------------------------------------------------------
CASES: list[dict] = [
    {
        "id": "raf-001-diabetes-neuropathy",
        "birthDate": "1948-03-15",
        "gender": "male",
        "icd10": ["E1142", "E1165"],  # Diabetic neuropathy + DM w/ hyperglycemia
    },
    {
        "id": "raf-002-chf-cardiomyopathy",
        "birthDate": "1945-11-02",
        "gender": "male",
        "icd10": ["I5022", "I420"],   # Chronic systolic HF + Dilated cardiomyopathy
    },
    {
        "id": "raf-003-ckd-esrd",
        "birthDate": "1940-07-22",
        "gender": "female",
        "icd10": ["N186", "N184"],    # ESRD + CKD Stage 4 (ESRD trumps)
    },
    {
        "id": "raf-004-cancer-metastasis",
        "birthDate": "1942-02-10",
        "gender": "female",
        "icd10": ["C61", "C787"],     # Prostate cancer + secondary liver mets
    },
    {
        "id": "raf-005-copd-alone",
        "birthDate": "1950-09-30",
        "gender": "male",
        "icd10": ["J441"],             # COPD exacerbation
    },
    {
        "id": "raf-006-diabetes-no-complication",
        "birthDate": "1952-04-01",
        "gender": "female",
        "icd10": ["E119"],             # DM w/o complications
    },
    {
        "id": "raf-007-diabetes-both-versions",
        "birthDate": "1948-12-05",
        "gender": "male",
        "icd10": ["E1122", "E119"],   # w/ chronic complications + w/o — HCC37 trumps
    },
    {
        "id": "raf-008-morbid-obesity",
        "birthDate": "1955-06-12",
        "gender": "female",
        "icd10": ["E6601"],
    },
    {
        "id": "raf-009-breast-cancer",
        "birthDate": "1947-08-21",
        "gender": "female",
        "icd10": ["C50911"],
    },
    {
        "id": "raf-010-arrhythmia",
        "birthDate": "1944-05-17",
        "gender": "male",
        "icd10": ["I4891"],            # Specified heart arrhythmia
    },
    {
        "id": "raf-011-respiratory-failure",
        "birthDate": "1939-01-30",
        "gender": "male",
        "icd10": ["J9611"],
    },
    {
        "id": "raf-012-dementia-alzheimer",
        "birthDate": "1936-10-03",
        "gender": "female",
        "icd10": ["G309", "F0150"],
    },
    {
        "id": "raf-013-chf-plus-diabetes",
        "birthDate": "1946-07-14",
        "gender": "male",
        "icd10": ["E1122", "I5022"],  # DIABETES_CHF interaction in V24
    },
    {
        "id": "raf-014-stroke-sequela",
        "birthDate": "1943-11-20",
        "gender": "female",
        "icd10": ["I6935"],            # no HCC in V28 — demographics only
    },
    {
        "id": "raf-015-ckd3b-alone",
        "birthDate": "1949-02-02",
        "gender": "female",
        "icd10": ["N1832"],
    },
    {
        "id": "raf-016-ckd4-alone",
        "birthDate": "1951-08-08",
        "gender": "male",
        "icd10": ["N184"],
    },
    {
        "id": "raf-017-pressure-ulcer",
        "birthDate": "1938-04-04",
        "gender": "female",
        "icd10": ["L89154"],           # Pressure ulcer sacral region, stage 4
    },
    {
        "id": "raf-018-amputation",
        "birthDate": "1941-12-24",
        "gender": "male",
        "icd10": ["Z8911"],            # Acquired absence of right lower limb BK
    },
    {
        "id": "raf-019-multi-cancer-chf-ckd",
        "birthDate": "1937-03-03",
        "gender": "male",
        "icd10": ["C61", "I5022", "N184", "E1122"],
    },
    {
        "id": "raf-020-healthy-control",
        "birthDate": "1953-05-05",
        "gender": "female",
        "icd10": ["Z0000"],            # General adult medical exam — no HCC
    },
]


def _bundle(case: dict) -> dict:
    pid = case["id"]
    entries: list[dict] = [
        {
            "fullUrl": f"urn:uuid:{pid}",
            "resource": {
                "resourceType": "Patient",
                "id": pid,
                "birthDate": case["birthDate"],
                "gender": case["gender"],
            },
        },
        {
            "fullUrl": f"urn:uuid:{pid}-enc-1",
            "resource": {
                "resourceType": "Encounter",
                "id": f"{pid}-enc-1",
                "status": "finished",
                "class": {
                    "system": "http://terminology.hl7.org/CodeSystem/v3-ActCode",
                    "code": "AMB",
                    "display": "ambulatory",
                },
                "subject": {"reference": f"Patient/{pid}"},
                "period": {"start": "2024-06-15T10:00:00Z", "end": "2024-06-15T10:30:00Z"},
            },
        },
    ]
    for i, icd in enumerate(case["icd10"], 1):
        entries.append(
            {
                "fullUrl": f"urn:uuid:{pid}-cond-{i}",
                "resource": {
                    "resourceType": "Condition",
                    "id": f"{pid}-cond-{i}",
                    "clinicalStatus": {
                        "coding": [
                            {
                                "system": "http://terminology.hl7.org/CodeSystem/condition-clinical",
                                "code": "active",
                            }
                        ]
                    },
                    "verificationStatus": {
                        "coding": [
                            {
                                "system": "http://terminology.hl7.org/CodeSystem/condition-ver-status",
                                "code": "confirmed",
                            }
                        ]
                    },
                    "code": {
                        "coding": [
                            {
                                "system": "http://hl7.org/fhir/sid/icd-10-cm",
                                "code": icd,
                            }
                        ]
                    },
                    "subject": {"reference": f"Patient/{pid}"},
                    "encounter": {"reference": f"Encounter/{pid}-enc-1"},
                    "recordedDate": "2024-06-15",
                },
            }
        )
    return {"resourceType": "Bundle", "type": "collection", "entry": entries}


def main() -> None:
    HAND_DIR.mkdir(parents=True, exist_ok=True)
    for case in CASES:
        out = HAND_DIR / f"{case['id']}.json"
        out.write_text(json.dumps(_bundle(case), indent=2))
    print(f"Wrote {len(CASES)} bundles to {HAND_DIR}")


if __name__ == "__main__":
    main()
