"""
Seed the knowledge graph with the top 20 CMS-HCC V28 categories and their
immediate clinical neighborhood: representative ICD-10 codes (subclass_of /
maps_to), primary indication conditions (treated_by drug class), and key
diagnostic labs (has_lab_signal).

This bootstraps the graph for downstream agents (suspect engine, recapture
prioritisation, dual-coder review, drug-driven HCC inference, etc.).

The data here is intentionally compact and human-curated rather than a full
UMLS dump — the goal is ~100 concepts and ~200+ edges so the API and
traversal logic have something realistic to work against.
"""
from __future__ import annotations

import logging
from typing import Any

from app.services.knowledge_graph.kg_repository import (
    bulk_upsert_concepts,
    bulk_upsert_edges,
    find_by_code,
)
from app.services.knowledge_graph.kg_schema import Concept, Edge, EdgeType

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Concept catalogue
#   Each tuple: (ontology, code, label, semantic_type, definition)
# ---------------------------------------------------------------------------


_HCC_CONCEPTS: list[tuple[str, str, str, str, str]] = [
    ("hcc", "17",  "Diabetes with Acute Complications",                    "Disease or Syndrome", "CMS-HCC V28: diabetes with ketoacidosis, hyperosmolarity, coma."),
    ("hcc", "18",  "Diabetes with Chronic Complications",                  "Disease or Syndrome", "CMS-HCC V28: diabetes with neuropathy, nephropathy, retinopathy, etc."),
    ("hcc", "19",  "Diabetes without Complication",                        "Disease or Syndrome", "CMS-HCC V28: uncomplicated diabetes mellitus."),
    ("hcc", "22",  "Morbid Obesity",                                       "Disease or Syndrome", "CMS-HCC V28: BMI >= 40 or >= 35 with comorbidity."),
    ("hcc", "35",  "End-Stage Liver Disease",                              "Disease or Syndrome", "CMS-HCC V28: cirrhosis with decompensation, varices, ascites, hepatorenal."),
    ("hcc", "37",  "Chronic Hepatitis",                                    "Disease or Syndrome", "CMS-HCC V28: chronic viral hepatitis B/C and chronic active hepatitis."),
    ("hcc", "38",  "Acute Liver Failure / Disease",                        "Disease or Syndrome", "CMS-HCC V28: acute and subacute hepatic failure."),
    ("hcc", "48",  "Coagulation Defects and Other Hematological Disorders", "Disease or Syndrome", "CMS-HCC V28: hemophilia, von Willebrand, thrombocytopenia."),
    ("hcc", "59",  "Major Depressive, Bipolar, and Paranoid Disorders",    "Mental Process",      "CMS-HCC V28: severe affective and psychotic disorders."),
    ("hcc", "85",  "Congestive Heart Failure",                             "Disease or Syndrome", "CMS-HCC V28: systolic, diastolic, and combined heart failure."),
    ("hcc", "96",  "Specified Heart Arrhythmias",                          "Disease or Syndrome", "CMS-HCC V28: atrial fibrillation, flutter, ventricular tachycardia."),
    ("hcc", "108", "Vascular Disease",                                     "Disease or Syndrome", "CMS-HCC V28: peripheral arterial disease, atherosclerosis."),
    ("hcc", "111", "Chronic Obstructive Pulmonary Disease",                "Disease or Syndrome", "CMS-HCC V28: COPD, emphysema, chronic bronchitis."),
    ("hcc", "122", "Proliferative Diabetic Retinopathy and Vitreous Hemorrhage", "Disease or Syndrome", "CMS-HCC V28: PDR with neovascularisation."),
    ("hcc", "138", "Chronic Kidney Disease, Stage 5",                      "Disease or Syndrome", "CMS-HCC V28: CKD stage 5, dialysis dependence."),
    ("hcc", "139", "Chronic Kidney Disease, Severe (Stage 4)",             "Disease or Syndrome", "CMS-HCC V28: CKD stage 4."),
    ("hcc", "226", "Hip Fracture / Dislocation",                           "Injury or Poisoning", "CMS-HCC V28: hip and pelvic fractures."),
    ("hcc", "238", "Major Complications of Medical Care and Trauma",       "Injury or Poisoning", "CMS-HCC V28: surgical and procedural complications."),
    ("hcc", "280", "Pressure Ulcer of Skin with Necrosis Through to Muscle, Tendon, or Bone", "Disease or Syndrome", "CMS-HCC V28: stage 3-4 pressure ulcers."),
    ("hcc", "300", "Opioid Use Disorder, Moderate/Severe, or Remission",   "Mental Process",      "CMS-HCC V28: substance use disorders."),
]


_ICD10_CONCEPTS: list[tuple[str, str, str, str, str]] = [
    # Diabetes (HCC 17/18/19)
    ("icd10", "E10.10",  "Type 1 diabetes mellitus with ketoacidosis without coma",      "Disease or Syndrome", ""),
    ("icd10", "E11.00",  "Type 2 diabetes mellitus with hyperosmolarity without coma",   "Disease or Syndrome", ""),
    ("icd10", "E11.21",  "Type 2 diabetes mellitus with diabetic nephropathy",            "Disease or Syndrome", ""),
    ("icd10", "E11.22",  "Type 2 diabetes mellitus with diabetic chronic kidney disease", "Disease or Syndrome", ""),
    ("icd10", "E11.40",  "Type 2 diabetes mellitus with diabetic neuropathy, unspecified", "Disease or Syndrome", ""),
    ("icd10", "E11.65",  "Type 2 diabetes mellitus with hyperglycemia",                  "Disease or Syndrome", ""),
    ("icd10", "E11.9",   "Type 2 diabetes mellitus without complications",               "Disease or Syndrome", ""),
    ("icd10", "E11.359", "T2DM w/ proliferative diabetic retinopathy w/o macular edema", "Disease or Syndrome", ""),

    # Obesity (HCC 22)
    ("icd10", "E66.01",  "Morbid (severe) obesity due to excess calories",               "Disease or Syndrome", ""),
    ("icd10", "Z68.41",  "Body mass index [BMI] 40.0-44.9, adult",                        "Finding",             ""),

    # Liver (HCC 35/37/38)
    ("icd10", "K70.30",  "Alcoholic cirrhosis of liver without ascites",                 "Disease or Syndrome", ""),
    ("icd10", "K72.00",  "Acute and subacute hepatic failure without coma",              "Disease or Syndrome", ""),
    ("icd10", "K74.60",  "Unspecified cirrhosis of liver",                               "Disease or Syndrome", ""),
    ("icd10", "B18.2",   "Chronic viral hepatitis C",                                    "Disease or Syndrome", ""),

    # Coagulation / heme (HCC 48)
    ("icd10", "D68.4",   "Acquired coagulation factor deficiency",                       "Disease or Syndrome", ""),
    ("icd10", "D69.6",   "Thrombocytopenia, unspecified",                                "Disease or Syndrome", ""),

    # Mental health (HCC 59)
    ("icd10", "F31.9",   "Bipolar disorder, unspecified",                                "Mental Process",      ""),
    ("icd10", "F33.2",   "Major depressive disorder, recurrent severe without psychotic features", "Mental Process", ""),

    # CHF (HCC 85)
    ("icd10", "I50.22",  "Chronic systolic (congestive) heart failure",                  "Disease or Syndrome", ""),
    ("icd10", "I50.32",  "Chronic diastolic (congestive) heart failure",                 "Disease or Syndrome", ""),
    ("icd10", "I50.9",   "Heart failure, unspecified",                                   "Disease or Syndrome", ""),

    # Arrhythmia (HCC 96)
    ("icd10", "I48.0",   "Paroxysmal atrial fibrillation",                               "Disease or Syndrome", ""),
    ("icd10", "I48.91",  "Unspecified atrial fibrillation",                              "Disease or Syndrome", ""),

    # Vascular (HCC 108)
    ("icd10", "I70.211", "Atherosclerosis of native arteries of right leg with intermittent claudication", "Disease or Syndrome", ""),
    ("icd10", "I73.9",   "Peripheral vascular disease, unspecified",                     "Disease or Syndrome", ""),

    # COPD (HCC 111)
    ("icd10", "J44.0",   "COPD with (acute) lower respiratory infection",                "Disease or Syndrome", ""),
    ("icd10", "J44.9",   "Chronic obstructive pulmonary disease, unspecified",           "Disease or Syndrome", ""),

    # Diabetic retinopathy (HCC 122)
    ("icd10", "E11.351", "T2DM w/ proliferative diabetic retinopathy w/ macular edema",  "Disease or Syndrome", ""),

    # CKD (HCC 138/139)
    ("icd10", "N18.4",   "Chronic kidney disease, stage 4 (severe)",                     "Disease or Syndrome", ""),
    ("icd10", "N18.5",   "Chronic kidney disease, stage 5",                              "Disease or Syndrome", ""),
    ("icd10", "N18.6",   "End stage renal disease",                                      "Disease or Syndrome", ""),

    # Hip fracture (HCC 226)
    ("icd10", "S72.001A","Fracture of unspecified part of neck of right femur, initial encounter for closed fracture", "Injury or Poisoning", ""),

    # Complications of medical care (HCC 238)
    ("icd10", "T81.4XXA","Infection following a procedure, initial encounter",           "Injury or Poisoning", ""),

    # Pressure ulcers (HCC 280)
    ("icd10", "L89.153", "Pressure ulcer of sacral region, stage 3",                     "Disease or Syndrome", ""),
    ("icd10", "L89.154", "Pressure ulcer of sacral region, stage 4",                     "Disease or Syndrome", ""),

    # Opioid use disorder (HCC 300)
    ("icd10", "F11.20",  "Opioid dependence, uncomplicated",                             "Mental Process",      ""),
    ("icd10", "F11.21",  "Opioid dependence, in remission",                              "Mental Process",      ""),

    # Additional broadly used codes for top-HCC neighbourhoods
    ("icd10", "E11.42",  "Type 2 diabetes mellitus with diabetic polyneuropathy",         "Disease or Syndrome", ""),
    ("icd10", "E11.51",  "T2DM w/ diabetic peripheral angiopathy w/o gangrene",           "Disease or Syndrome", ""),
    ("icd10", "I50.42",  "Chronic combined systolic and diastolic heart failure",         "Disease or Syndrome", ""),
    ("icd10", "I25.10",  "Atherosclerotic heart disease of native coronary artery w/o angina", "Disease or Syndrome", ""),
    ("icd10", "I12.9",   "Hypertensive chronic kidney disease w/ stage 1-4 CKD",          "Disease or Syndrome", ""),
    ("icd10", "I13.10",  "Hypertensive heart and CKD without heart failure",              "Disease or Syndrome", ""),
    ("icd10", "J43.9",   "Emphysema, unspecified",                                        "Disease or Syndrome", ""),
    ("icd10", "J45.50",  "Severe persistent asthma, uncomplicated",                       "Disease or Syndrome", ""),
    ("icd10", "F32.9",   "Major depressive disorder, single episode, unspecified",        "Mental Process",      ""),
    ("icd10", "F20.9",   "Schizophrenia, unspecified",                                    "Mental Process",      ""),
]


# SNOMED-CT bridges — give us a richer cross-ontology neighbourhood for the
# highest-volume concepts.
_SNOMED_CONCEPTS: list[tuple[str, str, str, str, str]] = [
    ("snomed", "44054006",  "Type 2 diabetes mellitus",                  "Disease or Syndrome", ""),
    ("snomed", "84114007",  "Heart failure",                             "Disease or Syndrome", ""),
    ("snomed", "13645005",  "Chronic obstructive lung disease",          "Disease or Syndrome", ""),
    ("snomed", "709044004", "Chronic kidney disease",                    "Disease or Syndrome", ""),
    ("snomed", "49436004",  "Atrial fibrillation",                       "Disease or Syndrome", ""),
    ("snomed", "19943007",  "Cirrhosis of liver",                        "Disease or Syndrome", ""),
    ("snomed", "370143000", "Major depressive disorder",                 "Mental Process",      ""),
    ("snomed", "238136002", "Morbid obesity",                            "Disease or Syndrome", ""),
    ("snomed", "75702008",  "Pressure ulcer",                            "Disease or Syndrome", ""),
    ("snomed", "5602001",   "Opioid dependence",                         "Mental Process",      ""),
]


_ATC_CONCEPTS: list[tuple[str, str, str, str, str]] = [
    ("atc", "A10BA02", "Metformin",                  "Pharmacologic Substance", "Biguanide oral antidiabetic."),
    ("atc", "A10BJ02", "Liraglutide",                "Pharmacologic Substance", "GLP-1 receptor agonist."),
    ("atc", "A10BK01", "Dapagliflozin",              "Pharmacologic Substance", "SGLT2 inhibitor."),
    ("atc", "A10AB01", "Insulin (human)",            "Pharmacologic Substance", "Short-acting human insulin."),
    ("atc", "C03CA01", "Furosemide",                 "Pharmacologic Substance", "Loop diuretic, used in CHF."),
    ("atc", "C09AA05", "Ramipril",                   "Pharmacologic Substance", "ACE inhibitor."),
    ("atc", "C07AB07", "Bisoprolol",                 "Pharmacologic Substance", "Beta-blocker, used in CHF/AF."),
    ("atc", "B01AF01", "Rivaroxaban",                "Pharmacologic Substance", "Direct oral anticoagulant for AF / VTE."),
    ("atc", "B01AC06", "Aspirin (low-dose)",         "Pharmacologic Substance", "Antiplatelet."),
    ("atc", "C10AA05", "Atorvastatin",               "Pharmacologic Substance", "HMG-CoA reductase inhibitor."),
    ("atc", "R03AC02", "Salbutamol (Albuterol)",     "Pharmacologic Substance", "Short-acting beta-2 agonist for COPD/asthma."),
    ("atc", "R03AL03", "Vilanterol/Umeclidinium",    "Pharmacologic Substance", "LABA/LAMA combination for COPD."),
    ("atc", "N06AB10", "Escitalopram",               "Pharmacologic Substance", "SSRI for depression."),
    ("atc", "N05AH04", "Quetiapine",                 "Pharmacologic Substance", "Atypical antipsychotic."),
    ("atc", "N02AA05", "Oxycodone",                  "Pharmacologic Substance", "Opioid analgesic — link to OUD risk."),
    ("atc", "N07BC02", "Methadone",                  "Pharmacologic Substance", "MAT for opioid use disorder."),
]


_LOINC_CONCEPTS: list[tuple[str, str, str, str, str]] = [
    ("loinc", "4548-4",  "Hemoglobin A1c (HbA1c)",                       "Laboratory Procedure", "Glycemic control marker."),
    ("loinc", "2339-0",  "Glucose, fasting",                             "Laboratory Procedure", "Fasting plasma glucose."),
    ("loinc", "33914-3", "Estimated GFR (MDRD)",                         "Laboratory Procedure", "Kidney function estimate."),
    ("loinc", "14959-1", "Microalbumin/Creatinine ratio",                "Laboratory Procedure", "Diabetic nephropathy screen."),
    ("loinc", "30934-4", "NT-proBNP",                                    "Laboratory Procedure", "Heart failure biomarker."),
    ("loinc", "10839-9", "Troponin I",                                   "Laboratory Procedure", "Cardiac injury marker."),
    ("loinc", "1742-6",  "ALT (alanine aminotransferase)",               "Laboratory Procedure", "Hepatocellular injury."),
    ("loinc", "1920-8",  "AST (aspartate aminotransferase)",             "Laboratory Procedure", "Hepatocellular injury."),
    ("loinc", "5902-2",  "Prothrombin time (PT)",                        "Laboratory Procedure", "Liver synthetic / anticoagulation."),
    ("loinc", "777-3",   "Platelet count",                               "Laboratory Procedure", "Heme / coagulation marker."),
    ("loinc", "20570-8", "Hematocrit",                                   "Laboratory Procedure", "Anemia screen."),
    ("loinc", "33747-7", "FEV1/FVC ratio (spirometry)",                  "Laboratory Procedure", "COPD severity grading."),
    ("loinc", "1798-8",  "Amylase",                                      "Laboratory Procedure", "Pancreatic / hepatic differential."),
]


_UMLS_CONCEPTS: list[tuple[str, str, str, str, str]] = [
    ("umls", "C0011860", "Diabetes Mellitus, Non-Insulin-Dependent",      "Disease or Syndrome", "Type 2 diabetes."),
    ("umls", "C0018802", "Heart Failure, Congestive",                     "Disease or Syndrome", "CHF."),
    ("umls", "C0024117", "Chronic Obstructive Pulmonary Disease",         "Disease or Syndrome", "COPD."),
    ("umls", "C0022661", "Chronic Kidney Disease",                        "Disease or Syndrome", "CKD."),
    ("umls", "C0004238", "Atrial Fibrillation",                           "Disease or Syndrome", "AF."),
    ("umls", "C0023895", "Liver Cirrhosis",                               "Disease or Syndrome", ""),
    ("umls", "C0011581", "Major Depressive Disorder",                     "Mental Process",      ""),
    ("umls", "C0029408", "Morbid Obesity",                                "Disease or Syndrome", ""),
    ("umls", "C0029134", "Opioid-Related Disorders",                      "Mental Process",      ""),
    ("umls", "C0011884", "Diabetic Retinopathy",                          "Disease or Syndrome", ""),
]


# ---------------------------------------------------------------------------
# Edge catalogue
#
# Each entry: (src ontology, src code, dst ontology, dst code, edge_type, weight)
# ---------------------------------------------------------------------------


_EDGES: list[tuple[str, str, str, str, str, float]] = [
    # ICD-10 -> HCC mapping (CMS-V28). Each ICD code gets a maps_to its HCC.
    ("icd10", "E10.10",  "hcc", "17",  EdgeType.MAPS_TO, 1.0),
    ("icd10", "E11.00",  "hcc", "17",  EdgeType.MAPS_TO, 1.0),
    ("icd10", "E11.21",  "hcc", "18",  EdgeType.MAPS_TO, 1.0),
    ("icd10", "E11.22",  "hcc", "18",  EdgeType.MAPS_TO, 1.0),
    ("icd10", "E11.40",  "hcc", "18",  EdgeType.MAPS_TO, 1.0),
    ("icd10", "E11.65",  "hcc", "18",  EdgeType.MAPS_TO, 1.0),
    ("icd10", "E11.9",   "hcc", "19",  EdgeType.MAPS_TO, 1.0),
    ("icd10", "E11.359", "hcc", "122", EdgeType.MAPS_TO, 1.0),
    ("icd10", "E11.351", "hcc", "122", EdgeType.MAPS_TO, 1.0),
    ("icd10", "E66.01",  "hcc", "22",  EdgeType.MAPS_TO, 1.0),
    ("icd10", "Z68.41",  "hcc", "22",  EdgeType.MAPS_TO, 0.8),
    ("icd10", "K70.30",  "hcc", "35",  EdgeType.MAPS_TO, 1.0),
    ("icd10", "K72.00",  "hcc", "38",  EdgeType.MAPS_TO, 1.0),
    ("icd10", "K74.60",  "hcc", "35",  EdgeType.MAPS_TO, 1.0),
    ("icd10", "B18.2",   "hcc", "37",  EdgeType.MAPS_TO, 1.0),
    ("icd10", "D68.4",   "hcc", "48",  EdgeType.MAPS_TO, 1.0),
    ("icd10", "D69.6",   "hcc", "48",  EdgeType.MAPS_TO, 1.0),
    ("icd10", "F31.9",   "hcc", "59",  EdgeType.MAPS_TO, 1.0),
    ("icd10", "F33.2",   "hcc", "59",  EdgeType.MAPS_TO, 1.0),
    ("icd10", "I50.22",  "hcc", "85",  EdgeType.MAPS_TO, 1.0),
    ("icd10", "I50.32",  "hcc", "85",  EdgeType.MAPS_TO, 1.0),
    ("icd10", "I50.9",   "hcc", "85",  EdgeType.MAPS_TO, 1.0),
    ("icd10", "I48.0",   "hcc", "96",  EdgeType.MAPS_TO, 1.0),
    ("icd10", "I48.91",  "hcc", "96",  EdgeType.MAPS_TO, 1.0),
    ("icd10", "I70.211", "hcc", "108", EdgeType.MAPS_TO, 1.0),
    ("icd10", "I73.9",   "hcc", "108", EdgeType.MAPS_TO, 1.0),
    ("icd10", "J44.0",   "hcc", "111", EdgeType.MAPS_TO, 1.0),
    ("icd10", "J44.9",   "hcc", "111", EdgeType.MAPS_TO, 1.0),
    ("icd10", "N18.4",   "hcc", "139", EdgeType.MAPS_TO, 1.0),
    ("icd10", "N18.5",   "hcc", "138", EdgeType.MAPS_TO, 1.0),
    ("icd10", "N18.6",   "hcc", "138", EdgeType.MAPS_TO, 1.0),
    ("icd10", "S72.001A","hcc", "226", EdgeType.MAPS_TO, 1.0),
    ("icd10", "T81.4XXA","hcc", "238", EdgeType.MAPS_TO, 1.0),
    ("icd10", "L89.153", "hcc", "280", EdgeType.MAPS_TO, 1.0),
    ("icd10", "L89.154", "hcc", "280", EdgeType.MAPS_TO, 1.0),
    ("icd10", "F11.20",  "hcc", "300", EdgeType.MAPS_TO, 1.0),

    # UMLS cross-ontology equivalence (maps_to)
    ("umls", "C0011860", "icd10", "E11.9",   EdgeType.MAPS_TO, 0.95),
    ("umls", "C0018802", "icd10", "I50.9",   EdgeType.MAPS_TO, 0.95),
    ("umls", "C0024117", "icd10", "J44.9",   EdgeType.MAPS_TO, 0.95),
    ("umls", "C0022661", "icd10", "N18.4",   EdgeType.MAPS_TO, 0.85),
    ("umls", "C0004238", "icd10", "I48.91",  EdgeType.MAPS_TO, 0.95),
    ("umls", "C0023895", "icd10", "K74.60",  EdgeType.MAPS_TO, 0.95),
    ("umls", "C0011581", "icd10", "F33.2",   EdgeType.MAPS_TO, 0.9),
    ("umls", "C0029408", "icd10", "E66.01",  EdgeType.MAPS_TO, 0.95),
    ("umls", "C0029134", "icd10", "F11.20",  EdgeType.MAPS_TO, 0.9),
    ("umls", "C0011884", "icd10", "E11.359", EdgeType.MAPS_TO, 0.9),

    # HCC subclass_of (ICD subclass_of HCC bucket)
    ("icd10", "E11.21",  "icd10", "E11.9",   EdgeType.SUBCLASS_OF, 1.0),
    ("icd10", "E11.40",  "icd10", "E11.9",   EdgeType.SUBCLASS_OF, 1.0),
    ("icd10", "E11.65",  "icd10", "E11.9",   EdgeType.SUBCLASS_OF, 1.0),
    ("icd10", "E11.351", "icd10", "E11.9",   EdgeType.SUBCLASS_OF, 1.0),
    ("icd10", "E11.359", "icd10", "E11.9",   EdgeType.SUBCLASS_OF, 1.0),
    ("icd10", "I50.22",  "icd10", "I50.9",   EdgeType.SUBCLASS_OF, 1.0),
    ("icd10", "I50.32",  "icd10", "I50.9",   EdgeType.SUBCLASS_OF, 1.0),
    ("icd10", "I48.0",   "icd10", "I48.91",  EdgeType.SUBCLASS_OF, 1.0),
    ("icd10", "L89.154", "icd10", "L89.153", EdgeType.SUBCLASS_OF, 0.9),
    ("icd10", "N18.5",   "icd10", "N18.4",   EdgeType.SUBCLASS_OF, 0.8),
    ("icd10", "N18.6",   "icd10", "N18.5",   EdgeType.SUBCLASS_OF, 0.8),

    # Drug -> condition (has_indication)  /  condition -> drug class (treated_by)
    ("atc", "A10BA02", "icd10", "E11.9",   EdgeType.HAS_INDICATION, 1.0),
    ("atc", "A10BJ02", "icd10", "E11.9",   EdgeType.HAS_INDICATION, 0.9),
    ("atc", "A10BK01", "icd10", "E11.9",   EdgeType.HAS_INDICATION, 0.9),
    ("atc", "A10BK01", "icd10", "I50.9",   EdgeType.HAS_INDICATION, 0.7),
    ("atc", "A10AB01", "icd10", "E10.10",  EdgeType.HAS_INDICATION, 1.0),
    ("atc", "C03CA01", "icd10", "I50.9",   EdgeType.HAS_INDICATION, 1.0),
    ("atc", "C09AA05", "icd10", "I50.9",   EdgeType.HAS_INDICATION, 0.95),
    ("atc", "C07AB07", "icd10", "I50.9",   EdgeType.HAS_INDICATION, 0.9),
    ("atc", "C07AB07", "icd10", "I48.91",  EdgeType.HAS_INDICATION, 0.85),
    ("atc", "B01AF01", "icd10", "I48.91",  EdgeType.HAS_INDICATION, 1.0),
    ("atc", "C10AA05", "icd10", "I70.211", EdgeType.HAS_INDICATION, 0.85),
    ("atc", "R03AC02", "icd10", "J44.9",   EdgeType.HAS_INDICATION, 1.0),
    ("atc", "R03AL03", "icd10", "J44.9",   EdgeType.HAS_INDICATION, 1.0),
    ("atc", "N06AB10", "icd10", "F33.2",   EdgeType.HAS_INDICATION, 0.95),
    ("atc", "N05AH04", "icd10", "F31.9",   EdgeType.HAS_INDICATION, 0.9),
    ("atc", "N07BC02", "icd10", "F11.20",  EdgeType.HAS_INDICATION, 1.0),

    ("icd10", "E11.9",   "atc", "A10BA02", EdgeType.TREATED_BY, 1.0),
    ("icd10", "I50.9",   "atc", "C03CA01", EdgeType.TREATED_BY, 1.0),
    ("icd10", "I48.91",  "atc", "B01AF01", EdgeType.TREATED_BY, 1.0),
    ("icd10", "J44.9",   "atc", "R03AL03", EdgeType.TREATED_BY, 1.0),
    ("icd10", "F33.2",   "atc", "N06AB10", EdgeType.TREATED_BY, 0.9),
    ("icd10", "F11.20",  "atc", "N07BC02", EdgeType.TREATED_BY, 0.95),

    # has_lab_signal (condition -> diagnostic LOINC)
    ("icd10", "E11.9",   "loinc", "4548-4",  EdgeType.HAS_LAB_SIGNAL, 1.0),
    ("icd10", "E11.9",   "loinc", "2339-0",  EdgeType.HAS_LAB_SIGNAL, 0.85),
    ("icd10", "E11.21",  "loinc", "14959-1", EdgeType.HAS_LAB_SIGNAL, 0.95),
    ("icd10", "E11.22",  "loinc", "33914-3", EdgeType.HAS_LAB_SIGNAL, 1.0),
    ("icd10", "I50.9",   "loinc", "30934-4", EdgeType.HAS_LAB_SIGNAL, 1.0),
    ("icd10", "I50.9",   "loinc", "10839-9", EdgeType.HAS_LAB_SIGNAL, 0.7),
    ("icd10", "K74.60",  "loinc", "1742-6",  EdgeType.HAS_LAB_SIGNAL, 0.9),
    ("icd10", "K74.60",  "loinc", "1920-8",  EdgeType.HAS_LAB_SIGNAL, 0.9),
    ("icd10", "K74.60",  "loinc", "5902-2",  EdgeType.HAS_LAB_SIGNAL, 0.85),
    ("icd10", "D68.4",   "loinc", "5902-2",  EdgeType.HAS_LAB_SIGNAL, 0.95),
    ("icd10", "D69.6",   "loinc", "777-3",   EdgeType.HAS_LAB_SIGNAL, 1.0),
    ("icd10", "N18.4",   "loinc", "33914-3", EdgeType.HAS_LAB_SIGNAL, 1.0),
    ("icd10", "N18.5",   "loinc", "33914-3", EdgeType.HAS_LAB_SIGNAL, 1.0),
    ("icd10", "J44.9",   "loinc", "33747-7", EdgeType.HAS_LAB_SIGNAL, 1.0),

    # has_complication chains
    ("icd10", "E11.9",   "icd10", "E11.21",  EdgeType.HAS_COMPLICATION, 0.6),
    ("icd10", "E11.9",   "icd10", "E11.40",  EdgeType.HAS_COMPLICATION, 0.5),
    ("icd10", "E11.9",   "icd10", "E11.359", EdgeType.HAS_COMPLICATION, 0.4),
    ("icd10", "E11.21",  "icd10", "N18.4",   EdgeType.HAS_COMPLICATION, 0.55),
    ("icd10", "I50.9",   "icd10", "N18.4",   EdgeType.HAS_COMPLICATION, 0.45),
    ("icd10", "K74.60",  "icd10", "K72.00",  EdgeType.HAS_COMPLICATION, 0.4),

    # Comorbidity (bidirectional pairs encoded as two edges)
    ("icd10", "E11.9",  "icd10", "I50.9",  EdgeType.COMORBID_WITH, 0.55),
    ("icd10", "I50.9",  "icd10", "E11.9",  EdgeType.COMORBID_WITH, 0.55),
    ("icd10", "E11.9",  "icd10", "E66.01", EdgeType.COMORBID_WITH, 0.5),
    ("icd10", "E66.01", "icd10", "E11.9",  EdgeType.COMORBID_WITH, 0.5),
    ("icd10", "I48.91", "icd10", "I50.9",  EdgeType.COMORBID_WITH, 0.6),
    ("icd10", "I50.9",  "icd10", "I48.91", EdgeType.COMORBID_WITH, 0.6),
    ("icd10", "J44.9",  "icd10", "I50.9",  EdgeType.COMORBID_WITH, 0.5),
    ("icd10", "I50.9",  "icd10", "J44.9",  EdgeType.COMORBID_WITH, 0.5),

    # Contraindications
    ("atc", "C03CA01", "icd10", "N18.6",  EdgeType.CONTRAINDICATED_WITH, 0.7),
    ("atc", "A10BA02", "icd10", "N18.5",  EdgeType.CONTRAINDICATED_WITH, 0.85),

    # ---------------------------------------------------------------------
    # SNOMED <-> ICD10 cross-walk (maps_to) and SNOMED <-> HCC mappings.
    # ---------------------------------------------------------------------
    ("snomed", "44054006",  "icd10", "E11.9",   EdgeType.MAPS_TO, 0.95),
    ("snomed", "44054006",  "hcc",   "19",      EdgeType.MAPS_TO, 0.9),
    ("snomed", "84114007",  "icd10", "I50.9",   EdgeType.MAPS_TO, 0.95),
    ("snomed", "84114007",  "hcc",   "85",      EdgeType.MAPS_TO, 0.95),
    ("snomed", "13645005",  "icd10", "J44.9",   EdgeType.MAPS_TO, 0.95),
    ("snomed", "13645005",  "hcc",   "111",     EdgeType.MAPS_TO, 0.95),
    ("snomed", "709044004", "icd10", "N18.4",   EdgeType.MAPS_TO, 0.85),
    ("snomed", "709044004", "hcc",   "139",     EdgeType.MAPS_TO, 0.8),
    ("snomed", "49436004",  "icd10", "I48.91",  EdgeType.MAPS_TO, 0.95),
    ("snomed", "49436004",  "hcc",   "96",      EdgeType.MAPS_TO, 0.95),
    ("snomed", "19943007",  "icd10", "K74.60",  EdgeType.MAPS_TO, 0.95),
    ("snomed", "19943007",  "hcc",   "35",      EdgeType.MAPS_TO, 0.9),
    ("snomed", "370143000", "icd10", "F33.2",   EdgeType.MAPS_TO, 0.9),
    ("snomed", "370143000", "hcc",   "59",      EdgeType.MAPS_TO, 0.9),
    ("snomed", "238136002", "icd10", "E66.01",  EdgeType.MAPS_TO, 0.95),
    ("snomed", "238136002", "hcc",   "22",      EdgeType.MAPS_TO, 0.95),
    ("snomed", "75702008",  "icd10", "L89.153", EdgeType.MAPS_TO, 0.85),
    ("snomed", "75702008",  "hcc",   "280",     EdgeType.MAPS_TO, 0.85),
    ("snomed", "5602001",   "icd10", "F11.20",  EdgeType.MAPS_TO, 0.95),
    ("snomed", "5602001",   "hcc",   "300",     EdgeType.MAPS_TO, 0.95),

    # UMLS <-> SNOMED equivalences
    ("umls", "C0011860", "snomed", "44054006",  EdgeType.MAPS_TO, 0.95),
    ("umls", "C0018802", "snomed", "84114007",  EdgeType.MAPS_TO, 0.95),
    ("umls", "C0024117", "snomed", "13645005",  EdgeType.MAPS_TO, 0.95),
    ("umls", "C0022661", "snomed", "709044004", EdgeType.MAPS_TO, 0.95),
    ("umls", "C0004238", "snomed", "49436004",  EdgeType.MAPS_TO, 0.95),
    ("umls", "C0023895", "snomed", "19943007",  EdgeType.MAPS_TO, 0.95),
    ("umls", "C0011581", "snomed", "370143000", EdgeType.MAPS_TO, 0.95),
    ("umls", "C0029408", "snomed", "238136002", EdgeType.MAPS_TO, 0.95),
    ("umls", "C0029134", "snomed", "5602001",   EdgeType.MAPS_TO, 0.95),

    # Newly added ICD-10 -> HCC
    ("icd10", "F11.21",  "hcc",   "300", EdgeType.MAPS_TO, 1.0),
    ("icd10", "E11.42",  "hcc",   "18",  EdgeType.MAPS_TO, 1.0),
    ("icd10", "E11.51",  "hcc",   "18",  EdgeType.MAPS_TO, 1.0),
    ("icd10", "I50.42",  "hcc",   "85",  EdgeType.MAPS_TO, 1.0),
    ("icd10", "I25.10",  "hcc",   "108", EdgeType.MAPS_TO, 0.7),
    ("icd10", "I12.9",   "hcc",   "139", EdgeType.MAPS_TO, 0.7),
    ("icd10", "I13.10",  "hcc",   "139", EdgeType.MAPS_TO, 0.7),
    ("icd10", "J43.9",   "hcc",   "111", EdgeType.MAPS_TO, 1.0),
    ("icd10", "J45.50",  "hcc",   "111", EdgeType.MAPS_TO, 0.6),
    ("icd10", "F32.9",   "hcc",   "59",  EdgeType.MAPS_TO, 0.8),
    ("icd10", "F20.9",   "hcc",   "59",  EdgeType.MAPS_TO, 1.0),

    # subclass_of for the new ICD additions
    ("icd10", "E11.42",  "icd10", "E11.40", EdgeType.SUBCLASS_OF, 1.0),
    ("icd10", "E11.51",  "icd10", "E11.40", EdgeType.SUBCLASS_OF, 0.9),
    ("icd10", "I50.42",  "icd10", "I50.9",  EdgeType.SUBCLASS_OF, 1.0),
    ("icd10", "F32.9",   "icd10", "F33.2",  EdgeType.SUBCLASS_OF, 0.7),
    ("icd10", "F11.21",  "icd10", "F11.20", EdgeType.SUBCLASS_OF, 0.9),
    ("icd10", "I13.10",  "icd10", "I12.9",  EdgeType.SUBCLASS_OF, 0.8),
    ("icd10", "J43.9",   "icd10", "J44.9",  EdgeType.SUBCLASS_OF, 0.8),
    ("icd10", "J45.50",  "icd10", "J44.9",  EdgeType.SUBCLASS_OF, 0.4),

    # More drug -> indication (deepens has_indication graph)
    ("atc", "C09AA05", "icd10", "I12.9",   EdgeType.HAS_INDICATION, 0.9),
    ("atc", "C09AA05", "icd10", "I13.10",  EdgeType.HAS_INDICATION, 0.9),
    ("atc", "C03CA01", "icd10", "I50.42",  EdgeType.HAS_INDICATION, 0.95),
    ("atc", "C07AB07", "icd10", "I25.10",  EdgeType.HAS_INDICATION, 0.85),
    ("atc", "C10AA05", "icd10", "I25.10",  EdgeType.HAS_INDICATION, 0.95),
    ("atc", "B01AC06", "icd10", "I25.10",  EdgeType.HAS_INDICATION, 0.9),
    ("atc", "N06AB10", "icd10", "F32.9",   EdgeType.HAS_INDICATION, 0.95),
    ("atc", "N05AH04", "icd10", "F20.9",   EdgeType.HAS_INDICATION, 0.95),
    ("atc", "R03AC02", "icd10", "J45.50",  EdgeType.HAS_INDICATION, 1.0),
    ("atc", "R03AL03", "icd10", "J43.9",   EdgeType.HAS_INDICATION, 0.9),
    ("atc", "A10BA02", "icd10", "E11.42",  EdgeType.HAS_INDICATION, 0.85),
    ("atc", "A10BJ02", "icd10", "E66.01",  EdgeType.HAS_INDICATION, 0.7),
    ("atc", "A10BK01", "icd10", "N18.4",   EdgeType.HAS_INDICATION, 0.6),

    # has_lab_signal for newly added conditions
    ("icd10", "E11.42",  "loinc", "4548-4",  EdgeType.HAS_LAB_SIGNAL, 0.95),
    ("icd10", "I50.42",  "loinc", "30934-4", EdgeType.HAS_LAB_SIGNAL, 1.0),
    ("icd10", "I12.9",   "loinc", "33914-3", EdgeType.HAS_LAB_SIGNAL, 1.0),
    ("icd10", "I13.10",  "loinc", "33914-3", EdgeType.HAS_LAB_SIGNAL, 1.0),
    ("icd10", "J43.9",   "loinc", "33747-7", EdgeType.HAS_LAB_SIGNAL, 1.0),
    ("icd10", "J45.50",  "loinc", "33747-7", EdgeType.HAS_LAB_SIGNAL, 0.85),
    ("icd10", "F33.2",   "loinc", "20570-8", EdgeType.HAS_LAB_SIGNAL, 0.4),
    ("icd10", "B18.2",   "loinc", "1742-6",  EdgeType.HAS_LAB_SIGNAL, 0.95),
    ("icd10", "B18.2",   "loinc", "1920-8",  EdgeType.HAS_LAB_SIGNAL, 0.95),
    ("icd10", "K70.30",  "loinc", "1742-6",  EdgeType.HAS_LAB_SIGNAL, 0.9),
    ("icd10", "K70.30",  "loinc", "1920-8",  EdgeType.HAS_LAB_SIGNAL, 0.9),
    ("icd10", "K72.00",  "loinc", "5902-2",  EdgeType.HAS_LAB_SIGNAL, 0.95),

    # has_complication chains for new codes
    ("icd10", "E11.42",  "icd10", "E11.51",  EdgeType.HAS_COMPLICATION, 0.4),
    ("icd10", "E11.40",  "icd10", "E11.42",  EdgeType.HAS_COMPLICATION, 0.7),
    ("icd10", "I12.9",   "icd10", "N18.4",   EdgeType.HAS_COMPLICATION, 0.55),
    ("icd10", "I13.10",  "icd10", "I50.9",   EdgeType.HAS_COMPLICATION, 0.5),
    ("icd10", "I25.10",  "icd10", "I50.9",   EdgeType.HAS_COMPLICATION, 0.45),
    ("icd10", "B18.2",   "icd10", "K74.60",  EdgeType.HAS_COMPLICATION, 0.55),
    ("icd10", "L89.153", "icd10", "L89.154", EdgeType.HAS_COMPLICATION, 0.5),

    # Comorbidities for new codes (bidirectional)
    ("icd10", "I50.9",   "icd10", "I25.10",  EdgeType.COMORBID_WITH, 0.6),
    ("icd10", "I25.10",  "icd10", "I50.9",   EdgeType.COMORBID_WITH, 0.6),
    ("icd10", "F33.2",   "icd10", "F11.20",  EdgeType.COMORBID_WITH, 0.4),
    ("icd10", "F11.20",  "icd10", "F33.2",   EdgeType.COMORBID_WITH, 0.4),
    ("icd10", "I50.9",   "icd10", "N18.4",   EdgeType.COMORBID_WITH, 0.5),
    ("icd10", "N18.4",   "icd10", "I50.9",   EdgeType.COMORBID_WITH, 0.5),
    ("icd10", "I48.91",  "icd10", "J44.9",   EdgeType.COMORBID_WITH, 0.4),
    ("icd10", "J44.9",   "icd10", "I48.91",  EdgeType.COMORBID_WITH, 0.4),

    # Additional condition -> drug-class treated_by
    ("icd10", "I12.9",   "atc", "C09AA05",  EdgeType.TREATED_BY, 0.95),
    ("icd10", "I13.10",  "atc", "C09AA05",  EdgeType.TREATED_BY, 0.95),
    ("icd10", "I25.10",  "atc", "C10AA05",  EdgeType.TREATED_BY, 0.95),
    ("icd10", "I25.10",  "atc", "B01AC06",  EdgeType.TREATED_BY, 0.9),
    ("icd10", "F32.9",   "atc", "N06AB10",  EdgeType.TREATED_BY, 0.9),
    ("icd10", "F20.9",   "atc", "N05AH04",  EdgeType.TREATED_BY, 0.95),
    ("icd10", "J45.50",  "atc", "R03AC02",  EdgeType.TREATED_BY, 1.0),
    ("icd10", "J43.9",   "atc", "R03AL03",  EdgeType.TREATED_BY, 0.95),
    ("icd10", "E11.42",  "atc", "A10BA02",  EdgeType.TREATED_BY, 0.85),
    ("icd10", "F11.21",  "atc", "N07BC02",  EdgeType.TREATED_BY, 0.95),

    # Additional contraindications
    ("atc", "C03CA01", "icd10", "N18.5",  EdgeType.CONTRAINDICATED_WITH, 0.6),
    ("atc", "B01AF01", "icd10", "N18.6",  EdgeType.CONTRAINDICATED_WITH, 0.85),
    ("atc", "C10AA05", "icd10", "K74.60", EdgeType.CONTRAINDICATED_WITH, 0.6),
    ("atc", "N02AA05", "icd10", "F11.20", EdgeType.CONTRAINDICATED_WITH, 0.95),
    ("atc", "N02AA05", "icd10", "F11.21", EdgeType.CONTRAINDICATED_WITH, 0.95),
]


# ---------------------------------------------------------------------------
# Public entrypoint
# ---------------------------------------------------------------------------


def _all_concepts() -> list[Concept]:
    rows = (
        _HCC_CONCEPTS
        + _ICD10_CONCEPTS
        + _ATC_CONCEPTS
        + _LOINC_CONCEPTS
        + _UMLS_CONCEPTS
        + _SNOMED_CONCEPTS
    )
    out: list[Concept] = []
    for ontology, code, label, sem_type, definition in rows:
        out.append(
            Concept(
                ontology=ontology,
                code=code,
                preferred_label=label,
                semantic_type=sem_type or None,
                definition=definition or None,
                metadata={"source": "raf-kg-bootstrap-v1"},
            )
        )
    return out


def seed_top_hccs() -> dict[str, Any]:
    """
    Idempotently load the bootstrap concepts and edges into the knowledge graph.

    Returns a summary dict suitable for logging / CLI output:
        {"concepts_inserted": 99, "edges_inserted": 84,
         "hccs_covered": [...], "by_ontology": {...}}
    """
    concepts = _all_concepts()
    logger.info("Seeding %d KG concepts ...", len(concepts))
    bulk_upsert_concepts(concepts)

    # Resolve concept ids by (ontology, code)
    by_key: dict[tuple[str, str], int] = {}
    for c in concepts:
        if c.id is not None:
            by_key[(c.ontology, c.code)] = c.id

    # Build edge dataclasses
    edges: list[Edge] = []
    skipped: list[tuple[Any, ...]] = []
    for src_ont, src_code, dst_ont, dst_code, etype, weight in _EDGES:
        src = by_key.get((src_ont, src_code))
        dst = by_key.get((dst_ont, dst_code))
        if src is None or dst is None:
            # Try a DB lookup as a fallback (concepts seeded earlier in the
            # process but not present in by_key, e.g. partial reseed).
            if src is None:
                row = find_by_code(src_ont, src_code)
                src = row.id if row else None
            if dst is None:
                row = find_by_code(dst_ont, dst_code)
                dst = row.id if row else None
        if src is None or dst is None:
            skipped.append((src_ont, src_code, dst_ont, dst_code, etype))
            continue
        edges.append(
            Edge(
                src_concept_id=src,
                dst_concept_id=dst,
                edge_type=etype,
                weight=weight,
                source="raf-kg-bootstrap-v1",
            )
        )

    logger.info("Seeding %d KG edges (%d skipped) ...", len(edges), len(skipped))
    bulk_upsert_edges(edges)

    by_ontology: dict[str, int] = {}
    for c in concepts:
        by_ontology[c.ontology] = by_ontology.get(c.ontology, 0) + 1

    hccs_covered = sorted(
        {code for ont, code, *_ in _HCC_CONCEPTS},
        key=lambda x: int(x) if x.isdigit() else 999,
    )

    return {
        "concepts_inserted": len(concepts),
        "edges_inserted": len(edges),
        "edges_skipped": len(skipped),
        "by_ontology": by_ontology,
        "hccs_covered": hccs_covered,
    }
