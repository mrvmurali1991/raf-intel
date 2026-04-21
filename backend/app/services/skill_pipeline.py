# DISCLAIMER: This module performs clinical analysis using the CMS-HCC V28
# model via the hccinfhir library, which is a third-party open-source
# implementation of the CMS-HCC model. It is NOT validated or endorsed by CMS.
# Results should be verified against the official CMS SAS software before use
# in payment determinations. This tool is designed for clinical analytics, gap
# identification, and prospective risk assessment — not for payment submission.

"""
Skill-based Clinical Analysis Pipeline.

Single Gemini call with function-calling (skills/tools) for:
  - HCC lookup from CMS V28 crosswalk
  - ICD-10 validation

Gemini sees the full clinical note, extracts diagnoses, calls skills
to validate ICD codes and get HCC mappings, then returns complete
structured results with MEAT evidence — all in ONE conversation.

Note: RAF scores produced by this pipeline are estimates based on the
hccinfhir library (third-party open-source CMS-HCC V28 implementation).
Not CMS-validated. For informational purposes only — verify against
official CMS SAS software for payment accuracy.
"""

import json
import logging
import os
import time
from typing import Any

from app.config import settings
from app.services.api_rate_limiter import gemini_limiter
from app.services.circuit_breaker import gemini_breaker
from app.services.icd_validator import validate_code_set

logger = logging.getLogger(__name__)

# Maximum characters of the clinical note submitted to Gemini.
# Raise or lower via the MAX_NOTE_CHARS environment variable.
_MAX_NOTE_CHARS = int(os.getenv("MAX_NOTE_CHARS", "15000"))

# ---------------------------------------------------------------------------
# Tool definitions for Gemini function calling
# ---------------------------------------------------------------------------

TOOLS = [
    {
        "functionDeclarations": [
            {
                "name": "lookup_hcc",
                "description": "Look up the CMS-HCC V28 risk adjustment mapping for an ICD-10-CM code. Returns the HCC code, label, and RAF weight coefficient. Returns null if the code is not HCC-relevant (not risk-adjusting).",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "icd10_code": {
                            "type": "string",
                            "description": "ICD-10-CM code, e.g. E11.22, F32.9, I10"
                        }
                    },
                    "required": ["icd10_code"]
                }
            },
            {
                "name": "check_medication_gaps",
                "description": "Check if any medications suggest undocumented conditions. Pass a medication name and get back conditions it typically treats that should be coded.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "medication": {
                            "type": "string",
                            "description": "Medication name, e.g. metformin, warfarin, donepezil"
                        }
                    },
                    "required": ["medication"]
                }
            },
            {
                "name": "get_raf_demographic_base",
                "description": "Get the CMS-HCC V28 demographic base rate for a patient based on age and sex.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "age": {"type": "integer", "description": "Patient age in years"},
                        "sex": {"type": "string", "description": "Male or Female"}
                    },
                    "required": ["age", "sex"]
                }
            },
            {
                "name": "validate_icd10",
                "description": "Validate an ICD-10-CM code and get its official description. Returns whether the code exists, is billable (leaf node), the full description, and if not billable, suggests more specific child codes. ALWAYS call this to verify your ICD-10 codes are valid and billable before including them in diagnoses.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "icd10_code": {
                            "type": "string",
                            "description": "ICD-10-CM code to validate, e.g. E11.22, F32.9"
                        }
                    },
                    "required": ["icd10_code"]
                }
            },
            {
                "name": "get_specific_codes",
                "description": "Get more specific (child) ICD-10-CM codes for a broad/parent code. Use this when you have a general code like E11.9 and want to find the most specific code supported by the documentation. Returns child codes with descriptions.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "icd10_code": {
                            "type": "string",
                            "description": "Parent ICD-10-CM code, e.g. E11.2, F03"
                        }
                    },
                    "required": ["icd10_code"]
                }
            },
            {
                "name": "calculate_raf_score",
                "description": "Calculate an estimated CMS-HCC V28 RAF score for a patient given their ICD-10 diagnosis codes, age and sex, using the hccinfhir library (third-party open-source implementation — not CMS-validated). Returns the total RAF score, demographic score, disease score, HCC codes with coefficients, and interaction terms. Call this AFTER extracting all diagnoses to get the final RAF score.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "icd_codes": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "List of ICD-10-CM codes, e.g. ['E11.22', 'F32.9', 'F03.90']"
                        },
                        "age": {"type": "integer", "description": "Patient age"},
                        "sex": {"type": "string", "description": "Male or Female"},
                        "dual_status": {
                            "type": "string",
                            "description": "Medicaid dual status: 'non_dual' (default), 'partial', or 'full'. Pass when known to ensure the correct CMS-HCC model segment (CNA/CND/CFA/CFD/CPA/CPD) is used."
                        }
                    },
                    "required": ["icd_codes", "age", "sex"]
                }
            }
        ]
    }
]

# ---------------------------------------------------------------------------
# Tool implementations (local DB lookups, no LLM)
# ---------------------------------------------------------------------------

def _handle_lookup_hcc(icd10_code: str) -> dict:
    """Look up ICD-10 -> HCC mapping using hccinfhir as the sole source of truth.

    hccinfhir (dx_to_cc_default) is the same crosswalk used internally by
    calculate_raf_score, so this surface is always consistent with the RAF
    calculation — no DB divergence is possible.

    Returns a dict with found/not-found structure; callers should inspect
    ``found`` before consuming ``hcc_code`` / ``raf_weight``.
    """
    from hccinfhir.defaults import (
        coefficients_default,
        dx_to_cc_default,
        is_chronic_default,
        labels_default,
    )

    MODEL = "CMS-HCC Model V28"

    icd = icd10_code.strip().upper()
    # hccinfhir keys use the undotted form; try that first, then the dotted
    # form in case a future library version normalises differently.
    icd_no_dot = icd.replace(".", "")

    cc_set = dx_to_cc_default.get((icd_no_dot, MODEL)) or dx_to_cc_default.get((icd, MODEL))

    if not cc_set:
        return {
            "found": False,
            "icd10_code": icd,
            "hcc_code": "",
            "hcc_label": "",
            "raf_weight": 0,
            "risk_adjusting": False,
            "source": "hccinfhir",
        }

    # When a code maps to multiple HCCs pick the first entry.
    cc = next(iter(cc_set))

    hcc_label = labels_default.get((cc, MODEL)) or f"HCC {cc}"
    raf_weight = coefficients_default.get((f"cna_hcc{cc}", MODEL)) or coefficients_default.get((f"HCC{cc}", MODEL)) or 0.0
    is_chronic = is_chronic_default.get((cc, MODEL)) or False

    return {
        "found": True,
        "icd10_code": icd,
        "hcc_code": f"HCC{cc}",
        "hcc_label": hcc_label,
        "raf_weight": float(raf_weight),
        "is_chronic": is_chronic,
        "risk_adjusting": True,
        "source": "hccinfhir",
    }


def _handle_get_raf_demographic_base(age: int, sex: str) -> dict:
    """Get demographic base coefficient from hccinfhir.

    Demographic coefficients are sourced directly from hccinfhir
    (coefficients_default) so the pipeline works with empty DB tables.
    The hcc_demographic_coefficients DB table is intentionally NOT queried
    here — it is kept for reference only.
    """
    sex_code = "F" if sex.lower().startswith("f") else "M"
    # Determine age band label used in hccinfhir coefficient keys
    bands = [(0, 34), (35, 44), (45, 54), (55, 59), (60, 64), (65, 69),
             (70, 74), (75, 79), (80, 84), (85, 89), (90, 94), (95, 200)]
    age_band = "65_69"  # default
    for lo, hi in bands:
        if lo <= age <= hi:
            age_band = f"{lo}_{hi}"
            break

    # Try to resolve the coefficient directly from hccinfhir
    try:
        from hccinfhir.defaults import coefficients_default
        MODEL = "CMS-HCC Model V28"
        # hccinfhir stores demographic coefficients under keys like
        # ("M65_69", MODEL) or ("F65_69", MODEL) depending on version.
        coeff_key = f"{sex_code}{age_band}"
        raw = (
            coefficients_default.get((coeff_key, MODEL))
            or coefficients_default.get(coeff_key)
        )
        if raw is not None:
            return {"base_rate": float(raw), "age_band": coeff_key, "source": "hccinfhir"}
    except Exception as exc:
        logger.warning("[Skill] hccinfhir demographic coefficient lookup failed: %s", exc)

    # Built-in defaults derived from published CMS-HCC V28 CNA coefficients.
    # These are used only when hccinfhir is unavailable (import failure).
    defaults = {
        "M": {(0, 64): 0.345, (65, 69): 0.389, (70, 74): 0.432, (75, 200): 0.532},
        "F": {(0, 64): 0.310, (65, 69): 0.365, (70, 74): 0.395, (75, 200): 0.487},
    }
    for (lo, hi), val in defaults.get(sex_code, defaults["M"]).items():
        if lo <= age <= hi:
            return {"base_rate": val, "age_band": f"{sex_code}{age_band}", "source": "built_in_default"}
    return {"base_rate": 0.395, "age_band": f"{sex_code}{age_band}", "source": "built_in_default"}


_DRUG_TO_CONDITIONS = {
    # ------------------------------------------------------------------ #
    # Diabetes with complications (V28 HCC37)                             #
    # ------------------------------------------------------------------ #
    "insulin": [{"condition": "Diabetes Mellitus with Complications", "icd10": "E11.649", "hcc": "HCC37"}],
    "insulin glargine": [{"condition": "Diabetes Mellitus with Complications", "icd10": "E11.649", "hcc": "HCC37"}],
    "insulin lispro": [{"condition": "Diabetes Mellitus with Complications", "icd10": "E11.649", "hcc": "HCC37"}],
    "insulin aspart": [{"condition": "Diabetes Mellitus with Complications", "icd10": "E11.649", "hcc": "HCC37"}],
    "insulin detemir": [{"condition": "Diabetes Mellitus with Complications", "icd10": "E11.649", "hcc": "HCC37"}],
    "dulaglutide": [{"condition": "Diabetes Mellitus with Complications", "icd10": "E11.649", "hcc": "HCC37"}],
    "exenatide": [{"condition": "Diabetes Mellitus with Complications", "icd10": "E11.649", "hcc": "HCC37"}],
    "liraglutide": [
        {"condition": "Diabetes Mellitus with Complications", "icd10": "E11.649", "hcc": "HCC37"},
        {"condition": "Morbid Obesity", "icd10": "E66.01", "hcc": "HCC48"},
    ],

    # ------------------------------------------------------------------ #
    # Diabetes without complications (V28 HCC38)                          #
    # ------------------------------------------------------------------ #
    "metformin": [{"condition": "Type 2 Diabetes Mellitus", "icd10": "E11.9", "hcc": "HCC38"}],
    "glipizide": [{"condition": "Type 2 Diabetes Mellitus", "icd10": "E11.9", "hcc": "HCC38"}],
    "glimepiride": [{"condition": "Type 2 Diabetes Mellitus", "icd10": "E11.9", "hcc": "HCC38"}],
    "glyburide": [{"condition": "Type 2 Diabetes Mellitus", "icd10": "E11.9", "hcc": "HCC38"}],
    "sitagliptin": [{"condition": "Type 2 Diabetes Mellitus", "icd10": "E11.9", "hcc": "HCC38"}],
    "empagliflozin": [{"condition": "Type 2 Diabetes Mellitus", "icd10": "E11.9", "hcc": "HCC38"}],
    "dapagliflozin": [{"condition": "Type 2 Diabetes Mellitus", "icd10": "E11.9", "hcc": "HCC38"}],
    "canagliflozin": [{"condition": "Type 2 Diabetes Mellitus", "icd10": "E11.9", "hcc": "HCC38"}],
    "pioglitazone": [{"condition": "Type 2 Diabetes Mellitus", "icd10": "E11.9", "hcc": "HCC38"}],

    # ------------------------------------------------------------------ #
    # Heart Failure (V28 HCC226)                                          #
    # ------------------------------------------------------------------ #
    "furosemide": [{"condition": "Heart Failure", "icd10": "I50.9", "hcc": "HCC226"}],
    "lasix": [{"condition": "Heart Failure", "icd10": "I50.9", "hcc": "HCC226"}],
    "torsemide": [{"condition": "Heart Failure", "icd10": "I50.9", "hcc": "HCC226"}],
    "bumetanide": [{"condition": "Heart Failure", "icd10": "I50.9", "hcc": "HCC226"}],
    "spironolactone": [{"condition": "Heart Failure", "icd10": "I50.9", "hcc": "HCC226"}],
    "eplerenone": [{"condition": "Heart Failure", "icd10": "I50.9", "hcc": "HCC226"}],
    "carvedilol": [{"condition": "Heart Failure", "icd10": "I50.9", "hcc": "HCC226"}],
    "sacubitril": [{"condition": "Heart Failure", "icd10": "I50.9", "hcc": "HCC226"}],
    "sacubitril/valsartan": [{"condition": "Heart Failure", "icd10": "I50.9", "hcc": "HCC226"}],
    "entresto": [{"condition": "Heart Failure", "icd10": "I50.9", "hcc": "HCC226"}],

    # ------------------------------------------------------------------ #
    # COPD (V28 HCC280)                                                   #
    # ------------------------------------------------------------------ #
    "tiotropium": [{"condition": "COPD", "icd10": "J44.9", "hcc": "HCC280"}],
    "albuterol": [{"condition": "COPD/Asthma", "icd10": "J44.9", "hcc": "HCC280"}],
    "ipratropium": [{"condition": "COPD", "icd10": "J44.9", "hcc": "HCC280"}],
    "albuterol/ipratropium": [{"condition": "COPD", "icd10": "J44.9", "hcc": "HCC280"}],
    "fluticasone/salmeterol": [{"condition": "COPD", "icd10": "J44.9", "hcc": "HCC280"}],
    "advair": [{"condition": "COPD", "icd10": "J44.9", "hcc": "HCC280"}],
    "budesonide/formoterol": [{"condition": "COPD", "icd10": "J44.9", "hcc": "HCC280"}],
    "roflumilast": [{"condition": "COPD", "icd10": "J44.1", "hcc": "HCC280"}],
    "umeclidinium": [{"condition": "COPD", "icd10": "J44.9", "hcc": "HCC280"}],

    # ------------------------------------------------------------------ #
    # CKD Stage 4+ (V28 HCC327)                                           #
    # ------------------------------------------------------------------ #
    "epoetin": [{"condition": "CKD Stage 4+", "icd10": "N18.4", "hcc": "HCC327"}],
    "epoetin alfa": [{"condition": "CKD Stage 4+", "icd10": "N18.4", "hcc": "HCC327"}],
    "darbepoetin": [{"condition": "CKD Stage 4+", "icd10": "N18.4", "hcc": "HCC327"}],
    "darbepoetin alfa": [{"condition": "CKD Stage 4+", "icd10": "N18.4", "hcc": "HCC327"}],
    "sevelamer": [{"condition": "CKD Stage 4+", "icd10": "N18.4", "hcc": "HCC327"}],
    "cinacalcet": [{"condition": "CKD Stage 4+ with secondary hyperparathyroidism", "icd10": "N18.4", "hcc": "HCC327"}],

    # ------------------------------------------------------------------ #
    # Atrial Fibrillation (V28 HCC238)                                    #
    # ------------------------------------------------------------------ #
    "warfarin": [{"condition": "Atrial Fibrillation", "icd10": "I48.91", "hcc": "HCC238"}],
    "apixaban": [{"condition": "Atrial Fibrillation", "icd10": "I48.91", "hcc": "HCC238"}],
    "eliquis": [{"condition": "Atrial Fibrillation", "icd10": "I48.91", "hcc": "HCC238"}],
    "rivaroxaban": [{"condition": "Atrial Fibrillation", "icd10": "I48.91", "hcc": "HCC238"}],
    "xarelto": [{"condition": "Atrial Fibrillation", "icd10": "I48.91", "hcc": "HCC238"}],
    "dabigatran": [{"condition": "Atrial Fibrillation", "icd10": "I48.91", "hcc": "HCC238"}],
    "edoxaban": [{"condition": "Atrial Fibrillation", "icd10": "I48.91", "hcc": "HCC238"}],
    "amiodarone": [{"condition": "Atrial Fibrillation", "icd10": "I48.91", "hcc": "HCC238"}],
    "flecainide": [{"condition": "Atrial Fibrillation", "icd10": "I48.91", "hcc": "HCC238"}],
    "dronedarone": [{"condition": "Atrial Fibrillation", "icd10": "I48.91", "hcc": "HCC238"}],

    # ------------------------------------------------------------------ #
    # Dementia (V28 HCC127)                                               #
    # ------------------------------------------------------------------ #
    "donepezil": [{"condition": "Dementia", "icd10": "F03.90", "hcc": "HCC127"}],
    "aricept": [{"condition": "Dementia", "icd10": "F03.90", "hcc": "HCC127"}],
    "memantine": [{"condition": "Dementia", "icd10": "F03.90", "hcc": "HCC127"}],
    "namenda": [{"condition": "Dementia", "icd10": "F03.90", "hcc": "HCC127"}],
    "rivastigmine": [{"condition": "Dementia", "icd10": "F03.90", "hcc": "HCC127"}],
    "galantamine": [{"condition": "Dementia", "icd10": "F03.90", "hcc": "HCC127"}],

    # ------------------------------------------------------------------ #
    # Depression (V28 HCC155)                                             #
    # ------------------------------------------------------------------ #
    "sertraline": [{"condition": "Major Depressive Disorder", "icd10": "F32.9", "hcc": "HCC155"}],
    "zoloft": [{"condition": "Major Depressive Disorder", "icd10": "F32.9", "hcc": "HCC155"}],
    "fluoxetine": [{"condition": "Major Depressive Disorder", "icd10": "F32.9", "hcc": "HCC155"}],
    "prozac": [{"condition": "Major Depressive Disorder", "icd10": "F32.9", "hcc": "HCC155"}],
    "escitalopram": [{"condition": "Major Depressive Disorder", "icd10": "F32.9", "hcc": "HCC155"}],
    "lexapro": [{"condition": "Major Depressive Disorder", "icd10": "F32.9", "hcc": "HCC155"}],
    "citalopram": [{"condition": "Major Depressive Disorder", "icd10": "F32.9", "hcc": "HCC155"}],
    "paroxetine": [{"condition": "Major Depressive Disorder", "icd10": "F32.9", "hcc": "HCC155"}],
    "duloxetine": [{"condition": "Major Depressive Disorder", "icd10": "F32.9", "hcc": "HCC155"}],
    "cymbalta": [{"condition": "Major Depressive Disorder", "icd10": "F32.9", "hcc": "HCC155"}],
    "venlafaxine": [{"condition": "Major Depressive Disorder", "icd10": "F32.9", "hcc": "HCC155"}],
    "effexor": [{"condition": "Major Depressive Disorder", "icd10": "F32.9", "hcc": "HCC155"}],
    "bupropion": [{"condition": "Major Depressive Disorder", "icd10": "F32.9", "hcc": "HCC155"}],
    "mirtazapine": [{"condition": "Major Depressive Disorder", "icd10": "F32.9", "hcc": "HCC155"}],
    "lithium": [{"condition": "Bipolar Disorder", "icd10": "F31.9", "hcc": "HCC155"}],

    # ------------------------------------------------------------------ #
    # Rheumatoid Arthritis (V28 HCC93)                                    #
    # ------------------------------------------------------------------ #
    "methotrexate": [{"condition": "Rheumatoid Arthritis", "icd10": "M06.9", "hcc": "HCC93"}],
    "hydroxychloroquine": [{"condition": "Rheumatoid Arthritis/Lupus", "icd10": "M06.9", "hcc": "HCC93"}],
    "plaquenil": [{"condition": "Rheumatoid Arthritis/Lupus", "icd10": "M06.9", "hcc": "HCC93"}],
    "adalimumab": [{"condition": "Rheumatoid Arthritis", "icd10": "M06.9", "hcc": "HCC93"}],
    "humira": [{"condition": "Rheumatoid Arthritis", "icd10": "M06.9", "hcc": "HCC93"}],
    "etanercept": [{"condition": "Rheumatoid Arthritis", "icd10": "M06.9", "hcc": "HCC93"}],
    "enbrel": [{"condition": "Rheumatoid Arthritis", "icd10": "M06.9", "hcc": "HCC93"}],
    "infliximab": [{"condition": "Rheumatoid Arthritis", "icd10": "M06.9", "hcc": "HCC93"}],
    "abatacept": [{"condition": "Rheumatoid Arthritis", "icd10": "M06.9", "hcc": "HCC93"}],
    "rituximab": [{"condition": "Rheumatoid Arthritis", "icd10": "M06.9", "hcc": "HCC93"}],
    "tocilizumab": [{"condition": "Rheumatoid Arthritis", "icd10": "M06.9", "hcc": "HCC93"}],
    "leflunomide": [{"condition": "Rheumatoid Arthritis", "icd10": "M06.9", "hcc": "HCC93"}],
    "sulfasalazine": [{"condition": "Rheumatoid Arthritis", "icd10": "M06.9", "hcc": "HCC93"}],
    "cyclosporine": [{"condition": "Rheumatoid Arthritis/Transplant", "icd10": "M06.9", "hcc": "HCC93"}],

    # ------------------------------------------------------------------ #
    # Schizophrenia (V28 HCC151)                                          #
    # ------------------------------------------------------------------ #
    "olanzapine": [{"condition": "Schizophrenia", "icd10": "F20.9", "hcc": "HCC151"}],
    "zyprexa": [{"condition": "Schizophrenia", "icd10": "F20.9", "hcc": "HCC151"}],
    "risperidone": [{"condition": "Schizophrenia", "icd10": "F20.9", "hcc": "HCC151"}],
    "risperdal": [{"condition": "Schizophrenia", "icd10": "F20.9", "hcc": "HCC151"}],
    "quetiapine": [{"condition": "Schizophrenia", "icd10": "F20.9", "hcc": "HCC151"}],
    "seroquel": [{"condition": "Schizophrenia", "icd10": "F20.9", "hcc": "HCC151"}],
    "aripiprazole": [{"condition": "Schizophrenia", "icd10": "F20.9", "hcc": "HCC151"}],
    "abilify": [{"condition": "Schizophrenia", "icd10": "F20.9", "hcc": "HCC151"}],
    "clozapine": [{"condition": "Schizophrenia", "icd10": "F20.9", "hcc": "HCC151"}],
    "clozaril": [{"condition": "Schizophrenia", "icd10": "F20.9", "hcc": "HCC151"}],
    "haloperidol": [{"condition": "Schizophrenia", "icd10": "F20.9", "hcc": "HCC151"}],
    "paliperidone": [{"condition": "Schizophrenia", "icd10": "F20.9", "hcc": "HCC151"}],
    "lurasidone": [{"condition": "Schizophrenia", "icd10": "F20.9", "hcc": "HCC151"}],
    "ziprasidone": [{"condition": "Schizophrenia", "icd10": "F20.9", "hcc": "HCC151"}],

    # ------------------------------------------------------------------ #
    # Seizure Disorders (V28 HCC134)                                      #
    # ------------------------------------------------------------------ #
    "levetiracetam": [{"condition": "Seizure Disorder/Epilepsy", "icd10": "G40.909", "hcc": "HCC134"}],
    "keppra": [{"condition": "Seizure Disorder/Epilepsy", "icd10": "G40.909", "hcc": "HCC134"}],
    "valproic acid": [{"condition": "Seizure Disorder/Epilepsy", "icd10": "G40.909", "hcc": "HCC134"}],
    "valproate": [{"condition": "Seizure Disorder/Epilepsy", "icd10": "G40.909", "hcc": "HCC134"}],
    "divalproex": [{"condition": "Seizure Disorder/Epilepsy", "icd10": "G40.909", "hcc": "HCC134"}],
    "phenytoin": [{"condition": "Seizure Disorder/Epilepsy", "icd10": "G40.909", "hcc": "HCC134"}],
    "dilantin": [{"condition": "Seizure Disorder/Epilepsy", "icd10": "G40.909", "hcc": "HCC134"}],
    "carbamazepine": [{"condition": "Seizure Disorder/Epilepsy", "icd10": "G40.909", "hcc": "HCC134"}],
    "tegretol": [{"condition": "Seizure Disorder/Epilepsy", "icd10": "G40.909", "hcc": "HCC134"}],
    "lamotrigine": [{"condition": "Seizure Disorder/Epilepsy", "icd10": "G40.909", "hcc": "HCC134"}],
    "lamictal": [{"condition": "Seizure Disorder/Epilepsy", "icd10": "G40.909", "hcc": "HCC134"}],
    "oxcarbazepine": [{"condition": "Seizure Disorder/Epilepsy", "icd10": "G40.909", "hcc": "HCC134"}],
    "topiramate": [{"condition": "Seizure Disorder/Epilepsy", "icd10": "G40.909", "hcc": "HCC134"}],
    "zonisamide": [{"condition": "Seizure Disorder/Epilepsy", "icd10": "G40.909", "hcc": "HCC134"}],

    # ------------------------------------------------------------------ #
    # Parkinson's Disease (V28 HCC199)                                    #
    # ------------------------------------------------------------------ #
    "carbidopa/levodopa": [{"condition": "Parkinson Disease", "icd10": "G20", "hcc": "HCC199"}],
    "levodopa": [{"condition": "Parkinson Disease", "icd10": "G20", "hcc": "HCC199"}],
    "carbidopa": [{"condition": "Parkinson Disease", "icd10": "G20", "hcc": "HCC199"}],
    "sinemet": [{"condition": "Parkinson Disease", "icd10": "G20", "hcc": "HCC199"}],
    "ropinirole": [{"condition": "Parkinson Disease", "icd10": "G20", "hcc": "HCC199"}],
    "requip": [{"condition": "Parkinson Disease", "icd10": "G20", "hcc": "HCC199"}],
    "pramipexole": [{"condition": "Parkinson Disease", "icd10": "G20", "hcc": "HCC199"}],
    "mirapex": [{"condition": "Parkinson Disease", "icd10": "G20", "hcc": "HCC199"}],
    "rasagiline": [{"condition": "Parkinson Disease", "icd10": "G20", "hcc": "HCC199"}],
    "selegiline": [{"condition": "Parkinson Disease", "icd10": "G20", "hcc": "HCC199"}],

    # ------------------------------------------------------------------ #
    # Organ Transplant (V28 HCC186)                                       #
    # ------------------------------------------------------------------ #
    "tacrolimus": [{"condition": "Organ Transplant Status", "icd10": "Z94.0", "hcc": "HCC186"}],
    "prograf": [{"condition": "Organ Transplant Status", "icd10": "Z94.0", "hcc": "HCC186"}],
    "mycophenolate": [{"condition": "Organ Transplant Status", "icd10": "Z94.0", "hcc": "HCC186"}],
    "mycophenolate mofetil": [{"condition": "Organ Transplant Status", "icd10": "Z94.0", "hcc": "HCC186"}],
    "cellcept": [{"condition": "Organ Transplant Status", "icd10": "Z94.0", "hcc": "HCC186"}],
    "sirolimus": [{"condition": "Organ Transplant Status", "icd10": "Z94.0", "hcc": "HCC186"}],
    "rapamune": [{"condition": "Organ Transplant Status", "icd10": "Z94.0", "hcc": "HCC186"}],
    "everolimus": [{"condition": "Organ Transplant Status", "icd10": "Z94.0", "hcc": "HCC186"}],

    # ------------------------------------------------------------------ #
    # HIV (V28 HCC1)                                                      #
    # ------------------------------------------------------------------ #
    "tenofovir": [{"condition": "HIV/AIDS", "icd10": "B20", "hcc": "HCC1"}],
    "emtricitabine": [{"condition": "HIV/AIDS", "icd10": "B20", "hcc": "HCC1"}],
    "dolutegravir": [{"condition": "HIV/AIDS", "icd10": "B20", "hcc": "HCC1"}],
    "bictegravir": [{"condition": "HIV/AIDS", "icd10": "B20", "hcc": "HCC1"}],
    "elvitegravir": [{"condition": "HIV/AIDS", "icd10": "B20", "hcc": "HCC1"}],
    "raltegravir": [{"condition": "HIV/AIDS", "icd10": "B20", "hcc": "HCC1"}],
    "abacavir": [{"condition": "HIV/AIDS", "icd10": "B20", "hcc": "HCC1"}],
    "efavirenz": [{"condition": "HIV/AIDS", "icd10": "B20", "hcc": "HCC1"}],
    "atazanavir": [{"condition": "HIV/AIDS", "icd10": "B20", "hcc": "HCC1"}],
    "darunavir": [{"condition": "HIV/AIDS", "icd10": "B20", "hcc": "HCC1"}],
    "triumeq": [{"condition": "HIV/AIDS", "icd10": "B20", "hcc": "HCC1"}],
    "biktarvy": [{"condition": "HIV/AIDS", "icd10": "B20", "hcc": "HCC1"}],
    "genvoya": [{"condition": "HIV/AIDS", "icd10": "B20", "hcc": "HCC1"}],

    # ------------------------------------------------------------------ #
    # Cancer / Active Treatment (V28 HCC12)                               #
    # ------------------------------------------------------------------ #
    "tamoxifen": [{"condition": "Breast Cancer", "icd10": "C50.919", "hcc": "HCC12"}],
    "letrozole": [{"condition": "Breast Cancer", "icd10": "C50.919", "hcc": "HCC12"}],
    "anastrozole": [{"condition": "Breast Cancer", "icd10": "C50.919", "hcc": "HCC12"}],
    "capecitabine": [{"condition": "Cancer (Active Treatment)", "icd10": "C80.1", "hcc": "HCC12"}],
    "xeloda": [{"condition": "Cancer (Active Treatment)", "icd10": "C80.1", "hcc": "HCC12"}],
    "imatinib": [{"condition": "Cancer (Active Treatment)", "icd10": "C80.1", "hcc": "HCC12"}],
    "erlotinib": [{"condition": "Cancer (Active Treatment)", "icd10": "C80.1", "hcc": "HCC12"}],
    "bevacizumab": [{"condition": "Cancer (Active Treatment)", "icd10": "C80.1", "hcc": "HCC12"}],

    # ------------------------------------------------------------------ #
    # Vascular Disease (V28 HCC263)                                       #
    # ------------------------------------------------------------------ #
    "clopidogrel": [{"condition": "Peripheral Vascular Disease/CAD", "icd10": "I73.9", "hcc": "HCC263"}],
    "plavix": [{"condition": "Peripheral Vascular Disease/CAD", "icd10": "I73.9", "hcc": "HCC263"}],
    "ticagrelor": [{"condition": "Peripheral Vascular Disease/CAD", "icd10": "I73.9", "hcc": "HCC263"}],
    "brilinta": [{"condition": "Peripheral Vascular Disease/CAD", "icd10": "I73.9", "hcc": "HCC263"}],
    "cilostazol": [{"condition": "Peripheral Arterial Disease", "icd10": "I73.9", "hcc": "HCC263"}],
    "pletal": [{"condition": "Peripheral Arterial Disease", "icd10": "I73.9", "hcc": "HCC263"}],
    "prasugrel": [{"condition": "Peripheral Vascular Disease/CAD", "icd10": "I73.9", "hcc": "HCC263"}],

    # ------------------------------------------------------------------ #
    # Morbid Obesity (V28 HCC48)                                          #
    # ------------------------------------------------------------------ #
    "semaglutide": [{"condition": "Morbid Obesity", "icd10": "E66.01", "hcc": "HCC48"}],
    "ozempic": [{"condition": "Morbid Obesity", "icd10": "E66.01", "hcc": "HCC48"}],
    "wegovy": [{"condition": "Morbid Obesity", "icd10": "E66.01", "hcc": "HCC48"}],
    "phentermine/topiramate": [{"condition": "Morbid Obesity", "icd10": "E66.01", "hcc": "HCC48"}],
    "qsymia": [{"condition": "Morbid Obesity", "icd10": "E66.01", "hcc": "HCC48"}],
    "naltrexone/bupropion": [{"condition": "Morbid Obesity", "icd10": "E66.01", "hcc": "HCC48"}],
    "contrave": [{"condition": "Morbid Obesity", "icd10": "E66.01", "hcc": "HCC48"}],
    "orlistat": [{"condition": "Morbid Obesity", "icd10": "E66.01", "hcc": "HCC48"}],
    "tirzepatide": [{"condition": "Morbid Obesity", "icd10": "E66.01", "hcc": "HCC48"}],
    "mounjaro": [{"condition": "Morbid Obesity", "icd10": "E66.01", "hcc": "HCC48"}],
    "zepbound": [{"condition": "Morbid Obesity", "icd10": "E66.01", "hcc": "HCC48"}],
}

def _handle_validate_icd10(icd10_code: str) -> dict:
    """Validate ICD-10 code using simple_icd_10_cm library."""
    try:
        import simple_icd_10_cm as cm
        code = icd10_code.strip()
        if not cm.is_valid_item(code):
            return {
                "valid": False,
                "billable": False,
                "code": code,
                "description": "",
                "hint": f"{code} is not a valid ICD-10-CM code. Check for typos.",
            }
        desc = cm.get_description(code)
        is_billable = cm.is_leaf(code)
        result = {
            "valid": True,
            "billable": is_billable,
            "code": code,
            "description": str(desc),
        }
        if not is_billable:
            children = cm.get_children(code)
            child_list = []
            for c in children[:10]:
                c_str = str(c)
                child_list.append({"code": c_str, "description": str(cm.get_description(c_str)), "billable": cm.is_leaf(c_str)})
            result["hint"] = f"{code} is valid but NOT billable. Use a more specific child code."
            result["children"] = child_list
        return result
    except Exception as exc:
        logger.warning("[Skill] ICD-10 validation failed for %s: %s", icd10_code, exc)
        return {"valid": False, "code": icd10_code, "error": str(exc)}


def _handle_get_specific_codes(icd10_code: str) -> dict:
    """Get child codes for a parent ICD-10 code."""
    try:
        import simple_icd_10_cm as cm
        code = icd10_code.strip()
        if not cm.is_valid_item(code):
            return {"code": code, "children": [], "error": "Invalid code"}
        children = cm.get_children(code)
        child_list = []
        for c in children[:15]:
            c_str = str(c)
            child_list.append({
                "code": c_str,
                "description": str(cm.get_description(c_str)),
                "billable": cm.is_leaf(c_str),
            })
        return {"code": code, "description": str(cm.get_description(code)), "children": child_list}
    except Exception as exc:
        logger.warning("[Skill] Get specific codes failed for %s: %s", icd10_code, exc)
        return {"code": icd10_code, "children": [], "error": str(exc)}


def _handle_check_medication_gaps(medication: str) -> dict:
    med = medication.strip().lower()
    conditions = _DRUG_TO_CONDITIONS.get(med, [])
    if conditions:
        return {"medication": medication, "suggests": conditions, "gap_found": True}
    return {"medication": medication, "suggests": [], "gap_found": False}


_INTERACTION_LABELS: dict[str, str] = {
    "DIABETES_HF_V28": "Diabetes + Heart Failure Interaction",
    "HF_CHR_LUNG_V28": "Heart Failure + Chronic Lung Disease",
    "HF_KIDNEY_V28": "Heart Failure + Kidney Disease",
    "CHR_LUNG_KIDNEY_V28": "Chronic Lung + Kidney Disease",
    "HF_HCC238_V28": "Heart Failure + Specified Heart Arrhythmia",
    "D6": "Disability Interaction (age < 65)",
}


def _handle_calculate_raf(
    icd_codes: list,
    age: int,
    sex: str,
    dual_status: str | None = None,
) -> dict:
    """
    Estimate CMS-HCC V28 RAF score using the hccinfhir library.

    Args:
        icd_codes:   List of ICD-10-CM codes.
        age:         Patient age in years.  This value is supplied by Gemini
                     based on what it reads in the clinical note context.

                     - Paste mode (patient_id=0): Gemini parses age from the
                       note text, reflecting the patient's documented age at
                       encounter time.  Correct for prospective / demo analysis.
                     - OpenEMR patient mode: analysis.py pre-calculates age from
                       DOB using the encounter service year (CMS rule: age as of
                       Feb 1 of that year) and injects it as "Patient age: N" in
                       the Gemini context.  Gemini returns that value unchanged.

                     Do NOT replace this with date.today() arithmetic here —
                     that would re-introduce the bug where a 2021 encounter
                     patient is scored with their 2026 age.
        sex:         "Male" / "Female" (normalised internally to M/F).
        dual_status: Medicaid dual status — "non_dual", "partial", or "full".
                     Defaults to "non_dual" when omitted so that existing callers
                     continue to work without change (backward compatible).
    """
    try:
        from hccinfhir import Demographics, HCCInFHIR

        from app.services.raf_calculator import determine_model_segment

        sex_code = "F" if sex.lower().startswith("f") else "M"

        # Resolve dual_status; default to "non_dual" for backward compatibility.
        _dual = (dual_status or "non_dual").lower()

        # Derive the correct CMS-HCC model segment so the demographic and disease
        # coefficients pulled from the CMS tables match the beneficiary's category.
        # The institutional flag is not available at this pipeline level, so it
        # defaults to False; pass dual info through to get the right community segment.
        segment = determine_model_segment(
            age=age,
            is_dual=_dual != "non_dual",
            dual_type=_dual,
            is_institutional=False,
        )

        demo = Demographics(age=age, sex=sex_code, dual_status=_dual, orec="0")
        engine = HCCInFHIR()
        result = engine.calculate_from_diagnosis(diagnosis_codes=icd_codes, demographics=demo)

        # --- HCC details: use hcc_details directly from hccinfhir ---
        # Fall back to manual coefficient extraction only if the attribute is missing
        # (e.g. older library version), to preserve backward compatibility.
        try:
            hcc_details = [
                {
                    "hcc": str(h.hcc),
                    "label": h.label if h.label else f"HCC {h.hcc}",
                    "coefficient": round(float(h.coefficient), 4),
                    "is_chronic": h.is_chronic,
                }
                for h in result.hcc_details
            ]
        except (AttributeError, TypeError):
            # Fallback: derive from coefficients dict — keys that start with a digit
            # are HCC entries (e.g. "18", "85"); demographic/interaction keys are alpha.
            hcc_details = []
            for key, val in result.coefficients.items():
                if key and key[0].isdigit():
                    hcc_details.append({
                        "hcc": str(key),
                        "label": f"HCC {key}",
                        "coefficient": round(float(val), 4),
                        "is_chronic": True,
                    })

        # --- Scores derived directly from hccinfhir result fields ---
        # Demographic score: sum of coefficient values whose keys are non-numeric
        # (age/sex band and any demographic adjustment entries in the coefficients map).
        demo_score = sum(
            v for k, v in result.coefficients.items()
            if k and not k[0].isdigit()
            and k not in (getattr(result, "interactions", None) or {})
        )

        # Disease score: sum of individual HCC coefficients (excludes interactions).
        disease_score = sum(h["coefficient"] for h in hcc_details)

        # Interaction score: sum of actual coefficients for fired interaction terms.
        # result.interactions holds flag indicators (1.0 when fired, 0 otherwise).
        # The actual additive coefficient for each term lives in result.coefficients.
        interactions_dict = {k: v for k, v in (getattr(result, "interactions", None) or {}).items()}
        interaction_score = sum(
            float(result.coefficients.get(k, 0.0))
            for k, v in interactions_dict.items()
            if v  # only fired interactions
        )

        # Build interaction_details: one entry per fired interaction term with its
        # real coefficient so callers can reconcile disease_score + interaction_score
        # back to the total and display each term's contribution transparently.
        interaction_details = []
        for term_name, indicator in (getattr(result, "interactions", None) or {}).items():
            if indicator:  # Only fired interactions
                coeff = result.coefficients.get(term_name, 0.0)
                if coeff:
                    interaction_details.append({
                        "term": term_name,
                        "coefficient": round(float(coeff), 4),
                        "description": _INTERACTION_LABELS.get(term_name, term_name),
                    })

        payload = {
            # Core scores
            "raf_score": round(result.risk_score, 3),
            "payment_raf": round(result.risk_score_payment, 3) if result.risk_score_payment else None,
            "demographic_score": round(demo_score, 3),
            "disease_score": round(disease_score, 3),
            "interaction_score": round(interaction_score, 3),
            # HCC breakdown
            "hcc_list": [str(h) for h in result.hcc_list],
            "hcc_details": hcc_details,
            "hcc_contributions": hcc_details,  # backward-compatible alias
            # Interaction and coefficient detail
            "interactions": {k: v for k, v in interactions_dict.items() if v},
            "interaction_details": interaction_details,
            "cc_to_dx": {
                f"HCC{str(k)}": sorted(list(v))
                for k, v in (result.cc_to_dx or {}).items()
            },
            # Metadata
            "model": "CMS-HCC Model V28",
            "model_segment": segment,
            "coefficients": {k: round(v, 4) for k, v in result.coefficients.items()},
            "_disclaimer": "RAF scores are estimates based on CMS-HCC V28 model. Not for payment submission.",
        }
        return payload
    except Exception as exc:
        logger.error("[Skill] RAF calc failed: %s", exc)
        return {"raf_score": 0, "error": str(exc)}


# Tool dispatch
_TOOL_HANDLERS = {
    "lookup_hcc": lambda args: _handle_lookup_hcc(args.get("icd10_code", "")),
    "get_raf_demographic_base": lambda args: _handle_get_raf_demographic_base(
        args.get("age", 70), args.get("sex", "Female")
    ),
    "validate_icd10": lambda args: _handle_validate_icd10(args.get("icd10_code", "")),
    "get_specific_codes": lambda args: _handle_get_specific_codes(args.get("icd10_code", "")),
    "check_medication_gaps": lambda args: _handle_check_medication_gaps(args.get("medication", "")),
    "calculate_raf_score": lambda args: _handle_calculate_raf(
        args.get("icd_codes", []),
        args.get("age", 70),
        args.get("sex", "Female"),
        args.get("dual_status", None),
    ),
}

# ---------------------------------------------------------------------------
# Main prompt
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """You are a certified medical coder (CPC, CRC) specializing in CMS-HCC V28 risk adjustment.

Analyze the clinical note and produce a complete RAF analysis. You MUST:

1. Extract EVERY diagnosis documented in the note (Assessment, Plan, History)
2. Use the EXACT ICD-10 codes written in the note when available
3. For each ICD-10 code, call validate_icd10() to verify it exists and is billable. If not billable, call get_specific_codes() to find the most specific billable code supported by the documentation.
4. For each validated ICD-10 code, call lookup_hcc() to get the official CMS-HCC mapping

ADDITIONAL CONTEXT SOURCES — when provided in the user message, use each section as follows:

- ACTIVE PROBLEM LIST: Cross-reference the problem list against the clinical note. If a problem list condition is addressed, monitored, or treated in the note, ensure it is coded. If it is a chronic condition with MEAT evidence in the note, include it even if not in the note's Assessment section verbatim.
- RECAPTURE OPPORTUNITIES: These are conditions documented in prior years that have NOT been billed this year. Review each entry carefully. If any condition in this list is supported by the current note (MEAT evidence), code it and document the evidence. Flag any that are NOT supported so the provider is aware of the recapture gap.
- LATEST VITALS: Use vitals to support or escalate coding specificity. Elevated BMI may indicate obesity coding. Low O2 saturation may support respiratory condition specificity. Abnormal BP may support hypertension coding.
- MEDICATION INDICATIONS: If a medication's documented indication reveals a condition not explicitly coded in the note, surface it as a suspect condition using check_medication_gaps() if needed.

4. MEAT EVIDENCE EXTRACTION — CRITICAL FOR AUDIT DEFENSIBILITY

   For EVERY diagnosis you extract, you MUST document MEAT evidence from the note. This is required
   for CMS RADV audit defense. Extract specific quotes/references, not generic statements.

   M (Monitor) — What is being tracked over time?
     Examples: "HbA1c monitored at 8.2% (up from 7.9%)", "eGFR tracked at 37 (down from 39)",
     "BNP 485 (previously 412)", "Weight 182 lbs (4 lb gain)", "BP 158/88 (uncontrolled)"
     Look for: Labs ordered/reviewed, vitals tracked, imaging results, follow-up schedule

   E (Evaluate) — What clinical evaluation was performed?
     Examples: "Bilateral crackles on auscultation", "2+ ankle edema", "JVD 6cm elevated",
     "EF 28% on echo", "Right-sided weakness 4/5", "Oriented x2, expressive aphasia"
     Look for: Physical exam findings, diagnostic test interpretation, symptom assessment

   A (Assess) — What is the clinical assessment/status?
     Examples: "CHF decompensated, NYHA Class II-III", "DM uncontrolled, A1c 8.2%",
     "CKD Stage 3B, progressive", "Vascular dementia, progressive since CVA"
     Look for: Disease staging, severity, prognosis, stable/worsening/improving status

   T (Treat) — What treatment is provided or planned?
     Examples: "Continue metoprolol, lisinopril, spironolactone, furosemide",
     "Reinforce diuretic compliance", "On empagliflozin for DM and renal protection",
     "Donepezil 10mg and memantine 20mg for dementia"
     Look for: Medications, procedures, referrals, lifestyle modifications, patient education

   IMPORTANT: Search the ENTIRE note for evidence. Check History, Exam, Labs, Assessment, AND Plan sections.
   If a MEAT component is not documented in the note, set it to null (not empty string).
   A diagnosis with 4/4 MEAT components (meat_score=4) is fully audit-defensible.
   A diagnosis with 0/4 MEAT (meat_score=0) is NOT audit-defensible and must be flagged in coding_notes.
5. Identify suspect conditions (medications without matching diagnoses)
6. For each medication, call check_medication_gaps() to see if there are undocumented conditions that should be coded as suspects.
7. Apply the negation and uncertainty rules below to classify every condition before deciding where it belongs in the output. Assign a certainty value to each condition. Only conditions with certainty="confirmed" may appear in the diagnoses array. Conditions with certainty="suspected" go in suspect_conditions. Conditions with certainty="negated" or certainty="historical" go in negated_conditions.
8. After extracting ALL diagnoses, call calculate_raf_score() with ALL confirmed ICD-10 codes, patient age and sex to get the official CMS-HCC V28 RAF score. Include the RAF result in your response.

NEGATION AND UNCERTAINTY RULES (per CMS Official Coding Guidelines):

Rule 1 — EXCLUDE from diagnoses (assign certainty="negated"):
   Assign certainty="negated" whenever any of these phrases appear for a condition in the note:
   - "denies [condition]"
   - "no evidence of [condition]"
   - "ruled out [condition]"
   - "negative for [condition]"
   - "[condition] was excluded"
   - "no signs/symptoms of [condition]"
   Negated conditions MUST NOT appear in the diagnoses array. Place them in negated_conditions only.

Rule 2 — DO NOT CODE in outpatient settings (assign certainty="suspected"):
   Assign certainty="suspected" whenever the note qualifies a condition with any of these terms:
   - "possible [condition]"
   - "probable [condition]"
   - "suspected [condition]"
   - "rule out [condition]" (this is a workup instruction, NOT a confirmed diagnosis)
   - "questionable [condition]"
   - "likely [condition]" (without a separate confirmatory statement elsewhere in the note)
   Suspected conditions MUST NOT appear in the diagnoses array. Place them in suspect_conditions only.
   Do NOT pass suspected ICD-10 codes to calculate_raf_score().

Rule 3 — CAN CODE as active diagnosis (assign certainty="confirmed"):
   Assign certainty="confirmed" when ANY of the following are true:
   - The condition appears in the ACTIVE PROBLEM LIST provided in the context (active problems are confirmed by definition)
   - The condition appears in the Assessment section marked as "Confirmed"
   - The note says "consistent with [condition]", "diagnosed with [condition]", "confirmed [condition]"
   - The note says "[condition] - stable", "[condition] - on medication", "[condition] - monitored by PCP"
   - The condition is documented with MEAT evidence (monitored, evaluated, assessed, or treated) anywhere in the note
   - A medication is prescribed specifically for the condition (e.g., Coreg for heart failure, insulin for diabetes)
   IMPORTANT: Conditions in the Active Problem List are ALREADY CONFIRMED by the treating physician. They do NOT need to also appear in the Assessment section to be coded. If a chronic condition is on the active problem list and has any MEAT evidence in the note, it MUST be coded.
   Only confirmed conditions may appear in the diagnoses array and be submitted for RAF scoring.

Rule 4 — HISTORICAL conditions (assign certainty="historical"):
   Assign certainty="historical" when the note says "history of", "h/o", or "past history of" a
   condition that is no longer active. Use the appropriate personal history Z-code (Z80-Z87) and
   place the entry in negated_conditions. Do NOT use the active disease code for resolved conditions.

For EVERY condition you encounter in the note you MUST explicitly record a certainty field using
one of exactly these four values: "confirmed", "suspected", "negated", or "historical".

CRITICAL RULES:
- Use ICD-10 codes from the note's Assessment/Plan section FIRST
- Call lookup_hcc() for EVERY diagnosis to get the real HCC mapping
- Do NOT invent HCC codes — only use what lookup_hcc() returns
- If lookup_hcc returns risk_adjusting=false, the condition has no HCC impact
- Include ALL chronic conditions even if stable

IMPORTANT: When coding a condition with a qualifier (exacerbation, acute, severe), verify the qualifier is supported by the clinical documentation. If the note says "denies exacerbation", "no acute exacerbation", "without exacerbation", or similar contradicting language ANYWHERE in the note, use the code WITHOUT the qualifier. Examples:
- "denies acute exacerbation" or "no acute exacerbation" -> use J44.9 (COPD, unspecified) NOT J44.1 (COPD with exacerbation)
- "stable heart failure" or "no acute decompensation" -> use I50.22 (chronic systolic HF) NOT I50.21 (acute systolic HF)
- "chronic kidney disease" or "CKD stage X" with no acute event documented -> do NOT code N17 (acute kidney failure)
Overcoding qualifiers is a RADV audit red flag and a compliance violation. When in doubt, use the less specific code.

CMS CODING GUIDELINES:

1. "HISTORY OF" CONDITIONS — Use the personal history Z-code, NOT the active disease code, whenever the note says "history of", "h/o", or "past history of" a condition that is no longer active:
   - History of CVA / stroke → Z86.73 (NOT I63.x)
   - History of breast cancer → Z85.3 (NOT C50.x)
   - History of MI → Z86.79 (NOT I21.x)
   - History of DVT → Z86.718 (NOT I82.x)
   - History of bladder cancer → Z85.51 (NOT C67.x)
   - History of colon polyps → Z86.010
   Apply this rule to any condition prefaced with "history of" or "h/o" — always select the corresponding Z80–Z87 personal history code.

2. ACTIVE VS RESOLVED CONDITIONS — Only code conditions that are CURRENTLY ACTIVE and being monitored, evaluated, assessed, or treated (MEAT criteria). If the note explicitly states "resolved", "no longer present", or similar, assign the appropriate personal history Z-code rather than the active disease code.

3. "FAMILY HISTORY OF" — When the note documents a family history (e.g., "family history of colon cancer"), assign the appropriate Z80–Z84 family history code. Do NOT code the disease itself.

4. OUTPATIENT SETTING — These encounters are annual wellness visits (outpatient). Per CMS outpatient coding guidelines:
   - Do NOT code diagnoses qualified as "possible", "probable", "suspected", "rule out", "questionable", or "working diagnosis".
   - Only code conditions that have been confirmed by the provider.
   - Unconfirmed conditions may be captured as suspect_conditions in the JSON output, but must NOT appear in the diagnoses array.

5. COMBINATION CODES — When a single combination code fully describes two related conditions, use that one code instead of two separate codes:
   - Diabetes (E11.x) AND CKD (N18.x) both present → use E11.22 (Type 2 DM with diabetic CKD). Do NOT code E11.9 and N18.x separately.
   - Hypertension (I10) AND heart failure (I50.x) both present → use I11.0 (Hypertensive heart disease with heart failure) plus the appropriate I50.x code for the type of heart failure. Do NOT code I10 and I50.x without I11.0.
   - Diabetes (E11.x) AND neuropathy coded separately → use E11.40 (Type 2 DM with diabetic neuropathy, unspecified) or E11.42 (with diabetic polyneuropathy) instead of coding E11.9 and G62.9/G63 separately.
   Always check whether a combination code exists before assigning two codes for related conditions.

6. EXCLUDES1 / EXCLUDES2 — Do not report two codes that carry an Excludes1 relationship in ICD-10-CM. An Excludes1 note means the two conditions cannot occur together and must never be coded on the same claim. Excludes2 means the excluded condition is not part of the coded condition but may be coded separately if documented.

INCOMPLETE NOTE HANDLING:
If the clinical note appears to end abruptly, is missing expected sections (e.g. Plan, Assessment), or contains a marker such as "[NOTE TRUNCATED]", explicitly state in the coding_notes field that the note may be incomplete and the analysis may not reflect all documented conditions. Advise the user to resubmit with the full note if possible.

Return your final answer as JSON with this structure:
{
  "diagnoses": [
    {
      "icd10": "E11.22",
      "description": "Type 2 DM with diabetic CKD",
      "hcc": "HCC18",
      "hcc_weight": 0.318,
      "confidence": 0.95,
      "certainty": "confirmed",
      "meat": {
        "M": "HbA1c monitored at 8.2% (up from 7.9%); eGFR tracked at 37 (down from 39)",
        "E": "2+ pedal edema on exam; urine microalbumin 85 mg/g (elevated)",
        "A": "DM uncontrolled, A1c 8.2%; CKD Stage 3B, progressive",
        "T": "Continue metformin 1000mg BID; on empagliflozin for DM and renal protection; nephrology referral placed"
      },
      "meat_score": 4
    }
  ],
  "suspect_conditions": [
    {"condition": "...", "icd10": "...", "confidence": 0.8, "evidence_type": "medication", "evidence": "..."}
  ],
  "negated_conditions": [
    {"description": "...", "icd10": "...", "certainty": "negated", "reason": "negated"}
  ],
  "coding_notes": "summary — flag any diagnoses with meat_score=0 as not audit-defensible"
}"""

# ---------------------------------------------------------------------------
# Pipeline entry point
# ---------------------------------------------------------------------------

@gemini_breaker
def run_pipeline(
    clinical_note: str,
    *,
    patient_age: int | None = None,
    patient_sex: str | None = None,
    medications: list[str] | None = None,
    existing_hccs: list[str] | None = None,
    problem_list: list[dict] | None = None,
    recapture_gaps: list[dict] | None = None,
    latest_vitals: dict | None = None,
    med_diagnoses: list[dict] | None = None,
) -> dict[str, Any]:
    """
    Run skill-based analysis pipeline.

    Single Gemini conversation with function calling.
    Gemini extracts diagnoses and calls lookup_hcc() for each one.

    New optional parameters (all backward-compatible with None defaults):
      problem_list    — active medical problems from OpenEMR problem list
      recapture_gaps  — problems active but not billed in the current year
      latest_vitals   — most recent vitals row (bps, bpd, BMI, O2 sat, etc.)
      med_diagnoses   — medications that carry an indication/diagnosis note
    """
    total_start = time.time()
    from app.services.llm import llm_generate_content

    model = settings.gemini_model or "gemini-2.5-pro"

    # Build the user prompt
    context_parts = []
    if patient_age:
        context_parts.append(f"Patient age: {patient_age}")
    if patient_sex:
        context_parts.append(f"Sex: {patient_sex}")
    if medications:
        context_parts.append(f"Current medications: {', '.join(medications[:20])}")

    context_str = "\n".join(context_parts) if context_parts else ""

    # --- Extended OpenEMR context -------------------------------------------
    # These sections are appended after the base demographic line so that
    # Gemini receives the full structured context while still seeing the note
    # as a clearly-demarcated block below.
    extended_context = ""

    if problem_list:
        extended_context += f"\n\nACTIVE PROBLEM LIST ({len(problem_list)} conditions):\n"
        for p in problem_list[:30]:
            diag = p.get("diagnosis") or "no code"
            extended_context += f"- {p.get('title', 'Unknown')} ({diag})\n"

    if recapture_gaps:
        extended_context += (
            f"\n\nRECAPTURE OPPORTUNITIES "
            f"({len(recapture_gaps)} conditions active but NOT billed this year):\n"
        )
        for g in recapture_gaps[:20]:
            extended_context += f"- {g.get('title', 'Unknown')} ({g.get('diagnosis', '')})\n"

    if latest_vitals:
        bps = latest_vitals.get("bps", "")
        bpd = latest_vitals.get("bpd", "")
        bmi = latest_vitals.get("BMI", "")
        o2 = latest_vitals.get("oxygen_saturation", "")
        weight = latest_vitals.get("weight", "")
        height = latest_vitals.get("height", "")
        pulse = latest_vitals.get("pulse", "")
        extended_context += "\n\nLATEST VITALS:\n"
        if bps and bpd:
            extended_context += f"BP: {bps}/{bpd} mmHg\n"
        if bmi:
            extended_context += f"BMI: {bmi}\n"
        if o2:
            extended_context += f"O2 Sat: {o2}%\n"
        if weight:
            extended_context += f"Weight: {weight}\n"
        if height:
            extended_context += f"Height: {height}\n"
        if pulse:
            extended_context += f"Pulse: {pulse} bpm\n"

    if med_diagnoses:
        extended_context += f"\n\nMEDICATION INDICATIONS ({len(med_diagnoses)} entries):\n"
        for md in med_diagnoses[:20]:
            note_text_md = str(md.get("note", "")).strip()
            if note_text_md:
                extended_context += f"- {md.get('drug', 'Unknown')}: {note_text_md}\n"
    # ------------------------------------------------------------------------

    original_len = len(clinical_note)
    if original_len > _MAX_NOTE_CHARS:
        note_text = clinical_note[:_MAX_NOTE_CHARS] + "\n[NOTE TRUNCATED — ANALYSIS MAY BE INCOMPLETE]"
        submitted_len = len(note_text)
        logger.warning(
            "Note truncated from %d to %d chars for pid context",
            original_len,
            submitted_len,
        )
        _note_was_truncated = True
    else:
        note_text = clinical_note
        submitted_len = original_len
        _note_was_truncated = False

    user_prompt = f"""{context_str}{extended_context}

CLINICAL NOTE:
{note_text}

Analyze this note completely. Use ALL context provided above (problem list, recapture opportunities, vitals, and medication indications) alongside the clinical note when identifying and coding diagnoses. Call lookup_hcc() for every ICD-10 code you identify to get the official HCC mapping. Then provide the full structured analysis."""

    # Build conversation messages
    messages = [
        {"role": "user", "parts": [{"text": user_prompt}]},
    ]

    payload = {
        "systemInstruction": {"parts": [{"text": _SYSTEM_PROMPT}]},
        "contents": messages,
        "tools": TOOLS,
        "generationConfig": {
            "temperature": 0.0,
            "maxOutputTokens": 8192,
        },
    }

    pipeline_meta = {
        "stages_run": ["skill_pipeline"],
        "timings": {},
        "medcat_entities": [],
        "after_negation_filter": [],
        "candidate_codes": [],
        "tool_calls": [],
        "note_truncated": _note_was_truncated,
        "note_chars_original": original_len,
        "note_chars_submitted": submitted_len,
        "llm_input": {
            "model": model,
            "patient_age": patient_age,
            "patient_sex": patient_sex,
            "medications": medications[:20] if medications else [],
            "existing_hccs": existing_hccs or [],
            "problem_list": [
                {"title": p.get("title", ""), "diagnosis": p.get("diagnosis", "")}
                for p in (problem_list or [])[:30]
            ],
            "recapture_gaps": [
                {"title": g.get("title", ""), "diagnosis": g.get("diagnosis", "")}
                for g in (recapture_gaps or [])[:20]
            ],
            "latest_vitals": latest_vitals or {},
            "med_diagnoses": [
                {"drug": m.get("drug", ""), "note": m.get("note", "")}
                for m in (med_diagnoses or [])[:20]
            ],
            "clinical_note_chars": submitted_len,
            "clinical_note_preview": note_text[:500] + ("..." if len(note_text) > 500 else ""),
            "temperature": 0.0,
            "max_output_tokens": 8192,
        },
    }

    try:
        # Multi-turn: keep calling until Gemini returns text (not tool calls)
        max_turns = 10
        for turn in range(max_turns):
            # Acquire a rate-limit token before every Gemini HTTP request.
            # This covers both the initial turn and any subsequent tool-call
            # turns so that batch processing cannot exceed the configured quota.
            if not gemini_limiter.acquire(timeout=30.0):
                logger.warning(
                    "[Skill Pipeline] Gemini rate-limit token not acquired within "
                    "30 s on turn %d — falling back to Stage 1 rule-based result.",
                    turn,
                )
                raise RuntimeError(
                    "Gemini rate-limit timeout: request queue is saturated. "
                    "Increase GEMINI_RATE_LIMIT_RPS or reduce batch concurrency."
                )
            t_start = time.time()
            data = llm_generate_content(payload, model=model, timeout=180)
            t_elapsed = time.time() - t_start

            candidates = data.get("candidates", [])
            if not candidates:
                logger.warning("[Skill Pipeline] No candidates on turn %d", turn)
                break

            content = candidates[0].get("content", {})
            parts = content.get("parts", [])

            # Check if Gemini wants to call tools
            function_calls = [p for p in parts if "functionCall" in p]
            text_parts = [p for p in parts if "text" in p]

            if function_calls:
                # Execute tool calls and send results back
                tool_responses = []
                for fc in function_calls:
                    fn = fc["functionCall"]
                    fn_name = fn["name"]
                    fn_args = fn.get("args", {})

                    handler = _TOOL_HANDLERS.get(fn_name)
                    if handler:
                        result = handler(fn_args)
                        pipeline_meta["tool_calls"].append({
                            "function": fn_name,
                            "args": fn_args,
                            "result": result,
                        })
                        logger.info("[Skill] %s(%s) → %s", fn_name, fn_args,
                                   json.dumps(result)[:100])
                    else:
                        result = {"error": f"Unknown function: {fn_name}"}

                    tool_responses.append({
                        "functionResponse": {
                            "name": fn_name,
                            "response": result,
                        }
                    })

                # Add model's response and tool results to conversation
                messages.append(content)  # model's turn with function calls
                messages.append({"role": "user", "parts": tool_responses})

                payload["contents"] = messages
                pipeline_meta["timings"][f"turn_{turn}"] = round(t_elapsed, 2)
                continue

            if text_parts:
                # Gemini returned final text answer
                raw_text = text_parts[0].get("text", "")
                pipeline_meta["timings"][f"turn_{turn}"] = round(t_elapsed, 2)
                pipeline_meta["timings"]["total"] = round(time.time() - total_start, 2)

                # Parse the JSON result
                result = _parse_result(raw_text)

                # --- Excludes1 advisory check -----------------------------------
                # Collect all confirmed ICD-10 codes from the diagnosis list and
                # run a pairwise Excludes1 check.  Conflicts are advisory only;
                # they are appended to coding_notes and stored under
                # result["excludes1_warnings"] so the frontend can surface them
                # without blocking the encounter.
                confirmed_codes = [
                    d.get("icd10", "")
                    for d in result.get("diagnoses", [])
                    if d.get("icd10")
                ]
                excludes1_warnings = validate_code_set(confirmed_codes)
                result["excludes1_warnings"] = excludes1_warnings
                if excludes1_warnings:
                    warning_summary = "; ".join(w["message"] for w in excludes1_warnings)
                    logger.warning(
                        "[Skill Pipeline] Excludes1 conflicts detected: %s",
                        warning_summary,
                    )
                    existing_notes = result.get("coding_notes", "") or ""
                    result["coding_notes"] = (
                        f"{existing_notes} | CODING WARNING: {warning_summary}"
                        if existing_notes
                        else f"CODING WARNING: {warning_summary}"
                    )
                # ----------------------------------------------------------------

                result["pipeline"] = pipeline_meta
                if _note_was_truncated:
                    result["_note_truncated"] = True
                    result["_note_original_length"] = original_len
                    result["_note_submitted_length"] = submitted_len
                result["_meta"] = {
                    "pipeline_version": "skill_v1",
                    "total_time_seconds": pipeline_meta["timings"]["total"],
                    "stages": ["skill_pipeline"],
                    "tool_calls_count": len(pipeline_meta["tool_calls"]),
                    "turns": turn + 1,
                    "timings": pipeline_meta["timings"],
                }

                # Build NER-compatible entities for frontend
                result["pipeline"]["medcat_entities"] = [
                    {
                        "text": dx.get("description", ""),
                        "name": dx.get("description", ""),
                        "icd10": dx.get("icd10", ""),
                        "confidence": dx.get("confidence", 0.85),
                        "negated": False,
                        "category": "disease",
                        "source": "skill_pipeline",
                    }
                    for dx in result.get("diagnoses", [])
                ]
                result["pipeline"]["after_negation_filter"] = result["pipeline"]["medcat_entities"]

                # Confidence routing
                dx = result.get("diagnoses", [])
                if dx:
                    avg_conf = sum(d.get("confidence", 0) for d in dx) / len(dx)
                    hcc_count = sum(1 for d in dx if d.get("hcc"))
                else:
                    avg_conf = 0
                    hcc_count = 0

                # Retrieve interaction terms from hccinfhir's calculate_raf_score result.
                # hccinfhir already applies all CMS interaction logic internally, so we
                # source interaction data from there instead of a separate DB query against
                # hcc_interaction_terms, which would double-count the same terms.
                raf_tool_result = next(
                    (tc["result"] for tc in pipeline_meta["tool_calls"] if tc["function"] == "calculate_raf_score"),
                    None,
                )
                hccinfhir_interactions: dict = (raf_tool_result or {}).get("interactions", {})
                interaction_bonus: float = round((raf_tool_result or {}).get("interaction_score", 0.0), 4)

                for term, coeff in hccinfhir_interactions.items():
                    logger.info("[Skill Pipeline] Interaction (hccinfhir): %s (+%.3f)", term, coeff)

                if avg_conf >= 0.85 and hcc_count > 0:
                    routing = "auto_accept"
                elif avg_conf >= 0.70:
                    routing = "human_review"
                else:
                    routing = "full_audit"

                # Ensure each diagnosis has a source field
                for d in dx:
                    d.setdefault("source", "skill_pipeline")

                # Append interaction info to coding_notes for display purposes.
                # The terms and score are sourced from hccinfhir (already included in the
                # calculate_raf_score tool result) so no separate recalculation is needed.
                if interaction_bonus > 0:
                    existing_notes = result.get("coding_notes", "")
                    result["coding_notes"] = f"{existing_notes} | Disease interactions: +{interaction_bonus:.3f} RAF"

                result["interaction_bonus"] = interaction_bonus
                result["interaction_terms"] = hccinfhir_interactions
                result["overall_confidence"] = round(avg_conf, 3)
                result["confidence_routing"] = {
                    "routing": routing,
                    "overall_confidence": round(avg_conf, 3),
                    "hcc_count": hcc_count,
                    "interaction_bonus": interaction_bonus,
                    "interaction_terms": hccinfhir_interactions,
                    "agreement_score": round(avg_conf, 3),
                }

                logger.info(
                    "[Skill Pipeline] Complete in %.1fs: %d diagnoses, %d HCC, %d tool calls, %d turns",
                    pipeline_meta["timings"]["total"], len(dx), hcc_count,
                    len(pipeline_meta["tool_calls"]), turn + 1,
                )
                return result

            logger.warning("[Skill Pipeline] No text or function calls on turn %d", turn)
            break

    except Exception as exc:
        logger.error("[Skill Pipeline] Failed: %s", exc)

    # Fallback empty result
    pipeline_meta["timings"]["total"] = round(time.time() - total_start, 2)
    return {
        "diagnoses": [],
        "suspect_conditions": [],
        "negated_conditions": [],
        "pipeline": pipeline_meta,
        "overall_confidence": 0,
        "confidence_routing": {"routing": "full_audit", "overall_confidence": 0, "hcc_count": 0},
        "_meta": {"pipeline_version": "skill_v1", "total_time_seconds": pipeline_meta["timings"]["total"]},
    }


def _parse_result(raw_text: str) -> dict:
    """Parse Gemini's final JSON response, handling truncation and markdown."""
    text = raw_text.strip()

    # Remove markdown code fences
    if text.startswith("```json"):
        text = text[7:]
    elif text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text[3:]
    if text.endswith("```"):
        text = text[:-3]
    text = text.strip()

    # Try direct parse first
    try:
        result = json.loads(text)
        if isinstance(result, dict):
            return result
    except json.JSONDecodeError:
        pass

    # Try progressively fixing truncated JSON
    # Find the last valid closing brace/bracket
    for i in range(len(text) - 1, 0, -1):
        if text[i] == '}':
            candidate = text[:i+1]
            # Count braces to check balance
            opens = candidate.count('{')
            closes = candidate.count('}')
            if opens > closes:
                candidate += '}' * (opens - closes)
            try:
                result = json.loads(candidate)
                if isinstance(result, dict):
                    logger.info("[Skill Pipeline] Recovered truncated JSON at position %d/%d", i, len(text))
                    return result
            except json.JSONDecodeError:
                continue

    logger.warning("[Skill Pipeline] Could not parse JSON response (%d chars)", len(text))
    return {"diagnoses": [], "suspect_conditions": [], "negated_conditions": []}
