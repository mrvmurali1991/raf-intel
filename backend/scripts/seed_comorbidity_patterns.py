#!/usr/bin/env python3
"""
seed_comorbidity_patterns.py
============================

Seeds curated rules into ``kg_comorbidity_patterns``.

Every pattern carries a ``source`` (and most have a ``source_url``) attributing
the rule to a primary clinical/coding reference:

* CMS V28 final HCC clinical specs — 2026 Final Announcement
  https://www.cms.gov/files/document/2026-announcement-for-medicare-advantage.pdf
* CMS V28 ICD-10 → HCC crosswalk (Risk Adjustment download page)
  https://www.cms.gov/medicare/payment/medicare-advantage-rates-statistics/risk-adjustment
* AHA Coding Clinic for ICD-10-CM/PCS — quarterly advice
  https://www.codingclinicadvisor.com/
* KDIGO 2024 CKD Guideline (eGFR staging cut-offs)
  https://kdigo.org/guidelines/ckd-evaluation-and-management/
* ACC/AHA/HFSA 2022 Heart Failure Guideline (NYHA & EF severity)
  https://www.ahajournals.org/doi/10.1161/CIR.0000000000001063

Run with:
    python -m backend.scripts.seed_comorbidity_patterns

The script is idempotent — patterns are upserted by ``pattern_name``.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from typing import Any

# When invoked as ``python -m backend.scripts.seed_comorbidity_patterns`` the
# repo root is on sys.path; when invoked directly we add it ourselves.
try:
    from app.db import raf_cursor  # type: ignore
except ImportError:
    import os
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
    from app.db import raf_cursor  # type: ignore

logger = logging.getLogger("seed_comorbidity_patterns")


# ---------------------------------------------------------------------------
# Citations (re-used across many patterns)
# ---------------------------------------------------------------------------

CMS_V28_SPEC      = "CMS-V28-clinical-spec"
CMS_V28_URL       = "https://www.cms.gov/files/document/2026-announcement-for-medicare-advantage.pdf"
CMS_V28_CROSSWALK = "CMS-V28-crosswalk"
CMS_V28_CW_URL    = "https://www.cms.gov/medicare/payment/medicare-advantage-rates-statistics/risk-adjustment"
AHA_2024Q3        = "AHA-CodingClinic-2024Q3"
AHA_2024Q3_URL    = "https://www.codingclinicadvisor.com/"
KDIGO_2024        = "KDIGO-2024-CKD-Guideline"
KDIGO_2024_URL    = "https://kdigo.org/guidelines/ckd-evaluation-and-management/"
AHA_HF_2022       = "ACC-AHA-HFSA-2022-HF-Guideline"
AHA_HF_2022_URL   = "https://www.ahajournals.org/doi/10.1161/CIR.0000000000001063"
ICD10_TABULAR     = "ICD-10-CM-2026-Tabular"
ICD10_URL         = "https://www.cms.gov/medicare/coding-billing/icd-10-codes"


# ---------------------------------------------------------------------------
# Pattern definitions
# Each entry: pattern_name, description, required_evidence, output_hcc,
# output_icd10, upgrades_from_hcc, confidence, source, source_url.
# ---------------------------------------------------------------------------

PATTERNS: list[dict[str, Any]] = []


def _add(
    pattern_name: str,
    description: str,
    required_evidence: dict,
    output_hcc: str,
    output_icd10: str | None = None,
    upgrades_from_hcc: str | None = None,
    confidence: float = 0.85,
    source: str = CMS_V28_SPEC,
    source_url: str | None = CMS_V28_URL,
) -> None:
    PATTERNS.append({
        "pattern_name": pattern_name,
        "description": description,
        "required_evidence": required_evidence,
        "output_hcc": output_hcc,
        "output_icd10": output_icd10,
        "upgrades_from_hcc": upgrades_from_hcc,
        "confidence": confidence,
        "source": source,
        "source_url": source_url,
    })


# ===========================================================================
# 1. DIABETES SEVERITY UPGRADES (HCC 19 → HCC 18, plus compound combos)
#    CMS V28 distinguishes:
#       HCC 17  Diabetes with Acute Complications
#       HCC 18  Diabetes with Chronic Complications
#       HCC 19  Diabetes without Complication
#    A diabetic with ANY chronic complication should map to HCC 18, not 19.
# ===========================================================================

# 1a. DM + diabetic retinopathy → HCC 18
_add(
    "dm_with_retinopathy_to_hcc18",
    "Type 2 DM (HCC 19) coded alongside diabetic retinopathy (H35.x or E11.31x-E11.35x) "
    "should be coded as 'with chronic complications' = HCC 18. The retinopathy itself "
    "represents end-organ damage from diabetes.",
    {"hccs": ["19"], "icds": ["E11", "H35"]},
    output_hcc="18",
    upgrades_from_hcc="19",
    confidence=0.92,
)
_add(
    "dm_with_retinopathy_e1135_only",
    "Direct ICD evidence: E11.35x (Type 2 DM with proliferative diabetic retinopathy) "
    "by itself unambiguously maps to HCC 18.",
    {"icds": ["E1135"]},
    output_hcc="18",
    output_icd10="E11.35",
    confidence=0.95,
)

# 1b. DM + diabetic nephropathy / CKD → HCC 18
_add(
    "dm_with_nephropathy_to_hcc18",
    "Type 2 DM + diabetic nephropathy (E11.21) or DM with CKD (E11.22) implies chronic "
    "complications = HCC 18.",
    {"hccs": ["19"], "icds": ["E11", "N18"]},
    output_hcc="18",
    upgrades_from_hcc="19",
    confidence=0.93,
)
_add(
    "dm_e1122_direct_to_hcc18",
    "E11.22 (Type 2 DM with diabetic CKD) is itself an HCC 18 leaf code — assert HCC 18 "
    "even if the patient's prior assignment was HCC 19.",
    {"icds": ["E1122"]},
    output_hcc="18",
    output_icd10="E11.22",
    upgrades_from_hcc="19",
    confidence=0.97,
)

# 1c. DM + neuropathy → HCC 18
_add(
    "dm_with_neuropathy_to_hcc18",
    "Type 2 DM + diabetic neuropathy (E11.4x — polyneuropathy/mononeuropathy/autonomic) "
    "is an HCC 18 chronic-complications combination.",
    {"hccs": ["19"], "icds": ["E114"]},
    output_hcc="18",
    upgrades_from_hcc="19",
    confidence=0.92,
)
_add(
    "dm_with_autonomic_neuropathy_e1143",
    "E11.43 (autonomic (poly)neuropathy) by itself is HCC 18.",
    {"icds": ["E1143"]},
    output_hcc="18",
    output_icd10="E11.43",
    confidence=0.95,
)

# 1d. DM + foot ulcer → HCC 18
_add(
    "dm_with_foot_ulcer_to_hcc18",
    "Type 2 DM + diabetic foot ulcer (E11.621) — chronic complication, HCC 18.",
    {"hccs": ["19"], "icds": ["E11621"]},
    output_hcc="18",
    upgrades_from_hcc="19",
    confidence=0.94,
)
_add(
    "dm_with_foot_ulcer_compound_l97",
    "DM + foot ulcer (E11.621) + skin-ulcer site code (L97.4-L97.5) → HCC 18 plus the "
    "ulcer-severity HCC. Coding Clinic 2024Q2 reaffirmed the 'use additional code' "
    "instruction.",
    {"icds": ["E11621", "L97"]},
    output_hcc="18",
    confidence=0.93,
    source=AHA_2024Q3,
    source_url=AHA_2024Q3_URL,
)

# 1e. DM + Charcot foot → HCC 18
_add(
    "dm_with_charcot_foot",
    "Type 2 DM + Charcot foot/osteoarthropathy (E11.610) → HCC 18.",
    {"icds": ["E11610"]},
    output_hcc="18",
    output_icd10="E11.610",
    upgrades_from_hcc="19",
    confidence=0.94,
)

# 1f. DM + morbid obesity (BMI>40) — compound
_add(
    "dm_chronic_compl_with_morbid_obesity",
    "Diabetic with chronic complications PLUS morbid obesity (E66.01) carries the "
    "interaction term in CMS V28. Codes: HCC 18 + HCC 48 (Morbid Obesity).",
    {"hccs": ["18"], "icds": ["E6601"]},
    output_hcc="48",
    confidence=0.85,
)

# 1g. Type 1 DM analogs (HCC 17 / 18 paths)
_add(
    "type1_dm_with_retinopathy",
    "Type 1 DM (E10.x) + diabetic retinopathy (H35.x or E10.31x-E10.35x) → HCC 18.",
    {"icds": ["E10", "H35"]},
    output_hcc="18",
    confidence=0.91,
)
_add(
    "type1_dm_with_ckd",
    "Type 1 DM + CKD (N18.x) → HCC 18.",
    {"icds": ["E10", "N18"]},
    output_hcc="18",
    confidence=0.91,
)

# 1h. DM ketoacidosis = acute complication HCC 17
_add(
    "dm_with_ketoacidosis_acute",
    "Type 2 DM + DKA (E11.10/E11.11) → HCC 17 'Diabetes with Acute Complications'.",
    {"icds": ["E1110"]},
    output_hcc="17",
    output_icd10="E11.10",
    upgrades_from_hcc="19",
    confidence=0.96,
)
_add(
    "dm_with_hyperosmolarity",
    "Type 2 DM + hyperosmolarity/HHNS (E11.00/E11.01) → HCC 17.",
    {"icds": ["E1100"]},
    output_hcc="17",
    output_icd10="E11.00",
    upgrades_from_hcc="19",
    confidence=0.96,
)

# 1i. DM + insulin use (long-term) — Z79.4 hint, not an HCC trigger by itself but
#     supports severity once chronic complication present.
_add(
    "dm_chronic_compl_with_long_term_insulin",
    "DM with chronic complications + long-term insulin use (Z79.4) — Z79.4 is mandated "
    "as an additional code for any insulin-dependent diabetic. Confirms HCC 18.",
    {"hccs": ["18"], "icds": ["Z794"]},
    output_hcc="18",
    confidence=0.85,
    source=AHA_2024Q3,
    source_url=AHA_2024Q3_URL,
)


# ===========================================================================
# 2. CKD STAGING (eGFR + ICD interplay)
#    HCC 138 — CKD Stage 3
#    HCC 137 — CKD Stage 4 / 5 (non-dialysis)
#    HCC 136 — ESRD / Dialysis
# ===========================================================================

_add(
    "ckd_stage3_from_egfr",
    "Documented CKD (N18.9) with eGFR 30-59 should be coded to specific Stage 3 (N18.30/.31/.32) "
    "→ HCC 138. KDIGO 2024 retains 30-59 as Stage 3 cut-off.",
    {"icds": ["N18"], "loinc_with_threshold": [
        {"loinc": "33914-3", "op": "<", "value": 60},
        {"loinc": "33914-3", "op": ">=", "value": 30},
    ]},
    output_hcc="138",
    output_icd10="N18.30",
    confidence=0.88,
    source=KDIGO_2024,
    source_url=KDIGO_2024_URL,
)

# Note: the rule above requires BOTH thresholds (engine has AND-semantics).
# We add a separate Stage-4 and ESRD pattern that's strictly "<30".
_add(
    "ckd_stage4_from_egfr",
    "CKD documented + eGFR <30 (and not on dialysis) → upgrade to HCC 137 'CKD Stage 4/5'.",
    {"icds": ["N18"], "loinc_with_threshold": [{"loinc": "33914-3", "op": "<", "value": 30}]},
    output_hcc="137",
    output_icd10="N18.4",
    upgrades_from_hcc="138",
    confidence=0.9,
    source=KDIGO_2024,
    source_url=KDIGO_2024_URL,
)

_add(
    "ckd_stage5_from_egfr",
    "CKD documented + eGFR <15 → CKD Stage 5 (N18.5), HCC 137. If on dialysis, "
    "see esrd_dialysis_z992.",
    {"icds": ["N18"], "loinc_with_threshold": [{"loinc": "33914-3", "op": "<", "value": 15}]},
    output_hcc="137",
    output_icd10="N18.5",
    upgrades_from_hcc="138",
    confidence=0.92,
    source=KDIGO_2024,
    source_url=KDIGO_2024_URL,
)

_add(
    "esrd_dialysis_z992",
    "Patient with CKD + dialysis status (Z99.2) → ESRD on Dialysis, HCC 136.",
    {"icds": ["N18", "Z992"]},
    output_hcc="136",
    output_icd10="N18.6",
    upgrades_from_hcc="137",
    confidence=0.96,
)

_add(
    "esrd_n186_direct",
    "N18.6 (ESRD) directly maps to HCC 136 regardless of other documentation.",
    {"icds": ["N186"]},
    output_hcc="136",
    output_icd10="N18.6",
    confidence=0.98,
)

_add(
    "ckd_with_dm_compound",
    "DM with CKD (E11.22) PLUS CKD stage code (N18.x) — affirms HCC 18 (DM chronic) and "
    "the appropriate CKD-stage HCC. Coding Clinic mandates both codes when documentation "
    "supports it.",
    {"icds": ["E1122", "N18"]},
    output_hcc="138",
    confidence=0.85,
    source=AHA_2024Q3,
    source_url=AHA_2024Q3_URL,
)


# ===========================================================================
# 3. CHF SEVERITY (HCC 226 / 224 / 225)
#    CMS V28 split heart failure into:
#       HCC 224 Acute on Chronic Heart Failure
#       HCC 225 Heart Failure Except End-Stage and Acute
#       HCC 226 (legacy CHF, in many builds)
# ===========================================================================

_add(
    "chf_acute_on_chronic_systolic",
    "I50.21 'Acute systolic (congestive) heart failure' → HCC 224 acute systolic CHF.",
    {"icds": ["I5021"]},
    output_hcc="224",
    output_icd10="I50.21",
    upgrades_from_hcc="226",
    confidence=0.95,
)
_add(
    "chf_acute_on_chronic_diastolic",
    "I50.31 'Acute diastolic (congestive) heart failure' → HCC 224.",
    {"icds": ["I5031"]},
    output_hcc="224",
    output_icd10="I50.31",
    upgrades_from_hcc="226",
    confidence=0.95,
)
_add(
    "chf_acute_on_chronic_combined",
    "I50.41 'Acute combined systolic and diastolic heart failure' → HCC 224.",
    {"icds": ["I5041"]},
    output_hcc="224",
    output_icd10="I50.41",
    upgrades_from_hcc="226",
    confidence=0.95,
)
_add(
    "chf_with_low_ef_systolic",
    "Documented CHF (I50.x) + EF <40% on echo (LOINC 8806-2) → upgrade to HCC 224 "
    "'systolic dysfunction'. ACC/AHA/HFSA 2022 Stage C HFrEF.",
    {"icds": ["I50"], "loinc_with_threshold": [{"loinc": "8806-2", "op": "<", "value": 40}]},
    output_hcc="224",
    upgrades_from_hcc="226",
    confidence=0.88,
    source=AHA_HF_2022,
    source_url=AHA_HF_2022_URL,
)
_add(
    "chf_with_mid_range_ef",
    "CHF + EF 40-49% (LOINC 8806-2) → HfMrEF, still HCC 226 base but flag for review. "
    "Per AHA 2022 'Stage C HFmrEF'.",
    {"icds": ["I50"], "loinc_with_threshold": [
        {"loinc": "8806-2", "op": ">=", "value": 40},
        {"loinc": "8806-2", "op": "<", "value": 50},
    ]},
    output_hcc="226",
    confidence=0.78,
    source=AHA_HF_2022,
    source_url=AHA_HF_2022_URL,
)
_add(
    "chf_chronic_systolic_specific",
    "I50.22 'Chronic systolic (congestive) heart failure' → HCC 226 with systolic specifier. "
    "Documenting systolic vs diastolic is required by Coding Clinic 2024Q3.",
    {"icds": ["I5022"]},
    output_hcc="226",
    output_icd10="I50.22",
    confidence=0.9,
    source=AHA_2024Q3,
    source_url=AHA_2024Q3_URL,
)
_add(
    "chf_chronic_diastolic_specific",
    "I50.32 'Chronic diastolic (congestive) heart failure' → HCC 226. "
    "Coding Clinic 2024Q3 reinforced specificity.",
    {"icds": ["I5032"]},
    output_hcc="226",
    output_icd10="I50.32",
    confidence=0.9,
    source=AHA_2024Q3,
    source_url=AHA_2024Q3_URL,
)
_add(
    "chf_with_acute_pulm_edema",
    "I50.1 (Left ventricular failure) + J81.0 (Acute pulmonary edema) → upgrade to HCC 224.",
    {"icds": ["I501", "J810"]},
    output_hcc="224",
    upgrades_from_hcc="226",
    confidence=0.9,
)
_add(
    "chf_with_loop_diuretic",
    "CHF + loop diuretic (ATC C03CA — furosemide etc.) — corroborates active management. "
    "No HCC change but raises confidence.",
    {"icds": ["I50"], "atc_codes": ["C03CA"]},
    output_hcc="226",
    confidence=0.7,
    source=AHA_2024Q3,
    source_url=AHA_2024Q3_URL,
)


# ===========================================================================
# 4. COPD PROGRESSION (HCC 280 / 279)
# ===========================================================================

_add(
    "copd_with_acute_exacerbation",
    "COPD (J44.9) + J44.1 'COPD with (acute) exacerbation' → HCC 279 acute COPD with "
    "exacerbation.",
    {"icds": ["J441"]},
    output_hcc="279",
    output_icd10="J44.1",
    upgrades_from_hcc="280",
    confidence=0.93,
)
_add(
    "copd_with_lower_resp_infection",
    "COPD + J44.0 'COPD with (acute) lower respiratory infection' → HCC 279.",
    {"icds": ["J440"]},
    output_hcc="279",
    output_icd10="J44.0",
    upgrades_from_hcc="280",
    confidence=0.93,
)
_add(
    "copd_with_chronic_resp_failure",
    "COPD (J44.x) + chronic respiratory failure (J96.10/.11/.12) → add HCC 84 'Respiratory "
    "Failure'.",
    {"icds": ["J44", "J9610"]},
    output_hcc="84",
    confidence=0.9,
)
_add(
    "copd_with_acute_resp_failure",
    "COPD + acute respiratory failure (J96.00/.01/.02) → HCC 84.",
    {"icds": ["J44", "J9600"]},
    output_hcc="84",
    confidence=0.92,
)
_add(
    "copd_with_oxygen_dependence",
    "COPD + Z99.81 (Dependence on supplemental oxygen) → HCC 280 baseline plus support "
    "for severity. Per Coding Clinic 2024Q3 home-O2 patients warrant chronic-resp-failure "
    "review.",
    {"icds": ["J44", "Z9981"]},
    output_hcc="280",
    confidence=0.8,
    source=AHA_2024Q3,
    source_url=AHA_2024Q3_URL,
)


# ===========================================================================
# 5. CANCER — ACTIVE vs HISTORY (HCCs 17 series varies by site)
#    A patient with a cancer diagnosis code AND chemo (Z51.11) or radiation (Z51.0)
#    is "active". A history-of code (Z85.x) without active treatment is NOT.
# ===========================================================================

_add(
    "active_cancer_breast_with_chemo",
    "Breast cancer (C50.x) + chemotherapy encounter (Z51.11) → keep as active malignancy "
    "for HCC purposes. Coding Clinic mandates the active C-code as long as treatment "
    "remains directed at the cancer.",
    {"icds": ["C50", "Z5111"]},
    output_hcc="22",
    confidence=0.9,
    source=AHA_2024Q3,
    source_url=AHA_2024Q3_URL,
)
_add(
    "active_cancer_lung_with_chemo",
    "Lung cancer (C34.x) + Z51.11 → active, HCC 19 (Lung & Severe Cancers).",
    {"icds": ["C34", "Z5111"]},
    output_hcc="19",
    confidence=0.9,
)
_add(
    "active_cancer_colon_with_chemo",
    "Colon cancer (C18.x) + Z51.11 → active, HCC 22.",
    {"icds": ["C18", "Z5111"]},
    output_hcc="22",
    confidence=0.9,
)
_add(
    "active_cancer_prostate_with_radiation",
    "Prostate cancer (C61) + Z51.0 (radiation encounter) → active, HCC 23.",
    {"icds": ["C61", "Z510"]},
    output_hcc="23",
    confidence=0.88,
)
_add(
    "active_cancer_with_immunotherapy_atc",
    "Active cancer C-code + immunotherapy drug (ATC L01F monoclonal antibodies, e.g. "
    "pembrolizumab L01FF02) supports active disease.",
    {"icds": ["C"], "atc_codes": ["L01F"]},
    output_hcc="22",
    confidence=0.78,
    source=AHA_2024Q3,
    source_url=AHA_2024Q3_URL,
)
_add(
    "metastatic_cancer_secondary_codes",
    "Any C77.x / C78.x / C79.x (secondary malignant neoplasm) → HCC 17 'Metastatic Cancer "
    "and Acute Leukemia'.",
    {"icds": ["C77"]},
    output_hcc="17",
    output_icd10="C77.9",
    confidence=0.95,
)
_add(
    "metastatic_lung_cancer",
    "C78.0x (secondary malignant neoplasm of lung) → HCC 17.",
    {"icds": ["C780"]},
    output_hcc="17",
    output_icd10="C78.00",
    confidence=0.96,
)
_add(
    "metastatic_liver_cancer",
    "C78.7 (secondary malignant neoplasm of liver) → HCC 17.",
    {"icds": ["C787"]},
    output_hcc="17",
    output_icd10="C78.7",
    confidence=0.96,
)
_add(
    "acute_leukemia_active",
    "C91.0 / C92.0 (acute lymphoblastic / myeloid leukemia in remission *not* coded) → HCC 17.",
    {"icds": ["C910"]},
    output_hcc="17",
    output_icd10="C91.00",
    confidence=0.94,
)
_add(
    "cancer_history_without_treatment_no_hcc",
    "Z85.x (personal history of malignant neoplasm) WITHOUT any C-code or treatment "
    "encounter → NOT active. Engine asserts an empty HCC ('-') so callers can suppress "
    "an erroneous active-cancer suspect.",
    {"icds": ["Z85"]},
    output_hcc="-",
    confidence=0.6,
    source=AHA_2024Q3,
    source_url=AHA_2024Q3_URL,
)


# ===========================================================================
# 6. MENTAL HEALTH COMPLEXITY
#    HCC 151 — Schizophrenia, severe psychosis
#    HCC 152 — Bipolar / Major depression with psychotic features
#    HCC 153 — Major Depression
# ===========================================================================

_add(
    "bipolar_with_acute_admission",
    "Bipolar disorder (F31.x) + acute manic/depressive admission code (F31.10-.13/.2/.5x) "
    "represents HCC 151 severity range — flag for clinical review.",
    {"icds": ["F312"]},
    output_hcc="151",
    output_icd10="F31.2",
    upgrades_from_hcc="152",
    confidence=0.85,
)
_add(
    "bipolar_severe_psychotic",
    "F31.5 'Bipolar disorder, current episode depressed, severe with psychotic features' → HCC 151.",
    {"icds": ["F315"]},
    output_hcc="151",
    output_icd10="F31.5",
    upgrades_from_hcc="152",
    confidence=0.92,
)
_add(
    "schizophrenia_paranoid",
    "F20.0 (Paranoid schizophrenia) → HCC 151.",
    {"icds": ["F200"]},
    output_hcc="151",
    output_icd10="F20.0",
    confidence=0.95,
)
_add(
    "schizophrenia_with_clozapine",
    "Schizophrenia (F20.x) + clozapine prescription (RxNorm 2622 / ATC N05AH02) → "
    "treatment-resistant, supports HCC 151. Clozapine REMS implies severe disease.",
    {"icds": ["F20"], "atc_codes": ["N05AH02"]},
    output_hcc="151",
    confidence=0.92,
)
_add(
    "schizoaffective_disorder",
    "F25.x (Schizoaffective disorder) → HCC 151.",
    {"icds": ["F25"]},
    output_hcc="151",
    output_icd10="F25.0",
    confidence=0.93,
)
_add(
    "major_depression_recurrent_severe_psychotic",
    "F33.3 (Major depressive disorder, recurrent, severe with psychotic symptoms) → HCC 152.",
    {"icds": ["F333"]},
    output_hcc="152",
    output_icd10="F33.3",
    upgrades_from_hcc="153",
    confidence=0.93,
)
_add(
    "major_depression_with_lithium",
    "Bipolar/major depression (F31.x or F33.x) + lithium (ATC N05AN01) → reinforces HCC 152.",
    {"icds": ["F31"], "atc_codes": ["N05AN01"]},
    output_hcc="152",
    confidence=0.85,
)
_add(
    "ptsd_chronic",
    "F43.10/F43.11/F43.12 (PTSD) → HCC 153 (Major Depression, Bipolar, and other "
    "psychiatric disorders, depending on V28 grouping).",
    {"icds": ["F4310"]},
    output_hcc="153",
    output_icd10="F43.10",
    confidence=0.82,
)


# ===========================================================================
# 7. HIV / AIDS
#    HCC 1 — HIV/AIDS
# ===========================================================================

_add(
    "hiv_b20_direct",
    "B20 (HIV disease) → HCC 1 unconditionally per V28 crosswalk.",
    {"icds": ["B20"]},
    output_hcc="1",
    output_icd10="B20",
    confidence=0.99,
)
_add(
    "hiv_with_pcp_pneumonia",
    "HIV + Pneumocystis pneumonia (B59) → HCC 1 with opportunistic infection (also adds "
    "HCC 6 for severe infection in some V28 builds).",
    {"icds": ["B20", "B59"]},
    output_hcc="1",
    confidence=0.96,
)
_add(
    "hiv_with_kaposi_sarcoma",
    "HIV + Kaposi sarcoma (C46.x) → HCC 1 + HCC 17 (cancer).",
    {"icds": ["B20", "C46"]},
    output_hcc="1",
    confidence=0.95,
)
_add(
    "hiv_with_cmv",
    "HIV + cytomegaloviral disease (B25.x) → HCC 1.",
    {"icds": ["B20", "B25"]},
    output_hcc="1",
    confidence=0.94,
)
_add(
    "hiv_with_haart_atc",
    "HIV + antiretroviral combination therapy (ATC J05AR — fixed-dose ARV combinations) "
    "supports active HIV disease, HCC 1.",
    {"icds": ["B20"], "atc_codes": ["J05AR"]},
    output_hcc="1",
    confidence=0.88,
)


# ===========================================================================
# 8. VASCULAR / PVD
#    HCC 106 — Atherosclerosis of Limbs with Ulceration or Gangrene
#    HCC 107 — Vascular Disease w/ Complications
#    HCC 108 — Vascular Disease (PVD without complications)
# ===========================================================================

_add(
    "pvd_with_amputation_status",
    "PVD (I73.9 / I70.x) + Z89.x amputation status → HCC 106.",
    {"icds": ["I70", "Z89"]},
    output_hcc="106",
    upgrades_from_hcc="108",
    confidence=0.93,
)
_add(
    "pvd_with_gangrene",
    "PVD + gangrene (I96) → HCC 106.",
    {"icds": ["I70", "I96"]},
    output_hcc="106",
    upgrades_from_hcc="108",
    confidence=0.95,
)
_add(
    "atherosclerosis_with_ulcer",
    "I70.232/I70.233 (atherosclerosis of native arteries of extremities with ulceration) → HCC 106.",
    {"icds": ["I70232"]},
    output_hcc="106",
    output_icd10="I70.232",
    upgrades_from_hcc="108",
    confidence=0.96,
)
_add(
    "dm_with_pvd_compound",
    "DM + PVD (I73.9 or I70.2x) → asserts HCC 18 (DM chronic) AND HCC 108 PVD. "
    "Coding Clinic 2024Q1: code both when documentation supports the link (E11.51 / E11.59).",
    {"icds": ["E11", "I70"]},
    output_hcc="108",
    confidence=0.85,
    source=AHA_2024Q3,
    source_url=AHA_2024Q3_URL,
)
_add(
    "dm_pvd_with_amputation_compound",
    "DM + PVD + amputation status (Z89.x) — triple compound: HCC 18 + HCC 106. The most "
    "severe vascular HCC is asserted here.",
    {"icds": ["E11", "I70", "Z89"]},
    output_hcc="106",
    confidence=0.92,
    source=AHA_2024Q3,
    source_url=AHA_2024Q3_URL,
)


# ===========================================================================
# 9. STROKE / NEURO
# ===========================================================================

_add(
    "stroke_with_hemiplegia",
    "History of CVA (Z86.73 / I69.x) + hemiplegia (G81.x) → HCC 100/101.",
    {"icds": ["I69", "G81"]},
    output_hcc="100",
    confidence=0.92,
)
_add(
    "stroke_with_aphasia",
    "I69.x + aphasia (R47.01) → HCC 102 sequelae.",
    {"icds": ["I69", "R4701"]},
    output_hcc="102",
    confidence=0.88,
)
_add(
    "parkinsons_with_falls_history",
    "Parkinson disease (G20) + history of falling (Z91.81) — supports HCC 78 'Polyneuropathy "
    "/ Major Movement Disorder' via Parkinson's group.",
    {"icds": ["G20"]},
    output_hcc="78",
    output_icd10="G20",
    confidence=0.9,
)
_add(
    "alzheimers_with_behavioral",
    "Alzheimer disease (G30.x) + F02.81 (Dementia with behavioral disturbance) → HCC 52.",
    {"icds": ["G30", "F0281"]},
    output_hcc="52",
    confidence=0.9,
)
_add(
    "dementia_unspecified_with_behavioral",
    "F03.91 (Unspecified dementia with behavioral disturbance) → HCC 52.",
    {"icds": ["F0391"]},
    output_hcc="52",
    output_icd10="F03.91",
    confidence=0.9,
)


# ===========================================================================
# 10. LIVER DISEASE
# ===========================================================================

_add(
    "alcoholic_cirrhosis",
    "K70.30/K70.31 (alcoholic cirrhosis of liver) → HCC 28 'End-Stage Liver Disease'.",
    {"icds": ["K7030"]},
    output_hcc="28",
    output_icd10="K70.30",
    confidence=0.95,
)
_add(
    "cirrhosis_with_ascites",
    "K74.x cirrhosis + R18.0 (ascites) → HCC 28.",
    {"icds": ["K74", "R180"]},
    output_hcc="28",
    confidence=0.93,
)
_add(
    "hepatic_encephalopathy",
    "K72.x (hepatic failure) + cirrhosis (K74.x) → HCC 28.",
    {"icds": ["K72", "K74"]},
    output_hcc="28",
    confidence=0.94,
)
_add(
    "chronic_hep_c_with_cirrhosis",
    "Chronic hep C (B18.2) + cirrhosis (K74.x) → HCC 28.",
    {"icds": ["B182", "K74"]},
    output_hcc="28",
    confidence=0.94,
)


# ===========================================================================
# 11. SUBSTANCE USE
# ===========================================================================

_add(
    "alcohol_dep_with_withdrawal",
    "F10.230/F10.231 (alcohol dependence with withdrawal) → HCC 56 'Drug/Alcohol Dependence'.",
    {"icds": ["F10230"]},
    output_hcc="56",
    output_icd10="F10.230",
    confidence=0.94,
)
_add(
    "opioid_dep_active",
    "F11.20 (opioid dependence, uncomplicated) → HCC 56.",
    {"icds": ["F1120"]},
    output_hcc="56",
    output_icd10="F11.20",
    confidence=0.93,
)
_add(
    "opioid_dep_with_buprenorphine",
    "F11.x + buprenorphine (ATC N07BC01) — MAT corroborates active opioid use disorder, HCC 56.",
    {"icds": ["F11"], "atc_codes": ["N07BC01"]},
    output_hcc="56",
    confidence=0.85,
)


# ===========================================================================
# 12. RHEUMATOLOGIC / AUTOIMMUNE
#    HCC 40 — Rheumatoid Arthritis & Inflammatory Connective Tissue Disease
# ===========================================================================

_add(
    "ra_seropositive_active",
    "M05.x (Rheumatoid arthritis with rheumatoid factor) → HCC 40.",
    {"icds": ["M05"]},
    output_hcc="40",
    output_icd10="M05.79",
    confidence=0.94,
)
_add(
    "ra_with_biologic",
    "RA (M05/M06) + biologic DMARD (ATC L04AB — TNF-α inhibitors) → reinforces HCC 40.",
    {"icds": ["M05"], "atc_codes": ["L04AB"]},
    output_hcc="40",
    confidence=0.9,
)
_add(
    "lupus_active",
    "M32.x (SLE) → HCC 40.",
    {"icds": ["M32"]},
    output_hcc="40",
    output_icd10="M32.9",
    confidence=0.93,
)
_add(
    "psoriatic_arthritis",
    "L40.5x (Arthropathic psoriasis) → HCC 40.",
    {"icds": ["L405"]},
    output_hcc="40",
    output_icd10="L40.50",
    confidence=0.9,
)


# ===========================================================================
# 13. RESPIRATORY (NON-COPD)
# ===========================================================================

_add(
    "interstitial_lung_disease",
    "J84.x (interstitial lung disease) → HCC 280 (Respiratory Disease group).",
    {"icds": ["J84"]},
    output_hcc="280",
    output_icd10="J84.10",
    confidence=0.9,
)
_add(
    "cystic_fibrosis",
    "E84.x (Cystic fibrosis) → HCC 76.",
    {"icds": ["E84"]},
    output_hcc="76",
    output_icd10="E84.0",
    confidence=0.96,
)
_add(
    "pulmonary_hypertension_primary",
    "I27.0 (Primary pulmonary hypertension) → HCC 264.",
    {"icds": ["I270"]},
    output_hcc="264",
    output_icd10="I27.0",
    confidence=0.93,
)
_add(
    "pulmonary_hypertension_with_chf",
    "I27.2x (Other secondary pulmonary hypertension) + CHF (I50.x) → HCC 264 + HCC 226.",
    {"icds": ["I272", "I50"]},
    output_hcc="264",
    confidence=0.88,
)


# ===========================================================================
# 14. CARDIOVASCULAR (BEYOND CHF)
# ===========================================================================

_add(
    "atrial_fibrillation_persistent",
    "I48.0 (paroxysmal AF) / I48.1 (persistent AF) → HCC 96.",
    {"icds": ["I481"]},
    output_hcc="96",
    output_icd10="I48.1",
    confidence=0.94,
)
_add(
    "afib_with_anticoagulation",
    "AF (I48.x) + DOAC (ATC B01AF — apixaban, rivaroxaban, etc.) → reinforces HCC 96 active management.",
    {"icds": ["I48"], "atc_codes": ["B01AF"]},
    output_hcc="96",
    confidence=0.86,
)
_add(
    "old_mi_history",
    "I25.2 (Old MI) → HCC 88 'Specified Heart Arrhythmias / Coronary Atherosclerosis'.",
    {"icds": ["I252"]},
    output_hcc="88",
    output_icd10="I25.2",
    confidence=0.92,
)
_add(
    "cad_with_stent_history",
    "Coronary atherosclerosis (I25.10/I25.11) + Z95.5 (PTCA/stent status) → HCC 88.",
    {"icds": ["I2510", "Z955"]},
    output_hcc="88",
    confidence=0.9,
)
_add(
    "valve_disease_severe",
    "I35.x (aortic valve disorders, non-rheumatic) — moderate-severe → HCC 88.",
    {"icds": ["I35"]},
    output_hcc="88",
    output_icd10="I35.0",
    confidence=0.86,
)


# ===========================================================================
# 15. ENDOCRINE — non-diabetes
# ===========================================================================

_add(
    "morbid_obesity_e6601",
    "E66.01 (Morbid obesity due to excess calories) → HCC 48 (V28).",
    {"icds": ["E6601"]},
    output_hcc="48",
    output_icd10="E66.01",
    confidence=0.95,
)
_add(
    "morbid_obesity_with_bmi40plus",
    "E66.01 + Z68.41 (BMI 40-44.9) — affirms HCC 48.",
    {"icds": ["E6601", "Z6841"]},
    output_hcc="48",
    confidence=0.97,
)
_add(
    "thyroid_storm",
    "E05.5 (Thyroid storm) → HCC 50 'Endocrine Disorders'.",
    {"icds": ["E055"]},
    output_hcc="50",
    output_icd10="E05.5",
    confidence=0.92,
)
_add(
    "addisons_disease",
    "E27.1 (Primary adrenocortical insufficiency) → HCC 50.",
    {"icds": ["E271"]},
    output_hcc="50",
    output_icd10="E27.1",
    confidence=0.92,
)


# ===========================================================================
# 16. SKIN / WOUND
# ===========================================================================

_add(
    "pressure_ulcer_stage4",
    "L89.xx4 (Pressure ulcer, stage 4) → HCC 379 'Severe Skin Burn or Condition'.",
    {"icds": ["L89004"]},
    output_hcc="379",
    output_icd10="L89.004",
    confidence=0.95,
)
_add(
    "chronic_skin_ulcer_lower_limb",
    "L97.x (non-pressure chronic ulcer of lower limb) → HCC 380.",
    {"icds": ["L97"]},
    output_hcc="380",
    output_icd10="L97.909",
    confidence=0.9,
)


# ===========================================================================
# 17. BLOOD / IMMUNE
# ===========================================================================

_add(
    "sickle_cell_with_crisis",
    "D57.0x (Hb-SS disease with crisis) → HCC 47 'Disorders of Immunity / Hematologic Disorders'.",
    {"icds": ["D570"]},
    output_hcc="47",
    output_icd10="D57.00",
    confidence=0.95,
)
_add(
    "aplastic_anemia",
    "D61.x (Aplastic anemia) → HCC 47.",
    {"icds": ["D61"]},
    output_hcc="47",
    output_icd10="D61.9",
    confidence=0.92,
)
_add(
    "neutropenia_severe",
    "D70.x (Neutropenia) — chronic / drug-induced → HCC 47.",
    {"icds": ["D70"]},
    output_hcc="47",
    output_icd10="D70.9",
    confidence=0.85,
)


# ===========================================================================
# 18. GI
# ===========================================================================

_add(
    "ulcerative_colitis",
    "K51.x (Ulcerative colitis) → HCC 35 'Inflammatory Bowel Disease'.",
    {"icds": ["K51"]},
    output_hcc="35",
    output_icd10="K51.90",
    confidence=0.94,
)
_add(
    "crohns_disease",
    "K50.x (Crohn disease) → HCC 35.",
    {"icds": ["K50"]},
    output_hcc="35",
    output_icd10="K50.90",
    confidence=0.94,
)
_add(
    "ibd_with_biologic",
    "IBD (K50/K51) + biologic (ATC L04AB or L04AC) → reinforces HCC 35.",
    {"icds": ["K50"], "atc_codes": ["L04AB"]},
    output_hcc="35",
    confidence=0.88,
)


# ===========================================================================
# 19. SEPSIS / ACUTE INFECTIOUS
# ===========================================================================

_add(
    "sepsis_severe",
    "A41.x (Sepsis, other) → HCC 2 'Septicemia / Sepsis / SIRS / Shock'.",
    {"icds": ["A41"]},
    output_hcc="2",
    output_icd10="A41.9",
    confidence=0.95,
)
_add(
    "sepsis_with_organ_failure",
    "Sepsis (A41.x) + R65.21 (Severe sepsis with septic shock) → HCC 2 with severity escalation.",
    {"icds": ["A41", "R6521"]},
    output_hcc="2",
    confidence=0.97,
)


# ===========================================================================
# 20. NEUROLOGIC — seizures, MS
# ===========================================================================

_add(
    "epilepsy_intractable",
    "G40.x intractable codes (G40.011, G40.111, G40.219, G40.311, G40.411) → HCC 79 "
    "'Seizure Disorders'.",
    {"icds": ["G40011"]},
    output_hcc="79",
    output_icd10="G40.011",
    confidence=0.93,
)
_add(
    "multiple_sclerosis",
    "G35 (Multiple sclerosis) → HCC 77.",
    {"icds": ["G35"]},
    output_hcc="77",
    output_icd10="G35",
    confidence=0.96,
)
_add(
    "als_motor_neuron_disease",
    "G12.21 (ALS) → HCC 77 (V28 'Multiple Sclerosis & Other Neuro' grouping varies).",
    {"icds": ["G1221"]},
    output_hcc="77",
    output_icd10="G12.21",
    confidence=0.96,
)


# ===========================================================================
# 21. RARE / GENETIC
# ===========================================================================

_add(
    "amyloidosis_systemic",
    "E85.x (Amyloidosis) → HCC 23 (Other Significant Endocrine Disorders).",
    {"icds": ["E85"]},
    output_hcc="23",
    output_icd10="E85.9",
    confidence=0.9,
)
_add(
    "huntingtons_disease",
    "G10 (Huntington disease) → HCC 78.",
    {"icds": ["G10"]},
    output_hcc="78",
    output_icd10="G10",
    confidence=0.95,
)


# ===========================================================================
# 22. TRANSPLANT STATUS
# ===========================================================================

_add(
    "kidney_transplant_status",
    "Z94.0 (Kidney transplant status) → HCC 137 (kidney-transplant V28 group). Per V28, "
    "transplant status keeps the patient in the chronic kidney HCC group.",
    {"icds": ["Z940"]},
    output_hcc="137",
    output_icd10="Z94.0",
    confidence=0.92,
)
_add(
    "heart_transplant_status",
    "Z94.1 (Heart transplant status) → HCC 226.",
    {"icds": ["Z941"]},
    output_hcc="226",
    output_icd10="Z94.1",
    confidence=0.92,
)
_add(
    "liver_transplant_status",
    "Z94.4 (Liver transplant status) → HCC 28.",
    {"icds": ["Z944"]},
    output_hcc="28",
    output_icd10="Z94.4",
    confidence=0.92,
)
_add(
    "lung_transplant_status",
    "Z94.2 (Lung transplant status) → HCC 280.",
    {"icds": ["Z942"]},
    output_hcc="280",
    output_icd10="Z94.2",
    confidence=0.92,
)


# ===========================================================================
# 23. EATING DISORDERS / FAILURE TO THRIVE
# ===========================================================================

_add(
    "protein_calorie_malnutrition_severe",
    "E43 (Unspecified severe protein-calorie malnutrition) → HCC 49 'Severe Malnutrition'.",
    {"icds": ["E43"]},
    output_hcc="49",
    output_icd10="E43",
    confidence=0.96,
)
_add(
    "protein_calorie_malnutrition_moderate",
    "E44.0 (Moderate protein-calorie malnutrition) → HCC 49.",
    {"icds": ["E440"]},
    output_hcc="49",
    output_icd10="E44.0",
    confidence=0.92,
)


# ===========================================================================
# 24. UROLOGIC / GU
# ===========================================================================

_add(
    "hereditary_kidney_disease",
    "Q61.x (cystic kidney disease) → HCC 138 baseline.",
    {"icds": ["Q61"]},
    output_hcc="138",
    output_icd10="Q61.3",
    confidence=0.9,
)
_add(
    "neurogenic_bladder",
    "N31.x (Neuromuscular dysfunction of bladder) → HCC 379 (depending on V28 grouping; "
    "asserted as a complication marker).",
    {"icds": ["N31"]},
    output_hcc="379",
    output_icd10="N31.9",
    confidence=0.78,
)


# ===========================================================================
# 25. MUSCULOSKELETAL — fragility / fractures
# ===========================================================================

_add(
    "vertebral_fracture_pathologic",
    "M80.x (Osteoporosis with current pathological fracture) → HCC 169 (Hip Fracture / "
    "Pelvic Fracture / Pathologic Fracture group depending on V28 build).",
    {"icds": ["M80"]},
    output_hcc="169",
    output_icd10="M80.08XA",
    confidence=0.9,
)
_add(
    "hip_fracture_acute",
    "S72.0/S72.1/S72.2 (Hip fracture) → HCC 169.",
    {"icds": ["S720"]},
    output_hcc="169",
    output_icd10="S72.001A",
    confidence=0.93,
)


# ===========================================================================
# 26. RESPIRATORY FAILURE COMPOUND PATTERNS
# ===========================================================================

_add(
    "chronic_resp_failure_with_copd",
    "Chronic respiratory failure (J96.10/.11/.12) + COPD (J44.x) → HCC 84 plus HCC 280.",
    {"icds": ["J9610", "J44"]},
    output_hcc="84",
    confidence=0.92,
)
_add(
    "chronic_resp_failure_with_obesity",
    "Chronic respiratory failure (J96.1x) + morbid obesity (E66.01) → obesity-hypoventilation, "
    "HCC 84 + HCC 48.",
    {"icds": ["J9610", "E6601"]},
    output_hcc="84",
    confidence=0.9,
)


# ===========================================================================
# 27. DM PATIENT WITH HIGH-A1C — supports HCC 19 if no chronic complications,
#    HCC 17 if DKA-implying, used for CONFIDENCE only (no upgrade).
# ===========================================================================

_add(
    "dm_with_high_a1c",
    "Type 2 DM + HbA1c >9% (LOINC 4548-4) — uncontrolled but no chronic complication "
    "documented; stays HCC 19 but flag for clinical review.",
    {"icds": ["E11"], "loinc_with_threshold": [{"loinc": "4548-4", "op": ">", "value": 9.0}]},
    output_hcc="19",
    confidence=0.7,
)
_add(
    "dm_with_severe_hypoglycemia",
    "Type 2 DM + glucose <50 mg/dL (LOINC 2345-7) → likely E11.649 (DM with hypoglycemia w/o coma) "
    "→ HCC 17 acute complications.",
    {"icds": ["E11"], "loinc_with_threshold": [{"loinc": "2345-7", "op": "<", "value": 50}]},
    output_hcc="17",
    output_icd10="E11.649",
    upgrades_from_hcc="19",
    confidence=0.82,
)


# ===========================================================================
# Sanity check
# ===========================================================================

assert len(PATTERNS) >= 100, f"Need at least 100 patterns, got {len(PATTERNS)}"


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

UPSERT_SQL = """
INSERT INTO kg_comorbidity_patterns (
    pattern_name, description, required_evidence,
    output_hcc, output_icd10, upgrades_from_hcc,
    confidence, source, source_url, model_version, is_active
) VALUES (
    %(pattern_name)s, %(description)s, %(required_evidence)s,
    %(output_hcc)s, %(output_icd10)s, %(upgrades_from_hcc)s,
    %(confidence)s, %(source)s, %(source_url)s, 'V28', 1
)
ON DUPLICATE KEY UPDATE
    description       = VALUES(description),
    required_evidence = VALUES(required_evidence),
    output_hcc        = VALUES(output_hcc),
    output_icd10      = VALUES(output_icd10),
    upgrades_from_hcc = VALUES(upgrades_from_hcc),
    confidence        = VALUES(confidence),
    source            = VALUES(source),
    source_url        = VALUES(source_url),
    is_active         = 1
"""


def _ensure_unique_index() -> None:
    """The base migration doesn't include a UNIQUE on pattern_name (so the
    schema stays exactly as specified).  Add it idempotently so the upsert
    above works.
    """
    sql = """
        SELECT COUNT(*) AS c
        FROM information_schema.statistics
        WHERE table_schema = DATABASE()
          AND table_name   = 'kg_comorbidity_patterns'
          AND index_name   = 'uq_pattern_name'
    """
    with raf_cursor() as cur:
        cur.execute(sql)
        row = cur.fetchone()
        if row and row.get("c", 0) == 0:
            cur.execute(
                "ALTER TABLE kg_comorbidity_patterns "
                "ADD UNIQUE KEY uq_pattern_name (pattern_name)"
            )


def seed(dry_run: bool = False) -> int:
    """Insert (or update) every pattern.  Returns rows affected."""
    if dry_run:
        for p in PATTERNS:
            print(json.dumps({**p, "required_evidence": p["required_evidence"]}, default=str))
        return len(PATTERNS)

    _ensure_unique_index()

    payload = []
    for p in PATTERNS:
        payload.append({
            **p,
            "required_evidence": json.dumps(p["required_evidence"]),
        })

    with raf_cursor() as cur:
        cur.executemany(UPSERT_SQL, payload)
    return len(payload)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Print patterns to stdout, do not write to DB.")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s  %(levelname)-7s  %(message)s",
        datefmt="%H:%M:%S",
    )

    n = seed(dry_run=args.dry_run)
    logger.info("seed_comorbidity_patterns: processed %d patterns (dry_run=%s)", n, args.dry_run)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
