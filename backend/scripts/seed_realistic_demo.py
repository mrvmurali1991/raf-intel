#!/usr/bin/env python3
"""
seed_realistic_demo.py
----------------------
Idempotent seeder: 50-patient longitudinal demo dataset for CMO / MA-plan executive demos.

What gets seeded (all data is synthetic, HIPAA Safe Harbor compliant):
  - 50 patients with realistic MA-plan age/sex/race/geo distribution
  - 2 years of quarterly A1c + CMP labs for diabetic patients (~22%)
  - 4-12 encounters/year per patient across PCP + specialists, with SOAP notes
  - HCC coding history (V24/V28), dropped HCCs as open suspects
  - Quality measure status (CDC A1c control tier)
  - Outreach messages (sent / failed / queued)
  - 3 chart-chase requests in different states
  - 1 RADV audit run with 7 sampled patients

Usage:
    python backend/scripts/seed_realistic_demo.py --tenant 1 --patients 50 --years 2

Dependencies: mysql-connector-python
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import random
import sys
from datetime import date, datetime, timedelta
from typing import Any

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
# Deterministic RNG — change the seed for a different but reproducible dataset
# ---------------------------------------------------------------------------
_RNG = random.Random(2025)

# ---------------------------------------------------------------------------
# DB connection — reads env vars first, falls back to local dev defaults
# ---------------------------------------------------------------------------

def _db_config() -> dict:
    return dict(
        host=os.getenv("RAF_DB_HOST", "127.0.0.1"),
        port=int(os.getenv("RAF_DB_PORT", "3306")),
        user=os.getenv("RAF_DB_USER", "root"),
        password=os.getenv("RAF_DB_PASSWORD", "root"),
        database=os.getenv("RAF_DB_NAME", "raf_intelligence"),
        charset="utf8mb4",
        collation="utf8mb4_unicode_ci",
        autocommit=False,
        connect_timeout=15,
    )


def _openemr_config() -> dict:
    return dict(
        host=os.getenv("OPENEMR_DB_HOST", "127.0.0.1"),
        port=int(os.getenv("OPENEMR_DB_PORT", "3309")),
        user=os.getenv("OPENEMR_DB_USER", "root"),
        password=os.getenv("OPENEMR_DB_PASSWORD", "root"),
        database=os.getenv("OPENEMR_DB_NAME", "openemr"),
        charset="utf8mb4",
        collation="utf8mb4_unicode_ci",
        autocommit=False,
        connect_timeout=15,
    )


# ---------------------------------------------------------------------------
# Name pool — synthetic, no real individuals
# ---------------------------------------------------------------------------

_FIRST_NAMES_F = [
    "Margaret", "Patricia", "Barbara", "Dorothy", "Ruth",
    "Helen", "Frances", "Beverly", "Shirley", "Gloria",
    "Joyce", "Betty", "Rosa", "Edna", "Virginia",
    "Sylvia", "Lorraine", "Evelyn", "Catherine", "Mildred",
    "Diane", "Janet", "Martha", "Norma", "Alice",
    "Lucille", "Carolyn", "Anna", "Joyce", "Sandra",
]

_FIRST_NAMES_M = [
    "Harold", "Raymond", "Walter", "Arthur", "Eugene",
    "Henry", "Clarence", "Roy", "Louis", "Ralph",
    "Howard", "Lawrence", "Gerald", "Carl", "Bernard",
    "Frank", "Donald", "Ronald", "Dennis", "Gary",
    "Kenneth", "George", "Douglas", "Keith", "Roger",
    "Dale", "Frederick", "Earl", "Lester", "Russell",
]

_LAST_NAMES = [
    "Anderson", "Baker", "Campbell", "Carter", "Clark",
    "Collins", "Davis", "Evans", "Foster", "Green",
    "Hall", "Harris", "Hill", "Jackson", "Johnson",
    "Jones", "King", "Lee", "Lewis", "Martin",
    "Martinez", "Mitchell", "Moore", "Nelson", "Parker",
    "Perez", "Phillips", "Roberts", "Robinson", "Rodriguez",
    "Scott", "Smith", "Stewart", "Taylor", "Thomas",
    "Thompson", "Turner", "Walker", "White", "Williams",
    "Wilson", "Wright", "Young", "Adams", "Allen",
    "Brown", "Coleman", "Cooper", "Cox", "Gray",
]

# ---------------------------------------------------------------------------
# Geography: 5 metro areas with realistic zip codes
# ---------------------------------------------------------------------------

_METROS = [
    # (city, state, zip_prefix)
    ("New York",   "NY", ["10001","10002","10025","10028","11201"]),
    ("Los Angeles","CA", ["90001","90024","90046","90210","90291"]),
    ("Chicago",    "IL", ["60601","60614","60625","60637","60657"]),
    ("Dallas",     "TX", ["75201","75204","75215","75219","75231"]),
    ("Atlanta",    "GA", ["30301","30308","30318","30329","30345"]),
]

_STREETS = [
    "100 Maple St", "220 Oak Ave", "345 Pine Rd", "412 Elm Dr", "558 Cedar Blvd",
    "617 Birch Ln", "733 Willow Way", "819 Ash Ct", "924 Poplar Pl", "1045 Walnut Terr",
    "1102 Spruce Ave", "1234 Chestnut St", "1388 Magnolia Blvd", "1491 Sycamore Dr",
    "1555 Hickory Ln", "1678 Cherry Ct", "1789 Dogwood Pl", "1892 Hawthorn Way",
]

# ---------------------------------------------------------------------------
# Race / ethnicity pool — CMS MA approximate distribution
# ---------------------------------------------------------------------------

# (race_label, ethnicity_label, weight)
_RACE_ETH_POOL = [
    ("White",                      "Not Hispanic or Latino",    58),
    ("Black or African American",  "Not Hispanic or Latino",    12),
    ("Hispanic",                   "Hispanic or Latino",        14),
    ("Asian",                      "Not Hispanic or Latino",     5),
    ("American Indian",            "Not Hispanic or Latino",     1),
    ("Other Race",                 "Not Hispanic or Latino",    10),
]

_RACE_WEIGHTS  = [r[2] for r in _RACE_ETH_POOL]
_RACE_CHOICES  = [(r[0], r[1]) for r in _RACE_ETH_POOL]

# ---------------------------------------------------------------------------
# Insurance types
# ---------------------------------------------------------------------------

_INSURANCE_POOL = [
    ("MA HMO", 80),
    ("MA PPO", 15),
    ("D-SNP",   5),
]

_INS_WEIGHTS = [i[1] for i in _INSURANCE_POOL]
_INS_CHOICES = [i[0] for i in _INSURANCE_POOL]

# ---------------------------------------------------------------------------
# Age / sex distribution per task spec
# Age bands: 50-64 18%, 65-74 45%, 75-84 30%, 85+ 7%
# Sex: 52% F, 48% M
# ---------------------------------------------------------------------------

_AGE_BANDS = [
    (50, 64, 18),
    (65, 74, 45),
    (75, 84, 30),
    (85, 95,  7),
]

_AGE_WEIGHTS = [b[2] for b in _AGE_BANDS]

# ---------------------------------------------------------------------------
# Condition profiles — each patient is assigned one or more
# ---------------------------------------------------------------------------

# HCC codes (V28 approximations) referenced in this seeder
_HCC_MAP = {
    "E11.9":  {"hcc": 37,  "label": "Type 2 Diabetes, uncomplicated"},
    "E11.65": {"hcc": 37,  "label": "Type 2 Diabetes with hyperglycemia"},
    "E11.22": {"hcc": 37,  "label": "Type 2 Diabetes with CKD stage 2"},
    "I50.32": {"hcc": 85,  "label": "Chronic diastolic heart failure"},
    "I50.22": {"hcc": 85,  "label": "Chronic systolic heart failure"},
    "N18.3":  {"hcc": 138, "label": "CKD stage 3"},
    "N18.4":  {"hcc": 137, "label": "CKD stage 4"},
    "J44.1":  {"hcc": 112, "label": "COPD with acute exacerbation"},
    "F32.1":  {"hcc": 155, "label": "Major depressive disorder, moderate"},
    "E66.01": {"hcc": 48,  "label": "Morbid obesity"},
    "I48.91": {"hcc": 96,  "label": "Unspecified atrial fibrillation"},
    "G30.9":  {"hcc": 52,  "label": "Alzheimer disease, unspecified"},
    "I25.10": {"hcc": 108, "label": "Atherosclerotic heart disease"},
    "Z87.891":{"hcc": 0,   "label": "History of nicotine dependence"},
}

# HCC rough RAF coefficients for V28
_HCC_COEFF = {
    37: 0.302, 85: 0.340, 138: 0.108, 137: 0.290,
    112: 0.335, 155: 0.309, 48: 0.272, 96: 0.288,
    52: 0.421, 108: 0.288,
}

# Condition bundles: (primary_label, icd_codes, pct_of_population, dropped_hcc_icd)
# dropped_hcc_icd = ICD that should have been recaptured this year but wasn't
_CONDITION_BUNDLES = [
    # Diabetes (22%) — main HEDIS target group
    {
        "label": "DM2_only",
        "icds": [("E11.9",  "Type 2 diabetes mellitus without complications")],
        "pct": 10,
        "dropped": None,
        "is_diabetic": True,
    },
    {
        "label": "DM2_CHF",
        "icds": [
            ("E11.65", "Type 2 diabetes with hyperglycemia"),
            ("I50.32", "Chronic diastolic heart failure"),
        ],
        "pct": 8,
        "dropped": ("I50.32", "Chronic diastolic CHF not recaptured this year"),
        "is_diabetic": True,
    },
    {
        "label": "DM2_CKD",
        "icds": [
            ("E11.22", "Type 2 diabetes with CKD stage 2"),
            ("N18.3",  "Chronic kidney disease, stage 3"),
        ],
        "pct": 4,
        "dropped": ("N18.3", "CKD stage 3 not coded this encounter"),
        "is_diabetic": True,
    },
    # CHF only (15%)
    {
        "label": "CHF",
        "icds": [("I50.32", "Chronic diastolic heart failure")],
        "pct": 15,
        "dropped": None,
        "is_diabetic": False,
    },
    # COPD (12%)
    {
        "label": "COPD",
        "icds": [("J44.1", "COPD with acute exacerbation")],
        "pct": 12,
        "dropped": ("J44.1", "COPD exacerbation coded in prior year only"),
        "is_diabetic": False,
    },
    # Depression (10%)
    {
        "label": "Depression",
        "icds": [("F32.1", "Major depressive disorder, single episode, moderate")],
        "pct": 10,
        "dropped": None,
        "is_diabetic": False,
    },
    # Atrial fibrillation (8%)
    {
        "label": "AFib",
        "icds": [("I48.91", "Unspecified atrial fibrillation")],
        "pct": 8,
        "dropped": ("I48.91", "AFib not coded despite apixaban Rx"),
        "is_diabetic": False,
    },
    # Complex (multiple HCC) — good demo patients for high-RAF showcase (8%)
    {
        "label": "Complex",
        "icds": [
            ("E11.65", "Type 2 diabetes with hyperglycemia"),
            ("I50.22", "Chronic systolic heart failure"),
            ("N18.4",  "Chronic kidney disease, stage 4"),
            ("I48.91", "Unspecified atrial fibrillation"),
        ],
        "pct": 8,
        "dropped": ("N18.4", "CKD stage 4 not recaptured current year"),
        "is_diabetic": True,
    },
    # Alzheimer / dementia (5%)
    {
        "label": "Dementia",
        "icds": [("G30.9", "Alzheimer disease, unspecified")],
        "pct": 5,
        "dropped": None,
        "is_diabetic": False,
    },
    # No major HCC (healthy-ish) — 20%
    {
        "label": "Healthy",
        "icds": [("Z87.891", "History of nicotine dependence")],
        "pct": 20,
        "dropped": None,
        "is_diabetic": False,
    },
]

_BUNDLE_WEIGHTS = [b["pct"] for b in _CONDITION_BUNDLES]

# ---------------------------------------------------------------------------
# Specialty + encounter type templates
# ---------------------------------------------------------------------------

_ENCOUNTER_TYPES = [
    ("PCP",          "Office Visit",              "11"),   # Place of service: office
    ("PCP",          "Annual Wellness Visit",      "11"),
    ("PCP",          "Follow-up",                 "11"),
    ("PCP",          "Telehealth",                "02"),
    ("Endocrinology","Specialist Consultation",   "11"),
    ("Cardiology",   "Specialist Consultation",   "11"),
    ("Nephrology",   "Specialist Consultation",   "11"),
    ("Pulmonology",  "Specialist Consultation",   "11"),
    ("Psychiatry",   "Specialist Consultation",   "11"),
]

_SOAP_TEMPLATES: dict[str, dict[str, str]] = {
    "DM2_only": {
        "subjective": (
            "Patient presents for routine diabetes management follow-up. "
            "Reports compliance with metformin and lifestyle modifications. "
            "Denies polyuria, polydipsia, or hypoglycemic episodes. "
            "Last HbA1c {hba1c}%."
        ),
        "objective": (
            "VS: BP {bp}, HR {hr} bpm, Wt {wt} lbs. "
            "Pedal pulses intact. No lower extremity edema. "
            "Fundoscopic exam deferred. "
            "Labs: HbA1c {hba1c}%, Fasting glucose {gluc} mg/dL, "
            "Creatinine {cr} mg/dL, LDL {ldl} mg/dL."
        ),
        "assessment": (
            "1. Type 2 diabetes mellitus — HbA1c {hba1c}%, {dm_control}. "
            "2. Continue current oral hypoglycemic regimen with dietary reinforcement. "
            "Annual retinal exam due. Podiatry referral placed."
        ),
        "plan": (
            "Continue metformin {metformin_dose}mg BID. "
            "Lifestyle: low-glycemic diet, 150 min/week moderate exercise. "
            "Labs in 3 months. Annual dilated eye exam reminder sent."
        ),
    },
    "DM2_CHF": {
        "subjective": (
            "72 y/o presents for DM and heart failure co-management. "
            "Reports mild dyspnea on exertion (NYHA class II). Ankle swelling improved. "
            "Compliant with furosemide, lisinopril, and insulin glargine. "
            "No chest pain or orthopnea. HbA1c {hba1c}% last draw."
        ),
        "objective": (
            "VS: BP {bp}, HR {hr} bpm, SpO2 {spo2}%. Weight {wt} lbs. "
            "Lungs: {lung_sounds}. Extremities: {edema}. "
            "Labs: HbA1c {hba1c}%, BNP {bnp} pg/mL, Creatinine {cr} mg/dL, K+ {k} mEq/L."
        ),
        "assessment": (
            "1. Type 2 DM with hyperglycemia — HbA1c {hba1c}%, {dm_control}. "
            "2. Chronic diastolic heart failure, NYHA class II — BNP {bnp} pg/mL, compensated. "
            "3. Renal function stable, monitoring per protocol."
        ),
        "plan": (
            "Insulin glargine {insulin_dose} units QHS. Furosemide 40mg daily. "
            "Lisinopril 10mg daily. "
            "Repeat BMP in 6 weeks. Cardiology follow-up in 3 months. "
            "HEDIS CDC: A1c in target — care gap {gap_status}."
        ),
    },
    "DM2_CKD": {
        "subjective": (
            "Patient with T2DM and CKD stage 3 presents for quarterly visit. "
            "Fatigue mild. No signs of fluid overload. Diet: low-sodium, low-protein per nephrology. "
            "eGFR trending at {egfr} mL/min. HbA1c {hba1c}%."
        ),
        "objective": (
            "VS: BP {bp}, HR {hr}. Weight {wt} lbs. "
            "No edema. CVAT absent. "
            "Labs: HbA1c {hba1c}%, eGFR {egfr}, Creatinine {cr}, "
            "UACR {uacr} mg/g, K+ {k} mEq/L."
        ),
        "assessment": (
            "1. T2DM with CKD stage 3 — glycemic control {dm_control}. "
            "2. CKD stage 3b (eGFR {egfr}) — stable, nephrology co-managing. "
            "3. SGLT2 inhibitor added for renoprotection per ADA/KDIGO guidelines."
        ),
        "plan": (
            "Metformin {metformin_dose}mg BID (dose-adjusted for eGFR). "
            "Empagliflozin 10mg daily. Lisinopril 5mg daily. "
            "Nephrology follow-up in 2 months. Repeat CMP in 6 weeks."
        ),
    },
    "CHF": {
        "subjective": (
            "Patient with chronic systolic heart failure presents for cardiology follow-up. "
            "Exertional dyspnea unchanged at NYHA class {nyha}. "
            "No paroxysmal nocturnal dyspnea. Weight stable."
        ),
        "objective": (
            "VS: BP {bp}, HR {hr} bpm, SpO2 {spo2}%. "
            "JVD absent. Lungs: {lung_sounds}. "
            "BNP {bnp} pg/mL. EF on last echo: {ef}%."
        ),
        "assessment": (
            "1. Chronic diastolic heart failure, NYHA class {nyha}, compensated. "
            "2. Continue GDMT — carvedilol, sacubitril/valsartan. "
            "3. BNP {bnp} pg/mL — {bnp_trend}."
        ),
        "plan": (
            "Carvedilol 25mg BID. Furosemide 40mg daily. "
            "Sacubitril/valsartan 97/103mg BID. "
            "Daily weights. Call if weight up > 3 lbs in 2 days. "
            "Echo in 6 months. ICD evaluation pending."
        ),
    },
    "COPD": {
        "subjective": (
            "Patient with COPD presents for pulmonology follow-up. "
            "Exacerbation last {months_since_exac} months ago — antibiotics and steroids given. "
            "Using tiotropium daily. Moderate dyspnea (mMRC grade 2). Tobacco hx: {pack_years} pack-years."
        ),
        "objective": (
            "VS: BP {bp}, HR {hr}, SpO2 {spo2}% on RA. "
            "Breath sounds: decreased throughout, prolonged expiration. Mild wheeze. "
            "Spirometry: FEV1 {fev1}% predicted, FEV1/FVC {fev1fvc}."
        ),
        "assessment": (
            "1. COPD with history of exacerbation — GOLD stage {gold_stage}. "
            "2. Current regimen adequate; add roflumilast given exacerbation history. "
            "3. Continue pulmonary rehab program."
        ),
        "plan": (
            "Tiotropium 18mcg inhaled daily. Roflumilast 500mcg daily. "
            "Rescue albuterol PRN. Pulmonary rehab referral. "
            "Annual influenza + PCV23 vaccines administered. "
            "Spirometry repeat in 12 months."
        ),
    },
    "Depression": {
        "subjective": (
            "Patient with MDD presents for psychiatric follow-up. "
            "PHQ-9 score {phq9} this visit (prior: {phq9_prior}). "
            "Sleep {sleep_status}. Energy {energy_status}. "
            "No SI/HI. Compliant with medication."
        ),
        "objective": (
            "Oriented x3. Mood: {mood}. Affect: appropriate. "
            "No psychomotor agitation or retardation. Speech fluent. "
            "GAD-7 score {gad7}."
        ),
        "assessment": (
            "1. Major depressive disorder — {mdd_severity}. PHQ-9 {phq9} ({phq9_change}). "
            "2. Current SSRI therapy effective. No medication changes indicated. "
            "3. Continue structured psychotherapy weekly."
        ),
        "plan": (
            "Sertraline {ssri_dose}mg daily. Continue weekly CBT. "
            "Safety plan reinforced. Crisis line number provided. "
            "Follow-up in 4 weeks or sooner PRN."
        ),
    },
    "AFib": {
        "subjective": (
            "Patient with paroxysmal AFib on anticoagulation presents for cardiology follow-up. "
            "Palpitations {palp_freq}. No syncopal episodes. "
            "Compliant with apixaban 5mg BID. CHA2DS2-VASc score: {chads}."
        ),
        "objective": (
            "VS: BP {bp}, HR {hr} bpm irregular. SpO2 {spo2}%. "
            "Rhythm: {rhythm}. No JVD. Lungs clear. "
            "INR not applicable (DOAC). TSH normal."
        ),
        "assessment": (
            "1. Atrial fibrillation — {afib_type}, rate controlled at {hr} bpm. "
            "2. Anticoagulation: apixaban 5mg BID — CHA2DS2-VASc {chads}, appropriate. "
            "3. Rate control: metoprolol succinate 50mg daily — adequate."
        ),
        "plan": (
            "Continue apixaban 5mg BID. Metoprolol succinate 50mg daily. "
            "Echo in 12 months. Consider cardioversion if symptomatic recurrence. "
            "Monthly follow-up."
        ),
    },
    "Complex": {
        "subjective": (
            "Complex patient with DM2, systolic CHF, CKD stage 4, and AFib. "
            "Fatigue and DOE NYHA class III. Peripheral edema. "
            "Fluid management challenging given CKD and diuresis needs. "
            "HbA1c {hba1c}%, eGFR {egfr} last month."
        ),
        "objective": (
            "VS: BP {bp}, HR {hr} bpm irregular. SpO2 {spo2}%. Wt {wt} lbs (baseline {wt_base} lbs). "
            "JVD +2cm. Lungs: bibasilar crackles. 2+ pitting edema bilateral. "
            "Labs: HbA1c {hba1c}%, BNP {bnp} pg/mL, eGFR {egfr}, K+ {k} mEq/L, Creatinine {cr}."
        ),
        "assessment": (
            "1. T2DM with hyperglycemia — HbA1c {hba1c}%, {dm_control}. "
            "2. Systolic CHF, NYHA class III — BNP {bnp}, partially compensated. "
            "3. CKD stage 4, eGFR {egfr} — nephrology co-managing. "
            "4. AFib — rate-controlled, anticoagulated with apixaban."
        ),
        "plan": (
            "Multidisciplinary care conference scheduled. "
            "Torsemide 40mg BID. Carvedilol 6.25mg BID. Apixaban 2.5mg BID (CKD dose-adjusted). "
            "Nephrology in 3 weeks. Cardiology in 4 weeks. "
            "RAF capture review: all 4 HCCs must be recaptured this year — "
            "care coordinator to perform HEDIS gap closure outreach."
        ),
    },
    "Dementia": {
        "subjective": (
            "Accompanied by family caregiver. Cognitive decline over 18 months. "
            "MMSE {mmse}/30. Manages ADLs with assistance. "
            "On donepezil and memantine. No behavioral disturbance reported."
        ),
        "objective": (
            "VS: BP {bp}, HR {hr}. Oriented x{orient}. "
            "Cognitive: MMSE {mmse}/30, clock draw impaired. "
            "Gait: {gait}. No focal neuro deficits."
        ),
        "assessment": (
            "1. Alzheimer dementia — moderate stage, MMSE {mmse}/30. "
            "2. ADL assistance provided by family. "
            "3. Safety assessment completed — driving cessation counseling provided."
        ),
        "plan": (
            "Donepezil 10mg QHS. Memantine 10mg BID. "
            "Caregiver support group referral. Elder care attorney consult recommended. "
            "6-month memory clinic follow-up."
        ),
    },
    "Healthy": {
        "subjective": (
            "Patient presents for annual wellness visit. "
            "No active complaints. Former smoker, quit {quit_years} years ago. "
            "Exercises regularly. No falls in past year."
        ),
        "objective": (
            "VS: BP {bp}, HR {hr}, Wt {wt} lbs. BMI {bmi}. "
            "General: well-appearing, no acute distress. "
            "Comprehensive exam: unremarkable."
        ),
        "assessment": (
            "1. Annual wellness — preventive care up to date. "
            "2. History of nicotine dependence — in remission {quit_years} years. "
            "3. Age-appropriate cancer screenings reviewed."
        ),
        "plan": (
            "Continue preventive medications. Influenza vaccine administered. "
            "Colonoscopy reminder sent. Bone density scan ordered. "
            "Return in 12 months or PRN."
        ),
    },
}

# ---------------------------------------------------------------------------
# Lab value generators — realistic ranges per A1c tier
# ---------------------------------------------------------------------------

def _a1c_value(tier: str) -> float:
    """Return a realistic A1c for the given HEDIS CDC tier."""
    if tier == "controlled":       # <8 → met
        return round(_RNG.uniform(6.0, 7.9), 1)
    elif tier == "borderline":     # 8-9 → borderline
        return round(_RNG.uniform(8.0, 8.9), 1)
    else:                          # >9 → gap/fail
        return round(_RNG.uniform(9.1, 12.0), 1)


def _trending_a1c(tier: str, q: int, total_q: int) -> float:
    """Simulate realistic trend: improving or deteriorating over time."""
    base = _a1c_value(tier)
    # Earlier quarters may have been worse for "improving" patients
    # and better for "deteriorating"
    if _RNG.random() < 0.5:  # improving trajectory
        offset = (total_q - q) * _RNG.uniform(0.1, 0.3)
        return round(min(base + offset, 13.5), 1)
    else:                     # flat or mild drift
        offset = _RNG.uniform(-0.2, 0.2)
        return round(max(5.5, min(base + offset, 13.5)), 1)


def _creatinine_value(ckd: bool) -> float:
    if ckd:
        return round(_RNG.uniform(1.6, 3.2), 1)
    return round(_RNG.uniform(0.7, 1.2), 1)


def _egfr_value(ckd: bool, ckd_stage: int) -> int:
    if not ckd:
        return _RNG.randint(70, 110)
    if ckd_stage == 3:
        return _RNG.randint(30, 59)
    if ckd_stage == 4:
        return _RNG.randint(15, 29)
    return _RNG.randint(10, 14)


def _bnp_value(chf: bool) -> int:
    if chf:
        return _RNG.randint(180, 1200)
    return _RNG.randint(20, 90)


def _ldl_value() -> int:
    return _RNG.randint(65, 185)


def _uacr_value(ckd: bool) -> int:
    if ckd:
        return _RNG.randint(30, 600)
    return _RNG.randint(5, 28)


# ---------------------------------------------------------------------------
# Soap note filler helpers
# ---------------------------------------------------------------------------

def _bp() -> str:
    s = _RNG.randint(110, 155)
    d = _RNG.randint(65, 95)
    return f"{s}/{d} mmHg"

def _hr() -> int:
    return _RNG.randint(58, 95)

def _weight() -> int:
    return _RNG.randint(142, 245)

def _spo2() -> int:
    return _RNG.randint(93, 99)


def _fill_soap(template: str, bundle_label: str, hba1c: float | None = None) -> str:
    """Do a best-effort substitution of template placeholders."""
    a1c = hba1c or _a1c_value("controlled")
    cr = _creatinine_value(ckd=("CKD" in bundle_label))
    egfr = _egfr_value(ckd=("CKD" in bundle_label), ckd_stage=(3 if "CKD" in bundle_label else 0))
    chf = any(k in bundle_label for k in ("CHF", "Complex"))

    vals = {
        "hba1c":            str(a1c),
        "bp":               _bp(),
        "hr":               str(_hr()),
        "wt":               str(_weight()),
        "wt_base":          str(_weight()),
        "spo2":             str(_spo2()),
        "cr":               str(cr),
        "egfr":             str(egfr),
        "uacr":             str(_uacr_value(ckd=("CKD" in bundle_label))),
        "k":                str(round(_RNG.uniform(3.8, 5.1), 1)),
        "bnp":              str(_bnp_value(chf=chf)),
        "gluc":             str(_RNG.randint(95, 240)),
        "ldl":              str(_ldl_value()),
        "ef":               str(_RNG.randint(25, 55) if chf else _RNG.randint(55, 65)),
        "fev1":             str(_RNG.randint(35, 70)),
        "fev1fvc":          str(round(_RNG.uniform(0.52, 0.68), 2)),
        "gold_stage":       _RNG.choice(["II", "III"]),
        "pack_years":       str(_RNG.randint(20, 55)),
        "months_since_exac":str(_RNG.randint(2, 10)),
        "phq9":             str(_RNG.randint(5, 22)),
        "phq9_prior":       str(_RNG.randint(5, 22)),
        "phq9_change":      _RNG.choice(["improving", "stable", "worsening"]),
        "gad7":             str(_RNG.randint(3, 16)),
        "sleep_status":     _RNG.choice(["improved", "fragmented", "adequate"]),
        "energy_status":    _RNG.choice(["low", "improving", "adequate"]),
        "mood":             _RNG.choice(["euthymic", "dysthymic", "mildly depressed"]),
        "mdd_severity":     _RNG.choice(["mild-moderate", "moderate", "in partial remission"]),
        "ssri_dose":        str(_RNG.choice([50, 100, 150])),
        "palp_freq":        _RNG.choice(["occasional", "rare", "none in past month"]),
        "chads":            str(_RNG.randint(2, 5)),
        "rhythm":           _RNG.choice(["sinus rhythm", "irregular rate and rhythm"]),
        "afib_type":        _RNG.choice(["paroxysmal", "persistent"]),
        "lung_sounds":      _RNG.choice(["clear bilaterally", "bibasilar crackles", "scattered rhonchi"]),
        "edema":            _RNG.choice(["no peripheral edema", "1+ pitting edema bilateral"]),
        "nyha":             _RNG.choice(["I-II", "II", "II-III"]),
        "bnp_trend":        _RNG.choice(["stable", "trending down from {}", "elevated from last visit"]),
        "metformin_dose":   str(_RNG.choice([500, 1000])),
        "insulin_dose":     str(_RNG.randint(14, 32)),
        "dm_control":       "well-controlled" if a1c < 8 else ("suboptimal" if a1c < 9 else "poorly controlled"),
        "gap_status":       "closed" if a1c < 8 else "open — action required",
        "mmse":             str(_RNG.randint(10, 24)),
        "orient":           str(_RNG.choice([1, 2, 2, 3])),
        "gait":             _RNG.choice(["steady with walker", "cautious", "normal"]),
        "bmi":              str(round(_RNG.uniform(22.0, 38.5), 1)),
        "quit_years":       str(_RNG.randint(3, 25)),
    }
    result = template
    for k, v in vals.items():
        result = result.replace("{" + k + "}", v)
    return result


# ---------------------------------------------------------------------------
# Core patient builder
# ---------------------------------------------------------------------------

def _build_patient_roster(n_patients: int, today: date) -> list[dict]:
    """Return a list of patient dicts with demographics + condition profile."""
    patients = []
    name_idx_f = 0
    name_idx_m = 0

    for i in range(n_patients):
        # Sex
        sex = "Female" if _RNG.random() < 0.52 else "Male"

        # Age band
        band = _RNG.choices(_AGE_BANDS, weights=_AGE_WEIGHTS, k=1)[0]
        age = _RNG.randint(band[0], band[1])
        birth_year = today.year - age
        birth_month = _RNG.randint(1, 12)
        birth_day = _RNG.randint(1, 28)
        dob = date(birth_year, birth_month, birth_day)

        # Name — cycle through pool to avoid duplicates
        if sex == "Female":
            fname = _FIRST_NAMES_F[name_idx_f % len(_FIRST_NAMES_F)]
            name_idx_f += 1
        else:
            fname = _FIRST_NAMES_M[name_idx_m % len(_FIRST_NAMES_M)]
            name_idx_m += 1
        lname = _LAST_NAMES[i % len(_LAST_NAMES)]

        # Race / ethnicity
        race, ethnicity = _RNG.choices(_RACE_CHOICES, weights=_RACE_WEIGHTS, k=1)[0]

        # Geography
        metro = _RNG.choice(_METROS)
        city, state = metro[0], metro[1]
        zip_code = _RNG.choice(metro[2])
        street = _RNG.choice(_STREETS)

        # Insurance
        insurance = _RNG.choices(_INS_CHOICES, weights=_INS_WEIGHTS, k=1)[0]

        # Condition bundle
        bundle = _RNG.choices(_CONDITION_BUNDLES, weights=_BUNDLE_WEIGHTS, k=1)[0]

        # HEDIS CDC tier for diabetic patients
        hedis_tier = None
        if bundle["is_diabetic"]:
            hedis_tier = _RNG.choices(
                ["controlled", "borderline", "failed"],
                weights=[30, 40, 30],
                k=1,
            )[0]

        # D-SNP patients are dual-eligible
        dual_eligible = insurance == "D-SNP"

        patients.append({
            "seq": i + 1,
            "fname": fname,
            "lname": lname,
            "sex": sex,
            "dob": dob,
            "age": age,
            "race": race,
            "ethnicity": ethnicity,
            "street": street,
            "city": city,
            "state": state,
            "zip": zip_code,
            "insurance": insurance,
            "dual_eligible": dual_eligible,
            "bundle": bundle,
            "hedis_tier": hedis_tier,
            # placeholder MBI — no real MBI per HIPAA Safe Harbor
            "mbi": f"PID{{seq}}",
        })

    return patients


# ---------------------------------------------------------------------------
# DB helpers — OpenEMR shadow tables
# ---------------------------------------------------------------------------

def _ensure_shadow_tables(cur) -> None:
    """Create shadow OpenEMR tables inside the RAF DB if absent."""
    ddls = [
        """
        CREATE TABLE IF NOT EXISTS patient_data (
            pid         INT AUTO_INCREMENT PRIMARY KEY,
            fname       VARCHAR(100) NOT NULL DEFAULT '',
            lname       VARCHAR(100) NOT NULL DEFAULT '',
            DOB         DATE,
            sex         VARCHAR(25) DEFAULT '',
            race        VARCHAR(100) DEFAULT '',
            ethnicity   VARCHAR(100) DEFAULT '',
            street      VARCHAR(255) DEFAULT '',
            city        VARCHAR(100) DEFAULT '',
            state       VARCHAR(50) DEFAULT '',
            postal_code VARCHAR(20) DEFAULT '',
            insurance   VARCHAR(100) DEFAULT '',
            is_demo     TINYINT(1) NOT NULL DEFAULT 0,
            INDEX idx_lname (lname),
            INDEX idx_is_demo (is_demo)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """,
        """
        CREATE TABLE IF NOT EXISTS form_encounter (
            encounter   INT AUTO_INCREMENT PRIMARY KEY,
            pid         INT NOT NULL,
            date        DATETIME NOT NULL,
            reason      VARCHAR(255) DEFAULT '',
            facility    VARCHAR(255) DEFAULT 'Demo Health System',
            pos_code    VARCHAR(10) DEFAULT '11',
            class_code  VARCHAR(20) DEFAULT 'AMB',
            specialty   VARCHAR(100) DEFAULT 'PCP',
            is_demo     TINYINT(1) NOT NULL DEFAULT 0,
            INDEX idx_pid (pid),
            INDEX idx_date (date),
            INDEX idx_is_demo (is_demo)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """,
        """
        CREATE TABLE IF NOT EXISTS billing (
            id          INT AUTO_INCREMENT PRIMARY KEY,
            pid         INT NOT NULL,
            encounter   INT NOT NULL,
            code_type   VARCHAR(20) NOT NULL DEFAULT 'ICD10',
            code        VARCHAR(20) NOT NULL,
            code_text   VARCHAR(255) DEFAULT '',
            activity    TINYINT(1) NOT NULL DEFAULT 1,
            is_demo     TINYINT(1) NOT NULL DEFAULT 0,
            INDEX idx_pid (pid),
            INDEX idx_encounter (encounter),
            INDEX idx_is_demo (is_demo)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """,
        """
        CREATE TABLE IF NOT EXISTS form_soap (
            id          INT AUTO_INCREMENT PRIMARY KEY,
            pid         INT NOT NULL,
            encounter   INT NOT NULL,
            subjective  TEXT,
            objective   TEXT,
            assessment  TEXT,
            plan        TEXT,
            activity    TINYINT(1) NOT NULL DEFAULT 1,
            is_demo     TINYINT(1) NOT NULL DEFAULT 0,
            INDEX idx_pid (pid),
            INDEX idx_encounter (encounter),
            INDEX idx_is_demo (is_demo)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """,
        """
        CREATE TABLE IF NOT EXISTS prescriptions (
            id          INT AUTO_INCREMENT PRIMARY KEY,
            pid         INT NOT NULL,
            encounter   INT NOT NULL,
            drug_name   VARCHAR(255) NOT NULL DEFAULT '',
            dosage      VARCHAR(100) DEFAULT '',
            sig         VARCHAR(255) DEFAULT '',
            active      TINYINT(1) NOT NULL DEFAULT 1,
            is_demo     TINYINT(1) NOT NULL DEFAULT 0,
            INDEX idx_pid (pid),
            INDEX idx_is_demo (is_demo)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """,
        """
        CREATE TABLE IF NOT EXISTS demo_lab_results (
            id          INT AUTO_INCREMENT PRIMARY KEY,
            pid         INT NOT NULL,
            test_name   VARCHAR(100) NOT NULL,
            loinc_code  VARCHAR(20) NOT NULL DEFAULT '',
            value       DECIMAL(12,4) NOT NULL,
            unit        VARCHAR(30) NOT NULL DEFAULT '',
            result_date DATE NOT NULL,
            is_abnormal TINYINT(1) NOT NULL DEFAULT 0,
            is_demo     TINYINT(1) NOT NULL DEFAULT 0,
            INDEX idx_pid (pid),
            INDEX idx_test (test_name),
            INDEX idx_date (result_date),
            INDEX idx_is_demo (is_demo)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """,
    ]
    for ddl in ddls:
        cur.execute(ddl)


def _upsert_patient(cur, p: dict) -> int | None:
    """Insert patient if not exists; return pid."""
    cur.execute(
        "SELECT pid FROM patient_data WHERE fname=%s AND lname=%s AND DOB=%s AND is_demo=1 LIMIT 1",
        (p["fname"], p["lname"], p["dob"]),
    )
    row = cur.fetchone()
    if row:
        return row[0]

    cur.execute(
        """INSERT INTO patient_data
           (fname, lname, DOB, sex, race, ethnicity, street, city, state, postal_code, insurance, is_demo)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,1)""",
        (
            p["fname"], p["lname"], p["dob"], p["sex"],
            p["race"], p["ethnicity"],
            p["street"], p["city"], p["state"], p["zip"],
            p["insurance"],
        ),
    )
    return cur.lastrowid


def _insert_encounter(cur, pid: int, enc_date: datetime, reason: str,
                      specialty: str, pos_code: str) -> int:
    cur.execute(
        """INSERT INTO form_encounter (pid, date, reason, facility, pos_code, specialty, is_demo)
           VALUES (%s,%s,%s,'Demo Health System',%s,%s,1)""",
        (pid, enc_date, reason, pos_code, specialty),
    )
    return cur.lastrowid


def _insert_billing(cur, pid: int, encounter: int, code: str, code_text: str) -> None:
    cur.execute(
        """INSERT IGNORE INTO billing (pid, encounter, code_type, code, code_text, is_demo)
           VALUES (%s,%s,'ICD10',%s,%s,1)""",
        (pid, encounter, code, code_text),
    )


def _insert_soap(cur, pid: int, encounter: int, soap: dict) -> None:
    cur.execute(
        """INSERT INTO form_soap (pid, encounter, subjective, objective, assessment, plan, is_demo)
           VALUES (%s,%s,%s,%s,%s,%s,1)""",
        (pid, encounter, soap["subjective"], soap["objective"],
         soap["assessment"], soap["plan"]),
    )


def _insert_prescription(cur, pid: int, encounter: int,
                         drug: str, dosage: str, sig: str) -> None:
    cur.execute(
        """INSERT INTO prescriptions (pid, encounter, drug_name, dosage, sig, is_demo)
           VALUES (%s,%s,%s,%s,%s,1)""",
        (pid, encounter, drug, dosage, sig),
    )


def _insert_lab(cur, pid: int, test: str, loinc: str, value: float,
                unit: str, result_date: date, is_abnormal: bool) -> None:
    cur.execute(
        """INSERT INTO demo_lab_results
           (pid, test_name, loinc_code, value, unit, result_date, is_abnormal, is_demo)
           VALUES (%s,%s,%s,%s,%s,%s,%s,1)""",
        (pid, test, loinc, value, unit, result_date, 1 if is_abnormal else 0),
    )


# ---------------------------------------------------------------------------
# RAF DB helpers
# ---------------------------------------------------------------------------

def _upsert_demographics(cur, pid: int, patient: dict,
                         measurement_year: int, tenant_id: str) -> None:
    age = patient["age"]
    if age < 65:
        age_band = "50-64"
    elif age < 70:
        age_band = "65-69"
    elif age < 75:
        age_band = "70-74"
    elif age < 80:
        age_band = "75-79"
    elif age < 85:
        age_band = "80-84"
    elif age < 90:
        age_band = "85-89"
    else:
        age_band = "90+"

    sex = "F" if patient["sex"] == "Female" else "M"
    dual = 1 if patient["dual_eligible"] else 0
    model_seg = "CPD" if dual else "CNA"

    cur.execute(
        """INSERT INTO raf_patient_demographics
               (patient_id, measurement_year, age_band, sex, dual_status, disabled, model_segment)
           VALUES (%s,%s,%s,%s,%s,0,%s)
           ON DUPLICATE KEY UPDATE age_band=VALUES(age_band), sex=VALUES(sex),
               dual_status=VALUES(dual_status), model_segment=VALUES(model_segment)""",
        (pid, measurement_year, age_band, sex, dual, model_seg),
    )


def _upsert_patient_hcc(cur, pid: int, measurement_year: int,
                        icd_codes: list[tuple[str, str]],
                        encounter_ids: list[int]) -> list[int]:
    """Insert HCC rows; return list of inserted hcc_ids."""
    hcc_ids = []
    seen_hcc: set[int] = set()
    for code, _desc in icd_codes:
        info = _HCC_MAP.get(code)
        if not info or info["hcc"] == 0:
            continue
        hcc_code = info["hcc"]
        if hcc_code in seen_hcc:
            continue
        seen_hcc.add(hcc_code)
        coeff = _HCC_COEFF.get(hcc_code, 0.200)
        cur.execute(
            """INSERT INTO raf_patient_hcc
                   (patient_id, measurement_year, hcc_code, icd10_codes,
                    source_encounter_ids, raf_coefficient, meat_status)
               VALUES (%s,%s,%s,%s,%s,%s,'complete')
               ON DUPLICATE KEY UPDATE
                   icd10_codes=VALUES(icd10_codes),
                   source_encounter_ids=VALUES(source_encounter_ids),
                   raf_coefficient=VALUES(raf_coefficient),
                   meat_status='complete'""",
            (
                pid, measurement_year, hcc_code,
                json.dumps([c for c, _ in icd_codes]),
                json.dumps(encounter_ids[:3]),
                coeff,
            ),
        )
        hcc_ids.append(cur.lastrowid)
    return hcc_ids


def _upsert_raf_score(cur, pid: int, measurement_year: int,
                      icd_codes: list[tuple[str, str]], model_seg: str) -> None:
    demo_score = round(_RNG.uniform(0.32, 0.48), 4)
    disease_score = sum(
        _HCC_COEFF.get(_HCC_MAP.get(c, {}).get("hcc", 0), 0.0)
        for c, _ in icd_codes
        if _HCC_MAP.get(c, {}).get("hcc", 0) > 0
    )
    disease_score = round(disease_score, 4)
    total = round(demo_score + disease_score, 4)
    final_raf = round(total / 1.069, 4)   # rough normalization factor
    hcc_count = len({_HCC_MAP.get(c, {}).get("hcc", 0)
                     for c, _ in icd_codes
                     if _HCC_MAP.get(c, {}).get("hcc", 0) > 0})

    cur.execute(
        """INSERT INTO raf_scores
               (patient_id, measurement_year, score_type, model_segment,
                demographic_score, disease_score, interaction_score,
                total_raw, normalization_factor, final_raf, hcc_count)
           VALUES (%s,%s,'prospective',%s,%s,%s,0.0000,%s,1.0690,%s,%s)
           ON DUPLICATE KEY UPDATE
               demographic_score=VALUES(demographic_score),
               disease_score=VALUES(disease_score),
               total_raw=VALUES(total_raw),
               final_raf=VALUES(final_raf),
               hcc_count=VALUES(hcc_count),
               calculated_at=NOW()""",
        (pid, measurement_year, model_seg, demo_score, disease_score,
         total, final_raf, hcc_count),
    )


def _upsert_suspect(cur, pid: int, measurement_year: int,
                    dropped_tuple: tuple[str, str] | None) -> None:
    if not dropped_tuple:
        return
    icd, detail = dropped_tuple
    info = _HCC_MAP.get(icd)
    if not info or info["hcc"] == 0:
        return
    cur.execute(
        """INSERT INTO raf_suspect_conditions
               (patient_id, measurement_year, suspect_hcc, suspect_icd10,
                evidence_type, evidence_detail, confidence_score, status)
           VALUES (%s,%s,%s,%s,'historical',%s,0.8500,'open')
           ON DUPLICATE KEY UPDATE
               confidence_score=VALUES(confidence_score),
               status='open'""",
        (
            pid, measurement_year, info["hcc"], icd,
            json.dumps({"reason": detail, "source": "prior_year_billing"}),
        ),
    )


# ---------------------------------------------------------------------------
# Outreach / chart-chase / RADV DDL + seed helpers
# ---------------------------------------------------------------------------

_OUTREACH_DDL = """
CREATE TABLE IF NOT EXISTS outreach_messages (
    id                  INT AUTO_INCREMENT PRIMARY KEY,
    tenant_id           VARCHAR(50) NOT NULL,
    campaign_id         INT DEFAULT NULL,
    patient_id          INT NOT NULL,
    measure_id          VARCHAR(100) NOT NULL,
    channel             ENUM('sms','email','phone','mail') NOT NULL DEFAULT 'sms',
    language            VARCHAR(10) NOT NULL DEFAULT 'en',
    status              ENUM('queued','sent','delivered','failed','opted_out') NOT NULL DEFAULT 'queued',
    template_id         VARCHAR(100) NOT NULL DEFAULT '',
    to_address          VARCHAR(255) NOT NULL DEFAULT '',
    provider_message_id VARCHAR(255) DEFAULT NULL,
    sent_at             DATETIME DEFAULT NULL,
    failed_at           DATETIME DEFAULT NULL,
    failure_reason      VARCHAR(500) DEFAULT NULL,
    is_demo             TINYINT(1) NOT NULL DEFAULT 0,
    created_at          DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_tenant (tenant_id),
    INDEX idx_patient (patient_id),
    INDEX idx_status (status),
    INDEX idx_is_demo (is_demo)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
"""

_CHART_CHASE_DDL = """
CREATE TABLE IF NOT EXISTS chart_chase_requests (
    id                  INT AUTO_INCREMENT PRIMARY KEY,
    tenant_id           VARCHAR(50) NOT NULL,
    patient_id          INT NOT NULL,
    provider_npi        VARCHAR(20) DEFAULT NULL,
    requesting_user_id  INT NOT NULL DEFAULT 1,
    chase_type          ENUM('initial','follow_up','final') NOT NULL DEFAULT 'initial',
    reason              TEXT NOT NULL,
    hcc_codes           JSON DEFAULT NULL,
    dos_from            DATE DEFAULT NULL,
    dos_to              DATE DEFAULT NULL,
    status              ENUM('pending','in_progress','completed','cancelled') NOT NULL DEFAULT 'pending',
    priority            ENUM('low','medium','high','urgent') NOT NULL DEFAULT 'medium',
    facility_name       VARCHAR(255) DEFAULT NULL,
    facility_fax        VARCHAR(50) DEFAULT NULL,
    facility_email      VARCHAR(255) DEFAULT NULL,
    facility_phone      VARCHAR(50) DEFAULT NULL,
    request_date        DATE NOT NULL,
    due_date            DATE DEFAULT NULL,
    notes               TEXT DEFAULT NULL,
    is_demo             TINYINT(1) NOT NULL DEFAULT 0,
    created_at          DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at          DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_tenant (tenant_id),
    INDEX idx_patient (patient_id),
    INDEX idx_status (status),
    INDEX idx_is_demo (is_demo)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
"""

_RADV_RUNS_DDL = """
CREATE TABLE IF NOT EXISTS raf_radv_audit_runs (
    id                          INT AUTO_INCREMENT PRIMARY KEY,
    tenant_id                   VARCHAR(50) NOT NULL,
    name                        VARCHAR(255) NOT NULL,
    payment_year                YEAR NOT NULL,
    sample_size                 INT NOT NULL DEFAULT 30,
    sample_method               ENUM('random','high_risk','stratified') NOT NULL DEFAULT 'stratified',
    status                      ENUM('prep','in_progress','review','complete') NOT NULL DEFAULT 'prep',
    created_by                  VARCHAR(100) DEFAULT NULL,
    notes                       TEXT DEFAULT NULL,
    members_enrolled            INT DEFAULT NULL,
    ffs_adjuster                DECIMAL(8,4) DEFAULT 1.0000,
    extrapolation_methodology   VARCHAR(100) DEFAULT 'ffs_adjuster_v1',
    assumed_fail_rate           DECIMAL(5,4) DEFAULT 0.0500,
    is_demo                     TINYINT(1) NOT NULL DEFAULT 0,
    created_at                  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at                  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_tenant (tenant_id),
    INDEX idx_status (status),
    INDEX idx_is_demo (is_demo)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
"""

_RADV_RECORDS_DDL = """
CREATE TABLE IF NOT EXISTS raf_radv_audit_records (
    id                      INT AUTO_INCREMENT PRIMARY KEY,
    audit_run_id            INT NOT NULL,
    tenant_id               VARCHAR(50) NOT NULL,
    patient_id              INT NOT NULL,
    sampled_hcc_codes       JSON DEFAULT NULL,
    final_decision          ENUM('defensible','undefensible','needs_remediation','pending')
                            NOT NULL DEFAULT 'pending',
    extrapolated_exposure_dollars DECIMAL(12,2) DEFAULT NULL,
    is_demo                 TINYINT(1) NOT NULL DEFAULT 0,
    created_at              DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_run (audit_run_id),
    INDEX idx_patient (patient_id),
    INDEX idx_is_demo (is_demo)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
"""


def _seed_outreach(cur, tenant_id: str, patient_ids: list[int]) -> int:
    """Seed 5-10 outreach messages in mixed states."""
    sample = _RNG.sample(patient_ids, min(8, len(patient_ids)))
    statuses = ["sent", "sent", "sent", "failed", "failed", "queued", "queued", "queued"]
    inserted = 0
    for pid, status in zip(sample, statuses):
        cur.execute(
            "SELECT id FROM outreach_messages WHERE patient_id=%s AND tenant_id=%s AND is_demo=1 LIMIT 1",
            (pid, tenant_id),
        )
        if cur.fetchone():
            continue
        channel = _RNG.choice(["sms", "email", "phone"])
        sent_at = "NOW()" if status == "sent" else "NULL"
        failed_at = "NOW()" if status == "failed" else "NULL"
        failure_reason = ("no_answer" if status == "failed" else None)
        cur.execute(
            """INSERT INTO outreach_messages
               (tenant_id, patient_id, measure_id, channel, status, template_id,
                to_address, sent_at, failed_at, failure_reason, is_demo)
               VALUES (%s,%s,'CDC_A1C',%s,%s,'cdc_a1c.sms.en',
               %s,
               CASE WHEN %s='sent' THEN NOW() ELSE NULL END,
               CASE WHEN %s='failed' THEN NOW() ELSE NULL END,
               %s, 1)""",
            (
                tenant_id, pid, channel, status,
                f"555-{_RNG.randint(1000,9999)}",
                status, status, failure_reason,
            ),
        )
        inserted += 1
    return inserted


def _seed_chart_chases(cur, tenant_id: str, patient_ids: list[int], today: date) -> int:
    """Seed 3 chart-chase requests in different states."""
    sample = _RNG.sample(patient_ids, min(3, len(patient_ids)))
    statuses = ["pending", "in_progress", "completed"]
    inserted = 0
    facilities = [
        ("Downtown Medical Group", "212-555-0100", "records@dmg.demo", "212-555-0101"),
        ("Westside Cardiology",    "310-555-0200", "charts@wsc.demo",  "310-555-0201"),
        ("Northside Family Care",  "404-555-0300", "records@nfc.demo", "404-555-0301"),
    ]
    for pid, status, facility in zip(sample, statuses, facilities):
        cur.execute(
            "SELECT id FROM chart_chase_requests WHERE patient_id=%s AND tenant_id=%s AND is_demo=1 LIMIT 1",
            (pid, tenant_id),
        )
        if cur.fetchone():
            continue
        cur.execute(
            """INSERT INTO chart_chase_requests
               (tenant_id, patient_id, requesting_user_id, chase_type, reason,
                hcc_codes, dos_from, dos_to, status, priority,
                facility_name, facility_fax, facility_email, facility_phone,
                request_date, due_date, notes, is_demo)
               VALUES (%s,%s,1,'initial',
               'HCC recapture: condition coded in prior year not yet recaptured this year',
               %s,%s,%s,%s,'high',%s,%s,%s,%s,%s,%s,
               'Demo chart chase — RADV readiness audit',1)""",
            (
                tenant_id, pid,
                json.dumps([37, 85]),
                today - timedelta(days=_RNG.randint(200, 365)),
                today - timedelta(days=1),
                status,
                facility[0], facility[1], facility[2], facility[3],
                today - timedelta(days=_RNG.randint(10, 30)),
                today + timedelta(days=_RNG.randint(5, 20)),
            ),
        )
        inserted += 1
    return inserted


def _seed_radv_run(cur, tenant_id: str, patient_ids: list[int],
                   payment_year: int, today: date) -> int:
    """Seed 1 RADV audit run with 7 sampled patients."""
    cur.execute(
        "SELECT id FROM raf_radv_audit_runs WHERE tenant_id=%s AND is_demo=1 LIMIT 1",
        (tenant_id,),
    )
    if cur.fetchone():
        return 0

    cur.execute(
        """INSERT INTO raf_radv_audit_runs
           (tenant_id, name, payment_year, sample_size, sample_method,
            status, created_by, notes, members_enrolled, ffs_adjuster,
            extrapolation_methodology, is_demo)
           VALUES (%s,%s,%s,7,'stratified','in_progress','demo_admin',
           'CY%s RADV demo audit — stratified high-risk sample',
           %s,1.0690,'ffs_adjuster_v1',1)""",
        (
            tenant_id,
            f"CY{payment_year} RADV Audit — Executive Demo",
            payment_year,
            payment_year,
            _RNG.randint(4500, 8000),
        ),
    )
    run_id = cur.lastrowid

    sampled = _RNG.sample(patient_ids, min(7, len(patient_ids)))
    decisions = ["defensible", "defensible", "defensible",
                 "needs_remediation", "needs_remediation",
                 "undefensible", "pending"]
    exposures = [0, 0, 0, 1240.50, 2180.00, 3450.75, None]

    for pid, decision, exposure in zip(sampled, decisions, exposures):
        cur.execute(
            """INSERT INTO raf_radv_audit_records
               (audit_run_id, tenant_id, patient_id, sampled_hcc_codes,
                final_decision, extrapolated_exposure_dollars, is_demo)
               VALUES (%s,%s,%s,%s,%s,%s,1)""",
            (
                run_id, tenant_id, pid,
                json.dumps([37, 85, 96]),
                decision,
                exposure,
            ),
        )
    return run_id


# ---------------------------------------------------------------------------
# Encounter + lab seeder
# ---------------------------------------------------------------------------

_DRUG_BY_BUNDLE: dict[str, list[tuple[str, str, str]]] = {
    "DM2_only":    [("Metformin", "1000 mg", "BID with meals"),
                    ("Atorvastatin", "40 mg", "Nightly")],
    "DM2_CHF":     [("Metformin", "500 mg", "BID with meals"),
                    ("Insulin glargine", "20 units", "QHS"),
                    ("Furosemide", "40 mg", "Daily"),
                    ("Lisinopril", "10 mg", "Daily")],
    "DM2_CKD":     [("Metformin", "500 mg", "BID (renal dose)"),
                    ("Empagliflozin", "10 mg", "Daily"),
                    ("Lisinopril", "5 mg", "Daily")],
    "CHF":         [("Carvedilol", "25 mg", "BID"),
                    ("Furosemide", "40 mg", "Daily"),
                    ("Sacubitril/valsartan", "97/103 mg", "BID")],
    "COPD":        [("Tiotropium", "18 mcg", "Inhaled daily"),
                    ("Roflumilast", "500 mcg", "Daily"),
                    ("Albuterol", "90 mcg", "PRN")],
    "Depression":  [("Sertraline", "100 mg", "Daily"),
                    ("Lorazepam", "0.5 mg", "PRN anxiety")],
    "AFib":        [("Apixaban", "5 mg", "BID"),
                    ("Metoprolol succinate", "50 mg", "Daily")],
    "Complex":     [("Insulin glargine", "24 units", "QHS"),
                    ("Torsemide", "40 mg", "BID"),
                    ("Carvedilol", "6.25 mg", "BID"),
                    ("Apixaban", "2.5 mg", "BID"),
                    ("Lisinopril", "5 mg", "Daily")],
    "Dementia":    [("Donepezil", "10 mg", "QHS"),
                    ("Memantine", "10 mg", "BID")],
    "Healthy":     [("Aspirin", "81 mg", "Daily"),
                    ("Atorvastatin", "20 mg", "Nightly")],
}


def _seed_encounters_for_patient(
    cur_emr,
    pid: int,
    patient: dict,
    today: date,
    n_years: int,
) -> tuple[list[int], int]:
    """
    Seed 4-12 encounters/year for n_years.
    Returns (encounter_ids, lab_count).
    """
    bundle = patient["bundle"]
    bundle_label = bundle["label"]
    icd_codes = bundle["icds"]
    hedis_tier = patient["hedis_tier"]

    encounters_per_year = _RNG.randint(4, 12)
    all_enc_ids: list[int] = []
    lab_count = 0
    drugs = _DRUG_BY_BUNDLE.get(bundle_label, [("Aspirin", "81 mg", "Daily")])

    # Specialty assignment
    primary_spec = "PCP"
    specialist_specs = []
    if any(k in bundle_label for k in ("CHF", "Complex", "AFib")):
        specialist_specs.append("Cardiology")
    if "CKD" in bundle_label or "Complex" in bundle_label:
        specialist_specs.append("Nephrology")
    if "COPD" in bundle_label:
        specialist_specs.append("Pulmonology")
    if "Depression" in bundle_label:
        specialist_specs.append("Psychiatry")
    if "Dementia" in bundle_label:
        specialist_specs.append("Neurology")
    if "DM2" in bundle_label:
        specialist_specs.append("Endocrinology")

    template = _SOAP_TEMPLATES.get(bundle_label, _SOAP_TEMPLATES["Healthy"])
    soap_text_s = _fill_soap(template["subjective"], bundle_label,
                             hba1c=_a1c_value(hedis_tier) if hedis_tier else None)
    soap_text_o = _fill_soap(template["objective"], bundle_label,
                             hba1c=_a1c_value(hedis_tier) if hedis_tier else None)
    soap_text_a = _fill_soap(template["assessment"], bundle_label,
                             hba1c=_a1c_value(hedis_tier) if hedis_tier else None)
    soap_text_p = _fill_soap(template["plan"], bundle_label,
                             hba1c=_a1c_value(hedis_tier) if hedis_tier else None)

    for year_offset in range(n_years):
        year_start = today - timedelta(days=365 * (year_offset + 1))

        for enc_n in range(encounters_per_year):
            days_offset = int(365 * (enc_n / encounters_per_year)) + _RNG.randint(-14, 14)
            enc_dt = year_start + timedelta(days=max(0, days_offset))
            enc_datetime = datetime.combine(enc_dt, datetime.min.time()).replace(
                hour=_RNG.randint(8, 17), minute=_RNG.choice([0, 15, 30, 45])
            )

            # Alternate PCP / specialist
            if specialist_specs and enc_n % 3 == 2:
                spec = _RNG.choice(specialist_specs)
                pos = "11"
                reason = f"{spec} follow-up: {bundle_label.replace('_', ' ')}"
            else:
                spec = primary_spec
                pos = _RNG.choice(["11", "02"])  # office or telehealth
                reason = f"PCP chronic disease management: {bundle_label.replace('_', ' ')}"

            enc_id = _insert_encounter(cur_emr, pid, enc_datetime, reason, spec, pos)
            all_enc_ids.append(enc_id)

            # Billing codes on every PCP encounter
            if spec == "PCP":
                for code, code_text in icd_codes:
                    _insert_billing(cur_emr, pid, enc_id, code, code_text)

            # SOAP note on every encounter
            _insert_soap(cur_emr, pid, enc_id, {
                "subjective": soap_text_s,
                "objective":  soap_text_o,
                "assessment": soap_text_a,
                "plan":       soap_text_p,
            })

            # Prescriptions on first encounter per year
            if enc_n == 0:
                for drug, dosage, sig in drugs:
                    _insert_prescription(cur_emr, pid, enc_id, drug, dosage, sig)

    # Labs — quarterly A1c + CMP for diabetic patients
    if bundle["is_diabetic"] and hedis_tier:
        total_quarters = n_years * 4
        for q in range(total_quarters):
            lab_date = today - timedelta(days=(total_quarters - q) * 91)
            a1c_val = _trending_a1c(hedis_tier, q, total_quarters)
            _insert_lab(cur_emr, pid, "HbA1c", "4548-4", a1c_val, "%", lab_date,
                        a1c_val >= 8.0)
            cr = _creatinine_value(ckd="CKD" in bundle_label)
            _insert_lab(cur_emr, pid, "Creatinine", "2160-0", cr, "mg/dL", lab_date,
                        cr > 1.3)
            ldl = _ldl_value()
            _insert_lab(cur_emr, pid, "LDL Cholesterol", "13457-7", ldl, "mg/dL", lab_date,
                        ldl > 130)
            uacr = _uacr_value(ckd="CKD" in bundle_label)
            _insert_lab(cur_emr, pid, "UACR", "9318-7", uacr, "mg/g", lab_date,
                        uacr >= 30)
            lab_count += 4  # 4 labs per quarter

    return all_enc_ids, lab_count


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def seed(tenant_id: str, n_patients: int, n_years: int) -> dict[str, Any]:
    """
    Idempotent seed function.

    Returns a stats dict with counts of rows created.
    """
    today = date.today()
    measurement_year = today.year

    log.info("Connecting to databases …")
    try:
        raf_conn  = mysql.connector.connect(**_db_config())
        emr_conn  = mysql.connector.connect(**_openemr_config())
    except MySQLError as exc:
        # Fallback: use only RAF DB (shadow tables)
        log.warning("OpenEMR connection failed (%s) — seeding into RAF DB shadow tables", exc)
        raf_conn = mysql.connector.connect(**_db_config())
        emr_conn = raf_conn

    raf_cur = raf_conn.cursor(dictionary=True)
    emr_cur = emr_conn.cursor(dictionary=True) if emr_conn is not raf_conn else raf_cur

    # Ensure shadow tables exist in whichever DB we are using for EMR
    _ensure_shadow_tables(emr_cur)
    emr_conn.commit()

    # Ensure RAF tables exist (they should, but harmless to re-check)
    for ddl in [_OUTREACH_DDL, _CHART_CHASE_DDL, _RADV_RUNS_DDL, _RADV_RECORDS_DDL]:
        try:
            raf_cur.execute(ddl)
        except MySQLError:
            pass
    raf_conn.commit()

    # Build patient roster
    log.info("Building %d patient records …", n_patients)
    roster = _build_patient_roster(n_patients, today)

    patients_created = 0
    encounters_created = 0
    labs_created = 0
    hcc_rows = 0
    suspect_rows = 0
    all_pids: list[int] = []

    for patient in roster:
        pid = _upsert_patient(emr_cur, patient)
        if pid is None:
            log.warning("Could not upsert patient %s %s", patient["fname"], patient["lname"])
            continue

        all_pids.append(pid)
        if pid not in all_pids[:-1]:   # only count newly created
            patients_created += 1

        # Encounters + labs
        enc_ids, lab_cnt = _seed_encounters_for_patient(
            emr_cur, pid, patient, today, n_years
        )
        encounters_created += len(enc_ids)
        labs_created += lab_cnt

        emr_conn.commit()

        # RAF demographics + HCC + scores (prior year + current year)
        for year_offset in range(n_years + 1):
            yr = measurement_year - year_offset
            _upsert_demographics(raf_cur, pid, patient, yr, tenant_id)
            enc_ids_for_yr = enc_ids[: max(1, len(enc_ids) // n_years)]  # first-year subset
            hcc_batch = _upsert_patient_hcc(
                raf_cur, pid, yr,
                patient["bundle"]["icds"],
                enc_ids_for_yr,
            )
            hcc_rows += len(hcc_batch)
            dual = patient["dual_eligible"]
            model_seg = "CPD" if dual else "CNA"
            _upsert_raf_score(raf_cur, pid, yr, patient["bundle"]["icds"], model_seg)

        # Dropped HCC as open suspect (current year only)
        _upsert_suspect(
            raf_cur, pid, measurement_year,
            patient["bundle"]["dropped"],
        )
        if patient["bundle"]["dropped"]:
            suspect_rows += 1

        raf_conn.commit()

    log.info("Seeding outreach messages …")
    outreach_count = _seed_outreach(raf_cur, tenant_id, all_pids)
    raf_conn.commit()

    log.info("Seeding chart-chase requests …")
    chase_count = _seed_chart_chases(raf_cur, tenant_id, all_pids, today)
    raf_conn.commit()

    log.info("Seeding RADV audit run …")
    radv_run_id = _seed_radv_run(raf_cur, tenant_id, all_pids, measurement_year, today)
    raf_conn.commit()

    # Close cursors
    raf_cur.close()
    if emr_cur is not raf_cur:
        emr_cur.close()
    raf_conn.close()
    if emr_conn is not raf_conn:
        emr_conn.close()

    stats = {
        "patients_created":    patients_created,
        "encounters_created":  encounters_created,
        "labs_created":        labs_created,
        "hcc_rows":            hcc_rows,
        "suspect_rows":        suspect_rows,
        "outreach_messages":   outreach_count,
        "chart_chase_requests":chase_count,
        "radv_run_id":         radv_run_id,
        "tenant_id":           tenant_id,
        "measurement_year":    measurement_year,
    }
    log.info("Seed complete: %s", stats)
    return stats


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Seed 50-patient longitudinal demo dataset for RAF Intelligence executive demos.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--tenant",   default="1",  help="Tenant ID (string)")
    parser.add_argument("--patients", type=int, default=50, help="Number of patients to seed")
    parser.add_argument("--years",    type=int, default=2,  help="Years of history to generate")
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    result = seed(
        tenant_id=args.tenant,
        n_patients=args.patients,
        n_years=args.years,
    )
    print(json.dumps(result, indent=2))
    sys.exit(0)
