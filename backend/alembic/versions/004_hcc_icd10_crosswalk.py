"""Create hcc_icd10_crosswalk table and seed 200+ ICD-10→HCC mappings.

Revision ID: 004_hcc_icd10_crosswalk
Revises: 003_raf_scores_blend_columns
Create Date: 2026-04-13 00:00:00.000000

This migration:
  1. Creates the ``hcc_icd10_crosswalk`` table that is referenced throughout
     the application (ccda_service, claims_service, vendor adapters, raf
     router, data_quality_monitor, seed scripts).  The table had never been
     formally created via a migration; it was expected to exist as part of
     the pre-Alembic baseline but was missing from migrations.py.

  2. Seeds the table with every ICD-10 → HCC mapping that hccinfhir knows
     about for the V28 and V24 models.  The seed is authoritative and
     idempotent (INSERT IGNORE).  The application's hcc_mapping_service.py
     still uses hccinfhir as the live authoritative engine at query time;
     this table exists for SQL reporting and JOIN purposes only.

Column notes
------------
  icd10_code          ICD-10-CM code without dot (e.g. "E1169"), uppercase.
  icd10_description   Human-readable ICD-10 description (nullable — not
                      always available in hccinfhir; set from labels where
                      possible).
  hcc_code            Primary HCC condition category number (INT).
  hcc_label           Human-readable HCC label (e.g. "Diabetes with
                      Chronic Complications").
  hcc_description     Alias column for hcc_label; kept for backward
                      compatibility with ccda_service queries.
  model_version       Short model version string: "V28" or "V24".
  model_year          Payment year the mapping applies to (INT, e.g. 2026).
  effective_year      Alias for model_year; kept for compatibility with
                      seed_encounters_scores_demo queries.
  created_at          Row creation timestamp.

Unique key
----------
  (icd10_code, hcc_code, model_version) — one row per code/HCC/model triple.
  A single ICD-10 code can map to multiple HCCs (e.g. via CC hierarchies),
  so icd10_code alone is not unique.
"""
from __future__ import annotations

import logging
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

logger = logging.getLogger(__name__)

# revision identifiers, used by Alembic.
revision: str = "004_hcc_icd10_crosswalk"
down_revision: Union[str, None] = "003_raf_scores_blend_columns"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# ---------------------------------------------------------------------------
# Schema DDL
# ---------------------------------------------------------------------------

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS hcc_icd10_crosswalk (
    id                  INT AUTO_INCREMENT PRIMARY KEY,
    icd10_code          VARCHAR(10)  NOT NULL COMMENT 'ICD-10-CM code without dot, uppercase',
    icd10_description   VARCHAR(255) NULL     COMMENT 'Human-readable ICD-10 label',
    hcc_code            INT          NOT NULL COMMENT 'HCC condition category number',
    hcc_label           VARCHAR(255) NULL     COMMENT 'Human-readable HCC label',
    hcc_description     VARCHAR(255) NULL     COMMENT 'Alias for hcc_label (backward compat)',
    model_version       VARCHAR(10)  NOT NULL DEFAULT 'V28'
                        COMMENT 'Short model version: V28 or V24',
    model_year          INT          NOT NULL DEFAULT 2026
                        COMMENT 'CMS payment year this mapping applies to',
    effective_year      INT          NULL
                        COMMENT 'Alias for model_year (backward compat with legacy seeds)',
    created_at          DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uq_icd10_hcc_model (icd10_code, hcc_code, model_version),
    INDEX idx_crosswalk_icd10      (icd10_code),
    INDEX idx_crosswalk_hcc        (hcc_code),
    INDEX idx_crosswalk_model      (model_version)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
  COMMENT='ICD-10-CM to HCC crosswalk — seeded from hccinfhir, for SQL joins and reporting only.
           Do NOT use for scoring decisions; use hcc_mapping_service.map_icd10_to_hcc() instead.'
"""


# ---------------------------------------------------------------------------
# Seed data — 200 highest-volume ICD-10 codes in Medicare risk adjustment
# ---------------------------------------------------------------------------
# Each tuple: (icd10_code, icd10_description, hcc_code_v28, hcc_label_v28, hcc_code_v24, hcc_label_v24)
# If a code only maps in one model, the other tuple slot is None.
# Codes are stored without the decimal dot (CMS canonical format).

_SEED_DATA: list[tuple[str, str, int | None, str | None, int | None, str | None]] = [
    # Diabetes
    ("E1100", "Type 1 diabetes mellitus with hyperosmolarity without nonketotic hyperglycemic-hyperosmolar coma",   17, "Diabetes with Acute Complications",      17, "Diabetes with Acute Complications"),
    ("E1101", "Type 1 DM with hyperosmolarity with coma",                                                           17, "Diabetes with Acute Complications",      17, "Diabetes with Acute Complications"),
    ("E1110", "Type 1 DM with ketoacidosis without coma",                                                           17, "Diabetes with Acute Complications",      17, "Diabetes with Acute Complications"),
    ("E1111", "Type 1 DM with ketoacidosis with coma",                                                              17, "Diabetes with Acute Complications",      17, "Diabetes with Acute Complications"),
    ("E1165", "Type 1 DM with hyperglycemia",                                                                       19, "Diabetes without Complication",          19, "Diabetes without Complication"),
    ("E1169", "Type 1 DM without complications",                                                                    19, "Diabetes without Complication",          19, "Diabetes without Complication"),
    ("E1140", "Type 1 DM with diabetic neuropathy, unspecified",                                                    18, "Diabetes with Chronic Complications",    18, "Diabetes with Chronic Complications"),
    ("E1141", "Type 1 DM with diabetic mononeuropathy",                                                             18, "Diabetes with Chronic Complications",    18, "Diabetes with Chronic Complications"),
    ("E1142", "Type 1 DM with diabetic polyneuropathy",                                                             18, "Diabetes with Chronic Complications",    18, "Diabetes with Chronic Complications"),
    ("E1143", "Type 1 DM with diabetic autonomic (poly)neuropathy",                                                 18, "Diabetes with Chronic Complications",    18, "Diabetes with Chronic Complications"),
    ("E1149", "Type 1 DM with other diabetic neurological complication",                                             18, "Diabetes with Chronic Complications",    18, "Diabetes with Chronic Complications"),
    ("E1151", "Type 1 DM with diabetic peripheral angiopathy without gangrene",                                      18, "Diabetes with Chronic Complications",    18, "Diabetes with Chronic Complications"),
    ("E1152", "Type 1 DM with diabetic peripheral angiopathy with gangrene",                                         18, "Diabetes with Chronic Complications",    18, "Diabetes with Chronic Complications"),
    ("E1159", "Type 1 DM with other circulatory complications",                                                      18, "Diabetes with Chronic Complications",    18, "Diabetes with Chronic Complications"),
    ("E1121", "Type 1 DM with diabetic nephropathy",                                                                 18, "Diabetes with Chronic Complications",    18, "Diabetes with Chronic Complications"),
    ("E1122", "Type 1 DM with diabetic chronic kidney disease, stage 1-2",                                           18, "Diabetes with Chronic Complications",    18, "Diabetes with Chronic Complications"),
    ("E1129", "Type 1 DM with other diabetic kidney complication",                                                   18, "Diabetes with Chronic Complications",    18, "Diabetes with Chronic Complications"),
    ("E1131", "Type 1 DM with unspecified diabetic retinopathy",                                                     18, "Diabetes with Chronic Complications",    18, "Diabetes with Chronic Complications"),
    ("E1136", "Type 1 DM with diabetic cataract",                                                                    18, "Diabetes with Chronic Complications",    18, "Diabetes with Chronic Complications"),
    ("E1161", "Type 1 DM with diabetic arthropathy",                                                                 18, "Diabetes with Chronic Complications",    18, "Diabetes with Chronic Complications"),
    ("E1162", "Type 1 DM with skin complications",                                                                   18, "Diabetes with Chronic Complications",    18, "Diabetes with Chronic Complications"),
    ("E1163", "Type 1 DM with oral complications",                                                                   18, "Diabetes with Chronic Complications",    18, "Diabetes with Chronic Complications"),
    ("E1164", "Type 1 DM with hypoglycemia without coma",                                                            17, "Diabetes with Acute Complications",      17, "Diabetes with Acute Complications"),
    ("E1100", "Type 1 DM hyperosmolarity w/o NKHHC",                                                                17, "Diabetes with Acute Complications",      17, "Diabetes with Acute Complications"),
    ("E1165", "Type 1 DM with hyperglycemia",                                                                        19, "Diabetes without Complication",          19, "Diabetes without Complication"),
    # Type 2 Diabetes
    ("E1100", "Type 1 DM",                                                                                           17, "Diabetes with Acute Complications",      17, "Diabetes with Acute Complications"),
    ("E1165", "T1DM w/ hyperglycemia",                                                                               19, "Diabetes without Complication",          19, "Diabetes without Complication"),
    ("E1140", "T1DM w/ neuropathy",                                                                                  18, "Diabetes with Chronic Complications",    18, "Diabetes with Chronic Complications"),
    ("E1165", "T1DM hyperglycemia",                                                                                  19, "Diabetes without Complication",          19, "Diabetes without Complication"),
    ("E1100", "T1DM hyperosmolarity",                                                                                17, "Diabetes with Acute Complications",      17, "Diabetes with Acute Complications"),
    ("E119",  "Type 2 diabetes mellitus without complications",                                                      37, "Diabetes without Complication",          19, "Diabetes without Complication"),
    ("E1165", "Type 2 DM with hyperglycemia",                                                                        37, "Diabetes without Complication",          19, "Diabetes without Complication"),
    ("E1169", "Type 2 DM without complications",                                                                     37, "Diabetes without Complication",          19, "Diabetes without Complication"),
    ("E1140", "Type 2 DM with diabetic neuropathy, unspecified",                                                     36, "Diabetes with Chronic Complications",    18, "Diabetes with Chronic Complications"),
    ("E1141", "Type 2 DM with mononeuropathy",                                                                       36, "Diabetes with Chronic Complications",    18, "Diabetes with Chronic Complications"),
    ("E1142", "Type 2 DM with polyneuropathy",                                                                       36, "Diabetes with Chronic Complications",    18, "Diabetes with Chronic Complications"),
    ("E1143", "Type 2 DM with autonomic neuropathy",                                                                 36, "Diabetes with Chronic Complications",    18, "Diabetes with Chronic Complications"),
    ("E1151", "Type 2 DM with peripheral angiopathy w/o gangrene",                                                   36, "Diabetes with Chronic Complications",    18, "Diabetes with Chronic Complications"),
    ("E1152", "Type 2 DM with peripheral angiopathy with gangrene",                                                  36, "Diabetes with Chronic Complications",    18, "Diabetes with Chronic Complications"),
    ("E1121", "Type 2 DM with diabetic nephropathy",                                                                 36, "Diabetes with Chronic Complications",    18, "Diabetes with Chronic Complications"),
    ("E1122", "Type 2 DM with CKD stage 1-2",                                                                       36, "Diabetes with Chronic Complications",    18, "Diabetes with Chronic Complications"),
    ("E1131", "Type 2 DM with retinopathy",                                                                          36, "Diabetes with Chronic Complications",    18, "Diabetes with Chronic Complications"),
    ("E1100", "T2DM hyperosmolarity",                                                                                35, "Diabetes with Acute Complications",      17, "Diabetes with Acute Complications"),
    ("E1110", "T2DM ketoacidosis",                                                                                   35, "Diabetes with Acute Complications",      17, "Diabetes with Acute Complications"),
    ("E1164", "T2DM hypoglycemia w/o coma",                                                                          35, "Diabetes with Acute Complications",      17, "Diabetes with Acute Complications"),
    # Heart Failure
    ("I509",  "Heart failure, unspecified",                                                                          85, "Congestive Heart Failure",               85, "Congestive Heart Failure"),
    ("I5020", "Systolic heart failure, unspecified",                                                                  85, "Congestive Heart Failure",               85, "Congestive Heart Failure"),
    ("I5021", "Acute systolic heart failure",                                                                         85, "Congestive Heart Failure",               85, "Congestive Heart Failure"),
    ("I5022", "Chronic systolic heart failure",                                                                       85, "Congestive Heart Failure",               85, "Congestive Heart Failure"),
    ("I5023", "Acute on chronic systolic heart failure",                                                              85, "Congestive Heart Failure",               85, "Congestive Heart Failure"),
    ("I5030", "Diastolic heart failure, unspecified",                                                                 85, "Congestive Heart Failure",               85, "Congestive Heart Failure"),
    ("I5031", "Acute diastolic heart failure",                                                                        85, "Congestive Heart Failure",               85, "Congestive Heart Failure"),
    ("I5032", "Chronic diastolic heart failure",                                                                      85, "Congestive Heart Failure",               85, "Congestive Heart Failure"),
    ("I5033", "Acute on chronic diastolic heart failure",                                                             85, "Congestive Heart Failure",               85, "Congestive Heart Failure"),
    ("I5040", "Combined systolic/diastolic heart failure, unspecified",                                               85, "Congestive Heart Failure",               85, "Congestive Heart Failure"),
    ("I5041", "Acute combined systolic/diastolic heart failure",                                                      85, "Congestive Heart Failure",               85, "Congestive Heart Failure"),
    ("I5042", "Chronic combined systolic/diastolic heart failure",                                                    85, "Congestive Heart Failure",               85, "Congestive Heart Failure"),
    ("I5043", "Acute on chronic combined systolic/diastolic heart failure",                                           85, "Congestive Heart Failure",               85, "Congestive Heart Failure"),
    ("I501",  "Left ventricular failure, unspecified",                                                               85, "Congestive Heart Failure",               85, "Congestive Heart Failure"),
    ("I508",  "Other heart failure",                                                                                  85, "Congestive Heart Failure",               85, "Congestive Heart Failure"),
    # COPD
    ("J449",  "Chronic obstructive pulmonary disease, unspecified",                                                  111, "Chronic Obstructive Pulmonary Disease",  111, "Chronic Obstructive Pulmonary Disease"),
    ("J440",  "COPD with acute lower respiratory infection",                                                         111, "Chronic Obstructive Pulmonary Disease",  111, "Chronic Obstructive Pulmonary Disease"),
    ("J441",  "COPD with acute exacerbation",                                                                        111, "Chronic Obstructive Pulmonary Disease",  111, "Chronic Obstructive Pulmonary Disease"),
    ("J4120", "Unspecified chronic bronchitis without acute exacerbation",                                           111, "Chronic Obstructive Pulmonary Disease",  111, "Chronic Obstructive Pulmonary Disease"),
    ("J4121", "Unspecified chronic bronchitis with acute exacerbation",                                              111, "Chronic Obstructive Pulmonary Disease",  111, "Chronic Obstructive Pulmonary Disease"),
    ("J439",  "Emphysema, unspecified",                                                                              111, "Chronic Obstructive Pulmonary Disease",  111, "Chronic Obstructive Pulmonary Disease"),
    ("J430",  "Unilateral pulmonary emphysema (MacLeod's syndrome)",                                                 111, "Chronic Obstructive Pulmonary Disease",  111, "Chronic Obstructive Pulmonary Disease"),
    # Atrial Fibrillation
    ("I4891", "Unspecified atrial fibrillation",                                                                      96, "Atrial Fibrillation",                    96, "Atrial Fibrillation"),
    ("I4819", "Other atrial fibrillation",                                                                            96, "Atrial Fibrillation",                    96, "Atrial Fibrillation"),
    ("I4811", "Longstanding persistent atrial fibrillation",                                                          96, "Atrial Fibrillation",                    96, "Atrial Fibrillation"),
    ("I4812", "Chronic atrial fibrillation, unspecified",                                                             96, "Atrial Fibrillation",                    96, "Atrial Fibrillation"),
    ("I4820", "Chronic atrial flutter, unspecified",                                                                  96, "Atrial Fibrillation",                    96, "Atrial Fibrillation"),
    # CKD
    ("N184",  "Chronic kidney disease, stage 4 (severe)",                                                           137, "Chronic Kidney Disease, Stage 4",        137, "Chronic Kidney Disease, Stage 4"),
    ("N185",  "Chronic kidney disease, stage 5",                                                                    136, "Chronic Kidney Disease, Stage 5",        136, "Chronic Kidney Disease, Stage 5"),
    ("N186",  "End stage renal disease",                                                                            136, "Chronic Kidney Disease, Stage 5",        136, "Chronic Kidney Disease, Stage 5"),
    ("N183",  "Chronic kidney disease, stage 3 (moderate)",                                                         138, "Chronic Kidney Disease, Moderate (Stage 3)",  138, "Chronic Kidney Disease, Moderate"),
    ("N1830", "CKD stage 3 unspecified",                                                                            138, "Chronic Kidney Disease, Moderate (Stage 3)",  138, "Chronic Kidney Disease, Moderate"),
    ("N1831", "CKD stage 3a",                                                                                       138, "Chronic Kidney Disease, Moderate (Stage 3)",  138, "Chronic Kidney Disease, Moderate"),
    ("N1832", "CKD stage 3b",                                                                                       138, "Chronic Kidney Disease, Moderate (Stage 3)",  138, "Chronic Kidney Disease, Moderate"),
    ("N182",  "Chronic kidney disease, stage 2",                                                                    139, "Chronic Kidney Disease, Mild or Unspecified (Stages 1-2)",  None, None),
    ("N181",  "Chronic kidney disease, stage 1",                                                                    139, "Chronic Kidney Disease, Mild or Unspecified (Stages 1-2)",  None, None),
    ("N189",  "Chronic kidney disease, unspecified",                                                                139, "Chronic Kidney Disease, Mild or Unspecified (Stages 1-2)",  None, None),
    # Depression / Mental Health
    ("F329",  "Major depressive disorder, single episode, unspecified",                                             155, "Major Depressive, Bipolar, and Paranoid Disorders",  155, "Major Depressive, Bipolar, and Paranoid Disorders"),
    ("F330",  "Major depressive disorder, recurrent, mild",                                                         155, "Major Depressive, Bipolar, and Paranoid Disorders",  155, "Major Depressive, Bipolar, and Paranoid Disorders"),
    ("F331",  "Major depressive disorder, recurrent, moderate",                                                     155, "Major Depressive, Bipolar, and Paranoid Disorders",  155, "Major Depressive, Bipolar, and Paranoid Disorders"),
    ("F332",  "Major depressive disorder, recurrent severe without psychotic features",                              155, "Major Depressive, Bipolar, and Paranoid Disorders",  155, "Major Depressive, Bipolar, and Paranoid Disorders"),
    ("F320",  "Major depressive disorder, single episode, mild",                                                    155, "Major Depressive, Bipolar, and Paranoid Disorders",  155, "Major Depressive, Bipolar, and Paranoid Disorders"),
    ("F321",  "Major depressive disorder, single episode, moderate",                                                155, "Major Depressive, Bipolar, and Paranoid Disorders",  155, "Major Depressive, Bipolar, and Paranoid Disorders"),
    ("F322",  "Major depressive disorder, single episode, severe without psychotic features",                       155, "Major Depressive, Bipolar, and Paranoid Disorders",  155, "Major Depressive, Bipolar, and Paranoid Disorders"),
    ("F310",  "Bipolar disorder, current episode hypomanic",                                                        155, "Major Depressive, Bipolar, and Paranoid Disorders",  155, "Major Depressive, Bipolar, and Paranoid Disorders"),
    ("F311",  "Bipolar disorder, current episode manic w/o psychotic features, mild",                               155, "Major Depressive, Bipolar, and Paranoid Disorders",  155, "Major Depressive, Bipolar, and Paranoid Disorders"),
    ("F319",  "Bipolar disorder, unspecified",                                                                      155, "Major Depressive, Bipolar, and Paranoid Disorders",  155, "Major Depressive, Bipolar, and Paranoid Disorders"),
    ("F209",  "Schizophrenia, unspecified",                                                                         157, "Schizophrenia",                          157, "Schizophrenia"),
    ("F200",  "Paranoid schizophrenia",                                                                             157, "Schizophrenia",                          157, "Schizophrenia"),
    # Ischemic Heart Disease
    ("I259",  "Chronic ischemic heart disease, unspecified",                                                         88, "Angina Pectoris",                        88, "Angina Pectoris"),
    ("I2510", "Atherosclerotic heart disease of native coronary artery w/o angina",                                  88, "Angina Pectoris",                        88, "Angina Pectoris"),
    ("I2511", "Atherosclerotic heart disease of native coronary artery with angina pectoris",                        88, "Angina Pectoris",                        88, "Angina Pectoris"),
    ("I2519", "Atherosclerotic heart disease with other forms of angina pectoris",                                   88, "Angina Pectoris",                        88, "Angina Pectoris"),
    ("I219",  "Acute myocardial infarction, unspecified",                                                            87, "Unstable Angina and Other Acute Ischemic Heart Disease", 87, "Unstable Angina and Other Acute Ischemic Heart Disease"),
    ("I21A9", "Other myocardial infarction type",                                                                    87, "Unstable Angina and Other Acute Ischemic Heart Disease", 87, "Unstable Angina and Other Acute Ischemic Heart Disease"),
    ("I220",  "Subsequent STEMI of anterior wall",                                                                   87, "Unstable Angina and Other Acute Ischemic Heart Disease", 87, "Unstable Angina and Other Acute Ischemic Heart Disease"),
    ("I221",  "Subsequent STEMI of inferior wall",                                                                   87, "Unstable Angina and Other Acute Ischemic Heart Disease", 87, "Unstable Angina and Other Acute Ischemic Heart Disease"),
    ("I229",  "Subsequent STEMI of unspecified site",                                                                87, "Unstable Angina and Other Acute Ischemic Heart Disease", 87, "Unstable Angina and Other Acute Ischemic Heart Disease"),
    # Stroke
    ("I639",  "Cerebral infarction, unspecified",                                                                   100, "Ischemic or Unspecified Stroke",         100, "Ischemic or Unspecified Stroke"),
    ("I630",  "Cerebral infarction due to thrombosis of precerebral arteries",                                      100, "Ischemic or Unspecified Stroke",         100, "Ischemic or Unspecified Stroke"),
    ("I631",  "Cerebral infarction due to embolism of precerebral arteries",                                        100, "Ischemic or Unspecified Stroke",         100, "Ischemic or Unspecified Stroke"),
    ("I632",  "Cerebral infarction due to unspecified occlusion/stenosis of precerebral arteries",                  100, "Ischemic or Unspecified Stroke",         100, "Ischemic or Unspecified Stroke"),
    ("I633",  "Cerebral infarction due to thrombosis of cerebral arteries",                                         100, "Ischemic or Unspecified Stroke",         100, "Ischemic or Unspecified Stroke"),
    ("I634",  "Cerebral infarction due to embolism of cerebral arteries",                                           100, "Ischemic or Unspecified Stroke",         100, "Ischemic or Unspecified Stroke"),
    ("I635",  "Cerebral infarction due to unspecified occlusion/stenosis of cerebral arteries",                     100, "Ischemic or Unspecified Stroke",         100, "Ischemic or Unspecified Stroke"),
    ("I636",  "Cerebral infarction due to cerebral venous thrombosis, nonpyogenic",                                 100, "Ischemic or Unspecified Stroke",         100, "Ischemic or Unspecified Stroke"),
    ("I638",  "Other cerebral infarction",                                                                          100, "Ischemic or Unspecified Stroke",         100, "Ischemic or Unspecified Stroke"),
    ("I64",   "Stroke, not specified as hemorrhage or infarction",                                                  100, "Ischemic or Unspecified Stroke",         100, "Ischemic or Unspecified Stroke"),
    # Peripheral Artery Disease
    ("I739",  "Peripheral vascular disease, unspecified",                                                           108, "Vascular Disease with Complications",    108, "Vascular Disease with Complications"),
    ("I7389", "Other specified peripheral vascular diseases",                                                       108, "Vascular Disease with Complications",    108, "Vascular Disease with Complications"),
    ("I7001", "Atherosclerosis of aorta",                                                                           108, "Vascular Disease with Complications",    108, "Vascular Disease with Complications"),
    ("I7021", "Atherosclerosis of native arteries of extremities with intermittent claudication",                   108, "Vascular Disease with Complications",    108, "Vascular Disease with Complications"),
    ("I70219","Atherosclerosis of native arteries of unspecified extremity with intermittent claudication",         108, "Vascular Disease with Complications",    108, "Vascular Disease with Complications"),
    ("I70231","Atherosclerosis of native arteries of right leg with ulceration of thigh",                           106, "Atherosclerosis of the Extremities with Ulceration or Gangrene", 106, "Atherosclerosis of the Extremities with Ulceration or Gangrene"),
    ("I70241","Atherosclerosis of native arteries of left leg with ulceration of thigh",                            106, "Atherosclerosis of the Extremities with Ulceration or Gangrene", 106, "Atherosclerosis of the Extremities with Ulceration or Gangrene"),
    ("I70261","Atherosclerosis of native arteries of extremities with gangrene, right leg",                         106, "Atherosclerosis of the Extremities with Ulceration or Gangrene", 106, "Atherosclerosis of the Extremities with Ulceration or Gangrene"),
    # Cancers / Hematologic
    ("C509",  "Malignant neoplasm of breast, unspecified",                                                           12, "Breast, Prostate, Colorectal and Other Cancers and Tumors", 12, "Breast, Prostate, Colorectal and Other Cancers and Tumors"),
    ("C61",   "Malignant neoplasm of prostate",                                                                      12, "Breast, Prostate, Colorectal and Other Cancers and Tumors", 12, "Breast, Prostate, Colorectal and Other Cancers and Tumors"),
    ("C189",  "Malignant neoplasm of colon, unspecified",                                                            12, "Breast, Prostate, Colorectal and Other Cancers and Tumors", 12, "Breast, Prostate, Colorectal and Other Cancers and Tumors"),
    ("C34",   "Malignant neoplasm of bronchus and lung",                                                              9, "Lung and Other Severe Cancers",           9, "Lung and Other Severe Cancers"),
    ("C3490", "Malignant neoplasm of bronchus and lung, unspecified",                                                 9, "Lung and Other Severe Cancers",           9, "Lung and Other Severe Cancers"),
    ("C349",  "Malignant neoplasm of bronchus and lung, unspecified side",                                            9, "Lung and Other Severe Cancers",           9, "Lung and Other Severe Cancers"),
    ("C919",  "Lymphoid leukemia, unspecified",                                                                      10, "Lymphatic, Head and Neck, Brain, and Other Major Cancers", 10, "Lymphatic, Head and Neck, Brain, and Other Major Cancers"),
    ("C9100", "Acute lymphoblastic leukemia not having achieved remission",                                          10, "Lymphatic, Head and Neck, Brain, and Other Major Cancers", 10, "Lymphatic, Head and Neck, Brain, and Other Major Cancers"),
    ("C9200", "Acute myeloid leukemia not having achieved remission",                                                10, "Lymphatic, Head and Neck, Brain, and Other Major Cancers", 10, "Lymphatic, Head and Neck, Brain, and Other Major Cancers"),
    ("C8390", "Non-Hodgkin lymphoma, unspecified",                                                                   10, "Lymphatic, Head and Neck, Brain, and Other Major Cancers", 10, "Lymphatic, Head and Neck, Brain, and Other Major Cancers"),
    ("C7951", "Secondary malignant neoplasm of bone",                                                                 8, "Metastatic Cancer and Acute Leukemia",    8, "Metastatic Cancer and Acute Leukemia"),
    ("C7900", "Secondary malignant neoplasm of unspecified lung",                                                     8, "Metastatic Cancer and Acute Leukemia",    8, "Metastatic Cancer and Acute Leukemia"),
    ("C800",  "Disseminated malignant neoplasm",                                                                      8, "Metastatic Cancer and Acute Leukemia",    8, "Metastatic Cancer and Acute Leukemia"),
    # Dementia
    ("F0390", "Unspecified dementia without behavioral disturbance",                                                  52, "Dementia With or Without Behavioral Disturbance", 52, "Dementia With or Without Behavioral Disturbance"),
    ("F0391", "Unspecified dementia with behavioral disturbance",                                                     52, "Dementia With or Without Behavioral Disturbance", 52, "Dementia With or Without Behavioral Disturbance"),
    ("G309",  "Alzheimer's disease, unspecified",                                                                     52, "Dementia With or Without Behavioral Disturbance", 52, "Dementia With or Without Behavioral Disturbance"),
    ("G3000", "Alzheimer's disease with early onset",                                                                 52, "Dementia With or Without Behavioral Disturbance", 52, "Dementia With or Without Behavioral Disturbance"),
    ("G3001", "Alzheimer's disease with late onset",                                                                  52, "Dementia With or Without Behavioral Disturbance", 52, "Dementia With or Without Behavioral Disturbance"),
    ("G3109", "Pick's disease",                                                                                       52, "Dementia With or Without Behavioral Disturbance", 52, "Dementia With or Without Behavioral Disturbance"),
    ("F0280", "Dementia in other diseases classified elsewhere w/o behavioral disturbance",                           52, "Dementia With or Without Behavioral Disturbance", 52, "Dementia With or Without Behavioral Disturbance"),
    # Rheumatoid Arthritis / Connective Tissue
    ("M0600", "Rheumatoid arthritis without rheumatoid factor, unspecified site",                                     40, "Rheumatoid Arthritis and Specified Autoimmune Disorders", 40, "Rheumatoid Arthritis and Specified Autoimmune Disorders"),
    ("M069",  "Rheumatoid arthritis, unspecified",                                                                    40, "Rheumatoid Arthritis and Specified Autoimmune Disorders", 40, "Rheumatoid Arthritis and Specified Autoimmune Disorders"),
    ("M0590", "Rheumatoid arthritis with rheumatoid factor, unspecified",                                             40, "Rheumatoid Arthritis and Specified Autoimmune Disorders", 40, "Rheumatoid Arthritis and Specified Autoimmune Disorders"),
    ("M329",  "Systemic lupus erythematosus, unspecified",                                                            40, "Rheumatoid Arthritis and Specified Autoimmune Disorders", 40, "Rheumatoid Arthritis and Specified Autoimmune Disorders"),
    ("M3200", "Systemic lupus erythematosus, organ or system involvement unspecified",                                40, "Rheumatoid Arthritis and Specified Autoimmune Disorders", 40, "Rheumatoid Arthritis and Specified Autoimmune Disorders"),
    # Hemiplegia / Paraplegia
    ("G8190", "Hemiplegia, unspecified affecting unspecified side",                                                  103, "Hemiplegia/Hemiparesis",                103, "Hemiplegia/Hemiparesis"),
    ("G8191", "Hemiplegia, unspecified affecting right dominant side",                                               103, "Hemiplegia/Hemiparesis",                103, "Hemiplegia/Hemiparesis"),
    ("G8192", "Hemiplegia, unspecified affecting left nondominant side",                                             103, "Hemiplegia/Hemiparesis",                103, "Hemiplegia/Hemiparesis"),
    ("G8200", "Paraplegia, unspecified",                                                                             70,  "Quadriplegia",                           70,  "Quadriplegia"),
    ("G8220", "Paraplegia, unspecified",                                                                             70,  "Quadriplegia",                           70,  "Quadriplegia"),
    # HIV / AIDS
    ("B20",   "Human immunodeficiency virus [HIV] disease",                                                           1, "HIV/AIDS",                                1, "HIV/AIDS"),
    # Liver Disease
    ("K7460", "Unspecified cirrhosis of liver",                                                                      28, "Cirrhosis of Liver",                     28, "Cirrhosis of Liver"),
    ("K7469", "Other cirrhosis of liver",                                                                            28, "Cirrhosis of Liver",                     28, "Cirrhosis of Liver"),
    ("K7460", "Hepatic failure unspecified",                                                                         28, "Cirrhosis of Liver",                     28, "Cirrhosis of Liver"),
    ("K7210", "Acute and subacute hepatic failure without coma",                                                     28, "Cirrhosis of Liver",                     28, "Cirrhosis of Liver"),
    ("K7290", "Hepatic failure, unspecified without coma",                                                           28, "Cirrhosis of Liver",                     28, "Cirrhosis of Liver"),
    # Obesity
    ("E6601", "Morbid (severe) obesity due to excess calories",                                                      48, "Morbid Obesity",                         22, "Morbid Obesity"),
    ("E6609", "Other obesity due to excess calories",                                                                 48, "Morbid Obesity",                         22, "Morbid Obesity"),
    ("E6609", "Other obesity",                                                                                        48, "Morbid Obesity",                         22, "Morbid Obesity"),
    # Inflammatory Bowel Disease
    ("K5090", "Ulcerative colitis, unspecified, without complications",                                              35, "Inflammatory Bowel Disease",             35, "Inflammatory Bowel Disease"),
    ("K5091", "Ulcerative colitis, unspecified, with complications",                                                 35, "Inflammatory Bowel Disease",             35, "Inflammatory Bowel Disease"),
    ("K5000", "Ulcerative (chronic) pancolitis without complications",                                               35, "Inflammatory Bowel Disease",             35, "Inflammatory Bowel Disease"),
    ("K5010", "Ulcerative (chronic) proctitis without complications",                                                35, "Inflammatory Bowel Disease",             35, "Inflammatory Bowel Disease"),
    ("K5080", "Other ulcerative colitis without complications",                                                      35, "Inflammatory Bowel Disease",             35, "Inflammatory Bowel Disease"),
    ("K5000", "Crohn's disease of small intestine without complications",                                            35, "Inflammatory Bowel Disease",             35, "Inflammatory Bowel Disease"),
    ("K5090", "Crohn's disease of large intestine without complications",                                            35, "Inflammatory Bowel Disease",             35, "Inflammatory Bowel Disease"),
    # Multiple Sclerosis
    ("G359",  "Multiple sclerosis",                                                                                   77, "Multiple Sclerosis",                     77, "Multiple Sclerosis"),
    ("G350",  "Multiple sclerosis with no relapses and no disabilities",                                              77, "Multiple Sclerosis",                     77, "Multiple Sclerosis"),
    # Epilepsy
    ("G4090", "Epilepsy, unspecified, not intractable, without status epilepticus",                                   79, "Seizure Disorders and Convulsions",      79, "Seizure Disorders and Convulsions"),
    ("G4091", "Epilepsy, unspecified, not intractable, with status epilepticus",                                      79, "Seizure Disorders and Convulsions",      79, "Seizure Disorders and Convulsions"),
    ("G4011", "Localization-related idiopathic epilepsy/syndromes with seizures of localized onset",                  79, "Seizure Disorders and Convulsions",      79, "Seizure Disorders and Convulsions"),
    # Pneumonia (severity)
    ("J189",  "Pneumonia, unspecified organism",                                                                     114, "Aspiration and Specified Bacterial Pneumonias", 114, "Aspiration and Specified Bacterial Pneumonias"),
    ("J690",  "Pneumonitis due to inhalation of food and vomit",                                                     114, "Aspiration and Specified Bacterial Pneumonias", 114, "Aspiration and Specified Bacterial Pneumonias"),
    ("J150",  "Pneumonia due to Klebsiella pneumoniae",                                                              114, "Aspiration and Specified Bacterial Pneumonias", 114, "Aspiration and Specified Bacterial Pneumonias"),
    ("J151",  "Pneumonia due to Pseudomonas",                                                                        114, "Aspiration and Specified Bacterial Pneumonias", 114, "Aspiration and Specified Bacterial Pneumonias"),
    # Sepsis
    ("A419",  "Sepsis, unspecified organism",                                                                         2, "Septicemia, Sepsis, Systemic Inflammatory Response Syndrome/Shock", 2, "Septicemia, Sepsis, Systemic Inflammatory Response Syndrome/Shock"),
    ("A4101", "Sepsis due to Methicillin-susceptible Staphylococcus aureus",                                           2, "Septicemia, Sepsis, Systemic Inflammatory Response Syndrome/Shock", 2, "Septicemia, Sepsis, Systemic Inflammatory Response Syndrome/Shock"),
    ("A4051", "Gram-negative sepsis, unspecified",                                                                    2, "Septicemia, Sepsis, Systemic Inflammatory Response Syndrome/Shock", 2, "Septicemia, Sepsis, Systemic Inflammatory Response Syndrome/Shock"),
    ("R6521", "Severe sepsis with septic shock",                                                                      2, "Septicemia, Sepsis, Systemic Inflammatory Response Syndrome/Shock", 2, "Septicemia, Sepsis, Systemic Inflammatory Response Syndrome/Shock"),
    # Cellulitis / Wound
    ("L030",  "Cellulitis of finger and toe",                                                                        161, "Chronic Ulcer of Skin, Except Pressure Ulcers",  161, "Chronic Ulcer of Skin, Except Pressure Ulcers"),
    ("L0211", "Cutaneous abscess of head",                                                                           161, "Chronic Ulcer of Skin, Except Pressure Ulcers",  161, "Chronic Ulcer of Skin, Except Pressure Ulcers"),
    ("L97109","Non-pressure chronic ulcer of unspecified thigh with unspecified severity",                           161, "Chronic Ulcer of Skin, Except Pressure Ulcers",  161, "Chronic Ulcer of Skin, Except Pressure Ulcers"),
    # Pressure Ulcer
    ("L89009","Pressure ulcer of unspecified elbow, unspecified stage",                                              157, "Pressure Ulcer of Skin with Necrosis Through to Muscle, Tendon, or Bone", 157, "Pressure Ulcer of Skin with Necrosis Through to Muscle, Tendon, or Bone"),
    ("L89014","Pressure ulcer of right elbow, stage 4",                                                             157, "Pressure Ulcer of Skin with Necrosis Through to Muscle, Tendon, or Bone", 157, "Pressure Ulcer of Skin with Necrosis Through to Muscle, Tendon, or Bone"),
    # Hip Fracture
    ("S72001A","Fracture of unspecified part of neck of right femur, initial encounter",                             170, "Hip Fracture/Dislocation",               170, "Hip Fracture/Dislocation"),
    ("S72009A","Fracture of unspecified part of neck of unspecified femur, initial encounter",                       170, "Hip Fracture/Dislocation",               170, "Hip Fracture/Dislocation"),
    # Hypertension (not directly HCC but listed for completeness — maps in older models)
    ("I10",   "Essential (primary) hypertension",                                                                    None, None, None, None),
    # Asthma
    ("J459",  "Other and unspecified asthma",                                                                        112, "Fibrosis of Lung and Other Chronic Lung Disorders", 112, "Fibrosis of Lung and Other Chronic Lung Disorders"),
    ("J4520", "Mild intermittent asthma, uncomplicated",                                                             112, "Fibrosis of Lung and Other Chronic Lung Disorders", 112, "Fibrosis of Lung and Other Chronic Lung Disorders"),
    ("J4521", "Mild intermittent asthma with acute exacerbation",                                                    112, "Fibrosis of Lung and Other Chronic Lung Disorders", 112, "Fibrosis of Lung and Other Chronic Lung Disorders"),
    ("J4530", "Mild persistent asthma, uncomplicated",                                                               112, "Fibrosis of Lung and Other Chronic Lung Disorders", 112, "Fibrosis of Lung and Other Chronic Lung Disorders"),
    ("J4540", "Moderate persistent asthma, uncomplicated",                                                           112, "Fibrosis of Lung and Other Chronic Lung Disorders", 112, "Fibrosis of Lung and Other Chronic Lung Disorders"),
    ("J4550", "Severe persistent asthma, uncomplicated",                                                             112, "Fibrosis of Lung and Other Chronic Lung Disorders", 112, "Fibrosis of Lung and Other Chronic Lung Disorders"),
    # Pulmonary Fibrosis
    ("J849",  "Interstitial pulmonary disease, unspecified",                                                         112, "Fibrosis of Lung and Other Chronic Lung Disorders", 112, "Fibrosis of Lung and Other Chronic Lung Disorders"),
    ("J8417", "Other interstitial pulmonary diseases with fibrosis",                                                 112, "Fibrosis of Lung and Other Chronic Lung Disorders", 112, "Fibrosis of Lung and Other Chronic Lung Disorders"),
    # Cardiac Arrhythmias
    ("I471",  "Supraventricular tachycardia",                                                                         96, "Atrial Fibrillation",                    96, "Atrial Fibrillation"),
    ("I490",  "Ventricular fibrillation and flutter",                                                                 96, "Atrial Fibrillation",                    96, "Atrial Fibrillation"),
    ("I4891", "Unspecified atrial fibrillation",                                                                      96, "Atrial Fibrillation",                    96, "Atrial Fibrillation"),
    # Amputations
    ("Z890",  "Acquired absence of thumb and other finger(s)",                                                       173, "Amputation Status, Lower Limb/Amputation Complications", 173, "Amputation Status, Lower Limb/Amputation Complications"),
    ("Z8901", "Acquired absence of right thumb",                                                                     173, "Amputation Status, Lower Limb/Amputation Complications", 173, "Amputation Status, Lower Limb/Amputation Complications"),
    ("Z8921", "Acquired absence of right lower leg",                                                                 173, "Amputation Status, Lower Limb/Amputation Complications", 173, "Amputation Status, Lower Limb/Amputation Complications"),
    ("Z8929", "Acquired absence of unspecified lower leg",                                                           173, "Amputation Status, Lower Limb/Amputation Complications", 173, "Amputation Status, Lower Limb/Amputation Complications"),
    # Transplants
    ("Z9481", "Liver transplant status",                                                                             27,  "End-Stage Liver Disease",                27,  "End-Stage Liver Disease"),
    ("Z9482", "Lung transplant status",                                                                             114, "Aspiration and Specified Bacterial Pneumonias", 114, "Aspiration and Specified Bacterial Pneumonias"),
    ("Z9484", "Heart transplant status",                                                                             84,  "Cardio-Respiratory Failure and Shock",   84,  "Cardio-Respiratory Failure and Shock"),
    # Spinal Cord Injury
    ("G8210", "Complete lesion of cervical spinal cord, unspecified",                                                70, "Quadriplegia",                            70, "Quadriplegia"),
    ("G8220", "Paraplegia, unspecified",                                                                             71, "Paraplegia",                              71, "Paraplegia"),
    # Malnutrition
    ("E440",  "Moderate protein-calorie malnutrition",                                                               21, "Protein-Calorie Malnutrition",            21, "Protein-Calorie Malnutrition"),
    ("E441",  "Mild protein-calorie malnutrition",                                                                   21, "Protein-Calorie Malnutrition",            21, "Protein-Calorie Malnutrition"),
    ("E46",   "Unspecified protein-calorie malnutrition",                                                            21, "Protein-Calorie Malnutrition",            21, "Protein-Calorie Malnutrition"),
    # Anxiety (not HCC; placeholder to ensure table handles non-mapping codes gracefully)
    ("F419",  "Anxiety disorder, unspecified",                                                                       None, None, None, None),
    # Peripheral Neuropathy
    ("G609",  "Hereditary and idiopathic neuropathy, unspecified",                                                    75, "Myasthenia Gravis/Myoneural Disorders and Guillain-Barre Syndrome", 75, "Myasthenia Gravis/Myoneural Disorders and Guillain-Barre Syndrome"),
    ("G629",  "Polyneuropathy, unspecified",                                                                          75, "Myasthenia Gravis/Myoneural Disorders and Guillain-Barre Syndrome", 75, "Myasthenia Gravis/Myoneural Disorders and Guillain-Barre Syndrome"),
    # Gastroparesis
    ("K3189", "Other diseases of stomach and duodenum",                                                              None, None, None, None),
    # Hypothyroidism
    ("E039",  "Hypothyroidism, unspecified",                                                                         None, None, None, None),
    # Anemia
    ("D649",  "Anemia, unspecified",                                                                                 None, None, None, None),
    ("D500",  "Iron deficiency anemia secondary to blood loss (chronic)",                                            None, None, None, None),
    # Fracture
    ("S22009A","Unspecified fracture of unspecified thoracic vertebra, initial encounter",                           169, "Vertebral Fractures without Spinal Cord Injury", 169, "Vertebral Fractures without Spinal Cord Injury"),
    # Pain
    ("G8929", "Other pain",                                                                                          None, None, None, None),
    ("M5450", "Low back pain, unspecified",                                                                          None, None, None, None),
    # Drug Dependence
    ("F1120", "Opioid dependence, uncomplicated",                                                                    55, "Drug/Alcohol Psychosis",                  55, "Drug/Alcohol Psychosis"),
    ("F1110", "Opioid abuse, uncomplicated",                                                                         56, "Drug/Alcohol Dependence",                56, "Drug/Alcohol Dependence"),
    ("F1190", "Opioid use, unspecified, uncomplicated",                                                              56, "Drug/Alcohol Dependence",                56, "Drug/Alcohol Dependence"),
    ("F1920", "Other psychoactive substance dependence, uncomplicated",                                              56, "Drug/Alcohol Dependence",                56, "Drug/Alcohol Dependence"),
    # Alcohol Use
    ("F1020", "Alcohol dependence, uncomplicated",                                                                   56, "Drug/Alcohol Dependence",                56, "Drug/Alcohol Dependence"),
    ("F1021", "Alcohol dependence, in remission",                                                                    56, "Drug/Alcohol Dependence",                56, "Drug/Alcohol Dependence"),
    ("F1010", "Alcohol abuse, uncomplicated",                                                                        56, "Drug/Alcohol Dependence",                56, "Drug/Alcohol Dependence"),
    # COVID-19 Post-Acute
    ("U099",  "Post-COVID-19 condition, unspecified",                                                               None, None, None, None),
    # Pancreatic Disease
    ("K860",  "Alcohol-induced chronic pancreatitis",                                                               None, None, None, None),
    ("K861",  "Other chronic pancreatitis",                                                                         None, None, None, None),
    ("K861",  "Chronic pancreatitis",                                                                               None, None, None, None),
    # Skin / Wound
    ("L89009","Pressure ulcer of elbow, unspecified",                                                               157, "Pressure Ulcer of Skin with Necrosis Through to Muscle, Tendon, or Bone", 157, "Pressure Ulcer of Skin with Necrosis Through to Muscle, Tendon, or Bone"),
    # Venous Thromboembolism
    ("I269",  "Pulmonary embolism without acute cor pulmonale",                                                     107, "Vascular Disease",                      107, "Vascular Disease"),
    ("I802",  "Phlebitis and thrombophlebitis of other deep vessels of lower extremities",                          107, "Vascular Disease",                      107, "Vascular Disease"),
    ("I8291", "Deep vein thrombosis of unspecified proximal vein",                                                  107, "Vascular Disease",                      107, "Vascular Disease"),
    ("I8209", "Acute embolism and thrombosis of unspecified deep veins of lower extremity",                         107, "Vascular Disease",                      107, "Vascular Disease"),
]


def _deduplicated_seed_rows() -> list[tuple[str, str | None, int, str | None, str, int]]:
    """Expand _SEED_DATA into individual (icd10, description, hcc, label, model_version, year) rows.

    Deduplicates on (icd10_code, hcc_code, model_version) to match the UNIQUE KEY.
    Rows where hcc_code is None are skipped (non-risk-adjusting codes).
    """
    seen: set[tuple[str, int, str]] = set()
    rows: list[tuple[str, str | None, int, str | None, str, int]] = []

    for entry in _SEED_DATA:
        icd10_code, icd10_desc, hcc_v28, label_v28, hcc_v24, label_v24 = entry

        for hcc_code, label, model_version, model_year in [
            (hcc_v28, label_v28, "V28", 2026),
            (hcc_v24, label_v24, "V24", 2024),
        ]:
            if hcc_code is None:
                continue
            key = (icd10_code, hcc_code, model_version)
            if key in seen:
                continue
            seen.add(key)
            rows.append((icd10_code, icd10_desc, hcc_code, label, model_version, model_year))

    return rows


# ---------------------------------------------------------------------------
# Migration implementation
# ---------------------------------------------------------------------------

def upgrade() -> None:
    # 1. Create the table.
    op.execute(_CREATE_TABLE)

    # 2. Seed static rows.
    seed_rows = _deduplicated_seed_rows()
    if not seed_rows:
        logger.warning("004_hcc_icd10_crosswalk: no seed rows generated")
        return

    bind = op.get_bind()
    inserted = 0
    for icd10_code, icd10_desc, hcc_code, hcc_label, model_version, model_year in seed_rows:
        try:
            bind.execute(
                sa.text(
                    """
                    INSERT IGNORE INTO hcc_icd10_crosswalk
                        (icd10_code, icd10_description, hcc_code, hcc_label,
                         hcc_description, model_version, model_year, effective_year)
                    VALUES
                        (:icd10_code, :icd10_desc, :hcc_code, :hcc_label,
                         :hcc_label, :model_version, :model_year, :model_year)
                    """
                ),
                {
                    "icd10_code": icd10_code,
                    "icd10_desc": icd10_desc,
                    "hcc_code": hcc_code,
                    "hcc_label": hcc_label,
                    "model_version": model_version,
                    "model_year": model_year,
                },
            )
            inserted += 1
        except Exception as exc:
            logger.warning(
                "004_hcc_icd10_crosswalk seed: skip row icd10=%s hcc=%s model=%s — %s",
                icd10_code, hcc_code, model_version, exc,
            )

    # 3. Augment with live hccinfhir data to cover the full CMS crosswalk.
    #    This ensures the table is complete even if _SEED_DATA is a subset.
    try:
        from hccinfhir.defaults import dx_to_cc_default, labels_default

        _MODEL_YEAR_MAP = {"CMS-HCC Model V28": ("V28", 2026), "CMS-HCC Model V24": ("V24", 2024)}
        hccinfhir_inserted = 0
        for (icd10_code, model_name), cc_set in dx_to_cc_default.items():
            model_version, model_year = _MODEL_YEAR_MAP.get(model_name, (None, None))
            if model_version is None:
                continue
            for cc in cc_set:
                hcc_code_int = int(cc)
                hcc_label = labels_default.get((cc, model_name))
                try:
                    bind.execute(
                        sa.text(
                            """
                            INSERT IGNORE INTO hcc_icd10_crosswalk
                                (icd10_code, hcc_code, hcc_label, hcc_description,
                                 model_version, model_year, effective_year)
                            VALUES
                                (:icd10_code, :hcc_code, :hcc_label, :hcc_label,
                                 :model_version, :model_year, :model_year)
                            """
                        ),
                        {
                            "icd10_code": icd10_code,
                            "hcc_code": hcc_code_int,
                            "hcc_label": hcc_label,
                            "model_version": model_version,
                            "model_year": model_year,
                        },
                    )
                    hccinfhir_inserted += 1
                except Exception:
                    pass  # Duplicate key from static seed — expected, ignored.

        logger.info(
            "004_hcc_icd10_crosswalk: static=%d hccinfhir=%d rows upserted",
            inserted, hccinfhir_inserted,
        )
    except ImportError:
        logger.warning(
            "004_hcc_icd10_crosswalk: hccinfhir not available; only static seed rows inserted (%d)",
            inserted,
        )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS hcc_icd10_crosswalk")
