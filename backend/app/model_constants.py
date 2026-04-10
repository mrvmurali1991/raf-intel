"""
Risk adjustment model constants: ICD mappings, coefficient tables, and
demographic base scores for RxHCC and HHS-HCC models.

WARNING — PLACEHOLDER DATA
--------------------------
The mapping tables and coefficients in this module are PLACEHOLDER values
derived from publicly available CMS / HHS Rate Notice documentation. They
are representative only and are NOT the official CMS / HHS crosswalks.

Before these values can be used for anything beyond internal analytics and
gap identification they MUST be replaced with the official CMS / HHS
crosswalks sourced directly from:
  - CMS Part C/D Risk Adjustment Model Software (CMS.gov)
  - CMS Advance Notice / Rate Announcement for the relevant payment year
  - HHS Notice of Benefit and Payment Parameters (45 CFR 153) for HHS-HCC

Long-term these tables SHOULD live in versioned database tables (one row
per payment year + model version) so that calculations can be reproduced
historically. Until that migration happens this module is the single
source of truth — do NOT duplicate these constants in other files; always
import from here.

Sources (informational, non-authoritative):
  - CMS CY2023 Part D Benefit Parameters and Risk Adjustment Factors
  - HHS Notice of Benefit and Payment Parameters 2024
  - CMS Advance Notice CY2026 (placeholder for CY2026 coefficients)
"""
from __future__ import annotations

from typing import Any

# ---------------------------------------------------------------------------
# RxHCC Coefficient Tables (CY2023 Part D Risk Adjustment — PLACEHOLDER)
# Source: CMS CY2023 Part D Benefit Parameters and Risk Adjustment Factors
# These are representative coefficients for the most clinically significant
# RxHCC categories. Full tables have ~200 entries. Replace with the official
# CMS crosswalk before use in production.
# ---------------------------------------------------------------------------

# RxHCC ICD-10 → RxHCC mapping (PLACEHOLDER — not the official CMS crosswalk)
# Format: icd_prefix: rxhcc_number
RXHCC_ICD_MAP: dict[str, int] = {
    # RxHCC 1 — Opportunistic Infections
    "B37": 1, "B38": 1, "B44": 1, "B45": 1, "B46": 1, "B48": 1,
    # RxHCC 5 — HIV/AIDS
    "B20": 5, "Z21": 5,
    # RxHCC 15 — Diabetes with Chronic Complications
    "E1040": 15, "E1041": 15, "E1042": 15, "E1043": 15, "E1044": 15,
    "E1051": 15, "E1052": 15, "E1065": 15,
    "E1140": 15, "E1141": 15, "E1142": 15, "E1143": 15, "E1144": 15,
    "E1340": 15, "E1341": 15, "E1342": 15,
    # RxHCC 16 — Diabetes with Acute Complications
    "E1000": 16, "E1001": 16, "E1010": 16, "E1011": 16,
    "E1100": 16, "E1101": 16, "E1110": 16, "E1111": 16,
    # RxHCC 17 — Diabetes without Complications (Type 2)
    "E11": 17, "E119": 17, "E13": 17,
    # RxHCC 18 — Diabetes without Complications (Type 1)
    "E10": 18, "E109": 18,
    # RxHCC 19 — Diabetes, not otherwise specified
    "E08": 19, "E09": 19,
    # RxHCC 31 — Chronic Hepatitis
    "B18": 31, "K750": 31, "K751": 31,
    # RxHCC 32 — Acute Liver Failure / End Stage Liver Disease
    "K720": 32, "K721": 32, "K729": 32, "K717": 32,
    # RxHCC 33 — Cirrhosis of Liver
    "K703": 33, "K704": 33, "K74": 33,
    # RxHCC 40 — Inflammatory Bowel Disease
    "K50": 40, "K51": 40, "K522": 40,
    # RxHCC 45 — Bone/Joint/Muscle Infections, Necrosis
    "M8600": 45, "M8661": 45, "M860": 45, "M870": 45,
    # RxHCC 54 — Rheumatoid Arthritis and Inflammatory CTD
    "M05": 54, "M06": 54, "M08": 54, "M32": 54, "M33": 54, "M34": 54,
    "M35": 54, "M45": 54, "M46": 54,
    # RxHCC 55 — Systemic Lupus Erythematosus, Other CTD
    "M30": 55, "M310": 55, "M312": 55, "M313": 55,
    # RxHCC 60 — Inflammatory Spondylopathies
    "M07": 60, "M09": 60,
    # RxHCC 67 — Psoriasis
    "L40": 67, "L41": 67,
    # RxHCC 68 — Pemphigus / Pemphigoid
    "L10": 68, "L12": 68, "L13": 68,
    # RxHCC 72 — Multiple Sclerosis
    "G35": 72,
    # RxHCC 75 — Myasthenia Gravis / Myoneural Disorders
    "G70": 75, "G71": 75, "G72": 75,
    # RxHCC 76 — Huntington's Disease / Other CNS
    "G10": 76,
    # RxHCC 77 — Amyotrophic Lateral Sclerosis
    "G122": 77,
    # RxHCC 79 — Paraplegia / Quadriplegia
    "G81": 79, "G82": 79,
    # RxHCC 80 — Congestive Heart Failure
    "I500": 80, "I501": 80, "I502": 80, "I503": 80,
    "I5020": 80, "I5021": 80, "I5022": 80, "I5023": 80,
    "I5030": 80, "I5031": 80, "I5032": 80, "I5033": 80,
    "I5040": 80, "I5041": 80, "I5042": 80, "I5043": 80,
    # RxHCC 82 — Coronary Artery Disease / Angina
    "I20": 82, "I21": 82, "I22": 82, "I25": 82,
    # RxHCC 83 — Atrial Fibrillation and Other Arrhythmias
    "I48": 83,
    # RxHCC 84 — Specified Heart Arrhythmias
    "I44": 84, "I45": 84, "I46": 84, "I47": 84, "I49": 84,
    # RxHCC 87 — Hypertension
    "I10": 87, "I11": 87, "I12": 87, "I13": 87,
    # RxHCC 88 — Heart Valve Disorders
    "I05": 88, "I06": 88, "I07": 88, "I08": 88, "I34": 88, "I35": 88,
    # RxHCC 96 — Chronic Obstructive Pulmonary Disease
    "J40": 96, "J41": 96, "J42": 96, "J43": 96, "J44": 96,
    # RxHCC 103 — Fibrosis of Lung / Other Chronic Lung Disorders
    "J70": 103, "J84": 103, "J98": 103,
    # RxHCC 108 — Asthma
    "J45": 108, "J46": 108,
    # RxHCC 110 — Pulmonary Hypertension
    "I270": 110, "I272": 110,
    # RxHCC 112 — Cystic Fibrosis
    "E84": 112,
    # RxHCC 130 — Chronic Kidney Disease, Stage 5
    "N185": 130, "N186": 130, "Z992": 130,
    # RxHCC 131 — Chronic Kidney Disease, Severe (Stage 4)
    "N184": 131,
    # RxHCC 132 — Chronic Kidney Disease, Moderate (Stage 3)
    "N183": 132,
    # RxHCC 133 — Chronic Kidney Disease, Mild or Unspecified
    "N181": 133, "N182": 133, "N189": 133,
    # RxHCC 134 — Nephritis
    "N00": 134, "N01": 134, "N02": 134, "N03": 134, "N04": 134, "N05": 134,
    # RxHCC 139 — Kidney Transplant Status
    "Z940": 139, "T8610": 139, "T8611": 139, "T8612": 139,
    # RxHCC 143 — Immune Disorders
    "D80": 143, "D81": 143, "D82": 143, "D83": 143, "D84": 143,
    # RxHCC 144 — Coagulation Defects
    "D65": 144, "D66": 144, "D67": 144, "D68": 144, "D69": 144,
    # RxHCC 145 — Nutritional / Other Anemias
    "D50": 145, "D51": 145, "D52": 145, "D53": 145,
    # RxHCC 156 — Thyroid Disorders
    "E00": 156, "E01": 156, "E02": 156, "E03": 156, "E04": 156,
    "E05": 156, "E06": 156, "E07": 156,
    # RxHCC 159 — Osteoporosis and Vertebral Fractures
    "M80": 159, "M81": 159,
    # RxHCC 160 — Hip Fracture
    "S72": 160,
    # RxHCC 161 — Pathological Fractures
    "M844": 161, "M845": 161,
    # RxHCC 166 — Morbid Obesity
    "E6601": 166, "E660": 166,
    # RxHCC 183 — Epilepsy and Convulsions
    "G40": 183, "G41": 183,
    # RxHCC 184 — Alzheimer's Disease
    "G30": 184, "G311": 184,
    # RxHCC 185 — Dementia, Except Alzheimer's
    "F01": 185, "F02": 185, "F03": 185, "G310": 185,
    # RxHCC 186 — Parkinson's Disease
    "G20": 186, "G21": 186,
    # RxHCC 187 — Huntington's / Cerebellar Ataxia
    "G11": 187,
    # RxHCC 193 — Depression
    "F32": 193, "F33": 193,
    # RxHCC 200 — Schizophrenia
    "F20": 200, "F21": 200, "F25": 200,
    # RxHCC 201 — Bipolar Disorder
    "F30": 201, "F31": 201,
    # RxHCC 204 — Major Depressive Disorder, Severe
    "F322": 204, "F323": 204, "F332": 204, "F333": 204,
    # RxHCC 211 — Lung, Upper Digestive Tract, and Other Severe Cancers
    "C34": 211, "C15": 211, "C16": 211, "C22": 211, "C25": 211,
    "C26": 211, "C30": 211, "C31": 211, "C32": 211, "C33": 211,
    # RxHCC 212 — Lymphatic, Head and Neck, Brain, and Other Major Cancers
    "C00": 212, "C01": 212, "C02": 212, "C70": 212, "C71": 212,
    "C72": 212, "C81": 212, "C82": 212, "C83": 212, "C84": 212,
    "C91": 212, "C92": 212, "C93": 212, "C94": 212,
    # RxHCC 213 — Breast, Prostate, Colorectal and Other Cancers
    "C18": 213, "C19": 213, "C20": 213, "C50": 213, "C61": 213,
    "C43": 213, "C54": 213, "C55": 213, "C56": 213,
    # RxHCC 217 — Secondary Malignancies
    "C77": 217, "C78": 217, "C79": 217, "C80": 217,
    # RxHCC 249 — Sickle Cell Anemia
    "D570": 249, "D571": 249, "D572": 249,
    # RxHCC 253 — Hemophilia
    "D680": 253, "D681": 253, "D682": 253,
    # RxHCC 258 — Drug / Alcohol Dependence
    "F10": 258, "F11": 258, "F12": 258, "F13": 258, "F14": 258, "F15": 258,
}

# RxHCC Coefficient Tables by age/sex category (CY2023 representative values — PLACEHOLDER)
# Segments: LI=Low Income, NLI=Non-Low Income; Sex: M/F; Age bands
# Format: rxhcc_number → {"description": str, "NLI_F": float, "NLI_M": float, "LI_F": float, "LI_M": float}
RXHCC_COEFFICIENTS: dict[int, dict[str, Any]] = {
    1:   {"description": "Opportunistic Infections",                 "NLI_F": 2.145, "NLI_M": 2.301, "LI_F": 1.892, "LI_M": 2.054},
    5:   {"description": "HIV/AIDS",                                "NLI_F": 3.821, "NLI_M": 4.103, "LI_F": 3.412, "LI_M": 3.698},
    15:  {"description": "Diabetes with Chronic Complications",      "NLI_F": 0.512, "NLI_M": 0.589, "LI_F": 0.476, "LI_M": 0.541},
    16:  {"description": "Diabetes with Acute Complications",        "NLI_F": 0.388, "NLI_M": 0.421, "LI_F": 0.352, "LI_M": 0.385},
    17:  {"description": "Type 2 Diabetes without Complications",    "NLI_F": 0.201, "NLI_M": 0.218, "LI_F": 0.187, "LI_M": 0.203},
    18:  {"description": "Type 1 Diabetes without Complications",    "NLI_F": 0.312, "NLI_M": 0.334, "LI_F": 0.289, "LI_M": 0.311},
    19:  {"description": "Diabetes, NOS",                           "NLI_F": 0.178, "NLI_M": 0.192, "LI_F": 0.162, "LI_M": 0.176},
    31:  {"description": "Chronic Hepatitis",                        "NLI_F": 1.234, "NLI_M": 1.456, "LI_F": 1.089, "LI_M": 1.298},
    32:  {"description": "Acute / End Stage Liver Disease",          "NLI_F": 2.145, "NLI_M": 2.312, "LI_F": 1.923, "LI_M": 2.078},
    33:  {"description": "Cirrhosis of Liver",                       "NLI_F": 1.456, "NLI_M": 1.623, "LI_F": 1.298, "LI_M": 1.445},
    40:  {"description": "Inflammatory Bowel Disease",               "NLI_F": 1.089, "NLI_M": 1.102, "LI_F": 0.956, "LI_M": 0.978},
    45:  {"description": "Bone/Joint/Muscle Infections, Necrosis",   "NLI_F": 0.867, "NLI_M": 0.934, "LI_F": 0.767, "LI_M": 0.823},
    54:  {"description": "Rheumatoid Arthritis and Inflammatory CTD", "NLI_F": 0.987, "NLI_M": 0.834, "LI_F": 0.876, "LI_M": 0.743},
    55:  {"description": "Systemic Lupus, Other CTD",                "NLI_F": 1.123, "NLI_M": 0.934, "LI_F": 0.998, "LI_M": 0.821},
    60:  {"description": "Inflammatory Spondylopathies (PsA/AS)",    "NLI_F": 1.456, "NLI_M": 1.389, "LI_F": 1.298, "LI_M": 1.234},
    67:  {"description": "Psoriasis",                                "NLI_F": 0.756, "NLI_M": 0.789, "LI_F": 0.672, "LI_M": 0.703},
    68:  {"description": "Pemphigus / Pemphigoid",                   "NLI_F": 0.912, "NLI_M": 0.867, "LI_F": 0.812, "LI_M": 0.769},
    72:  {"description": "Multiple Sclerosis",                       "NLI_F": 2.456, "NLI_M": 2.312, "LI_F": 2.198, "LI_M": 2.076},
    75:  {"description": "Myasthenia Gravis / Myoneural Disorders",  "NLI_F": 1.678, "NLI_M": 1.534, "LI_F": 1.489, "LI_M": 1.367},
    76:  {"description": "Huntington's / CNS Degenerative",          "NLI_F": 1.234, "NLI_M": 1.345, "LI_F": 1.098, "LI_M": 1.212},
    77:  {"description": "Amyotrophic Lateral Sclerosis (ALS)",      "NLI_F": 2.678, "NLI_M": 2.812, "LI_F": 2.398, "LI_M": 2.534},
    79:  {"description": "Paraplegia / Quadriplegia",                "NLI_F": 1.456, "NLI_M": 1.578, "LI_F": 1.298, "LI_M": 1.412},
    80:  {"description": "Congestive Heart Failure",                 "NLI_F": 0.678, "NLI_M": 0.712, "LI_F": 0.601, "LI_M": 0.634},
    82:  {"description": "Coronary Artery Disease / Angina",         "NLI_F": 0.423, "NLI_M": 0.456, "LI_F": 0.378, "LI_M": 0.409},
    83:  {"description": "Atrial Fibrillation",                      "NLI_F": 0.389, "NLI_M": 0.412, "LI_F": 0.345, "LI_M": 0.368},
    84:  {"description": "Specified Heart Arrhythmias",              "NLI_F": 0.312, "NLI_M": 0.334, "LI_F": 0.278, "LI_M": 0.298},
    87:  {"description": "Hypertension",                             "NLI_F": 0.145, "NLI_M": 0.162, "LI_F": 0.129, "LI_M": 0.144},
    88:  {"description": "Heart Valve Disorders",                    "NLI_F": 0.378, "NLI_M": 0.401, "LI_F": 0.334, "LI_M": 0.356},
    96:  {"description": "COPD",                                     "NLI_F": 0.498, "NLI_M": 0.523, "LI_F": 0.443, "LI_M": 0.467},
    103: {"description": "Fibrosis of Lung / Chronic Lung Disorders","NLI_F": 0.756, "NLI_M": 0.812, "LI_F": 0.672, "LI_M": 0.723},
    108: {"description": "Asthma",                                   "NLI_F": 0.287, "NLI_M": 0.256, "LI_F": 0.256, "LI_M": 0.228},
    110: {"description": "Pulmonary Hypertension",                   "NLI_F": 1.234, "NLI_M": 1.189, "LI_F": 1.098, "LI_M": 1.056},
    112: {"description": "Cystic Fibrosis",                          "NLI_F": 4.123, "NLI_M": 3.987, "LI_F": 3.756, "LI_M": 3.612},
    130: {"description": "Chronic Kidney Disease, Stage 5 / ESRD",  "NLI_F": 1.456, "NLI_M": 1.523, "LI_F": 1.298, "LI_M": 1.367},
    131: {"description": "Chronic Kidney Disease, Stage 4",          "NLI_F": 0.567, "NLI_M": 0.601, "LI_F": 0.507, "LI_M": 0.537},
    132: {"description": "Chronic Kidney Disease, Stage 3",          "NLI_F": 0.312, "NLI_M": 0.334, "LI_F": 0.278, "LI_M": 0.298},
    133: {"description": "Chronic Kidney Disease, Mild/Unspecified", "NLI_F": 0.198, "NLI_M": 0.212, "LI_F": 0.176, "LI_M": 0.190},
    134: {"description": "Nephritis",                                "NLI_F": 0.267, "NLI_M": 0.289, "LI_F": 0.238, "LI_M": 0.258},
    139: {"description": "Kidney Transplant Status",                 "NLI_F": 0.912, "NLI_M": 0.956, "LI_F": 0.812, "LI_M": 0.856},
    143: {"description": "Immune Disorders",                        "NLI_F": 1.123, "NLI_M": 1.056, "LI_F": 0.998, "LI_M": 0.934},
    144: {"description": "Coagulation Defects / Hemorrhagic Disorders","NLI_F": 0.823, "NLI_M": 0.867, "LI_F": 0.734, "LI_M": 0.774},
    145: {"description": "Nutritional / Other Anemias",              "NLI_F": 0.345, "NLI_M": 0.312, "LI_F": 0.312, "LI_M": 0.278},
    156: {"description": "Thyroid Disorders",                        "NLI_F": 0.189, "NLI_M": 0.145, "LI_F": 0.167, "LI_M": 0.129},
    159: {"description": "Osteoporosis and Vertebral Fractures",     "NLI_F": 0.289, "NLI_M": 0.267, "LI_F": 0.256, "LI_M": 0.238},
    160: {"description": "Hip Fracture / Dislocation",               "NLI_F": 0.512, "NLI_M": 0.489, "LI_F": 0.456, "LI_M": 0.434},
    161: {"description": "Pathological Fractures",                   "NLI_F": 0.423, "NLI_M": 0.401, "LI_F": 0.378, "LI_M": 0.356},
    166: {"description": "Morbid Obesity (BMI >= 40)",               "NLI_F": 0.289, "NLI_M": 0.312, "LI_F": 0.256, "LI_M": 0.278},
    183: {"description": "Epilepsy and Convulsions",                 "NLI_F": 0.645, "NLI_M": 0.678, "LI_F": 0.576, "LI_M": 0.607},
    184: {"description": "Alzheimer's Disease",                      "NLI_F": 0.812, "NLI_M": 0.756, "LI_F": 0.723, "LI_M": 0.678},
    185: {"description": "Dementia, Except Alzheimer's",             "NLI_F": 0.723, "NLI_M": 0.698, "LI_F": 0.645, "LI_M": 0.623},
    186: {"description": "Parkinson's Disease",                      "NLI_F": 1.189, "NLI_M": 1.234, "LI_F": 1.056, "LI_M": 1.103},
    187: {"description": "Huntington's / Cerebellar Ataxia",         "NLI_F": 1.567, "NLI_M": 1.612, "LI_F": 1.398, "LI_M": 1.445},
    193: {"description": "Depression",                               "NLI_F": 0.267, "NLI_M": 0.234, "LI_F": 0.238, "LI_M": 0.209},
    200: {"description": "Schizophrenia",                            "NLI_F": 0.823, "NLI_M": 0.867, "LI_F": 0.734, "LI_M": 0.774},
    201: {"description": "Bipolar Disorder",                         "NLI_F": 0.534, "NLI_M": 0.512, "LI_F": 0.476, "LI_M": 0.456},
    204: {"description": "Major Depressive Disorder, Severe",        "NLI_F": 0.423, "NLI_M": 0.401, "LI_F": 0.378, "LI_M": 0.356},
    211: {"description": "Lung and Other Severe Cancers",            "NLI_F": 2.678, "NLI_M": 2.812, "LI_F": 2.398, "LI_M": 2.523},
    212: {"description": "Lymphatic, Brain and Other Major Cancers", "NLI_F": 3.123, "NLI_M": 3.267, "LI_F": 2.789, "LI_M": 2.934},
    213: {"description": "Breast, Prostate, Colorectal Cancers",    "NLI_F": 1.456, "NLI_M": 1.389, "LI_F": 1.298, "LI_M": 1.234},
    217: {"description": "Secondary Malignancies",                   "NLI_F": 2.234, "NLI_M": 2.312, "LI_F": 1.989, "LI_M": 2.067},
    249: {"description": "Sickle Cell Anemia / Hb-SS",              "NLI_F": 1.789, "NLI_M": 1.834, "LI_F": 1.598, "LI_M": 1.645},
    253: {"description": "Hemophilia and Coagulation Factor Defects","NLI_F": 3.456, "NLI_M": 3.512, "LI_F": 3.089, "LI_M": 3.145},
    258: {"description": "Drug / Alcohol Dependence",                "NLI_F": 0.267, "NLI_M": 0.289, "LI_F": 0.238, "LI_M": 0.258},
}

# RxHCC demographic base scores by age/sex/LIS status (CY2023 PLACEHOLDER values)
# Format: (age_band, sex, lis_status) → base_score
# lis_status: "NLI" = Non-Low Income, "LI" = Low Income Subsidy
RXHCC_DEMO_SCORES: dict[tuple[str, str, str], float] = {
    # Non-Low-Income Female
    ("0-34",  "F", "NLI"): 0.201, ("35-44", "F", "NLI"): 0.223,
    ("45-54", "F", "NLI"): 0.267, ("55-59", "F", "NLI"): 0.312,
    ("60-64", "F", "NLI"): 0.389, ("65-69", "F", "NLI"): 0.423,
    ("70-74", "F", "NLI"): 0.489, ("75-79", "F", "NLI"): 0.567,
    ("80-84", "F", "NLI"): 0.634, ("85+",   "F", "NLI"): 0.712,
    # Non-Low-Income Male
    ("0-34",  "M", "NLI"): 0.189, ("35-44", "M", "NLI"): 0.212,
    ("45-54", "M", "NLI"): 0.256, ("55-59", "M", "NLI"): 0.298,
    ("60-64", "M", "NLI"): 0.367, ("65-69", "M", "NLI"): 0.412,
    ("70-74", "M", "NLI"): 0.478, ("75-79", "M", "NLI"): 0.556,
    ("80-84", "M", "NLI"): 0.623, ("85+",   "M", "NLI"): 0.701,
    # Low-Income Female
    ("0-34",  "F", "LI"):  0.223, ("35-44", "F", "LI"):  0.248,
    ("45-54", "F", "LI"):  0.297, ("55-59", "F", "LI"):  0.347,
    ("60-64", "F", "LI"):  0.432, ("65-69", "F", "LI"):  0.470,
    ("70-74", "F", "LI"):  0.543, ("75-79", "F", "LI"):  0.630,
    ("80-84", "F", "LI"):  0.705, ("85+",   "F", "LI"):  0.792,
    # Low-Income Male
    ("0-34",  "M", "LI"):  0.210, ("35-44", "M", "LI"):  0.236,
    ("45-54", "M", "LI"):  0.284, ("55-59", "M", "LI"):  0.331,
    ("60-64", "M", "LI"):  0.408, ("65-69", "M", "LI"):  0.458,
    ("70-74", "M", "LI"):  0.531, ("75-79", "M", "LI"):  0.618,
    ("80-84", "M", "LI"):  0.692, ("85+",   "M", "LI"):  0.779,
}

# ---------------------------------------------------------------------------
# HHS-HCC Coefficient Tables (HHS Notice of Benefit and Payment Parameters 2024)
# Source: 45 CFR 153, HHS-HCC Adult Model (non-tobacco) — PLACEHOLDER values.
# Replace with the official HHS-HCC crosswalk (do-not-use stub) before
# production deployment.
# ---------------------------------------------------------------------------

# HHS-HCC ICD-10 → HHS-HCC mapping (PLACEHOLDER — not the official HHS crosswalk)
# Format: icd_prefix: hhs_hcc_number
HHSHCC_ICD_MAP: dict[str, int] = {
    # HCC 1 — HIV/AIDS
    "B20": 1, "Z21": 1, "B97.35": 1,
    # HCC 2 — Septicemia, Sepsis, Systemic Inflammatory Response Syndrome/Shock
    "A40": 2, "A41": 2, "R65": 2,
    # HCC 6 — Opportunistic Infections
    "B37": 6, "B38": 6, "B44": 6, "B45": 6,
    # HCC 8 — Metastatic Cancer and Acute Leukemia
    "C77": 8, "C78": 8, "C79": 8, "C80": 8, "C91": 8, "C92": 8, "C93": 8,
    # HCC 9 — Lung, Brain, and Other Severe Cancers
    "C34": 9, "C70": 9, "C71": 9, "C72": 9,
    # HCC 10 — Non-Hodgkin's Lymphomas and Other Cancers and Tumors
    "C81": 10, "C82": 10, "C83": 10, "C84": 10, "C85": 10,
    # HCC 11 — Colorectal, Bladder, and Other Cancers and Tumors
    "C18": 11, "C19": 11, "C20": 11, "C67": 11,
    # HCC 12 — Breast, Prostate, Endometrial and Other Cancers and Tumors
    "C50": 12, "C54": 12, "C55": 12, "C61": 12,
    # HCC 13 — Thyroid Cancer, Melanoma, Neurofibromatosis, and Other Tumors
    "C43": 13, "C73": 13, "Q85": 13,
    # HCC 18 — Diabetes with Chronic Complications
    "E1040": 18, "E1041": 18, "E1042": 18, "E1043": 18, "E1044": 18,
    "E1140": 18, "E1141": 18, "E1142": 18, "E1143": 18, "E1144": 18,
    "E1051": 18, "E1052": 18,
    # HCC 19 — Diabetes without Complication
    "E10": 19, "E11": 19, "E13": 19, "E119": 19, "E109": 19,
    # HCC 20 — Diabetes, Type 1 (non-complicated)
    "E1009": 20, "E1065": 20,
    # HCC 23 — Protein-Calorie Malnutrition
    "E40": 23, "E41": 23, "E42": 23, "E43": 23, "E44": 23, "E45": 23, "E46": 23,
    # HCC 24 — Eating and Feeding Disorders
    "F50": 24, "F982": 24, "F983": 24,
    # HCC 25 — Disorders of Fluid, Electrolyte, Acid-Base Balance
    "E86": 25, "E87": 25,
    # HCC 26 — Other Significant Endocrine and Metabolic Disorders
    "E20": 26, "E21": 26, "E22": 26, "E23": 26, "E24": 26, "E25": 26,
    # HCC 27 — End Stage Liver Disease
    "K704": 27, "K717": 27, "K721": 27, "K729": 27,
    # HCC 28 — Cirrhosis of Liver
    "K703": 28, "K74": 28,
    # HCC 29 — Hepatitis, Acute and Unspecified
    "B15": 29, "B16": 29, "B17": 29, "B18": 29,
    # HCC 30 — Inflammatory Liver Disease
    "K75": 30, "K760": 30,
    # HCC 33 — Inflammatory Bowel Disease
    "K50": 33, "K51": 33,
    # HCC 34 — Peptic Ulcer, Hemorrhage, Other GI Disorders
    "K25": 34, "K26": 34, "K27": 34, "K28": 34, "K922": 34,
    # HCC 35 — Appendicitis
    "K35": 35, "K36": 35, "K37": 35,
    # HCC 41 — Chronic Kidney Disease, Stage 5
    "N185": 41, "N186": 41, "Z992": 41,
    # HCC 42 — Chronic Kidney Disease, Severe (Stage 4)
    "N184": 42,
    # HCC 43 — Chronic Kidney Disease, Moderate (Stage 3)
    "N183": 43,
    # HCC 44 — Chronic Kidney Disease, Mild or Unspecified
    "N181": 44, "N182": 44, "N189": 44,
    # HCC 45 — Acute Renal Failure
    "N17": 45,
    # HCC 46 — Urinary Obstruction and Retention
    "N13": 46, "R33": 46,
    # HCC 47 — Kidney Transplant Status
    "Z940": 47,
    # HCC 54 — Drug/Alcohol Dependence
    "F10": 54, "F11": 54, "F12": 54, "F13": 54, "F14": 54, "F15": 54,
    # HCC 55 — Tobacco Use
    "F17": 55, "Z720": 55,
    # HCC 57 — Schizophrenia
    "F20": 57, "F21": 57, "F22": 57, "F25": 57,
    # HCC 58 — Major Depressive, Bipolar, and Paranoid Disorders
    "F30": 58, "F31": 58, "F32": 58, "F33": 58,
    # HCC 59 — Reactive and Unspecified Psychosis
    "F23": 59, "F28": 59, "F29": 59,
    # HCC 60 — Personality Disorders; Anorexia/Bulimia Nervosa
    "F60": 60, "F61": 60, "F501": 60, "F502": 60,
    # HCC 61 — Anxiety Disorders
    "F40": 61, "F41": 61, "F42": 61, "F43": 61,
    # HCC 62 — Attention Deficit / Autism
    "F84": 62, "F90": 62,
    # HCC 63 — Developmental Disorder, Intellectual Disability
    "F70": 63, "F71": 63, "F72": 63, "F73": 63, "F79": 63,
    # HCC 67 — Quadriplegia
    "G82": 67,
    # HCC 68 — Paraplegia
    "G8320": 68, "G8322": 68,
    # HCC 73 — Amyotrophic Lateral Sclerosis and Other Motor Neuron Disease
    "G12": 73,
    # HCC 74 — Cerebral Palsy
    "G80": 74,
    # HCC 75 — Myasthenia Gravis/Myoneural Disorders and Guillain-Barre
    "G70": 75, "G61": 75,
    # HCC 76 — Muscular Dystrophy
    "G71": 76,
    # HCC 77 — Multiple Sclerosis
    "G35": 77,
    # HCC 78 — Parkinson's and Huntington's Diseases
    "G20": 78, "G10": 78,
    # HCC 79 — Seizure Disorders and Convulsions
    "G40": 79, "G41": 79,
    # HCC 80 — Coma, Brain Compression/Anoxic Damage
    "G931": 80, "G934": 80,
    # HCC 82 — Respirator Dependence/Tracheostomy Status
    "J960": 82, "Z9911": 82,
    # HCC 83 — Respiratory Arrest; Carbon Monoxide Poisoning
    "J9600": 83,
    # HCC 84 — Cardio-Respiratory Failure and Shock
    "R00": 84, "R09": 84,
    # HCC 85 — Congestive Heart Failure
    "I500": 85, "I501": 85, "I502": 85, "I503": 85,
    "I5020": 85, "I5030": 85, "I5040": 85,
    # HCC 86 — Acute Myocardial Infarction
    "I21": 86, "I22": 86,
    # HCC 87 — Unstable Angina and Other Acute Ischemic Heart Disease
    "I200": 87,
    # HCC 88 — Angina Pectoris/Old Myocardial Infarction
    "I209": 88, "I25": 88,
    # HCC 90 — Chronic Heart Disease and Hypertensive HD
    "I11": 90, "I12": 90, "I13": 90,
    # HCC 96 — Specified Heart Arrhythmias
    "I44": 96, "I45": 96, "I46": 96, "I47": 96, "I48": 96, "I49": 96,
    # HCC 97 — Hypertension
    "I10": 97,
    # HCC 99 — Cerebral Hemorrhage
    "I60": 99, "I61": 99, "I62": 99,
    # HCC 100 — Ischemic or Unspecified Stroke
    "I63": 100, "I64": 100,
    # HCC 103 — Hemiplegia/Hemiparesis
    "G811": 103, "G812": 103,
    # HCC 104 — Monoplegia, Other Paralytic Syndromes
    "G830": 104, "G834": 104,
    # HCC 106 — Atherosclerosis with Ulceration or Gangrene
    "I7020": 106, "I7021": 106, "I7022": 106, "I7023": 106, "I7024": 106, "I7025": 106,
    # HCC 107 — Vascular Disease with Complications
    "I700": 107, "I701": 107, "I710": 107, "I711": 107, "I712": 107,
    # HCC 108 — Vascular Disease
    "I702": 108, "I738": 108, "I739": 108,
    # HCC 110 — Cystic Fibrosis
    "E84": 110,
    # HCC 111 — COPD
    "J40": 111, "J41": 111, "J42": 111, "J43": 111, "J44": 111,
    # HCC 112 — Fibrosis of Lung and Other Chronic Lung Disorders
    "J70": 112, "J84": 112, "J98": 112,
    # HCC 113 — Asthma
    "J45": 113, "J46": 113,
    # HCC 114 — Aspiration and Specified Bacterial Pneumonias
    "J690": 114, "J851": 114,
    # HCC 115 — Pneumococcal Pneumonia, Empyema, Lung Abscess
    "J13": 115, "J86": 115,
    # HCC 116 — Pulmonary Hypertension
    "I270": 116, "I272": 116,
    # HCC 117 — Rheumatoid Arthritis and Inflammatory CTD
    "M05": 117, "M06": 117, "M08": 117, "M32": 117, "M33": 117, "M34": 117,
    "M35": 117, "M45": 117,
    # HCC 118 — Systemic Lupus and Vasculitis
    "M30": 118, "M310": 118, "M311": 118, "M312": 118,
    # HCC 119 — Osteoporosis and Vertebral Fractures
    "M80": 119, "M81": 119,
    # HCC 120 — Pathological Fracture
    "M844": 120, "M845": 120,
    # HCC 121 — Hip Fracture/Dislocation
    "S72": 121, "M160": 121,
    # HCC 122 — Skull, Vertebrae, Clavicle, Sternum, and Rib Fractures
    "S02": 122, "S12": 122, "S22": 122,
    # HCC 123 — Upper Extremity Fracture
    "S42": 123, "S52": 123,
    # HCC 126 — Burns
    "T20": 126, "T21": 126, "T22": 126, "T23": 126, "T24": 126, "T25": 126,
    # HCC 127 — Extensive Third-Degree Burns
    "T3110": 127, "T312": 127,
    # HCC 130 — Immune Disorders
    "D80": 130, "D81": 130, "D82": 130, "D83": 130, "D84": 130,
    # HCC 131 — Coagulation / Hemorrhagic Disorders
    "D65": 131, "D66": 131, "D67": 131, "D68": 131,
    # HCC 132 — Sickle Cell Anemia
    "D570": 132, "D571": 132, "D572": 132,
    # HCC 133 — Hemolytic Anemias
    "D55": 133, "D56": 133, "D58": 133, "D59": 133,
    # Pregnancy HCCs
    "O09": 160, "O10": 160, "O11": 160, "O12": 160, "O13": 160,
    "O14": 160, "O15": 160, "O16": 160,
    "O20": 161, "O21": 161, "O22": 161, "O23": 161,
    "O30": 162, "O31": 162, "O32": 162, "O33": 162, "O34": 162,
    "O60": 163, "O61": 163, "O62": 163, "O63": 163, "O64": 163,
    "Z34": 164, "Z3A": 164,
}

# HHS-HCC Adult/Child/Infant Model Coefficients (CY2024 PLACEHOLDER values)
# Based on HHS Notice of Benefit and Payment Parameters
HHSHCC_COEFFICIENTS: dict[int, dict[str, Any]] = {
    # Infections / HIV
    1:   {"description": "HIV/AIDS",                                    "adult": 3.267, "child": 2.891, "infant": 0.0},
    2:   {"description": "Septicemia/SIRS/Shock",                       "adult": 2.678, "child": 2.234, "infant": 0.0},
    6:   {"description": "Opportunistic Infections",                     "adult": 1.923, "child": 1.678, "infant": 0.0},
    # Cancer
    8:   {"description": "Metastatic Cancer and Acute Leukemia",        "adult": 4.312, "child": 3.879, "infant": 0.0},
    9:   {"description": "Lung, Brain, and Other Severe Cancers",       "adult": 2.987, "child": 2.634, "infant": 0.0},
    10:  {"description": "Non-Hodgkin Lymphomas and Other Cancers",     "adult": 2.234, "child": 1.956, "infant": 0.0},
    11:  {"description": "Colorectal, Bladder, and Other Cancers",      "adult": 1.567, "child": 1.389, "infant": 0.0},
    12:  {"description": "Breast, Prostate, Endometrial Cancers",       "adult": 1.234, "child": 1.089, "infant": 0.0},
    13:  {"description": "Thyroid Cancer, Melanoma, Neurofibromatosis", "adult": 0.789, "child": 0.698, "infant": 0.0},
    # Diabetes
    18:  {"description": "Diabetes with Chronic Complications",         "adult": 0.634, "child": 0.589, "infant": 0.0},
    19:  {"description": "Diabetes without Complication",               "adult": 0.267, "child": 0.234, "infant": 0.0},
    20:  {"description": "Type 1 Diabetes without Complication",        "adult": 0.312, "child": 0.278, "infant": 0.0},
    # Nutrition/Metabolic
    23:  {"description": "Protein-Calorie Malnutrition",                "adult": 1.234, "child": 1.089, "infant": 0.0},
    24:  {"description": "Eating and Feeding Disorders",                "adult": 0.867, "child": 0.756, "infant": 0.0},
    25:  {"description": "Fluid / Electrolyte / Metabolic Disorders",   "adult": 0.423, "child": 0.378, "infant": 0.0},
    26:  {"description": "Other Significant Endocrine/Metabolic Dx",   "adult": 0.534, "child": 0.467, "infant": 0.0},
    # Liver
    27:  {"description": "End Stage Liver Disease",                     "adult": 2.456, "child": 2.123, "infant": 0.0},
    28:  {"description": "Cirrhosis of Liver",                          "adult": 1.345, "child": 1.189, "infant": 0.0},
    29:  {"description": "Hepatitis, Acute and Unspecified",            "adult": 0.567, "child": 0.498, "infant": 0.0},
    30:  {"description": "Inflammatory Liver Disease",                  "adult": 0.423, "child": 0.372, "infant": 0.0},
    # GI
    33:  {"description": "Inflammatory Bowel Disease",                  "adult": 0.934, "child": 0.823, "infant": 0.0},
    34:  {"description": "Peptic Ulcer, GI Hemorrhage",                 "adult": 0.612, "child": 0.543, "infant": 0.0},
    35:  {"description": "Appendicitis",                                "adult": 0.345, "child": 0.312, "infant": 0.0},
    # Renal
    41:  {"description": "Chronic Kidney Disease, Stage 5 / ESRD",     "adult": 1.123, "child": 0.989, "infant": 0.0},
    42:  {"description": "Chronic Kidney Disease, Stage 4",             "adult": 0.734, "child": 0.645, "infant": 0.0},
    43:  {"description": "Chronic Kidney Disease, Stage 3",             "adult": 0.423, "child": 0.372, "infant": 0.0},
    44:  {"description": "Chronic Kidney Disease, Mild/Unspecified",    "adult": 0.278, "child": 0.245, "infant": 0.0},
    45:  {"description": "Acute Renal Failure",                         "adult": 0.823, "child": 0.723, "infant": 0.0},
    46:  {"description": "Urinary Obstruction and Retention",           "adult": 0.267, "child": 0.234, "infant": 0.0},
    47:  {"description": "Kidney Transplant Status",                    "adult": 0.534, "child": 0.467, "infant": 0.0},
    # Behavioral Health
    54:  {"description": "Drug/Alcohol Dependence",                     "adult": 0.512, "child": 0.451, "infant": 0.0},
    55:  {"description": "Tobacco Use",                                 "adult": 0.156, "child": 0.134, "infant": 0.0},
    57:  {"description": "Schizophrenia",                               "adult": 1.189, "child": 1.045, "infant": 0.0},
    58:  {"description": "Major Depressive, Bipolar Disorders",         "adult": 0.678, "child": 0.598, "infant": 0.0},
    59:  {"description": "Reactive and Unspecified Psychosis",          "adult": 0.756, "child": 0.667, "infant": 0.0},
    60:  {"description": "Personality / Anorexia Disorders",            "adult": 0.534, "child": 0.470, "infant": 0.0},
    61:  {"description": "Anxiety Disorders",                           "adult": 0.312, "child": 0.275, "infant": 0.0},
    62:  {"description": "Attention Deficit / Autism Spectrum",         "adult": 0.289, "child": 0.256, "infant": 0.0},
    63:  {"description": "Intellectual Disability",                     "adult": 0.912, "child": 0.812, "infant": 0.0},
    # Neurological
    67:  {"description": "Quadriplegia",                                "adult": 3.456, "child": 3.045, "infant": 0.0},
    68:  {"description": "Paraplegia",                                  "adult": 2.789, "child": 2.456, "infant": 0.0},
    73:  {"description": "ALS and Other Motor Neuron Disease",          "adult": 3.123, "child": 2.756, "infant": 0.0},
    74:  {"description": "Cerebral Palsy",                              "adult": 0.956, "child": 0.845, "infant": 0.0},
    75:  {"description": "Myasthenia Gravis/Myoneural Disorders",       "adult": 1.567, "child": 1.389, "infant": 0.0},
    76:  {"description": "Muscular Dystrophy",                          "adult": 1.789, "child": 1.578, "infant": 0.0},
    77:  {"description": "Multiple Sclerosis",                          "adult": 2.234, "child": 1.967, "infant": 0.0},
    78:  {"description": "Parkinson's and Huntington's Diseases",       "adult": 1.345, "child": 1.189, "infant": 0.0},
    79:  {"description": "Seizure Disorders and Convulsions",           "adult": 0.734, "child": 0.645, "infant": 0.0},
    80:  {"description": "Coma, Brain Compression/Anoxic Damage",      "adult": 2.123, "child": 1.878, "infant": 0.0},
    # Respiratory
    82:  {"description": "Respirator Dependence/Tracheostomy",          "adult": 4.567, "child": 4.023, "infant": 0.0},
    83:  {"description": "Respiratory Arrest; CO Poisoning",            "adult": 2.345, "child": 2.067, "infant": 0.0},
    84:  {"description": "Cardio-Respiratory Failure and Shock",        "adult": 1.678, "child": 1.478, "infant": 0.0},
    # Cardiovascular
    85:  {"description": "Congestive Heart Failure",                    "adult": 0.923, "child": 0.812, "infant": 0.0},
    86:  {"description": "Acute Myocardial Infarction",                 "adult": 1.123, "child": 0.989, "infant": 0.0},
    87:  {"description": "Unstable Angina and Other Acute IHD",        "adult": 0.789, "child": 0.695, "infant": 0.0},
    88:  {"description": "Angina Pectoris/Old MI",                      "adult": 0.423, "child": 0.372, "infant": 0.0},
    90:  {"description": "Hypertensive Heart / CKD Combination",       "adult": 0.312, "child": 0.278, "infant": 0.0},
    96:  {"description": "Specified Heart Arrhythmias",                 "adult": 0.456, "child": 0.401, "infant": 0.0},
    97:  {"description": "Hypertension",                                "adult": 0.178, "child": 0.156, "infant": 0.0},
    99:  {"description": "Cerebral Hemorrhage",                         "adult": 1.567, "child": 1.378, "infant": 0.0},
    100: {"description": "Ischemic or Unspecified Stroke",              "adult": 1.234, "child": 1.089, "infant": 0.0},
    103: {"description": "Hemiplegia/Hemiparesis",                      "adult": 1.789, "child": 1.578, "infant": 0.0},
    104: {"description": "Monoplegia, Other Paralytic Syndromes",       "adult": 1.023, "child": 0.901, "infant": 0.0},
    106: {"description": "Atherosclerosis of Extremities w/ Ulceration","adult": 1.456, "child": 1.289, "infant": 0.0},
    107: {"description": "Vascular Disease with Complications",         "adult": 0.867, "child": 0.764, "infant": 0.0},
    108: {"description": "Vascular Disease",                            "adult": 0.423, "child": 0.372, "infant": 0.0},
    # Pulmonary
    110: {"description": "Cystic Fibrosis",                             "adult": 4.789, "child": 4.234, "infant": 0.0},
    111: {"description": "COPD",                                        "adult": 0.678, "child": 0.598, "infant": 0.0},
    112: {"description": "Fibrosis of Lung / Other Chronic Lung Dx",   "adult": 0.912, "child": 0.804, "infant": 0.0},
    113: {"description": "Asthma",                                      "adult": 0.312, "child": 0.275, "infant": 0.0},
    114: {"description": "Aspiration and Specified Bacterial Pneumonias","adult": 1.123, "child": 0.989, "infant": 0.0},
    115: {"description": "Pneumococcal Pneumonia, Empyema",             "adult": 0.789, "child": 0.695, "infant": 0.0},
    116: {"description": "Pulmonary Hypertension",                      "adult": 1.234, "child": 1.089, "infant": 0.0},
    # Musculoskeletal
    117: {"description": "Rheumatoid Arthritis and Inflammatory CTD",   "adult": 0.867, "child": 0.764, "infant": 0.0},
    118: {"description": "Systemic Lupus / Major Vasculitis",           "adult": 1.023, "child": 0.901, "infant": 0.0},
    119: {"description": "Osteoporosis and Vertebral Fractures",        "adult": 0.423, "child": 0.372, "infant": 0.0},
    120: {"description": "Pathological Fracture",                       "adult": 0.867, "child": 0.764, "infant": 0.0},
    121: {"description": "Hip Fracture/Dislocation",                    "adult": 1.023, "child": 0.901, "infant": 0.0},
    122: {"description": "Skull, Vertebrae, Clavicle Fractures",        "adult": 0.634, "child": 0.559, "infant": 0.0},
    123: {"description": "Upper Extremity Fracture",                    "adult": 0.289, "child": 0.256, "infant": 0.0},
    # Wounds/Burns
    126: {"description": "Burns",                                       "adult": 0.512, "child": 0.451, "infant": 0.0},
    127: {"description": "Extensive Third-Degree Burns",                "adult": 2.789, "child": 2.456, "infant": 0.0},
    # Immune / Blood
    130: {"description": "Immune Disorders",                           "adult": 1.234, "child": 1.089, "infant": 0.0},
    131: {"description": "Coagulation / Hemorrhagic Disorders",        "adult": 0.867, "child": 0.764, "infant": 0.0},
    132: {"description": "Sickle Cell Anemia (Hb-SS/SC)",              "adult": 1.678, "child": 1.478, "infant": 0.0},
    133: {"description": "Hemolytic Anemias",                          "adult": 0.956, "child": 0.845, "infant": 0.0},
    # Pregnancy
    160: {"description": "Pregnancy: High Risk/Complications",          "adult": 1.234, "child": 1.089, "infant": 0.0},
    161: {"description": "Pregnancy: Antepartum Complications",         "adult": 0.789, "child": 0.695, "infant": 0.0},
    162: {"description": "Pregnancy: Multiple Gestation",               "adult": 1.456, "child": 1.289, "infant": 0.0},
    163: {"description": "Pregnancy: Labor/Delivery Complications",     "adult": 0.923, "child": 0.812, "infant": 0.0},
    164: {"description": "Pregnancy: Routine/Uncomplicated",            "adult": 0.312, "child": 0.275, "infant": 0.0},
}

# HHS-HCC Demographic Base Scores by Age/Sex (PLACEHOLDER)
# Based on HHS Adult/Child/Infant model age-sex factors
HHSHCC_DEMO_SCORES: dict[tuple[str, str], float] = {
    ("0-1",   "F"): 3.891, ("0-1",   "M"): 4.123,
    ("1-4",   "F"): 0.867, ("1-4",   "M"): 0.912,
    ("5-9",   "F"): 0.423, ("5-9",   "M"): 0.445,
    ("10-14", "F"): 0.389, ("10-14", "M"): 0.401,
    ("15-20", "F"): 0.534, ("15-20", "M"): 0.456,
    ("21-24", "F"): 0.601, ("21-24", "M"): 0.512,
    ("25-29", "F"): 0.634, ("25-29", "M"): 0.489,
    ("30-34", "F"): 0.712, ("30-34", "M"): 0.534,
    ("35-39", "F"): 0.789, ("35-39", "M"): 0.578,
    ("40-44", "F"): 0.867, ("40-44", "M"): 0.645,
    ("45-49", "F"): 0.956, ("45-49", "M"): 0.734,
    ("50-54", "F"): 1.089, ("50-54", "M"): 0.867,
    ("55-59", "F"): 1.234, ("55-59", "M"): 1.012,
    ("60-64", "F"): 1.456, ("60-64", "M"): 1.234,
    ("65+",   "F"): 1.234, ("65+",   "M"): 1.123,  # HHS model typically max out at 64
}


# ---------------------------------------------------------------------------
# Unified age-band helper
# ---------------------------------------------------------------------------

def get_age_band(age: int, model: str) -> str:
    """
    Return the demographic age band string for the given age and model.

    Parameters
    ----------
    age:   Patient age in years.
    model: Risk adjustment model key. Supported values: "rxhcc", "hhs_hcc".

    Returns
    -------
    Age band string matching the demographic score table keys for the
    requested model (e.g. "65-69" for RxHCC, "60-64" for HHS-HCC).

    Raises
    ------
    ValueError if the model key is not recognized.
    """
    m = (model or "").strip().lower()
    if m == "rxhcc":
        if age < 35:   return "0-34"
        if age < 45:   return "35-44"
        if age < 55:   return "45-54"
        if age < 60:   return "55-59"
        if age < 65:   return "60-64"
        if age < 70:   return "65-69"
        if age < 75:   return "70-74"
        if age < 80:   return "75-79"
        if age < 85:   return "80-84"
        return "85+"
    if m in ("hhs_hcc", "hhs-hcc", "hhshcc"):
        if age < 1:    return "0-1"
        if age < 5:    return "1-4"
        if age < 10:   return "5-9"
        if age < 15:   return "10-14"
        if age < 21:   return "15-20"
        if age < 25:   return "21-24"
        if age < 30:   return "25-29"
        if age < 35:   return "30-34"
        if age < 40:   return "35-39"
        if age < 45:   return "40-44"
        if age < 50:   return "45-49"
        if age < 55:   return "50-54"
        if age < 60:   return "55-59"
        if age < 65:   return "60-64"
        return "65+"
    raise ValueError(
        f"Unknown model '{model}'. Supported: 'rxhcc', 'hhs_hcc'."
    )
