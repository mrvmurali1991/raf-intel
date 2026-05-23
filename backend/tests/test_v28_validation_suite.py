"""
V28 Validation Suite — 50 Known-Correct Mappings

Each test case represents a real-world clinical scenario verified against
hccinfhir, which is treated as the authoritative source for CMS V28 mappings.

All expected HCC values were confirmed by querying dx_to_cc_default directly
before authoring this file. Do not "fix" failures by changing hccinfhir —
update the expected value in this file to match hccinfhir output.

Test case format: (icd10_code, expected_hcc_or_None, clinical_description)
"""
import pytest
from hccinfhir.defaults import dx_to_cc_default

MODEL = "CMS-HCC Model V28"

# fmt: off
V28_VALIDATION_CASES = [
    # ------------------------------------------------------------------
    # Diabetes — HCC37 (with complications) / HCC38 (hyperglycemia / insulin)
    # ------------------------------------------------------------------
    ("E1122",   "37",  "DM2 with diabetic CKD stage 1-2"),
    ("E1140",   "37",  "DM2 with diabetic neuropathy unspecified"),
    ("E1142",   "37",  "DM2 with diabetic polyneuropathy"),
    ("E1151",   "37",  "DM2 with peripheral angiopathy without gangrene"),
    ("E11311",  "298", "DM2 with mild nonproliferative retinopathy + macular edema"),
    ("E1165",   "38",  "DM2 with hyperglycemia"),
    ("Z794",    "38",  "Long-term insulin use — maps to HCC38 in V28"),

    # ------------------------------------------------------------------
    # Heart Failure — HCC226 (chronic) / HCC224 (acute-on-chronic)
    # ------------------------------------------------------------------
    ("I5020",   "226", "Unspecified systolic heart failure"),
    ("I5022",   "226", "Chronic systolic heart failure"),
    ("I5023",   "224", "Acute on chronic systolic HF — maps HCC224, not 226"),
    ("I5032",   "226", "Chronic diastolic heart failure"),
    ("I110",    "226", "Hypertensive heart disease with heart failure"),

    # ------------------------------------------------------------------
    # Chronic Kidney Disease — HCC326 (stage 5/ESRD) / HCC327 (stage 4) / HCC328 (stage 3b)
    # ------------------------------------------------------------------
    ("N184",    "327", "CKD Stage 4"),
    ("N185",    "326", "CKD Stage 5"),
    ("N1832",   "328", "CKD Stage 3b"),
    ("N186",    "326", "ESRD on dialysis"),

    # ------------------------------------------------------------------
    # COPD — HCC280
    # ------------------------------------------------------------------
    ("J449",    "280", "COPD unspecified"),
    ("J441",    "280", "COPD with acute exacerbation"),
    ("J440",    "280", "COPD with lower respiratory infection"),

    # ------------------------------------------------------------------
    # Dementia — HCC127
    # Note: F0151 (vascular dementia with behavioral disturbance) does NOT
    # map in V28; use F0150 or G309/G3183 for confirmed HCC127 codes.
    # ------------------------------------------------------------------
    ("F0150",   "127", "Vascular dementia, uncomplicated"),
    ("G309",    "127", "Alzheimer disease, unspecified"),
    ("G3183",   "127", "Senile dementia with psychosis"),

    # ------------------------------------------------------------------
    # Stroke Sequelae — HCC253
    # ------------------------------------------------------------------
    ("I69351",  "253", "Hemiplegia following cerebral infarction, right dominant"),
    ("I69352",  "253", "Hemiplegia following cerebral infarction, left dominant"),

    # ------------------------------------------------------------------
    # Atrial Fibrillation / Arrhythmia — HCC238
    # Note: I4891 (AFib unspecified) and I480 map; I4801 does NOT in V28.
    # ------------------------------------------------------------------
    ("I4891",   "238", "Atrial fibrillation, unspecified"),
    ("I480",    "238", "Paroxysmal atrial fibrillation (I480) — confirmed in V28"),

    # ------------------------------------------------------------------
    # Cancer — HCC20 (lung/thorax), HCC22 (digestive tract), HCC23 (hematologic)
    # V28 split cancer into finer categories; colon maps to HCC22, not HCC12.
    # ------------------------------------------------------------------
    ("C3490",   "20",  "Malignant neoplasm of bronchus and lung, unspecified — HCC20"),
    ("C3410",   "20",  "Malignant neoplasm of upper lobe, bronchus/lung — HCC20"),
    ("C189",    "22",  "Malignant neoplasm of colon, unspecified — HCC22 (not 12)"),
    ("C20",     "22",  "Malignant neoplasm of rectum — HCC22"),
    ("D473",    "23",  "Essential (hemorrhagic) thrombocythemia — HCC23"),

    # ------------------------------------------------------------------
    # HIV — HCC1
    # ------------------------------------------------------------------
    ("B20",     "1",   "HIV disease"),

    # ------------------------------------------------------------------
    # Schizophrenia / Psychosis — HCC151
    # ------------------------------------------------------------------
    ("F2089",   "151", "Other schizophrenia"),

    # ------------------------------------------------------------------
    # Multiple Sclerosis — HCC198
    # ------------------------------------------------------------------
    ("G35",     "198", "Multiple sclerosis"),

    # ------------------------------------------------------------------
    # Morbid Obesity — HCC48
    # ------------------------------------------------------------------
    ("E6601",   "48",  "Morbid (severe) obesity due to excess calories"),

    # ------------------------------------------------------------------
    # Respiratory Failure — HCC213
    # ------------------------------------------------------------------
    ("J9611",   "213", "Chronic respiratory failure with hypoxia"),

    # ------------------------------------------------------------------
    # Anemia — HCC109
    # ------------------------------------------------------------------
    ("D594",    "109", "Other nonautoimmune hemolytic anemias"),

    # ------------------------------------------------------------------
    # Septicemia / Serious Infection — HCC2
    # ------------------------------------------------------------------
    ("A419",    "2",   "Sepsis, unspecified organism"),

    # ------------------------------------------------------------------
    # Kidney Transplant Status — HCC77
    # ------------------------------------------------------------------
    ("Z9482",   "77",  "Kidney transplant status"),

    # ------------------------------------------------------------------
    # Pressure Ulcer — HCC381
    # ------------------------------------------------------------------
    ("L89213",  "381", "Pressure ulcer of right hip, stage 3"),

    # ------------------------------------------------------------------
    # Hip Fracture — HCC402
    # ------------------------------------------------------------------
    ("S72001A", "402", "Fracture of unspecified part of femur, initial encounter"),

    # ------------------------------------------------------------------
    # Peripheral Artery Disease with Ulceration — HCC383
    # ------------------------------------------------------------------
    ("I7025",   "383", "Atherosclerosis of native arteries of extremities with ulceration"),

    # ------------------------------------------------------------------
    # Coronary Artery Disease with Unstable Angina — HCC229
    # ------------------------------------------------------------------
    ("I25110",  "229", "Atherosclerotic heart disease of native coronary artery with unstable angina"),

    # ------------------------------------------------------------------
    # NOT in V28 — codes that must return None
    # These are common codes that do NOT generate an HCC in the V28 model.
    # ------------------------------------------------------------------
    ("I10",     None,  "Essential hypertension — not risk-adjusting in V28"),
    ("E785",    None,  "Pure hypercholesterolemia — not risk-adjusting in V28"),
    ("F330",    None,  "Major depressive disorder, recurrent, mild — dropped in V28"),
    ("M170",    None,  "Bilateral primary osteoarthritis of knee — not in V28"),
    ("K210",    None,  "GERD with esophagitis — not in V28"),
    ("F0151",   None,  "Vascular dementia with behavioral disturbance — does NOT map in V28"),
    ("I4801",   None,  "Paroxysmal AFib via I4801 subcode — does NOT map in V28"),
]
# fmt: on

# Sanity check: exactly 50 cases
assert len(V28_VALIDATION_CASES) == 50, (
    f"Expected 50 test cases, found {len(V28_VALIDATION_CASES)}"
)


class TestV28ValidationSuite:
    """
    Validates that hccinfhir correctly maps known ICD-10 codes to their
    V28 HCC categories (or confirms absence of a mapping).

    hccinfhir is authoritative. If a test fails, correct the expected
    value in this file — never patch hccinfhir to match stale expectations.
    """

    @pytest.mark.parametrize("icd, expected_hcc, description", V28_VALIDATION_CASES)
    def test_v28_mapping(self, icd: str, expected_hcc, description: str) -> None:
        result = dx_to_cc_default.get((icd, MODEL))

        if expected_hcc is None:
            assert result is None, (
                f"[{icd}] {description}\n"
                f"  Expected: no HCC mapping in V28\n"
                f"  Actual:   {result}"
            )
        else:
            assert result is not None, (
                f"[{icd}] {description}\n"
                f"  Expected: HCC{expected_hcc}\n"
                f"  Actual:   None (code not found in V28 mapping)"
            )
            assert expected_hcc in result, (
                f"[{icd}] {description}\n"
                f"  Expected HCC{expected_hcc} to be present in mapping\n"
                f"  Actual:   {result}"
            )
