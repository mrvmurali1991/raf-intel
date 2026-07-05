#!/usr/bin/env python3
"""
seed_specificity_upgrades.py
==============================
Seeds the ``raf_specificity_upgrades`` table with ICD-10 specificity upgrade
rules for the RAF Intelligence Specificity Upgrade Engine.

Finds patients coded with unspecified/generic ICD-10 codes who have clinical
evidence supporting more specific codes that map to higher-value HCCs.  This
is pure revenue recovery -- the condition is already documented, just
under-coded.

Example:
    Patient coded E11.9 (Type 2 DM, unspecified)
    + CKD (N18.3) in their problem list
    = Should be coded E11.22 (Type 2 DM with diabetic CKD)
    -> Maps to HCC 18 instead of HCC 19
    -> Revenue difference: ~$1,500/year per patient

Covers:
    - Diabetes Specificity (E11.9 -> E11.xx) -- MASSIVE revenue
    - Heart Failure Specificity (I50.9 -> I50.xx)
    - CKD Specificity (N18.9 -> N18.x)
    - COPD Specificity (J44.9 -> J44.x)
    - Malnutrition Specificity (E46 -> E43/E44.x)
    - Depression Specificity (F32.9 -> F33.x)
    - Vascular Disease Specificity (I73.9 -> I70.xxx)
    - Liver Specificity (K76.0/K74.60 -> K70.xx)
    - Stroke Specificity (I63.9 -> sequelae)
    - Obesity Specificity (E66.9 -> E66.01)

Data sources:
    - CMS-HCC V24 / V28 crosswalk mappings
    - AHA Coding Clinic guidance
    - KDIGO / ACC / ADA clinical guidelines
    - Standard CMS risk-adjustment revenue models

Idempotent: uses INSERT ... ON DUPLICATE KEY UPDATE on the
(generic_icd10, specific_icd10, required_evidence) unique key.
Safe to run multiple times.

Usage:
    python scripts/seed_specificity_upgrades.py

    # With custom DB connection:
    RAF_DB_HOST=10.1.0.204 RAF_DB_PORT=3306 RAF_DB_USER=root \\
      RAF_DB_PASSWORD=secret python scripts/seed_specificity_upgrades.py
"""

from __future__ import annotations

import logging
import os
import sys
from decimal import Decimal

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
# Database connection -- mirrors settings in backend/app/config.py
# Override any value via environment variables for non-development envs.
# ---------------------------------------------------------------------------
DB_CONFIG = dict(
    host=os.environ.get("RAF_DB_HOST", "127.0.0.1"),
    port=int(os.environ.get("RAF_DB_PORT", "3309")),
    user=os.environ.get("RAF_DB_USER", "root"),
    password=os.environ.get("RAF_DB_PASSWORD", "root"),
    database="raf_intelligence",
    charset="utf8mb4",
    collation="utf8mb4_unicode_ci",
    autocommit=False,
    connect_timeout=10,
)

# ---------------------------------------------------------------------------
# Table DDL
# ---------------------------------------------------------------------------

CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS raf_specificity_upgrades (
    id                  INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    generic_icd10       VARCHAR(10)   NOT NULL,
    generic_hcc         SMALLINT UNSIGNED NULL,
    specific_icd10      VARCHAR(10)   NOT NULL,
    specific_hcc        SMALLINT UNSIGNED NULL,
    required_evidence   VARCHAR(255)  NOT NULL,
    evidence_type       ENUM('comorbidity','lab','medication','procedure') NOT NULL DEFAULT 'comorbidity',
    revenue_delta_est   DECIMAL(10,2) NOT NULL DEFAULT 0.00,
    confidence_base     DECIMAL(5,4)  NOT NULL DEFAULT 0.7500,
    description         VARCHAR(500)  NOT NULL DEFAULT '',
    is_active           TINYINT(1)    NOT NULL DEFAULT 1,
    created_at          DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at          DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uq_upgrade (generic_icd10, specific_icd10, required_evidence),
    INDEX idx_generic (generic_icd10),
    INDEX idx_specific_hcc (specific_hcc)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
"""

# ---------------------------------------------------------------------------
# Upgrade Rules Data
#
# Each tuple:
#   (generic_icd10, generic_hcc, specific_icd10, specific_hcc,
#    required_evidence, evidence_type, revenue_delta_est,
#    confidence_base, description)
#
# required_evidence is the ICD-10 prefix (for comorbidity), lab name pattern
# (for lab), or medication pattern (for medication) that must be present in
# the patient's record to support the upgrade.
#
# revenue_delta_est is the estimated annual per-patient revenue uplift from
# the specificity upgrade (based on CMS MA capitation rates).
# ---------------------------------------------------------------------------

UPGRADES: list[tuple] = [

    # =========================================================================
    # 1. DIABETES SPECIFICITY (E11.9 -> E11.xx)
    #    HCC 19 (uncomplicated) -> HCC 18 (complicated) = ~$1,500/yr
    # =========================================================================

    # DM + CKD -> DM with CKD
    ("E11.9", 19, "E11.22", 18, "N18", "comorbidity",
     Decimal("1500.00"), Decimal("0.8500"),
     "Type 2 DM unspecified + CKD present -> DM with diabetic chronic kidney disease"),

    # DM + hyperglycemia (A1C > 9)
    ("E11.9", 19, "E11.65", 18, "A1C>=9", "lab",
     Decimal("1500.00"), Decimal("0.8000"),
     "Type 2 DM unspecified + A1C >= 9.0% -> DM with hyperglycemia"),

    # DM + retinopathy
    ("E11.9", 19, "E11.319", 18, "H35", "comorbidity",
     Decimal("1500.00"), Decimal("0.8200"),
     "Type 2 DM unspecified + retinopathy (H35.x) -> DM with unspecified diabetic retinopathy"),

    ("E11.9", 19, "E11.319", 18, "E11.3", "comorbidity",
     Decimal("1500.00"), Decimal("0.8500"),
     "Type 2 DM unspecified + diabetic retinopathy code -> DM with diabetic retinopathy"),

    # DM + neuropathy
    ("E11.9", 19, "E11.40", 18, "G62", "comorbidity",
     Decimal("1500.00"), Decimal("0.8000"),
     "Type 2 DM unspecified + polyneuropathy (G62.x) -> DM with diabetic neuropathy"),

    ("E11.9", 19, "E11.40", 18, "E11.4", "comorbidity",
     Decimal("1500.00"), Decimal("0.8500"),
     "Type 2 DM unspecified + diabetic neuropathy code -> DM with neuropathy"),

    # DM + PVD
    ("E11.9", 19, "E11.51", 18, "I73.9", "comorbidity",
     Decimal("1500.00"), Decimal("0.7800"),
     "Type 2 DM unspecified + PVD (I73.9) -> DM with peripheral angiopathy"),

    ("E11.9", 19, "E11.51", 18, "I70", "comorbidity",
     Decimal("1500.00"), Decimal("0.8000"),
     "Type 2 DM unspecified + atherosclerosis (I70.x) -> DM with peripheral angiopathy"),

    # DM + gastroparesis
    ("E11.9", 19, "E11.43", 18, "K31.84", "comorbidity",
     Decimal("1500.00"), Decimal("0.8500"),
     "Type 2 DM unspecified + gastroparesis (K31.84) -> DM with diabetic autonomic neuropathy"),

    # DM + foot ulcer
    ("E11.9", 19, "E11.621", 18, "L97", "comorbidity",
     Decimal("1500.00"), Decimal("0.8500"),
     "Type 2 DM unspecified + foot ulcer (L97.x) -> DM with foot ulcer"),

    # DM + insulin use (documentation completeness)
    ("E11.9", 19, "E11.9", 19, "Z79.4", "comorbidity",
     Decimal("0.00"), Decimal("0.9000"),
     "Type 2 DM unspecified + insulin use -> add Z79.4 for documentation completeness"),

    # DM + microalbuminuria (lab evidence)
    ("E11.9", 19, "E11.21", 18, "microalbumin>=30", "lab",
     Decimal("1500.00"), Decimal("0.7800"),
     "Type 2 DM unspecified + microalbuminuria >= 30 mg/L -> DM with diabetic nephropathy"),

    # DM + proteinuria (lab evidence)
    ("E11.9", 19, "E11.21", 18, "proteinuria>=300", "lab",
     Decimal("1500.00"), Decimal("0.8200"),
     "Type 2 DM unspecified + proteinuria >= 300 mg/day -> DM with diabetic nephropathy"),

    # =========================================================================
    # 2. HEART FAILURE SPECIFICITY (I50.9 -> I50.xx)
    #    HCC 85 retained but proper specificity supports audit defensibility
    #    and prevents CMS RADV downcoding
    # =========================================================================

    # HF + EF < 40% -> systolic HF chronic
    ("I50.9", 85, "I50.22", 85, "EF<40", "lab",
     Decimal("800.00"), Decimal("0.8500"),
     "Unspecified HF + EF < 40% on echo -> chronic systolic (HFrEF) heart failure"),

    # HF + EF >= 50% -> diastolic HF chronic
    ("I50.9", 85, "I50.32", 85, "EF>=50", "lab",
     Decimal("800.00"), Decimal("0.8500"),
     "Unspecified HF + EF >= 50% on echo -> chronic diastolic (HFpEF) heart failure"),

    # HF + acute exacerbation evidence
    ("I50.9", 85, "I50.21", 85, "J81", "comorbidity",
     Decimal("800.00"), Decimal("0.7500"),
     "Unspecified HF + pulmonary edema (J81.x) -> acute systolic heart failure"),

    # HF + HTN -> hypertensive heart disease with HF
    ("I50.9", 85, "I11.0", 85, "I10", "comorbidity",
     Decimal("900.00"), Decimal("0.7800"),
     "Unspecified HF + essential hypertension -> hypertensive heart disease with HF"),

    ("I50.9", 85, "I11.0", 85, "I11", "comorbidity",
     Decimal("900.00"), Decimal("0.8000"),
     "Unspecified HF + hypertensive heart disease -> hypertensive heart disease with HF"),

    # HF + CKD + HTN -> hypertensive heart + CKD with HF
    ("I50.9", 85, "I13.0", 85, "N18", "comorbidity",
     Decimal("1200.00"), Decimal("0.7500"),
     "Unspecified HF + CKD + HTN -> hypertensive heart and CKD with HF (I13.0)"),

    # =========================================================================
    # 3. CKD SPECIFICITY (N18.9 -> N18.x staged)
    #    N18.9 -> HCC 138 (generic) but staged = more defensible + may upgrade
    # =========================================================================

    # CKD unspecified + eGFR 30-59 -> Stage 3
    ("N18.9", 138, "N18.3", 138, "eGFR_30_59", "lab",
     Decimal("500.00"), Decimal("0.8500"),
     "Unspecified CKD + eGFR 30-59 mL/min -> CKD Stage 3"),

    # CKD unspecified + eGFR 15-29 -> Stage 4
    ("N18.9", 138, "N18.4", 137, "eGFR_15_29", "lab",
     Decimal("2500.00"), Decimal("0.8800"),
     "Unspecified CKD + eGFR 15-29 mL/min -> CKD Stage 4 (HCC 137)"),

    # CKD unspecified + eGFR < 15 -> Stage 5
    ("N18.9", 138, "N18.5", 136, "eGFR<15", "lab",
     Decimal("4000.00"), Decimal("0.9000"),
     "Unspecified CKD + eGFR < 15 mL/min -> CKD Stage 5 (HCC 136)"),

    # CKD + DM -> diabetic CKD
    ("N18.9", 138, "E11.22", 18, "E11", "comorbidity",
     Decimal("1500.00"), Decimal("0.7800"),
     "Unspecified CKD + Type 2 DM -> code as DM with diabetic CKD (E11.22) HCC 18"),

    # CKD + HTN -> hypertensive CKD
    ("N18.9", 138, "I12.9", 138, "I10", "comorbidity",
     Decimal("400.00"), Decimal("0.8000"),
     "Unspecified CKD + essential hypertension -> hypertensive CKD (I12.9)"),

    ("N18.9", 138, "I12.9", 138, "I11", "comorbidity",
     Decimal("400.00"), Decimal("0.8200"),
     "Unspecified CKD + hypertensive heart disease -> hypertensive CKD (I12.9)"),

    # =========================================================================
    # 4. COPD SPECIFICITY (J44.9 -> J44.1)
    #    J44.9 (unspecified) vs J44.1 (with acute exacerbation) = HCC 111
    # =========================================================================

    # COPD + acute exacerbation
    ("J44.9", 111, "J44.1", 111, "J96", "comorbidity",
     Decimal("600.00"), Decimal("0.7500"),
     "Unspecified COPD + respiratory failure (J96.x) -> COPD with acute exacerbation"),

    ("J44.9", 111, "J44.1", 111, "R06.0", "comorbidity",
     Decimal("600.00"), Decimal("0.7000"),
     "Unspecified COPD + dyspnea (R06.0x) -> COPD with acute exacerbation"),

    ("J44.9", 111, "J44.1", 111, "J44.0", "comorbidity",
     Decimal("600.00"), Decimal("0.8500"),
     "Unspecified COPD + lower resp infection -> COPD with acute exacerbation and infection"),

    # COPD + home oxygen (medication evidence)
    ("J44.9", 111, "J44.1", 111, "oxygen%", "medication",
     Decimal("600.00"), Decimal("0.7800"),
     "Unspecified COPD + on home oxygen therapy -> COPD with acute exacerbation"),

    ("J44.9", 111, "J44.1", 111, "Z99.81", "comorbidity",
     Decimal("600.00"), Decimal("0.8000"),
     "Unspecified COPD + dependence on supplemental oxygen (Z99.81) -> COPD with exacerbation"),

    # =========================================================================
    # 5. MALNUTRITION SPECIFICITY (E46 -> E43/E44.x)
    #    E46 (unspecified) -> E43 (severe) or E44.0 (moderate) = HCC 21
    # =========================================================================

    # Malnutrition + albumin < 3.0 -> severe
    ("E46", 21, "E43", 21, "albumin<3.0", "lab",
     Decimal("3000.00"), Decimal("0.8500"),
     "Unspecified malnutrition + albumin < 3.0 g/dL -> severe protein-calorie malnutrition"),

    # Malnutrition + albumin 3.0-3.4 -> moderate
    ("E46", 21, "E44.0", 21, "albumin_3.0_3.4", "lab",
     Decimal("2500.00"), Decimal("0.8000"),
     "Unspecified malnutrition + albumin 3.0-3.4 g/dL -> moderate protein-calorie malnutrition"),

    # Malnutrition + BMI < 18.5 -> mild
    ("E46", 21, "E44.1", 21, "BMI<18.5", "lab",
     Decimal("2000.00"), Decimal("0.7800"),
     "Unspecified malnutrition + BMI < 18.5 -> mild protein-calorie malnutrition"),

    # Malnutrition + prealbumin < 15 -> severe
    ("E46", 21, "E43", 21, "prealbumin<15", "lab",
     Decimal("3000.00"), Decimal("0.8200"),
     "Unspecified malnutrition + prealbumin < 15 mg/dL -> severe malnutrition"),

    # =========================================================================
    # 6. DEPRESSION SPECIFICITY (F32.9 -> F33.x)
    #    F32.9 (single episode unspecified) -> F33.x (recurrent) = HCC 155
    # =========================================================================

    # Depression + recurrent episodes evidence
    ("F32.9", 155, "F33.0", 155, "F32", "comorbidity",
     Decimal("400.00"), Decimal("0.7500"),
     "Unspecified depression + prior depressive episode documented -> recurrent MDD, mild"),

    ("F32.9", 155, "F33.1", 155, "F33", "comorbidity",
     Decimal("400.00"), Decimal("0.8500"),
     "Unspecified depression + prior recurrent MDD code -> recurrent MDD, moderate"),

    # Depression + severe symptoms / suicidal ideation
    ("F32.9", 155, "F33.2", 155, "R45.851", "comorbidity",
     Decimal("500.00"), Decimal("0.8000"),
     "Unspecified depression + suicidal ideation (R45.851) -> recurrent MDD, severe"),

    ("F32.9", 155, "F33.2", 155, "T14.91", "comorbidity",
     Decimal("500.00"), Decimal("0.7800"),
     "Unspecified depression + suicide attempt history -> recurrent MDD, severe"),

    # Depression + antidepressant medication (supports recurrent diagnosis)
    ("F32.9", 155, "F33.0", 155, "antidepressant%", "medication",
     Decimal("400.00"), Decimal("0.6500"),
     "Unspecified depression + on chronic antidepressant -> likely recurrent MDD"),

    # =========================================================================
    # 7. VASCULAR DISEASE SPECIFICITY (I73.9 -> I70.xxx)
    #    I73.9 (unspecified PVD) HCC 108 -> I70.2xx HCC 107/108
    # =========================================================================

    # PVD + claudication
    ("I73.9", 108, "I70.211", 108, "M79.6", "comorbidity",
     Decimal("600.00"), Decimal("0.7800"),
     "Unspecified PVD + limb pain/claudication -> atherosclerosis with intermittent claudication"),

    ("I73.9", 108, "I70.211", 108, "R26", "comorbidity",
     Decimal("600.00"), Decimal("0.7000"),
     "Unspecified PVD + gait abnormality -> atherosclerosis with claudication"),

    # PVD + rest pain (higher severity = HCC 107)
    ("I73.9", 108, "I70.221", 107, "G89", "comorbidity",
     Decimal("1200.00"), Decimal("0.7500"),
     "Unspecified PVD + rest pain (G89.x) -> atherosclerosis with rest pain (HCC 107)"),

    ("I73.9", 108, "I70.221", 107, "R52", "comorbidity",
     Decimal("1200.00"), Decimal("0.7000"),
     "Unspecified PVD + chronic pain at rest -> atherosclerosis with rest pain"),

    # PVD + ulceration (highest severity = HCC 107)
    ("I73.9", 108, "I70.231", 107, "L97", "comorbidity",
     Decimal("1500.00"), Decimal("0.8500"),
     "Unspecified PVD + non-pressure ulcer of lower limb -> atherosclerosis with ulceration"),

    ("I73.9", 108, "I70.231", 107, "L98.49", "comorbidity",
     Decimal("1500.00"), Decimal("0.8000"),
     "Unspecified PVD + chronic skin ulcer -> atherosclerosis with ulceration"),

    # PVD + gangrene (highest acuity)
    ("I73.9", 108, "I70.261", 107, "I96", "comorbidity",
     Decimal("2000.00"), Decimal("0.8800"),
     "Unspecified PVD + gangrene (I96) -> atherosclerosis with gangrene"),

    # =========================================================================
    # 8. LIVER SPECIFICITY (K76.0/K74.60 -> K70.xx)
    # =========================================================================

    # Fatty liver + alcohol use -> alcoholic fatty liver
    ("K76.0", None, "K70.0", 29, "F10", "comorbidity",
     Decimal("1200.00"), Decimal("0.8000"),
     "Fatty liver (K76.0) + alcohol use disorder (F10.x) -> alcoholic fatty liver (HCC 29)"),

    ("K76.0", None, "K70.0", 29, "Z72.1", "comorbidity",
     Decimal("1200.00"), Decimal("0.7000"),
     "Fatty liver + alcohol use history (Z72.1) -> alcoholic fatty liver disease"),

    # Unspecified cirrhosis + alcohol -> alcoholic cirrhosis
    ("K74.60", 28, "K70.30", 28, "F10", "comorbidity",
     Decimal("800.00"), Decimal("0.8500"),
     "Unspecified cirrhosis + alcohol use disorder -> alcoholic cirrhosis (K70.30)"),

    ("K74.60", 28, "K70.30", 28, "Z87.891", "comorbidity",
     Decimal("800.00"), Decimal("0.7500"),
     "Unspecified cirrhosis + personal history of alcohol dependence -> alcoholic cirrhosis"),

    # Cirrhosis + portal hypertension -> decompensated
    ("K74.60", 28, "K74.60", 27, "K76.6", "comorbidity",
     Decimal("2000.00"), Decimal("0.8500"),
     "Unspecified cirrhosis + portal hypertension (K76.6) -> cirrhosis with portal HTN (HCC 27)"),

    # Cirrhosis + ascites -> decompensated
    ("K74.60", 28, "K74.60", 27, "R18", "comorbidity",
     Decimal("2000.00"), Decimal("0.8200"),
     "Unspecified cirrhosis + ascites (R18.x) -> decompensated cirrhosis (HCC 27)"),

    # Cirrhosis + hepatic encephalopathy
    ("K74.60", 28, "K74.60", 27, "G93.4", "comorbidity",
     Decimal("2000.00"), Decimal("0.8000"),
     "Unspecified cirrhosis + encephalopathy -> decompensated cirrhosis (HCC 27)"),

    # Cirrhosis + esophageal varices
    ("K74.60", 28, "K74.60", 27, "I85", "comorbidity",
     Decimal("2000.00"), Decimal("0.8500"),
     "Unspecified cirrhosis + esophageal varices (I85.x) -> decompensated cirrhosis (HCC 27)"),

    # =========================================================================
    # 9. STROKE SPECIFICITY (I63.9 + sequelae)
    # =========================================================================

    # Stroke + right hemiplegia
    ("I63.9", 100, "I63.9", 100, "G81.91", "comorbidity",
     Decimal("1000.00"), Decimal("0.8500"),
     "Unspecified stroke + right hemiplegia -> code both stroke + hemiplegia HCC 100+103"),

    # Stroke + left hemiplegia
    ("I63.9", 100, "I63.9", 100, "G81.92", "comorbidity",
     Decimal("1000.00"), Decimal("0.8500"),
     "Unspecified stroke + left hemiplegia -> code both stroke + hemiplegia HCC 100+103"),

    # Stroke + aphasia
    ("I63.9", 100, "I63.9", 100, "R47.01", "comorbidity",
     Decimal("800.00"), Decimal("0.8000"),
     "Unspecified stroke + aphasia (R47.01) -> code both for accurate HCC capture"),

    # Stroke + dysphagia
    ("I63.9", 100, "I63.9", 100, "R13.10", "comorbidity",
     Decimal("600.00"), Decimal("0.7500"),
     "Unspecified stroke + dysphagia (R13.10) -> code both for complete documentation"),

    # Stroke + cognitive deficits
    ("I63.9", 100, "I63.9", 100, "R41.840", "comorbidity",
     Decimal("600.00"), Decimal("0.7000"),
     "Unspecified stroke + attention deficit (R41.840) -> code post-stroke cognitive deficit"),

    # Stroke + monoplegia of upper limb
    ("I63.9", 100, "I63.9", 100, "G83.2", "comorbidity",
     Decimal("800.00"), Decimal("0.8000"),
     "Unspecified stroke + monoplegia upper limb -> code for HCC 104 capture"),

    # =========================================================================
    # 10. OBESITY SPECIFICITY (E66.9 -> E66.01)
    #     E66.9 (unspecified) does NOT map to HCC; E66.01 (morbid) = HCC 22
    # =========================================================================

    # Obesity unspecified + BMI >= 40 -> morbid obesity
    ("E66.9", None, "E66.01", 22, "BMI>=40", "lab",
     Decimal("1800.00"), Decimal("0.9000"),
     "Unspecified obesity + BMI >= 40 -> morbid (severe) obesity HCC 22"),

    # Obesity unspecified + BMI 35-39.9 + comorbidity -> morbid obesity
    ("E66.9", None, "E66.01", 22, "BMI_35_39.9", "lab",
     Decimal("1800.00"), Decimal("0.7500"),
     "Unspecified obesity + BMI 35-39.9 + obesity-related comorbidity -> morbid obesity HCC 22"),

    # Obesity unspecified + BMI >= 40 (alternate BMI source)
    ("E66.9", None, "E66.01", 22, "Z68.4", "comorbidity",
     Decimal("1800.00"), Decimal("0.9200"),
     "Unspecified obesity + BMI 40+ ICD code (Z68.4x) -> morbid obesity HCC 22"),

    # =========================================================================
    # 11. ADDITIONAL HIGH-VALUE SPECIFICITY UPGRADES
    # =========================================================================

    # --- Atrial Fibrillation specificity ---
    # I48.91 (unspecified AFib) -> I48.2 (chronic/permanent)
    ("I48.91", 96, "I48.2", 96, "Z79.01", "comorbidity",
     Decimal("300.00"), Decimal("0.7500"),
     "Unspecified AFib + long-term anticoagulant use -> chronic/permanent AFib"),

    # --- Dementia specificity ---
    # F03.90 (unspecified dementia) -> specific type
    ("F03.90", 52, "F03.91", 52, "F03", "comorbidity",
     Decimal("600.00"), Decimal("0.7000"),
     "Unspecified dementia + behavioral disturbance documented -> dementia with behavioral disturbance"),

    ("F03.90", 52, "G30.9", 51, "G30", "comorbidity",
     Decimal("1200.00"), Decimal("0.8000"),
     "Unspecified dementia + Alzheimer evidence -> Alzheimer disease unspecified (HCC 51)"),

    # --- Seizure specificity ---
    # G40.909 (unspecified epilepsy) -> intractable
    ("G40.909", 79, "G40.919", 79, "G40.91", "comorbidity",
     Decimal("500.00"), Decimal("0.8000"),
     "Unspecified epilepsy + intractable seizure evidence -> intractable epilepsy"),

    ("G40.909", 79, "G40.919", 79, "anticonvulsant%", "medication",
     Decimal("500.00"), Decimal("0.7000"),
     "Unspecified epilepsy + multiple anticonvulsants -> likely intractable epilepsy"),

    # --- Asthma specificity ---
    # J45.909 (unspecified asthma) -> persistent
    ("J45.909", None, "J45.40", 111, "J45.4", "comorbidity",
     Decimal("800.00"), Decimal("0.7500"),
     "Unspecified asthma + moderate persistent evidence -> moderate persistent asthma (HCC 111)"),

    ("J45.909", None, "J45.50", 111, "J45.5", "comorbidity",
     Decimal("1000.00"), Decimal("0.8000"),
     "Unspecified asthma + severe persistent evidence -> severe persistent asthma (HCC 111)"),

    # --- Bipolar specificity ---
    # F31.9 (unspecified bipolar) -> specific episode type
    ("F31.9", 59, "F31.10", 59, "F31.1", "comorbidity",
     Decimal("400.00"), Decimal("0.7500"),
     "Unspecified bipolar + manic episode evidence -> bipolar, current episode manic"),

    ("F31.9", 59, "F31.30", 59, "F31.3", "comorbidity",
     Decimal("400.00"), Decimal("0.7500"),
     "Unspecified bipolar + depressed episode evidence -> bipolar, current episode depressed"),

    # --- Rheumatoid arthritis specificity ---
    # M06.9 (unspecified RA) -> seropositive RA
    ("M06.9", 40, "M05.79", 40, "rheumatoid_factor%", "lab",
     Decimal("600.00"), Decimal("0.8000"),
     "Unspecified RA + positive rheumatoid factor -> seropositive RA (M05.79)"),

    ("M06.9", 40, "M05.79", 40, "anti_ccp%", "lab",
     Decimal("600.00"), Decimal("0.8500"),
     "Unspecified RA + positive anti-CCP antibodies -> seropositive RA (M05.79)"),

    # --- Heart failure further specificity ---
    # I50.20 (unspecified systolic HF) -> I50.22 (chronic systolic)
    ("I50.20", 85, "I50.22", 85, "chronic_hf%", "medication",
     Decimal("400.00"), Decimal("0.8000"),
     "Unspecified systolic HF + on chronic HF medications -> chronic systolic HF (I50.22)"),

    # I50.30 (unspecified diastolic HF) -> I50.32 (chronic diastolic)
    ("I50.30", 85, "I50.32", 85, "chronic_hf%", "medication",
     Decimal("400.00"), Decimal("0.8000"),
     "Unspecified diastolic HF + on chronic HF medications -> chronic diastolic HF (I50.32)"),

    # --- DM Type 1 specificity (parallel to Type 2) ---
    # E10.9 (Type 1 DM unspecified) + CKD
    ("E10.9", 17, "E10.22", 17, "N18", "comorbidity",
     Decimal("1500.00"), Decimal("0.8500"),
     "Type 1 DM unspecified + CKD present -> Type 1 DM with diabetic CKD"),

    # E10.9 + retinopathy
    ("E10.9", 17, "E10.319", 17, "H35", "comorbidity",
     Decimal("1500.00"), Decimal("0.8200"),
     "Type 1 DM unspecified + retinopathy -> Type 1 DM with retinopathy"),

    # E10.9 + neuropathy
    ("E10.9", 17, "E10.40", 17, "G62", "comorbidity",
     Decimal("1500.00"), Decimal("0.8000"),
     "Type 1 DM unspecified + neuropathy -> Type 1 DM with neuropathy"),

    # --- BMI codes for obesity documentation ---
    ("E66.9", None, "E66.01", 22, "BMI>=40.0", "lab",
     Decimal("1800.00"), Decimal("0.9000"),
     "Unspecified obesity + measured BMI >= 40 -> morbid obesity (E66.01) HCC 22"),

    # --- Protein-energy malnutrition in CKD context ---
    ("E46", 21, "E43", 21, "N18.5", "comorbidity",
     Decimal("3000.00"), Decimal("0.7500"),
     "Unspecified malnutrition + CKD Stage 5 -> likely severe malnutrition"),

    ("E46", 21, "E43", 21, "weight_loss>=10%", "lab",
     Decimal("3000.00"), Decimal("0.8000"),
     "Unspecified malnutrition + weight loss >= 10% in 6 months -> severe malnutrition"),
]


# ---------------------------------------------------------------------------
# Upsert SQL
# ---------------------------------------------------------------------------

UPSERT_SQL = """
INSERT INTO raf_specificity_upgrades (
    generic_icd10, generic_hcc, specific_icd10, specific_hcc,
    required_evidence, evidence_type, revenue_delta_est,
    confidence_base, description, is_active
) VALUES (
    %s, %s, %s, %s, %s, %s, %s, %s, %s, 1
)
ON DUPLICATE KEY UPDATE
    generic_hcc       = VALUES(generic_hcc),
    specific_hcc      = VALUES(specific_hcc),
    evidence_type     = VALUES(evidence_type),
    revenue_delta_est = VALUES(revenue_delta_est),
    confidence_base   = VALUES(confidence_base),
    description       = VALUES(description),
    is_active         = 1
"""


def main() -> int:
    log.info("Connecting to MySQL at %s:%s ...", DB_CONFIG["host"], DB_CONFIG["port"])

    try:
        conn = mysql.connector.connect(**DB_CONFIG)
        cursor = conn.cursor()
    except MySQLError as e:
        log.error("Database connection failed: %s", e)
        return 1

    # Create the table if it does not exist
    log.info("Ensuring raf_specificity_upgrades table exists ...")
    try:
        cursor.execute(CREATE_TABLE_SQL)
        conn.commit()
        log.info("Table raf_specificity_upgrades ready.")
    except MySQLError as e:
        if e.errno != 1050:  # "Table already exists"
            log.error("Failed to create table: %s", e)
            return 1
        log.info("Table already exists.")

    # Seed the upgrade rules
    inserted = 0
    skipped = 0
    errors = 0
    for row in UPGRADES:
        (generic_icd10, generic_hcc, specific_icd10, specific_hcc,
         required_evidence, evidence_type, revenue_delta_est,
         confidence_base, description) = row
        try:
            cursor.execute(
                UPSERT_SQL,
                (generic_icd10, generic_hcc, specific_icd10, specific_hcc,
                 required_evidence, evidence_type, revenue_delta_est,
                 confidence_base, description),
            )
            if cursor.rowcount > 0:
                inserted += 1
            else:
                skipped += 1
        except MySQLError as e:
            log.error(
                "Failed to insert upgrade rule '%s -> %s' (evidence: %s): %s",
                generic_icd10, specific_icd10, required_evidence, e,
            )
            errors += 1

    conn.commit()
    cursor.close()
    conn.close()

    log.info(
        "Seeding complete: %d rules processed (%d inserted/updated, %d unchanged, %d errors)",
        len(UPGRADES), inserted, skipped, errors,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
