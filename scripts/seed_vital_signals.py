#!/usr/bin/env python3
"""
seed_vital_signals.py
----------------------
Creates and seeds the raf_vital_signals table with vital sign threshold
rules to ICD-10/HCC mappings for the RAF Intelligence suspect detection
engine.

Covers clinically significant vital sign abnormalities that suggest
undocumented chronic conditions:

    BMI (obesity, malnutrition), Blood Pressure (hypertension, crisis),
    Oxygen Saturation (respiratory failure, COPD), Heart Rate (AFib,
    arrhythmia), Weight Loss (cancer, malnutrition), Temperature
    (chronic infection), Respiratory Rate (respiratory failure)

Data sources:
    - WHO/AHA clinical thresholds and guidelines
    - CMS-HCC V24 / V28 crosswalk mappings
    - Standard clinical vital sign interpretation references

Idempotent: checks existing (vital_name, threshold_operator,
threshold_value, suspect_icd10) tuples before inserting.
Safe to run multiple times.

Usage:
    python scripts/seed_vital_signals.py

    # With custom DB connection:
    RAF_DB_HOST=10.1.0.204 RAF_DB_PORT=3306 RAF_DB_USER=root \\
      RAF_DB_PASSWORD=secret python scripts/seed_vital_signals.py
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
CREATE TABLE IF NOT EXISTS raf_vital_signals (
    id                  INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    vital_name          VARCHAR(50)   NOT NULL,
    threshold_operator  ENUM('<','<=','>','>=','=','!=','BETWEEN') NOT NULL,
    threshold_value     DECIMAL(12,4) NULL,
    threshold_low       DECIMAL(12,4) NULL,
    threshold_high      DECIMAL(12,4) NULL,
    threshold_unit      VARCHAR(30)   NOT NULL DEFAULT '',
    suspect_icd10       VARCHAR(10)   NOT NULL,
    suspect_hcc         SMALLINT UNSIGNED NOT NULL,
    confidence_base     DECIMAL(5,4)  NOT NULL DEFAULT 0.5000,
    notes               VARCHAR(500)  NOT NULL DEFAULT '',
    is_active           TINYINT(1)    NOT NULL DEFAULT 1,
    created_at          DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at          DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uq_vital (vital_name, threshold_operator, threshold_value, suspect_icd10),
    INDEX idx_vital_name (vital_name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
"""

# ---------------------------------------------------------------------------
# Signal Data
#
# Each tuple:
#   (vital_name, threshold_operator, threshold_value, threshold_low,
#    threshold_high, threshold_unit, suspect_icd10, suspect_hcc,
#    confidence_base, notes)
#
# For single-threshold operators (<, <=, >, >=, =, !=):
#   - threshold_value is set, threshold_low/high are None
#
# For BETWEEN operator:
#   - threshold_value is None, threshold_low/high are set
#
# HCC numbers follow the CMS-HCC V24/V28 model.
# Confidence reflects specificity of the vital sign abnormality for
# the suspected condition.
# ---------------------------------------------------------------------------

SIGNALS: list[tuple] = [

    # =========================================================================
    # BMI (BODY MASS INDEX)
    # =========================================================================

    # --- Morbid Obesity ---
    ('BMI', '>=', Decimal('40.0000'), None, None,
     'kg/m2', 'E66.01', 22, Decimal('0.9000'),
     'BMI >= 40 diagnostic for morbid obesity (Class III)'),

    ('BMI', 'BETWEEN', None, Decimal('35.0000'), Decimal('39.9999'),
     'kg/m2', 'E66.01', 22, Decimal('0.5500'),
     'BMI 35.0-39.9 suggests morbid obesity if comorbidity present (Class II)'),

    ('BMI', 'BETWEEN', None, Decimal('30.0000'), Decimal('34.9999'),
     'kg/m2', 'E66.9', 0, Decimal('0.5000'),
     'BMI 30.0-34.9 indicates obesity (Class I) — no HCC impact alone'),

    # --- Underweight / Malnutrition ---
    ('BMI', '<', Decimal('18.5000'), None, None,
     'kg/m2', 'R63.6', 21, Decimal('0.4500'),
     'BMI < 18.5 underweight — screen for malnutrition'),

    ('BMI', '<', Decimal('18.5000'), None, None,
     'kg/m2', 'E46', 21, Decimal('0.4500'),
     'BMI < 18.5 — protein-calorie malnutrition screen'),

    ('BMI', '<', Decimal('16.0000'), None, None,
     'kg/m2', 'E43', 21, Decimal('0.7000'),
     'BMI < 16 — severe protein-calorie malnutrition (marasmus)'),

    ('BMI', '<', Decimal('16.0000'), None, None,
     'kg/m2', 'E41', 21, Decimal('0.6500'),
     'BMI < 16 — nutritional marasmus screen'),

    ('BMI', 'BETWEEN', None, Decimal('16.0000'), Decimal('16.9999'),
     'kg/m2', 'E44.0', 21, Decimal('0.5500'),
     'BMI 16.0-16.9 — moderate protein-calorie malnutrition'),

    ('BMI', 'BETWEEN', None, Decimal('17.0000'), Decimal('18.4999'),
     'kg/m2', 'E44.1', 21, Decimal('0.4000'),
     'BMI 17.0-18.4 — mild protein-calorie malnutrition'),

    # =========================================================================
    # BLOOD PRESSURE (SYSTOLIC)
    # =========================================================================

    ('systolic_bp', '>=', Decimal('180.0000'), None, None,
     'mmHg', 'I16.0', 0, Decimal('0.7000'),
     'Systolic BP >= 180 — hypertensive crisis/urgency'),

    ('systolic_bp', '>=', Decimal('180.0000'), None, None,
     'mmHg', 'I16.1', 0, Decimal('0.6000'),
     'Systolic BP >= 180 — hypertensive emergency screen'),

    ('systolic_bp', 'BETWEEN', None, Decimal('160.0000'), Decimal('179.9999'),
     'mmHg', 'I10', 0, Decimal('0.5500'),
     'Systolic BP 160-179 — Stage 2 hypertension'),

    ('systolic_bp', 'BETWEEN', None, Decimal('140.0000'), Decimal('159.9999'),
     'mmHg', 'I10', 0, Decimal('0.4000'),
     'Systolic BP 140-159 — Stage 1 hypertension'),

    ('systolic_bp', 'BETWEEN', None, Decimal('130.0000'), Decimal('139.9999'),
     'mmHg', 'I10', 0, Decimal('0.2500'),
     'Systolic BP 130-139 — elevated BP (per ACC/AHA 2017 guidelines)'),

    # =========================================================================
    # BLOOD PRESSURE (DIASTOLIC)
    # =========================================================================

    ('diastolic_bp', '>=', Decimal('120.0000'), None, None,
     'mmHg', 'I16.0', 0, Decimal('0.7500'),
     'Diastolic BP >= 120 — hypertensive crisis'),

    ('diastolic_bp', '>=', Decimal('120.0000'), None, None,
     'mmHg', 'I16.1', 0, Decimal('0.6500'),
     'Diastolic BP >= 120 — hypertensive emergency screen'),

    ('diastolic_bp', 'BETWEEN', None, Decimal('100.0000'), Decimal('119.9999'),
     'mmHg', 'I10', 0, Decimal('0.5000'),
     'Diastolic BP 100-119 — Stage 2 hypertension'),

    ('diastolic_bp', 'BETWEEN', None, Decimal('90.0000'), Decimal('99.9999'),
     'mmHg', 'I10', 0, Decimal('0.4000'),
     'Diastolic BP 90-99 — Stage 1 hypertension'),

    # =========================================================================
    # OXYGEN SATURATION (SpO2)
    # =========================================================================

    ('spo2', '<', Decimal('88.0000'), None, None,
     '%', 'J96.11', 84, Decimal('0.7500'),
     'SpO2 < 88% — chronic respiratory failure (meets O2 qualification)'),

    ('spo2', '<', Decimal('88.0000'), None, None,
     '%', 'J96.10', 84, Decimal('0.6500'),
     'SpO2 < 88% — respiratory failure, unspecified chronicity'),

    ('spo2', 'BETWEEN', None, Decimal('88.0000'), Decimal('89.9999'),
     '%', 'J96.11', 84, Decimal('0.6000'),
     'SpO2 88-89% — borderline respiratory failure'),

    ('spo2', 'BETWEEN', None, Decimal('88.0000'), Decimal('92.0000'),
     '%', 'J44.1', 111, Decimal('0.5000'),
     'SpO2 88-92% on room air — screen for COPD/chronic lung disease'),

    ('spo2', 'BETWEEN', None, Decimal('90.0000'), Decimal('92.0000'),
     '%', 'J96.11', 84, Decimal('0.4500'),
     'SpO2 90-92% — mild hypoxemia, chronic resp failure screen'),

    ('spo2', '<', Decimal('90.0000'), None, None,
     '%', 'J96.11', 84, Decimal('0.6000'),
     'SpO2 < 90% — significant hypoxemia, respiratory failure'),

    ('spo2', '<', Decimal('85.0000'), None, None,
     '%', 'J96.11', 84, Decimal('0.8500'),
     'SpO2 < 85% — severe hypoxemia, definitive respiratory failure'),

    # =========================================================================
    # HEART RATE
    # =========================================================================

    # --- Tachycardia ---
    ('heart_rate', '>', Decimal('100.0000'), None, None,
     'bpm', 'R00.0', 96, Decimal('0.3500'),
     'HR > 100 — tachycardia, screen for AFib or other arrhythmia'),

    ('heart_rate', '>', Decimal('100.0000'), None, None,
     'bpm', 'I48.91', 96, Decimal('0.3500'),
     'HR > 100 persistent — screen for atrial fibrillation'),

    ('heart_rate', '>', Decimal('110.0000'), None, None,
     'bpm', 'I48.91', 96, Decimal('0.4000'),
     'HR > 110 — moderate tachycardia, increased AFib suspicion'),

    ('heart_rate', '>', Decimal('120.0000'), None, None,
     'bpm', 'I48.91', 96, Decimal('0.4500'),
     'HR > 120 — significant tachycardia, AFib likely if persistent'),

    ('heart_rate', '>', Decimal('130.0000'), None, None,
     'bpm', 'I48.91', 96, Decimal('0.5000'),
     'HR > 130 — marked tachycardia, high AFib/arrhythmia probability'),

    ('heart_rate', '>', Decimal('150.0000'), None, None,
     'bpm', 'I48.91', 96, Decimal('0.6000'),
     'HR > 150 — severe tachycardia, very high arrhythmia probability'),

    # --- Bradycardia ---
    ('heart_rate', '<', Decimal('50.0000'), None, None,
     'bpm', 'R00.1', 0, Decimal('0.3500'),
     'HR < 50 — bradycardia, screen for conduction disorders'),

    ('heart_rate', '<', Decimal('50.0000'), None, None,
     'bpm', 'I44.1', 96, Decimal('0.3000'),
     'HR < 50 — screen for AV block second degree'),

    ('heart_rate', '<', Decimal('45.0000'), None, None,
     'bpm', 'I44.2', 96, Decimal('0.4000'),
     'HR < 45 — significant bradycardia, screen for complete heart block'),

    ('heart_rate', '<', Decimal('40.0000'), None, None,
     'bpm', 'I44.2', 96, Decimal('0.5000'),
     'HR < 40 — severe bradycardia, high probability complete heart block'),

    # --- Irregular rhythm ---
    ('heart_rate_irregular', '=', Decimal('1.0000'), None, None,
     'flag', 'I48.91', 96, Decimal('0.4500'),
     'Irregular heart rhythm documented — screen for atrial fibrillation'),

    ('heart_rate_irregular', '=', Decimal('1.0000'), None, None,
     'flag', 'I49.9', 96, Decimal('0.3500'),
     'Irregular heart rhythm — cardiac arrhythmia unspecified'),

    # =========================================================================
    # WEIGHT LOSS
    # =========================================================================

    ('weight_loss_pct_6mo', '>', Decimal('10.0000'), None, None,
     '%', 'R63.4', 21, Decimal('0.5000'),
     'Weight loss > 10% in 6 months — screen for cancer/malnutrition'),

    ('weight_loss_pct_6mo', '>', Decimal('10.0000'), None, None,
     '%', 'E46', 21, Decimal('0.4500'),
     'Weight loss > 10% in 6 months — malnutrition screen'),

    ('weight_loss_pct_6mo', '>', Decimal('10.0000'), None, None,
     '%', 'C80.1', 12, Decimal('0.3000'),
     'Weight loss > 10% in 6 months — screen for occult malignancy'),

    ('weight_loss_pct_6mo', '>', Decimal('15.0000'), None, None,
     '%', 'E43', 21, Decimal('0.6000'),
     'Weight loss > 15% in 6 months — severe malnutrition signal'),

    ('weight_loss_pct_6mo', '>', Decimal('20.0000'), None, None,
     '%', 'E43', 21, Decimal('0.7500'),
     'Weight loss > 20% in 6 months — severe protein-calorie malnutrition'),

    ('weight_loss_pct_1mo', '>', Decimal('5.0000'), None, None,
     '%', 'R63.4', 21, Decimal('0.5500'),
     'Weight loss > 5% in 1 month — significant unintentional weight loss'),

    ('weight_loss_pct_1mo', '>', Decimal('5.0000'), None, None,
     '%', 'E46', 21, Decimal('0.5000'),
     'Weight loss > 5% in 1 month — malnutrition screen'),

    ('weight_loss_pct_1mo', '>', Decimal('10.0000'), None, None,
     '%', 'E43', 21, Decimal('0.7000'),
     'Weight loss > 10% in 1 month — severe malnutrition probable'),

    # =========================================================================
    # TEMPERATURE
    # =========================================================================

    ('temperature', '>', Decimal('38.3000'), None, None,
     'C', 'R50.9', 0, Decimal('0.3000'),
     'Temp > 38.3C (101F) persistent — screen for chronic infection'),

    ('temperature', '>', Decimal('38.3000'), None, None,
     'C', 'A49.9', 0, Decimal('0.2500'),
     'Temp > 38.3C — bacterial infection screen'),

    ('temperature', '>', Decimal('39.0000'), None, None,
     'C', 'R50.9', 0, Decimal('0.4000'),
     'Temp > 39.0C (102.2F) — significant fever, infection workup'),

    ('temperature', '>', Decimal('40.0000'), None, None,
     'C', 'R50.9', 0, Decimal('0.5000'),
     'Temp > 40C (104F) — high fever, serious infection/sepsis screen'),

    ('temperature', '<', Decimal('35.0000'), None, None,
     'C', 'R68.0', 0, Decimal('0.4000'),
     'Temp < 35C (95F) — hypothermia, screen for metabolic/endocrine'),

    ('temperature', '<', Decimal('35.0000'), None, None,
     'C', 'E03.9', 0, Decimal('0.3000'),
     'Temp < 35C — hypothermia may indicate hypothyroidism'),

    ('temperature', '<', Decimal('34.0000'), None, None,
     'C', 'T68', 0, Decimal('0.5000'),
     'Temp < 34C — significant hypothermia'),

    # =========================================================================
    # RESPIRATORY RATE
    # =========================================================================

    ('respiratory_rate', '>', Decimal('24.0000'), None, None,
     'breaths/min', 'R06.00', 84, Decimal('0.3500'),
     'RR > 24 — tachypnea, screen for respiratory distress'),

    ('respiratory_rate', '>', Decimal('24.0000'), None, None,
     'breaths/min', 'J96.11', 84, Decimal('0.3000'),
     'RR > 24 — tachypnea, chronic respiratory failure screen'),

    ('respiratory_rate', '>', Decimal('28.0000'), None, None,
     'breaths/min', 'J96.11', 84, Decimal('0.4500'),
     'RR > 28 — significant tachypnea, respiratory failure likely'),

    ('respiratory_rate', '>', Decimal('30.0000'), None, None,
     'breaths/min', 'J96.11', 84, Decimal('0.5500'),
     'RR > 30 — severe tachypnea, respiratory failure'),

    ('respiratory_rate', '>', Decimal('30.0000'), None, None,
     'breaths/min', 'J44.1', 111, Decimal('0.4000'),
     'RR > 30 — severe tachypnea, screen for COPD exacerbation'),

    ('respiratory_rate', '>', Decimal('35.0000'), None, None,
     'breaths/min', 'J96.11', 84, Decimal('0.6500'),
     'RR > 35 — critical tachypnea, definitive respiratory failure'),

    ('respiratory_rate', '<', Decimal('10.0000'), None, None,
     'breaths/min', 'R06.89', 0, Decimal('0.4000'),
     'RR < 10 — bradypnea, screen for CNS depression or resp failure'),

    ('respiratory_rate', '<', Decimal('8.0000'), None, None,
     'breaths/min', 'J96.11', 84, Decimal('0.5000'),
     'RR < 8 — significant bradypnea, respiratory failure'),

    # =========================================================================
    # BLOOD GLUCOSE (point-of-care)
    # =========================================================================

    ('blood_glucose', '>=', Decimal('200.0000'), None, None,
     'mg/dL', 'E11.9', 19, Decimal('0.6500'),
     'Random blood glucose >= 200 mg/dL — diabetes diagnostic threshold'),

    ('blood_glucose', '>=', Decimal('250.0000'), None, None,
     'mg/dL', 'E11.65', 19, Decimal('0.7000'),
     'Blood glucose >= 250 — hyperglycemia, uncontrolled diabetes'),

    ('blood_glucose', '>=', Decimal('300.0000'), None, None,
     'mg/dL', 'E11.65', 18, Decimal('0.7500'),
     'Blood glucose >= 300 — severe hyperglycemia, DM with complications'),

    ('blood_glucose', '>=', Decimal('400.0000'), None, None,
     'mg/dL', 'E11.10', 17, Decimal('0.8000'),
     'Blood glucose >= 400 — critical hyperglycemia, DKA/HHS risk'),

    ('blood_glucose', '<', Decimal('70.0000'), None, None,
     'mg/dL', 'E11.649', 19, Decimal('0.5000'),
     'Blood glucose < 70 — hypoglycemia, confirms diabetes on treatment'),

    ('blood_glucose', '<', Decimal('54.0000'), None, None,
     'mg/dL', 'E11.649', 18, Decimal('0.6000'),
     'Blood glucose < 54 — clinically significant hypoglycemia in diabetes'),

    ('blood_glucose', 'BETWEEN', None, Decimal('126.0000'), Decimal('199.9999'),
     'mg/dL', 'E11.9', 19, Decimal('0.5000'),
     'Fasting glucose 126-199 — diabetes diagnosis range'),

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
    # 1.  Create the table if it does not exist
    # ------------------------------------------------------------------
    try:
        cur.execute(CREATE_TABLE_SQL)
        cnx.commit()
        log.info("Table raf_vital_signals: CREATE TABLE IF NOT EXISTS executed.")
    except MySQLError as exc:
        log.error("Failed to create table: %s", exc)
        cur.close()
        cnx.close()
        return 1

    # ------------------------------------------------------------------
    # 2.  Count existing rows
    # ------------------------------------------------------------------
    cur.execute("SELECT COUNT(*) AS cnt FROM raf_vital_signals")
    existing_count = cur.fetchone()["cnt"]
    log.info("Table raf_vital_signals currently has %d rows.", existing_count)

    # ------------------------------------------------------------------
    # 3.  Load existing keys for duplicate detection
    #     Key: (vital_name, threshold_operator, threshold_value, suspect_icd10)
    # ------------------------------------------------------------------
    cur.execute("""
        SELECT vital_name, threshold_operator, threshold_value, suspect_icd10
        FROM raf_vital_signals
    """)
    existing_keys: set[tuple] = set()
    for row in cur.fetchall():
        existing_keys.add((
            row["vital_name"],
            row["threshold_operator"],
            row["threshold_value"],
            row["suspect_icd10"],
        ))

    log.info("Loaded %d existing keys for dedup.", len(existing_keys))

    # ------------------------------------------------------------------
    # 4.  Insert new signals
    # ------------------------------------------------------------------
    INSERT_SQL = """
        INSERT INTO raf_vital_signals
            (vital_name, threshold_operator, threshold_value,
             threshold_low, threshold_high, threshold_unit,
             suspect_icd10, suspect_hcc, confidence_base, notes, is_active)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 1)
    """

    inserted = 0
    skipped = 0
    errors = 0

    for (vital_name, operator, threshold_val, threshold_low, threshold_high,
         unit, icd10, hcc, confidence, notes) in SIGNALS:

        key = (vital_name, operator, threshold_val, icd10)
        if key in existing_keys:
            skipped += 1
            continue

        try:
            cur.execute(INSERT_SQL, (
                vital_name, operator, threshold_val,
                threshold_low, threshold_high, unit,
                icd10, hcc, confidence, notes,
            ))
            existing_keys.add(key)
            inserted += 1
        except MySQLError as exc:
            log.warning(
                "Failed to insert vital=%r op=%s val=%s icd10=%s: %s",
                vital_name, operator, threshold_val, icd10, exc,
            )
            errors += 1

    cnx.commit()

    # ------------------------------------------------------------------
    # 5.  Report
    # ------------------------------------------------------------------
    cur.execute("SELECT COUNT(*) AS cnt FROM raf_vital_signals")
    final_count = cur.fetchone()["cnt"]

    log.info("=" * 60)
    log.info("Seed complete.")
    log.info("  Signals in script:      %d", len(SIGNALS))
    log.info("  Skipped (duplicates):    %d", skipped)
    log.info("  Inserted:                %d", inserted)
    log.info("  Errors:                  %d", errors)
    log.info("  Total rows in table:     %d  (was %d)", final_count, existing_count)
    log.info("=" * 60)

    cur.close()
    cnx.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
