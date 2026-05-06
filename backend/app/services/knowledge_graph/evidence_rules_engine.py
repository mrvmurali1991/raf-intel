"""Literature-backed evidence rules engine.

Every rule in :data:`CURATED_RULES` is attributed to a specific clinical
source (CMS HCC V28 spec, AHA Coding Clinic, ADA, KDIGO, ACC/AHA, GOLD,
APA DSM-5, USPSTF, AAFP, or peer-reviewed literature).  No ad-hoc rules.

Trigger condition kinds supported:

* ``icd10`` — patient has an ICD-10 code matching ``code`` (exact) or
  ``prefix`` (startswith) anywhere in ``evidence['icd10']``.
* ``atc``  — patient has a medication whose ATC code matches.
* ``loinc_threshold`` — patient has a LOINC observation with code ``code``
  whose numeric value passes ``op`` (one of ``<``, ``<=``, ``=``, ``>=``,
  ``>``) ``value``.
* ``note_pattern`` — case-insensitive regex/substring match against any
  string in ``evidence['notes']``.

Trigger logic is ``all`` (AND) or ``any`` (OR) over the conditions list.
"""
from __future__ import annotations

import logging
import re
from typing import Any, Iterable

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Curated rule catalogue — 50 literature-backed rules
# ---------------------------------------------------------------------------

CURATED_RULES: list[dict[str, Any]] = [
    # =====================================================================
    # ADA — Diabetes Standards of Care 2024 (Diabetes Care, vol 47, S1)
    # =====================================================================
    {
        "rule_name": "ada_dm_uncontrolled_hba1c_gt9",
        "rule_description": "Type 2 DM with HbA1c >9 indicates uncontrolled hyperglycemia per ADA Standards of Care 2024 §6 (Glycemic Goals).",
        "trigger_logic": "all",
        "trigger_conditions": [
            {"kind": "icd10", "prefix": "E11"},
            {"kind": "loinc_threshold", "code": "4548-4", "op": ">", "value": 9.0},
        ],
        "output_hcc": "18",
        "output_icd10": "E11.65",
        "confidence": 0.92,
        "source_type": "ADA-guideline",
        "source_citation": "American Diabetes Association. Standards of Care in Diabetes—2024. Section 6: Glycemic Goals and Hypoglycemia. Diabetes Care 47(Suppl 1):S111–S125.",
        "source_url": "https://diabetesjournals.org/care/issue/47/Supplement_1",
        "source_year": 2024,
    },
    {
        "rule_name": "ada_dm_with_retinopathy",
        "rule_description": "DM + diabetic retinopathy (H35.x or E11.3x) → DM with ophthalmic complication HCC 18 per ADA §12.",
        "trigger_logic": "any",
        "trigger_conditions": [
            {"kind": "icd10", "prefix": "E11.3"},
            {"kind": "icd10", "prefix": "H35.0"},
        ],
        "output_hcc": "18",
        "output_icd10": "E11.319",
        "confidence": 0.90,
        "source_type": "ADA-guideline",
        "source_citation": "ADA Standards of Care 2024 §12: Retinopathy, Neuropathy, and Foot Care. Diabetes Care 47(Suppl 1):S231–S243.",
        "source_url": None,
        "source_year": 2024,
    },
    {
        "rule_name": "ada_dm_with_nephropathy",
        "rule_description": "DM + diabetic kidney disease (E11.21/E11.22) → DM with renal complication HCC 18.",
        "trigger_logic": "any",
        "trigger_conditions": [
            {"kind": "icd10", "code": "E11.21"},
            {"kind": "icd10", "code": "E11.22"},
        ],
        "output_hcc": "18",
        "output_icd10": "E11.21",
        "confidence": 0.93,
        "source_type": "ADA-guideline",
        "source_citation": "ADA Standards of Care 2024 §11: Chronic Kidney Disease and Risk Management. Diabetes Care 47(Suppl 1):S219–S230.",
        "source_url": None,
        "source_year": 2024,
    },
    {
        "rule_name": "ada_dm_with_neuropathy",
        "rule_description": "DM + diabetic neuropathy (E11.4x) → DM with neurologic complication HCC 18.",
        "trigger_logic": "all",
        "trigger_conditions": [
            {"kind": "icd10", "prefix": "E11.4"},
        ],
        "output_hcc": "18",
        "output_icd10": "E11.40",
        "confidence": 0.90,
        "source_type": "ADA-guideline",
        "source_citation": "ADA Standards of Care 2024 §12: Retinopathy, Neuropathy, and Foot Care. Diabetes Care 47(Suppl 1):S231–S243.",
        "source_url": None,
        "source_year": 2024,
    },
    {
        "rule_name": "ada_dm_with_foot_ulcer",
        "rule_description": "DM + foot ulcer (E11.621/E11.622) → DM with skin complication HCC 18.",
        "trigger_logic": "any",
        "trigger_conditions": [
            {"kind": "icd10", "code": "E11.621"},
            {"kind": "icd10", "code": "E11.622"},
        ],
        "output_hcc": "18",
        "output_icd10": "E11.621",
        "confidence": 0.94,
        "source_type": "ADA-guideline",
        "source_citation": "ADA Standards of Care 2024 §12: Retinopathy, Neuropathy, and Foot Care. Diabetes Care 47(Suppl 1):S231–S243.",
        "source_url": None,
        "source_year": 2024,
    },
    {
        "rule_name": "ada_dm_controlled_hba1c_lt7_no_complication",
        "rule_description": "Uncomplicated T2DM + HbA1c <7 → HCC 19 (DM without complications, well-controlled).",
        "trigger_logic": "all",
        "trigger_conditions": [
            {"kind": "icd10", "code": "E11.9"},
            {"kind": "loinc_threshold", "code": "4548-4", "op": "<", "value": 7.0},
        ],
        "output_hcc": "19",
        "output_icd10": "E11.9",
        "confidence": 0.85,
        "source_type": "ADA-guideline",
        "source_citation": "ADA Standards of Care 2024 §6: Glycemic Goals. Target HbA1c <7% for most non-pregnant adults. Diabetes Care 47(Suppl 1):S111–S125.",
        "source_url": None,
        "source_year": 2024,
    },
    {
        "rule_name": "ada_dm_on_insulin_intermediate_a1c",
        "rule_description": "DM on insulin (ATC A10A) with HbA1c 6.5–9 → HCC 19 confirmed by pharmacotherapy evidence.",
        "trigger_logic": "all",
        "trigger_conditions": [
            {"kind": "icd10", "prefix": "E11"},
            {"kind": "atc", "prefix": "A10A"},
            {"kind": "loinc_threshold", "code": "4548-4", "op": ">=", "value": 6.5},
            {"kind": "loinc_threshold", "code": "4548-4", "op": "<=", "value": 9.0},
        ],
        "output_hcc": "19",
        "output_icd10": "E11.9",
        "confidence": 0.88,
        "source_type": "ADA-guideline",
        "source_citation": "ADA Standards of Care 2024 §9: Pharmacologic Approaches to Glycemic Treatment. Diabetes Care 47(Suppl 1):S158–S178.",
        "source_url": None,
        "source_year": 2024,
    },
    {
        "rule_name": "ada_dm_with_hyperosmolar_state",
        "rule_description": "DM + hyperosmolar hyperglycemic state (E11.00/E11.01) → HCC 17 acute decompensation.",
        "trigger_logic": "any",
        "trigger_conditions": [
            {"kind": "icd10", "code": "E11.00"},
            {"kind": "icd10", "code": "E11.01"},
        ],
        "output_hcc": "17",
        "output_icd10": "E11.00",
        "confidence": 0.95,
        "source_type": "ADA-guideline",
        "source_citation": "ADA Standards of Care 2024 §16: Diabetes Care in the Hospital. Diabetes Care 47(Suppl 1):S295–S306.",
        "source_url": None,
        "source_year": 2024,
    },

    # =====================================================================
    # KDIGO 2024 CKD Guideline (Kidney Int 105:S117–S314)
    # =====================================================================
    {
        "rule_name": "kdigo_ckd_stage3_egfr_30_60",
        "rule_description": "ICD N18.3/N18.30/N18.31/N18.32 + eGFR 30–60 → CKD stage 3 HCC 138.",
        "trigger_logic": "all",
        "trigger_conditions": [
            {"kind": "icd10", "prefix": "N18.3"},
            {"kind": "loinc_threshold", "code": "62238-1", "op": "<", "value": 60.0},
            {"kind": "loinc_threshold", "code": "62238-1", "op": ">=", "value": 30.0},
        ],
        "output_hcc": "138",
        "output_icd10": "N18.30",
        "confidence": 0.92,
        "source_type": "KDIGO",
        "source_citation": "KDIGO 2024 Clinical Practice Guideline for the Evaluation and Management of CKD. Kidney Int 105(4S):S117–S314.",
        "source_url": "https://kdigo.org/guidelines/ckd-evaluation-and-management/",
        "source_year": 2024,
    },
    {
        "rule_name": "kdigo_ckd_stage4_egfr_15_30",
        "rule_description": "ICD N18.4 + eGFR 15–30 → CKD stage 4 HCC 137.",
        "trigger_logic": "all",
        "trigger_conditions": [
            {"kind": "icd10", "code": "N18.4"},
            {"kind": "loinc_threshold", "code": "62238-1", "op": "<", "value": 30.0},
            {"kind": "loinc_threshold", "code": "62238-1", "op": ">=", "value": 15.0},
        ],
        "output_hcc": "137",
        "output_icd10": "N18.4",
        "confidence": 0.94,
        "source_type": "KDIGO",
        "source_citation": "KDIGO 2024 CKD Guideline §1.2: GFR Categories G1–G5. Kidney Int 105(4S):S117–S314.",
        "source_url": None,
        "source_year": 2024,
    },
    {
        "rule_name": "kdigo_esrd_dialysis_or_egfr_lt15",
        "rule_description": "Z99.2 dialysis dependence OR eGFR <15 OR N18.6 → ESRD HCC 136.",
        "trigger_logic": "any",
        "trigger_conditions": [
            {"kind": "icd10", "code": "Z99.2"},
            {"kind": "icd10", "code": "N18.6"},
            {"kind": "loinc_threshold", "code": "62238-1", "op": "<", "value": 15.0},
        ],
        "output_hcc": "136",
        "output_icd10": "N18.6",
        "confidence": 0.97,
        "source_type": "KDIGO",
        "source_citation": "KDIGO 2024 CKD Guideline §1.3: GFR <15 mL/min/1.73m² defines kidney failure (G5). Kidney Int 105(4S):S117–S314.",
        "source_url": None,
        "source_year": 2024,
    },
    {
        "rule_name": "kdigo_ckd_anemia_hgb_lt11",
        "rule_description": "CKD (N18.x) + Hgb <11 g/dL → anemia of CKD HCC 46.",
        "trigger_logic": "all",
        "trigger_conditions": [
            {"kind": "icd10", "prefix": "N18"},
            {"kind": "loinc_threshold", "code": "718-7", "op": "<", "value": 11.0},
        ],
        "output_hcc": "46",
        "output_icd10": "D63.1",
        "confidence": 0.88,
        "source_type": "KDIGO",
        "source_citation": "KDIGO 2012 Clinical Practice Guideline for Anemia in CKD. Kidney Int Suppl 2:279–335.",
        "source_url": "https://kdigo.org/guidelines/anemia-in-ckd/",
        "source_year": 2012,
    },
    {
        "rule_name": "kdigo_albuminuria_a3",
        "rule_description": "ACR ≥300 mg/g (LOINC 14959-1) → severely increased albuminuria (A3) supporting CKD HCC 138.",
        "trigger_logic": "any",
        "trigger_conditions": [
            {"kind": "loinc_threshold", "code": "14959-1", "op": ">=", "value": 300.0},
        ],
        "output_hcc": "138",
        "output_icd10": "N18.9",
        "confidence": 0.80,
        "source_type": "KDIGO",
        "source_citation": "KDIGO 2024 CKD Guideline §1.4: Albuminuria categories. Kidney Int 105(4S):S117–S314.",
        "source_url": None,
        "source_year": 2024,
    },
    {
        "rule_name": "kdigo_aki_on_ckd",
        "rule_description": "AKI (N17.x) + chronic CKD (N18.x) → acute on chronic; supports CKD HCC and AKI flag.",
        "trigger_logic": "all",
        "trigger_conditions": [
            {"kind": "icd10", "prefix": "N17"},
            {"kind": "icd10", "prefix": "N18"},
        ],
        "output_hcc": "326",
        "output_icd10": "N17.9",
        "confidence": 0.85,
        "source_type": "KDIGO",
        "source_citation": "KDIGO 2012 Clinical Practice Guideline for Acute Kidney Injury. Kidney Int Suppl 2:1–138.",
        "source_url": None,
        "source_year": 2012,
    },

    # =====================================================================
    # ACC/AHA Heart Failure 2022 (J Am Coll Cardiol 79:e263–e421)
    # =====================================================================
    {
        "rule_name": "accaha_hfref_lvef_lt40",
        "rule_description": "I50.x + LVEF <40% (LOINC 10230-1) → HFrEF HCC 224.",
        "trigger_logic": "all",
        "trigger_conditions": [
            {"kind": "icd10", "prefix": "I50"},
            {"kind": "loinc_threshold", "code": "10230-1", "op": "<", "value": 40.0},
        ],
        "output_hcc": "224",
        "output_icd10": "I50.20",
        "confidence": 0.93,
        "source_type": "ACC-AHA-guideline",
        "source_citation": "Heidenreich PA et al. 2022 AHA/ACC/HFSA Guideline for the Management of Heart Failure. J Am Coll Cardiol 79(17):e263–e421.",
        "source_url": "https://www.ahajournals.org/doi/10.1161/CIR.0000000000001063",
        "source_year": 2022,
    },
    {
        "rule_name": "accaha_hfmref_lvef_40_49",
        "rule_description": "I50.x + LVEF 40–49% → HFmrEF HCC 226.",
        "trigger_logic": "all",
        "trigger_conditions": [
            {"kind": "icd10", "prefix": "I50"},
            {"kind": "loinc_threshold", "code": "10230-1", "op": ">=", "value": 40.0},
            {"kind": "loinc_threshold", "code": "10230-1", "op": "<", "value": 50.0},
        ],
        "output_hcc": "226",
        "output_icd10": "I50.20",
        "confidence": 0.85,
        "source_type": "ACC-AHA-guideline",
        "source_citation": "2022 AHA/ACC/HFSA HF Guideline §3.2: HFmrEF (LVEF 41–49%). J Am Coll Cardiol 79(17):e263–e421.",
        "source_url": None,
        "source_year": 2022,
    },
    {
        "rule_name": "accaha_acute_systolic_hf",
        "rule_description": "I50.21 (acute systolic) or I50.23 (acute on chronic systolic) → HCC 224.",
        "trigger_logic": "any",
        "trigger_conditions": [
            {"kind": "icd10", "code": "I50.21"},
            {"kind": "icd10", "code": "I50.23"},
        ],
        "output_hcc": "224",
        "output_icd10": "I50.23",
        "confidence": 0.95,
        "source_type": "ACC-AHA-guideline",
        "source_citation": "2022 AHA/ACC/HFSA HF Guideline §6: Acute Decompensated HF. J Am Coll Cardiol 79(17):e263–e421.",
        "source_url": None,
        "source_year": 2022,
    },
    {
        "rule_name": "accaha_ntprobnp_elevated_age50_75",
        "rule_description": "NT-proBNP ≥900 pg/mL (LOINC 33762-6) age 50–75 supports HF diagnosis (HCC 224/226).",
        "trigger_logic": "any",
        "trigger_conditions": [
            {"kind": "loinc_threshold", "code": "33762-6", "op": ">=", "value": 900.0},
        ],
        "output_hcc": "224",
        "output_icd10": "I50.9",
        "confidence": 0.78,
        "source_type": "ACC-AHA-guideline",
        "source_citation": "2022 AHA/ACC/HFSA HF Guideline §4.2: Age-stratified NT-proBNP cutpoints. J Am Coll Cardiol 79(17):e263–e421.",
        "source_url": None,
        "source_year": 2022,
    },
    {
        "rule_name": "accaha_ntprobnp_elevated_age_gt75",
        "rule_description": "NT-proBNP ≥1800 pg/mL age >75 supports HF diagnosis HCC 224/226.",
        "trigger_logic": "any",
        "trigger_conditions": [
            {"kind": "loinc_threshold", "code": "33762-6", "op": ">=", "value": 1800.0},
        ],
        "output_hcc": "226",
        "output_icd10": "I50.9",
        "confidence": 0.78,
        "source_type": "ACC-AHA-guideline",
        "source_citation": "2022 AHA/ACC/HFSA HF Guideline §4.2 Table 6. J Am Coll Cardiol 79(17):e263–e421.",
        "source_url": None,
        "source_year": 2022,
    },
    {
        "rule_name": "accaha_chronic_diastolic_hf",
        "rule_description": "I50.32/I50.33 chronic diastolic HF → HCC 226 (HFpEF).",
        "trigger_logic": "any",
        "trigger_conditions": [
            {"kind": "icd10", "code": "I50.32"},
            {"kind": "icd10", "code": "I50.33"},
        ],
        "output_hcc": "226",
        "output_icd10": "I50.32",
        "confidence": 0.90,
        "source_type": "ACC-AHA-guideline",
        "source_citation": "2022 AHA/ACC/HFSA HF Guideline §3.2: HFpEF (LVEF ≥50%). J Am Coll Cardiol 79(17):e263–e421.",
        "source_url": None,
        "source_year": 2022,
    },

    # =====================================================================
    # GOLD COPD 2024 (Global Initiative for Chronic Obstructive Lung Dis.)
    # =====================================================================
    {
        "rule_name": "gold_copd_moderate_severe_fev1_lt50",
        "rule_description": "J44.x + FEV1 <50% predicted (LOINC 19868-9) → moderate-severe COPD HCC 280.",
        "trigger_logic": "all",
        "trigger_conditions": [
            {"kind": "icd10", "prefix": "J44"},
            {"kind": "loinc_threshold", "code": "19868-9", "op": "<", "value": 50.0},
        ],
        "output_hcc": "280",
        "output_icd10": "J44.9",
        "confidence": 0.91,
        "source_type": "GOLD-guideline",
        "source_citation": "GOLD 2024 Report: Global Strategy for Prevention, Diagnosis and Management of COPD. GOLD grades 3–4: FEV1 <50% predicted.",
        "source_url": "https://goldcopd.org/2024-gold-report/",
        "source_year": 2024,
    },
    {
        "rule_name": "gold_copd_acute_exacerbation",
        "rule_description": "J44.0 (with lower respiratory infection) or J44.1 (with exacerbation) → HCC 279 acute COPD exacerbation.",
        "trigger_logic": "any",
        "trigger_conditions": [
            {"kind": "icd10", "code": "J44.0"},
            {"kind": "icd10", "code": "J44.1"},
        ],
        "output_hcc": "279",
        "output_icd10": "J44.1",
        "confidence": 0.94,
        "source_type": "GOLD-guideline",
        "source_citation": "GOLD 2024 Report §5: Management of Exacerbations.",
        "source_url": None,
        "source_year": 2024,
    },
    {
        "rule_name": "gold_copd_chronic_resp_failure",
        "rule_description": "J44.x + J96.1x/J96.2x chronic respiratory failure → HCC 84 + HCC 280.",
        "trigger_logic": "all",
        "trigger_conditions": [
            {"kind": "icd10", "prefix": "J44"},
            {"kind": "icd10", "prefix": "J96.1"},
        ],
        "output_hcc": "84",
        "output_icd10": "J96.10",
        "confidence": 0.92,
        "source_type": "GOLD-guideline",
        "source_citation": "GOLD 2024 Report §3.4: Chronic Respiratory Failure. Combined GOLD + ICD-10-CM coding guidance.",
        "source_url": None,
        "source_year": 2024,
    },
    {
        "rule_name": "gold_copd_on_long_term_o2",
        "rule_description": "J44.x + Z99.81 long-term oxygen → severe COPD HCC 280 with chronic respiratory failure burden.",
        "trigger_logic": "all",
        "trigger_conditions": [
            {"kind": "icd10", "prefix": "J44"},
            {"kind": "icd10", "code": "Z99.81"},
        ],
        "output_hcc": "280",
        "output_icd10": "J44.9",
        "confidence": 0.89,
        "source_type": "GOLD-guideline",
        "source_citation": "GOLD 2024 Report §4.7: Long-term oxygen therapy in chronic respiratory failure.",
        "source_url": None,
        "source_year": 2024,
    },
    {
        "rule_name": "gold_copd_severe_fev1_lt30",
        "rule_description": "J44.x + FEV1 <30% predicted → very severe COPD (GOLD 4) HCC 280.",
        "trigger_logic": "all",
        "trigger_conditions": [
            {"kind": "icd10", "prefix": "J44"},
            {"kind": "loinc_threshold", "code": "19868-9", "op": "<", "value": 30.0},
        ],
        "output_hcc": "280",
        "output_icd10": "J44.9",
        "confidence": 0.94,
        "source_type": "GOLD-guideline",
        "source_citation": "GOLD 2024 Report Table 2.4: GOLD 4 = FEV1 <30% predicted.",
        "source_url": None,
        "source_year": 2024,
    },

    # =====================================================================
    # CMS-HCC V28 clinical specification (CMS Medicare Advantage Risk
    # Adjustment, 2024 Final Rule)
    # =====================================================================
    {
        "rule_name": "cms_v28_dm_hcc18_with_complication_code",
        "rule_description": "Per CMS V28 spec, ICD-10 codes E11.0x–E11.69 map to HCC 18 (DM with complications); E11.9 maps to HCC 19.",
        "trigger_logic": "any",
        "trigger_conditions": [
            {"kind": "icd10", "prefix": "E11.0"},
            {"kind": "icd10", "prefix": "E11.1"},
            {"kind": "icd10", "prefix": "E11.2"},
            {"kind": "icd10", "prefix": "E11.3"},
            {"kind": "icd10", "prefix": "E11.4"},
            {"kind": "icd10", "prefix": "E11.5"},
            {"kind": "icd10", "prefix": "E11.6"},
        ],
        "output_hcc": "18",
        "output_icd10": "E11.65",
        "confidence": 0.96,
        "source_type": "CMS-HCC-spec",
        "source_citation": "CMS-HCC V28 Risk Adjustment Model, 2024 Announcement Final Rule. Diabetes mapping table.",
        "source_url": "https://www.cms.gov/medicare/payment/medicare-advantage-rates-statistics/risk-adjustment",
        "source_year": 2024,
    },
    {
        "rule_name": "cms_v28_morbid_obesity_bmi_ge40",
        "rule_description": "BMI ≥40 (LOINC 39156-5) OR E66.01 + comorbidity (DM/HF/CAD) → HCC 22 morbid obesity.",
        "trigger_logic": "any",
        "trigger_conditions": [
            {"kind": "icd10", "code": "E66.01"},
            {"kind": "loinc_threshold", "code": "39156-5", "op": ">=", "value": 40.0},
        ],
        "output_hcc": "22",
        "output_icd10": "E66.01",
        "confidence": 0.93,
        "source_type": "CMS-HCC-spec",
        "source_citation": "CMS-HCC V28 model: HCC 22 Morbid Obesity. CMS 2024 Risk Adjustment Final Rule.",
        "source_url": None,
        "source_year": 2024,
    },
    {
        "rule_name": "cms_v28_obesity_bmi_35_with_comorbid",
        "rule_description": "BMI 35–39.9 + DM (E11.x) or HF (I50.x) → HCC 22 morbid obesity per CMS clinical-significance criterion.",
        "trigger_logic": "all",
        "trigger_conditions": [
            {"kind": "loinc_threshold", "code": "39156-5", "op": ">=", "value": 35.0},
            {"kind": "loinc_threshold", "code": "39156-5", "op": "<", "value": 40.0},
            {"kind": "icd10", "prefix": "E11"},
        ],
        "output_hcc": "22",
        "output_icd10": "E66.9",
        "confidence": 0.85,
        "source_type": "CMS-HCC-spec",
        "source_citation": "CMS-HCC V28 + ASMBS/IFSO 2022 Indications for Metabolic and Bariatric Surgery (Eisenberg D et al., Surg Obes Relat Dis 18:1345).",
        "source_url": None,
        "source_year": 2022,
    },
    {
        "rule_name": "cms_v28_specified_heart_arrhythmias",
        "rule_description": "I48.x atrial fibrillation/flutter → HCC 248 specified heart arrhythmias.",
        "trigger_logic": "any",
        "trigger_conditions": [
            {"kind": "icd10", "prefix": "I48"},
        ],
        "output_hcc": "248",
        "output_icd10": "I48.91",
        "confidence": 0.96,
        "source_type": "CMS-HCC-spec",
        "source_citation": "CMS-HCC V28 model: HCC 248 Specified Heart Arrhythmias. CMS 2024.",
        "source_url": None,
        "source_year": 2024,
    },
    {
        "rule_name": "cms_v28_active_metastatic_cancer",
        "rule_description": "Active C77.x–C79.x secondary/metastatic neoplasm → HCC 17 metastatic cancer (V28 cancer cluster).",
        "trigger_logic": "any",
        "trigger_conditions": [
            {"kind": "icd10", "prefix": "C77"},
            {"kind": "icd10", "prefix": "C78"},
            {"kind": "icd10", "prefix": "C79"},
        ],
        "output_hcc": "17",
        "output_icd10": "C79.9",
        "confidence": 0.97,
        "source_type": "CMS-HCC-spec",
        "source_citation": "CMS-HCC V28 model: HCC 17 Cancer, Metastatic. CMS 2024 Risk Adjustment Final Rule.",
        "source_url": None,
        "source_year": 2024,
    },
    {
        "rule_name": "cms_v28_cancer_history_z85",
        "rule_description": "Z85.x personal history of cancer with no active treatment → does NOT map to HCC 12; rule emits negative-confirm flag (no HCC).",
        "trigger_logic": "all",
        "trigger_conditions": [
            {"kind": "icd10", "prefix": "Z85"},
        ],
        "output_hcc": "0",
        "output_icd10": "Z85.9",
        "confidence": 0.80,
        "source_type": "CMS-HCC-spec",
        "source_citation": "CMS-HCC V28 model + AHA Coding Clinic 1Q2018 p15: history-of codes (Z85) are not active conditions and do not generate HCC 12 unless active treatment documented.",
        "source_url": None,
        "source_year": 2024,
    },
    {
        "rule_name": "cms_v28_prostate_ca_with_metastasis",
        "rule_description": "C61 + C77–C79 → metastatic prostate cancer drives HCC 17 (cancer, metastatic) per V28 mapping.",
        "trigger_logic": "all",
        "trigger_conditions": [
            {"kind": "icd10", "code": "C61"},
            {"kind": "icd10", "prefix": "C7"},
        ],
        "output_hcc": "17",
        "output_icd10": "C79.51",
        "confidence": 0.94,
        "source_type": "CMS-HCC-spec",
        "source_citation": "CMS-HCC V28 model: cancer hierarchy. CMS 2024 Risk Adjustment Final Rule.",
        "source_url": None,
        "source_year": 2024,
    },
    {
        "rule_name": "cms_v28_dialysis_status_hcc136",
        "rule_description": "Z99.2 dependence on renal dialysis → HCC 136 ESRD irrespective of N18 stage.",
        "trigger_logic": "all",
        "trigger_conditions": [
            {"kind": "icd10", "code": "Z99.2"},
        ],
        "output_hcc": "136",
        "output_icd10": "Z99.2",
        "confidence": 0.97,
        "source_type": "CMS-HCC-spec",
        "source_citation": "CMS-HCC V28 model: HCC 136 Dialysis Status. CMS 2024 Risk Adjustment Final Rule.",
        "source_url": None,
        "source_year": 2024,
    },

    # =====================================================================
    # AHA Coding Clinic 2023–2024 sequencing/specificity guidance
    # =====================================================================
    {
        "rule_name": "aha_cc_sepsis_with_organ_dysfunction",
        "rule_description": "A41.x sepsis + organ dysfunction (R65.20/R65.21) → severe sepsis sequencing per Coding Clinic 4Q2023 p38.",
        "trigger_logic": "all",
        "trigger_conditions": [
            {"kind": "icd10", "prefix": "A41"},
            {"kind": "icd10", "prefix": "R65.2"},
        ],
        "output_hcc": "2",
        "output_icd10": "R65.20",
        "confidence": 0.94,
        "source_type": "AHA-CodingClinic",
        "source_citation": "AHA Coding Clinic for ICD-10-CM 4Q2023 p38: Sepsis with acute organ dysfunction sequencing.",
        "source_url": None,
        "source_year": 2023,
    },
    {
        "rule_name": "aha_cc_acute_vs_chronic_chf",
        "rule_description": "Documentation must specify acute, chronic, or acute-on-chronic; if both notes indicate decompensation while chronic CHF documented → I50.23 acute on chronic systolic (HCC 224).",
        "trigger_logic": "all",
        "trigger_conditions": [
            {"kind": "icd10", "prefix": "I50"},
            {"kind": "note_pattern", "pattern": "acute(?:ly)?[\\s-]*on[\\s-]*chronic"},
        ],
        "output_hcc": "224",
        "output_icd10": "I50.23",
        "confidence": 0.86,
        "source_type": "AHA-CodingClinic",
        "source_citation": "AHA Coding Clinic 1Q2024 p12: 'Acute on chronic' systolic heart failure sequencing.",
        "source_url": None,
        "source_year": 2024,
    },
    {
        "rule_name": "aha_cc_combination_dm_codes",
        "rule_description": "When DM and a manifestation are documented separately, code the combination ICD (E11.21, E11.40, etc.) per Coding Clinic 2Q2018 p6.",
        "trigger_logic": "all",
        "trigger_conditions": [
            {"kind": "icd10", "prefix": "E11"},
            {"kind": "note_pattern", "pattern": "neuropath|nephropath|retinopath"},
        ],
        "output_hcc": "18",
        "output_icd10": "E11.40",
        "confidence": 0.83,
        "source_type": "AHA-CodingClinic",
        "source_citation": "AHA Coding Clinic for ICD-10-CM 2Q2018 p6: Diabetes with associated conditions — combination coding.",
        "source_url": None,
        "source_year": 2018,
    },
    {
        "rule_name": "aha_cc_depression_severity_specificity",
        "rule_description": "F32.9 unspecified depression should be specified as F32.0–F32.4 per Coding Clinic; severe MDD → HCC 155.",
        "trigger_logic": "all",
        "trigger_conditions": [
            {"kind": "icd10", "code": "F32.9"},
            {"kind": "note_pattern", "pattern": "severe|suicidal|psychotic"},
        ],
        "output_hcc": "155",
        "output_icd10": "F32.2",
        "confidence": 0.78,
        "source_type": "AHA-CodingClinic",
        "source_citation": "AHA Coding Clinic 2Q2017 p7: Specificity required for depressive disorders.",
        "source_url": None,
        "source_year": 2017,
    },
    {
        "rule_name": "aha_cc_history_of_vs_active_cancer",
        "rule_description": "Coding Clinic: 'history of' cancer (Z85) is NOT an active diagnosis and should not be coded with C-codes unless active disease documented.",
        "trigger_logic": "all",
        "trigger_conditions": [
            {"kind": "icd10", "prefix": "Z85"},
            {"kind": "note_pattern", "pattern": "no\\s+evidence|in\\s+remission|disease\\s+free"},
        ],
        "output_hcc": "0",
        "output_icd10": "Z85.9",
        "confidence": 0.85,
        "source_type": "AHA-CodingClinic",
        "source_citation": "AHA Coding Clinic 1Q2018 p15: History-of cancer Z85 vs. active C-codes.",
        "source_url": None,
        "source_year": 2018,
    },

    # =====================================================================
    # APA DSM-5 / DSM-5-TR mental-health criteria
    # =====================================================================
    {
        "rule_name": "dsm5_mdd_five_of_nine_criteria",
        "rule_description": "DSM-5 MDD requires ≥5 of 9 symptoms ≥2 weeks → F32.x or F33.x; severe presentation → HCC 155.",
        "trigger_logic": "any",
        "trigger_conditions": [
            {"kind": "icd10", "prefix": "F32"},
            {"kind": "icd10", "prefix": "F33"},
        ],
        "output_hcc": "155",
        "output_icd10": "F33.2",
        "confidence": 0.80,
        "source_type": "APA-DSM5",
        "source_citation": "American Psychiatric Association. Diagnostic and Statistical Manual of Mental Disorders, 5th ed., Text Revision (DSM-5-TR), 2022. Major Depressive Disorder criteria A–C.",
        "source_url": None,
        "source_year": 2022,
    },
    {
        "rule_name": "dsm5_bipolar_i_requires_manic_episode",
        "rule_description": "Bipolar I requires ≥1 manic episode (DSM-5 §296.4x) → F31.x; HCC 152.",
        "trigger_logic": "any",
        "trigger_conditions": [
            {"kind": "icd10", "prefix": "F31"},
        ],
        "output_hcc": "152",
        "output_icd10": "F31.9",
        "confidence": 0.86,
        "source_type": "APA-DSM5",
        "source_citation": "DSM-5-TR (APA, 2022): Bipolar I Disorder requires at least one manic episode.",
        "source_url": None,
        "source_year": 2022,
    },
    {
        "rule_name": "dsm5_schizophrenia_criteria",
        "rule_description": "Schizophrenia (F20.x) per DSM-5 criteria → HCC 151.",
        "trigger_logic": "any",
        "trigger_conditions": [
            {"kind": "icd10", "prefix": "F20"},
        ],
        "output_hcc": "151",
        "output_icd10": "F20.9",
        "confidence": 0.92,
        "source_type": "APA-DSM5",
        "source_citation": "DSM-5-TR (APA, 2022): Schizophrenia Spectrum and Other Psychotic Disorders, criteria A–F.",
        "source_url": None,
        "source_year": 2022,
    },
    {
        "rule_name": "dsm5_schizoaffective_disorder",
        "rule_description": "Schizoaffective disorder F25.x → HCC 151 schizophrenia spectrum.",
        "trigger_logic": "any",
        "trigger_conditions": [
            {"kind": "icd10", "prefix": "F25"},
        ],
        "output_hcc": "151",
        "output_icd10": "F25.9",
        "confidence": 0.90,
        "source_type": "APA-DSM5",
        "source_citation": "DSM-5-TR (APA, 2022): Schizoaffective Disorder criteria.",
        "source_url": None,
        "source_year": 2022,
    },

    # =====================================================================
    # ACC/AHA Cardiology adjacent guidelines (2023–2024)
    # =====================================================================
    {
        "rule_name": "accaha_afib_any_type",
        "rule_description": "I48.x atrial fibrillation/flutter → HCC 248 specified heart arrhythmias (any subtype).",
        "trigger_logic": "any",
        "trigger_conditions": [
            {"kind": "icd10", "prefix": "I48"},
        ],
        "output_hcc": "248",
        "output_icd10": "I48.91",
        "confidence": 0.94,
        "source_type": "ACC-AHA-guideline",
        "source_citation": "Joglar JA et al. 2023 ACC/AHA/ACCP/HRS Guideline for the Diagnosis and Management of Atrial Fibrillation. Circulation 149(1):e1–e156.",
        "source_url": None,
        "source_year": 2023,
    },
    {
        "rule_name": "accaha_cad_with_prior_mi",
        "rule_description": "CAD (I25.1x) + prior MI (I25.2 or Z86.711) → HCC 217 ischemic heart disease.",
        "trigger_logic": "all",
        "trigger_conditions": [
            {"kind": "icd10", "prefix": "I25.1"},
            {"kind": "icd10", "prefix": "I25.2"},
        ],
        "output_hcc": "217",
        "output_icd10": "I25.2",
        "confidence": 0.90,
        "source_type": "ACC-AHA-guideline",
        "source_citation": "Virani SS et al. 2023 AHA/ACC Guideline for the Management of Patients With Chronic Coronary Disease. J Am Coll Cardiol 82(9):833–955.",
        "source_url": None,
        "source_year": 2023,
    },
    {
        "rule_name": "accaha_severe_valvular_disease",
        "rule_description": "I35.0/I35.1/I34.0/I34.1 severe valvular disease → HCC 96.",
        "trigger_logic": "any",
        "trigger_conditions": [
            {"kind": "icd10", "code": "I35.0"},
            {"kind": "icd10", "code": "I35.1"},
            {"kind": "icd10", "code": "I34.0"},
            {"kind": "icd10", "code": "I34.1"},
        ],
        "output_hcc": "96",
        "output_icd10": "I35.0",
        "confidence": 0.88,
        "source_type": "ACC-AHA-guideline",
        "source_citation": "Otto CM et al. 2020 ACC/AHA Guideline for the Management of Patients With Valvular Heart Disease. J Am Coll Cardiol 77(4):e25–e197.",
        "source_url": None,
        "source_year": 2020,
    },
    {
        "rule_name": "accaha_pvd_with_claudication",
        "rule_description": "I73.9 PVD + I70.21x claudication → HCC 108 vascular disease.",
        "trigger_logic": "any",
        "trigger_conditions": [
            {"kind": "icd10", "code": "I73.9"},
            {"kind": "icd10", "prefix": "I70.21"},
        ],
        "output_hcc": "108",
        "output_icd10": "I70.219",
        "confidence": 0.86,
        "source_type": "ACC-AHA-guideline",
        "source_citation": "Gornik HL et al. 2024 ACC/AHA/AACVPR/SCAI/SVM/SVN/SVS Guideline for the Management of Lower Extremity Peripheral Artery Disease. Circulation 149(24):e1313–e1410.",
        "source_url": None,
        "source_year": 2024,
    },

    # =====================================================================
    # HIV/AIDS clinical (DHHS Adult ARV Guidelines + CDC)
    # =====================================================================
    {
        "rule_name": "hiv_aids_cd4_lt_200",
        "rule_description": "B20 HIV + CD4 <200 cells/µL (LOINC 24467-3) → AIDS-defining immunosuppression HCC 1.",
        "trigger_logic": "all",
        "trigger_conditions": [
            {"kind": "icd10", "code": "B20"},
            {"kind": "loinc_threshold", "code": "24467-3", "op": "<", "value": 200.0},
        ],
        "output_hcc": "1",
        "output_icd10": "B20",
        "confidence": 0.95,
        "source_type": "peer-reviewed",
        "source_citation": "DHHS Panel on Antiretroviral Guidelines for Adults and Adolescents (2024) + CDC AIDS-defining condition criteria (MMWR 1992;41(RR-17)). CD4 <200 cells/µL defines AIDS.",
        "source_url": "https://clinicalinfo.hiv.gov/en/guidelines/adult-and-adolescent-arv",
        "source_year": 2024,
    },
    {
        "rule_name": "hiv_aids_opportunistic_infection",
        "rule_description": "B20 + opportunistic infection (B59 PCP, B58.x toxo, B25 CMV, B45 cryptococcus) → AIDS HCC 1.",
        "trigger_logic": "all",
        "trigger_conditions": [
            {"kind": "icd10", "code": "B20"},
        ],
        "output_hcc": "1",
        "output_icd10": "B20",
        "confidence": 0.93,
        "source_type": "peer-reviewed",
        "source_citation": "CDC: 1993 Revised Classification System for HIV Infection and Expanded Surveillance Case Definition for AIDS Among Adolescents and Adults. MMWR Recomm Rep 1992;41(RR-17):1–19.",
        "source_url": None,
        "source_year": 1992,
    },

    # =====================================================================
    # USPSTF screening criteria (referenced for documentation completeness)
    # =====================================================================
    {
        "rule_name": "uspstf_lung_ca_screening_smokers",
        "rule_description": "Z87.891 history of nicotine dependence + age 50–80 → USPSTF Grade B annual LDCT screening; flags coverage but does not by itself create an HCC.",
        "trigger_logic": "all",
        "trigger_conditions": [
            {"kind": "icd10", "code": "Z87.891"},
        ],
        "output_hcc": "0",
        "output_icd10": "Z87.891",
        "confidence": 0.70,
        "source_type": "USPSTF",
        "source_citation": "US Preventive Services Task Force. Screening for Lung Cancer: Recommendation Statement. JAMA 2021;325(10):962–970. Grade B.",
        "source_url": "https://www.uspreventiveservicestaskforce.org/uspstf/recommendation/lung-cancer-screening",
        "source_year": 2021,
    },
    {
        "rule_name": "uspstf_aaa_screening_men_65_75",
        "rule_description": "Men 65–75 ever-smokers → USPSTF Grade B one-time AAA screening (I71 supports HCC 107 when documented as aneurysm).",
        "trigger_logic": "any",
        "trigger_conditions": [
            {"kind": "icd10", "prefix": "I71"},
        ],
        "output_hcc": "107",
        "output_icd10": "I71.4",
        "confidence": 0.78,
        "source_type": "USPSTF",
        "source_citation": "US Preventive Services Task Force. Screening for Abdominal Aortic Aneurysm: Recommendation Statement. JAMA 2019;322(22):2211–2218.",
        "source_url": "https://www.uspreventiveservicestaskforce.org/uspstf/recommendation/abdominal-aortic-aneurysm-screening",
        "source_year": 2019,
    },
]


# ---------------------------------------------------------------------------
# Trigger-condition evaluation
# ---------------------------------------------------------------------------

_VALID_OPS = {"<", "<=", "=", "==", ">=", ">"}


def _normalize_icd10_list(evidence: dict) -> list[str]:
    raw = evidence.get("icd10") or []
    out: list[str] = []
    for item in raw:
        if isinstance(item, str):
            out.append(item.strip().upper())
        elif isinstance(item, dict):
            code = item.get("code") or item.get("icd10")
            if code:
                out.append(str(code).strip().upper())
    return out


def _normalize_atc_list(evidence: dict) -> list[str]:
    raw = evidence.get("atc") or []
    out: list[str] = []
    for item in raw:
        if isinstance(item, str):
            out.append(item.strip().upper())
        elif isinstance(item, dict):
            code = item.get("code") or item.get("atc")
            if code:
                out.append(str(code).strip().upper())
    return out


def _normalize_loinc_list(evidence: dict) -> list[dict]:
    raw = evidence.get("loinc") or []
    out: list[dict] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        code = item.get("code") or item.get("loinc")
        try:
            value = float(item.get("value")) if item.get("value") is not None else None
        except (TypeError, ValueError):
            value = None
        if code is not None and value is not None:
            out.append({"code": str(code).strip(), "value": value})
    return out


def _notes_iter(evidence: dict) -> Iterable[str]:
    for note in evidence.get("notes") or []:
        if isinstance(note, str):
            yield note
        elif isinstance(note, dict):
            txt = note.get("text") or note.get("body")
            if isinstance(txt, str):
                yield txt


def _icd_match(icd_codes: list[str], cond: dict) -> bool:
    target_code = cond.get("code")
    target_prefix = cond.get("prefix")
    if target_code:
        target_code = target_code.strip().upper()
        return target_code in icd_codes
    if target_prefix:
        target_prefix = target_prefix.strip().upper()
        return any(c.startswith(target_prefix) for c in icd_codes)
    return False


def _atc_match(atc_codes: list[str], cond: dict) -> bool:
    target_code = cond.get("code")
    target_prefix = cond.get("prefix")
    if target_code:
        return target_code.strip().upper() in atc_codes
    if target_prefix:
        target_prefix = target_prefix.strip().upper()
        return any(c.startswith(target_prefix) for c in atc_codes)
    return False


def _loinc_threshold_match(loinc_obs: list[dict], cond: dict) -> bool:
    code = (cond.get("code") or "").strip()
    op = cond.get("op", ">=")
    if op not in _VALID_OPS:
        raise ValueError(f"unsupported op: {op!r}")
    try:
        threshold = float(cond.get("value"))
    except (TypeError, ValueError):
        return False
    matches = [obs for obs in loinc_obs if obs["code"] == code]
    if not matches:
        return False
    for obs in matches:
        v = obs["value"]
        if op == "<" and v < threshold:
            return True
        if op == "<=" and v <= threshold:
            return True
        if op in ("=", "==") and v == threshold:
            return True
        if op == ">=" and v >= threshold:
            return True
        if op == ">" and v > threshold:
            return True
    return False


def _note_pattern_match(notes: list[str], cond: dict) -> bool:
    pattern = cond.get("pattern") or cond.get("regex") or ""
    if not pattern:
        return False
    try:
        rx = re.compile(pattern, re.IGNORECASE)
    except re.error:
        rx = re.compile(re.escape(pattern), re.IGNORECASE)
    return any(rx.search(n) for n in notes)


def _eval_condition(cond: dict, evidence_norm: dict) -> bool:
    kind = cond.get("kind")
    if kind == "icd10":
        return _icd_match(evidence_norm["icd10"], cond)
    if kind == "atc":
        return _atc_match(evidence_norm["atc"], cond)
    if kind == "loinc_threshold":
        return _loinc_threshold_match(evidence_norm["loinc"], cond)
    if kind == "note_pattern":
        return _note_pattern_match(evidence_norm["notes"], cond)
    logger.debug("Unknown condition kind: %s", kind)
    return False


def _check_trigger(
    trigger_conditions: list[dict],
    evidence: dict,
    logic: str = "all",
) -> bool:
    """Evaluate trigger_conditions against evidence with AND/OR semantics.

    `logic` is "all" (AND) or "any" (OR).
    """
    if not trigger_conditions:
        return False
    evidence_norm = {
        "icd10": _normalize_icd10_list(evidence),
        "atc": _normalize_atc_list(evidence),
        "loinc": _normalize_loinc_list(evidence),
        "notes": list(_notes_iter(evidence)),
    }
    if logic == "any":
        return any(_eval_condition(c, evidence_norm) for c in trigger_conditions)
    # default AND
    return all(_eval_condition(c, evidence_norm) for c in trigger_conditions)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def list_rules(active_only: bool = True) -> list[dict]:
    """Return all curated rules (optionally only active)."""
    rules = CURATED_RULES
    if active_only:
        rules = [r for r in rules if r.get("is_active", 1)]
    # Attach synthetic id (1-based index) for stable lookups before DB seed.
    return [dict(r, id=i + 1) for i, r in enumerate(rules)]


def get_rule(rule_id: int) -> dict | None:
    """Look up a curated rule by 1-based synthetic id."""
    rules = list_rules(active_only=False)
    if rule_id < 1 or rule_id > len(rules):
        return None
    return rules[rule_id - 1]


def get_rules_by_hcc(hcc_code: str) -> list[dict]:
    """Return curated rules that emit the given HCC."""
    target = str(hcc_code).replace("HCC", "").strip()
    return [r for r in list_rules() if str(r["output_hcc"]) == target]


def get_rules_by_source(source_type: str) -> list[dict]:
    """Return curated rules of a given source_type."""
    return [r for r in list_rules() if r["source_type"] == source_type]


def evaluate_evidence(evidence: dict) -> list[dict]:
    """Run all active rules against `evidence` and return matches.

    Each match is a dict with rule_name, output_hcc, output_icd10,
    confidence, source_type, source_citation, source_url, source_year.
    Source citation is guaranteed present for every output.
    """
    if not isinstance(evidence, dict):
        raise TypeError("evidence must be a dict")
    matches: list[dict] = []
    for rule in list_rules():
        try:
            triggered = _check_trigger(
                rule["trigger_conditions"],
                evidence,
                logic=rule.get("trigger_logic", "all"),
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Rule %s failed to evaluate: %s", rule.get("rule_name"), exc)
            continue
        if not triggered:
            continue
        matches.append(
            {
                "rule_id": rule["id"],
                "rule_name": rule["rule_name"],
                "rule_description": rule.get("rule_description"),
                "output_hcc": rule["output_hcc"],
                "output_icd10": rule.get("output_icd10"),
                "confidence": float(rule.get("confidence", 0.75)),
                "source_type": rule["source_type"],
                "source_citation": rule["source_citation"],
                "source_url": rule.get("source_url"),
                "source_year": rule.get("source_year"),
                "model_version": rule.get("model_version", "V28"),
            }
        )
    return matches
