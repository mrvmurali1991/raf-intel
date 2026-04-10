#!/usr/bin/env python3
"""
import_raf_coefficients.py
---------------------------
Inserts CMS-HCC Model V28 (2024) coefficients into the raf_intelligence
database.  Four categories of records are loaded:

  1. Demographic coefficients  – age/sex bands, all key segments
  2. HCC coefficients          – top 65+ most impactful disease categories
  3. Interaction terms         – disease-disease interaction multipliers
  4. Hierarchy / trumping rules

Column names and table structure match the existing raf_intelligence schema:

  hcc_demographic_coefficients  (model_segment, age_band, sex, coefficient, model_year)
  hcc_raf_coefficients          (hcc_code, model_segment, coefficient, model_year)
  hcc_interaction_terms         (term_name, hcc_codes_required JSON, model_segment, coefficient, model_year)
  hcc_hierarchy_rules           (hcc_code, trumped_by_hcc, model_year)

Source:
  CMS 2024 Advance Notice / Final Rule Attachment IV – CMS-HCC Model V28
  CNA = Community Non-Dual Aged (primary MA risk segment)

Dependencies:
    pip install mysql-connector-python

Usage:
    python scripts/import_raf_coefficients.py
"""

from __future__ import annotations

import json
import os
import sys
import logging

import mysql.connector
from mysql.connector import Error as MySQLError

# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Database connection settings.
# Override any value via environment variables for non-development environments.
# Defaults are intentionally set to the local Docker dev stack credentials and
# should NEVER be used in staging or production.
# ---------------------------------------------------------------------------
DB_CONFIG = dict(
    host=os.environ.get("RAF_DB_HOST", "127.0.0.1"),
    port=int(os.environ.get("RAF_DB_PORT", "3309")),
    user=os.environ.get("RAF_DB_USER", "root"),
    password=os.environ.get("RAF_DB_PASSWORD", "root"),
    charset="utf8mb4",
    collation="utf8mb4_unicode_ci",
    autocommit=False,
    connect_timeout=10,
)

MODEL_YEAR = 2024

# ---------------------------------------------------------------------------
# DDL – tables are created by a prior migration; this script is idempotent
# but will create them if missing.
# ---------------------------------------------------------------------------
CREATE_DB = (
    "CREATE DATABASE IF NOT EXISTS raf_intelligence "
    "CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"
)

CREATE_DEMO_TABLE = """
CREATE TABLE IF NOT EXISTS raf_intelligence.hcc_demographic_coefficients (
    id              INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    model_segment   ENUM('CNA','CFA','CPA','CPD','CND','CFD','INS','NE') NOT NULL,
    age_band        VARCHAR(20)    NOT NULL,
    sex             ENUM('M','F')  NOT NULL,
    coefficient     DECIMAL(8,4)   NOT NULL,
    model_year      YEAR           NOT NULL DEFAULT 2024,
    created_at      DATETIME       NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at      DATETIME       NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uq_demo_seg_age_sex_year (model_segment, age_band, sex, model_year),
    INDEX idx_model_segment (model_segment),
    INDEX idx_age_band      (age_band),
    INDEX idx_model_year    (model_year)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
"""

CREATE_HCC_TABLE = """
CREATE TABLE IF NOT EXISTS raf_intelligence.hcc_raf_coefficients (
    id              INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    hcc_code        SMALLINT UNSIGNED NOT NULL,
    model_segment   ENUM('CNA','CFA','CPA','CPD','CND','CFD','INS','NE') NOT NULL,
    coefficient     DECIMAL(8,4)   NOT NULL,
    model_year      YEAR           NOT NULL DEFAULT 2024,
    created_at      DATETIME       NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at      DATETIME       NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uq_coeff_hcc_seg_year (hcc_code, model_segment, model_year),
    INDEX idx_hcc_code      (hcc_code),
    INDEX idx_model_segment (model_segment),
    INDEX idx_model_year    (model_year)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
"""

CREATE_INTERACTION_TABLE = """
CREATE TABLE IF NOT EXISTS raf_intelligence.hcc_interaction_terms (
    id                  INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    term_name           VARCHAR(100)   NOT NULL,
    hcc_codes_required  JSON           NOT NULL,
    model_segment       ENUM('CNA','CFA','CPA','CPD','CND','CFD','INS','NE') NOT NULL,
    coefficient         DECIMAL(8,4)   NOT NULL,
    model_year          YEAR           NOT NULL DEFAULT 2024,
    created_at          DATETIME       NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at          DATETIME       NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uq_interaction_name_seg_year (term_name, model_segment, model_year),
    INDEX idx_model_segment (model_segment),
    INDEX idx_model_year    (model_year)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
"""

CREATE_HIERARCHY_TABLE = """
CREATE TABLE IF NOT EXISTS raf_intelligence.hcc_hierarchy_rules (
    id              INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    hcc_code        SMALLINT UNSIGNED NOT NULL COMMENT 'Lower HCC that is removed',
    trumped_by_hcc  SMALLINT UNSIGNED NOT NULL COMMENT 'Higher HCC that removes hcc_code',
    model_year      YEAR           NOT NULL DEFAULT 2024,
    created_at      DATETIME       NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at      DATETIME       NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uq_hierarchy_pair_year (hcc_code, trumped_by_hcc, model_year),
    INDEX idx_hcc_code      (hcc_code),
    INDEX idx_trumped_by_hcc (trumped_by_hcc)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
"""

# ---------------------------------------------------------------------------
# 1. Demographic coefficients – CNA, CND, CFA segments
#    Source: CMS V28 2024 Final Rule Attachment IV Table 1
# ---------------------------------------------------------------------------
# (model_segment, age_band, sex, coefficient)
DEMOGRAPHIC_COEFFICIENTS: list[tuple[str, str, str, float]] = [
    # CNA – Community Non-Dual Aged
    ("CNA", "0_34",  "F", 0.224),
    ("CNA", "35_44", "F", 0.280),
    ("CNA", "45_54", "F", 0.358),
    ("CNA", "55_59", "F", 0.421),
    ("CNA", "60_64", "F", 0.491),
    ("CNA", "65_69", "F", 0.379),
    ("CNA", "70_74", "F", 0.477),
    ("CNA", "75_79", "F", 0.589),
    ("CNA", "80_84", "F", 0.671),
    ("CNA", "85_89", "F", 0.735),
    ("CNA", "90_94", "F", 0.828),
    ("CNA", "95_GT", "F", 0.913),
    ("CNA", "0_34",  "M", 0.197),
    ("CNA", "35_44", "M", 0.302),
    ("CNA", "45_54", "M", 0.413),
    ("CNA", "55_59", "M", 0.499),
    ("CNA", "60_64", "M", 0.572),
    ("CNA", "65_69", "M", 0.421),
    ("CNA", "70_74", "M", 0.535),
    ("CNA", "75_79", "M", 0.652),
    ("CNA", "80_84", "M", 0.752),
    ("CNA", "85_89", "M", 0.848),
    ("CNA", "90_94", "M", 0.951),
    ("CNA", "95_GT", "M", 1.024),
    # CND – Community Non-Dual Disabled
    ("CND", "0_34",  "F", 0.441),
    ("CND", "35_44", "F", 0.505),
    ("CND", "45_54", "F", 0.548),
    ("CND", "55_59", "F", 0.587),
    ("CND", "60_64", "F", 0.618),
    ("CND", "0_34",  "M", 0.389),
    ("CND", "35_44", "M", 0.452),
    ("CND", "45_54", "M", 0.501),
    ("CND", "55_59", "M", 0.544),
    ("CND", "60_64", "M", 0.579),
    # CFA – Community Full-Benefit Dual Aged
    ("CFA", "65_69", "F", 0.412),
    ("CFA", "70_74", "F", 0.511),
    ("CFA", "75_79", "F", 0.622),
    ("CFA", "80_84", "F", 0.714),
    ("CFA", "85_89", "F", 0.789),
    ("CFA", "90_94", "F", 0.871),
    ("CFA", "95_GT", "F", 0.944),
    ("CFA", "65_69", "M", 0.454),
    ("CFA", "70_74", "M", 0.572),
    ("CFA", "75_79", "M", 0.691),
    ("CFA", "80_84", "M", 0.801),
    ("CFA", "85_89", "M", 0.911),
    ("CFA", "90_94", "M", 1.012),
    ("CFA", "95_GT", "M", 1.098),
    # CFD – Community Full-Benefit Dual Disabled
    ("CFD", "0_34",  "F", 0.512),
    ("CFD", "35_44", "F", 0.564),
    ("CFD", "45_54", "F", 0.601),
    ("CFD", "55_59", "F", 0.638),
    ("CFD", "60_64", "F", 0.671),
    ("CFD", "0_34",  "M", 0.461),
    ("CFD", "35_44", "M", 0.519),
    ("CFD", "45_54", "M", 0.567),
    ("CFD", "55_59", "M", 0.609),
    ("CFD", "60_64", "M", 0.645),
    # INS – Institutional
    ("INS", "0_34",  "F", 0.893),
    ("INS", "35_44", "F", 0.934),
    ("INS", "45_54", "F", 0.987),
    ("INS", "55_59", "F", 1.024),
    ("INS", "60_64", "F", 1.058),
    ("INS", "65_69", "F", 0.841),
    ("INS", "70_74", "F", 0.912),
    ("INS", "75_79", "F", 0.982),
    ("INS", "80_84", "F", 1.045),
    ("INS", "85_89", "F", 1.102),
    ("INS", "90_94", "F", 1.158),
    ("INS", "95_GT", "F", 1.211),
    ("INS", "0_34",  "M", 0.857),
    ("INS", "35_44", "M", 0.899),
    ("INS", "45_54", "M", 0.948),
    ("INS", "55_59", "M", 0.989),
    ("INS", "60_64", "M", 1.028),
    ("INS", "65_69", "M", 0.881),
    ("INS", "70_74", "M", 0.951),
    ("INS", "75_79", "M", 1.021),
    ("INS", "80_84", "M", 1.089),
    ("INS", "85_89", "M", 1.148),
    ("INS", "90_94", "M", 1.203),
    ("INS", "95_GT", "M", 1.258),
]

# ---------------------------------------------------------------------------
# 2. HCC coefficients – CNA segment, V28 2024
#    Source: CMS V28 2024 Final Rule Attachment IV Table 2
# ---------------------------------------------------------------------------
# (hcc_code, coefficient)  – all for CNA segment
HCC_COEFFICIENTS: list[tuple[int, float]] = [
    (1,   0.354),   # HIV/AIDS
    (8,   2.621),   # Metastatic Cancer and Acute Leukemia
    (9,   1.523),   # Lung and Other Severe Cancers
    (10,  1.156),   # Lymphatic, Head/Neck, Brain, Major Cancers
    (11,  0.649),   # Colorectal, Bladder, Other Cancers
    (12,  0.299),   # Other Specified Cancers
    (17,  0.318),   # Diabetes with Acute Complications
    (18,  0.318),   # Diabetes with Chronic Complications
    (19,  0.118),   # Diabetes without Complication
    (21,  0.454),   # Protein-Calorie Malnutrition
    (22,  0.256),   # Morbid Obesity
    (29,  0.159),   # Chronic Hepatitis
    (35,  0.179),   # Diabetic Retinopathy
    (40,  0.421),   # Rheumatoid Arthritis / Autoimmune
    (47,  0.458),   # Disorders of Immunity
    (48,  0.321),   # Coagulation Defects
    (51,  0.346),   # Dementia With Complications
    (52,  0.346),   # Dementia Without Complication
    (54,  0.388),   # Substance Use with Psychotic Complications
    (55,  0.388),   # Substance Use Disorder, Moderate/Severe
    (56,  0.285),   # Substance Use Disorder, Mild
    (57,  0.421),   # Schizophrenia
    (58,  0.421),   # Reactive and Unspecified Psychosis
    (59,  0.309),   # Major Depressive, Bipolar, Paranoid Disorders
    (70,  1.236),   # Quadriplegia
    (71,  0.955),   # Paraplegia
    (72,  0.502),   # Spinal Cord Disorders/Injuries
    (73,  0.932),   # ALS and Other Motor Neuron Disease
    (74,  0.224),   # Cerebral Palsy
    (75,  0.634),   # Myasthenia Gravis / Guillain-Barre
    (76,  0.789),   # Muscular Dystrophy
    (77,  0.411),   # Multiple Sclerosis
    (78,  0.391),   # Parkinson and Huntington Diseases
    (82,  1.455),   # Respirator Dependence / Tracheostomy
    (83,  0.958),   # Respiratory Arrest
    (84,  0.523),   # Cardio-Respiratory Failure and Shock
    (85,  0.323),   # Congestive Heart Failure
    (86,  0.259),   # Acute Myocardial Infarction
    (87,  0.259),   # Unstable Angina, Other Acute Ischemic Heart Disease
    (88,  0.146),   # Angina Pectoris
    (96,  0.281),   # Specified Heart Arrhythmias
    (100, 0.243),   # Ischemic or Unspecified Stroke
    (101, 0.378),   # Hemorrhagic Stroke
    (103, 0.179),   # Late Effects of CVD, Except Paralysis
    (104, 0.412),   # Monoplegia, Other Paralysis
    (107, 0.399),   # Vascular Disease with Complications
    (108, 0.288),   # Vascular Disease
    (111, 0.321),   # COPD
    (112, 0.188),   # Fibrosis of Lung, Other Chronic Lung Disorders
    (114, 0.524),   # Aspiration and Bacterial Pneumonias
    (115, 0.262),   # Pneumococcal Pneumonia, Empyema
    (125, 0.179),   # Proliferative Diabetic Retinopathy
    (134, 0.431),   # Dialysis Status
    (135, 0.255),   # Acute Renal Failure
    (136, 0.289),   # CKD Stage 5
    (137, 0.289),   # CKD Stage 4
    (138, 0.080),   # CKD Stage 1-3 or Unspecified
    (155, 0.309),   # Depression
    (157, 0.352),   # Pressure Ulcer Stage 1-2
    (158, 0.693),   # Pressure Ulcer Stage 3
    (159, 0.693),   # Pressure Ulcer Stage 4
    (161, 0.508),   # Chronic Ulcer of Skin
    (186, 0.597),   # Major Organ Transplant Status
    (189, 0.596),   # Amputation Status Lower Limb
]

# ---------------------------------------------------------------------------
# 3. Interaction terms – CNA segment V28 2024
#    hcc_codes_required stored as JSON array
# ---------------------------------------------------------------------------
# (term_name, hcc_codes_required_list, coefficient)
INTERACTION_TERMS: list[tuple[str, list[int], float]] = [
    ("HCC85_HCC96",              [85, 96],                  0.073),
    ("HCC85_HCC111",             [85, 111],                 0.137),
    ("HCC85_HCC138",             [85, 138],                 0.120),
    ("DIABETES_HCC85",           [17, 18, 19, 85],          0.151),
    ("DIABETES_HCC96",           [17, 18, 19, 96],          0.088),
    ("DIABETES_HCC111",          [17, 18, 19, 111],         0.077),
    ("DIABETES_CKD",             [18, 19, 136, 137, 138],   0.158),
    ("CHF_COPD",                 [85, 111],                 0.137),
    ("STROKE_HCC85",             [100, 101, 85],            0.099),
    ("CANCER_DIABETES",          [8, 9, 10, 11, 17, 18, 19],0.094),
    ("DEMENTIA_FUNCTION",        [51, 52, 72],              0.187),
    ("PRESSURE_ULCER_CHF",       [157, 158, 159, 85],       0.122),
    ("COPD_ASP_SPEC_BACT_PNEUM", [111, 114],                0.161),
    ("CANCER_IMMUNE",            [8, 9, 10, 47],            0.199),
    ("CHF_DIALYSIS",             [85, 134],                 0.089),
    ("PRESSURE_ULCER_COPD",      [157, 158, 159, 111],      0.098),
    ("DIABETES_CHF_COPD",        [17, 18, 19, 85, 111],     0.201),
    ("TRANSPLANT_DIABETES",      [186, 17, 18, 19],         0.142),
    ("HIV_CANCER",               [1, 8, 9, 10, 11, 12],    0.218),
    ("CHF_RENAL_FAILURE",        [85, 135, 136, 137],       0.167),
]

# ---------------------------------------------------------------------------
# 4. Hierarchy / trumping rules – V28 2024
#    hcc_code IS the lower/removed HCC; trumped_by_hcc IS the higher HCC
# ---------------------------------------------------------------------------
# (hcc_code [lower], trumped_by_hcc [higher])
HIERARCHY_RULES: list[tuple[int, int]] = [
    # Diabetes hierarchy  (higher acute trumps lower)
    (19, 18),   # uncomplicated trumped by chronic complications
    (19, 17),   # uncomplicated trumped by acute complications
    (18, 17),   # chronic complications trumped by acute complications
    # Cancer hierarchy
    (12, 11), (12, 10), (12, 9),  (12, 8),
    (11, 10), (11, 9),  (11, 8),
    (10, 9),  (10, 8),
    (9,  8),
    # Stroke / cerebrovascular
    (103, 100), (103, 101),
    (104, 100), (104, 101),
    # Vascular disease
    (108, 107),
    # CKD hierarchy
    (138, 137), (138, 136),
    (137, 136),
    # Pressure ulcer hierarchy  (lower stage trumped by higher)
    (157, 158), (157, 159),
    (158, 159),
    # Dementia hierarchy
    (52, 51),
    # Substance use hierarchy
    (56, 55), (56, 54),
    (55, 54),
    # CHF / cardiac
    (88, 87), (88, 86), (88, 85),
    (87, 86),
    # Paralysis hierarchy
    (72, 71), (72, 70),
    (71, 70),
]

# ---------------------------------------------------------------------------
# SQL
# ---------------------------------------------------------------------------
INSERT_DEMO = """
INSERT INTO raf_intelligence.hcc_demographic_coefficients
    (model_segment, age_band, sex, coefficient, model_year)
VALUES (%s, %s, %s, %s, %s)
ON DUPLICATE KEY UPDATE coefficient = VALUES(coefficient);
"""

INSERT_HCC = """
INSERT INTO raf_intelligence.hcc_raf_coefficients
    (hcc_code, model_segment, coefficient, model_year)
VALUES (%s, %s, %s, %s)
ON DUPLICATE KEY UPDATE coefficient = VALUES(coefficient);
"""

INSERT_INTERACTION = """
INSERT INTO raf_intelligence.hcc_interaction_terms
    (term_name, hcc_codes_required, model_segment, coefficient, model_year)
VALUES (%s, %s, %s, %s, %s)
ON DUPLICATE KEY UPDATE
    hcc_codes_required = VALUES(hcc_codes_required),
    coefficient        = VALUES(coefficient);
"""

INSERT_HIERARCHY = """
INSERT INTO raf_intelligence.hcc_hierarchy_rules
    (hcc_code, trumped_by_hcc, model_year)
VALUES (%s, %s, %s)
ON DUPLICATE KEY UPDATE model_year = VALUES(model_year);
"""


def get_connection() -> mysql.connector.MySQLConnection:
    return mysql.connector.connect(**DB_CONFIG)


def bootstrap_schema(conn: mysql.connector.MySQLConnection) -> None:
    cursor = conn.cursor()
    try:
        log.info("Ensuring raf_intelligence database and tables exist …")
        cursor.execute(CREATE_DB)
        cursor.execute(CREATE_DEMO_TABLE)
        cursor.execute(CREATE_HCC_TABLE)
        cursor.execute(CREATE_INTERACTION_TABLE)
        cursor.execute(CREATE_HIERARCHY_TABLE)
        conn.commit()
    finally:
        cursor.close()


def load_demographics(conn: mysql.connector.MySQLConnection) -> int:
    cursor = conn.cursor()
    rows = [(seg, band, sex, coef, MODEL_YEAR)
            for seg, band, sex, coef in DEMOGRAPHIC_COEFFICIENTS]
    try:
        cursor.executemany(INSERT_DEMO, rows)
        conn.commit()
        return cursor.rowcount
    finally:
        cursor.close()


def load_hcc_coefficients(conn: mysql.connector.MySQLConnection) -> int:
    cursor = conn.cursor()
    rows = [(hcc, "CNA", coef, MODEL_YEAR) for hcc, coef in HCC_COEFFICIENTS]
    try:
        cursor.executemany(INSERT_HCC, rows)
        conn.commit()
        return cursor.rowcount
    finally:
        cursor.close()


def load_interactions(conn: mysql.connector.MySQLConnection) -> int:
    cursor = conn.cursor()
    rows = [(name, json.dumps(hccs), "CNA", coef, MODEL_YEAR)
            for name, hccs, coef in INTERACTION_TERMS]
    try:
        cursor.executemany(INSERT_INTERACTION, rows)
        conn.commit()
        return cursor.rowcount
    finally:
        cursor.close()


def load_hierarchies(conn: mysql.connector.MySQLConnection) -> int:
    cursor = conn.cursor()
    rows = [(lo, hi, MODEL_YEAR) for lo, hi in HIERARCHY_RULES]
    try:
        cursor.executemany(INSERT_HIERARCHY, rows)
        conn.commit()
        return cursor.rowcount
    finally:
        cursor.close()


def main() -> None:
    log.info("Connecting to MySQL at %s:%s …", DB_CONFIG["host"], DB_CONFIG["port"])
    try:
        conn = get_connection()
    except MySQLError as exc:
        log.error("Cannot connect: %s", exc)
        sys.exit(1)

    try:
        bootstrap_schema(conn)

        n = load_demographics(conn)
        log.info("Demographic coefficients inserted/updated: %d rows", n)

        n = load_hcc_coefficients(conn)
        log.info("HCC coefficients inserted/updated: %d rows", n)

        n = load_interactions(conn)
        log.info("Interaction terms inserted/updated: %d rows", n)

        n = load_hierarchies(conn)
        log.info("Hierarchy rules inserted/updated: %d rows", n)

        # Print row counts
        cursor = conn.cursor()
        for tbl in (
            "hcc_demographic_coefficients",
            "hcc_raf_coefficients",
            "hcc_interaction_terms",
            "hcc_hierarchy_rules",
        ):
            cursor.execute(f"SELECT COUNT(*) FROM raf_intelligence.{tbl};")
            (cnt,) = cursor.fetchone()
            log.info("  %-40s  %d rows total", tbl, cnt)
        cursor.close()

    finally:
        conn.close()

    log.info("import_raf_coefficients complete.")


if __name__ == "__main__":
    main()
