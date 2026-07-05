#!/usr/bin/env python3
"""
seed_comorbidity_patterns.py
=============================
Seeds clinically validated comorbidity patterns into ``raf_comorbidity_patterns``.

When a patient has Condition A + Condition B, they very likely also have
Condition C (which may be uncoded).  This is the 5th suspect-scanning strategy
in the RAF Intelligence suspect engine.

Covers:
    - Diabetes Complications (highest revenue)
    - Cardiovascular Cascades
    - Respiratory
    - Obesity Cascade
    - Renal Cascade
    - Mental Health
    - Autoimmune
    - Cancer
    - Neurological
    - Liver Disease

Data sources:
    - CMS V28 ICD-10 -> HCC crosswalk
    - AHA Coding Clinic 2024
    - KDIGO 2024 CKD Guideline
    - ACC/AHA/HFSA 2022 Heart Failure Guideline

Idempotent: uses INSERT ... ON DUPLICATE KEY UPDATE on the
(condition_a_icd, condition_b_icd, suspect_icd10) unique key.

Usage:
    python scripts/seed_comorbidity_patterns.py

    # With custom DB connection:
    RAF_DB_HOST=10.1.0.204 RAF_DB_PORT=3306 RAF_DB_USER=root \\
      RAF_DB_PASSWORD=secret python scripts/seed_comorbidity_patterns.py
"""

from __future__ import annotations

import logging
import os
import sys

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
# Pattern Data
#
# Each tuple:
#   (condition_a_icd, condition_a_hcc, condition_b_icd, condition_b_hcc,
#    suspect_icd10, suspect_hcc, confidence_base, pattern_name, notes)
#
# condition_b_icd may be None for single-condition upgrade patterns.
# ICD codes use dot notation for readability; the scan function normalises.
# ---------------------------------------------------------------------------

PATTERNS: list[tuple] = [

    # =========================================================================
    # 1. DIABETES COMPLICATIONS (highest revenue impact)
    # =========================================================================

    # DM + CKD -> DM with CKD
    ("E11.9", 19, "N18.9", 138, "E11.22", 18, 0.8500,
     "dm_ckd_to_dm_with_ckd",
     "DM + CKD co-occurrence strongly implies diabetic nephropathy (E11.22) HCC 18"),
    ("E11.9", 19, "N18.3", 138, "E11.22", 18, 0.8500,
     "dm_ckd3_to_dm_with_ckd",
     "DM + CKD Stage 3 implies diabetic nephropathy"),
    ("E11.9", 19, "N18.4", 137, "E11.22", 18, 0.8800,
     "dm_ckd4_to_dm_with_ckd",
     "DM + CKD Stage 4 implies diabetic nephropathy (higher confidence)"),

    # DM + Retinopathy/eye disease -> DM with retinopathy
    ("E11.9", 19, "H35.0", None, "E11.319", 18, 0.7500,
     "dm_retinopathy_to_dm_retinopathy",
     "DM + retinopathy implies DM with diabetic retinopathy E11.31x HCC 18"),
    ("E11.9", 19, "H35.3", None, "E11.319", 18, 0.7500,
     "dm_macular_degen_to_dm_retinopathy",
     "DM + macular degeneration implies DM with retinopathy"),
    ("E11.9", 19, "H36", None, "E11.319", 18, 0.7800,
     "dm_retinal_disorder_to_dm_retinopathy",
     "DM + retinal disorder in diabetic (H36) implies DM retinopathy"),

    # DM + Neuropathy -> DM with neuropathy
    ("E11.9", 19, "G62.9", None, "E11.40", 18, 0.7500,
     "dm_polyneuropathy_to_dm_neuropathy",
     "DM + polyneuropathy implies DM with neuropathy E11.40 HCC 18"),
    ("E11.9", 19, "G60.9", None, "E11.40", 18, 0.7000,
     "dm_hereditary_neuropathy_to_dm_neuropathy",
     "DM + hereditary neuropathy warrants DM neuropathy screen"),
    ("E11.9", 19, "G90.9", None, "E11.43", 18, 0.7200,
     "dm_autonomic_neuropathy_to_dm_autonomic",
     "DM + autonomic neuropathy implies DM with autonomic neuropathy E11.43"),

    # DM + PVD -> DM with PVD
    ("E11.9", 19, "I73.9", 108, "E11.51", 18, 0.8000,
     "dm_pvd_to_dm_with_pvd",
     "DM + PVD implies DM with peripheral angiopathy E11.51 HCC 18"),
    ("E11.9", 19, "I70.2", 108, "E11.51", 18, 0.8200,
     "dm_atherosclerosis_to_dm_with_pvd",
     "DM + atherosclerosis of extremities implies DM with PVD"),

    # DM + Gastroparesis -> DM with gastroparesis
    ("E11.9", 19, "K31.84", None, "E11.43", 18, 0.7000,
     "dm_gastroparesis_to_dm_gastroparesis",
     "DM + gastroparesis implies DM with autonomic neuropathy/gastroparesis"),

    # DM + Foot ulcer -> DM with foot complications
    ("E11.9", 19, "L97.5", None, "E11.621", 18, 0.7500,
     "dm_foot_ulcer_to_dm_foot_ulcer",
     "DM + non-pressure chronic ulcer of foot implies DM foot ulcer E11.621"),

    # =========================================================================
    # 2. CARDIOVASCULAR CASCADES
    # =========================================================================

    # HTN + CKD -> Hypertensive CKD
    ("I10", None, "N18.9", 138, "I12.9", 138, 0.8500,
     "htn_ckd_to_hypertensive_ckd",
     "HTN + CKD should be coded as Hypertensive CKD (I12.9) per AHA guidelines"),
    ("I10", None, "N18.3", 138, "I12.9", 138, 0.8500,
     "htn_ckd3_to_hypertensive_ckd",
     "HTN + CKD Stage 3 -> Hypertensive CKD"),
    ("I10", None, "N18.4", 137, "I12.9", 137, 0.8800,
     "htn_ckd4_to_hypertensive_ckd",
     "HTN + CKD Stage 4 -> Hypertensive CKD (higher severity)"),

    # HTN + CHF -> Hypertensive heart disease with HF
    ("I10", None, "I50.9", 85, "I11.0", 85, 0.8000,
     "htn_chf_to_hypertensive_hd_with_hf",
     "HTN + CHF should be coded as Hypertensive heart disease with HF (I11.0) HCC 85"),
    ("I10", None, "I50.2", 85, "I11.0", 85, 0.8200,
     "htn_systolic_hf_to_hypertensive_hd",
     "HTN + systolic HF -> Hypertensive heart disease with HF"),
    ("I10", None, "I50.3", 85, "I11.0", 85, 0.8200,
     "htn_diastolic_hf_to_hypertensive_hd",
     "HTN + diastolic HF -> Hypertensive heart disease with HF"),

    # HTN + CKD + CHF -> Hypertensive heart+CKD with HF
    ("I11.0", 85, "N18.9", 138, "I13.0", 85, 0.8500,
     "htn_hf_ckd_to_hypertensive_heart_ckd",
     "Hypertensive HF + CKD -> Hypertensive heart+CKD with HF (I13.0) HCC 85"),
    ("I12.9", 138, "I50.9", 85, "I13.0", 85, 0.8500,
     "hypertensive_ckd_hf_to_triple",
     "Hypertensive CKD + CHF -> Hypertensive heart+CKD with HF"),

    # CAD + DM -> screen for PVD
    ("I25.1", 88, "E11.9", 19, "I73.9", 108, 0.5500,
     "cad_dm_screen_pvd",
     "CAD + DM patients have high PVD prevalence; screen for I73.9 HCC 108"),

    # AFib + CVA history -> increased stroke recurrence risk
    ("I48.9", 96, "Z86.73", None, "I63.9", 100, 0.5000,
     "afib_cva_history_screen_stroke",
     "AFib + history of CVA -> screen for recurrent stroke I63.x HCC 100"),
    ("I48.0", 96, "Z86.73", None, "I63.9", 100, 0.5000,
     "afib_paroxysmal_cva_screen_stroke",
     "Paroxysmal AFib + CVA history -> screen for stroke"),
    ("I48.1", 96, "Z86.73", None, "I63.9", 100, 0.5200,
     "afib_persistent_cva_screen_stroke",
     "Persistent AFib + CVA history -> higher recurrence risk"),

    # CHF + AFib -> both coded, ensure HCC 85+96
    ("I50.9", 85, "I48.9", 96, "I48.91", 96, 0.6000,
     "chf_afib_ensure_afib_coded",
     "CHF + AFib: ensure AFib is coded to its highest specificity for HCC 96"),

    # =========================================================================
    # 3. RESPIRATORY
    # =========================================================================

    # COPD + CHF -> screen for respiratory failure
    ("J44.1", 111, "I50.9", 85, "J96.10", 84, 0.6000,
     "copd_chf_screen_resp_failure",
     "COPD + CHF -> screen for chronic respiratory failure J96.1x HCC 84"),
    ("J44.9", 111, "I50.9", 85, "J96.10", 84, 0.5800,
     "copd_unspec_chf_screen_resp_failure",
     "COPD unspecified + CHF -> screen for respiratory failure"),

    # COPD + Tobacco use -> screen for emphysema
    ("J44.9", 111, "F17.21", None, "J43.9", 111, 0.5500,
     "copd_tobacco_screen_emphysema",
     "COPD + tobacco dependence -> screen for emphysema J43.9 HCC 111"),
    ("J44.1", 111, "Z87.891", None, "J43.9", 111, 0.5000,
     "copd_tobacco_history_screen_emphysema",
     "COPD + personal history of tobacco -> screen for emphysema"),

    # Obesity + COPD -> screen for obesity hypoventilation
    ("E66.01", 22, "J44.9", 111, "E66.2", 22, 0.5500,
     "obesity_copd_screen_hypoventilation",
     "Morbid obesity + COPD -> screen for obesity hypoventilation E66.2 HCC 22"),

    # =========================================================================
    # 4. OBESITY CASCADE
    # =========================================================================

    # BMI >= 40 + Sleep apnea -> Morbid obesity
    ("E66.01", 22, "G47.33", None, "E66.01", 22, 0.8000,
     "morbid_obesity_sleep_apnea_confirm",
     "Morbid obesity + obstructive sleep apnea confirms HCC 22 severity"),
    ("E66.9", None, "G47.33", None, "E66.01", 22, 0.7000,
     "obesity_unspec_sleep_apnea_upgrade",
     "Unspecified obesity + sleep apnea -> likely morbid obesity E66.01 HCC 22"),

    # Obesity + DM -> screen for DM with complications
    ("E66.01", 22, "E11.9", 19, "E11.65", 18, 0.5500,
     "obesity_dm_screen_dm_complications",
     "Morbid obesity + DM -> screen for DM with complications E11.6x HCC 18"),

    # BMI >= 40 + DM + HTN -> Metabolic syndrome screening
    ("E66.01", 22, "E11.9", 19, "E11.69", 18, 0.6000,
     "metabolic_syndrome_dm_complications",
     "Morbid obesity + DM -> metabolic syndrome, screen all DM complications"),

    # =========================================================================
    # 5. RENAL CASCADE
    # =========================================================================

    # CKD + DM -> DM nephropathy
    ("N18.3", 138, "E11.9", 19, "E11.22", 18, 0.8000,
     "ckd3_dm_to_dm_nephropathy",
     "CKD Stage 3 + DM -> diabetic nephropathy E11.22 HCC 18"),
    ("N18.4", 137, "E11.9", 19, "E11.22", 18, 0.8500,
     "ckd4_dm_to_dm_nephropathy",
     "CKD Stage 4 + DM -> diabetic nephropathy (high confidence)"),
    ("N18.9", 138, "E11.9", 19, "E11.22", 18, 0.7500,
     "ckd_unspec_dm_to_dm_nephropathy",
     "CKD unspecified + DM -> screen for diabetic nephropathy"),

    # CKD Stage 4/5 + Anemia -> CKD-related anemia
    ("N18.4", 137, "D64.9", None, "D63.1", 48, 0.7500,
     "ckd4_anemia_to_ckd_anemia",
     "CKD Stage 4 + anemia -> CKD-related anemia D63.1 HCC 48"),
    ("N18.5", 137, "D64.9", None, "D63.1", 48, 0.8000,
     "ckd5_anemia_to_ckd_anemia",
     "CKD Stage 5 + anemia -> CKD-related anemia (high confidence)"),
    ("N18.4", 137, "D50.9", None, "D63.1", 48, 0.7000,
     "ckd4_iron_deficiency_to_ckd_anemia",
     "CKD Stage 4 + iron deficiency anemia -> screen for CKD anemia"),

    # CKD + Bone disease -> CKD-MBD
    ("N18.4", 137, "M81.0", None, "N25.0", 138, 0.6500,
     "ckd4_osteoporosis_to_ckd_mbd",
     "CKD Stage 4 + osteoporosis -> CKD mineral bone disease N25.0"),
    ("N18.3", 138, "M83.9", None, "N25.0", 138, 0.6000,
     "ckd3_osteomalacia_to_ckd_mbd",
     "CKD Stage 3 + osteomalacia -> CKD mineral bone disease"),

    # CKD + HTN -> Hypertensive CKD (mirrors cardio section but from renal perspective)
    ("N18.3", 138, "I10", None, "I12.9", 138, 0.8500,
     "ckd3_htn_to_hypertensive_ckd",
     "CKD Stage 3 + HTN -> Hypertensive CKD I12.9 HCC 138"),
    ("N18.4", 137, "I10", None, "I12.9", 137, 0.8800,
     "ckd4_htn_to_hypertensive_ckd",
     "CKD Stage 4 + HTN -> Hypertensive CKD (higher severity)"),

    # =========================================================================
    # 6. MENTAL HEALTH
    # =========================================================================

    # Depression + Anxiety -> screen for GAD
    ("F33.0", 155, "F41.9", None, "F41.1", 155, 0.5000,
     "depression_anxiety_screen_gad",
     "Major depression + unspecified anxiety -> screen for GAD F41.1"),
    ("F33.1", 155, "F41.9", None, "F41.1", 155, 0.5200,
     "moderate_depression_anxiety_screen_gad",
     "Moderate MDD + anxiety -> screen for GAD"),

    # Schizophrenia + DM -> metabolic syndrome complications
    ("F20.9", 57, "E11.9", 19, "E11.65", 18, 0.6000,
     "schizophrenia_dm_metabolic_complications",
     "Schizophrenia + DM -> screen for metabolic syndrome DM complications"),
    ("F20.0", 57, "E11.9", 19, "E11.65", 18, 0.6000,
     "paranoid_schizo_dm_complications",
     "Paranoid schizophrenia + DM -> screen for DM with complications"),

    # Bipolar + Substance use -> Dual diagnosis
    ("F31.9", 59, "F10.2", 55, "F10.20", 55, 0.5500,
     "bipolar_alcohol_dual_diagnosis",
     "Bipolar + alcohol use -> dual diagnosis, ensure specificity coded"),
    ("F31.9", 59, "F11.2", 55, "F11.20", 55, 0.5500,
     "bipolar_opioid_dual_diagnosis",
     "Bipolar + opioid use -> dual diagnosis F11.20"),
    ("F31.9", 59, "F14.2", 55, "F14.20", 55, 0.5500,
     "bipolar_cocaine_dual_diagnosis",
     "Bipolar + cocaine use -> dual diagnosis F14.20"),

    # =========================================================================
    # 7. AUTOIMMUNE
    # =========================================================================

    # RA + Lung disease -> RA with lung involvement
    ("M05.79", 40, "J84.1", None, "M05.10", 40, 0.6500,
     "ra_lung_disease_to_ra_lung",
     "RA + interstitial lung disease -> RA with lung involvement M05.1x HCC 40"),
    ("M05.79", 40, "J98.4", None, "M05.10", 40, 0.6000,
     "ra_lung_disorder_to_ra_lung",
     "RA + other lung disorder -> screen for RA lung involvement"),
    ("M06.9", None, "J84.1", None, "M05.10", 40, 0.5500,
     "ra_unspec_lung_to_ra_lung",
     "RA unspecified + ILD -> RA with lung involvement"),

    # SLE + CKD -> Lupus nephritis
    ("M32.9", 40, "N18.9", 138, "M32.14", 40, 0.7500,
     "sle_ckd_to_lupus_nephritis",
     "SLE + CKD -> lupus nephritis M32.14 HCC 40"),
    ("M32.9", 40, "N18.3", 138, "M32.14", 40, 0.7800,
     "sle_ckd3_to_lupus_nephritis",
     "SLE + CKD Stage 3 -> lupus nephritis (higher confidence)"),
    ("M32.9", 40, "N18.4", 137, "M32.14", 40, 0.8000,
     "sle_ckd4_to_lupus_nephritis",
     "SLE + CKD Stage 4 -> lupus nephritis (high confidence)"),

    # RA + Anemia -> RA-related anemia
    ("M05.79", 40, "D64.9", None, "D63.8", 48, 0.6000,
     "ra_anemia_to_ra_anemia",
     "RA + anemia -> RA-related anemia D63.8 HCC 48"),
    ("M05.79", 40, "D50.9", None, "D63.8", 48, 0.5500,
     "ra_iron_deficiency_to_ra_anemia",
     "RA + iron deficiency anemia -> screen for disease-related anemia"),

    # =========================================================================
    # 8. CANCER
    # =========================================================================

    # History of cancer + Weight loss -> screen for recurrence/metastasis
    ("Z85.3", None, "R63.4", None, "C80.1", 12, 0.4500,
     "cancer_history_weight_loss_screen_recurrence",
     "History of GI cancer + weight loss -> screen for recurrence HCC 12"),
    ("Z85.1", None, "R63.4", None, "C80.1", 12, 0.4500,
     "cancer_history_resp_weight_loss_recurrence",
     "History of respiratory cancer + weight loss -> screen for recurrence"),
    ("Z85.82", None, "R63.4", None, "C80.1", 12, 0.4000,
     "cancer_history_skin_weight_loss_recurrence",
     "History of skin cancer + weight loss -> screen for recurrence"),

    # Cancer + Anemia -> cancer-related anemia
    ("C50.9", 12, "D64.9", None, "D63.0", 48, 0.7000,
     "breast_cancer_anemia_to_cancer_anemia",
     "Breast cancer + anemia -> cancer-related anemia D63.0 HCC 48"),
    ("C34.9", 9, "D64.9", None, "D63.0", 48, 0.7200,
     "lung_cancer_anemia_to_cancer_anemia",
     "Lung cancer + anemia -> cancer-related anemia"),
    ("C18.9", 12, "D64.9", None, "D63.0", 48, 0.7000,
     "colon_cancer_anemia_to_cancer_anemia",
     "Colon cancer + anemia -> cancer-related anemia"),
    ("C61", 12, "D64.9", None, "D63.0", 48, 0.6500,
     "prostate_cancer_anemia_to_cancer_anemia",
     "Prostate cancer + anemia -> cancer-related anemia"),

    # =========================================================================
    # 9. NEUROLOGICAL
    # =========================================================================

    # Parkinson's + Dementia -> PD with dementia
    ("G20", 78, "F03.90", 52, "G31.83", 52, 0.7000,
     "parkinsons_dementia_to_pd_dementia",
     "Parkinson disease + dementia -> PD with dementia G31.83 HCC 52"),
    ("G20", 78, "G31.84", None, "G31.83", 52, 0.7500,
     "parkinsons_cognitive_to_pd_dementia",
     "Parkinson disease + mild cognitive impairment -> screen for PD dementia"),

    # Stroke + Hemiplegia
    ("I63.9", 100, "G81.9", 103, "G81.90", 103, 0.8000,
     "stroke_hemiplegia_confirm",
     "Stroke + hemiplegia -> confirm hemiplegia G81.9x HCC 103"),
    ("I69.3", None, "G81.9", 103, "G81.90", 103, 0.8500,
     "stroke_sequelae_hemiplegia",
     "Stroke sequelae + hemiplegia -> HCC 103"),

    # Stroke + Aphasia
    ("I63.9", 100, "R47.01", None, "R47.01", 103, 0.7000,
     "stroke_aphasia_sequelae",
     "Stroke + aphasia -> post-stroke aphasia HCC 103"),
    ("I69.3", None, "R47.01", None, "I69.320", 103, 0.7500,
     "stroke_sequelae_aphasia",
     "Stroke sequelae + aphasia -> I69.320 HCC 103"),

    # Stroke + Dysphagia
    ("I63.9", 100, "R13.10", None, "I69.391", 100, 0.6500,
     "stroke_dysphagia_sequelae",
     "Stroke + dysphagia -> post-stroke dysphagia sequelae"),
    ("I69.3", None, "R13.10", None, "I69.391", 100, 0.7000,
     "stroke_sequelae_dysphagia",
     "Stroke sequelae + dysphagia -> I69.391"),

    # =========================================================================
    # 10. LIVER DISEASE
    # =========================================================================

    # Alcohol use + Liver disease -> Alcoholic liver disease
    ("F10.20", 55, "K76.0", None, "K70.0", 28, 0.7500,
     "alcohol_dep_fatty_liver_to_alcoholic_liver",
     "Alcohol dependence + fatty liver -> alcoholic liver disease K70.x HCC 28"),
    ("F10.20", 55, "K74.6", 28, "K70.30", 28, 0.8000,
     "alcohol_dep_cirrhosis_to_alcoholic_cirrhosis",
     "Alcohol dependence + cirrhosis -> alcoholic cirrhosis K70.30 HCC 28"),
    ("F10.20", 55, "K76.9", None, "K70.9", 28, 0.7000,
     "alcohol_dep_liver_disease_to_alcoholic_liver",
     "Alcohol dependence + liver disease unspec -> alcoholic liver disease"),

    # Hepatitis C + Cirrhosis -> HCV cirrhosis
    ("B18.2", None, "K74.6", 28, "K74.60", 28, 0.8500,
     "hep_c_cirrhosis_to_hcv_cirrhosis",
     "Chronic Hepatitis C + cirrhosis -> HCV cirrhosis K74.60 HCC 28"),
    ("B18.2", None, "K76.6", None, "K74.60", 28, 0.7000,
     "hep_c_portal_htn_to_cirrhosis",
     "Chronic Hep C + portal hypertension -> screen for cirrhosis"),

    # Cirrhosis + Ascites
    ("K74.60", 28, "R18.8", None, "K70.31", 27, 0.8000,
     "cirrhosis_ascites_to_severe_liver",
     "Cirrhosis + ascites -> decompensated cirrhosis HCC 27"),
    ("K74.60", 28, "R18.0", None, "K70.31", 27, 0.8200,
     "cirrhosis_malignant_ascites_severe",
     "Cirrhosis + malignant ascites -> decompensated liver disease"),

    # =========================================================================
    # 11. ADDITIONAL HIGH-VALUE PATTERNS
    # =========================================================================

    # CHF + CKD compound
    ("I50.9", 85, "N18.4", 137, "I13.0", 85, 0.7500,
     "chf_ckd4_compound",
     "CHF + CKD Stage 4 -> review for Hypertensive heart+CKD compound coding"),

    # DM + CKD + HTN triple compound
    ("E11.22", 18, "I10", None, "I13.10", 85, 0.7000,
     "dm_ckd_htn_triple_compound",
     "DM with CKD + HTN -> Hypertensive CKD compound I13.10"),

    # Obesity + Sleep apnea + HTN
    ("E66.01", 22, "I10", None, "I13.10", 85, 0.4500,
     "obesity_htn_screen_compound",
     "Morbid obesity + HTN -> screen for compound cardiovascular coding"),

    # COPD + Obesity -> Obesity hypoventilation
    ("J44.9", 111, "E66.01", 22, "E66.2", 22, 0.5500,
     "copd_obesity_hypoventilation",
     "COPD + morbid obesity -> screen for obesity hypoventilation syndrome"),

    # Dementia + Depression
    ("F03.90", 52, "F33.1", 155, "F03.91", 52, 0.6000,
     "dementia_depression_behavioral",
     "Dementia + depression -> dementia with behavioral disturbance F03.91 HCC 52"),

    # CKD + Hyperkalemia -> secondary hyperkalemia
    ("N18.4", 137, "E87.5", None, "N25.9", 138, 0.6000,
     "ckd_hyperkalemia_renal_tubular",
     "CKD + hyperkalemia -> renal tubular disorder N25.9"),

    # Heart failure + Cardiomyopathy
    ("I50.2", 85, "I42.9", None, "I42.0", 85, 0.6500,
     "hf_cardiomyopathy_dilated",
     "Systolic HF + cardiomyopathy -> dilated cardiomyopathy I42.0 HCC 85"),

    # Atrial fibrillation + Stroke -> cardioembolic stroke risk
    ("I48.91", 96, "I63.9", 100, "I63.4", 100, 0.5500,
     "afib_stroke_cardioembolic",
     "AFib + ischemic stroke -> cardioembolic stroke I63.4 HCC 100"),

    # COPD + Pulmonary hypertension
    ("J44.9", 111, "I27.2", None, "I27.20", 85, 0.6000,
     "copd_pulm_htn",
     "COPD + secondary pulmonary hypertension I27.2 HCC 85"),

    # DM + Depression -> screen for DM with complications
    ("E11.9", 19, "F33.1", 155, "E11.69", 18, 0.4500,
     "dm_depression_complications",
     "DM + major depression -> screen for other DM complications"),

    # Chronic pain + Opioid use
    ("G89.29", None, "F11.20", 55, "F11.20", 55, 0.7000,
     "chronic_pain_opioid_confirm",
     "Chronic pain + opioid dependence -> confirm opioid use disorder coding"),
]


# ---------------------------------------------------------------------------
# Upsert SQL
# ---------------------------------------------------------------------------

UPSERT_SQL = """
INSERT INTO raf_comorbidity_patterns (
    condition_a_icd, condition_a_hcc, condition_b_icd, condition_b_hcc,
    suspect_icd10, suspect_hcc, confidence_base, pattern_name, notes, is_active
) VALUES (
    %s, %s, %s, %s, %s, %s, %s, %s, %s, 1
)
ON DUPLICATE KEY UPDATE
    condition_a_hcc = VALUES(condition_a_hcc),
    condition_b_hcc = VALUES(condition_b_hcc),
    suspect_hcc     = VALUES(suspect_hcc),
    confidence_base = VALUES(confidence_base),
    pattern_name    = VALUES(pattern_name),
    notes           = VALUES(notes),
    is_active       = 1
"""


def main() -> int:
    log.info("Connecting to MySQL at %s:%s ...", DB_CONFIG["host"], DB_CONFIG["port"])

    try:
        conn = mysql.connector.connect(**DB_CONFIG)
        cursor = conn.cursor()
    except MySQLError as e:
        log.error("Database connection failed: %s", e)
        return 1

    # Ensure the table exists
    migration_path = os.path.join(
        os.path.dirname(__file__), "create_comorbidity_patterns.sql"
    )
    if os.path.exists(migration_path):
        log.info("Applying migration from %s ...", migration_path)
        with open(migration_path, "r") as f:
            ddl = f.read()
        # Execute each statement (skip comments-only blocks)
        for stmt in ddl.split(";"):
            stmt = stmt.strip()
            if stmt and not stmt.startswith("--"):
                try:
                    cursor.execute(stmt)
                except MySQLError as e:
                    # Ignore "table already exists" and similar
                    if e.errno not in (1050, 1061):
                        log.warning("DDL warning: %s", e)
        conn.commit()
    else:
        log.warning("Migration file not found at %s; assuming table exists.", migration_path)

    # Seed the patterns
    inserted = 0
    skipped = 0
    for row in PATTERNS:
        (cond_a_icd, cond_a_hcc, cond_b_icd, cond_b_hcc,
         suspect_icd, suspect_hcc, confidence, pattern_name, notes) = row
        try:
            cursor.execute(
                UPSERT_SQL,
                (cond_a_icd, cond_a_hcc, cond_b_icd, cond_b_hcc,
                 suspect_icd, suspect_hcc, confidence, pattern_name, notes),
            )
            if cursor.rowcount > 0:
                inserted += 1
            else:
                skipped += 1
        except MySQLError as e:
            log.error("Failed to insert pattern '%s': %s", pattern_name, e)
            skipped += 1

    conn.commit()
    cursor.close()
    conn.close()

    log.info(
        "Seeding complete: %d patterns processed (%d inserted/updated, %d unchanged)",
        len(PATTERNS), inserted, skipped,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
