#!/usr/bin/env python3
"""
seed_demographic_risk_factors.py
--------------------------------
Seed the ``kg_demographic_risk_factors`` table with curated demographic +
comorbidity-conditional priors used by the suspect-detection layer.

These multipliers DO NOT touch the official CMS RAF score — they only
sharpen the prior probability estimate the suspect engine uses when
ranking which open codes deserve clinician attention.

Sources (cited per row in ``source`` / ``source_notes``):
  - MEDPAR-2023            : CMS Medicare Provider Analysis & Review file (2023)
  - CMS-CCW-2023           : CMS Chronic Conditions Warehouse condition prevalence files (2023)
  - curated-AAFP-2024      : American Academy of Family Physicians clinical reviews (2024)
  - curated-NIH-NIA-2023   : NIH National Institute on Aging epidemiology reviews (2023)
  - curated-AHA-2024       : American Heart Association statistical updates (2024)
  - curated-ADA-2024       : American Diabetes Association Standards of Care (2024)
  - curated-USRDS-2023     : United States Renal Data System annual report (2023)
  - curated-NSDUH-2023     : National Survey on Drug Use and Health (2023)

Each row encodes ONE rule.  Multipliers are applied multiplicatively when
multiple rows match a patient (see demographic_risk_service.compute_modulated_prior).

Idempotent: re-running deletes existing rows for the same (hcc_code, age_min,
age_max, sex, dual_status, disabled, institutional, conditional_on_hccs)
fingerprint and re-inserts.  In practice the seed is wiped+reseeded since
the table is curated reference data.

Usage::

    python backend/scripts/seed_demographic_risk_factors.py
    # or with a custom DB target:
    RAF_DB_HOST=10.1.0.204 RAF_DB_USER=raf_app python backend/scripts/seed_demographic_risk_factors.py
"""
from __future__ import annotations

import json
import logging
import os
import sys
from typing import Any

import mysql.connector  # type: ignore[import-untyped]
from mysql.connector import Error as MySQLError  # type: ignore[import-untyped]

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("seed_demographic_risk_factors")


DB_CONFIG = dict(
    host=os.environ.get("RAF_DB_HOST", "127.0.0.1"),
    port=int(os.environ.get("RAF_DB_PORT", "3306")),
    user=os.environ.get("RAF_DB_USER", "root"),
    password=os.environ.get("RAF_DB_PASSWORD", "root"),
    database=os.environ.get("RAF_DB_NAME", "raf_intelligence"),
    charset="utf8mb4",
)


# ---------------------------------------------------------------------------
# Curated factor catalog
#
# Tuple shape:
#   (hcc_code, age_min, age_max, sex, dual_status, disabled, institutional,
#    multiplier, conditional_on_hccs, source, notes)
#
# Conventions:
#   - sex=None means "any"; sex='F'/'M' means female / male specific.
#   - dual_status default is "any" unless restricted.
#   - disabled / institutional are NULL unless we want to require a value.
#   - conditional_on_hccs is None for unconditional factors, else a list of
#     HCC code strings; the patient must have AT LEAST ONE to fire.
# ---------------------------------------------------------------------------

FACTORS: list[tuple] = [
    # =====================================================================
    # CKD (HCC 138 — Chronic Kidney Disease, moderate)
    # =====================================================================
    ("138", 65, 74, "F", "dual",     None, None, 1.4000, None,
     "MEDPAR-2023", "Dual-eligible women 65-74 have ~40% higher CKD prevalence vs non-dual peers"),
    ("138", 65, 74, "M", "dual",     None, None, 1.3000, None,
     "MEDPAR-2023", "Dual-eligible men 65-74 ~30% higher CKD prevalence"),
    ("138", 75, 120, None, "any",    None, None, 1.5000, None,
     "curated-USRDS-2023", "CKD prevalence rises sharply 75+ regardless of sex/dual"),
    ("138", 75, 120, None, "any",    None, None, 2.1000, ["18"],
     "curated-USRDS-2023", "Age 75+ with diabetes complications: very high CKD prior"),
    ("138", 75, 120, None, "any",    None, None, 1.8000, ["226"],
     "curated-AHA-2024", "Age 75+ with CHF: cardio-renal syndrome elevates CKD prior"),
    ("138", 65, 120, None, "any",    None, None, 1.6000, ["19"],
     "curated-ADA-2024", "Diabetes (HCC 19) doubles long-term CKD risk (compounding)"),
    ("138", 70, 120, None, "any",    None,    1, 1.4000, None,
     "curated-USRDS-2023", "Institutional residents have higher undiagnosed CKD rate"),
    ("138", 0,  64,  None, "any",       1, None, 1.3000, None,
     "MEDPAR-2023", "Disabled <65 carry elevated CKD baseline"),
    ("138", 65, 120, "F", "any",     None, None, 1.1500, None,
     "curated-USRDS-2023", "Female sex modest CKD prevalence bump 65+"),
    ("138", 60, 120, None, "any",    None, None, 1.2500, ["108"],
     "curated-AHA-2024", "Vascular disease (HCC 108) raises CKD prior"),

    # =====================================================================
    # CHF (HCC 226 — Heart failure)
    # =====================================================================
    ("226", 75, 120, "M", "any",     None, None, 1.3000, None,
     "curated-AHA-2024", "Men 75+ have higher CHF incidence vs women same age"),
    ("226", 75, 120, "F", "any",     None, None, 1.2000, None,
     "curated-AHA-2024", "Women 75+ CHF prevalence elevated, less than men"),
    ("226", 65, 120, None, "any",    None, None, 2.4000, ["138"],
     "curated-AHA-2024", "Cardio-renal syndrome — CKD strongly predicts CHF"),
    ("226", 65, 120, None, "any",    None, None, 1.7000, ["19"],
     "curated-ADA-2024", "Diabetic cardiomyopathy raises CHF prior"),
    ("226", 65, 120, None, "any",    None, None, 1.5000, ["18"],
     "curated-ADA-2024", "Diabetes with complications raises CHF prior further"),
    ("226", 65, 120, None, "any",    None, None, 1.6000, ["108"],
     "curated-AHA-2024", "Vascular disease elevates CHF prior"),
    ("226", 65, 120, None, "dual",   None, None, 1.3000, None,
     "MEDPAR-2023", "Dual-eligible carry higher CHF baseline"),
    ("226", 65, 120, None, "any",    None,    1, 1.5000, None,
     "curated-AHA-2024", "Institutional residents — higher undiagnosed CHF rate"),
    ("226", 70, 120, None, "any",    None, None, 1.2000, ["96"],
     "curated-AHA-2024", "Specified heart arrhythmias raise CHF prior"),
    ("226", 0,  64,  None, "any",       1, None, 1.3500, None,
     "MEDPAR-2023", "Disabled <65 carry elevated CHF baseline"),

    # =====================================================================
    # Diabetes WITH complications (HCC 18)
    # =====================================================================
    ("18", 70, 120, None, "dual",    None, None, 2.0000, ["19"],
     "curated-ADA-2024", "Dual-eligible 70+ with uncomplicated DM commonly progress to complications"),
    ("18", 65, 120, "F", "any",      None, None, 1.9000, ["138"],
     "curated-USRDS-2023", "Women 65+ with CKD have very high prior of progression to DM with complications"),
    ("18", 65, 120, None, "any",     None, None, 1.7000, ["19"],
     "curated-ADA-2024", "Existing uncomplicated DM strongly predicts complication progression"),
    ("18", 65, 120, None, "any",     None, None, 1.5000, ["108"],
     "curated-AHA-2024", "Vascular disease + DM 19 = high prior for DM complications"),
    ("18", 75, 120, None, "any",     None, None, 1.4000, None,
     "curated-ADA-2024", "Age 75+ baseline progression to complicated DM"),
    ("18", 65, 120, None, "dual",    None, None, 1.3000, None,
     "MEDPAR-2023", "Dual-eligible higher DM-complications baseline"),
    ("18", 65, 120, None, "any",     None,    1, 1.4000, None,
     "curated-ADA-2024", "Institutional residents — undiagnosed complications common"),
    ("18", 0,  64,  None, "any",        1, None, 1.6000, None,
     "MEDPAR-2023", "Disabled <65 — higher rates of poorly-controlled DM"),
    ("18", 65, 120, None, "any",     None, None, 1.4000, ["111"],
     "curated-AHA-2024", "COPD + DM 19 raises DM-complications prior"),

    # =====================================================================
    # Diabetes WITHOUT complications (HCC 19)
    # =====================================================================
    ("19", 65, 120, None, "dual",    None, None, 1.5000, None,
     "MEDPAR-2023", "Dual-eligible 65+ have ~50% higher DM prevalence"),
    ("19", 65, 120, "F", "dual",     None, None, 1.6000, None,
     "MEDPAR-2023", "Dual-eligible women 65+ even higher DM prior"),
    ("19", 70, 120, None, "any",     None, None, 1.3000, None,
     "curated-ADA-2024", "Age 70+ baseline DM prevalence elevated"),
    ("19", 65, 120, None, "any",     None, None, 1.4000, ["22"],
     "curated-ADA-2024", "Morbid obesity raises DM prior"),
    ("19", 65, 120, None, "any",     None,    1, 1.3000, None,
     "MEDPAR-2023", "Institutional residents — higher DM prevalence"),
    ("19", 0,  64,  None, "any",        1, None, 1.4000, None,
     "MEDPAR-2023", "Disabled <65 carry elevated DM prevalence"),
    ("19", 65, 120, None, "any",     None, None, 1.3000, ["108"],
     "curated-AHA-2024", "Vascular disease raises DM prior"),

    # =====================================================================
    # Dementia (HCC 51 / 52 — Senile Dementia / Alzheimer's)
    #   Stored under HCC code "51" (canonical V28 dementia bucket) and
    #   also "52" for granular subtype.  Some legacy callers use "125"
    #   from V24; include rules for both for compatibility.
    # =====================================================================
    ("51", 80, 120, None, "any",     None, None, 2.5000, None,
     "curated-NIH-NIA-2023", "Dementia prevalence ~30% by age 80+"),
    ("51", 75, 120, None, "any",     None,    1, 3.0000, None,
     "curated-NIH-NIA-2023", "Institutional 75+ — dementia prevalence 50%+"),
    ("51", 70, 120, None, "any",     None, None, 4.0000, ["24"],
     "curated-NIH-NIA-2023", "Down syndrome + age 70+ extreme Alzheimer's prior"),
    ("51", 65, 120, "F", "any",      None, None, 1.3000, None,
     "curated-NIH-NIA-2023", "Women carry slightly higher dementia prior 65+"),
    ("51", 75, 120, None, "dual",    None, None, 1.6000, None,
     "MEDPAR-2023", "Dual-eligible 75+ — higher undiagnosed dementia rate"),
    ("51", 80, 120, "F", "dual",     None, None, 2.0000, None,
     "MEDPAR-2023", "Female dual 80+ stacked dementia prior"),
    ("51", 65, 120, None, "any",     None, None, 1.5000, ["108"],
     "curated-NIH-NIA-2023", "Vascular disease raises vascular-dementia prior"),
    ("51", 65, 120, None, "any",     None, None, 1.4000, ["19"],
     "curated-ADA-2024", "Diabetes raises dementia prior (vascular pathway)"),

    ("52", 80, 120, None, "any",     None, None, 2.5000, None,
     "curated-NIH-NIA-2023", "Alzheimer's-specific subtype: same age curve as HCC 51"),
    ("52", 75, 120, None, "any",     None,    1, 3.0000, None,
     "curated-NIH-NIA-2023", "Institutional 75+ — high Alzheimer's prevalence"),
    ("52", 70, 120, None, "any",     None, None, 4.0000, ["24"],
     "curated-NIH-NIA-2023", "Down syndrome + 70+ very high Alzheimer's prior"),

    ("125", 80, 120, None, "any",    None, None, 2.5000, None,
     "curated-NIH-NIA-2023", "V24 dementia bucket — legacy callers"),
    ("125", 75, 120, None, "any",    None,    1, 3.0000, None,
     "curated-NIH-NIA-2023", "V24 dementia institutional 75+"),
    ("125", 70, 120, None, "any",    None, None, 4.0000, ["24"],
     "curated-NIH-NIA-2023", "V24 dementia + Down syndrome 70+"),

    # =====================================================================
    # Major depression (HCC 155 V28 / 59 V24)
    # =====================================================================
    ("155", 65, 120, "F", "any",     None, None, 1.4000, None,
     "curated-AAFP-2024", "Female sex 65+ — higher depression prevalence"),
    ("155", 65, 120, None, "dual",   None, None, 1.6000, None,
     "MEDPAR-2023", "Dual-eligible carry markedly higher depression baseline"),
    ("155", 65, 120, None, "any",    None, None, 1.9000, ["75"],
     "curated-AAFP-2024", "Chronic pain (HCC 75) strongly elevates depression prior"),
    ("155", 65, 120, "F", "dual",    None, None, 1.8000, None,
     "MEDPAR-2023", "Female dual 65+ stacked depression prior"),
    ("155", 65, 120, None, "any",    None,    1, 1.7000, None,
     "curated-AAFP-2024", "Institutional residents — high undertreated depression"),
    ("155", 65, 120, None, "any",    None, None, 1.4000, ["51"],
     "curated-NIH-NIA-2023", "Dementia raises co-morbid depression prior"),
    ("155", 65, 120, None, "any",    None, None, 1.5000, ["226"],
     "curated-AHA-2024", "CHF + depression bidirectional association"),
    ("155", 0,  64,  None, "any",       1, None, 1.5000, None,
     "MEDPAR-2023", "Disabled <65 — higher depression baseline"),

    ("59", 65, 120, "F", "any",      None, None, 1.4000, None,
     "curated-AAFP-2024", "V24 depression code — female bump"),
    ("59", 65, 120, None, "dual",    None, None, 1.6000, None,
     "MEDPAR-2023", "V24 depression — dual-eligible bump"),
    ("59", 65, 120, None, "any",     None, None, 1.9000, ["75"],
     "curated-AAFP-2024", "V24 depression — chronic pain conditional"),

    # =====================================================================
    # Cancer recurrence (HCCs 12-22 — Neoplasms)
    # Conditional on a prior cancer HCC firing.  Patient with prior
    # neoplasm carries an elevated suspect prior for recurrence.
    # =====================================================================
    ("12", 75, 120, None, "any",     None, None, 1.5000, ["12", "13", "14", "15", "16", "17", "18", "20", "21", "22"],
     "curated-AAFP-2024", "Age 75+ with prior cancer — recurrence prior elevated"),
    ("13", 75, 120, None, "any",     None, None, 1.5000, ["12", "13", "14", "15", "16", "17", "20", "21", "22"],
     "curated-AAFP-2024", "Age 75+ with prior cancer — solid-tumor recurrence prior"),
    ("14", 75, 120, None, "any",     None, None, 1.5000, ["12", "13", "14", "15", "16", "17", "20", "21", "22"],
     "curated-AAFP-2024", "Age 75+ with prior cancer — recurrence prior"),
    ("15", 75, 120, None, "any",     None, None, 1.5000, ["12", "13", "14", "15", "16", "17", "20", "21", "22"],
     "curated-AAFP-2024", "Age 75+ with prior cancer — recurrence prior"),
    ("16", 75, 120, None, "any",     None, None, 1.5000, ["12", "13", "14", "15", "16", "17", "20", "21", "22"],
     "curated-AAFP-2024", "Age 75+ with prior cancer — recurrence prior"),
    ("17", 75, 120, None, "any",     None, None, 1.5000, ["12", "13", "14", "15", "16", "17", "20", "21", "22"],
     "curated-AAFP-2024", "Age 75+ with prior cancer — recurrence prior"),
    ("20", 75, 120, None, "any",     None, None, 1.5000, ["12", "13", "14", "15", "16", "17", "20", "21", "22"],
     "curated-AAFP-2024", "Age 75+ with prior cancer — recurrence prior"),
    ("21", 75, 120, None, "any",     None, None, 1.5000, ["12", "13", "14", "15", "16", "17", "20", "21", "22"],
     "curated-AAFP-2024", "Age 75+ with prior cancer — recurrence prior"),
    ("22", 75, 120, None, "any",     None, None, 1.3000, None,
     "curated-AAFP-2024", "Morbid obesity 75+ baseline elevated"),

    # =====================================================================
    # Behavioral health (HCCs 151, 152, 155 V28)
    #   Dual eligibility is the dominant signal.
    # =====================================================================
    ("151", 65, 120, None, "dual",   None, None, 1.8000, None,
     "curated-NSDUH-2023", "Dual-eligible 65+ — schizophrenia/psychotic baseline ~80% higher"),
    ("151", 0,  64,  None, "any",       1, None, 1.8000, None,
     "curated-NSDUH-2023", "Disabled <65 — schizophrenia/psychotic baseline elevated"),
    ("151", 65, 120, None, "any",    None,    1, 1.6000, None,
     "curated-NSDUH-2023", "Institutional 65+ — psychotic-disorder prevalence elevated"),
    ("151", 65, 120, "M", "dual",    None, None, 1.5000, None,
     "MEDPAR-2023", "Male dual 65+ slightly elevated baseline"),

    ("152", 65, 120, None, "dual",   None, None, 1.8000, None,
     "curated-NSDUH-2023", "Dual-eligible 65+ — bipolar/severe mood baseline elevated"),
    ("152", 0,  64,  None, "any",       1, None, 1.7000, None,
     "curated-NSDUH-2023", "Disabled <65 — bipolar baseline elevated"),
    ("152", 65, 120, "F", "dual",    None, None, 1.6000, None,
     "MEDPAR-2023", "Female dual 65+ elevated mood-disorder baseline"),
    ("152", 65, 120, None, "any",    None, None, 1.4000, ["75"],
     "curated-AAFP-2024", "Chronic pain elevates bipolar/mood prior"),

    # =====================================================================
    # Substance use disorders (HCC 54-56)
    # =====================================================================
    ("54", 0,  64,  None, "any",        1, None, 1.7000, None,
     "curated-NSDUH-2023", "Disabled <65 — substance-use baseline elevated"),
    ("54", 65, 120, None, "dual",    None, None, 1.5000, None,
     "MEDPAR-2023", "Dual-eligible 65+ — alcohol/SU prior elevated"),
    ("54", 65, 120, "M", "any",      None, None, 1.4000, None,
     "curated-NSDUH-2023", "Men 65+ — alcohol-use baseline higher"),
    ("55", 0,  64,  None, "any",        1, None, 1.8000, None,
     "curated-NSDUH-2023", "Disabled <65 — opioid/drug-use elevated"),
    ("55", 65, 120, None, "dual",    None, None, 1.6000, None,
     "MEDPAR-2023", "Dual-eligible 65+ — drug-use prior elevated"),
    ("56", 0,  64,  None, "any",        1, None, 1.7000, None,
     "curated-NSDUH-2023", "Disabled <65 — drug psychosis baseline elevated"),

    # =====================================================================
    # COPD (HCC 111)
    # =====================================================================
    ("111", 65, 120, "M", "any",     None, None, 1.4000, None,
     "MEDPAR-2023", "Men 65+ — higher COPD prevalence"),
    ("111", 65, 120, None, "dual",   None, None, 1.6000, None,
     "MEDPAR-2023", "Dual-eligible 65+ — higher COPD prevalence"),
    ("111", 65, 120, None, "any",    None, None, 1.5000, ["226"],
     "curated-AHA-2024", "CHF + COPD frequent comorbidity"),
    ("111", 65, 120, None, "any",    None, None, 1.3000, ["108"],
     "curated-AHA-2024", "Vascular disease + COPD elevated prior"),
    ("111", 75, 120, None, "any",    None, None, 1.4000, None,
     "MEDPAR-2023", "Age 75+ — higher COPD prevalence"),

    # =====================================================================
    # Vascular disease (HCC 108)
    # =====================================================================
    ("108", 65, 120, "M", "any",     None, None, 1.3000, None,
     "curated-AHA-2024", "Men 65+ — higher PVD prevalence"),
    ("108", 65, 120, None, "dual",   None, None, 1.4000, None,
     "MEDPAR-2023", "Dual-eligible 65+ — higher vascular disease prior"),
    ("108", 65, 120, None, "any",    None, None, 1.6000, ["19"],
     "curated-ADA-2024", "Diabetes raises PVD prior"),
    ("108", 65, 120, None, "any",    None, None, 1.5000, ["18"],
     "curated-ADA-2024", "Complicated diabetes raises PVD prior"),
    ("108", 75, 120, None, "any",    None, None, 1.4000, None,
     "curated-AHA-2024", "Age 75+ — higher vascular disease prevalence"),
    ("108", 65, 120, None, "any",    None, None, 1.3000, ["111"],
     "curated-AHA-2024", "COPD raises PVD prior (shared risk factors)"),

    # =====================================================================
    # Cardiac arrhythmias (HCC 96)
    # =====================================================================
    ("96", 75, 120, None, "any",     None, None, 1.5000, None,
     "curated-AHA-2024", "AFib prevalence rises sharply 75+"),
    ("96", 65, 120, None, "any",     None, None, 1.6000, ["226"],
     "curated-AHA-2024", "CHF + AFib frequent comorbidity"),
    ("96", 65, 120, "M", "any",      None, None, 1.2000, None,
     "curated-AHA-2024", "Men slightly higher AFib prevalence"),
    ("96", 65, 120, None, "any",     None, None, 1.3000, ["111"],
     "curated-AHA-2024", "COPD raises AFib prior"),

    # =====================================================================
    # Morbid obesity (HCC 22)
    # =====================================================================
    ("22", 65, 120, "F", "any",      None, None, 1.3000, None,
     "MEDPAR-2023", "Women 65+ — higher morbid obesity prevalence"),
    ("22", 0,  64,  None, "any",        1, None, 1.6000, None,
     "MEDPAR-2023", "Disabled <65 — higher morbid obesity prevalence"),
    ("22", 65, 120, None, "dual",    None, None, 1.5000, None,
     "MEDPAR-2023", "Dual-eligible 65+ — higher morbid obesity"),
    ("22", 65, 120, None, "any",     None, None, 1.4000, ["19"],
     "curated-ADA-2024", "Diabetes + morbid obesity comorbidity"),

    # =====================================================================
    # Specified arthritis / RA (HCC 40)
    # =====================================================================
    ("40", 65, 120, "F", "any",      None, None, 1.5000, None,
     "curated-AAFP-2024", "Women have ~3x higher RA prevalence"),
    ("40", 65, 120, "F", "dual",     None, None, 1.7000, None,
     "MEDPAR-2023", "Female dual 65+ stacked RA prior"),
    ("40", 75, 120, None, "any",     None, None, 1.3000, None,
     "curated-AAFP-2024", "Age 75+ — RA prevalence rises"),

    # =====================================================================
    # Pressure ulcers / chronic ulcers (HCC 157, 158, 159)
    # =====================================================================
    ("157", 75, 120, None, "any",    None,    1, 2.5000, None,
     "MEDPAR-2023", "Institutional 75+ — pressure ulcers very common"),
    ("157", 65, 120, None, "any",    None, None, 1.4000, ["19"],
     "curated-ADA-2024", "Diabetes raises pressure ulcer prior"),
    ("157", 65, 120, None, "any",    None, None, 1.5000, ["108"],
     "curated-AHA-2024", "Vascular disease raises chronic ulcer prior"),
    ("158", 75, 120, None, "any",    None,    1, 2.0000, None,
     "MEDPAR-2023", "Institutional 75+ — pressure ulcer Stage 3 prior"),
    ("158", 65, 120, None, "any",    None, None, 1.3000, ["19"],
     "curated-ADA-2024", "Diabetes + Stage 3 ulcer prior"),
    ("159", 75, 120, None, "any",    None,    1, 1.8000, None,
     "MEDPAR-2023", "Institutional 75+ — Stage 4 pressure ulcer prior"),

    # =====================================================================
    # Stroke / CVA (HCC 100, 103)
    # =====================================================================
    ("100", 75, 120, None, "any",    None, None, 1.5000, None,
     "curated-AHA-2024", "Stroke prevalence rises sharply 75+"),
    ("100", 65, 120, None, "any",    None, None, 1.7000, ["96"],
     "curated-AHA-2024", "AFib raises stroke prior"),
    ("100", 65, 120, None, "any",    None, None, 1.4000, ["108"],
     "curated-AHA-2024", "Vascular disease raises stroke prior"),
    ("100", 65, 120, "M", "any",     None, None, 1.2000, None,
     "curated-AHA-2024", "Men slightly higher stroke prevalence"),
    ("103", 75, 120, None, "any",    None, None, 1.4000, None,
     "curated-AHA-2024", "Hemiplegia/late-effects of stroke prevalence rises 75+"),
    ("103", 65, 120, None, "any",    None, None, 1.6000, ["100"],
     "curated-AHA-2024", "Prior stroke raises hemiplegia prior"),

    # =====================================================================
    # End-stage renal disease (HCC 134, 135, 136, 137)
    # =====================================================================
    ("134", 65, 120, None, "any",    None, None, 2.0000, ["18"],
     "curated-USRDS-2023", "Diabetes + age 65+ very high ESRD prior"),
    ("134", 65, 120, None, "any",    None, None, 1.8000, ["138"],
     "curated-USRDS-2023", "CKD progression to dialysis"),
    ("134", 65, 120, None, "dual",   None, None, 1.4000, None,
     "MEDPAR-2023", "Dual-eligible 65+ higher ESRD prior"),
    ("135", 65, 120, None, "any",    None, None, 1.7000, ["138"],
     "curated-USRDS-2023", "CKD stage 5 elevated prior"),
    ("136", 65, 120, None, "any",    None, None, 1.5000, ["138"],
     "curated-USRDS-2023", "CKD stage 4 elevated prior"),
    ("137", 65, 120, None, "any",    None, None, 1.3000, ["138"],
     "curated-USRDS-2023", "CKD stage 3 elevated prior"),

    # =====================================================================
    # Liver disease (HCC 27, 28, 29)
    # =====================================================================
    ("27", 0,  64,  None, "any",        1, None, 1.6000, None,
     "MEDPAR-2023", "Disabled <65 — liver disease elevated"),
    ("27", 65, 120, "M", "any",      None, None, 1.4000, None,
     "curated-AAFP-2024", "Men 65+ higher liver-disease prevalence"),
    ("27", 65, 120, None, "any",     None, None, 1.5000, ["54"],
     "curated-AAFP-2024", "Alcohol-use disorder raises cirrhosis prior"),
    ("28", 65, 120, "M", "any",      None, None, 1.3000, None,
     "curated-AAFP-2024", "Men 65+ — chronic hep prevalence"),
    ("29", 0,  64,  None, "any",        1, None, 1.5000, None,
     "MEDPAR-2023", "Disabled <65 — chronic hep prior"),

    # =====================================================================
    # Hip/major fracture (HCC 169, 170)
    # =====================================================================
    ("169", 80, 120, "F", "any",     None, None, 2.0000, None,
     "curated-NIH-NIA-2023", "Women 80+ very high hip-fracture prior"),
    ("169", 75, 120, "F", "any",     None,    1, 2.5000, None,
     "curated-NIH-NIA-2023", "Institutional women 75+ extreme hip-fracture prior"),
    ("169", 65, 120, "F", "any",     None, None, 1.4000, ["51"],
     "curated-NIH-NIA-2023", "Dementia + female 65+ raises fall/fracture prior"),
    ("170", 80, 120, None, "any",    None, None, 1.5000, None,
     "curated-NIH-NIA-2023", "Major fracture except hip — age 80+"),

    # =====================================================================
    # Asthma (HCC 112)
    # =====================================================================
    ("112", 65, 120, "F", "any",     None, None, 1.3000, None,
     "curated-AAFP-2024", "Women 65+ — higher asthma prevalence"),
    ("112", 0,  64,  None, "any",        1, None, 1.4000, None,
     "MEDPAR-2023", "Disabled <65 — asthma baseline elevated"),

    # =====================================================================
    # Specified peripheral neuropathy (HCC 75 — Chronic pain)
    # =====================================================================
    ("75", 65, 120, "F", "any",      None, None, 1.3000, None,
     "curated-AAFP-2024", "Women 65+ higher chronic-pain prevalence"),
    ("75", 65, 120, None, "any",     None, None, 1.5000, ["19"],
     "curated-ADA-2024", "Diabetes + chronic pain — diabetic neuropathy pathway"),
    ("75", 65, 120, None, "any",     None, None, 1.4000, ["18"],
     "curated-ADA-2024", "Complicated diabetes raises chronic-pain prior"),
    ("75", 65, 120, None, "dual",    None, None, 1.4000, None,
     "MEDPAR-2023", "Dual-eligible 65+ chronic-pain prevalence elevated"),
    ("75", 0,  64,  None, "any",        1, None, 1.5000, None,
     "MEDPAR-2023", "Disabled <65 chronic-pain prevalence elevated"),

    # =====================================================================
    # Coagulation defects (HCC 48)
    # =====================================================================
    ("48", 75, 120, None, "any",     None, None, 1.3000, None,
     "curated-AAFP-2024", "Age 75+ — coagulation defect prevalence rises"),
    ("48", 65, 120, None, "any",     None, None, 1.4000, ["96"],
     "curated-AHA-2024", "AFib + coagulation issues frequent (anticoagulation)"),

    # =====================================================================
    # Specified anemia (HCC 47)
    # =====================================================================
    ("47", 75, 120, None, "any",     None, None, 1.3000, None,
     "curated-AAFP-2024", "Age 75+ — anemia prevalence rises"),
    ("47", 65, 120, None, "any",     None, None, 1.5000, ["138"],
     "curated-USRDS-2023", "CKD + anemia — anemia of chronic disease"),
    ("47", 65, 120, None, "any",     None, None, 1.3000, ["18"],
     "curated-ADA-2024", "Complicated diabetes + anemia"),

    # =====================================================================
    # HIV/AIDS (HCC 1)
    # =====================================================================
    ("1", 0,  64,  None, "any",         1, None, 1.5000, None,
     "MEDPAR-2023", "Disabled <65 — HIV prevalence elevated"),
    ("1", 65, 120, "M", "any",       None, None, 1.3000, None,
     "MEDPAR-2023", "Men 65+ — HIV prevalence elevated"),

    # =====================================================================
    # Multiple sclerosis (HCC 77)
    # =====================================================================
    ("77", 0,  64,  "F", "any",         1, None, 2.0000, None,
     "curated-NIH-NIA-2023", "Disabled female <65 — MS prevalence elevated"),
    ("77", 0,  64,  None, "any",        1, None, 1.4000, None,
     "MEDPAR-2023", "Disabled <65 — MS prevalence elevated"),

    # =====================================================================
    # Parkinson's (HCC 78)
    # =====================================================================
    ("78", 75, 120, "M", "any",      None, None, 1.5000, None,
     "curated-NIH-NIA-2023", "Men 75+ — Parkinson's prevalence rises"),
    ("78", 80, 120, None, "any",     None, None, 1.4000, None,
     "curated-NIH-NIA-2023", "Age 80+ Parkinson's prevalence elevated"),
    ("78", 75, 120, None, "any",     None,    1, 1.6000, None,
     "curated-NIH-NIA-2023", "Institutional 75+ — Parkinson's elevated"),

    # =====================================================================
    # Seizures / epilepsy (HCC 79)
    # =====================================================================
    ("79", 0,  64,  None, "any",        1, None, 1.6000, None,
     "MEDPAR-2023", "Disabled <65 — seizure-disorder prevalence elevated"),
    ("79", 65, 120, None, "any",     None, None, 1.3000, ["100"],
     "curated-AHA-2024", "Prior stroke raises seizure prior"),

    # =====================================================================
    # Aspiration / pneumonia (HCC 114)
    # =====================================================================
    ("114", 75, 120, None, "any",    None,    1, 1.8000, None,
     "MEDPAR-2023", "Institutional 75+ — aspiration pneumonia"),
    ("114", 65, 120, None, "any",    None, None, 1.4000, ["51"],
     "curated-NIH-NIA-2023", "Dementia raises aspiration pneumonia prior"),
    ("114", 65, 120, None, "any",    None, None, 1.3000, ["78"],
     "curated-NIH-NIA-2023", "Parkinson's raises aspiration pneumonia prior"),

    # =====================================================================
    # Sepsis (HCC 2)
    # =====================================================================
    ("2", 75, 120, None, "any",      None,    1, 1.6000, None,
     "MEDPAR-2023", "Institutional 75+ — sepsis prior elevated"),
    ("2", 65, 120, None, "any",      None, None, 1.3000, ["157", "158", "159"],
     "MEDPAR-2023", "Pressure ulcers raise sepsis prior"),

    # =====================================================================
    # Acute MI (HCC 222)
    # =====================================================================
    ("222", 75, 120, "M", "any",     None, None, 1.4000, None,
     "curated-AHA-2024", "Men 75+ — MI prevalence rises"),
    ("222", 65, 120, None, "any",    None, None, 1.6000, ["108"],
     "curated-AHA-2024", "Vascular disease raises MI prior"),
    ("222", 65, 120, None, "any",    None, None, 1.4000, ["19"],
     "curated-ADA-2024", "Diabetes raises MI prior"),
    ("222", 65, 120, None, "any",    None, None, 1.5000, ["18"],
     "curated-ADA-2024", "Complicated diabetes raises MI prior"),
]


def insert_factors(cur, factors: list[tuple]) -> int:
    """Insert all factor rows; returns count inserted."""
    sql = """
        INSERT INTO kg_demographic_risk_factors
          (hcc_code, age_min, age_max, sex, dual_status, disabled,
           institutional, prior_multiplier, conditional_on_hccs, source,
           source_notes, is_active, created_at)
        VALUES
          (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 1, CURRENT_TIMESTAMP)
    """
    inserted = 0
    for row in factors:
        (hcc, amin, amax, sex, dual, disabled, inst,
         multiplier, cond, source, notes) = row
        cond_json = json.dumps(cond) if cond else None
        cur.execute(sql, (
            hcc, int(amin), int(amax), sex, dual,
            None if disabled is None else int(disabled),
            None if inst is None else int(inst),
            float(multiplier),
            cond_json,
            source,
            notes,
        ))
        inserted += 1
    return inserted


def main() -> int:
    log.info("Connecting to %s:%s/%s as %s",
             DB_CONFIG["host"], DB_CONFIG["port"], DB_CONFIG["database"], DB_CONFIG["user"])
    try:
        conn = mysql.connector.connect(**DB_CONFIG)
    except MySQLError as exc:
        log.error("Failed to connect: %s", exc)
        return 1

    try:
        with conn.cursor() as cur:
            # Idempotent: clear and reseed.
            log.info("Clearing existing rows from kg_demographic_risk_factors")
            cur.execute("DELETE FROM kg_demographic_risk_factors")
            n = insert_factors(cur, FACTORS)
            conn.commit()
            log.info("Inserted %d demographic-risk factor rows", n)
            cur.execute(
                "SELECT COUNT(*) AS c FROM kg_demographic_risk_factors WHERE is_active = 1"
            )
            row = cur.fetchone()
            log.info("Active rows in table: %s", row[0] if row else "?")
    finally:
        conn.close()

    log.info("Done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
