"""
Seed encounter RAF-gap analysis, V28/V24 scores, and expanded ICD-10-to-HCC crosswalk.

Idempotent — safe to run on every restart.

This module seeds data ONLY for the 15 patients that exist in OpenEMR (PIDs 1-15).
It also cleans up orphaned data for non-existent patients (16-30) on every run.
"""
from __future__ import annotations

import logging
import random

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
MEASUREMENT_YEAR = 2026
PMPM = 12_000  # revenue-per-RAF-point assumption

# The 15 real OpenEMR patients (PIDs 1-15).
# Each entry: (billing_raf, suspect_gap)
# billing_raf = what's currently coded in the EMR (lower / under-coded)
# suspect_gap = additional RAF the AI found but hasn't been coded yet (positive)
# This ensures AI RAF > billing RAF → "Estimated annual capture" (positive gap)
PATIENT_RAF_DATA: dict[int, tuple[float, float]] = {
    #  pid  billing_raf  suspect_gap
    1:  (0.9850, 0.3900),  # CHF + AFib + DM — missing CKD stage upgrade
    2:  (1.1200, 0.2660),  # CHF + HTN — missing AFib from cardiology notes
    3:  (0.2400, 0.0000),  # Young, healthy — no suspects
    4:  (0.2280, 0.0000),  # Young, healthy — no suspects
    5:  (0.8750, 0.3350),  # RA + DM — missing COPD (on tiotropium)
    6:  (1.4200, 0.2710),  # COPD + CHF + CKD — missing CKD stage 4 upgrade
    7:  (0.5900, 0.1851),  # DM + Depression — missing morbid obesity + CKD
    8:  (0.6300, 0.1053),  # AFib + DM — DM not recoded for 2026
    9:  (0.4800, 0.3090),  # Depression — missing depression severity coding
    10: (0.7500, 0.3680),  # COPD + DM + AFib — CHF from 2024 not recaptured
    11: (0.5200, 0.0690),  # Dementia + CHF + CKD — CKD stage not coded
    12: (0.4100, 0.3350),  # DM + PVD — COPD not coded (on Spiriva)
    13: (0.1900, 0.1053),  # Morbid obesity — DM not coded (HbA1c 7.8%)
    14: (1.0500, 0.2660),  # Cirrhosis + CHF + DM — AFib from cardiology
    15: (0.8200, 0.0690),  # Depression + obesity — CKD stage not coded
}

# Open suspect-condition coefficient totals per patient (subset of PATIENT_RAF_DATA)
SUSPECT_VALUES: dict[int, float] = {
    pid: gap for pid, (_, gap) in PATIENT_RAF_DATA.items() if gap > 0
}

# V28 / V24 score rows for patients 1-15
# Tuple: (model_segment, demographic, disease, interaction, total_raw, norm_factor, final_raf, hcc_count)
V28_SCORES: dict[int, tuple] = {
    1:  ("CNA", 0.5020, 0.4830, 0.0000, 0.9850, 1.0000, 0.9850, 3),
    2:  ("CNA", 0.5670, 0.5530, 0.0000, 1.1200, 1.0000, 1.1200, 3),
    3:  ("CNA", 0.2400, 0.0000, 0.0000, 0.2400, 1.0000, 0.2400, 0),
    4:  ("CNA", 0.2280, 0.0000, 0.0000, 0.2280, 1.0000, 0.2280, 0),
    5:  ("CNA", 0.4650, 0.4100, 0.0000, 0.8750, 1.0000, 0.8750, 3),
    6:  ("CNA", 0.5240, 0.8960, 0.0000, 1.4200, 1.0000, 1.4200, 4),
    7:  ("CNA", 0.3530, 0.2370, 0.0000, 0.5900, 1.0000, 0.5900, 2),
    8:  ("CNA", 0.4650, 0.1650, 0.0000, 0.6300, 1.0000, 0.6300, 2),
    9:  ("CNA", 0.3960, 0.0840, 0.0000, 0.4800, 1.0000, 0.4800, 1),
    10: ("CNA", 0.3150, 0.4350, 0.0000, 0.7500, 1.0000, 0.7500, 3),
    11: ("CNA", 0.5710, 0.0000, 0.0000, 0.5200, 0.9100, 0.5200, 0),
    12: ("CNA", 0.2400, 0.1700, 0.0000, 0.4100, 1.0000, 0.4100, 2),
    13: ("CNA", 0.1900, 0.0000, 0.0000, 0.1900, 1.0000, 0.1900, 0),
    14: ("CNA", 0.4120, 0.6380, 0.0000, 1.0500, 1.0000, 1.0500, 4),
    15: ("CNA", 0.4480, 0.3720, 0.0000, 0.8200, 1.0000, 0.8200, 2),
}

V24_SCORES: dict[int, tuple] = {
    1:  ("CNA", 0.5670, 0.5550, 0.0000, 1.1220, 1.0000, 1.1220, 3),
    2:  ("CNA", 0.5670, 0.6360, 0.0000, 1.2740, 1.0000, 1.2740, 3),
    3:  ("CNA", 0.2400, 0.0000, 0.0000, 0.2568, 1.0000, 0.2568, 0),
    4:  ("CNA", 0.2280, 0.0000, 0.0000, 0.2440, 1.0000, 0.2440, 0),
    5:  ("CNA", 0.4480, 0.4720, 0.0000, 0.9930, 1.0000, 0.9930, 3),
    6:  ("CNA", 0.5240, 1.0290, 0.0000, 1.6120, 1.0000, 1.6120, 4),
    7:  ("CNA", 0.3530, 0.2720, 0.0000, 0.6770, 1.0000, 0.6770, 2),
    8:  ("CNA", 0.4480, 0.1897, 0.0000, 0.7230, 1.0000, 0.7230, 2),
    9:  ("CNA", 0.3350, 0.0965, 0.0000, 0.5510, 1.0000, 0.5510, 1),
    10: ("CNA", 0.3150, 0.5002, 0.0000, 0.8610, 1.0000, 0.8610, 3),
    11: ("CNA", 0.5710, 0.0000, 0.0000, 0.5980, 1.0000, 0.5980, 0),
    12: ("CNA", 0.2400, 0.1953, 0.0000, 0.4710, 1.0000, 0.4710, 2),
    13: ("CNA", 0.1900, 0.0000, 0.0000, 0.2033, 1.0000, 0.2033, 0),
    14: ("CNA", 0.4120, 0.7337, 0.0000, 1.2046, 1.0000, 1.2046, 4),
    15: ("CNA", 0.4480, 0.4277, 0.0000, 0.9430, 1.0000, 0.9430, 2),
}

# Expanded ICD-10 to HCC crosswalk (149 entries)
# (icd10_code, icd10_description, hcc_code, hcc_label, effective_year)
CROSSWALK: list[tuple] = [
    ("B20",     "HIV disease",                                                              1,   "HIV/AIDS",                                      2024),
    ("Z21",     "Asymptomatic HIV infection status",                                        1,   "HIV/AIDS",                                      2024),
    ("C18.0",   "Malignant neoplasm of cecum",                                              12,  "Cancer",                                        2024),
    ("C18.2",   "Malignant neoplasm of ascending colon",                                    12,  "Cancer",                                        2024),
    ("C18.7",   "Malignant neoplasm of sigmoid colon",                                      12,  "Cancer",                                        2024),
    ("C18.9",   "Malignant neoplasm of colon",                                              12,  "Colorectal, Bladder, and Other Cancers",        2024),
    ("C22.0",   "Liver cell carcinoma",                                                     12,  "Cancer",                                        2024),
    ("C25.0",   "Malignant neoplasm of head of pancreas",                                   12,  "Cancer",                                        2024),
    ("C34.10",  "Malignant neoplasm of upper lobe bronchus or lung",                        12,  "Cancer",                                        2024),
    ("C34.30",  "Malignant neoplasm of lower lobe bronchus or lung",                        12,  "Cancer",                                        2024),
    ("C34.90",  "Malignant neoplasm of bronchus or lung",                                   12,  "Lung and Other Severe Cancers",                 2024),
    ("C50.011", "Malignant neoplasm of nipple and areola right female breast",              12,  "Cancer",                                        2024),
    ("C50.012", "Malignant neoplasm of nipple and areola left female breast",               12,  "Cancer",                                        2024),
    ("C50.411", "Malignant neoplasm of upper-outer quadrant right female breast",           12,  "Cancer",                                        2024),
    ("C50.919", "Malignant neoplasm of breast",                                             12,  "Breast, Prostate, and Other Cancers",           2024),
    ("C61",     "Malignant neoplasm of prostate",                                           12,  "Breast, Prostate, and Other Cancers",           2024),
    ("C64.1",   "Malignant neoplasm of right kidney",                                       12,  "Cancer",                                        2024),
    ("C64.2",   "Malignant neoplasm of left kidney",                                        12,  "Cancer",                                        2024),
    ("C67.9",   "Malignant neoplasm of bladder unspecified",                                12,  "Cancer",                                        2024),
    ("E10.10",  "Type 1 DM with ketoacidosis without coma",                                 17,  "Diabetes with Acute Complications",             2024),
    ("E10.11",  "Type 1 DM with ketoacidosis with coma",                                    17,  "Diabetes with Acute Complications",             2024),
    ("E10.22",  "Type 1 DM with diabetic chronic kidney disease",                           18,  "Diabetes with Chronic Complications",           2024),
    ("E10.40",  "Type 1 DM with diabetic neuropathy unspecified",                           18,  "Diabetes with Chronic Complications",           2024),
    ("E11.21",  "Type 2 DM with diabetic nephropathy",                                      18,  "Diabetes with Chronic Complications",           2024),
    ("E11.22",  "Type 2 DM with diabetic chronic kidney disease",                           18,  "Diabetes with Chronic Complications",           2024),
    ("E11.29",  "Type 2 DM with other diabetic kidney complication",                        18,  "Diabetes with Chronic Complications",           2024),
    ("E11.311", "Type 2 DM with unspecified diabetic retinopathy with macular edema",       18,  "Diabetes with Chronic Complications",           2024),
    ("E11.319", "Type 2 DM with diabetic retinopathy",                                      18,  "Diabetes with Chronic Complications",           2024),
    ("E11.321", "Type 2 DM with mild nonproliferative diabetic retinopathy with macular edema", 18, "Diabetes with Chronic Complications",       2024),
    ("E11.329", "Type 2 DM with mild nonproliferative diabetic retinopathy without macular edema", 18, "Diabetes with Chronic Complications",    2024),
    ("E11.331", "Type 2 DM with moderate nonproliferative diabetic retinopathy with macular edema", 18, "Diabetes with Chronic Complications",   2024),
    ("E11.349", "Type 2 DM with severe nonproliferative diabetic retinopathy without macular edema", 18, "Diabetes with Chronic Complications",  2024),
    ("E11.351", "Type 2 DM with proliferative diabetic retinopathy with macular edema",     18,  "Diabetes with Chronic Complications",           2024),
    ("E11.40",  "Type 2 DM with diabetic neuropathy",                                       18,  "Diabetes with Chronic Complications",           2024),
    ("E11.41",  "Type 2 DM with diabetic mononeuropathy",                                   18,  "Diabetes with Chronic Complications",           2024),
    ("E11.42",  "Type 2 DM with diabetic polyneuropathy",                                   18,  "Diabetes with Chronic Complications",           2024),
    ("E11.43",  "Type 2 DM with diabetic autonomic neuropathy",                             18,  "Diabetes with Chronic Complications",           2024),
    ("E11.44",  "Type 2 DM with diabetic amyotrophy",                                       18,  "Diabetes with Chronic Complications",           2024),
    ("E11.51",  "Type 2 DM with diabetic peripheral angiopathy without gangrene",           18,  "Diabetes with Chronic Complications",           2024),
    ("E11.52",  "Type 2 DM with diabetic peripheral angiopathy with gangrene",              18,  "Diabetes with Chronic Complications",           2024),
    ("E11.59",  "Type 2 DM with other circulatory complications",                           18,  "Diabetes with Chronic Complications",           2024),
    ("E11.610", "Type 2 DM with diabetic neuropathic arthropathy",                          18,  "Diabetes with Chronic Complications",           2024),
    ("E11.618", "Type 2 DM with other diabetic arthropathy",                                18,  "Diabetes with Chronic Complications",           2024),
    ("E11.620", "Type 2 DM with diabetic dermatitis",                                       18,  "Diabetes with Chronic Complications",           2024),
    ("E11.621", "Type 2 DM with foot ulcer",                                                18,  "Diabetes with Chronic Complications",           2024),
    ("E11.622", "Type 2 DM with other skin ulcer",                                          18,  "Diabetes with Chronic Complications",           2024),
    ("E11.628", "Type 2 DM with other skin complications",                                  18,  "Diabetes with Chronic Complications",           2024),
    ("E11.630", "Type 2 DM with periodontal disease",                                       18,  "Diabetes with Chronic Complications",           2024),
    ("E11.638", "Type 2 DM with other oral complications",                                  18,  "Diabetes with Chronic Complications",           2024),
    ("E11.69",  "Type 2 DM with other specified complication",                              18,  "Diabetes with Chronic Complications",           2024),
    ("E11.8",   "Type 2 DM with unspecified complications",                                 18,  "Diabetes with Chronic Complications",           2024),
    ("B18.1",   "Chronic viral hepatitis B without delta-agent",                            29,  "Liver Disease",                                 2024),
    ("B18.2",   "Chronic viral hepatitis C",                                                29,  "Cirrhosis of Liver",                            2024),
    ("K70.30",  "Alcoholic cirrhosis of liver without ascites",                             29,  "Liver Disease",                                 2024),
    ("K70.31",  "Alcoholic cirrhosis of liver with ascites",                                29,  "Liver Disease",                                 2024),
    ("K74.60",  "Unspecified cirrhosis of liver",                                           29,  "Cirrhosis of Liver",                            2024),
    ("K74.69",  "Other cirrhosis of liver",                                                 29,  "Liver Disease",                                 2024),
    ("K76.6",   "Portal hypertension",                                                      29,  "Liver Disease",                                 2024),
    ("E10.65",  "Type 1 DM with hyperglycemia",                                             37,  "Diabetes without Complication",                 2024),
    ("E10.9",   "Type 1 diabetes mellitus without complications",                           37,  "Diabetes without Complication",                 2024),
    ("E11.641", "Type 2 DM with hypoglycemia with coma",                                    37,  "Diabetes without Complication",                 2024),
    ("E11.649", "Type 2 DM with hypoglycemia without coma",                                 37,  "Diabetes without Complication",                 2024),
    ("E11.65",  "Type 2 DM with hyperglycemia",                                             37,  "Diabetes without Complication",                 2024),
    ("E11.9",   "Type 2 diabetes mellitus without complications",                           37,  "Diabetes without Complication",                 2024),
    ("M05.70",  "RA without organ involvement unspecified",                                 40,  "Rheumatoid Arthritis",                          2024),
    ("M05.79",  "RA without organ involvement multiple sites",                              40,  "Rheumatoid Arthritis",                          2024),
    ("M06.00",  "RA without rheumatoid factor unspecified site",                            40,  "Rheumatoid Arthritis",                          2024),
    ("M06.9",   "Rheumatoid arthritis, unspecified",                                        40,  "Rheumatoid Arthritis",                          2024),
    ("E66.01",  "Morbid obesity due to excess calories",                                    48,  "Morbid Obesity",                                2024),
    ("E66.09",  "Other obesity due to excess calories",                                     48,  "Morbid Obesity",                                2024),
    ("E66.2",   "Morbid severe obesity with alveolar hypoventilation",                      48,  "Morbid Obesity",                                2024),
    ("G30.0",   "Alzheimer disease with early onset",                                       51,  "Dementia",                                      2024),
    ("G30.1",   "Alzheimer disease with late onset",                                        51,  "Dementia",                                      2024),
    ("G30.8",   "Other Alzheimer disease",                                                  51,  "Dementia",                                      2024),
    ("G30.9",   "Alzheimer's disease",                                                      51,  "Dementia With Complications",                   2024),
    ("F01.50",  "Vascular dementia without behavioral disturbance",                         52,  "Dementia without Behavioral Disturbance",       2024),
    ("F01.51",  "Vascular dementia with behavioral disturbance",                            52,  "Dementia without Behavioral Disturbance",       2024),
    ("F02.80",  "Dementia in other diseases classified elsewhere without behavioral disturbance", 52, "Dementia without Behavioral Disturbance",  2024),
    ("F03.90",  "Unspecified dementia",                                                     52,  "Dementia Without Complication",                 2024),
    ("F20.9",   "Schizophrenia, unspecified",                                               57,  "Schizophrenia",                                 2024),
    ("F25.0",   "Schizoaffective disorder bipolar type",                                    57,  "Schizophrenia",                                 2024),
    ("F25.1",   "Schizoaffective disorder depressive type",                                 57,  "Schizophrenia",                                 2024),
    ("F31.10",  "Bipolar disorder current episode manic without psychotic features unspecified", 59, "Bipolar Disorder",                          2024),
    ("F31.30",  "Bipolar disorder current episode depressed mild or moderate unspecified",   59,  "Bipolar Disorder",                              2024),
    ("F31.9",   "Bipolar disorder, unspecified",                                            59,  "Major Depressive, Bipolar Disorders",           2024),
    ("G20",     "Parkinson's disease",                                                      78,  "Parkinson's Disease",                           2024),
    ("G20.A1",  "Parkinson disease without dyskinesia without fluctuations",                78,  "Parkinson Disease",                             2024),
    ("G20.B1",  "Parkinson disease with dyskinesia without fluctuations",                   78,  "Parkinson Disease",                             2024),
    ("G40.301", "Generalized idiopathic epilepsy not intractable with status epilepticus",  79,  "Seizure Disorders",                             2024),
    ("G40.309", "Generalized idiopathic epilepsy not intractable without status epilepticus", 79, "Seizure Disorders",                            2024),
    ("G40.909", "Epilepsy, unspecified",                                                    79,  "Seizure Disorders and Convulsions",             2024),
    ("G40.A09", "Absence epileptic syndrome not intractable without status epilepticus",    79,  "Seizure Disorders",                             2024),
    ("I50.1",   "Left ventricular failure unspecified",                                     85,  "Heart Failure",                                 2024),
    ("I50.20",  "Unspecified systolic heart failure",                                       85,  "Congestive Heart Failure",                      2024),
    ("I50.21",  "Acute systolic heart failure",                                             85,  "Heart Failure",                                 2024),
    ("I50.22",  "Chronic systolic heart failure",                                           85,  "Heart Failure",                                 2024),
    ("I50.23",  "Acute on chronic systolic heart failure",                                  85,  "Heart Failure",                                 2024),
    ("I50.30",  "Unspecified diastolic heart failure",                                      85,  "Heart Failure",                                 2024),
    ("I50.31",  "Acute diastolic heart failure",                                            85,  "Heart Failure",                                 2024),
    ("I50.32",  "Chronic diastolic heart failure",                                          85,  "Heart Failure",                                 2024),
    ("I50.33",  "Acute on chronic diastolic heart failure",                                 85,  "Heart Failure",                                 2024),
    ("I50.40",  "Unspecified combined systolic and diastolic heart failure",                 85,  "Heart Failure",                                 2024),
    ("I50.41",  "Acute combined systolic and diastolic heart failure",                      85,  "Heart Failure",                                 2024),
    ("I50.42",  "Chronic combined systolic and diastolic heart failure",                    85,  "Heart Failure",                                 2024),
    ("I50.43",  "Acute on chronic combined systolic and diastolic heart failure",           85,  "Heart Failure",                                 2024),
    ("I50.9",   "Heart failure, unspecified",                                               85,  "Congestive Heart Failure",                      2024),
    ("I48.0",   "Paroxysmal atrial fibrillation",                                           96,  "Atrial Fibrillation",                           2024),
    ("I48.1",   "Persistent atrial fibrillation",                                           96,  "Atrial Fibrillation",                           2024),
    ("I48.19",  "Other persistent atrial fibrillation",                                     96,  "Atrial Fibrillation",                           2024),
    ("I48.2",   "Chronic atrial fibrillation",                                              96,  "Atrial Fibrillation",                           2024),
    ("I48.91",  "Unspecified atrial fibrillation",                                          96,  "Specified Heart Arrhythmias",                   2024),
    ("I61.0",   "Nontraumatic intracerebral hemorrhage in hemisphere subcortical",          99,  "Hemorrhagic Stroke",                            2024),
    ("I61.9",   "Nontraumatic intracerebral hemorrhage unspecified",                        99,  "Hemorrhagic Stroke",                            2024),
    ("I63.30",  "Cerebral infarction due to thrombosis of unspecified cerebral artery",     100, "Ischemic Stroke",                               2024),
    ("I63.40",  "Cerebral infarction due to embolism of unspecified cerebral artery",       100, "Ischemic Stroke",                               2024),
    ("I63.50",  "Cerebral infarction due to unspecified occlusion of unspecified cerebral artery", 100, "Ischemic Stroke",                        2024),
    ("I63.9",   "Cerebral infarction, unspecified",                                         100, "Ischemic or Unspecified Stroke",                2024),
    ("I65.29",  "Occlusion and stenosis of unspecified carotid artery",                     107, "Vascular Disease with Complications",           2024),
    ("I70.0",   "Atherosclerosis of aorta",                                                 108, "Vascular Disease",                              2024),
    ("I70.1",   "Atherosclerosis of renal artery",                                          108, "Vascular Disease",                              2024),
    ("I70.211", "Atherosclerosis of native arteries of extremities with intermittent claudication right leg", 108, "Vascular Disease",             2024),
    ("I70.219", "Atherosclerosis of native arteries of extremities with intermittent claudication unspecified leg", 108, "Vascular Disease",       2024),
    ("I70.90",  "Unspecified atherosclerosis",                                              108, "Vascular Disease",                              2024),
    ("I73.9",   "Peripheral vascular disease",                                              108, "Vascular Disease",                              2024),
    ("J43.0",   "Unilateral pulmonary emphysema",                                           112, "COPD",                                          2024),
    ("J43.1",   "Panlobular emphysema",                                                     112, "COPD",                                          2024),
    ("J43.2",   "Centrilobular emphysema",                                                  112, "COPD",                                          2024),
    ("J43.9",   "Emphysema unspecified",                                                    112, "COPD",                                          2024),
    ("J44.0",   "COPD with acute lower respiratory infection",                              112, "Chronic Obstructive Pulmonary Disease",         2024),
    ("J44.1",   "COPD with acute exacerbation",                                             112, "Chronic Obstructive Pulmonary Disease",         2024),
    ("J44.9",   "Chronic obstructive pulmonary disease unspecified",                        112, "COPD",                                          2024),
    ("N18.5",   "Chronic kidney disease, stage 5",                                          136, "Chronic Kidney Disease, Stage 5",               2024),
    ("N18.6",   "End stage renal disease",                                                  136, "CKD Stage 5",                                   2024),
    ("N18.4",   "Chronic kidney disease, stage 4",                                          137, "Chronic Kidney Disease, Severe (Stage 4)",      2024),
    ("N18.1",   "Chronic kidney disease stage 1",                                           141, "CKD Stage 1-3",                                 2024),
    ("N18.2",   "Chronic kidney disease stage 2",                                           141, "CKD Stage 1-3",                                 2024),
    ("N18.3",   "Chronic kidney disease, stage 3",                                          141, "Chronic Kidney Disease, Moderate (Stage 3)",    2024),
    ("N18.30",  "Chronic kidney disease stage 3 unspecified",                               141, "CKD Stage 1-3",                                 2024),
    ("N18.31",  "Chronic kidney disease stage 3a",                                          141, "CKD Stage 1-3",                                 2024),
    ("N18.32",  "Chronic kidney disease stage 3b",                                          141, "CKD Stage 1-3",                                 2024),
    ("N18.9",   "Chronic kidney disease, unspecified",                                      141, "Chronic Kidney Disease, Moderate",              2024),
    ("F32.0",   "Major depressive disorder single episode mild",                            155, "Major Depression",                               2024),
    ("F32.1",   "Major depressive disorder single episode moderate",                        155, "Major Depression",                               2024),
    ("F32.2",   "Major depressive disorder single episode severe without psychotic features", 155, "Major Depression",                             2024),
    ("F32.3",   "Major depressive disorder single episode severe with psychotic features",  155, "Major Depression",                               2024),
    ("F33.0",   "Major depressive disorder, recurrent, mild",                               155, "Major Depression, Moderate or Severe",          2024),
    ("F33.1",   "Major depressive disorder, recurrent, moderate",                           155, "Major Depression, Moderate or Severe",          2024),
    ("F33.2",   "Major depressive disorder recurrent severe without psychotic features",    155, "Major Depression",                               2024),
    ("F33.3",   "Major depressive disorder recurrent severe with psychotic features",       155, "Major Depression",                               2024),
]


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------
def seed_encounters_scores_demo() -> None:
    """Seed encounter RAF gaps, V28/V24 scores, and ICD-10-to-HCC crosswalk."""
    from app.db import raf_cursor

    try:
        with raf_cursor() as cur:
            _cleanup_orphaned_data(cur)
            _fix_raf_scores_for_openemr_patients(cur)
            _seed_encounter_analysis_all_patients(cur)
            _seed_v28_v24_scores(cur)
            _seed_crosswalk(cur)
            _ensure_patient_hcc_rows(cur)
            _seed_historical_scores(cur)
    except Exception as exc:
        logger.error("seed_encounters_scores_demo failed: %s", exc)
        raise


# ---------------------------------------------------------------------------
# 0. Cleanup orphaned data (patients 16-30 not in OpenEMR)
# ---------------------------------------------------------------------------
def _cleanup_orphaned_data(cur) -> None:
    """Remove raf_scores, raf_encounter_analysis, etc. for non-OpenEMR patients."""
    # The 15 real OpenEMR patients are PIDs 1-15. Patients 16-30 are orphaned.
    orphan_pids = list(range(16, 31))
    placeholders = ",".join(["%s"] * len(orphan_pids))

    # Delete orphaned raf_scores rows (all score types)
    cur.execute(
        f"DELETE FROM raf_scores WHERE patient_id IN ({placeholders})",
        orphan_pids,
    )
    deleted_scores = cur.rowcount
    if deleted_scores:
        logger.info("Cleaned up %d orphaned raf_scores rows (patients 16-30).", deleted_scores)

    # Delete orphaned raf_encounter_analysis rows
    cur.execute(
        f"DELETE FROM raf_encounter_analysis WHERE patient_id IN ({placeholders})",
        orphan_pids,
    )
    deleted_ea = cur.rowcount
    if deleted_ea:
        logger.info("Cleaned up %d orphaned raf_encounter_analysis rows.", deleted_ea)

    # Delete orphaned emr_patient_matches (synthetic + non-OpenEMR local patients)
    # Keep only direct OpenEMR patients (emr_pid 1-15) or FHIR matches for real patients
    cur.execute(
        "DELETE FROM emr_patient_matches "
        "WHERE match_method IN ('manual_import', 'openemr_local') "
        f"AND raf_patient_id IN ({placeholders})",
        orphan_pids,
    )
    deleted_matches = cur.rowcount
    if deleted_matches:
        logger.info("Cleaned up %d orphaned emr_patient_matches rows.", deleted_matches)

    # Delete orphaned raf_patient_demographics
    cur.execute(
        f"DELETE FROM raf_patient_demographics WHERE patient_id IN ({placeholders})",
        orphan_pids,
    )
    cur.execute(
        f"DELETE FROM raf_patient_hcc WHERE patient_id IN ({placeholders})",
        orphan_pids,
    )
    cur.execute(
        f"DELETE FROM raf_suspect_conditions WHERE patient_id IN ({placeholders})",
        orphan_pids,
    )
    logger.info("Orphaned data cleanup complete.")


# ---------------------------------------------------------------------------
# 1. Fix raf_scores for the 15 OpenEMR patients
# ---------------------------------------------------------------------------
def _fix_raf_scores_for_openemr_patients(cur) -> None:
    """
    Update raf_scores prospective rows for patients 1-15 to match PATIENT_RAF_DATA.
    billing_raf is the coded RAF; the AI will find higher (suspect gap is positive).
    """
    for pid, (billing_raf, _suspect_gap) in PATIENT_RAF_DATA.items():
        # Upsert prospective score — update if exists, insert if not
        cur.execute(
            """INSERT INTO raf_scores
               (patient_id, measurement_year, score_type, model_segment,
                demographic_score, disease_score, interaction_score,
                total_raw, normalization_factor, final_raf, hcc_count)
               VALUES (%s, %s, 'prospective', 'CNA', 0, %s, 0, %s, 1.0, %s, 0)
               ON DUPLICATE KEY UPDATE final_raf = %s, total_raw = %s""",
            (pid, MEASUREMENT_YEAR, billing_raf, billing_raf, billing_raf,
             billing_raf, billing_raf),
        )
    logger.info("Updated prospective raf_scores for 15 OpenEMR patients.")


# ---------------------------------------------------------------------------
# 2. Seed raf_encounter_analysis for ALL 15 OpenEMR patients
# ---------------------------------------------------------------------------
def _seed_encounter_analysis_all_patients(cur) -> None:
    """
    Ensure all 15 OpenEMR patients have at least one raf_encounter_analysis row.
    The AI RAF (overall_score) is always billing_raf + suspect_gap (positive gap).
    Clears existing stale rows first and rebuilds cleanly.
    """
    # Check if all 15 patients already have analysis
    cur.execute(
        "SELECT COUNT(DISTINCT patient_id) AS cnt FROM raf_encounter_analysis "
        "WHERE patient_id BETWEEN 1 AND 15"
    )
    row = cur.fetchone()
    existing_patients = int(row["cnt"]) if row else 0

    if existing_patients >= 15:
        # Verify billing < ai for all rows — fix if needed
        cur.execute(
            "SELECT COUNT(*) AS cnt FROM raf_encounter_analysis "
            "WHERE patient_id BETWEEN 1 AND 15 AND (ai_raf <= billing_raf OR ai_raf IS NULL)"
        )
        bad_rows = int(cur.fetchone()["cnt"])
        if bad_rows == 0:
            logger.info("Encounter analysis already seeded for all 15 patients — skipping.")
            return
        logger.info("Found %d encounter-analysis rows where ai_raf <= billing_raf — rebuilding.", bad_rows)

    # Delete existing rows for patients 1-15 and rebuild
    cur.execute("DELETE FROM raf_encounter_analysis WHERE patient_id BETWEEN 1 AND 15")
    logger.info("Rebuilding encounter analysis for 15 OpenEMR patients.")

    # Generate one representative encounter row per patient
    # encounter_id values are synthetic but realistic-looking
    base_encounter_id = 9_000_000

    inserted = 0
    for pid, (billing_raf, suspect_gap) in PATIENT_RAF_DATA.items():
        ai_raf = round(billing_raf + suspect_gap, 4)
        raf_gap = round(suspect_gap, 4)
        revenue_opp = round(raf_gap * PMPM, 2)
        encounter_id = base_encounter_id + pid
        hcc_opp_count = 1 if suspect_gap > 0 else 0

        cur.execute(
            """INSERT INTO raf_encounter_analysis
               (patient_id, encounter_id, billing_raf, ai_raf, raf_gap,
                revenue_opportunity, overall_score, hcc_opportunity_count,
                analyzed_at)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, '2026-04-01 00:00:00')""",
            (pid, encounter_id, billing_raf, ai_raf, raf_gap,
             revenue_opp, ai_raf, hcc_opp_count),
        )
        inserted += 1

    logger.info("Inserted %d encounter-analysis rows for all 15 patients.", inserted)


# ---------------------------------------------------------------------------
# 3. V28 / V24 RAF scores (patients 1-15 only)
# ---------------------------------------------------------------------------
def _seed_v28_v24_scores(cur) -> None:
    """Insert V28 and V24 score rows for patients 1-15 if they don't already exist."""

    cur.execute(
        "SELECT COUNT(*) AS cnt FROM raf_scores "
        "WHERE measurement_year = %s AND score_type IN ('v28','v24') "
        "AND patient_id BETWEEN 1 AND 15",
        (MEASUREMENT_YEAR,),
    )
    if cur.fetchone()["cnt"] >= 30:
        logger.info("V28/V24 scores already seeded (30 rows for patients 1-15) — skipping.")
        return

    # Clear and rebuild V28/V24 for patients 1-15
    cur.execute(
        "DELETE FROM raf_scores "
        "WHERE measurement_year = %s AND score_type IN ('v28','v24') "
        "AND patient_id BETWEEN 1 AND 15",
        (MEASUREMENT_YEAR,),
    )

    logger.info("Seeding V28/V24 RAF scores for 15 patients …")

    inserted = 0
    for score_type, data in [("v28", V28_SCORES), ("v24", V24_SCORES)]:
        for pid, vals in data.items():
            seg, demo, disease, interact, raw, norm, final, hcc_cnt = vals

            cur.execute(
                """
                INSERT INTO raf_scores
                    (patient_id, score_type, model_segment,
                     demographic_score, disease_score, interaction_score,
                     total_raw, normalization_factor, final_raf,
                     hcc_count, measurement_year)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (pid, score_type, seg, demo, disease, interact,
                 raw, norm, final, hcc_cnt, MEASUREMENT_YEAR),
            )
            inserted += 1

    logger.info("Inserted %d V28/V24 score rows.", inserted)


# ---------------------------------------------------------------------------
# 4. ICD-10 to HCC crosswalk
# ---------------------------------------------------------------------------
def _seed_crosswalk(cur) -> None:
    """Insert crosswalk entries using INSERT IGNORE to avoid duplicates."""

    cur.execute("SELECT COUNT(*) AS cnt FROM hcc_icd10_crosswalk")
    if cur.fetchone()["cnt"] >= 149:
        logger.info("ICD-10-to-HCC crosswalk already has >= 149 entries — skipping.")
        return

    logger.info("Seeding ICD-10-to-HCC crosswalk (%d entries) …", len(CROSSWALK))

    inserted = 0
    for icd, icd_desc, hcc, hcc_label, eff_year in CROSSWALK:
        cur.execute(
            """
            INSERT IGNORE INTO hcc_icd10_crosswalk
                (icd10_code, icd10_description, hcc_code, hcc_label, effective_year)
            VALUES (%s, %s, %s, %s, %s)
            """,
            (icd, icd_desc, hcc, hcc_label, eff_year),
        )
        inserted += cur.rowcount

    logger.info("Inserted %d new crosswalk rows.", inserted)


# ---------------------------------------------------------------------------
# 5. Ensure raf_patient_hcc rows exist for the 15 OpenEMR patients
# ---------------------------------------------------------------------------

# Known ICD-10 -> (hcc_code, raf_coefficient) for the demo patients
_HCC_MAP: dict[str, tuple[int, float]] = {
    "E11.9":   (37,  0.1053),
    "J44.1":   (112, 0.3350),
    "F33.0":   (155, 0.3090),
    "I50.9":   (85,  0.3680),
    "I48.91":  (96,  0.2660),
    "N18.4":   (137, 0.2710),
    "N18.3":   (141, 0.0690),
    "E66.01":  (48,  0.1161),
    "I63.9":   (100, 0.2630),
    "I73.9":   (108, 0.2380),
    "F20.9":   (57,  0.3410),
    "G20":     (78,  0.5780),
    "B20":     (1,   0.3543),
    "C34.90":  (12,  0.2714),
    "K74.60":  (29,  0.3712),
    "M06.9":   (40,  0.3614),
    "F03.90":  (52,  0.2660),
    "G40.909": (79,  0.1640),
}

# ICD-10 codes per patient (pids 1-15)
_PATIENT_HCC_CODES: dict[int, list[str]] = {
    1:  ["I50.9", "I48.91", "E11.9", "N18.3"],
    2:  ["G20", "F03.90", "I73.9", "E11.9", "J44.1"],
    3:  [], 4: [],
    5:  ["M06.9", "E11.9", "E66.01"],
    6:  ["J44.1", "I50.9", "N18.4", "I63.9", "E11.9"],
    7:  ["E11.9", "F33.0"],
    8:  ["I48.91", "E11.9"],
    9:  ["F33.0"],
    10: ["J44.1", "E11.9", "I48.91"],
    11: ["F03.90", "I50.9", "N18.4", "G40.909", "E11.9"],
    12: ["E11.9", "I73.9"],
    13: ["E66.01"],
    14: ["K74.60", "I50.9", "E11.9", "N18.3"],
    15: ["F33.0", "E66.01"],
}


def _ensure_patient_hcc_rows(cur) -> None:
    """
    Guarantee that every known HCC for pids 1-15 has a row in raf_patient_hcc
    for measurement_year=2026.  This is idempotent — skips rows that already
    exist.  Runs after seed_raf_demo's early-exit guard, so it fills any gaps
    that the demo seeder may have missed.
    """
    import json as _json

    inserted = 0
    for pid, codes in _PATIENT_HCC_CODES.items():
        for icd in codes:
            hcc, coeff = _HCC_MAP[icd]
            cur.execute(
                "SELECT id FROM raf_patient_hcc "
                "WHERE patient_id=%s AND hcc_code=%s AND measurement_year=2026 LIMIT 1",
                (pid, hcc),
            )
            if cur.fetchone():
                continue
            cur.execute(
                "INSERT INTO raf_patient_hcc "
                "  (patient_id, measurement_year, hcc_code, icd10_codes, "
                "   source_encounter_ids, raf_coefficient, meat_status, "
                "   is_trumped, trumped_by_hcc) "
                "VALUES (%s, 2026, %s, %s, '[]', %s, 'complete', 0, NULL)",
                (pid, hcc, _json.dumps([icd]), coeff),
            )
            inserted += 1

    if inserted:
        logger.info("Inserted %d missing raf_patient_hcc rows for pids 1-15.", inserted)
    else:
        logger.info("raf_patient_hcc rows for pids 1-15 already complete — skipping.")


# ---------------------------------------------------------------------------
# 6. Historical RAF scores for 2024 and 2025 (score history chart)
# ---------------------------------------------------------------------------
def _seed_historical_scores(cur) -> None:
    """
    Insert prospective raf_scores rows for 2024 and 2025 for all 15 patients
    so the Score History chart shows 3 bars.  Uses V28_SCORES as the 2026
    baseline and scales down for prior years to show a realistic upward trend.

    Multipliers vs 2026:
      2025 -> 93 % of demographic/disease/final
      2024 -> 85 % of demographic/disease/final

    raf_scores has a FK to raf_patient_demographics(patient_id, measurement_year)
    so we must ensure demographics rows exist for 2024/2025 first.
    """
    # Check whether historical rows already exist
    cur.execute(
        "SELECT COUNT(*) AS cnt FROM raf_scores "
        "WHERE measurement_year IN (2024, 2025) "
        "  AND score_type = 'prospective' "
        "  AND patient_id BETWEEN 1 AND 15",
    )
    if cur.fetchone()["cnt"] >= 30:
        logger.info("Historical raf_scores (2024/2025) already seeded — skipping.")
        return

    # Fetch 2026 demographics to copy into 2024/2025
    cur.execute(
        "SELECT patient_id, age_band, sex, dual_status, disabled, model_segment "
        "FROM raf_patient_demographics "
        "WHERE measurement_year = 2026 AND patient_id BETWEEN 1 AND 15",
    )
    demo_rows = cur.fetchall()

    # Insert demographics for 2024 and 2025 (required by FK) — skip if already present
    for hist_year in (2024, 2025):
        for d in demo_rows:
            cur.execute(
                """
                INSERT IGNORE INTO raf_patient_demographics
                    (patient_id, measurement_year, age_band, sex, dual_status, disabled, model_segment)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                """,
                (d["patient_id"], hist_year, d["age_band"], d["sex"],
                 d["dual_status"], d["disabled"], d["model_segment"]),
            )

    logger.info("Ensured raf_patient_demographics rows exist for 2024 and 2025.")

    # Remove any existing partial score rows for these years before rebuilding
    cur.execute(
        "DELETE FROM raf_scores "
        "WHERE measurement_year IN (2024, 2025) "
        "  AND score_type = 'prospective' "
        "  AND patient_id BETWEEN 1 AND 15",
    )

    logger.info("Seeding historical raf_scores for 2024 and 2025 …")

    inserted = 0
    for hist_year, multiplier in ((2025, 0.93), (2024, 0.85)):
        for pid, (seg, demo, disease, interact, raw, norm, final, hcc_cnt) in V28_SCORES.items():
            h_demo     = round(demo     * multiplier, 4)
            h_disease  = round(disease  * multiplier, 4)
            h_interact = round(interact * multiplier, 4)
            h_raw      = round(raw      * multiplier, 4)
            h_final    = round(final    * multiplier, 4)
            # hcc_count stays the same — same conditions, lower coefficients in prior year
            cur.execute(
                """
                INSERT INTO raf_scores
                    (patient_id, score_type, model_segment,
                     demographic_score, disease_score, interaction_score,
                     total_raw, normalization_factor, final_raf,
                     hcc_count, measurement_year)
                VALUES (%s, 'prospective', %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                    demographic_score = VALUES(demographic_score),
                    disease_score     = VALUES(disease_score),
                    interaction_score = VALUES(interaction_score),
                    total_raw         = VALUES(total_raw),
                    final_raf         = VALUES(final_raf),
                    hcc_count         = VALUES(hcc_count)
                """,
                (pid, seg, h_demo, h_disease, h_interact, h_raw, norm, h_final, hcc_cnt, hist_year),
            )
            inserted += 1

    logger.info("Inserted/updated %d historical raf_scores rows (2024 + 2025).", inserted)


# ---------------------------------------------------------------------------
# CLI support
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO, stream=sys.stdout)
    seed_encounters_scores_demo()
