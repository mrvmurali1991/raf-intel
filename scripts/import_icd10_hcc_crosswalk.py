#!/usr/bin/env python3
"""
import_icd10_hcc_crosswalk.py
------------------------------
Generates a comprehensive ICD-10-CM to CMS-HCC V28 crosswalk and inserts it
into the hcc_icd10_crosswalk table in the raf_intelligence MySQL database.

The raf_intelligence database and the hcc_icd10_crosswalk table are created
automatically if they do not already exist.

Dependencies:
    pip install simple-icd-10-cm mysql-connector-python

Usage:
    python scripts/import_icd10_hcc_crosswalk.py
"""

from __future__ import annotations

import sys
import logging
from typing import Optional

import mysql.connector
from mysql.connector import Error as MySQLError

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Database connection – mirrors settings in backend/app/config.py
# ---------------------------------------------------------------------------
DB_CONFIG = dict(
    host="127.0.0.1",
    port=3309,
    user="root",
    password="root",
    charset="utf8mb4",
    collation="utf8mb4_unicode_ci",
    autocommit=False,
    connect_timeout=10,
)

# ---------------------------------------------------------------------------
# DDL – create raf_intelligence database and hcc_icd10_crosswalk table
# ---------------------------------------------------------------------------
CREATE_DB = "CREATE DATABASE IF NOT EXISTS raf_intelligence CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"

CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS raf_intelligence.hcc_icd10_crosswalk (
    id                  INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    icd10_code          VARCHAR(10)   NOT NULL,
    icd10_description   VARCHAR(500)  NOT NULL,
    hcc_code            SMALLINT UNSIGNED NOT NULL,
    hcc_label           VARCHAR(255)  NOT NULL,
    effective_year      YEAR          NOT NULL DEFAULT 2024,
    created_at          DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at          DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uq_crosswalk_code_year (icd10_code, hcc_code, effective_year),
    INDEX idx_icd10_code   (icd10_code),
    INDEX idx_hcc_code     (hcc_code),
    INDEX idx_effective_year (effective_year)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
"""

# Migration: add condition_group column if it does not yet exist
ADD_CONDITION_GROUP_COL = """
ALTER TABLE raf_intelligence.hcc_icd10_crosswalk
    ADD COLUMN condition_group VARCHAR(64) NOT NULL DEFAULT '' COMMENT 'Clinical grouping'
    AFTER hcc_label;
"""

# ---------------------------------------------------------------------------
# Master crosswalk definition
# Format: (icd10_code, icd10_desc, hcc_v28, hcc_label, condition_group)
# Source: CMS-HCC V28 ICD-10 Mappings (2024 model)
# ---------------------------------------------------------------------------
RAW_MAPPINGS: list[tuple[str, str, int, str, str]] = [

    # -----------------------------------------------------------------------
    # HIV (HCC 1)
    # -----------------------------------------------------------------------
    ("B20",     "Human immunodeficiency virus [HIV] disease",                                                        1,  "HIV/AIDS",                          "HIV"),

    # -----------------------------------------------------------------------
    # Cancer (HCC 8–12)
    # -----------------------------------------------------------------------
    ("C34.10",  "Malignant neoplasm of upper lobe bronchus/lung, unspecified",                                       9,  "Lung and Other Severe Cancers",     "Cancer"),
    ("C34.11",  "Malignant neoplasm of upper lobe, right bronchus/lung",                                             9,  "Lung and Other Severe Cancers",     "Cancer"),
    ("C34.12",  "Malignant neoplasm of upper lobe, left bronchus/lung",                                              9,  "Lung and Other Severe Cancers",     "Cancer"),
    ("C34.30",  "Malignant neoplasm of lower lobe bronchus/lung, unspecified",                                       9,  "Lung and Other Severe Cancers",     "Cancer"),
    ("C34.31",  "Malignant neoplasm of lower lobe, right bronchus/lung",                                             9,  "Lung and Other Severe Cancers",     "Cancer"),
    ("C34.32",  "Malignant neoplasm of lower lobe, left bronchus/lung",                                              9,  "Lung and Other Severe Cancers",     "Cancer"),
    ("C50.911", "Malignant neoplasm of unspecified site of right female breast",                                     11, "Colorectal, Bladder, and Other Cancers", "Cancer"),
    ("C50.912", "Malignant neoplasm of unspecified site of left female breast",                                      11, "Colorectal, Bladder, and Other Cancers", "Cancer"),
    ("C18.9",   "Malignant neoplasm of colon, unspecified",                                                          11, "Colorectal, Bladder, and Other Cancers", "Cancer"),
    ("C20",     "Malignant neoplasm of rectum",                                                                      11, "Colorectal, Bladder, and Other Cancers", "Cancer"),
    ("C61",     "Malignant neoplasm of prostate",                                                                    11, "Colorectal, Bladder, and Other Cancers", "Cancer"),
    ("C67.9",   "Malignant neoplasm of bladder, unspecified",                                                        11, "Colorectal, Bladder, and Other Cancers", "Cancer"),
    ("C25.9",   "Malignant neoplasm of pancreas, unspecified",                                                        8, "Metastatic Cancer and Acute Leukemia", "Cancer"),
    ("C80.1",   "Malignant (primary) neoplasm, unspecified",                                                          8, "Metastatic Cancer and Acute Leukemia", "Cancer"),
    ("C78.00",  "Secondary malignant neoplasm of unspecified lung",                                                   8, "Metastatic Cancer and Acute Leukemia", "Cancer"),
    ("C79.51",  "Secondary malignant neoplasm of bone",                                                               8, "Metastatic Cancer and Acute Leukemia", "Cancer"),
    ("C79.81",  "Secondary malignant neoplasm of breast",                                                             8, "Metastatic Cancer and Acute Leukemia", "Cancer"),
    ("C91.00",  "Acute lymphoblastic leukemia not having achieved remission",                                          8, "Metastatic Cancer and Acute Leukemia", "Cancer"),
    ("C92.00",  "Acute myeloblastic leukemia, not having achieved remission",                                          8, "Metastatic Cancer and Acute Leukemia", "Cancer"),
    ("C83.30",  "Diffuse large B-cell lymphoma, unspecified site",                                                   10, "Lymphatic, Head and Neck, Brain, and Other Major Cancers", "Cancer"),
    ("C85.10",  "Unspecified B-cell lymphoma, unspecified site",                                                     10, "Lymphatic, Head and Neck, Brain, and Other Major Cancers", "Cancer"),
    ("C90.00",  "Multiple myeloma not having achieved remission",                                                    10, "Lymphatic, Head and Neck, Brain, and Other Major Cancers", "Cancer"),
    ("C71.9",   "Malignant neoplasm of brain, unspecified",                                                          10, "Lymphatic, Head and Neck, Brain, and Other Major Cancers", "Cancer"),
    ("C73",     "Malignant neoplasm of thyroid gland",                                                               12, "Other Specified Cancers",           "Cancer"),
    ("C43.9",   "Malignant melanoma of skin, unspecified",                                                           12, "Other Specified Cancers",           "Cancer"),
    ("C56.9",   "Malignant neoplasm of unspecified ovary",                                                           12, "Other Specified Cancers",           "Cancer"),
    ("C54.1",   "Malignant neoplasm of endometrium",                                                                 12, "Other Specified Cancers",           "Cancer"),
    ("C64.9",   "Malignant neoplasm of unspecified kidney, except renal pelvis",                                     12, "Other Specified Cancers",           "Cancer"),

    # -----------------------------------------------------------------------
    # Hepatitis (HCC 29)
    # -----------------------------------------------------------------------
    ("B18.0",   "Chronic viral hepatitis B with delta-agent",                                                        29, "Chronic Hepatitis",                 "Hepatitis"),
    ("B18.1",   "Chronic viral hepatitis B without delta-agent",                                                     29, "Chronic Hepatitis",                 "Hepatitis"),
    ("B18.2",   "Chronic viral hepatitis C",                                                                         29, "Chronic Hepatitis",                 "Hepatitis"),
    ("B18.8",   "Other chronic viral hepatitis",                                                                     29, "Chronic Hepatitis",                 "Hepatitis"),
    ("B18.9",   "Chronic viral hepatitis, unspecified",                                                              29, "Chronic Hepatitis",                 "Hepatitis"),

    # -----------------------------------------------------------------------
    # Malnutrition (HCC 21)
    # -----------------------------------------------------------------------
    ("E40",     "Kwashiorkor",                                                                                        21, "Protein-Calorie Malnutrition",      "Malnutrition"),
    ("E41",     "Nutritional marasmus",                                                                               21, "Protein-Calorie Malnutrition",      "Malnutrition"),
    ("E42",     "Marasmic kwashiorkor",                                                                               21, "Protein-Calorie Malnutrition",      "Malnutrition"),
    ("E43",     "Unspecified severe protein-calorie malnutrition",                                                    21, "Protein-Calorie Malnutrition",      "Malnutrition"),
    ("E44.0",   "Moderate protein-calorie malnutrition",                                                              21, "Protein-Calorie Malnutrition",      "Malnutrition"),
    ("E44.1",   "Mild protein-calorie malnutrition",                                                                  21, "Protein-Calorie Malnutrition",      "Malnutrition"),
    ("E46",     "Unspecified protein-calorie malnutrition",                                                           21, "Protein-Calorie Malnutrition",      "Malnutrition"),

    # -----------------------------------------------------------------------
    # Morbid obesity (HCC 22)
    # -----------------------------------------------------------------------
    ("E66.01",  "Morbid (severe) obesity due to excess calories",                                                    22, "Morbid Obesity",                    "Obesity"),
    ("E66.09",  "Other obesity due to excess calories",                                                              22, "Morbid Obesity",                    "Obesity"),
    ("E66.1",   "Drug-induced obesity",                                                                              22, "Morbid Obesity",                    "Obesity"),

    # -----------------------------------------------------------------------
    # Diabetes (HCC 17, 18, 19, 35)
    # -----------------------------------------------------------------------
    ("E10.10",  "Type 1 diabetes mellitus with ketoacidosis without coma",                                           17, "Diabetes with Acute Complications", "Diabetes"),
    ("E10.11",  "Type 1 diabetes mellitus with ketoacidosis with coma",                                              17, "Diabetes with Acute Complications", "Diabetes"),
    ("E10.641", "Type 1 diabetes with hypoglycemia with coma",                                                       17, "Diabetes with Acute Complications", "Diabetes"),
    ("E11.10",  "Type 2 diabetes mellitus with ketoacidosis without coma",                                           17, "Diabetes with Acute Complications", "Diabetes"),
    ("E11.641", "Type 2 diabetes with hypoglycemia with coma",                                                       17, "Diabetes with Acute Complications", "Diabetes"),
    ("E10.40",  "Type 1 diabetes with diabetic neuropathy, unspecified",                                             18, "Diabetes with Chronic Complications", "Diabetes"),
    ("E10.41",  "Type 1 diabetes with diabetic mononeuropathy",                                                      18, "Diabetes with Chronic Complications", "Diabetes"),
    ("E10.42",  "Type 1 diabetes with diabetic polyneuropathy",                                                      18, "Diabetes with Chronic Complications", "Diabetes"),
    ("E10.43",  "Type 1 diabetes with diabetic autonomic (poly)neuropathy",                                          18, "Diabetes with Chronic Complications", "Diabetes"),
    ("E10.44",  "Type 1 diabetes with diabetic amyotrophy",                                                          18, "Diabetes with Chronic Complications", "Diabetes"),
    ("E10.51",  "Type 1 diabetes with diabetic peripheral angiopathy without gangrene",                              18, "Diabetes with Chronic Complications", "Diabetes"),
    ("E10.52",  "Type 1 diabetes with diabetic peripheral angiopathy with gangrene",                                 18, "Diabetes with Chronic Complications", "Diabetes"),
    ("E10.59",  "Type 1 diabetes with other circulatory complications",                                              18, "Diabetes with Chronic Complications", "Diabetes"),
    ("E10.65",  "Type 1 diabetes with hyperglycemia",                                                                18, "Diabetes with Chronic Complications", "Diabetes"),
    ("E11.21",  "Type 2 diabetes with diabetic nephropathy",                                                         18, "Diabetes with Chronic Complications", "Diabetes"),
    ("E11.22",  "Type 2 diabetes with diabetic chronic kidney disease",                                              18, "Diabetes with Chronic Complications", "Diabetes"),
    ("E11.29",  "Type 2 diabetes with other diabetic kidney complication",                                           18, "Diabetes with Chronic Complications", "Diabetes"),
    ("E11.40",  "Type 2 diabetes with diabetic neuropathy, unspecified",                                             18, "Diabetes with Chronic Complications", "Diabetes"),
    ("E11.41",  "Type 2 diabetes with diabetic mononeuropathy",                                                      18, "Diabetes with Chronic Complications", "Diabetes"),
    ("E11.42",  "Type 2 diabetes with diabetic polyneuropathy",                                                      18, "Diabetes with Chronic Complications", "Diabetes"),
    ("E11.43",  "Type 2 diabetes with diabetic autonomic (poly)neuropathy",                                          18, "Diabetes with Chronic Complications", "Diabetes"),
    ("E11.44",  "Type 2 diabetes with diabetic amyotrophy",                                                          18, "Diabetes with Chronic Complications", "Diabetes"),
    ("E11.51",  "Type 2 diabetes with diabetic peripheral angiopathy without gangrene",                              18, "Diabetes with Chronic Complications", "Diabetes"),
    ("E11.52",  "Type 2 diabetes with diabetic peripheral angiopathy with gangrene",                                 18, "Diabetes with Chronic Complications", "Diabetes"),
    ("E11.59",  "Type 2 diabetes with other circulatory complications",                                              18, "Diabetes with Chronic Complications", "Diabetes"),
    ("E11.65",  "Type 2 diabetes with hyperglycemia",                                                                18, "Diabetes with Chronic Complications", "Diabetes"),
    ("E10.9",   "Type 1 diabetes mellitus without complications",                                                    19, "Diabetes without Complication",     "Diabetes"),
    ("E11.9",   "Type 2 diabetes mellitus without complications",                                                    19, "Diabetes without Complication",     "Diabetes"),
    ("E11.00",  "Type 2 diabetes mellitus with hyperosmolarity without NKHHC",                                       19, "Diabetes without Complication",     "Diabetes"),
    ("E13.9",   "Other specified diabetes mellitus without complications",                                           19, "Diabetes without Complication",     "Diabetes"),
    ("E11.311", "Type 2 diabetes with unspecified diabetic retinopathy with macular edema",                          35, "Diabetic Retinopathy",              "Diabetes"),
    ("E11.319", "Type 2 diabetes with unspecified diabetic retinopathy without macular edema",                       35, "Diabetic Retinopathy",              "Diabetes"),
    ("E11.321", "Type 2 diabetes with mild nonproliferative retinopathy with macular edema",                         35, "Diabetic Retinopathy",              "Diabetes"),
    ("E11.329", "Type 2 diabetes with mild nonproliferative retinopathy without macular edema",                      35, "Diabetic Retinopathy",              "Diabetes"),
    ("E11.351", "Type 2 diabetes with proliferative retinopathy with macular edema",                                 35, "Diabetic Retinopathy",              "Diabetes"),
    ("E10.311", "Type 1 diabetes with unspecified diabetic retinopathy with macular edema",                          35, "Diabetic Retinopathy",              "Diabetes"),

    # -----------------------------------------------------------------------
    # Rheumatoid arthritis (HCC 40)
    # -----------------------------------------------------------------------
    ("M05.10",  "Rheumatoid lung disease with rheumatoid arthritis of unspecified site",                             40, "Rheumatoid Arthritis and Specified Autoimmune Disorders", "Autoimmune"),
    ("M05.30",  "Rheumatoid heart disease with rheumatoid arthritis, unspecified site",                              40, "Rheumatoid Arthritis and Specified Autoimmune Disorders", "Autoimmune"),
    ("M05.70",  "Rheumatoid arthritis with rheumatoid factor, unspecified site",                                     40, "Rheumatoid Arthritis and Specified Autoimmune Disorders", "Autoimmune"),
    ("M05.79",  "Rheumatoid arthritis with rheumatoid factor, multiple sites",                                       40, "Rheumatoid Arthritis and Specified Autoimmune Disorders", "Autoimmune"),
    ("M06.00",  "Rheumatoid arthritis without rheumatoid factor, unspecified site",                                  40, "Rheumatoid Arthritis and Specified Autoimmune Disorders", "Autoimmune"),
    ("M06.09",  "Rheumatoid arthritis without rheumatoid factor, multiple sites",                                    40, "Rheumatoid Arthritis and Specified Autoimmune Disorders", "Autoimmune"),
    ("M32.10",  "Systemic lupus erythematosus, organ or system involvement unspecified",                             40, "Rheumatoid Arthritis and Specified Autoimmune Disorders", "Autoimmune"),
    ("M34.0",   "Progressive systemic sclerosis",                                                                    40, "Rheumatoid Arthritis and Specified Autoimmune Disorders", "Autoimmune"),

    # -----------------------------------------------------------------------
    # Dementia (HCC 51, 52)
    # -----------------------------------------------------------------------
    ("F01.50",  "Vascular dementia without behavioral disturbance",                                                  51, "Dementia With Complications",       "Dementia"),
    ("F01.51",  "Vascular dementia with behavioral disturbance",                                                     51, "Dementia With Complications",       "Dementia"),
    ("F02.80",  "Dementia in other diseases classified elsewhere, without behavioral disturbance",                   51, "Dementia With Complications",       "Dementia"),
    ("F02.81",  "Dementia in other diseases classified elsewhere, with behavioral disturbance",                      51, "Dementia With Complications",       "Dementia"),
    ("F03.90",  "Unspecified dementia without behavioral disturbance",                                               52, "Dementia Without Complication",     "Dementia"),
    ("F03.91",  "Unspecified dementia with behavioral disturbance",                                                  51, "Dementia With Complications",       "Dementia"),
    ("G30.0",   "Alzheimer disease with early onset",                                                                52, "Dementia Without Complication",     "Dementia"),
    ("G30.1",   "Alzheimer disease with late onset",                                                                 52, "Dementia Without Complication",     "Dementia"),
    ("G30.8",   "Other Alzheimer disease",                                                                           52, "Dementia Without Complication",     "Dementia"),
    ("G30.9",   "Alzheimer disease, unspecified",                                                                    52, "Dementia Without Complication",     "Dementia"),
    ("G31.01",  "Pick disease",                                                                                      52, "Dementia Without Complication",     "Dementia"),
    ("G31.09",  "Other frontotemporal dementia",                                                                     52, "Dementia Without Complication",     "Dementia"),

    # -----------------------------------------------------------------------
    # Substance use disorders (HCC 54, 55, 56)
    # -----------------------------------------------------------------------
    ("F10.20",  "Alcohol dependence, uncomplicated",                                                                 56, "Substance Use Disorder, Mild, Except Alcohol and Cannabis", "SubstanceUse"),
    ("F10.21",  "Alcohol dependence, in remission",                                                                  56, "Substance Use Disorder, Mild, Except Alcohol and Cannabis", "SubstanceUse"),
    ("F11.20",  "Opioid dependence, uncomplicated",                                                                  55, "Substance Use Disorder, Moderate/Severe, or Substance Use with Complications", "SubstanceUse"),
    ("F11.21",  "Opioid dependence, in remission",                                                                   55, "Substance Use Disorder, Moderate/Severe, or Substance Use with Complications", "SubstanceUse"),
    ("F11.22",  "Opioid dependence with intoxication",                                                               54, "Substance Use with Psychotic Complications",          "SubstanceUse"),
    ("F11.23",  "Opioid dependence with withdrawal",                                                                 55, "Substance Use Disorder, Moderate/Severe, or Substance Use with Complications", "SubstanceUse"),
    ("F14.20",  "Cocaine dependence, uncomplicated",                                                                 55, "Substance Use Disorder, Moderate/Severe, or Substance Use with Complications", "SubstanceUse"),
    ("F14.22",  "Cocaine dependence with intoxication",                                                              54, "Substance Use with Psychotic Complications",          "SubstanceUse"),
    ("F15.20",  "Other stimulant dependence, uncomplicated",                                                         55, "Substance Use Disorder, Moderate/Severe, or Substance Use with Complications", "SubstanceUse"),
    ("F17.210", "Nicotine dependence, cigarettes, uncomplicated",                                                    56, "Substance Use Disorder, Mild, Except Alcohol and Cannabis", "SubstanceUse"),
    ("F19.20",  "Other psychoactive substance dependence, uncomplicated",                                            55, "Substance Use Disorder, Moderate/Severe, or Substance Use with Complications", "SubstanceUse"),

    # -----------------------------------------------------------------------
    # Schizophrenia (HCC 57)
    # -----------------------------------------------------------------------
    ("F20.0",   "Paranoid schizophrenia",                                                                            57, "Schizophrenia",                     "MentalHealth"),
    ("F20.1",   "Disorganized schizophrenia",                                                                        57, "Schizophrenia",                     "MentalHealth"),
    ("F20.3",   "Undifferentiated schizophrenia",                                                                    57, "Schizophrenia",                     "MentalHealth"),
    ("F20.5",   "Residual schizophrenia",                                                                            57, "Schizophrenia",                     "MentalHealth"),
    ("F20.9",   "Schizophrenia, unspecified",                                                                        57, "Schizophrenia",                     "MentalHealth"),
    ("F25.0",   "Schizoaffective disorder, bipolar type",                                                            57, "Schizophrenia",                     "MentalHealth"),
    ("F25.1",   "Schizoaffective disorder, depressive type",                                                         57, "Schizophrenia",                     "MentalHealth"),

    # -----------------------------------------------------------------------
    # Bipolar disorder (HCC 59)
    # -----------------------------------------------------------------------
    ("F31.0",   "Bipolar disorder, current episode hypomanic",                                                       59, "Major Depressive, Bipolar, and Paranoid Disorders", "MentalHealth"),
    ("F31.10",  "Bipolar disorder, current episode manic without psychotic features, unspecified", 59, "Major Depressive, Bipolar, and Paranoid Disorders", "MentalHealth"),
    ("F31.30",  "Bipolar disorder, current episode depressed, mild or moderate severity, unspecified", 59, "Major Depressive, Bipolar, and Paranoid Disorders", "MentalHealth"),
    ("F31.31",  "Bipolar disorder, current episode depressed, mild",                                                 59, "Major Depressive, Bipolar, and Paranoid Disorders", "MentalHealth"),
    ("F31.32",  "Bipolar disorder, current episode depressed, moderate",                                             59, "Major Depressive, Bipolar, and Paranoid Disorders", "MentalHealth"),
    ("F31.4",   "Bipolar disorder, current episode depressed, severe, without psychotic features",                   59, "Major Depressive, Bipolar, and Paranoid Disorders", "MentalHealth"),
    ("F31.5",   "Bipolar disorder, current episode depressed, severe, with psychotic features",                      59, "Major Depressive, Bipolar, and Paranoid Disorders", "MentalHealth"),
    ("F31.81",  "Bipolar II disorder",                                                                               59, "Major Depressive, Bipolar, and Paranoid Disorders", "MentalHealth"),
    ("F31.9",   "Bipolar disorder, unspecified",                                                                     59, "Major Depressive, Bipolar, and Paranoid Disorders", "MentalHealth"),

    # -----------------------------------------------------------------------
    # Depression (HCC 155)
    # -----------------------------------------------------------------------
    ("F32.0",   "Major depressive disorder, single episode, mild",                                                  155, "Depression",                        "MentalHealth"),
    ("F32.1",   "Major depressive disorder, single episode, moderate",                                              155, "Depression",                        "MentalHealth"),
    ("F32.2",   "Major depressive disorder, single episode, severe without psychotic features",                     155, "Depression",                        "MentalHealth"),
    ("F32.3",   "Major depressive disorder, single episode, severe with psychotic features",                        155, "Depression",                        "MentalHealth"),
    ("F32.4",   "Major depressive disorder, single episode, in partial remission",                                  155, "Depression",                        "MentalHealth"),
    ("F32.5",   "Major depressive disorder, single episode, in full remission",                                     155, "Depression",                        "MentalHealth"),
    ("F32.9",   "Major depressive disorder, single episode, unspecified",                                           155, "Depression",                        "MentalHealth"),
    ("F33.0",   "Major depressive disorder, recurrent, mild",                                                       155, "Depression",                        "MentalHealth"),
    ("F33.1",   "Major depressive disorder, recurrent, moderate",                                                   155, "Depression",                        "MentalHealth"),
    ("F33.2",   "Major depressive disorder, recurrent severe without psychotic features",                           155, "Depression",                        "MentalHealth"),
    ("F33.3",   "Major depressive disorder, recurrent, severe with psychotic symptoms",                             155, "Depression",                        "MentalHealth"),
    ("F33.9",   "Major depressive disorder, recurrent, unspecified",                                                155, "Depression",                        "MentalHealth"),

    # -----------------------------------------------------------------------
    # Multiple sclerosis (HCC 77)
    # -----------------------------------------------------------------------
    ("G35",     "Multiple sclerosis",                                                                                77, "Multiple Sclerosis",                "Neurological"),

    # -----------------------------------------------------------------------
    # Parkinson's disease (HCC 78)
    # -----------------------------------------------------------------------
    ("G20",     "Parkinson disease",                                                                                 78, "Parkinson and Huntington Diseases", "Neurological"),
    ("G21.11",  "Neuroleptic induced parkinsonism",                                                                  78, "Parkinson and Huntington Diseases", "Neurological"),
    ("G21.19",  "Other drug induced secondary parkinsonism",                                                         78, "Parkinson and Huntington Diseases", "Neurological"),
    ("G21.4",   "Vascular parkinsonism",                                                                             78, "Parkinson and Huntington Diseases", "Neurological"),

    # -----------------------------------------------------------------------
    # Heart failure (HCC 85)
    # -----------------------------------------------------------------------
    ("I50.1",   "Left ventricular failure, unspecified",                                                             85, "Congestive Heart Failure",          "CardiacDisease"),
    ("I50.20",  "Unspecified systolic (congestive) heart failure",                                                   85, "Congestive Heart Failure",          "CardiacDisease"),
    ("I50.21",  "Acute systolic (congestive) heart failure",                                                         85, "Congestive Heart Failure",          "CardiacDisease"),
    ("I50.22",  "Chronic systolic (congestive) heart failure",                                                       85, "Congestive Heart Failure",          "CardiacDisease"),
    ("I50.23",  "Acute on chronic systolic (congestive) heart failure",                                              85, "Congestive Heart Failure",          "CardiacDisease"),
    ("I50.30",  "Unspecified diastolic (congestive) heart failure",                                                  85, "Congestive Heart Failure",          "CardiacDisease"),
    ("I50.31",  "Acute diastolic (congestive) heart failure",                                                        85, "Congestive Heart Failure",          "CardiacDisease"),
    ("I50.32",  "Chronic diastolic (congestive) heart failure",                                                      85, "Congestive Heart Failure",          "CardiacDisease"),
    ("I50.33",  "Acute on chronic diastolic (congestive) heart failure",                                             85, "Congestive Heart Failure",          "CardiacDisease"),
    ("I50.40",  "Unspecified combined systolic and diastolic heart failure",                                         85, "Congestive Heart Failure",          "CardiacDisease"),
    ("I50.41",  "Acute combined systolic and diastolic heart failure",                                               85, "Congestive Heart Failure",          "CardiacDisease"),
    ("I50.42",  "Chronic combined systolic and diastolic heart failure",                                             85, "Congestive Heart Failure",          "CardiacDisease"),
    ("I50.43",  "Acute on chronic combined systolic and diastolic heart failure",                                    85, "Congestive Heart Failure",          "CardiacDisease"),
    ("I50.810", "Right heart failure, unspecified",                                                                  85, "Congestive Heart Failure",          "CardiacDisease"),
    ("I50.9",   "Heart failure, unspecified",                                                                        85, "Congestive Heart Failure",          "CardiacDisease"),

    # -----------------------------------------------------------------------
    # Atrial fibrillation (HCC 96)
    # -----------------------------------------------------------------------
    ("I48.0",   "Paroxysmal atrial fibrillation",                                                                    96, "Specified Heart Arrhythmias",       "CardiacDisease"),
    ("I48.11",  "Longstanding persistent atrial fibrillation",                                                       96, "Specified Heart Arrhythmias",       "CardiacDisease"),
    ("I48.19",  "Other persistent atrial fibrillation",                                                              96, "Specified Heart Arrhythmias",       "CardiacDisease"),
    ("I48.20",  "Chronic atrial fibrillation, unspecified",                                                          96, "Specified Heart Arrhythmias",       "CardiacDisease"),
    ("I48.21",  "Permanent atrial fibrillation",                                                                     96, "Specified Heart Arrhythmias",       "CardiacDisease"),
    ("I48.91",  "Unspecified atrial fibrillation",                                                                   96, "Specified Heart Arrhythmias",       "CardiacDisease"),
    ("I48.3",   "Typical atrial flutter",                                                                            96, "Specified Heart Arrhythmias",       "CardiacDisease"),
    ("I48.4",   "Atypical atrial flutter",                                                                           96, "Specified Heart Arrhythmias",       "CardiacDisease"),
    ("I49.01",  "Ventricular fibrillation",                                                                          96, "Specified Heart Arrhythmias",       "CardiacDisease"),
    ("I49.02",  "Ventricular flutter",                                                                               96, "Specified Heart Arrhythmias",       "CardiacDisease"),

    # -----------------------------------------------------------------------
    # Stroke / cerebral infarction (HCC 100–104)
    # -----------------------------------------------------------------------
    ("I63.00",  "Cerebral infarction due to thrombosis of unspecified precerebral artery",                          100, "Ischemic or Unspecified Stroke",     "Stroke"),
    ("I63.10",  "Cerebral infarction due to embolism of unspecified precerebral artery",                            100, "Ischemic or Unspecified Stroke",     "Stroke"),
    ("I63.30",  "Cerebral infarction due to thrombosis of unspecified cerebral artery",                             100, "Ischemic or Unspecified Stroke",     "Stroke"),
    ("I63.40",  "Cerebral infarction due to embolism of unspecified cerebral artery",                               100, "Ischemic or Unspecified Stroke",     "Stroke"),
    ("I63.50",  "Cerebral infarction due to unspecified occlusion/stenosis of cerebral artery",                     100, "Ischemic or Unspecified Stroke",     "Stroke"),
    ("I63.9",   "Cerebral infarction, unspecified",                                                                  100, "Ischemic or Unspecified Stroke",     "Stroke"),
    ("I61.0",   "Intracerebral hemorrhage in hemisphere, subcortical",                                              101, "Hemorrhagic Stroke",                 "Stroke"),
    ("I61.1",   "Intracerebral hemorrhage in hemisphere, cortical",                                                  101, "Hemorrhagic Stroke",                 "Stroke"),
    ("I61.3",   "Intracerebral hemorrhage in brain stem",                                                            101, "Hemorrhagic Stroke",                 "Stroke"),
    ("I61.4",   "Intracerebral hemorrhage in cerebellum",                                                            101, "Hemorrhagic Stroke",                 "Stroke"),
    ("I61.9",   "Nontraumatic intracerebral hemorrhage, unspecified",                                                101, "Hemorrhagic Stroke",                 "Stroke"),
    ("I60.9",   "Nontraumatic subarachnoid hemorrhage, unspecified",                                                101, "Hemorrhagic Stroke",                 "Stroke"),
    ("I69.30",  "Unspecified sequelae of cerebral infarction",                                                      103, "Late Effects of Cerebrovascular Disease, Except Paralysis", "Stroke"),
    ("I69.31",  "Cognitive deficits following cerebral infarction",                                                  103, "Late Effects of Cerebrovascular Disease, Except Paralysis", "Stroke"),
    ("I69.350", "Hemiplegia and hemiparesis following cerebral infarction affecting unspecified side",               104, "Monoplegia, Other Paralysis",        "Stroke"),
    ("I69.351", "Hemiplegia/hemiparesis following cerebral infarction affecting right dominant side",                104, "Monoplegia, Other Paralysis",        "Stroke"),
    ("I69.352", "Hemiplegia/hemiparesis following cerebral infarction affecting left nondominant side",              104, "Monoplegia, Other Paralysis",        "Stroke"),

    # -----------------------------------------------------------------------
    # Vascular disease (HCC 107, 108)
    # -----------------------------------------------------------------------
    ("I70.0",   "Atherosclerosis of aorta",                                                                         108, "Vascular Disease",                  "VascularDisease"),
    ("I70.1",   "Atherosclerosis of renal artery",                                                                   108, "Vascular Disease",                  "VascularDisease"),
    ("I70.201", "Unspecified atherosclerosis of native arteries of extremities, right leg",                          108, "Vascular Disease",                  "VascularDisease"),
    ("I70.211", "Atherosclerosis of native arteries of extremities with intermittent claudication, right leg",       108, "Vascular Disease",                  "VascularDisease"),
    ("I70.221", "Atherosclerosis of native arteries of extremities with rest pain, right leg",                       107, "Vascular Disease with Complications", "VascularDisease"),
    ("I70.231", "Atherosclerosis of native arteries of right leg with ulceration of thigh",                          107, "Vascular Disease with Complications", "VascularDisease"),
    ("I70.241", "Atherosclerosis of native arteries of right leg with ulceration of calf",                           107, "Vascular Disease with Complications", "VascularDisease"),
    ("I70.25",  "Atherosclerosis of native arteries of other extremities with ulceration",                           107, "Vascular Disease with Complications", "VascularDisease"),
    ("I70.261", "Atherosclerosis of native arteries of extremities with gangrene, right leg",                        107, "Vascular Disease with Complications", "VascularDisease"),
    ("I71.00",  "Dissection of unspecified site of aorta",                                                           108, "Vascular Disease",                  "VascularDisease"),
    ("I71.3",   "Abdominal aortic aneurysm, ruptured",                                                               107, "Vascular Disease with Complications", "VascularDisease"),
    ("I71.4",   "Abdominal aortic aneurysm, without mention of rupture",                                             108, "Vascular Disease",                  "VascularDisease"),
    ("I73.01",  "Raynaud syndrome with gangrene",                                                                    107, "Vascular Disease with Complications", "VascularDisease"),
    ("I73.9",   "Peripheral vascular disease, unspecified",                                                          108, "Vascular Disease",                  "VascularDisease"),

    # -----------------------------------------------------------------------
    # COPD (HCC 111)
    # -----------------------------------------------------------------------
    ("J44.0",   "Chronic obstructive pulmonary disease with acute lower respiratory infection",                      111, "Chronic Obstructive Pulmonary Disease", "Pulmonary"),
    ("J44.1",   "Chronic obstructive pulmonary disease with acute exacerbation",                                     111, "Chronic Obstructive Pulmonary Disease", "Pulmonary"),
    ("J44.9",   "Chronic obstructive pulmonary disease, unspecified",                                                111, "Chronic Obstructive Pulmonary Disease", "Pulmonary"),
    ("J43.0",   "Unilateral pulmonary emphysema [MacLeod syndrome]",                                                 111, "Chronic Obstructive Pulmonary Disease", "Pulmonary"),
    ("J43.1",   "Panlobular emphysema",                                                                              111, "Chronic Obstructive Pulmonary Disease", "Pulmonary"),
    ("J43.2",   "Centrilobular emphysema",                                                                           111, "Chronic Obstructive Pulmonary Disease", "Pulmonary"),
    ("J43.9",   "Emphysema, unspecified",                                                                            111, "Chronic Obstructive Pulmonary Disease", "Pulmonary"),
    ("J41.0",   "Simple chronic bronchitis",                                                                         111, "Chronic Obstructive Pulmonary Disease", "Pulmonary"),
    ("J41.1",   "Mucopurulent chronic bronchitis",                                                                   111, "Chronic Obstructive Pulmonary Disease", "Pulmonary"),
    ("J42",     "Unspecified chronic bronchitis",                                                                    111, "Chronic Obstructive Pulmonary Disease", "Pulmonary"),

    # -----------------------------------------------------------------------
    # Chronic kidney disease (HCC 136, 137, 138)
    # -----------------------------------------------------------------------
    ("N18.1",   "Chronic kidney disease, stage 1",                                                                  138, "Chronic Kidney Disease, Stage 1-3",  "RenalDisease"),
    ("N18.2",   "Chronic kidney disease, stage 2 (mild)",                                                           138, "Chronic Kidney Disease, Stage 1-3",  "RenalDisease"),
    ("N18.30",  "Chronic kidney disease, stage 3 unspecified",                                                       138, "Chronic Kidney Disease, Stage 1-3",  "RenalDisease"),
    ("N18.31",  "Chronic kidney disease, stage 3a",                                                                  138, "Chronic Kidney Disease, Stage 1-3",  "RenalDisease"),
    ("N18.32",  "Chronic kidney disease, stage 3b",                                                                  138, "Chronic Kidney Disease, Stage 1-3",  "RenalDisease"),
    ("N18.4",   "Chronic kidney disease, stage 4 (severe)",                                                         137, "Chronic Kidney Disease, Stage 4",    "RenalDisease"),
    ("N18.5",   "Chronic kidney disease, stage 5",                                                                   136, "Chronic Kidney Disease, Stage 5",    "RenalDisease"),
    ("N18.6",   "End stage renal disease",                                                                           136, "Chronic Kidney Disease, Stage 5",    "RenalDisease"),
    ("N18.9",   "Chronic kidney disease, unspecified",                                                               138, "Chronic Kidney Disease, Stage 1-3",  "RenalDisease"),

    # -----------------------------------------------------------------------
    # Depression (HCC 155) – additional
    # -----------------------------------------------------------------------
    ("F41.1",   "Generalized anxiety disorder",                                                                     155, "Depression",                        "MentalHealth"),

    # -----------------------------------------------------------------------
    # Pressure ulcers (HCC 157, 158, 159, 161)
    # -----------------------------------------------------------------------
    ("L89.000", "Pressure ulcer of unspecified elbow, unstageable",                                                 161, "Pressure Ulcer of Unspecified Stage", "PressureUlcer"),
    ("L89.003", "Pressure ulcer of unspecified elbow, stage 3",                                                     159, "Pressure Ulcer of Stage 3",          "PressureUlcer"),
    ("L89.004", "Pressure ulcer of unspecified elbow, stage 4",                                                     158, "Pressure Ulcer of Stage 4",          "PressureUlcer"),
    ("L89.100", "Pressure ulcer of unspecified part of back, unstageable",                                          161, "Pressure Ulcer of Unspecified Stage", "PressureUlcer"),
    ("L89.103", "Pressure ulcer of unspecified part of back, stage 3",                                              159, "Pressure Ulcer of Stage 3",          "PressureUlcer"),
    ("L89.104", "Pressure ulcer of unspecified part of back, stage 4",                                              158, "Pressure Ulcer of Stage 4",          "PressureUlcer"),
    ("L89.200", "Pressure ulcer of unspecified hip, unstageable",                                                   161, "Pressure Ulcer of Unspecified Stage", "PressureUlcer"),
    ("L89.203", "Pressure ulcer of unspecified hip, stage 3",                                                       159, "Pressure Ulcer of Stage 3",          "PressureUlcer"),
    ("L89.204", "Pressure ulcer of unspecified hip, stage 4",                                                       158, "Pressure Ulcer of Stage 4",          "PressureUlcer"),
    ("L89.300", "Pressure ulcer of unspecified buttock, unstageable",                                               161, "Pressure Ulcer of Unspecified Stage", "PressureUlcer"),
    ("L89.303", "Pressure ulcer of unspecified buttock, stage 3",                                                   159, "Pressure Ulcer of Stage 3",          "PressureUlcer"),
    ("L89.304", "Pressure ulcer of unspecified buttock, stage 4",                                                   158, "Pressure Ulcer of Stage 4",          "PressureUlcer"),
    ("L89.500", "Pressure ulcer of unspecified ankle, unstageable",                                                 161, "Pressure Ulcer of Unspecified Stage", "PressureUlcer"),
    ("L89.503", "Pressure ulcer of unspecified ankle, stage 3",                                                     159, "Pressure Ulcer of Stage 3",          "PressureUlcer"),
    ("L89.504", "Pressure ulcer of unspecified ankle, stage 4",                                                     158, "Pressure Ulcer of Stage 4",          "PressureUlcer"),
    ("L89.620", "Pressure ulcer of left heel, stage 2",                                                             157, "Pressure Ulcer of Stage 1 or 2",    "PressureUlcer"),
    ("L89.621", "Pressure ulcer of left heel, stage 1",                                                             157, "Pressure Ulcer of Stage 1 or 2",    "PressureUlcer"),
    ("L89.610", "Pressure ulcer of right heel, stage 2",                                                            157, "Pressure Ulcer of Stage 1 or 2",    "PressureUlcer"),

    # -----------------------------------------------------------------------
    # Transplant status (HCC 186)
    # -----------------------------------------------------------------------
    ("Z94.0",   "Kidney transplant status",                                                                         186, "Major Organ Transplant or Replacement Status", "Transplant"),
    ("Z94.1",   "Heart transplant status",                                                                           186, "Major Organ Transplant or Replacement Status", "Transplant"),
    ("Z94.2",   "Lung transplant status",                                                                            186, "Major Organ Transplant or Replacement Status", "Transplant"),
    ("Z94.4",   "Liver transplant status",                                                                           186, "Major Organ Transplant or Replacement Status", "Transplant"),
    ("Z94.5",   "Skin transplant status",                                                                            186, "Major Organ Transplant or Replacement Status", "Transplant"),
    ("Z94.81",  "Bone marrow transplant status",                                                                     186, "Major Organ Transplant or Replacement Status", "Transplant"),
    ("Z94.83",  "Pancreas transplant status",                                                                        186, "Major Organ Transplant or Replacement Status", "Transplant"),
    ("Z94.84",  "Stem cells transplant status",                                                                      186, "Major Organ Transplant or Replacement Status", "Transplant"),

    # -----------------------------------------------------------------------
    # Amputation status (HCC 189)
    # -----------------------------------------------------------------------
    ("Z89.411", "Acquired absence of right great toe",                                                              189, "Amputation Status, Lower Limb/Amputation Complications", "Amputation"),
    ("Z89.419", "Acquired absence of unspecified great toe",                                                        189, "Amputation Status, Lower Limb/Amputation Complications", "Amputation"),
    ("Z89.421", "Acquired absence of other right toe(s)",                                                           189, "Amputation Status, Lower Limb/Amputation Complications", "Amputation"),
    ("Z89.511", "Acquired absence of right leg below knee",                                                          189, "Amputation Status, Lower Limb/Amputation Complications", "Amputation"),
    ("Z89.512", "Acquired absence of left leg below knee",                                                           189, "Amputation Status, Lower Limb/Amputation Complications", "Amputation"),
    ("Z89.521", "Acquired absence of right knee",                                                                    189, "Amputation Status, Lower Limb/Amputation Complications", "Amputation"),
    ("Z89.611", "Acquired absence of right leg above knee",                                                          189, "Amputation Status, Lower Limb/Amputation Complications", "Amputation"),
    ("Z89.612", "Acquired absence of left leg above knee",                                                           189, "Amputation Status, Lower Limb/Amputation Complications", "Amputation"),
    ("Z89.631", "Acquired absence of right hip joint",                                                               189, "Amputation Status, Lower Limb/Amputation Complications", "Amputation"),
    ("Z89.9",   "Acquired absence of unspecified limb",                                                              189, "Amputation Status, Lower Limb/Amputation Complications", "Amputation"),
]

INSERT_SQL = """
INSERT INTO raf_intelligence.hcc_icd10_crosswalk
    (icd10_code, icd10_description, hcc_code, hcc_label, condition_group, effective_year)
VALUES (%s, %s, %s, %s, %s, %s)
ON DUPLICATE KEY UPDATE
    icd10_description = VALUES(icd10_description),
    hcc_label         = VALUES(hcc_label),
    condition_group   = VALUES(condition_group);
"""


def get_connection(database: Optional[str] = None) -> mysql.connector.MySQLConnection:
    cfg = {**DB_CONFIG}
    if database:
        cfg["database"] = database
    return mysql.connector.connect(**cfg)


def bootstrap_schema(conn: mysql.connector.MySQLConnection) -> None:
    cursor = conn.cursor()
    try:
        log.info("Ensuring raf_intelligence database exists …")
        cursor.execute(CREATE_DB)
        log.info("Ensuring hcc_icd10_crosswalk table exists …")
        cursor.execute(CREATE_TABLE)
        # Add condition_group column if it was not in the original schema
        cursor.execute(
            "SELECT COUNT(*) FROM information_schema.COLUMNS "
            "WHERE TABLE_SCHEMA='raf_intelligence' "
            "AND TABLE_NAME='hcc_icd10_crosswalk' "
            "AND COLUMN_NAME='condition_group';"
        )
        (has_col,) = cursor.fetchone()
        if not has_col:
            log.info("Adding condition_group column to hcc_icd10_crosswalk …")
            cursor.execute(ADD_CONDITION_GROUP_COL)
        conn.commit()
    finally:
        cursor.close()


def insert_mappings(conn: mysql.connector.MySQLConnection) -> int:
    cursor = conn.cursor()
    rows = [(code, desc, hcc, label, grp, 2024) for code, desc, hcc, label, grp in RAW_MAPPINGS]
    try:
        cursor.executemany(INSERT_SQL, rows)
        conn.commit()
        affected = cursor.rowcount
    finally:
        cursor.close()
    return affected


def main() -> None:
    log.info("Connecting to MySQL at 127.0.0.1:3309 …")
    try:
        conn = get_connection()
    except MySQLError as exc:
        log.error("Cannot connect: %s", exc)
        sys.exit(1)

    try:
        bootstrap_schema(conn)
        total = len(RAW_MAPPINGS)
        log.info("Inserting %d ICD-10 → HCC V28 mappings …", total)
        affected = insert_mappings(conn)
        log.info("Done. Rows inserted/updated: %d", affected)

        # Summary by condition group
        cursor = conn.cursor()
        cursor.execute(
            "SELECT COALESCE(NULLIF(condition_group,''),'(uncategorised)'), COUNT(*) AS cnt "
            "FROM raf_intelligence.hcc_icd10_crosswalk "
            "GROUP BY condition_group ORDER BY cnt DESC;"
        )
        rows = cursor.fetchall()
        cursor.close()
        log.info("Crosswalk summary by condition group:")
        for grp, cnt in rows:
            log.info("  %-20s  %d codes", grp, cnt)

    finally:
        conn.close()

    log.info("import_icd10_hcc_crosswalk complete.")


if __name__ == "__main__":
    main()
