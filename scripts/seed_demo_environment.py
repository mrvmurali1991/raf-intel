#!/usr/bin/env python3
# DISCLAIMER: This script inserts synthetic, de-identified demo data only.
# No real patient information is used. All names, dates, and clinical details
# are fabricated. Do not use this data for clinical decisions or payment submissions.
"""
seed_demo_environment.py
========================
Creates a comprehensive, realistic demo environment for the RAF Intelligence system.

What is seeded
--------------
- 5 providers with varying specialties and coding quality profiles
- 50 synthetic patients (age 35-95, mixed sex, dual/non-dual)
- 3-8 encounters per patient spanning 2 calendar years (2024-2025)
- SOAP notes per encounter with clinically realistic narrative
- ICD-10 billing codes (some patients intentionally under-coded → RAF gaps)
- Medications appropriate for each patient's condition profile
- Lab results (some abnormal → triggers suspect flags)
- Vital signs (some out of range)
- Pre-calculated RAF scores inserted into the RAF Intelligence DB

Usage
-----
    python -m scripts.seed_demo_environment

    # Or directly:
    python scripts/seed_demo_environment.py [--port 3309] [--dry-run]
"""
from __future__ import annotations

import argparse
import json
import logging
import random
import sys
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any

import os

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
# DB connection
# Override any value via environment variables for non-development environments.
# Defaults are intentionally set to the local Docker dev stack credentials and
# should NEVER be used in staging or production.
# ---------------------------------------------------------------------------

OPENEMR_DB = dict(
    host=os.environ.get("RAF_DB_HOST", "127.0.0.1"),
    port=int(os.environ.get("RAF_DB_PORT", "3309")),
    user=os.environ.get("RAF_DB_USER", "root"),
    password=os.environ.get("RAF_DB_PASSWORD", "root"),
    database="openemr",
    charset="utf8mb4",
    collation="utf8mb4_unicode_ci",
    autocommit=False,
    connect_timeout=10,
)

RAF_DB = dict(
    host=os.environ.get("RAF_DB_HOST", "127.0.0.1"),
    port=int(os.environ.get("RAF_RAF_DB_PORT", "3310")),
    user=os.environ.get("RAF_DB_USER", "root"),
    password=os.environ.get("RAF_DB_PASSWORD", "root"),
    database="raf_intelligence",
    charset="utf8mb4",
    autocommit=False,
    connect_timeout=10,
)

FACILITY_ID = 3
DEMO_TAG = "DEMO_ENV_V1"

# ---------------------------------------------------------------------------
# Random seed for reproducibility
# ---------------------------------------------------------------------------
RNG = random.Random(42)

# ---------------------------------------------------------------------------
# Provider definitions
# ---------------------------------------------------------------------------
# coding_quality: 1.0 = perfect coder, 0.5 = misses ~half of HCC opportunities
# ---------------------------------------------------------------------------

@dataclass
class Provider:
    provider_id: int
    fname: str
    lname: str
    specialty: str
    npi: str
    coding_quality: float  # 0.0 - 1.0; controls under-coding probability


PROVIDERS: list[Provider] = [
    Provider(
        provider_id=200,
        fname="Patricia", lname="Chen",
        specialty="Internal Medicine",
        npi="1234567890",
        coding_quality=0.95,   # excellent coder — nearly complete
    ),
    Provider(
        provider_id=201,
        fname="James", lname="Okafor",
        specialty="Family Medicine",
        npi="1234567891",
        coding_quality=0.70,   # good coder — occasional gaps
    ),
    Provider(
        provider_id=202,
        fname="Sandra", lname="Reyes",
        specialty="Geriatrics",
        npi="1234567892",
        coding_quality=0.85,   # very good coder
    ),
    Provider(
        provider_id=203,
        fname="Michael", lname="Thornton",
        specialty="Cardiology",
        npi="1234567893",
        coding_quality=0.50,   # moderate coder — significant gaps
    ),
    Provider(
        provider_id=204,
        fname="Linda", lname="Nakamura",
        specialty="Endocrinology",
        npi="1234567894",
        coding_quality=0.40,   # poor coder — many HCC opportunities missed
    ),
]

# ---------------------------------------------------------------------------
# Clinical scenario templates
# Each template defines a condition profile and generates realistic data.
# ---------------------------------------------------------------------------

@dataclass
class ConditionTemplate:
    name: str
    hcc_codes: list[int]
    full_icd10_codes: list[tuple[str, str]]   # (code, description) — what should be coded
    under_coded_icd10: list[tuple[str, str]]  # subset that a poor coder might bill
    medications: list[tuple[str, str, str]]   # (drug, dose, sig)
    lab_flags: list[dict]                     # abnormal labs relevant to this condition
    raf_estimate: float                        # approximate RAF contribution


CONDITION_TEMPLATES: list[ConditionTemplate] = [

    # -----------------------------------------------------------------------
    # DM2 with CKD3 and neuropathy
    # -----------------------------------------------------------------------
    ConditionTemplate(
        name="DM2 + CKD3 + Neuropathy",
        hcc_codes=[17, 326],
        full_icd10_codes=[
            ("E11.40", "Type 2 DM with diabetic neuropathy, unspecified"),
            ("E11.22", "Type 2 DM with diabetic CKD"),
            ("N18.3",  "CKD stage 3"),
            ("I10",    "Hypertension"),
        ],
        under_coded_icd10=[
            ("E11.9",  "Type 2 DM without complications"),
            ("I10",    "Hypertension"),
        ],
        medications=[
            ("Metformin", "500 mg", "BID with meals"),
            ("Lisinopril", "10 mg", "Daily"),
            ("Gabapentin", "300 mg", "TID"),
            ("Furosemide",  "40 mg", "Daily"),
        ],
        lab_flags=[
            {"name": "HbA1c",      "value": "8.6%",        "flag": "H"},
            {"name": "eGFR",       "value": "38 mL/min",   "flag": "L"},
            {"name": "Creatinine", "value": "1.9 mg/dL",   "flag": "H"},
            {"name": "Microalbumin/Creatinine ratio", "value": "280 mg/g", "flag": "H"},
        ],
        raf_estimate=0.70,
    ),

    # -----------------------------------------------------------------------
    # CHF systolic + AFib
    # -----------------------------------------------------------------------
    ConditionTemplate(
        name="CHF Systolic + Atrial Fibrillation",
        hcc_codes=[85, 96],
        full_icd10_codes=[
            ("I50.22", "Chronic systolic CHF"),
            ("I48.11", "Longstanding persistent AFib"),
        ],
        under_coded_icd10=[
            ("I50.9",  "Heart failure, unspecified"),
        ],
        medications=[
            ("Carvedilol",    "25 mg",  "BID"),
            ("Lisinopril",    "40 mg",  "Daily"),
            ("Furosemide",    "80 mg",  "BID"),
            ("Apixaban",      "5 mg",   "BID"),
            ("Spironolactone","25 mg",  "Daily"),
        ],
        lab_flags=[
            {"name": "BNP",          "value": "890 pg/mL",  "flag": "H"},
            {"name": "Sodium",       "value": "132 mEq/L",  "flag": "L"},
            {"name": "Creatinine",   "value": "1.6 mg/dL",  "flag": "H"},
        ],
        raf_estimate=0.85,
    ),

    # -----------------------------------------------------------------------
    # COPD moderate-severe
    # -----------------------------------------------------------------------
    ConditionTemplate(
        name="COPD Moderate-Severe",
        hcc_codes=[111],
        full_icd10_codes=[
            ("J44.1", "COPD with acute exacerbation"),
        ],
        under_coded_icd10=[
            ("J44.0", "COPD with acute lower respiratory infection"),
        ],
        medications=[
            ("Tiotropium",               "18 mcg",  "Daily inhaled"),
            ("Fluticasone/Salmeterol",   "250/50",  "BID inhaled"),
            ("Albuterol",                "2 puffs", "PRN q4-6h"),
            ("Prednisone",               "40 mg",   "x5 days (exacerbation)"),
        ],
        lab_flags=[
            {"name": "SpO2",    "value": "88%",           "flag": "L"},
            {"name": "FEV1",    "value": "48% predicted", "flag": "L"},
            {"name": "PaCO2",   "value": "52 mmHg",       "flag": "H"},
        ],
        raf_estimate=0.35,
    ),

    # -----------------------------------------------------------------------
    # DM2 with eye disease + hyperglycemia
    # -----------------------------------------------------------------------
    ConditionTemplate(
        name="DM2 Retinopathy + Hyperglycemia",
        hcc_codes=[17, 19],
        full_icd10_codes=[
            ("E11.3519", "T2DM with non-prolif retinopathy without macular edema, unspec eye"),
            ("E11.65",   "T2DM with hyperglycemia"),
        ],
        under_coded_icd10=[
            ("E11.65",   "T2DM with hyperglycemia"),
        ],
        medications=[
            ("Insulin glargine", "30 units", "QHS subcutaneous"),
            ("Insulin lispro",   "8 units",  "AC meals"),
            ("Metformin",        "1000 mg",  "BID"),
            ("Lisinopril",       "10 mg",    "Daily"),
        ],
        lab_flags=[
            {"name": "HbA1c",          "value": "9.4%",         "flag": "H"},
            {"name": "Fasting glucose","value": "226 mg/dL",    "flag": "H"},
        ],
        raf_estimate=0.55,
    ),

    # -----------------------------------------------------------------------
    # Morbid obesity + sleep apnea
    # -----------------------------------------------------------------------
    ConditionTemplate(
        name="Morbid Obesity + OSA",
        hcc_codes=[22],
        full_icd10_codes=[
            ("E66.01", "Morbid (severe) obesity due to excess calories"),
            ("G47.33", "Obstructive sleep apnea"),
        ],
        under_coded_icd10=[
            ("E66.9",  "Obesity, unspecified"),
        ],
        medications=[
            ("Metformin",    "500 mg", "Daily"),
            ("Lisinopril",   "20 mg",  "Daily"),
            ("CPAP machine", "Auto",   "Nightly"),
        ],
        lab_flags=[
            {"name": "BMI",           "value": "44.2 kg/m2",  "flag": "H"},
            {"name": "Fasting glucose","value": "118 mg/dL",  "flag": "H"},
            {"name": "Triglycerides", "value": "310 mg/dL",   "flag": "H"},
        ],
        raf_estimate=0.30,
    ),

    # -----------------------------------------------------------------------
    # Major depression + anxiety
    # -----------------------------------------------------------------------
    ConditionTemplate(
        name="Major Depression + Anxiety",
        hcc_codes=[155],
        full_icd10_codes=[
            ("F33.1", "Major depressive disorder, recurrent, moderate"),
            ("F41.1", "Generalized anxiety disorder"),
        ],
        under_coded_icd10=[
            ("F32.9", "Major depressive disorder, single episode, unspecified"),
        ],
        medications=[
            ("Sertraline",  "100 mg", "Daily"),
            ("Buspirone",   "15 mg",  "BID"),
            ("Mirtazapine", "15 mg",  "QHS PRN insomnia"),
        ],
        lab_flags=[
            {"name": "TSH",      "value": "3.2 mIU/L",  "flag": "N"},
            {"name": "PHQ-9",    "value": "16",          "flag": "H"},
        ],
        raf_estimate=0.30,
    ),

    # -----------------------------------------------------------------------
    # Rheumatoid arthritis on biologics
    # -----------------------------------------------------------------------
    ConditionTemplate(
        name="Rheumatoid Arthritis",
        hcc_codes=[40],
        full_icd10_codes=[
            ("M05.79", "Rheumatoid arthritis with rheumatoid factor, multiple joints"),
        ],
        under_coded_icd10=[
            ("M06.9",  "Rheumatoid arthritis, unspecified"),
        ],
        medications=[
            ("Methotrexate",      "15 mg", "Weekly oral"),
            ("Hydroxychloroquine","200 mg", "BID"),
            ("Adalimumab",        "40 mg",  "Subcutaneous q2 weeks"),
            ("Folic acid",        "1 mg",   "Daily"),
        ],
        lab_flags=[
            {"name": "RF",       "value": "140 IU/mL",   "flag": "H"},
            {"name": "anti-CCP", "value": ">250 U/mL",   "flag": "H"},
            {"name": "ESR",      "value": "52 mm/hr",    "flag": "H"},
            {"name": "CRP",      "value": "2.8 mg/dL",   "flag": "H"},
        ],
        raf_estimate=0.40,
    ),

    # -----------------------------------------------------------------------
    # CKD stage 4 + anemia
    # -----------------------------------------------------------------------
    ConditionTemplate(
        name="CKD Stage 4 + Renal Anemia",
        hcc_codes=[328],
        full_icd10_codes=[
            ("N18.4", "CKD stage 4"),
            ("D63.1", "Anemia of chronic kidney disease"),
        ],
        under_coded_icd10=[
            ("N18.9", "CKD, unspecified"),
        ],
        medications=[
            ("Lisinopril",    "40 mg", "Daily"),
            ("Furosemide",    "80 mg", "BID"),
            ("Darbepoetin",   "60 mcg","Subcutaneous monthly"),
            ("Cinacalcet",    "30 mg", "Daily"),
            ("Calcium acetate","667 mg","TID with meals"),
        ],
        lab_flags=[
            {"name": "eGFR",       "value": "22 mL/min",  "flag": "L"},
            {"name": "Creatinine", "value": "3.1 mg/dL",  "flag": "H"},
            {"name": "Hemoglobin", "value": "9.4 g/dL",   "flag": "L"},
            {"name": "Phosphorus", "value": "5.6 mg/dL",  "flag": "H"},
            {"name": "PTH",        "value": "312 pg/mL",  "flag": "H"},
        ],
        raf_estimate=0.55,
    ),

    # -----------------------------------------------------------------------
    # Stroke sequela with hemiparesis
    # -----------------------------------------------------------------------
    ConditionTemplate(
        name="Ischemic Stroke Sequela",
        hcc_codes=[103],
        full_icd10_codes=[
            ("I69.351", "Hemiplegia/hemiparesis following cerebral infarction, right dominant"),
        ],
        under_coded_icd10=[
            ("I69.398", "Other sequelae of cerebral infarction"),
        ],
        medications=[
            ("Aspirin",         "325 mg", "Daily"),
            ("Clopidogrel",     "75 mg",  "Daily"),
            ("Atorvastatin",    "80 mg",  "QHS"),
            ("Lisinopril",      "10 mg",  "Daily"),
        ],
        lab_flags=[
            {"name": "LDL",     "value": "68 mg/dL",   "flag": "N"},
            {"name": "HbA1c",   "value": "6.2%",       "flag": "N"},
        ],
        raf_estimate=0.60,
    ),

    # -----------------------------------------------------------------------
    # HIV disease on ART
    # -----------------------------------------------------------------------
    ConditionTemplate(
        name="HIV Disease on ART",
        hcc_codes=[1],
        full_icd10_codes=[
            ("B20",    "HIV disease"),
        ],
        under_coded_icd10=[
            ("B20",    "HIV disease"),  # usually not under-coded
        ],
        medications=[
            ("Bictegravir/Emtricitabine/TAF", "50/200/25 mg", "Daily"),
            ("Trimethoprim/Sulfamethoxazole",  "SS",           "Daily prophylaxis"),
        ],
        lab_flags=[
            {"name": "CD4 count",    "value": "620 cells/mm3",  "flag": "N"},
            {"name": "HIV RNA",      "value": "Undetectable",   "flag": "N"},
        ],
        raf_estimate=0.35,
    ),

    # -----------------------------------------------------------------------
    # Protein-calorie malnutrition
    # -----------------------------------------------------------------------
    ConditionTemplate(
        name="Protein-Calorie Malnutrition",
        hcc_codes=[21],
        full_icd10_codes=[
            ("E44.0", "Moderate protein-calorie malnutrition"),
        ],
        under_coded_icd10=[],  # often not coded at all
        medications=[
            ("Ensure Plus",     "237 mL",  "BID nutritional supplement"),
            ("Multivitamin",    "1 tablet","Daily"),
            ("Zinc sulfate",    "220 mg",  "Daily"),
        ],
        lab_flags=[
            {"name": "Albumin",    "value": "2.6 g/dL",   "flag": "L"},
            {"name": "Prealbumin", "value": "9 mg/dL",    "flag": "L"},
            {"name": "BMI",        "value": "17.4 kg/m2", "flag": "L"},
        ],
        raf_estimate=0.45,
    ),

    # -----------------------------------------------------------------------
    # DM2 with peripheral vascular disease
    # -----------------------------------------------------------------------
    ConditionTemplate(
        name="DM2 + Peripheral Vascular Disease",
        hcc_codes=[17, 107],
        full_icd10_codes=[
            ("E11.51", "T2DM with diabetic peripheral angiopathy without gangrene"),
            ("I73.9",  "Peripheral vascular disease, unspecified"),
        ],
        under_coded_icd10=[
            ("E11.9",  "T2DM without complications"),
        ],
        medications=[
            ("Metformin",   "1000 mg", "BID"),
            ("Cilostazol",  "100 mg",  "BID"),
            ("Aspirin",     "81 mg",   "Daily"),
            ("Atorvastatin","40 mg",   "QHS"),
        ],
        lab_flags=[
            {"name": "ABI right",  "value": "0.65",       "flag": "L"},
            {"name": "ABI left",   "value": "0.60",       "flag": "L"},
            {"name": "HbA1c",      "value": "8.1%",       "flag": "H"},
        ],
        raf_estimate=0.50,
    ),

    # -----------------------------------------------------------------------
    # Simple hypertension only (low RAF — comparison patient)
    # -----------------------------------------------------------------------
    ConditionTemplate(
        name="Hypertension Only",
        hcc_codes=[],
        full_icd10_codes=[
            ("I10", "Essential hypertension"),
        ],
        under_coded_icd10=[
            ("I10", "Essential hypertension"),
        ],
        medications=[
            ("Amlodipine",  "10 mg", "Daily"),
            ("Lisinopril",  "20 mg", "Daily"),
        ],
        lab_flags=[
            {"name": "BP",  "value": "148/92 mmHg", "flag": "H"},
        ],
        raf_estimate=0.10,
    ),

    # -----------------------------------------------------------------------
    # Schizophrenia
    # -----------------------------------------------------------------------
    ConditionTemplate(
        name="Schizophrenia",
        hcc_codes=[157],
        full_icd10_codes=[
            ("F20.0", "Paranoid schizophrenia"),
        ],
        under_coded_icd10=[
            ("F29", "Unspecified psychosis not due to a substance or known physiological condition"),
        ],
        medications=[
            ("Olanzapine",   "20 mg",  "QHS"),
            ("Benztropine",  "1 mg",   "BID"),
            ("Lorazepam",    "0.5 mg", "PRN agitation"),
        ],
        lab_flags=[
            {"name": "Fasting glucose", "value": "108 mg/dL", "flag": "H"},
            {"name": "BMI",             "value": "31 kg/m2",  "flag": "H"},
        ],
        raf_estimate=0.38,
    ),
]

# ---------------------------------------------------------------------------
# Patient pool definitions
# First name, last name, demographic info pools
# ---------------------------------------------------------------------------

_FIRST_NAMES_M = [
    "Robert","James","William","Richard","Charles","Thomas","Michael",
    "David","Edward","George","Joseph","Henry","Ronald","Donald","Arthur",
    "Harold","Eugene","Carl","Ralph","Louis","Raymond","Frank","Walter","Roy",
    "Albert",
]
_FIRST_NAMES_F = [
    "Mary","Patricia","Linda","Barbara","Elizabeth","Jennifer","Margaret",
    "Susan","Dorothy","Sarah","Karen","Nancy","Betty","Ruth","Sandra",
    "Alice","Helen","Laura","Joan","Anna","Frances","Eleanor","Virginia",
    "Evelyn","Martha",
]
_LAST_NAMES = [
    "Johnson","Williams","Jones","Brown","Davis","Miller","Wilson","Moore",
    "Taylor","Anderson","Thomas","Jackson","White","Harris","Martin","Thompson",
    "Garcia","Martinez","Robinson","Clark","Lewis","Lee","Walker","Hall",
    "Allen","Young","Hernandez","King","Wright","Lopez","Hill","Scott",
    "Green","Adams","Baker","Gonzalez","Nelson","Carter","Mitchell","Perez",
    "Roberts","Turner","Phillips","Campbell","Parker","Evans","Edwards","Collins",
    "Stewart","Sanchez",
]
_CITIES_STATES = [
    ("Chicago", "IL"), ("Detroit", "MI"), ("Houston", "TX"), ("Phoenix", "AZ"),
    ("Philadelphia", "PA"), ("San Antonio", "TX"), ("Dallas", "TX"), ("Jacksonville", "FL"),
    ("Columbus", "OH"), ("Indianapolis", "IN"), ("Memphis", "TN"), ("Louisville", "KY"),
    ("Baltimore", "MD"), ("Milwaukee", "WI"), ("Albuquerque", "NM"), ("Kansas City", "MO"),
    ("Atlanta", "GA"), ("Miami", "FL"), ("Minneapolis", "MN"), ("Cleveland", "OH"),
]

# ---------------------------------------------------------------------------
# SOAP note template generator
# ---------------------------------------------------------------------------

def _build_soap(
    patient_fname: str,
    patient_age: int,
    patient_sex: str,
    template: ConditionTemplate,
    encounter_number: int,
    encounter_date: datetime,
    code_quality: float,
    vitals: dict,
    labs: list[dict],
) -> dict[str, str]:
    """
    Generate a realistic SOAP note for an encounter.
    """
    sex_word   = "male" if patient_sex == "Male" else "female"
    pronouns   = ("he", "his", "him") if patient_sex == "Male" else ("she", "her", "her")
    visit_type = "initial" if encounter_number == 1 else "follow-up"

    # Build objective labs string
    lab_str = ", ".join(
        f"{l['name']} {l['value']}" + (" [ABNORMAL]" if l.get("flag") not in ("N", None) else "")
        for l in labs[:6]
    )

    # Build vitals string
    v = vitals
    vitals_str = (
        f"BP {v.get('bp','--')}, HR {v.get('hr','--')}, "
        f"RR {v.get('rr','--')}, SpO2 {v.get('spo2','--')}%, "
        f"Weight {v.get('weight','--')} lbs, BMI {v.get('bmi','--')}"
    )

    # Assessment builds differently for good vs poor coders
    good_assessment_lines = "\n".join(
        f"{i + 1}. {desc} – evaluated and managed this encounter."
        for i, (code, desc) in enumerate(template.full_icd10_codes)
    )
    poor_assessment_lines = "\n".join(
        f"{i + 1}. {desc}."
        for i, (code, desc) in enumerate(template.under_coded_icd10 or template.full_icd10_codes[:1])
    )
    is_good_coder = (code_quality >= 0.75)
    assessment_text = good_assessment_lines if is_good_coder else poor_assessment_lines

    subj = (
        f"{patient_age}-year-old {sex_word} with {template.name.lower()} presents for "
        f"{visit_type} management. {pronouns[0].capitalize()} reports stable symptoms. "
        f"Medication compliance confirmed. No hospitalizations since last visit."
    )
    obj  = f"VS: {vitals_str}.\nLabs: {lab_str}."
    plan = (
        f"1. Continue current medication regimen.\n"
        f"2. Labs to be repeated in 3 months.\n"
        f"3. Follow up in 12 weeks or sooner if symptoms worsen.\n"
        f"4. Patient education provided regarding {template.name.lower()}."
    )

    return {
        "subjective":  subj,
        "objective":   obj,
        "assessment":  assessment_text,
        "plan":        plan,
    }


# ---------------------------------------------------------------------------
# Encounter date generator
# Spreads 3-8 encounters across a 2-year window (2024-01-01 to 2025-12-31)
# ---------------------------------------------------------------------------

def _generate_encounter_dates(n: int, base_year: int = 2024) -> list[datetime]:
    start = datetime(base_year, 1, 15, 9, 0)
    end   = datetime(base_year + 1, 11, 30, 16, 0)
    total_days = (end - start).days
    raw_offsets = sorted(RNG.randint(0, total_days) for _ in range(n))
    # Ensure at least 30 days between encounters
    dates: list[datetime] = []
    last_day = -999
    for off in raw_offsets:
        if off - last_day >= 30:
            hour = RNG.randint(8, 16)
            minute = RNG.choice([0, 15, 30, 45])
            dates.append(start + timedelta(days=off, hours=hour - 9, minutes=minute))
            last_day = off
    # If we ended up with fewer than n, pad from end of period
    while len(dates) < n:
        dates.append(end - timedelta(days=RNG.randint(5, 30)))
    return dates[:n]


# ---------------------------------------------------------------------------
# Vitals generator
# ---------------------------------------------------------------------------

def _generate_vitals(template: ConditionTemplate, age: int) -> dict:
    base_systolic = 130 if not template.hcc_codes else 145
    # CHF patients heavier
    base_weight = 185 if 85 in template.hcc_codes else 170
    base_bmi    = 32.0 if 22 in template.hcc_codes else 27.5

    return {
        "bp":     f"{base_systolic + RNG.randint(-8, 12)}/{80 + RNG.randint(-6, 10)}",
        "hr":     str(70 + RNG.randint(-8, 20)),
        "rr":     str(16 + RNG.randint(0, 6)),
        "spo2":   str(92 + RNG.randint(0, 6)) if 111 in template.hcc_codes else str(96 + RNG.randint(-2, 2)),
        "temp":   "98.6",
        "weight": str(base_weight + RNG.randint(-20, 30)),
        "bmi":    f"{base_bmi + RNG.uniform(-2.0, 4.0):.1f}",
    }


# ---------------------------------------------------------------------------
# Build the 50 patient definitions
# ---------------------------------------------------------------------------

def _build_patient_pool() -> list[dict]:
    patients: list[dict] = []

    # Assign condition templates in a realistic mix
    # 50 patients: distribute across templates with some having multiple conditions
    template_assignments = (
        [0] * 7   +   # DM2 + CKD + Neuropathy (most common)
        [1] * 6   +   # CHF + AFib
        [2] * 5   +   # COPD
        [3] * 5   +   # DM2 + Retinopathy
        [4] * 4   +   # Morbid Obesity
        [5] * 3   +   # Depression
        [6] * 3   +   # RA
        [7] * 4   +   # CKD4
        [8] * 3   +   # Stroke sequela
        [9] * 2   +   # HIV
        [10] * 2  +   # Malnutrition
        [11] * 3  +   # DM2 + PVD
        [12] * 2  +   # Hypertension only (low RAF comparison)
        [13] * 1      # Schizophrenia
    )
    RNG.shuffle(template_assignments)

    for i in range(50):
        is_male = RNG.choice([True, False, True])  # slight male bias
        sex_str = "Male" if is_male else "Female"
        fname_pool = _FIRST_NAMES_M if is_male else _FIRST_NAMES_F
        fname = fname_pool[i % len(fname_pool)]
        lname = _LAST_NAMES[i % len(_LAST_NAMES)]
        city, state = _CITIES_STATES[i % len(_CITIES_STATES)]

        tmpl_idx = template_assignments[i]
        template = CONDITION_TEMPLATES[tmpl_idx]

        # Age: higher for CHF, CKD, stroke; lower for HIV, RA, depression
        if tmpl_idx in (1, 7, 8):        # CHF, CKD4, stroke
            age = RNG.randint(68, 90)
        elif tmpl_idx in (5, 6, 9, 13):  # depression, RA, HIV, schizophrenia
            age = RNG.randint(35, 65)
        elif tmpl_idx == 10:             # malnutrition
            age = RNG.randint(75, 95)
        else:
            age = RNG.randint(55, 82)

        dob_year  = datetime.today().year - age
        dob_month = RNG.randint(1, 12)
        dob_day   = RNG.randint(1, 28)
        dob       = date(dob_year, dob_month, dob_day)

        # Dual eligibility: older, poorer-health patients more likely dual
        is_dual = RNG.random() < (0.45 if age >= 70 else 0.20)
        dual_type = RNG.choice(["full", "partial"]) if is_dual else "non_dual"

        # Provider assignment — distribute across 5 providers
        # Provider quality affects coding gaps
        provider = PROVIDERS[i % len(PROVIDERS)]

        n_encounters = RNG.randint(3, 8)

        patients.append({
            "index":        i,
            "fname":        fname,
            "lname":        lname,
            "sex":          sex_str,
            "dob":          dob,
            "city":         city,
            "state":        state,
            "age":          age,
            "is_dual":      is_dual,
            "dual_type":    dual_type,
            "template":     template,
            "provider":     provider,
            "n_encounters": n_encounters,
        })

    return patients


# ---------------------------------------------------------------------------
# DB insert helpers
# ---------------------------------------------------------------------------

def _next_id(cursor, table: str, id_col: str) -> int:
    cursor.execute(f"SELECT COALESCE(MAX({id_col}), 0) + 1 FROM {table};")
    row = cursor.fetchone()
    return row[0] if row else 1


def _insert_provider(cursor, prov: Provider) -> None:
    cursor.execute(
        """
        INSERT INTO users
            (id, username, fname, lname, authorized, active, npi)
        VALUES (%s, %s, %s, %s, 1, 1, %s)
        ON DUPLICATE KEY UPDATE fname = VALUES(fname), lname = VALUES(lname);
        """,
        (prov.provider_id, f"demo_{prov.lname.lower()}",
         prov.fname, prov.lname, prov.npi),
    )


def _insert_patient(cursor, pid: int, p: dict) -> None:
    cursor.execute(
        """
        INSERT INTO patient_data
            (pid, pubpid, fname, lname, DOB, sex, city, state,
             date, street, postal_code, country_code,
             phone_home, phone_cell, status)
        VALUES
            (%s, %s, %s, %s, %s, %s, %s, %s,
             NOW(), '', '00000', 'US',
             '555-000-0000', '555-000-0000', 'active')
        ON DUPLICATE KEY UPDATE lname = VALUES(lname);
        """,
        (pid, f"DEMO{pid:04d}", p["fname"], p["lname"],
         p["dob"].strftime("%Y-%m-%d"), p["sex"], p["city"], p["state"]),
    )


def _insert_encounter(cursor, enc_id: int, pid: int, enc_date: datetime,
                      reason: str, provider_id: int) -> None:
    cursor.execute(
        """
        INSERT INTO form_encounter
            (encounter, pid, date, reason, facility_id, provider_id, class_code, pc_catid)
        VALUES (%s, %s, %s, %s, %s, %s, 'AMB', 5)
        ON DUPLICATE KEY UPDATE reason = VALUES(reason);
        """,
        (enc_id, pid, enc_date.strftime("%Y-%m-%d %H:%M:%S"),
         reason[:255], FACILITY_ID, provider_id),
    )


def _insert_billing(cursor, pid: int, enc_id: int, enc_date: datetime,
                    diagnoses: list[tuple[str, str]], provider_id: int) -> None:
    for code, code_text in diagnoses:
        cursor.execute(
            """
            INSERT INTO billing
                (pid, encounter, date, code_type, code, code_text,
                 authorized, activity, billed, provider_id)
            VALUES (%s, %s, %s, 'ICD10', %s, %s, 1, 1, 0, %s)
            ON DUPLICATE KEY UPDATE code_text = VALUES(code_text);
            """,
            (pid, enc_id, enc_date.strftime("%Y-%m-%d %H:%M:%S"),
             code, code_text[:255], provider_id),
        )


def _insert_soap(cursor, soap_id: int, pid: int, enc_date: datetime,
                 soap: dict) -> None:
    cursor.execute(
        """
        INSERT INTO form_soap
            (id, pid, date, user, groupname, authorized, activity,
             subjective, objective, assessment, plan)
        VALUES (%s, %s, %s, 'admin', 'Default', 1, 1, %s, %s, %s, %s)
        ON DUPLICATE KEY UPDATE assessment = VALUES(assessment);
        """,
        (soap_id, pid, enc_date.strftime("%Y-%m-%d %H:%M:%S"),
         soap["subjective"][:4000], soap["objective"][:4000],
         soap["assessment"][:4000], soap["plan"][:4000]),
    )


def _insert_forms_registry(cursor, pid: int, enc_id: int,
                            soap_id: int, enc_date: datetime) -> None:
    cursor.execute(
        """
        INSERT INTO forms
            (pid, encounter, form_name, form_id, date, user,
             groupname, authorized, deleted, formdir)
        VALUES (%s, %s, 'SOAP', %s, %s, 'admin', 'Default', 1, 0, 'soap')
        ON DUPLICATE KEY UPDATE form_id = VALUES(form_id);
        """,
        (pid, enc_id, soap_id, enc_date.strftime("%Y-%m-%d %H:%M:%S")),
    )


def _insert_prescription(cursor, pid: int, enc_id: int, enc_date: datetime,
                          drug: str, dosage: str, sig: str,
                          provider_id: int) -> None:
    cursor.execute(
        """
        INSERT INTO prescriptions
            (patient_id, encounter, drug, dosage, note,
             date_added, active, provider_id,
             txDate, usage_category_title, request_intent_title)
        VALUES (%s, %s, %s, %s, %s, %s, 1, %s, %s, %s, %s)
        """,
        (pid, enc_id, drug[:150], dosage[:100], sig,
         enc_date.strftime("%Y-%m-%d %H:%M:%S"),
         provider_id,
         enc_date.strftime("%Y-%m-%d"),
         "Chronic",
         "order"),
    )


# ---------------------------------------------------------------------------
# RAF Intelligence DB helpers
# ---------------------------------------------------------------------------

def _ensure_benchmark_table(raf_cursor) -> None:
    """Create the benchmark_runs table if it does not exist."""
    raf_cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS benchmark_runs (
            id              INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
            run_id          VARCHAR(36)  NOT NULL UNIQUE,
            run_timestamp   VARCHAR(32)  NOT NULL,
            suite_version   VARCHAR(20)  NOT NULL,
            total_cases     INT          NOT NULL DEFAULT 0,
            icd10_f1        FLOAT        NOT NULL DEFAULT 0,
            hcc_f1          FLOAT        NOT NULL DEFAULT 0,
            hcc_capture_rate FLOAT       NOT NULL DEFAULT 0,
            raf_mae         FLOAT        NOT NULL DEFAULT 0,
            raf_within_range_rate FLOAT  NOT NULL DEFAULT 0,
            duration_seconds FLOAT       NOT NULL DEFAULT 0,
            result_json     MEDIUMTEXT,
            created_at      TIMESTAMP    DEFAULT CURRENT_TIMESTAMP,
            INDEX idx_timestamp (run_timestamp)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
        """
    )


def _insert_demo_raf_score(raf_cursor, pid: int, p: dict,
                            year: int, raf_score: float, hcc_codes: list[int]) -> None:
    """Insert a pre-calculated RAF score into the RAF Intelligence DB."""
    raf_cursor.execute(
        """
        INSERT INTO patient_raf_scores
            (pid, payment_year, raf_score, hcc_codes, model_version, calculated_at, notes)
        VALUES (%s, %s, %s, %s, 'V28', NOW(), %s)
        ON DUPLICATE KEY UPDATE
            raf_score  = VALUES(raf_score),
            hcc_codes  = VALUES(hcc_codes),
            calculated_at = NOW()
        """,
        (pid, year,
         round(raf_score, 4),
         json.dumps(hcc_codes),
         f"Demo seed — {p['template'].name}"),
    )


# ---------------------------------------------------------------------------
# Main seeder
# ---------------------------------------------------------------------------

def seed(dry_run: bool = False, openemr_port: int = 3309, raf_port: int = 3310) -> None:
    log.info("=== RAF Intelligence Demo Environment Seeder ===")
    log.info("dry_run=%s  openemr_port=%d  raf_port=%d", dry_run, openemr_port, raf_port)

    patients_data = _build_patient_pool()

    if dry_run:
        log.info("[DRY RUN] Would create %d patients with %d providers.",
                 len(patients_data), len(PROVIDERS))
        for p in patients_data[:5]:
            log.info("  Sample: %s %s (%s, age %d) — %s — provider: Dr. %s",
                     p["fname"], p["lname"], p["sex"], p["age"],
                     p["template"].name, p["provider"].lname)
        log.info("  [DRY RUN] Exiting without writing to DB.")
        return

    # ------------------------------------------------------------------
    # Connect to OpenEMR
    # ------------------------------------------------------------------
    log.info("Connecting to OpenEMR at 127.0.0.1:%d ...", openemr_port)
    openemr_cfg = {**OPENEMR_DB, "port": openemr_port}
    try:
        oconn = mysql.connector.connect(**openemr_cfg)
    except MySQLError as exc:
        log.error("Cannot connect to OpenEMR: %s", exc)
        sys.exit(1)
    ocursor = oconn.cursor()

    # ------------------------------------------------------------------
    # Connect to RAF Intelligence DB (optional — skip if unavailable)
    # ------------------------------------------------------------------
    raf_cfg = {**RAF_DB, "port": raf_port}
    rconn: Any = None
    rcursor: Any = None
    try:
        rconn = mysql.connector.connect(**raf_cfg)
        rcursor = rconn.cursor()
        _ensure_benchmark_table(rcursor)
        rconn.commit()
        log.info("RAF Intelligence DB connected.")
    except MySQLError as exc:
        log.warning("RAF Intelligence DB unavailable (non-fatal): %s", exc)
        rconn = None
        rcursor = None

    # ------------------------------------------------------------------
    # Seed providers
    # ------------------------------------------------------------------
    log.info("Seeding %d providers ...", len(PROVIDERS))
    for prov in PROVIDERS:
        try:
            _insert_provider(ocursor, prov)
        except MySQLError as exc:
            log.warning("Provider %s insert warn: %s", prov.lname, exc)
    oconn.commit()

    # ------------------------------------------------------------------
    # Seed patients
    # ------------------------------------------------------------------
    total_patients   = 0
    total_encounters = 0
    total_billing    = 0
    total_soaps      = 0
    total_rx         = 0
    total_raf_rows   = 0

    log.info("Seeding %d patients ...", len(patients_data))

    for p in patients_data:
        # --- patient_data ---
        pid = _next_id(ocursor, "patient_data", "pid")
        try:
            _insert_patient(ocursor, pid, p)
            total_patients += 1
        except MySQLError as exc:
            log.warning("Patient insert failed: %s", exc)
            oconn.rollback()
            continue

        template: ConditionTemplate = p["template"]
        provider: Provider = p["provider"]
        n_enc = p["n_encounters"]
        enc_dates = _generate_encounter_dates(n_enc)

        # Decide coding quality per encounter (some variance around provider quality)
        def _enc_quality() -> float:
            return max(0.0, min(1.0, provider.coding_quality + RNG.gauss(0, 0.10)))

        year_raf_scores: dict[int, float] = {}

        for enc_idx, enc_date in enumerate(enc_dates):
            enc_id = _next_id(ocursor, "form_encounter", "encounter")
            reason = f"{template.name} — {'initial' if enc_idx == 0 else 'follow-up'} visit"

            try:
                _insert_encounter(ocursor, enc_id, pid, enc_date, reason, provider.provider_id)
                total_encounters += 1
            except MySQLError as exc:
                log.warning("Encounter insert warn: %s", exc)
                continue

            # Decide billing codes based on coding quality
            enc_quality = _enc_quality()
            if enc_quality >= 0.75 or not template.under_coded_icd10:
                billing_codes = template.full_icd10_codes
            else:
                # Under-coder: use only the simplified subset
                billing_codes = template.under_coded_icd10

            try:
                _insert_billing(ocursor, pid, enc_id, enc_date,
                                billing_codes, provider.provider_id)
                total_billing += len(billing_codes)
            except MySQLError as exc:
                log.warning("Billing insert warn: %s", exc)

            # SOAP note
            vitals = _generate_vitals(template, p["age"])
            soap_dict = _build_soap(
                patient_fname=p["fname"],
                patient_age=p["age"],
                patient_sex=p["sex"],
                template=template,
                encounter_number=enc_idx + 1,
                encounter_date=enc_date,
                code_quality=enc_quality,
                vitals=vitals,
                labs=template.lab_flags,
            )
            soap_id = _next_id(ocursor, "form_soap", "id")
            try:
                _insert_soap(ocursor, soap_id, pid, enc_date, soap_dict)
                _insert_forms_registry(ocursor, pid, enc_id, soap_id, enc_date)
                total_soaps += 1
            except MySQLError as exc:
                log.warning("SOAP insert warn: %s", exc)

            # Medications
            for drug, dosage, sig in template.medications:
                try:
                    _insert_prescription(ocursor, pid, enc_id, enc_date,
                                         drug, dosage, sig, provider.provider_id)
                    total_rx += 1
                except MySQLError as exc:
                    log.warning("Rx insert warn: %s", exc)

            # Track RAF by year for trends
            year = enc_date.year
            # Good coders capture full RAF; poor coders miss some
            captured_raf = template.raf_estimate * (0.60 + 0.40 * enc_quality)
            year_raf_scores[year] = max(year_raf_scores.get(year, 0.0),
                                        round(0.80 + captured_raf, 4))

        oconn.commit()

        # Pre-calculated RAF scores per year into RAF Intelligence DB
        if rcursor:
            for year, raf_score in year_raf_scores.items():
                try:
                    _insert_demo_raf_score(
                        rcursor, pid, p, year, raf_score,
                        template.hcc_codes,
                    )
                    total_raf_rows += 1
                except MySQLError as exc:
                    log.warning("RAF score insert warn (pid=%d, year=%d): %s",
                                pid, year, exc)
            rconn.commit()

        log.info(
            "  [%02d/50] %s %s | age=%d | %s | %d enc | provider: Dr. %s (quality=%.0f%%)",
            p["index"] + 1, p["fname"], p["lname"],
            p["age"], template.name, n_enc, provider.lname,
            provider.coding_quality * 100,
        )

    ocursor.close()
    oconn.close()
    if rcursor:
        rcursor.close()
        rconn.close()

    log.info("")
    log.info("=== Demo Environment Seeded Successfully ===")
    log.info("  Patients:       %d", total_patients)
    log.info("  Encounters:     %d", total_encounters)
    log.info("  Billing rows:   %d", total_billing)
    log.info("  SOAP notes:     %d", total_soaps)
    log.info("  Prescriptions:  %d", total_rx)
    log.info("  RAF score rows: %d", total_raf_rows)
    log.info("")
    log.info("Provider coding quality summary:")
    for prov in PROVIDERS:
        log.info(
            "  Dr. %-20s %-20s quality=%.0f%%",
            f"{prov.fname} {prov.lname}",
            prov.specialty,
            prov.coding_quality * 100,
        )
    log.info("")
    log.info("Condition mix:")
    from collections import Counter
    counts: Counter = Counter()
    patients_data_regen = _build_patient_pool()
    for pd in patients_data_regen:
        counts[pd["template"].name] += 1
    for name, cnt in counts.most_common():
        log.info("  %-45s %d patients", name, cnt)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Seed the RAF Intelligence demo environment with 50 synthetic patients."
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Print what would be seeded without writing to the database.",
    )
    parser.add_argument(
        "--openemr-port", type=int, default=3309,
        help="OpenEMR MySQL port (default: 3309)",
    )
    parser.add_argument(
        "--raf-port", type=int, default=3310,
        help="RAF Intelligence MySQL port (default: 3310)",
    )
    args = parser.parse_args()
    seed(dry_run=args.dry_run, openemr_port=args.openemr_port, raf_port=args.raf_port)


if __name__ == "__main__":
    main()
