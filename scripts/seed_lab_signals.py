#!/usr/bin/env python3
"""
seed_lab_signals.py
--------------------
Expands raf_lab_signals with comprehensive lab abnormality -> ICD-10 -> HCC
mappings for all major HCC-relevant clinical conditions.

Covers the highest-impact HCC categories for Medicare Advantage risk
adjustment:

    Diabetes, CKD, CHF, Liver Disease, Thyroid, Anemia/Blood Disorders,
    Lipid/Cardiovascular, Nutritional/Metabolic, Coagulation/DVT,
    Autoimmune, Cancer Markers, HIV, Respiratory, Endocrine

Data sources:
    - Standard LOINC codes for common laboratory tests
    - CMS-HCC V24 / V28 crosswalk mappings
    - Clinical laboratory reference ranges
    - Evidence-based clinical decision thresholds

Idempotent: checks existing (lab_name_pattern, lab_loinc_code,
threshold_operator, threshold_value, suspect_icd10) tuples before
inserting.  Safe to run multiple times.

Usage:
    python scripts/seed_lab_signals.py

    # With custom DB connection:
    RAF_DB_HOST=10.1.0.204 RAF_DB_PORT=3306 RAF_DB_USER=root \\
      RAF_DB_PASSWORD=secret python scripts/seed_lab_signals.py
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
# Signal Data
#
# Each tuple:
#   (lab_name_pattern, lab_loinc_code, threshold_operator,
#    threshold_value, threshold_low, threshold_high,
#    threshold_unit, suspect_icd10, suspect_hcc,
#    confidence_base, notes)
#
# For single-threshold operators (<, <=, >, >=, =, !=):
#   - threshold_value is set, threshold_low/high are None
#
# For BETWEEN operator:
#   - threshold_value is None, threshold_low/high are set
#
# Patterns use SQL LIKE syntax (trailing %).
# LOINC codes follow standard nomenclature.
# HCC numbers follow the CMS-HCC V24/V28 model.
# Confidence reflects specificity of the lab abnormality for the condition.
# ---------------------------------------------------------------------------

SIGNALS: list[tuple] = [

    # =========================================================================
    # DIABETES MELLITUS  (HCC 18, 19)
    # =========================================================================

    # --- HbA1c / A1C (LOINC 4548-4) ---
    ('HbA1c%', '4548-4', '>=', Decimal('6.5'), None, None,
     '%', 'E11.9', 19, Decimal('0.9000'),
     'HbA1c >= 6.5% diagnostic for Type 2 Diabetes'),

    ('HbA1c%', '4548-4', '>=', Decimal('9.0'), None, None,
     '%', 'E11.65', 18, Decimal('0.8500'),
     'HbA1c >= 9.0% = DM with hyperglycemia (poor control)'),

    ('HbA1c%', '4548-4', 'BETWEEN', None, Decimal('5.7'), Decimal('6.4'),
     '%', 'R73.03', 0, Decimal('0.6000'),
     'HbA1c 5.7-6.4% = Prediabetes'),

    ('A1C%', '4548-4', '>=', Decimal('6.5'), None, None,
     '%', 'E11.9', 19, Decimal('0.9000'),
     'A1C >= 6.5% diagnostic for Type 2 Diabetes'),

    ('A1C%', '4548-4', '>=', Decimal('9.0'), None, None,
     '%', 'E11.65', 18, Decimal('0.8500'),
     'A1C >= 9.0% = DM with hyperglycemia (poor control)'),

    ('A1C%', '4548-4', 'BETWEEN', None, Decimal('5.7'), Decimal('6.4'),
     '%', 'R73.03', 0, Decimal('0.6000'),
     'A1C 5.7-6.4% = Prediabetes'),

    ('glycated hemoglobin%', '4548-4', '>=', Decimal('6.5'), None, None,
     '%', 'E11.9', 19, Decimal('0.9000'),
     'Glycated hemoglobin >= 6.5% diagnostic for Type 2 DM'),

    ('glycated hemoglobin%', '4548-4', '>=', Decimal('9.0'), None, None,
     '%', 'E11.65', 18, Decimal('0.8500'),
     'Glycated hemoglobin >= 9.0% = DM with hyperglycemia'),

    ('glycosylated hemoglobin%', '4548-4', '>=', Decimal('6.5'), None, None,
     '%', 'E11.9', 19, Decimal('0.9000'),
     'Glycosylated hemoglobin >= 6.5% diagnostic for Type 2 DM'),

    # --- Fasting glucose (LOINC 1558-6) ---
    ('fasting glucose%', '1558-6', '>=', Decimal('126.0'), None, None,
     'mg/dL', 'E11.9', 19, Decimal('0.8000'),
     'Fasting glucose >= 126 mg/dL diagnostic for diabetes'),

    ('fasting blood sugar%', '1558-6', '>=', Decimal('126.0'), None, None,
     'mg/dL', 'E11.9', 19, Decimal('0.8000'),
     'Fasting blood sugar >= 126 mg/dL diagnostic for diabetes'),

    ('fasting glucose%', '1558-6', 'BETWEEN', None, Decimal('100.0'), Decimal('125.0'),
     'mg/dL', 'R73.03', 0, Decimal('0.5500'),
     'Fasting glucose 100-125 = impaired fasting glucose / prediabetes'),

    ('glucose%fasting%', '1558-6', '>=', Decimal('126.0'), None, None,
     'mg/dL', 'E11.9', 19, Decimal('0.8000'),
     'Glucose fasting >= 126 mg/dL diagnostic for diabetes'),

    # --- Random glucose (LOINC 2345-7) ---
    ('glucose%', '2345-7', '>=', Decimal('200.0'), None, None,
     'mg/dL', 'E11.9', 19, Decimal('0.7500'),
     'Random glucose >= 200 mg/dL suggests diabetes'),

    ('blood glucose%', '2345-7', '>=', Decimal('200.0'), None, None,
     'mg/dL', 'E11.9', 19, Decimal('0.7500'),
     'Blood glucose >= 200 mg/dL suggests diabetes'),

    ('glucose%random%', '2345-7', '>=', Decimal('200.0'), None, None,
     'mg/dL', 'E11.9', 19, Decimal('0.7500'),
     'Random glucose >= 200 suggests diabetes'),

    ('glucose%', '2345-7', '>=', Decimal('300.0'), None, None,
     'mg/dL', 'E11.65', 18, Decimal('0.8500'),
     'Glucose >= 300 mg/dL = DM with hyperglycemia'),

    # --- Microalbumin/creatinine ratio (LOINC 14959-1) ---
    ('microalbumin%creatinine%', '14959-1', '>=', Decimal('30.0'), None, None,
     'mg/g', 'E11.21', 18, Decimal('0.7000'),
     'Microalbumin/creatinine ratio >= 30 suggests DM nephropathy (microalbuminuria)'),

    ('microalbumin%creatinine%', '14959-1', '>=', Decimal('300.0'), None, None,
     'mg/g', 'E11.21', 18, Decimal('0.8500'),
     'Microalbumin/creatinine ratio >= 300 = macroalbuminuria (DM nephropathy)'),

    ('albumin%creatinine ratio%', '14959-1', '>=', Decimal('30.0'), None, None,
     'mg/g', 'E11.21', 18, Decimal('0.7000'),
     'ACR >= 30 mg/g suggests diabetic nephropathy'),

    ('albumin%creatinine ratio%', '14959-1', '>=', Decimal('300.0'), None, None,
     'mg/g', 'E11.21', 18, Decimal('0.8500'),
     'ACR >= 300 mg/g = macroalbuminuria (severe DM nephropathy)'),

    ('uACR%', '14959-1', '>=', Decimal('30.0'), None, None,
     'mg/g', 'E11.21', 18, Decimal('0.7000'),
     'uACR >= 30 mg/g suggests diabetic nephropathy'),

    ('uACR%', '14959-1', '>=', Decimal('300.0'), None, None,
     'mg/g', 'E11.21', 18, Decimal('0.8500'),
     'uACR >= 300 mg/g = macroalbuminuria'),

    # --- Fructosamine (LOINC 1784-8) ---
    ('fructosamine%', '1784-8', '>=', Decimal('317.0'), None, None,
     'umol/L', 'E11.9', 19, Decimal('0.7000'),
     'Fructosamine >= 317 umol/L suggests diabetes'),

    # --- C-peptide (LOINC 1986-9) ---
    ('c-peptide%', '1986-9', '<', Decimal('0.8'), None, None,
     'ng/mL', 'E10.9', 19, Decimal('0.6500'),
     'Low C-peptide < 0.8 suggests Type 1 Diabetes (insulin deficiency)'),

    # =========================================================================
    # CHRONIC KIDNEY DISEASE  (HCC 136, 137, 138)
    # =========================================================================

    # --- eGFR (LOINC 98980-6) -- additional thresholds ---
    ('eGFR%', '98980-6', '<', Decimal('15.0'), None, None,
     'mL/min/1.73m2', 'N18.5', 136, Decimal('0.9500'),
     'eGFR < 15 = CKD Stage 5 (kidney failure)'),

    ('eGFR%', '98980-6', 'BETWEEN', None, Decimal('15.0'), Decimal('29.9'),
     'mL/min/1.73m2', 'N18.4', 137, Decimal('0.9000'),
     'eGFR 15-29 = CKD Stage 4'),

    ('eGFR%', '98980-6', 'BETWEEN', None, Decimal('30.0'), Decimal('44.9'),
     'mL/min/1.73m2', 'N18.3', 138, Decimal('0.8500'),
     'eGFR 30-44 = CKD Stage 3b'),

    ('eGFR%', '98980-6', 'BETWEEN', None, Decimal('45.0'), Decimal('59.9'),
     'mL/min/1.73m2', 'N18.3', 138, Decimal('0.8000'),
     'eGFR 45-59 = CKD Stage 3a'),

    ('glomerular filtration rate%', '98980-6', '<', Decimal('60.0'), None, None,
     'mL/min/1.73m2', 'N18.3', 138, Decimal('0.8000'),
     'GFR < 60 = CKD Stage 3+'),

    ('glomerular filtration rate%', '98980-6', '<', Decimal('30.0'), None, None,
     'mL/min/1.73m2', 'N18.4', 137, Decimal('0.9000'),
     'GFR < 30 = CKD Stage 4'),

    ('glomerular filtration rate%', '98980-6', '<', Decimal('15.0'), None, None,
     'mL/min/1.73m2', 'N18.5', 136, Decimal('0.9500'),
     'GFR < 15 = CKD Stage 5'),

    # --- Creatinine (LOINC 2160-0) -- additional thresholds ---
    ('creatinine%', '2160-0', '>', Decimal('2.0'), None, None,
     'mg/dL', 'N18.4', 137, Decimal('0.7500'),
     'Creatinine > 2.0 mg/dL suggests CKD Stage 4'),

    ('creatinine%', '2160-0', '>', Decimal('4.0'), None, None,
     'mg/dL', 'N18.5', 136, Decimal('0.8500'),
     'Creatinine > 4.0 mg/dL suggests CKD Stage 5'),

    ('serum creatinine%', '2160-0', '>', Decimal('1.5'), None, None,
     'mg/dL', 'N18.3', 138, Decimal('0.6500'),
     'Serum creatinine > 1.5 = elevated, suggests CKD Stage 3'),

    ('serum creatinine%', '2160-0', '>', Decimal('2.0'), None, None,
     'mg/dL', 'N18.4', 137, Decimal('0.7500'),
     'Serum creatinine > 2.0 suggests CKD Stage 4'),

    # --- BUN (LOINC 3094-0) ---
    ('BUN%', '3094-0', '>', Decimal('30.0'), None, None,
     'mg/dL', 'N18.3', 138, Decimal('0.5500'),
     'BUN > 30 mg/dL suggests renal impairment'),

    ('blood urea nitrogen%', '3094-0', '>', Decimal('30.0'), None, None,
     'mg/dL', 'N18.3', 138, Decimal('0.5500'),
     'Blood urea nitrogen > 30 suggests renal impairment'),

    ('BUN%', '3094-0', '>', Decimal('60.0'), None, None,
     'mg/dL', 'N18.4', 137, Decimal('0.7000'),
     'BUN > 60 mg/dL suggests advanced CKD'),

    ('urea nitrogen%', '3094-0', '>', Decimal('30.0'), None, None,
     'mg/dL', 'N18.3', 138, Decimal('0.5500'),
     'Urea nitrogen > 30 suggests renal impairment'),

    # --- Potassium (LOINC 2823-3) ---
    ('potassium%', '2823-3', '>', Decimal('5.5'), None, None,
     'mEq/L', 'N18.4', 137, Decimal('0.6000'),
     'Potassium > 5.5 = hyperkalemia, common in CKD Stage 4'),

    ('potassium%', '2823-3', '>', Decimal('6.0'), None, None,
     'mEq/L', 'N18.4', 137, Decimal('0.7000'),
     'Potassium > 6.0 = severe hyperkalemia in CKD'),

    ('K+%', '2823-3', '>', Decimal('5.5'), None, None,
     'mEq/L', 'N18.4', 137, Decimal('0.6000'),
     'K+ > 5.5 = hyperkalemia in CKD'),

    # --- Phosphorus (LOINC 2777-1) ---
    ('phosphorus%', '2777-1', '>', Decimal('4.5'), None, None,
     'mg/dL', 'N18.4', 137, Decimal('0.5500'),
     'Phosphorus > 4.5 = hyperphosphatemia in CKD'),

    ('phosphorus%', '2777-1', '>', Decimal('6.0'), None, None,
     'mg/dL', 'N18.5', 136, Decimal('0.7000'),
     'Phosphorus > 6.0 = severe hyperphosphatemia (ESRD)'),

    ('phosphate%', '2777-1', '>', Decimal('4.5'), None, None,
     'mg/dL', 'N18.4', 137, Decimal('0.5500'),
     'Phosphate > 4.5 suggests CKD hyperphosphatemia'),

    # --- Calcium (LOINC 17861-6) ---
    ('calcium%', '17861-6', '<', Decimal('8.5'), None, None,
     'mg/dL', 'N18.4', 137, Decimal('0.5000'),
     'Calcium < 8.5 = hypocalcemia in CKD'),

    ('calcium%', '17861-6', '<', Decimal('7.5'), None, None,
     'mg/dL', 'N18.5', 136, Decimal('0.6500'),
     'Calcium < 7.5 = severe hypocalcemia (advanced CKD)'),

    ('ionized calcium%', '1994-3', '<', Decimal('4.2'), None, None,
     'mg/dL', 'N18.4', 137, Decimal('0.5500'),
     'Ionized calcium < 4.2 = hypocalcemia in CKD'),

    # --- Urine protein (LOINC 2888-6) ---
    ('urine protein%', '2888-6', '>=', Decimal('300.0'), None, None,
     'mg/24h', 'N18.3', 138, Decimal('0.7000'),
     'Urine protein >= 300 mg/24h = significant proteinuria (CKD)'),

    ('24 hour urine protein%', '2888-6', '>=', Decimal('300.0'), None, None,
     'mg/24h', 'N18.3', 138, Decimal('0.7000'),
     '24-hour urine protein >= 300 mg = significant proteinuria'),

    ('urine protein%', '2888-6', '>=', Decimal('3500.0'), None, None,
     'mg/24h', 'N18.4', 137, Decimal('0.8000'),
     'Urine protein >= 3500 mg/24h = nephrotic-range proteinuria'),

    ('protein%urine%', '2888-6', '>=', Decimal('300.0'), None, None,
     'mg/24h', 'N18.3', 138, Decimal('0.7000'),
     'Protein in urine >= 300 mg/24h = significant proteinuria'),

    # --- Cystatin C (LOINC 33863-2) ---
    ('cystatin C%', '33863-2', '>', Decimal('1.2'), None, None,
     'mg/L', 'N18.3', 138, Decimal('0.7000'),
     'Cystatin C > 1.2 suggests CKD (alternative to creatinine)'),

    # =========================================================================
    # CONGESTIVE HEART FAILURE  (HCC 85, 86)
    # =========================================================================

    # --- BNP (LOINC 30934-4) ---
    ('BNP%', '30934-4', '>', Decimal('100.0'), None, None,
     'pg/mL', 'I50.9', 85, Decimal('0.8000'),
     'BNP > 100 pg/mL suggests heart failure'),

    ('BNP%', '30934-4', '>', Decimal('400.0'), None, None,
     'pg/mL', 'I50.9', 85, Decimal('0.9000'),
     'BNP > 400 pg/mL strongly suggests heart failure'),

    ('BNP%', '30934-4', '>', Decimal('900.0'), None, None,
     'pg/mL', 'I50.9', 85, Decimal('0.9500'),
     'BNP > 900 pg/mL = severe heart failure'),

    ('brain natriuretic peptide%', '30934-4', '>', Decimal('100.0'), None, None,
     'pg/mL', 'I50.9', 85, Decimal('0.8000'),
     'Brain natriuretic peptide > 100 suggests CHF'),

    ('brain natriuretic peptide%', '30934-4', '>', Decimal('400.0'), None, None,
     'pg/mL', 'I50.9', 85, Decimal('0.9000'),
     'Brain natriuretic peptide > 400 strongly suggests CHF'),

    # --- NT-proBNP (LOINC 33762-6) ---
    ('NT-proBNP%', '33762-6', '>', Decimal('300.0'), None, None,
     'pg/mL', 'I50.9', 85, Decimal('0.8000'),
     'NT-proBNP > 300 pg/mL suggests heart failure'),

    ('NT-proBNP%', '33762-6', '>', Decimal('900.0'), None, None,
     'pg/mL', 'I50.9', 85, Decimal('0.9000'),
     'NT-proBNP > 900 pg/mL strongly suggests heart failure'),

    ('NT-proBNP%', '33762-6', '>', Decimal('1800.0'), None, None,
     'pg/mL', 'I50.9', 85, Decimal('0.9500'),
     'NT-proBNP > 1800 = severe heart failure (age >= 75)'),

    ('pro-BNP%', '33762-6', '>', Decimal('300.0'), None, None,
     'pg/mL', 'I50.9', 85, Decimal('0.8000'),
     'Pro-BNP > 300 suggests heart failure'),

    ('pro-BNP%', '33762-6', '>', Decimal('900.0'), None, None,
     'pg/mL', 'I50.9', 85, Decimal('0.9000'),
     'Pro-BNP > 900 strongly suggests heart failure'),

    ('N-terminal pro-BNP%', '33762-6', '>', Decimal('300.0'), None, None,
     'pg/mL', 'I50.9', 85, Decimal('0.8000'),
     'N-terminal pro-BNP > 300 suggests CHF'),

    # --- Ejection Fraction (LOINC 10230-1) ---
    ('ejection fraction%', '10230-1', '<', Decimal('40.0'), None, None,
     '%', 'I50.22', 85, Decimal('0.9200'),
     'EF < 40% = systolic heart failure (HFrEF)'),

    ('ejection fraction%', '10230-1', '<', Decimal('50.0'), None, None,
     '%', 'I50.9', 85, Decimal('0.7500'),
     'EF < 50% = reduced cardiac function (heart failure)'),

    ('ejection fraction%', '10230-1', '<', Decimal('30.0'), None, None,
     '%', 'I50.22', 85, Decimal('0.9500'),
     'EF < 30% = severe systolic heart failure'),

    ('EF%', '10230-1', '<', Decimal('40.0'), None, None,
     '%', 'I50.22', 85, Decimal('0.9200'),
     'EF < 40% = systolic heart failure (HFrEF)'),

    ('EF%', '10230-1', '<', Decimal('50.0'), None, None,
     '%', 'I50.9', 85, Decimal('0.7500'),
     'EF < 50% = reduced cardiac function'),

    ('LVEF%', '10230-1', '<', Decimal('40.0'), None, None,
     '%', 'I50.22', 85, Decimal('0.9200'),
     'LVEF < 40% = HFrEF (systolic heart failure)'),

    ('LVEF%', '10230-1', '<', Decimal('50.0'), None, None,
     '%', 'I50.9', 85, Decimal('0.7500'),
     'LVEF < 50% suggests heart failure'),

    # =========================================================================
    # LIVER DISEASE  (HCC 27, 28, 29)
    # =========================================================================

    # --- ALT/SGPT (LOINC 1742-6) ---
    ('ALT%', '1742-6', '>', Decimal('56.0'), None, None,
     'U/L', 'K76.0', 29, Decimal('0.5000'),
     'ALT > 56 U/L = elevated, suggests fatty liver disease'),

    ('ALT%', '1742-6', '>', Decimal('200.0'), None, None,
     'U/L', 'K75.9', 29, Decimal('0.7000'),
     'ALT > 200 U/L suggests acute hepatitis'),

    ('ALT%', '1742-6', '>', Decimal('500.0'), None, None,
     'U/L', 'K75.9', 29, Decimal('0.8000'),
     'ALT > 500 U/L = significant hepatocellular injury'),

    ('SGPT%', '1742-6', '>', Decimal('56.0'), None, None,
     'U/L', 'K76.0', 29, Decimal('0.5000'),
     'SGPT > 56 U/L = elevated, suggests liver disease'),

    ('alanine aminotransferase%', '1742-6', '>', Decimal('56.0'), None, None,
     'U/L', 'K76.0', 29, Decimal('0.5000'),
     'Alanine aminotransferase > 56 = elevated (fatty liver)'),

    ('alanine aminotransferase%', '1742-6', '>', Decimal('200.0'), None, None,
     'U/L', 'K75.9', 29, Decimal('0.7000'),
     'ALT > 200 = hepatitis'),

    # --- AST/SGOT (LOINC 1920-8) ---
    ('AST%', '1920-8', '>', Decimal('40.0'), None, None,
     'U/L', 'K76.0', 29, Decimal('0.5000'),
     'AST > 40 U/L = elevated, suggests liver disease'),

    ('AST%', '1920-8', '>', Decimal('200.0'), None, None,
     'U/L', 'K75.9', 29, Decimal('0.7000'),
     'AST > 200 U/L suggests hepatitis'),

    ('AST%', '1920-8', '>', Decimal('500.0'), None, None,
     'U/L', 'K75.9', 29, Decimal('0.8000'),
     'AST > 500 = significant hepatocellular injury'),

    ('SGOT%', '1920-8', '>', Decimal('40.0'), None, None,
     'U/L', 'K76.0', 29, Decimal('0.5000'),
     'SGOT > 40 U/L = elevated, suggests liver disease'),

    ('SGOT%', '1920-8', '>', Decimal('200.0'), None, None,
     'U/L', 'K75.9', 29, Decimal('0.7000'),
     'SGOT > 200 U/L suggests hepatitis'),

    ('aspartate aminotransferase%', '1920-8', '>', Decimal('40.0'), None, None,
     'U/L', 'K76.0', 29, Decimal('0.5000'),
     'Aspartate aminotransferase > 40 = elevated'),

    # --- Total bilirubin (LOINC 1975-2) ---
    ('total bilirubin%', '1975-2', '>', Decimal('2.0'), None, None,
     'mg/dL', 'K76.0', 29, Decimal('0.6000'),
     'Total bilirubin > 2.0 mg/dL = elevated (liver disease)'),

    ('total bilirubin%', '1975-2', '>', Decimal('5.0'), None, None,
     'mg/dL', 'K74.60', 28, Decimal('0.7000'),
     'Total bilirubin > 5.0 mg/dL suggests cirrhosis'),

    ('total bilirubin%', '1975-2', '>', Decimal('10.0'), None, None,
     'mg/dL', 'K74.60', 28, Decimal('0.8000'),
     'Total bilirubin > 10 mg/dL = severe liver disease/cirrhosis'),

    ('bilirubin%total%', '1975-2', '>', Decimal('2.0'), None, None,
     'mg/dL', 'K76.0', 29, Decimal('0.6000'),
     'Bilirubin total > 2.0 suggests liver disease'),

    ('bilirubin%total%', '1975-2', '>', Decimal('5.0'), None, None,
     'mg/dL', 'K74.60', 28, Decimal('0.7000'),
     'Bilirubin total > 5.0 suggests cirrhosis'),

    ('T. bilirubin%', '1975-2', '>', Decimal('2.0'), None, None,
     'mg/dL', 'K76.0', 29, Decimal('0.6000'),
     'T. bilirubin > 2.0 mg/dL = elevated'),

    # --- Direct bilirubin (LOINC 1968-7) ---
    ('direct bilirubin%', '1968-7', '>', Decimal('0.4'), None, None,
     'mg/dL', 'K76.0', 29, Decimal('0.5500'),
     'Direct bilirubin > 0.4 mg/dL suggests hepatobiliary disease'),

    ('direct bilirubin%', '1968-7', '>', Decimal('2.0'), None, None,
     'mg/dL', 'K74.60', 28, Decimal('0.6500'),
     'Direct bilirubin > 2.0 suggests severe liver disease'),

    # --- Albumin (LOINC 1751-7) ---
    ('albumin%', '1751-7', '<', Decimal('3.5'), None, None,
     'g/dL', 'K74.60', 28, Decimal('0.5500'),
     'Albumin < 3.5 g/dL = hypoalbuminemia (cirrhosis, malnutrition)'),

    ('albumin%', '1751-7', '<', Decimal('2.5'), None, None,
     'g/dL', 'K74.60', 28, Decimal('0.7500'),
     'Albumin < 2.5 g/dL = severe hypoalbuminemia (advanced cirrhosis)'),

    ('albumin%', '1751-7', '<', Decimal('2.0'), None, None,
     'g/dL', 'K74.60', 28, Decimal('0.8500'),
     'Albumin < 2.0 = critical hypoalbuminemia (decompensated cirrhosis)'),

    ('serum albumin%', '1751-7', '<', Decimal('3.5'), None, None,
     'g/dL', 'K74.60', 28, Decimal('0.5500'),
     'Serum albumin < 3.5 suggests cirrhosis'),

    ('serum albumin%', '1751-7', '<', Decimal('2.5'), None, None,
     'g/dL', 'K74.60', 28, Decimal('0.7500'),
     'Serum albumin < 2.5 = advanced cirrhosis'),

    # --- INR (LOINC 6301-6) ---
    ('INR%', '6301-6', '>', Decimal('1.5'), None, None,
     '', 'K74.60', 28, Decimal('0.6000'),
     'INR > 1.5 = coagulopathy, suggests cirrhosis (if not on anticoagulants)'),

    ('INR%', '6301-6', '>', Decimal('2.0'), None, None,
     '', 'K74.60', 28, Decimal('0.6500'),
     'INR > 2.0 without anticoag suggests advanced liver disease'),

    ('international normalized ratio%', '6301-6', '>', Decimal('1.5'), None, None,
     '', 'K74.60', 28, Decimal('0.6000'),
     'International normalized ratio > 1.5 suggests liver coagulopathy'),

    # --- AFP (LOINC 1834-1) ---
    ('AFP%', '1834-1', '>', Decimal('20.0'), None, None,
     'ng/mL', 'C22.0', 12, Decimal('0.6500'),
     'AFP > 20 ng/mL raises suspicion for hepatocellular carcinoma'),

    ('AFP%', '1834-1', '>', Decimal('200.0'), None, None,
     'ng/mL', 'C22.0', 12, Decimal('0.8000'),
     'AFP > 200 ng/mL highly suspicious for liver cancer'),

    ('AFP%', '1834-1', '>', Decimal('400.0'), None, None,
     'ng/mL', 'C22.0', 12, Decimal('0.9000'),
     'AFP > 400 = diagnostic threshold for HCC'),

    ('alpha-fetoprotein%', '1834-1', '>', Decimal('20.0'), None, None,
     'ng/mL', 'C22.0', 12, Decimal('0.6500'),
     'Alpha-fetoprotein > 20 suggests HCC'),

    ('alpha-fetoprotein%', '1834-1', '>', Decimal('200.0'), None, None,
     'ng/mL', 'C22.0', 12, Decimal('0.8000'),
     'Alpha-fetoprotein > 200 highly suspicious for HCC'),

    # --- Hepatitis C viral load (LOINC 11259-9) ---
    ('hepatitis C%viral load%', '11259-9', '>', Decimal('0.0'), None, None,
     'IU/mL', 'B18.2', 6, Decimal('0.9000'),
     'Detectable HCV viral load = chronic Hepatitis C'),

    ('HCV%RNA%', '11259-9', '>', Decimal('0.0'), None, None,
     'IU/mL', 'B18.2', 6, Decimal('0.9000'),
     'Detectable HCV RNA = active Hepatitis C infection'),

    ('HCV%viral load%', '11259-9', '>', Decimal('0.0'), None, None,
     'IU/mL', 'B18.2', 6, Decimal('0.9000'),
     'Detectable HCV viral load = chronic Hepatitis C'),

    ('hep C%RNA%', '11259-9', '>', Decimal('0.0'), None, None,
     'IU/mL', 'B18.2', 6, Decimal('0.9000'),
     'Detectable Hep C RNA = active HCV'),

    # --- Hepatitis B (LOINC 5195-3) ---
    ('hepatitis B%surface antigen%', '5195-3', '>', Decimal('0.0'), None, None,
     '', 'B18.1', 6, Decimal('0.9000'),
     'HBsAg positive/reactive = chronic Hepatitis B'),

    ('HBsAg%', '5195-3', '>', Decimal('0.0'), None, None,
     '', 'B18.1', 6, Decimal('0.9000'),
     'HBsAg positive = Hepatitis B infection'),

    ('HBV%DNA%', '42595-9', '>', Decimal('0.0'), None, None,
     'IU/mL', 'B18.1', 6, Decimal('0.9000'),
     'Detectable HBV DNA = active Hepatitis B'),

    # --- GGT (LOINC 2324-2) ---
    ('GGT%', '2324-2', '>', Decimal('60.0'), None, None,
     'U/L', 'K76.0', 29, Decimal('0.4500'),
     'GGT > 60 suggests liver disease (cholestatic or alcoholic)'),

    ('gamma-glutamyl%', '2324-2', '>', Decimal('60.0'), None, None,
     'U/L', 'K76.0', 29, Decimal('0.4500'),
     'Gamma-glutamyl transferase > 60 suggests liver disease'),

    # --- Alkaline Phosphatase (LOINC 6768-6) ---
    ('alkaline phosphatase%', '6768-6', '>', Decimal('150.0'), None, None,
     'U/L', 'K76.0', 29, Decimal('0.4500'),
     'Alkaline phosphatase > 150 = elevated (cholestatic liver disease)'),

    ('ALP%', '6768-6', '>', Decimal('150.0'), None, None,
     'U/L', 'K76.0', 29, Decimal('0.4500'),
     'ALP > 150 suggests cholestatic liver disease'),

    ('alk phos%', '6768-6', '>', Decimal('150.0'), None, None,
     'U/L', 'K76.0', 29, Decimal('0.4500'),
     'Alk phos > 150 = elevated (liver/bone disease)'),

    # --- Ammonia (LOINC 1925-7) ---
    ('ammonia%', '1925-7', '>', Decimal('60.0'), None, None,
     'umol/L', 'K74.60', 28, Decimal('0.7000'),
     'Ammonia > 60 umol/L suggests hepatic encephalopathy (cirrhosis)'),

    ('ammonia%', '1925-7', '>', Decimal('100.0'), None, None,
     'umol/L', 'K74.60', 28, Decimal('0.8000'),
     'Ammonia > 100 = severe hepatic encephalopathy'),

    # =========================================================================
    # THYROID DISEASE  (HCC 23)
    # =========================================================================

    # --- TSH (LOINC 3016-3) ---
    ('TSH%', '3016-3', '>', Decimal('10.0'), None, None,
     'mIU/L', 'E03.9', 23, Decimal('0.8000'),
     'TSH > 10 mIU/L = overt hypothyroidism'),

    ('TSH%', '3016-3', '>', Decimal('20.0'), None, None,
     'mIU/L', 'E03.9', 23, Decimal('0.9000'),
     'TSH > 20 = severe hypothyroidism'),

    ('TSH%', '3016-3', '<', Decimal('0.1'), None, None,
     'mIU/L', 'E05.90', 23, Decimal('0.8000'),
     'TSH < 0.1 mIU/L = overt hyperthyroidism'),

    ('TSH%', '3016-3', '<', Decimal('0.01'), None, None,
     'mIU/L', 'E05.90', 23, Decimal('0.9000'),
     'TSH < 0.01 = severe hyperthyroidism (suppressed)'),

    ('thyroid stimulating hormone%', '3016-3', '>', Decimal('10.0'), None, None,
     'mIU/L', 'E03.9', 23, Decimal('0.8000'),
     'Thyroid stimulating hormone > 10 = hypothyroidism'),

    ('thyroid stimulating hormone%', '3016-3', '<', Decimal('0.1'), None, None,
     'mIU/L', 'E05.90', 23, Decimal('0.8000'),
     'Thyroid stimulating hormone < 0.1 = hyperthyroidism'),

    ('thyrotropin%', '3016-3', '>', Decimal('10.0'), None, None,
     'mIU/L', 'E03.9', 23, Decimal('0.8000'),
     'Thyrotropin > 10 = hypothyroidism'),

    ('thyrotropin%', '3016-3', '<', Decimal('0.1'), None, None,
     'mIU/L', 'E05.90', 23, Decimal('0.8000'),
     'Thyrotropin < 0.1 = hyperthyroidism'),

    # --- Free T4 (LOINC 3024-7) ---
    ('free T4%', '3024-7', '<', Decimal('0.8'), None, None,
     'ng/dL', 'E03.9', 23, Decimal('0.6500'),
     'Free T4 < 0.8 ng/dL = low (hypothyroidism)'),

    ('free T4%', '3024-7', '>', Decimal('1.8'), None, None,
     'ng/dL', 'E05.90', 23, Decimal('0.6500'),
     'Free T4 > 1.8 ng/dL = elevated (hyperthyroidism)'),

    ('free T4%', '3024-7', '>', Decimal('3.0'), None, None,
     'ng/dL', 'E05.90', 23, Decimal('0.8000'),
     'Free T4 > 3.0 = significantly elevated (overt hyperthyroidism)'),

    ('FT4%', '3024-7', '<', Decimal('0.8'), None, None,
     'ng/dL', 'E03.9', 23, Decimal('0.6500'),
     'FT4 < 0.8 ng/dL suggests hypothyroidism'),

    ('FT4%', '3024-7', '>', Decimal('1.8'), None, None,
     'ng/dL', 'E05.90', 23, Decimal('0.6500'),
     'FT4 > 1.8 ng/dL suggests hyperthyroidism'),

    ('free thyroxine%', '3024-7', '<', Decimal('0.8'), None, None,
     'ng/dL', 'E03.9', 23, Decimal('0.6500'),
     'Free thyroxine < 0.8 = hypothyroidism'),

    ('free thyroxine%', '3024-7', '>', Decimal('1.8'), None, None,
     'ng/dL', 'E05.90', 23, Decimal('0.6500'),
     'Free thyroxine > 1.8 = hyperthyroidism'),

    # --- Free T3 (LOINC 3051-0) ---
    ('free T3%', '3051-0', '>', Decimal('4.4'), None, None,
     'pg/mL', 'E05.90', 23, Decimal('0.6000'),
     'Free T3 > 4.4 pg/mL suggests hyperthyroidism'),

    ('free T3%', '3051-0', '<', Decimal('2.0'), None, None,
     'pg/mL', 'E03.9', 23, Decimal('0.5500'),
     'Free T3 < 2.0 suggests hypothyroidism'),

    # --- Thyroid antibodies ---
    ('TPO antibod%', '5382-7', '>', Decimal('35.0'), None, None,
     'IU/mL', 'E06.3', 23, Decimal('0.6000'),
     'TPO antibody > 35 = Hashimoto thyroiditis'),

    ('thyroid peroxidase%', '5382-7', '>', Decimal('35.0'), None, None,
     'IU/mL', 'E06.3', 23, Decimal('0.6000'),
     'Thyroid peroxidase antibody > 35 = autoimmune thyroiditis'),

    # =========================================================================
    # ANEMIA / BLOOD DISORDERS  (HCC 46, 48)
    # =========================================================================

    # --- Hemoglobin (LOINC 718-7) ---
    ('hemoglobin%', '718-7', '<', Decimal('10.0'), None, None,
     'g/dL', 'D64.9', 48, Decimal('0.7000'),
     'Hemoglobin < 10 g/dL = moderate anemia'),

    ('hemoglobin%', '718-7', '<', Decimal('7.0'), None, None,
     'g/dL', 'D64.9', 48, Decimal('0.9000'),
     'Hemoglobin < 7 g/dL = severe anemia'),

    ('hemoglobin%', '718-7', '<', Decimal('8.0'), None, None,
     'g/dL', 'D64.9', 48, Decimal('0.8000'),
     'Hemoglobin < 8 g/dL = significant anemia'),

    ('Hgb%', '718-7', '<', Decimal('10.0'), None, None,
     'g/dL', 'D64.9', 48, Decimal('0.7000'),
     'Hgb < 10 = moderate anemia'),

    ('Hgb%', '718-7', '<', Decimal('7.0'), None, None,
     'g/dL', 'D64.9', 48, Decimal('0.9000'),
     'Hgb < 7 = severe anemia'),

    ('Hb%', '718-7', '<', Decimal('10.0'), None, None,
     'g/dL', 'D64.9', 48, Decimal('0.7000'),
     'Hb < 10 g/dL = moderate anemia'),

    # --- Hematocrit (LOINC 4544-3) ---
    ('hematocrit%', '4544-3', '<', Decimal('30.0'), None, None,
     '%', 'D64.9', 48, Decimal('0.6500'),
     'Hematocrit < 30% = significant anemia'),

    ('hematocrit%', '4544-3', '<', Decimal('25.0'), None, None,
     '%', 'D64.9', 48, Decimal('0.8000'),
     'Hematocrit < 25% = severe anemia'),

    ('HCT%', '4544-3', '<', Decimal('30.0'), None, None,
     '%', 'D64.9', 48, Decimal('0.6500'),
     'HCT < 30% = significant anemia'),

    # --- MCV (LOINC 787-2) ---
    ('MCV%', '787-2', '>', Decimal('100.0'), None, None,
     'fL', 'D51.0', 48, Decimal('0.5500'),
     'MCV > 100 fL = macrocytic anemia (B12/folate deficiency)'),

    ('MCV%', '787-2', '>', Decimal('110.0'), None, None,
     'fL', 'D51.0', 48, Decimal('0.7000'),
     'MCV > 110 = significantly macrocytic (B12 deficiency)'),

    ('MCV%', '787-2', '<', Decimal('80.0'), None, None,
     'fL', 'D50.9', 48, Decimal('0.5500'),
     'MCV < 80 fL = microcytic anemia (iron deficiency)'),

    ('MCV%', '787-2', '<', Decimal('70.0'), None, None,
     'fL', 'D50.9', 48, Decimal('0.7000'),
     'MCV < 70 = severely microcytic (iron deficiency or thalassemia)'),

    ('mean corpuscular volume%', '787-2', '>', Decimal('100.0'), None, None,
     'fL', 'D51.0', 48, Decimal('0.5500'),
     'Mean corpuscular volume > 100 = macrocytic anemia'),

    ('mean corpuscular volume%', '787-2', '<', Decimal('80.0'), None, None,
     'fL', 'D50.9', 48, Decimal('0.5500'),
     'Mean corpuscular volume < 80 = microcytic anemia'),

    # --- Ferritin (LOINC 2276-4) ---
    ('ferritin%', '2276-4', '<', Decimal('12.0'), None, None,
     'ng/mL', 'D50.9', 48, Decimal('0.7500'),
     'Ferritin < 12 ng/mL = iron deficiency anemia'),

    ('ferritin%', '2276-4', '<', Decimal('30.0'), None, None,
     'ng/mL', 'D50.9', 48, Decimal('0.6000'),
     'Ferritin < 30 ng/mL suggests iron deficiency'),

    ('ferritin%', '2276-4', '>', Decimal('1000.0'), None, None,
     'ng/mL', 'E83.10', 48, Decimal('0.6000'),
     'Ferritin > 1000 suggests iron overload / hemochromatosis'),

    # --- Iron saturation / TSAT (LOINC 2502-3) ---
    ('iron saturation%', '2502-3', '<', Decimal('20.0'), None, None,
     '%', 'D50.9', 48, Decimal('0.6500'),
     'Iron saturation < 20% = iron deficiency'),

    ('TSAT%', '2502-3', '<', Decimal('20.0'), None, None,
     '%', 'D50.9', 48, Decimal('0.6500'),
     'TSAT < 20% = iron deficiency'),

    ('transferrin saturation%', '2502-3', '<', Decimal('20.0'), None, None,
     '%', 'D50.9', 48, Decimal('0.6500'),
     'Transferrin saturation < 20% = iron deficiency'),

    ('iron saturation%', '2502-3', '>', Decimal('45.0'), None, None,
     '%', 'E83.10', 48, Decimal('0.5500'),
     'Iron saturation > 45% suggests iron overload'),

    # --- Platelet count (LOINC 777-3) ---
    ('platelet%', '777-3', '<', Decimal('100.0'), None, None,
     'K/uL', 'D69.6', 48, Decimal('0.6500'),
     'Platelet count < 100K = thrombocytopenia'),

    ('platelet%', '777-3', '<', Decimal('50.0'), None, None,
     'K/uL', 'D69.6', 48, Decimal('0.8000'),
     'Platelet count < 50K = severe thrombocytopenia'),

    ('platelet%', '777-3', '<', Decimal('20.0'), None, None,
     'K/uL', 'D69.6', 48, Decimal('0.9000'),
     'Platelet count < 20K = critical thrombocytopenia'),

    ('PLT%', '777-3', '<', Decimal('100.0'), None, None,
     'K/uL', 'D69.6', 48, Decimal('0.6500'),
     'PLT < 100K = thrombocytopenia'),

    ('PLT%', '777-3', '<', Decimal('50.0'), None, None,
     'K/uL', 'D69.6', 48, Decimal('0.8000'),
     'PLT < 50K = severe thrombocytopenia'),

    # --- Vitamin B12 (LOINC 2132-9) ---
    ('vitamin B12%', '2132-9', '<', Decimal('200.0'), None, None,
     'pg/mL', 'D51.0', 48, Decimal('0.6500'),
     'Vitamin B12 < 200 pg/mL = B12 deficiency'),

    ('B12%', '2132-9', '<', Decimal('200.0'), None, None,
     'pg/mL', 'D51.0', 48, Decimal('0.6500'),
     'B12 < 200 = deficiency (macrocytic anemia)'),

    ('cobalamin%', '2132-9', '<', Decimal('200.0'), None, None,
     'pg/mL', 'D51.0', 48, Decimal('0.6500'),
     'Cobalamin < 200 = B12 deficiency'),

    # --- Folate (LOINC 2284-8) ---
    ('folate%', '2284-8', '<', Decimal('3.0'), None, None,
     'ng/mL', 'D52.9', 48, Decimal('0.6500'),
     'Folate < 3 ng/mL = folate deficiency anemia'),

    ('folic acid%', '2284-8', '<', Decimal('3.0'), None, None,
     'ng/mL', 'D52.9', 48, Decimal('0.6500'),
     'Folic acid < 3 = folate deficiency'),

    # --- Reticulocyte count (LOINC 17849-1) ---
    ('reticulocyte%', '17849-1', '>', Decimal('2.5'), None, None,
     '%', 'D64.9', 48, Decimal('0.4500'),
     'Reticulocyte > 2.5% = hemolytic or blood loss anemia'),

    # --- WBC (LOINC 6690-2) ---
    ('WBC%', '6690-2', '<', Decimal('2.0'), None, None,
     'K/uL', 'D70.9', 48, Decimal('0.7000'),
     'WBC < 2K = severe leukopenia / neutropenia'),

    ('white blood cell%', '6690-2', '<', Decimal('2.0'), None, None,
     'K/uL', 'D70.9', 48, Decimal('0.7000'),
     'White blood cell count < 2K = severe leukopenia'),

    # =========================================================================
    # LIPID / CARDIOVASCULAR  (HCC 22, 86, 107)
    # =========================================================================

    # --- LDL (LOINC 13457-7) ---
    ('LDL%', '13457-7', '>', Decimal('190.0'), None, None,
     'mg/dL', 'E78.01', 22, Decimal('0.6000'),
     'LDL > 190 mg/dL suggests familial hypercholesterolemia'),

    ('LDL%', '13457-7', '>', Decimal('250.0'), None, None,
     'mg/dL', 'E78.01', 22, Decimal('0.7500'),
     'LDL > 250 = severe hypercholesterolemia (likely familial)'),

    ('LDL cholesterol%', '13457-7', '>', Decimal('190.0'), None, None,
     'mg/dL', 'E78.01', 22, Decimal('0.6000'),
     'LDL cholesterol > 190 suggests familial hypercholesterolemia'),

    ('low density lipoprotein%', '13457-7', '>', Decimal('190.0'), None, None,
     'mg/dL', 'E78.01', 22, Decimal('0.6000'),
     'Low density lipoprotein > 190 suggests familial HC'),

    # --- Triglycerides (LOINC 2571-8) ---
    ('triglyceride%', '2571-8', '>', Decimal('500.0'), None, None,
     'mg/dL', 'E78.1', 22, Decimal('0.6500'),
     'Triglycerides > 500 mg/dL = hypertriglyceridemia (pancreatitis risk)'),

    ('triglyceride%', '2571-8', '>', Decimal('1000.0'), None, None,
     'mg/dL', 'E78.1', 22, Decimal('0.8000'),
     'Triglycerides > 1000 = severe hypertriglyceridemia'),

    ('TG%', '2571-8', '>', Decimal('500.0'), None, None,
     'mg/dL', 'E78.1', 22, Decimal('0.6500'),
     'TG > 500 = severe hypertriglyceridemia'),

    # --- Total cholesterol (LOINC 2093-3) ---
    ('total cholesterol%', '2093-3', '>', Decimal('300.0'), None, None,
     'mg/dL', 'E78.0', 22, Decimal('0.5500'),
     'Total cholesterol > 300 mg/dL = severe hypercholesterolemia'),

    ('cholesterol%total%', '2093-3', '>', Decimal('300.0'), None, None,
     'mg/dL', 'E78.0', 22, Decimal('0.5500'),
     'Cholesterol total > 300 = severe hypercholesterolemia'),

    # --- Troponin I (LOINC 10839-9) ---
    ('troponin I%', '10839-9', '>', Decimal('0.04'), None, None,
     'ng/mL', 'I21.9', 86, Decimal('0.8500'),
     'Troponin I > 0.04 ng/mL suggests acute myocardial infarction'),

    ('troponin I%', '10839-9', '>', Decimal('0.4'), None, None,
     'ng/mL', 'I21.9', 86, Decimal('0.9200'),
     'Troponin I > 0.4 = significant myocardial injury (STEMI)'),

    ('trop I%', '10839-9', '>', Decimal('0.04'), None, None,
     'ng/mL', 'I21.9', 86, Decimal('0.8500'),
     'Trop I > 0.04 suggests AMI'),

    # --- Troponin T (LOINC 6598-7) ---
    ('troponin T%', '6598-7', '>', Decimal('0.01'), None, None,
     'ng/mL', 'I21.9', 86, Decimal('0.8000'),
     'Troponin T > 0.01 ng/mL suggests myocardial infarction'),

    ('troponin T%', '6598-7', '>', Decimal('0.1'), None, None,
     'ng/mL', 'I21.9', 86, Decimal('0.9000'),
     'Troponin T > 0.1 = significant myocardial injury'),

    ('trop T%', '6598-7', '>', Decimal('0.01'), None, None,
     'ng/mL', 'I21.9', 86, Decimal('0.8000'),
     'Trop T > 0.01 suggests AMI'),

    # --- High-sensitivity Troponin (LOINC 89579-7) ---
    ('hs-troponin%', '89579-7', '>', Decimal('14.0'), None, None,
     'ng/L', 'I21.9', 86, Decimal('0.7500'),
     'HS-Troponin > 14 ng/L (female) / 22 (male) suggests MI'),

    ('high sensitivity troponin%', '89579-7', '>', Decimal('14.0'), None, None,
     'ng/L', 'I21.9', 86, Decimal('0.7500'),
     'High sensitivity troponin elevated suggests myocardial injury'),

    # --- D-dimer (LOINC 48065-7) ---
    ('D-dimer%', '48065-7', '>', Decimal('500.0'), None, None,
     'ng/mL', 'I26.99', 107, Decimal('0.5500'),
     'D-dimer > 500 ng/mL raises suspicion for PE/DVT'),

    ('D-dimer%', '48065-7', '>', Decimal('2000.0'), None, None,
     'ng/mL', 'I26.99', 107, Decimal('0.7000'),
     'D-dimer > 2000 highly suspicious for PE/DVT'),

    ('d dimer%', '48065-7', '>', Decimal('500.0'), None, None,
     'ng/mL', 'I26.99', 107, Decimal('0.5500'),
     'D dimer > 500 suggests PE/DVT'),

    # --- Lp(a) (LOINC 10835-7) ---
    ('lipoprotein(a)%', '10835-7', '>', Decimal('50.0'), None, None,
     'mg/dL', 'E78.0', 22, Decimal('0.5500'),
     'Lipoprotein(a) > 50 mg/dL = elevated cardiovascular risk'),

    ('Lp(a)%', '10835-7', '>', Decimal('50.0'), None, None,
     'mg/dL', 'E78.0', 22, Decimal('0.5500'),
     'Lp(a) > 50 = elevated cardiovascular risk'),

    # =========================================================================
    # NUTRITIONAL / METABOLIC
    # =========================================================================

    # --- Vitamin D (LOINC 1989-3) ---
    ('vitamin D%', '1989-3', '<', Decimal('20.0'), None, None,
     'ng/mL', 'E55.9', 0, Decimal('0.5000'),
     'Vitamin D < 20 ng/mL = deficiency'),

    ('vitamin D%', '1989-3', '<', Decimal('10.0'), None, None,
     'ng/mL', 'E55.9', 0, Decimal('0.7000'),
     'Vitamin D < 10 = severe deficiency'),

    ('25-hydroxy vitamin D%', '1989-3', '<', Decimal('20.0'), None, None,
     'ng/mL', 'E55.9', 0, Decimal('0.5000'),
     '25-OH Vitamin D < 20 = deficiency'),

    ('25-OH vitamin D%', '1989-3', '<', Decimal('20.0'), None, None,
     'ng/mL', 'E55.9', 0, Decimal('0.5000'),
     '25-OH Vitamin D < 20 = deficiency'),

    # --- Sodium (LOINC 2951-2) ---
    ('sodium%', '2951-2', '<', Decimal('125.0'), None, None,
     'mEq/L', 'E87.1', 23, Decimal('0.6000'),
     'Sodium < 125 mEq/L = moderate-severe hyponatremia'),

    ('sodium%', '2951-2', '<', Decimal('120.0'), None, None,
     'mEq/L', 'E87.1', 23, Decimal('0.7500'),
     'Sodium < 120 = severe hyponatremia (seizure risk)'),

    ('sodium%', '2951-2', '>', Decimal('150.0'), None, None,
     'mEq/L', 'E87.0', 23, Decimal('0.6000'),
     'Sodium > 150 mEq/L = hypernatremia'),

    ('sodium%', '2951-2', '>', Decimal('155.0'), None, None,
     'mEq/L', 'E87.0', 23, Decimal('0.7500'),
     'Sodium > 155 = severe hypernatremia'),

    ('Na+%', '2951-2', '<', Decimal('125.0'), None, None,
     'mEq/L', 'E87.1', 23, Decimal('0.6000'),
     'Na+ < 125 = hyponatremia'),

    ('Na+%', '2951-2', '>', Decimal('150.0'), None, None,
     'mEq/L', 'E87.0', 23, Decimal('0.6000'),
     'Na+ > 150 = hypernatremia'),

    # --- Uric acid (LOINC 3084-1) ---
    ('uric acid%', '3084-1', '>', Decimal('9.0'), None, None,
     'mg/dL', 'M10.9', 39, Decimal('0.5500'),
     'Uric acid > 9.0 mg/dL suggests gout'),

    ('uric acid%', '3084-1', '>', Decimal('12.0'), None, None,
     'mg/dL', 'M10.9', 39, Decimal('0.7000'),
     'Uric acid > 12 = severe hyperuricemia (high gout risk)'),

    ('urate%', '3084-1', '>', Decimal('9.0'), None, None,
     'mg/dL', 'M10.9', 39, Decimal('0.5500'),
     'Urate > 9.0 suggests gout'),

    # --- Magnesium (LOINC 19123-9) ---
    ('magnesium%', '19123-9', '<', Decimal('1.5'), None, None,
     'mg/dL', 'E83.42', 23, Decimal('0.5000'),
     'Magnesium < 1.5 = hypomagnesemia'),

    ('Mg%', '19123-9', '<', Decimal('1.5'), None, None,
     'mg/dL', 'E83.42', 23, Decimal('0.5000'),
     'Mg < 1.5 = hypomagnesemia'),

    # =========================================================================
    # COAGULATION / DVT  (HCC 48)
    # =========================================================================

    # --- PT/INR (LOINC 5902-2) ---
    ('PT%', '5902-2', '>', Decimal('16.0'), None, None,
     'sec', 'D68.9', 48, Decimal('0.5500'),
     'PT > 16 sec suggests coagulopathy'),

    ('prothrombin time%', '5902-2', '>', Decimal('16.0'), None, None,
     'sec', 'D68.9', 48, Decimal('0.5500'),
     'Prothrombin time > 16 sec suggests coagulopathy'),

    ('INR%', '6301-6', '>', Decimal('4.0'), None, None,
     '', 'D68.9', 48, Decimal('0.6000'),
     'INR > 4.0 = coagulopathy (if not on anticoagulant therapy)'),

    # --- aPTT (LOINC 3173-2) ---
    ('aPTT%', '3173-2', '>', Decimal('60.0'), None, None,
     'sec', 'D68.9', 48, Decimal('0.5500'),
     'aPTT > 60 sec suggests coagulopathy'),

    ('aPTT%', '3173-2', '>', Decimal('100.0'), None, None,
     'sec', 'D68.9', 48, Decimal('0.7500'),
     'aPTT > 100 = severe coagulopathy'),

    ('activated partial thromboplastin%', '3173-2', '>', Decimal('60.0'), None, None,
     'sec', 'D68.9', 48, Decimal('0.5500'),
     'Activated partial thromboplastin time > 60 sec suggests coagulopathy'),

    ('PTT%', '3173-2', '>', Decimal('60.0'), None, None,
     'sec', 'D68.9', 48, Decimal('0.5500'),
     'PTT > 60 sec suggests coagulopathy'),

    # --- Fibrinogen (LOINC 3255-7) ---
    ('fibrinogen%', '3255-7', '<', Decimal('100.0'), None, None,
     'mg/dL', 'D68.9', 48, Decimal('0.6500'),
     'Fibrinogen < 100 mg/dL = hypofibrinogenemia (DIC, liver disease)'),

    ('fibrinogen%', '3255-7', '>', Decimal('700.0'), None, None,
     'mg/dL', 'D68.9', 48, Decimal('0.4000'),
     'Fibrinogen > 700 = acute phase reactant (inflammation/thrombosis risk)'),

    # =========================================================================
    # AUTOIMMUNE  (HCC 40)
    # =========================================================================

    # --- ANA (LOINC 8061-4) ---
    ('ANA%', '8061-4', '>', Decimal('0.0'), None, None,
     '', 'M32.9', 40, Decimal('0.4000'),
     'ANA positive suggests systemic lupus (low specificity)'),

    ('antinuclear antibod%', '8061-4', '>', Decimal('0.0'), None, None,
     '', 'M32.9', 40, Decimal('0.4000'),
     'Antinuclear antibody positive suggests autoimmune disease'),

    # --- RF / Rheumatoid Factor (LOINC 11572-5) ---
    ('rheumatoid factor%', '11572-5', '>', Decimal('20.0'), None, None,
     'IU/mL', 'M05.9', 40, Decimal('0.4500'),
     'Rheumatoid factor > 20 IU/mL suggests RA'),

    ('RF%', '11572-5', '>', Decimal('20.0'), None, None,
     'IU/mL', 'M05.9', 40, Decimal('0.4500'),
     'RF > 20 IU/mL suggests rheumatoid arthritis'),

    ('rheumatoid factor%', '11572-5', '>', Decimal('60.0'), None, None,
     'IU/mL', 'M05.9', 40, Decimal('0.6000'),
     'Rheumatoid factor > 60 = high titer (strong RA signal)'),

    # --- Anti-CCP (LOINC 53027-9) ---
    ('anti-CCP%', '53027-9', '>', Decimal('20.0'), None, None,
     'U/mL', 'M05.9', 40, Decimal('0.6500'),
     'Anti-CCP > 20 U/mL highly specific for rheumatoid arthritis'),

    ('anti-CCP%', '53027-9', '>', Decimal('60.0'), None, None,
     'U/mL', 'M05.9', 40, Decimal('0.8000'),
     'Anti-CCP > 60 = strong positive for RA'),

    ('cyclic citrullinated peptide%', '53027-9', '>', Decimal('20.0'), None, None,
     'U/mL', 'M05.9', 40, Decimal('0.6500'),
     'Cyclic citrullinated peptide antibody > 20 = RA'),

    ('CCP antibod%', '53027-9', '>', Decimal('20.0'), None, None,
     'U/mL', 'M05.9', 40, Decimal('0.6500'),
     'CCP antibody > 20 suggests RA'),

    # --- ESR (LOINC 4537-7) ---
    ('ESR%', '4537-7', '>', Decimal('50.0'), None, None,
     'mm/hr', 'M35.9', 40, Decimal('0.3500'),
     'ESR > 50 mm/hr suggests chronic inflammatory condition'),

    ('ESR%', '4537-7', '>', Decimal('100.0'), None, None,
     'mm/hr', 'M35.9', 40, Decimal('0.5000'),
     'ESR > 100 = significantly elevated (GCA, malignancy, infection)'),

    ('sed rate%', '4537-7', '>', Decimal('50.0'), None, None,
     'mm/hr', 'M35.9', 40, Decimal('0.3500'),
     'Sed rate > 50 suggests chronic inflammatory condition'),

    ('erythrocyte sedimentation rate%', '4537-7', '>', Decimal('50.0'), None, None,
     'mm/hr', 'M35.9', 40, Decimal('0.3500'),
     'Erythrocyte sedimentation rate > 50 suggests inflammation'),

    # --- CRP (LOINC 1988-5) ---
    ('CRP%', '1988-5', '>', Decimal('10.0'), None, None,
     'mg/L', 'M35.9', 40, Decimal('0.3500'),
     'CRP > 10 mg/L suggests chronic inflammatory condition'),

    ('CRP%', '1988-5', '>', Decimal('50.0'), None, None,
     'mg/L', 'M35.9', 40, Decimal('0.5000'),
     'CRP > 50 = significantly elevated (infection/severe inflammation)'),

    ('C-reactive protein%', '1988-5', '>', Decimal('10.0'), None, None,
     'mg/L', 'M35.9', 40, Decimal('0.3500'),
     'C-reactive protein > 10 suggests inflammatory condition'),

    ('hs-CRP%', '30522-7', '>', Decimal('3.0'), None, None,
     'mg/L', 'I25.10', 107, Decimal('0.3500'),
     'HS-CRP > 3 mg/L = high cardiovascular risk'),

    # --- Anti-dsDNA (LOINC 35659-2) ---
    ('anti-dsDNA%', '35659-2', '>', Decimal('0.0'), None, None,
     '', 'M32.9', 40, Decimal('0.7000'),
     'Anti-dsDNA positive = highly specific for SLE'),

    ('double stranded DNA antibod%', '35659-2', '>', Decimal('0.0'), None, None,
     '', 'M32.9', 40, Decimal('0.7000'),
     'Double stranded DNA antibody positive = SLE'),

    # --- Anti-Smith (LOINC 14076-4) ---
    ('anti-Smith%', '14076-4', '>', Decimal('0.0'), None, None,
     '', 'M32.9', 40, Decimal('0.8000'),
     'Anti-Smith antibody positive = highly specific for SLE'),

    # =========================================================================
    # CANCER MARKERS  (HCC 12)
    # =========================================================================

    # --- PSA (LOINC 2857-1) ---
    ('PSA%', '2857-1', '>', Decimal('10.0'), None, None,
     'ng/mL', 'C61', 12, Decimal('0.6000'),
     'PSA > 10 ng/mL raises suspicion for prostate cancer'),

    ('PSA%', '2857-1', '>', Decimal('20.0'), None, None,
     'ng/mL', 'C61', 12, Decimal('0.7500'),
     'PSA > 20 = high probability of prostate cancer'),

    ('PSA%', '2857-1', '>', Decimal('50.0'), None, None,
     'ng/mL', 'C61', 12, Decimal('0.8500'),
     'PSA > 50 = very high probability of advanced prostate cancer'),

    ('prostate specific antigen%', '2857-1', '>', Decimal('10.0'), None, None,
     'ng/mL', 'C61', 12, Decimal('0.6000'),
     'Prostate specific antigen > 10 suggests prostate cancer'),

    ('prostate specific antigen%', '2857-1', '>', Decimal('20.0'), None, None,
     'ng/mL', 'C61', 12, Decimal('0.7500'),
     'Prostate specific antigen > 20 = high prostate cancer probability'),

    # --- CA-125 (LOINC 10334-1) ---
    ('CA-125%', '10334-1', '>', Decimal('35.0'), None, None,
     'U/mL', 'C56.9', 12, Decimal('0.5000'),
     'CA-125 > 35 U/mL raises suspicion for ovarian cancer'),

    ('CA-125%', '10334-1', '>', Decimal('200.0'), None, None,
     'U/mL', 'C56.9', 12, Decimal('0.7000'),
     'CA-125 > 200 = high suspicion for ovarian cancer'),

    ('CA 125%', '10334-1', '>', Decimal('35.0'), None, None,
     'U/mL', 'C56.9', 12, Decimal('0.5000'),
     'CA 125 > 35 suggests ovarian cancer'),

    # --- CA 19-9 (LOINC 24108-3) ---
    ('CA 19-9%', '24108-3', '>', Decimal('37.0'), None, None,
     'U/mL', 'C25.9', 12, Decimal('0.5000'),
     'CA 19-9 > 37 U/mL raises suspicion for pancreatic cancer'),

    ('CA 19-9%', '24108-3', '>', Decimal('100.0'), None, None,
     'U/mL', 'C25.9', 12, Decimal('0.6500'),
     'CA 19-9 > 100 = high suspicion for pancreatic cancer'),

    ('CA19-9%', '24108-3', '>', Decimal('37.0'), None, None,
     'U/mL', 'C25.9', 12, Decimal('0.5000'),
     'CA19-9 > 37 suggests pancreatic cancer'),

    # --- CEA (LOINC 2039-6) ---
    ('CEA%', '2039-6', '>', Decimal('5.0'), None, None,
     'ng/mL', 'C18.9', 12, Decimal('0.4000'),
     'CEA > 5 ng/mL suggests GI malignancy (colon, pancreas)'),

    ('CEA%', '2039-6', '>', Decimal('20.0'), None, None,
     'ng/mL', 'C18.9', 12, Decimal('0.6000'),
     'CEA > 20 = highly suspicious for metastatic GI cancer'),

    ('carcinoembryonic antigen%', '2039-6', '>', Decimal('5.0'), None, None,
     'ng/mL', 'C18.9', 12, Decimal('0.4000'),
     'Carcinoembryonic antigen > 5 suggests GI malignancy'),

    # --- Beta-2 microglobulin (LOINC 1952-1) ---
    ('beta-2 microglobulin%', '1952-1', '>', Decimal('3.5'), None, None,
     'mg/L', 'C90.0', 12, Decimal('0.5000'),
     'Beta-2 microglobulin > 3.5 suggests myeloma/lymphoma'),

    ('B2M%', '1952-1', '>', Decimal('3.5'), None, None,
     'mg/L', 'C90.0', 12, Decimal('0.5000'),
     'B2M > 3.5 suggests multiple myeloma'),

    # --- LDH (LOINC 2532-0) -- as cancer/lymphoma marker ---
    ('LDH%', '2532-0', '>', Decimal('500.0'), None, None,
     'U/L', 'C85.9', 12, Decimal('0.4000'),
     'LDH > 500 suggests lymphoma or widespread malignancy'),

    ('lactate dehydrogenase%', '2532-0', '>', Decimal('500.0'), None, None,
     'U/L', 'C85.9', 12, Decimal('0.4000'),
     'Lactate dehydrogenase > 500 suggests lymphoma/malignancy'),

    # =========================================================================
    # HIV  (HCC 1)
    # =========================================================================

    # --- HIV viral load (LOINC 20447-9) ---
    ('HIV%viral load%', '20447-9', '>', Decimal('0.0'), None, None,
     'copies/mL', 'B20', 1, Decimal('0.9500'),
     'Detectable HIV viral load = HIV infection'),

    ('HIV%RNA%', '20447-9', '>', Decimal('0.0'), None, None,
     'copies/mL', 'B20', 1, Decimal('0.9500'),
     'Detectable HIV RNA = active HIV infection'),

    ('HIV-1%RNA%', '20447-9', '>', Decimal('0.0'), None, None,
     'copies/mL', 'B20', 1, Decimal('0.9500'),
     'HIV-1 RNA detectable = HIV infection'),

    ('HIV%quantitative%', '20447-9', '>', Decimal('0.0'), None, None,
     'copies/mL', 'B20', 1, Decimal('0.9500'),
     'HIV quantitative > 0 = active HIV'),

    # --- CD4 count (LOINC 24467-3) ---
    ('CD4%', '24467-3', '<', Decimal('200.0'), None, None,
     'cells/uL', 'B20', 1, Decimal('0.9000'),
     'CD4 < 200 cells/uL = AIDS-defining immunosuppression'),

    ('CD4%', '24467-3', '<', Decimal('500.0'), None, None,
     'cells/uL', 'B20', 1, Decimal('0.8000'),
     'CD4 < 500 = immunosuppression consistent with HIV'),

    ('CD4%', '24467-3', '<', Decimal('50.0'), None, None,
     'cells/uL', 'B20', 1, Decimal('0.9500'),
     'CD4 < 50 = severe AIDS (high OI risk)'),

    ('CD4%count%', '24467-3', '<', Decimal('200.0'), None, None,
     'cells/uL', 'B20', 1, Decimal('0.9000'),
     'CD4 count < 200 = AIDS'),

    ('CD4%count%', '24467-3', '<', Decimal('500.0'), None, None,
     'cells/uL', 'B20', 1, Decimal('0.8000'),
     'CD4 count < 500 suggests HIV'),

    ('T helper%', '24467-3', '<', Decimal('200.0'), None, None,
     'cells/uL', 'B20', 1, Decimal('0.9000'),
     'T helper cells < 200 = AIDS'),

    # =========================================================================
    # RESPIRATORY  (HCC 84, 111)
    # =========================================================================

    # --- FEV1/FVC ratio ---
    ('FEV1/FVC%', '', '<', Decimal('0.70'), None, None,
     '', 'J44.1', 111, Decimal('0.8500'),
     'FEV1/FVC ratio < 0.70 = obstructive pattern (COPD)'),

    ('FEV1%FVC%', '', '<', Decimal('0.70'), None, None,
     '', 'J44.1', 111, Decimal('0.8500'),
     'FEV1/FVC < 0.70 = COPD (obstructive airway disease)'),

    # --- FEV1 % predicted (LOINC 20150-9) ---
    ('FEV1%predicted%', '20150-9', '<', Decimal('50.0'), None, None,
     '%', 'J44.1', 111, Decimal('0.8500'),
     'FEV1 < 50% predicted = severe COPD (GOLD Stage III)'),

    ('FEV1%predicted%', '20150-9', '<', Decimal('30.0'), None, None,
     '%', 'J44.1', 111, Decimal('0.9000'),
     'FEV1 < 30% predicted = very severe COPD (GOLD Stage IV)'),

    ('FEV1%', '20150-9', '<', Decimal('50.0'), None, None,
     '%', 'J44.1', 111, Decimal('0.8000'),
     'FEV1 < 50% predicted suggests severe COPD'),

    ('FEV1%', '20150-9', '<', Decimal('80.0'), None, None,
     '%', 'J44.1', 111, Decimal('0.6500'),
     'FEV1 < 80% predicted = moderate COPD (GOLD Stage II)'),

    # --- ABG pCO2 (LOINC 2019-8) ---
    ('pCO2%', '2019-8', '>', Decimal('45.0'), None, None,
     'mmHg', 'J96.11', 84, Decimal('0.7000'),
     'pCO2 > 45 mmHg = hypercapnia (chronic respiratory failure)'),

    ('pCO2%', '2019-8', '>', Decimal('55.0'), None, None,
     'mmHg', 'J96.11', 84, Decimal('0.8000'),
     'pCO2 > 55 = significant hypercapnia (severe respiratory failure)'),

    ('carbon dioxide%arterial%', '2019-8', '>', Decimal('45.0'), None, None,
     'mmHg', 'J96.11', 84, Decimal('0.7000'),
     'Arterial CO2 > 45 = respiratory failure with hypercapnia'),

    ('CO2%arterial%', '2019-8', '>', Decimal('45.0'), None, None,
     'mmHg', 'J96.11', 84, Decimal('0.7000'),
     'Arterial CO2 > 45 mmHg = hypercapnic respiratory failure'),

    # --- ABG pO2 (LOINC 2703-7) ---
    ('pO2%', '2703-7', '<', Decimal('60.0'), None, None,
     'mmHg', 'J96.11', 84, Decimal('0.7500'),
     'pO2 < 60 mmHg = hypoxemia (respiratory failure)'),

    ('pO2%', '2703-7', '<', Decimal('50.0'), None, None,
     'mmHg', 'J96.11', 84, Decimal('0.8500'),
     'pO2 < 50 = severe hypoxemia'),

    ('oxygen%arterial%', '2703-7', '<', Decimal('60.0'), None, None,
     'mmHg', 'J96.11', 84, Decimal('0.7500'),
     'Arterial oxygen < 60 mmHg = respiratory failure'),

    ('PaO2%', '2703-7', '<', Decimal('60.0'), None, None,
     'mmHg', 'J96.11', 84, Decimal('0.7500'),
     'PaO2 < 60 = hypoxemia (respiratory failure)'),

    # --- Oxygen saturation (LOINC 20564-1) ---
    ('SpO2%', '20564-1', '<', Decimal('88.0'), None, None,
     '%', 'J96.11', 84, Decimal('0.7000'),
     'SpO2 < 88% = significant hypoxemia (O2 therapy indicated)'),

    ('oxygen saturation%', '20564-1', '<', Decimal('88.0'), None, None,
     '%', 'J96.11', 84, Decimal('0.7000'),
     'Oxygen saturation < 88% = respiratory failure'),

    # =========================================================================
    # ENDOCRINE  (HCC 23)
    # =========================================================================

    # --- Cortisol AM (LOINC 2143-6) ---
    ('cortisol%', '2143-6', '>', Decimal('25.0'), None, None,
     'ug/dL', 'E24.9', 23, Decimal('0.6000'),
     'AM cortisol > 25 ug/dL suggests Cushing syndrome'),

    ('cortisol%', '2143-6', '<', Decimal('3.0'), None, None,
     'ug/dL', 'E27.1', 23, Decimal('0.7000'),
     'AM cortisol < 3 ug/dL suggests adrenal insufficiency (Addison)'),

    ('AM cortisol%', '2143-6', '>', Decimal('25.0'), None, None,
     'ug/dL', 'E24.9', 23, Decimal('0.6000'),
     'AM cortisol > 25 suggests hypercortisolism'),

    ('AM cortisol%', '2143-6', '<', Decimal('3.0'), None, None,
     'ug/dL', 'E27.1', 23, Decimal('0.7000'),
     'AM cortisol < 3 suggests Addison disease'),

    ('morning cortisol%', '2143-6', '>', Decimal('25.0'), None, None,
     'ug/dL', 'E24.9', 23, Decimal('0.6000'),
     'Morning cortisol > 25 suggests Cushing'),

    ('morning cortisol%', '2143-6', '<', Decimal('3.0'), None, None,
     'ug/dL', 'E27.1', 23, Decimal('0.7000'),
     'Morning cortisol < 3 = adrenal insufficiency'),

    # --- PTH (LOINC 2731-8) ---
    ('PTH%', '2731-8', '>', Decimal('65.0'), None, None,
     'pg/mL', 'E21.0', 23, Decimal('0.6500'),
     'PTH > 65 pg/mL suggests hyperparathyroidism'),

    ('PTH%', '2731-8', '>', Decimal('100.0'), None, None,
     'pg/mL', 'E21.0', 23, Decimal('0.7500'),
     'PTH > 100 = significant hyperparathyroidism'),

    ('parathyroid hormone%', '2731-8', '>', Decimal('65.0'), None, None,
     'pg/mL', 'E21.0', 23, Decimal('0.6500'),
     'Parathyroid hormone > 65 suggests hyperparathyroidism'),

    ('parathyroid hormone%', '2731-8', '>', Decimal('100.0'), None, None,
     'pg/mL', 'E21.0', 23, Decimal('0.7500'),
     'Parathyroid hormone > 100 = hyperparathyroidism'),

    ('intact PTH%', '2731-8', '>', Decimal('65.0'), None, None,
     'pg/mL', 'E21.0', 23, Decimal('0.6500'),
     'Intact PTH > 65 pg/mL suggests hyperparathyroidism'),

    ('PTH%', '2731-8', '<', Decimal('10.0'), None, None,
     'pg/mL', 'E20.9', 23, Decimal('0.6000'),
     'PTH < 10 suggests hypoparathyroidism'),

    # --- ACTH (LOINC 2141-0) ---
    ('ACTH%', '2141-0', '>', Decimal('60.0'), None, None,
     'pg/mL', 'E24.0', 23, Decimal('0.5500'),
     'ACTH > 60 pg/mL suggests Cushing disease (pituitary)'),

    ('ACTH%', '2141-0', '<', Decimal('5.0'), None, None,
     'pg/mL', 'E27.1', 23, Decimal('0.5500'),
     'ACTH < 5 = low (secondary adrenal insufficiency)'),

    # --- IGF-1 (LOINC 2484-4) ---
    ('IGF-1%', '2484-4', '>', Decimal('300.0'), None, None,
     'ng/mL', 'E22.0', 23, Decimal('0.5500'),
     'IGF-1 elevated suggests acromegaly'),

    # --- Prolactin (LOINC 2842-3) ---
    ('prolactin%', '2842-3', '>', Decimal('100.0'), None, None,
     'ng/mL', 'E22.1', 23, Decimal('0.6000'),
     'Prolactin > 100 suggests prolactinoma'),

    # =========================================================================
    # ADDITIONAL DIABETES COMPLICATIONS
    # =========================================================================

    # --- Insulin (LOINC 2484-4 / 20448-7) -- insulin resistance ---
    ('insulin%fasting%', '20448-7', '>', Decimal('25.0'), None, None,
     'uIU/mL', 'E11.9', 19, Decimal('0.6000'),
     'Fasting insulin > 25 suggests insulin resistance / T2DM'),

    # --- GAD65 antibodies (LOINC 56718-0) ---
    ('GAD65%', '56718-0', '>', Decimal('5.0'), None, None,
     'U/mL', 'E10.9', 19, Decimal('0.7500'),
     'GAD65 antibody positive suggests Type 1 / LADA diabetes'),

    ('GAD antibod%', '56718-0', '>', Decimal('5.0'), None, None,
     'U/mL', 'E10.9', 19, Decimal('0.7500'),
     'GAD antibody positive suggests autoimmune diabetes'),

    # =========================================================================
    # ADDITIONAL CKD MARKERS
    # =========================================================================

    # --- Urine specific gravity ---
    ('urine specific gravity%', '2965-2', '<', Decimal('1.005'), None, None,
     '', 'N18.3', 138, Decimal('0.4000'),
     'Low urine specific gravity suggests impaired concentrating ability (CKD)'),

    # --- Bicarbonate (LOINC 1963-8) ---
    ('bicarbonate%', '1963-8', '<', Decimal('18.0'), None, None,
     'mEq/L', 'N18.4', 137, Decimal('0.5000'),
     'Bicarbonate < 18 = metabolic acidosis (common in CKD Stage 4)'),

    ('CO2%', '1963-8', '<', Decimal('18.0'), None, None,
     'mEq/L', 'N18.4', 137, Decimal('0.5000'),
     'CO2 < 18 = metabolic acidosis in CKD'),

    ('HCO3%', '1963-8', '<', Decimal('18.0'), None, None,
     'mEq/L', 'N18.4', 137, Decimal('0.5000'),
     'HCO3 < 18 = metabolic acidosis (CKD)'),

    # =========================================================================
    # ADDITIONAL CARDIAC MARKERS
    # =========================================================================

    # --- Homocysteine (LOINC 13965-9) ---
    ('homocysteine%', '13965-9', '>', Decimal('15.0'), None, None,
     'umol/L', 'I70.0', 107, Decimal('0.4000'),
     'Homocysteine > 15 = hyperhomocysteinemia (CVD risk factor)'),

    # --- CK-MB (LOINC 13969-1) ---
    ('CK-MB%', '13969-1', '>', Decimal('5.0'), None, None,
     'ng/mL', 'I21.9', 86, Decimal('0.7000'),
     'CK-MB > 5 ng/mL suggests myocardial injury/AMI'),

    ('creatine kinase MB%', '13969-1', '>', Decimal('5.0'), None, None,
     'ng/mL', 'I21.9', 86, Decimal('0.7000'),
     'Creatine kinase MB > 5 suggests AMI'),

    # =========================================================================
    # ADDITIONAL LIVER / PANCREAS
    # =========================================================================

    # --- Lipase (LOINC 3040-3) ---
    ('lipase%', '3040-3', '>', Decimal('180.0'), None, None,
     'U/L', 'K85.9', 29, Decimal('0.7500'),
     'Lipase > 3x ULN (>180) suggests acute pancreatitis'),

    ('lipase%', '3040-3', '>', Decimal('300.0'), None, None,
     'U/L', 'K85.9', 29, Decimal('0.8500'),
     'Lipase > 5x ULN = high probability acute pancreatitis'),

    # --- Amylase (LOINC 1798-8) ---
    ('amylase%', '1798-8', '>', Decimal('300.0'), None, None,
     'U/L', 'K85.9', 29, Decimal('0.7000'),
     'Amylase > 3x ULN suggests acute pancreatitis'),

    # =========================================================================
    # ADDITIONAL AUTOIMMUNE MARKERS
    # =========================================================================

    # --- ANCA (LOINC 17356-7) ---
    ('ANCA%', '17356-7', '>', Decimal('0.0'), None, None,
     '', 'M31.3', 40, Decimal('0.5500'),
     'ANCA positive suggests granulomatosis with polyangiitis'),

    ('c-ANCA%', '17356-7', '>', Decimal('0.0'), None, None,
     '', 'M31.3', 40, Decimal('0.6000'),
     'c-ANCA positive = GPA (Wegener granulomatosis)'),

    ('p-ANCA%', '33632-1', '>', Decimal('0.0'), None, None,
     '', 'M31.7', 40, Decimal('0.5500'),
     'p-ANCA positive suggests microscopic polyangiitis'),

    # --- Complement C3/C4 (LOINC 4485-9 / 4498-2) ---
    ('complement C3%', '4485-9', '<', Decimal('80.0'), None, None,
     'mg/dL', 'M32.9', 40, Decimal('0.5000'),
     'Low C3 suggests active lupus nephritis'),

    ('complement C4%', '4498-2', '<', Decimal('15.0'), None, None,
     'mg/dL', 'M32.9', 40, Decimal('0.5000'),
     'Low C4 suggests active SLE'),

    ('C3%', '4485-9', '<', Decimal('80.0'), None, None,
     'mg/dL', 'M32.9', 40, Decimal('0.5000'),
     'C3 < 80 mg/dL suggests active lupus'),

    ('C4%', '4498-2', '<', Decimal('15.0'), None, None,
     'mg/dL', 'M32.9', 40, Decimal('0.5000'),
     'C4 < 15 suggests active SLE or complement deficiency'),

    # =========================================================================
    # ADDITIONAL HEMATOLOGY / ONCOLOGY
    # =========================================================================

    # --- Absolute neutrophil count (ANC) ---
    ('ANC%', '26499-4', '<', Decimal('500.0'), None, None,
     'cells/uL', 'D70.9', 48, Decimal('0.8000'),
     'ANC < 500 = severe neutropenia (infection risk)'),

    ('absolute neutrophil%', '26499-4', '<', Decimal('1000.0'), None, None,
     'cells/uL', 'D70.9', 48, Decimal('0.6500'),
     'ANC < 1000 = neutropenia'),

    # --- Serum protein electrophoresis / M-spike ---
    ('M-spike%', '48347-9', '>', Decimal('0.0'), None, None,
     'g/dL', 'C90.0', 12, Decimal('0.7000'),
     'M-spike detected on SPEP suggests multiple myeloma'),

    ('monoclonal protein%', '48347-9', '>', Decimal('0.0'), None, None,
     'g/dL', 'C90.0', 12, Decimal('0.7000'),
     'Monoclonal protein detected suggests myeloma/MGUS'),

    # --- Free light chains (LOINC 33944-0 / 33945-7) ---
    ('kappa free light chain%', '33944-0', '>', Decimal('19.4'), None, None,
     'mg/L', 'C90.0', 12, Decimal('0.5500'),
     'Elevated kappa free light chain suggests myeloma'),

    ('lambda free light chain%', '33945-7', '>', Decimal('26.3'), None, None,
     'mg/L', 'C90.0', 12, Decimal('0.5500'),
     'Elevated lambda free light chain suggests myeloma'),

    # =========================================================================
    # ADDITIONAL METABOLIC PANELS
    # =========================================================================

    # --- Chloride (LOINC 2075-0) ---
    ('chloride%', '2075-0', '>', Decimal('110.0'), None, None,
     'mEq/L', 'E87.8', 23, Decimal('0.4000'),
     'Chloride > 110 = hyperchloremia (metabolic acidosis)'),

    ('chloride%', '2075-0', '<', Decimal('95.0'), None, None,
     'mEq/L', 'E87.8', 23, Decimal('0.4000'),
     'Chloride < 95 = hypochloremia (metabolic alkalosis, vomiting)'),

    # --- Anion gap ---
    ('anion gap%', '33037-3', '>', Decimal('16.0'), None, None,
     'mEq/L', 'E87.2', 23, Decimal('0.4500'),
     'Anion gap > 16 = high anion gap metabolic acidosis'),

    # --- Lactic acid (LOINC 2524-7) ---
    ('lactic acid%', '2524-7', '>', Decimal('4.0'), None, None,
     'mmol/L', 'E87.2', 23, Decimal('0.5000'),
     'Lactic acid > 4 mmol/L = lactic acidosis (sepsis, shock)'),

    ('lactate%', '2524-7', '>', Decimal('4.0'), None, None,
     'mmol/L', 'E87.2', 23, Decimal('0.5000'),
     'Lactate > 4 = lactic acidosis'),

    # =========================================================================
    # ADDITIONAL INFECTIOUS DISEASE
    # =========================================================================

    # --- Procalcitonin (LOINC 33959-8) ---
    ('procalcitonin%', '33959-8', '>', Decimal('0.5'), None, None,
     'ng/mL', 'A41.9', 2, Decimal('0.5500'),
     'Procalcitonin > 0.5 ng/mL suggests bacterial sepsis'),

    ('procalcitonin%', '33959-8', '>', Decimal('2.0'), None, None,
     'ng/mL', 'A41.9', 2, Decimal('0.7000'),
     'Procalcitonin > 2.0 = high probability of sepsis'),

    ('PCT%', '33959-8', '>', Decimal('0.5'), None, None,
     'ng/mL', 'A41.9', 2, Decimal('0.5500'),
     'PCT > 0.5 suggests bacterial sepsis'),

    # =========================================================================
    # MYELOPROLIFERATIVE / HEMATOLOGIC MALIGNANCY
    # =========================================================================

    # --- JAK2 mutation ---
    ('JAK2%', '53932-0', '>', Decimal('0.0'), None, None,
     '', 'D47.1', 48, Decimal('0.8000'),
     'JAK2 V617F positive suggests myeloproliferative neoplasm'),

    # --- BCR-ABL ---
    ('BCR-ABL%', '11553-5', '>', Decimal('0.0'), None, None,
     '', 'C92.1', 12, Decimal('0.9000'),
     'BCR-ABL positive = chronic myeloid leukemia'),

    # =========================================================================
    # NUTRITION / MALABSORPTION
    # =========================================================================

    # --- Prealbumin (LOINC 14338-8) ---
    ('prealbumin%', '14338-8', '<', Decimal('15.0'), None, None,
     'mg/dL', 'E46', 0, Decimal('0.5000'),
     'Prealbumin < 15 mg/dL = protein-calorie malnutrition'),

    ('transthyretin%', '14338-8', '<', Decimal('15.0'), None, None,
     'mg/dL', 'E46', 0, Decimal('0.5000'),
     'Transthyretin < 15 = malnutrition marker'),

    # --- Total protein (LOINC 2885-2) ---
    ('total protein%', '2885-2', '<', Decimal('6.0'), None, None,
     'g/dL', 'E46', 0, Decimal('0.4000'),
     'Total protein < 6 g/dL = hypoproteinemia (malnutrition or liver disease)'),

    # =========================================================================
    # ADDITIONAL RENAL TRANSPLANT / IMMUNOSUPPRESSION
    # =========================================================================

    # --- Tacrolimus level (LOINC 4049-3) ---
    ('tacrolimus%', '4049-3', '>', Decimal('20.0'), None, None,
     'ng/mL', 'Z94.0', 186, Decimal('0.7000'),
     'Tacrolimus level > 20 = supratherapeutic (transplant patient)'),

    ('FK506%', '4049-3', '>', Decimal('20.0'), None, None,
     'ng/mL', 'Z94.0', 186, Decimal('0.7000'),
     'FK506 level > 20 = supratherapeutic (transplant patient)'),

    # --- Cyclosporine level (LOINC 3520-4) ---
    ('cyclosporine%', '3520-4', '>', Decimal('400.0'), None, None,
     'ng/mL', 'Z94.0', 186, Decimal('0.7000'),
     'Cyclosporine level > 400 = supratherapeutic (transplant)'),

    # =========================================================================
    # BONE / MINERAL METABOLISM
    # =========================================================================

    # --- Calcium elevated (LOINC 17861-6) ---
    ('calcium%', '17861-6', '>', Decimal('10.5'), None, None,
     'mg/dL', 'E83.52', 23, Decimal('0.5500'),
     'Calcium > 10.5 = hypercalcemia (hyperparathyroidism, malignancy)'),

    ('calcium%', '17861-6', '>', Decimal('12.0'), None, None,
     'mg/dL', 'E83.52', 23, Decimal('0.7000'),
     'Calcium > 12 = moderate hypercalcemia'),

    ('calcium%', '17861-6', '>', Decimal('14.0'), None, None,
     'mg/dL', 'E83.52', 23, Decimal('0.8000'),
     'Calcium > 14 = severe/critical hypercalcemia'),

    # --- 25-OH Vitamin D and PTH in combination context ---
    ('25-hydroxy vitamin D%', '1989-3', '<', Decimal('10.0'), None, None,
     'ng/mL', 'E55.0', 0, Decimal('0.7000'),
     '25-OH Vitamin D < 10 = severe deficiency (rickets/osteomalacia risk)'),

    # =========================================================================
    # PANCREATIC FUNCTION
    # =========================================================================

    # --- Elastase (LOINC 14944-3) ---
    ('fecal elastase%', '14944-3', '<', Decimal('200.0'), None, None,
     'ug/g', 'K86.1', 29, Decimal('0.7000'),
     'Fecal elastase < 200 = pancreatic exocrine insufficiency'),

    ('pancreatic elastase%', '14944-3', '<', Decimal('100.0'), None, None,
     'ug/g', 'K86.1', 29, Decimal('0.8000'),
     'Pancreatic elastase < 100 = severe exocrine insufficiency'),

    # =========================================================================
    # HEART FAILURE -- ADDITIONAL VARIANTS
    # =========================================================================

    # --- Galectin-3 (LOINC 62302-9) ---
    ('galectin-3%', '62302-9', '>', Decimal('25.8'), None, None,
     'ng/mL', 'I50.9', 85, Decimal('0.6000'),
     'Galectin-3 > 25.8 = elevated (HF prognosis marker)'),

    # --- ST2 (LOINC 56767-7) ---
    ('ST2%', '56767-7', '>', Decimal('35.0'), None, None,
     'ng/mL', 'I50.9', 85, Decimal('0.6000'),
     'Soluble ST2 > 35 ng/mL = elevated (HF risk stratification)'),

    ('sST2%', '56767-7', '>', Decimal('35.0'), None, None,
     'ng/mL', 'I50.9', 85, Decimal('0.6000'),
     'sST2 > 35 = heart failure risk marker'),

]


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    log.info("Connecting to raf_intelligence database ...")
    try:
        cnx = mysql.connector.connect(**DB_CONFIG)
        cur = cnx.cursor(dictionary=True)
        log.info("Connected to %s:%s", DB_CONFIG["host"], DB_CONFIG["port"])
    except MySQLError as exc:
        log.error("Database connection failed: %s", exc)
        return 1

    # ------------------------------------------------------------------
    # 1.  Ensure the table exists (it should from schema.sql)
    # ------------------------------------------------------------------
    try:
        cur.execute("SELECT COUNT(*) AS cnt FROM raf_lab_signals")
        existing_count = cur.fetchone()["cnt"]
        log.info("Table raf_lab_signals currently has %d rows.", existing_count)
    except MySQLError as exc:
        log.error("Table raf_lab_signals does not exist: %s", exc)
        log.error("Run the schema migration first (database/schema.sql).")
        cur.close()
        cnx.close()
        return 1

    # ------------------------------------------------------------------
    # 2.  Load existing dedup keys:
    #     (lab_name_pattern, lab_loinc_code, threshold_operator,
    #      threshold_value, suspect_icd10)
    #     for duplicate detection (case-insensitive pattern)
    # ------------------------------------------------------------------
    cur.execute("""
        SELECT LOWER(lab_name_pattern) AS pat,
               COALESCE(lab_loinc_code, '') AS loinc,
               threshold_operator AS op,
               threshold_value AS val,
               suspect_icd10 AS icd
        FROM raf_lab_signals
    """)
    existing_keys: set[tuple] = set()
    for row in cur.fetchall():
        # Normalize threshold_value to string for consistent comparison
        val_str = str(row["val"]) if row["val"] is not None else "BETWEEN"
        existing_keys.add((row["pat"], row["loinc"], row["op"], val_str, row["icd"]))

    log.info("Loaded %d existing dedup keys.", len(existing_keys))

    # ------------------------------------------------------------------
    # 3.  Insert new signals
    # ------------------------------------------------------------------
    INSERT_SQL = """
        INSERT INTO raf_lab_signals
            (lab_name_pattern, lab_loinc_code, threshold_operator,
             threshold_value, threshold_low, threshold_high,
             threshold_unit, suspect_icd10, suspect_hcc,
             confidence_base, notes, is_active)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 1)
    """

    inserted = 0
    skipped = 0
    errors = 0

    for row_data in SIGNALS:
        (pattern, loinc, operator, threshold_val, threshold_low,
         threshold_high, unit, icd10, hcc, confidence, notes) = row_data

        # Build the dedup key
        val_str = str(threshold_val) if threshold_val is not None else "BETWEEN"
        key = (pattern.lower(), loinc, operator, val_str, icd10)

        if key in existing_keys:
            skipped += 1
            continue

        try:
            cur.execute(INSERT_SQL, (
                pattern, loinc if loinc else None, operator,
                threshold_val, threshold_low, threshold_high,
                unit, icd10, hcc, confidence, notes
            ))
            existing_keys.add(key)
            inserted += 1
        except MySQLError as exc:
            log.warning("Failed to insert pattern=%r loinc=%s op=%s val=%s icd10=%s: %s",
                        pattern, loinc, operator, threshold_val, icd10, exc)
            errors += 1

    cnx.commit()

    # ------------------------------------------------------------------
    # 4.  Report
    # ------------------------------------------------------------------
    cur.execute("SELECT COUNT(*) AS cnt FROM raf_lab_signals")
    final_count = cur.fetchone()["cnt"]

    log.info("=" * 60)
    log.info("Seed complete.")
    log.info("  Signals in script:      %d", len(SIGNALS))
    log.info("  Skipped (duplicates):    %d", skipped)
    log.info("  Inserted:                %d", inserted)
    log.info("  Errors:                  %d", errors)
    log.info("  Total rows in table:     %d  (was %d)", final_count, existing_count)
    log.info("  Expansion factor:        %.1fx", final_count / max(existing_count, 1))
    log.info("=" * 60)

    cur.close()
    cnx.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
