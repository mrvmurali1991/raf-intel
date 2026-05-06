#!/usr/bin/env python3
"""
seed_specialty_hcc_priors.py
----------------------------
Populate ``kg_specialty_hcc_priors`` and ``kg_specialty_aliases`` with a
curated baseline of 10 specialties x 25+ HCC priors plus 30+ raw-string
aliases.

Sources
-------
- AAFP specialty mix surveys (top conditions seen by family / internal medicine).
- MEDPAR specialty-mix tables (Medicare claims by attending specialty).
- Curated clinical knowledge — applied where claims data is sparse
  (e.g. severity-tier weighting within a single HCC family).

Each row carries an explicit ``source`` so the audit trail can show why a
particular weight was picked.

Usage
-----
    python -m backend.scripts.seed_specialty_hcc_priors
    python backend/scripts/seed_specialty_hcc_priors.py --dry-run

The script is idempotent — it uses ``INSERT ... ON DUPLICATE KEY UPDATE``
on the unique key ``(specialty, hcc_code)`` so re-running it simply
refreshes the weights.
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path
from typing import Any

# Allow direct ``python backend/scripts/seed_specialty_hcc_priors.py`` invocation
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.db import raf_cursor  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("seed_specialty_hcc_priors")


# ---------------------------------------------------------------------------
# Curated priors
# ---------------------------------------------------------------------------
# Schema for each tuple: (hcc_code, prior_weight, panel_prevalence_pct, source, notes)
#
# prior_weight is a multiplier vs the generic-PCP baseline.
#   1.0  = same as a PCP would see
#   3-8  = strongly enriched in this specialty's panel
#   <1.0 = de-enriched (this specialty rarely sees this HCC)
# ---------------------------------------------------------------------------

PRIORS: dict[str, list[tuple[str, float, float | None, str, str]]] = {

    # =====================================================================
    # Internal Medicine (PCP, broad)
    # =====================================================================
    "Internal Medicine": [
        ("19",  1.00, 18.0, "AAFP-survey",       "Diabetes uncomplicated — bread-and-butter PCP HCC"),
        ("18",  1.00,  6.0, "AAFP-survey",       "DM with chronic complications"),
        ("138", 1.00,  9.0, "MEDPAR-specialty-mix", "CKD stage 3+"),
        ("226", 1.00,  4.5, "MEDPAR-specialty-mix", "CHF — ambulatory"),
        ("280", 1.00,  6.5, "AAFP-survey",       "COPD"),
        ("279", 1.00,  3.5, "AAFP-survey",       "Asthma"),
        ("155", 1.00,  9.0, "AAFP-survey",       "Major depression"),
        ("125", 1.00,  3.0, "MEDPAR-specialty-mix", "Dementia / cognitive impairment"),
        ("48",  1.00,  6.0, "AAFP-survey",       "Morbid obesity"),
        ("21",  1.00,  1.5, "MEDPAR-specialty-mix", "Prostate cancer surveillance"),
        ("20",  1.00,  1.8, "MEDPAR-specialty-mix", "Breast cancer surveillance"),
        ("248", 1.00,  3.0, "AAFP-survey",       "Atrial fibrillation"),
        ("108", 1.00,  3.5, "AAFP-survey",       "Vascular disease"),
        ("96",  1.00,  1.5, "MEDPAR-specialty-mix", "Specified heart arrhythmias / valvular"),
        ("136", 1.00,  2.0, "MEDPAR-specialty-mix", "ESRD / dialysis"),
        ("46",  1.00,  4.0, "MEDPAR-specialty-mix", "Anemia"),
        ("54",  1.00,  3.0, "AAFP-survey",       "Substance use disorder"),
        ("55",  1.00,  2.0, "AAFP-survey",       "Opioid use disorder"),
        ("224", 1.00,  1.5, "MEDPAR-specialty-mix", "CHF — acute on chronic"),
        ("225", 1.00,  1.5, "MEDPAR-specialty-mix", "Heart failure with reduced EF"),
        ("28",  1.00,  1.5, "MEDPAR-specialty-mix", "Liver disease — cirrhosis"),
        ("35",  1.00,  1.0, "MEDPAR-specialty-mix", "IBD"),
        ("11",  1.00,  1.0, "MEDPAR-specialty-mix", "Lung / respiratory cancer"),
        ("170", 1.00,  3.0, "AAFP-survey",       "Hip / pelvic fracture"),
        ("152", 1.00,  1.5, "AAFP-survey",       "Bipolar disorder"),
    ],

    # =====================================================================
    # Family Medicine (PCP — slightly different demographic mix)
    # =====================================================================
    "Family Medicine": [
        ("19",  1.00, 16.0, "AAFP-survey",       "Diabetes uncomplicated"),
        ("18",  1.00,  5.0, "AAFP-survey",       "DM with complications"),
        ("138", 1.00,  7.5, "MEDPAR-specialty-mix", "CKD stage 3+"),
        ("226", 1.00,  3.5, "MEDPAR-specialty-mix", "CHF"),
        ("280", 1.00,  5.5, "AAFP-survey",       "COPD"),
        ("279", 1.00,  4.5, "AAFP-survey",       "Asthma — slightly higher than IM (peds carry-over)"),
        ("155", 1.20, 11.0, "AAFP-survey",       "Major depression — FM sees more behavioral health"),
        ("152", 1.20,  2.0, "AAFP-survey",       "Bipolar disorder"),
        ("125", 1.00,  2.5, "MEDPAR-specialty-mix", "Dementia"),
        ("48",  1.00,  6.0, "AAFP-survey",       "Morbid obesity"),
        ("248", 1.00,  2.5, "AAFP-survey",       "AFib"),
        ("108", 1.00,  3.0, "AAFP-survey",       "Vascular disease"),
        ("96",  1.00,  1.5, "MEDPAR-specialty-mix", "Heart arrhythmia / valvular"),
        ("46",  1.00,  3.5, "MEDPAR-specialty-mix", "Anemia"),
        ("54",  1.20,  3.5, "AAFP-survey",       "Substance use — common FM workload"),
        ("55",  1.20,  2.5, "AAFP-survey",       "Opioid use disorder"),
        ("21",  1.00,  1.0, "MEDPAR-specialty-mix", "Prostate cancer"),
        ("20",  1.00,  1.5, "MEDPAR-specialty-mix", "Breast cancer"),
        ("224", 1.00,  1.0, "MEDPAR-specialty-mix", "Acute CHF"),
        ("225", 1.00,  1.5, "MEDPAR-specialty-mix", "HFrEF"),
        ("28",  1.00,  1.0, "MEDPAR-specialty-mix", "Liver cirrhosis"),
        ("11",  1.00,  0.8, "MEDPAR-specialty-mix", "Lung cancer"),
        ("170", 1.00,  2.5, "AAFP-survey",       "Hip / pelvic fracture"),
        ("136", 1.00,  1.0, "MEDPAR-specialty-mix", "ESRD / dialysis"),
        ("35",  1.00,  0.9, "MEDPAR-specialty-mix", "IBD"),
    ],

    # =====================================================================
    # Geriatrics (age-skewed)
    # =====================================================================
    "Geriatrics": [
        ("125", 4.00, 28.0, "MEDPAR-specialty-mix", "Dementia — defining HCC for geriatrics"),
        ("170", 3.00, 12.0, "MEDPAR-specialty-mix", "Hip / pelvic fracture (falls)"),
        ("169", 3.00,  8.0, "MEDPAR-specialty-mix", "Vertebral fracture"),
        ("48",  0.70,  4.0, "curated",           "Morbid obesity rarer at advanced age"),
        ("226", 1.80, 14.0, "MEDPAR-specialty-mix", "CHF — common in elderly"),
        ("224", 1.80,  4.0, "MEDPAR-specialty-mix", "Acute on chronic CHF"),
        ("225", 1.80,  6.0, "MEDPAR-specialty-mix", "HFrEF"),
        ("248", 2.50, 12.0, "MEDPAR-specialty-mix", "AFib — high prevalence elderly"),
        ("138", 1.80, 18.0, "MEDPAR-specialty-mix", "CKD stage 3+ — age-driven"),
        ("19",  1.20, 22.0, "MEDPAR-specialty-mix", "DM uncomplicated"),
        ("18",  1.30,  9.0, "MEDPAR-specialty-mix", "DM with complications"),
        ("280", 1.30,  9.0, "AAFP-survey",       "COPD"),
        ("46",  1.80, 12.0, "MEDPAR-specialty-mix", "Anemia — common in elderly"),
        ("155", 1.30, 12.0, "AAFP-survey",       "Depression"),
        ("108", 1.80,  9.0, "MEDPAR-specialty-mix", "Vascular disease"),
        ("96",  2.00,  4.0, "MEDPAR-specialty-mix", "Valvular / arrhythmia"),
        ("136", 1.30,  3.0, "MEDPAR-specialty-mix", "ESRD / dialysis"),
        ("11",  1.20,  2.5, "MEDPAR-specialty-mix", "Lung cancer"),
        ("20",  1.20,  3.0, "MEDPAR-specialty-mix", "Breast cancer surveillance"),
        ("21",  1.20,  3.5, "MEDPAR-specialty-mix", "Prostate cancer surveillance"),
        ("28",  0.90,  1.0, "curated",           "Cirrhosis less common in geriatric panel"),
        ("54",  0.50,  1.5, "curated",           "Substance use de-enriched"),
        ("55",  0.50,  1.0, "curated",           "Opioid use de-enriched"),
        ("279", 0.80,  2.5, "curated",           "Asthma less defining than COPD"),
        ("152", 0.80,  1.0, "curated",           "Bipolar de-enriched"),
        ("151", 0.60,  0.8, "curated",           "Schizophrenia less common in elderly cohort"),
    ],

    # =====================================================================
    # Cardiology
    # =====================================================================
    "Cardiology": [
        ("226", 5.00, 38.0, "MEDPAR-specialty-mix", "CHF — defining cardiology HCC"),
        ("225", 5.00, 24.0, "MEDPAR-specialty-mix", "HFrEF"),
        ("224", 5.00, 15.0, "MEDPAR-specialty-mix", "Acute on chronic CHF"),
        ("248", 4.00, 28.0, "MEDPAR-specialty-mix", "Atrial fibrillation"),
        ("216", 3.50,  6.0, "MEDPAR-specialty-mix", "Acute MI history (recent)"),
        ("217", 3.50,  9.0, "MEDPAR-specialty-mix", "AMI — older / chronic"),
        ("96",  3.00, 14.0, "MEDPAR-specialty-mix", "Valvular disease"),
        ("108", 3.00, 18.0, "MEDPAR-specialty-mix", "Vascular disease"),
        ("221", 2.50,  7.0, "MEDPAR-specialty-mix", "Cardiomyopathy"),
        ("223", 2.50,  4.0, "MEDPAR-specialty-mix", "Pulmonary hypertension"),
        ("19",  0.80, 12.0, "curated",           "Diabetes — comorbid but not defining"),
        ("18",  1.00,  8.0, "curated",           "DM with complications — relevant cardiac comorbid"),
        ("138", 1.30, 14.0, "MEDPAR-specialty-mix", "CKD — cardiorenal common"),
        ("46",  1.20,  9.0, "MEDPAR-specialty-mix", "Anemia"),
        ("280", 0.90,  4.0, "curated",           "COPD — comorbid"),
        ("279", 0.50,  1.0, "curated",           "Asthma — de-enriched"),
        ("155", 0.60,  3.0, "curated",           "Depression — comorbid but de-enriched"),
        ("125", 0.70,  2.0, "curated",           "Dementia — de-enriched"),
        ("48",  0.80,  5.0, "curated",           "Morbid obesity — relevant comorbid"),
        ("11",  0.50,  0.5, "curated",           "Lung cancer — outside scope"),
        ("20",  0.40,  0.5, "curated",           "Breast cancer — outside scope"),
        ("28",  0.50,  0.6, "curated",           "Cirrhosis — outside scope"),
        ("35",  0.40,  0.4, "curated",           "IBD — outside scope"),
        ("136", 1.20,  2.0, "MEDPAR-specialty-mix", "ESRD — cardiorenal"),
        ("170", 0.50,  1.0, "curated",           "Hip fracture — outside scope"),
    ],

    # =====================================================================
    # Nephrology
    # =====================================================================
    "Nephrology": [
        ("138", 8.00, 72.0, "MEDPAR-specialty-mix", "CKD stage 3+ — defining HCC"),
        ("137", 7.00, 35.0, "MEDPAR-specialty-mix", "CKD severe stage 4-5"),
        ("136", 8.00, 40.0, "MEDPAR-specialty-mix", "ESRD / dialysis"),
        ("186", 6.00,  8.0, "MEDPAR-specialty-mix", "Kidney transplant status"),
        ("46",  4.00, 38.0, "MEDPAR-specialty-mix", "Anemia of CKD"),
        ("40",  3.00, 12.0, "MEDPAR-specialty-mix", "Secondary hyperparathyroidism / mineral bone disease"),
        ("18",  2.50, 28.0, "MEDPAR-specialty-mix", "DM with complications — common nephropathy driver"),
        ("19",  1.50, 30.0, "MEDPAR-specialty-mix", "DM uncomplicated"),
        ("226", 2.00, 15.0, "MEDPAR-specialty-mix", "CHF — cardiorenal"),
        ("225", 2.00,  9.0, "MEDPAR-specialty-mix", "HFrEF"),
        ("108", 2.00, 12.0, "MEDPAR-specialty-mix", "Vascular disease"),
        ("248", 1.80,  9.0, "MEDPAR-specialty-mix", "AFib"),
        ("96",  1.50,  4.0, "MEDPAR-specialty-mix", "Valvular"),
        ("48",  1.50,  9.0, "MEDPAR-specialty-mix", "Morbid obesity"),
        ("280", 0.80,  3.5, "curated",           "COPD — comorbid"),
        ("279", 0.50,  0.8, "curated",           "Asthma de-enriched"),
        ("155", 1.00,  9.0, "MEDPAR-specialty-mix", "Depression — common in dialysis cohort"),
        ("125", 0.80,  3.0, "curated",           "Dementia"),
        ("11",  0.50,  0.4, "curated",           "Lung cancer outside scope"),
        ("20",  0.50,  0.5, "curated",           "Breast cancer outside scope"),
        ("21",  0.60,  0.6, "curated",           "Prostate cancer surveillance"),
        ("35",  0.60,  0.5, "curated",           "IBD outside scope"),
        ("28",  0.80,  1.0, "curated",           "Cirrhosis — hepato-renal relevant"),
        ("170", 0.70,  1.0, "curated",           "Hip fracture"),
        ("54",  0.70,  1.5, "curated",           "Substance use"),
    ],

    # =====================================================================
    # Pulmonology
    # =====================================================================
    "Pulmonology": [
        ("280", 5.00, 65.0, "MEDPAR-specialty-mix", "COPD — defining pulm HCC"),
        ("279", 4.00, 25.0, "MEDPAR-specialty-mix", "Severe / persistent asthma"),
        ("11",  3.50,  9.0, "MEDPAR-specialty-mix", "Lung / respiratory cancer"),
        ("228", 3.00,  6.0, "MEDPAR-specialty-mix", "Respiratory failure / dependence"),
        ("227", 3.00,  4.0, "MEDPAR-specialty-mix", "Cystic fibrosis / bronchiectasis"),
        ("108", 2.00,  9.0, "MEDPAR-specialty-mix", "Pulmonary HTN / vascular"),
        ("223", 3.00,  9.0, "MEDPAR-specialty-mix", "Pulmonary hypertension specifically"),
        ("226", 1.50,  8.0, "MEDPAR-specialty-mix", "CHF — comorbid (cardiopulmonary)"),
        ("46",  1.20,  6.0, "MEDPAR-specialty-mix", "Anemia"),
        ("19",  0.80, 14.0, "curated",           "DM uncomplicated"),
        ("18",  1.00,  5.0, "curated",           "DM with complications"),
        ("48",  1.50,  9.0, "MEDPAR-specialty-mix", "Morbid obesity (OSA)"),
        ("138", 1.00,  6.0, "curated",           "CKD — comorbid"),
        ("248", 1.20,  5.0, "MEDPAR-specialty-mix", "AFib"),
        ("96",  0.80,  2.0, "curated",           "Valvular — comorbid"),
        ("155", 0.80,  4.0, "curated",           "Depression"),
        ("125", 0.70,  2.0, "curated",           "Dementia"),
        ("54",  1.20,  4.0, "curated",           "Substance / smoking-related"),
        ("55",  0.80,  1.5, "curated",           "Opioid use"),
        ("20",  0.50,  0.5, "curated",           "Breast cancer outside scope"),
        ("21",  0.50,  0.5, "curated",           "Prostate cancer outside scope"),
        ("35",  0.40,  0.4, "curated",           "IBD outside scope"),
        ("28",  0.70,  0.8, "curated",           "Cirrhosis — comorbid"),
        ("136", 0.80,  0.8, "curated",           "ESRD"),
        ("170", 0.70,  1.0, "curated",           "Hip fracture"),
    ],

    # =====================================================================
    # Endocrinology
    # =====================================================================
    "Endocrinology": [
        ("18",  4.00, 55.0, "MEDPAR-specialty-mix", "DM with chronic complications"),
        ("19",  3.00, 70.0, "MEDPAR-specialty-mix", "DM uncomplicated"),
        ("17",  4.00,  6.0, "MEDPAR-specialty-mix", "DM with acute complications (DKA, HHS)"),
        ("48",  3.00, 35.0, "MEDPAR-specialty-mix", "Morbid obesity"),
        ("47",  2.50, 12.0, "MEDPAR-specialty-mix", "Pituitary / adrenal disorders"),
        ("138", 2.00, 18.0, "MEDPAR-specialty-mix", "CKD — diabetic nephropathy"),
        ("46",  1.50,  6.0, "MEDPAR-specialty-mix", "Anemia"),
        ("226", 1.50,  9.0, "MEDPAR-specialty-mix", "CHF — comorbid"),
        ("248", 1.30,  6.0, "curated",           "AFib comorbid"),
        ("108", 1.80, 14.0, "MEDPAR-specialty-mix", "Vascular disease — diabetic"),
        ("280", 0.80,  3.5, "curated",           "COPD"),
        ("279", 0.70,  1.5, "curated",           "Asthma"),
        ("155", 1.20,  9.0, "MEDPAR-specialty-mix", "Depression — common in DM cohort"),
        ("125", 0.80,  2.5, "curated",           "Dementia"),
        ("96",  1.00,  2.0, "curated",           "Valvular comorbid"),
        ("11",  0.50,  0.4, "curated",           "Lung cancer outside scope"),
        ("20",  0.60,  0.6, "curated",           "Breast cancer outside scope"),
        ("21",  0.60,  0.6, "curated",           "Prostate cancer outside scope"),
        ("28",  0.80,  0.8, "curated",           "Cirrhosis (NAFLD relevant)"),
        ("35",  0.50,  0.4, "curated",           "IBD outside scope"),
        ("136", 1.20,  2.0, "MEDPAR-specialty-mix", "ESRD — diabetic"),
        ("170", 0.80,  1.5, "curated",           "Hip fracture"),
        ("54",  0.80,  1.5, "curated",           "Substance use"),
        ("152", 0.80,  1.0, "curated",           "Bipolar"),
        ("151", 0.70,  0.5, "curated",           "Schizophrenia"),
    ],

    # =====================================================================
    # Psychiatry
    # =====================================================================
    "Psychiatry": [
        ("155", 5.00, 65.0, "MEDPAR-specialty-mix", "Major depression — defining psych HCC"),
        ("151", 6.00, 22.0, "MEDPAR-specialty-mix", "Schizophrenia"),
        ("152", 5.00, 28.0, "MEDPAR-specialty-mix", "Bipolar disorder"),
        ("154", 4.00, 18.0, "MEDPAR-specialty-mix", "Anxiety disorders / OCD / PTSD"),
        ("54",  4.00, 32.0, "MEDPAR-specialty-mix", "Substance use disorder"),
        ("55",  4.00, 18.0, "MEDPAR-specialty-mix", "Opioid use disorder"),
        ("125", 1.50,  9.0, "MEDPAR-specialty-mix", "Dementia (psych comorbid)"),
        ("19",  0.80, 12.0, "curated",           "DM comorbid"),
        ("18",  0.80,  4.0, "curated",           "DM with complications"),
        ("48",  1.20,  9.0, "MEDPAR-specialty-mix", "Morbid obesity (psych comorbid)"),
        ("280", 0.70,  3.0, "curated",           "COPD"),
        ("279", 0.60,  1.5, "curated",           "Asthma"),
        ("226", 0.70,  3.0, "curated",           "CHF"),
        ("248", 0.70,  2.0, "curated",           "AFib"),
        ("138", 0.70,  4.0, "curated",           "CKD"),
        ("46",  0.90,  4.0, "curated",           "Anemia"),
        ("108", 0.60,  3.0, "curated",           "Vascular"),
        ("96",  0.50,  1.0, "curated",           "Valvular"),
        ("11",  0.40,  0.4, "curated",           "Lung cancer outside scope"),
        ("20",  0.50,  0.5, "curated",           "Breast cancer outside scope"),
        ("21",  0.50,  0.5, "curated",           "Prostate cancer outside scope"),
        ("28",  1.00,  2.0, "MEDPAR-specialty-mix", "Cirrhosis — common in heavy-drinking cohort"),
        ("170", 0.60,  1.5, "curated",           "Hip fracture"),
        ("136", 0.50,  0.5, "curated",           "ESRD"),
        ("35",  0.40,  0.4, "curated",           "IBD outside scope"),
    ],

    # =====================================================================
    # Oncology
    # =====================================================================
    "Oncology": [
        ("11",  6.00, 18.0, "MEDPAR-specialty-mix", "Lung / respiratory cancer"),
        ("12",  6.00,  9.0, "MEDPAR-specialty-mix", "Lymphoma / leukemia / multiple myeloma"),
        ("13",  6.00,  4.0, "MEDPAR-specialty-mix", "Head and neck cancer"),
        ("17",  3.00,  3.0, "curated",           "DKA risk — chemo-related"),
        ("20",  7.00, 22.0, "MEDPAR-specialty-mix", "Breast cancer (active / metastatic)"),
        ("21",  6.00, 16.0, "MEDPAR-specialty-mix", "Prostate cancer (active)"),
        ("22",  8.00,  6.0, "MEDPAR-specialty-mix", "Metastatic cancer / acute leukemia"),
        ("18",  1.00,  6.0, "curated",           "DM — comorbid"),
        ("19",  1.00, 11.0, "curated",           "DM uncomplicated"),
        ("46",  3.00, 25.0, "MEDPAR-specialty-mix", "Chemo-induced anemia"),
        ("226", 1.20,  6.0, "curated",           "CHF — cardio-oncology"),
        ("225", 1.20,  4.0, "curated",           "HFrEF — anthracycline cardiotox"),
        ("280", 1.00,  5.0, "curated",           "COPD comorbid"),
        ("248", 1.00,  4.0, "curated",           "AFib — cardio-oncology"),
        ("138", 1.00,  6.0, "curated",           "CKD"),
        ("155", 1.20, 12.0, "MEDPAR-specialty-mix", "Depression — psycho-oncology"),
        ("48",  0.80,  5.0, "curated",           "Morbid obesity"),
        ("125", 0.70,  2.0, "curated",           "Dementia"),
        ("28",  1.00,  2.0, "curated",           "Cirrhosis (HCC risk)"),
        ("35",  0.80,  1.5, "curated",           "IBD"),
        ("96",  0.80,  1.5, "curated",           "Valvular"),
        ("108", 1.00,  4.0, "curated",           "Vascular"),
        ("136", 1.00,  1.5, "curated",           "ESRD"),
        ("170", 0.80,  1.5, "curated",           "Hip fracture"),
        ("54",  0.80,  2.0, "curated",           "Substance use"),
    ],

    # =====================================================================
    # Gastroenterology
    # =====================================================================
    "Gastroenterology": [
        ("28",  4.00, 22.0, "MEDPAR-specialty-mix", "Liver cirrhosis — defining GI HCC"),
        ("27",  3.50,  9.0, "MEDPAR-specialty-mix", "Chronic hepatitis"),
        ("29",  3.00,  6.0, "MEDPAR-specialty-mix", "End-stage liver disease"),
        ("35",  3.50, 14.0, "MEDPAR-specialty-mix", "Inflammatory bowel disease"),
        ("36",  3.00,  6.0, "MEDPAR-specialty-mix", "Intestinal obstruction / perforation"),
        ("11",  3.00,  6.0, "MEDPAR-specialty-mix", "GI cancers (esophagus / stomach / colon)"),
        ("12",  2.00,  3.0, "curated",           "Hepatobiliary cancers"),
        ("46",  1.80, 11.0, "MEDPAR-specialty-mix", "Anemia (GI bleed)"),
        ("19",  1.00, 14.0, "curated",           "DM"),
        ("18",  1.00,  5.0, "curated",           "DM complicated"),
        ("48",  1.50, 12.0, "MEDPAR-specialty-mix", "Morbid obesity (NAFLD)"),
        ("226", 1.00,  4.0, "curated",           "CHF comorbid"),
        ("248", 1.00,  3.0, "curated",           "AFib"),
        ("138", 1.20,  6.0, "MEDPAR-specialty-mix", "CKD (hepato-renal relevance)"),
        ("280", 0.80,  3.5, "curated",           "COPD"),
        ("279", 0.60,  1.5, "curated",           "Asthma"),
        ("155", 1.00,  9.0, "curated",           "Depression"),
        ("54",  1.50,  6.0, "MEDPAR-specialty-mix", "Substance use (alcoholic liver)"),
        ("55",  1.00,  2.0, "curated",           "Opioid use"),
        ("125", 0.70,  2.0, "curated",           "Dementia"),
        ("108", 1.00,  4.0, "curated",           "Vascular"),
        ("96",  0.70,  1.5, "curated",           "Valvular"),
        ("136", 0.80,  0.8, "curated",           "ESRD"),
        ("170", 0.70,  1.0, "curated",           "Hip fracture"),
        ("20",  0.60,  0.6, "curated",           "Breast cancer outside scope"),
    ],
}


# ---------------------------------------------------------------------------
# Specialty aliases
# ---------------------------------------------------------------------------
ALIASES: dict[str, str] = {
    # Internal Medicine
    "IM":                       "Internal Medicine",
    "Internal Med":             "Internal Medicine",
    "Internal Medicine":        "Internal Medicine",
    "Gen Internal Medicine":    "Internal Medicine",
    "General Internal Medicine":"Internal Medicine",
    "GenIM":                    "Internal Medicine",

    # Family Medicine
    "FM":                       "Family Medicine",
    "Family Med":               "Family Medicine",
    "Family Medicine":          "Family Medicine",
    "Family Practice":          "Family Medicine",
    "GP":                       "Family Medicine",
    "General Practice":         "Family Medicine",

    # Geriatrics
    "Geri":                     "Geriatrics",
    "Geriatric Medicine":       "Geriatrics",
    "Geriatrics":               "Geriatrics",

    # Cardiology
    "Cards":                    "Cardiology",
    "Cardio":                   "Cardiology",
    "Cardiology":               "Cardiology",
    "Cardiovascular Disease":   "Cardiology",
    "CV":                       "Cardiology",

    # Nephrology
    "Nephro":                   "Nephrology",
    "Nephrology":               "Nephrology",
    "Renal":                    "Nephrology",
    "Kidney":                   "Nephrology",

    # Pulmonology
    "Pulm":                     "Pulmonology",
    "Pulmonology":              "Pulmonology",
    "Pulmonary":                "Pulmonology",
    "Pulmonary Disease":        "Pulmonology",

    # Endocrinology
    "Endo":                     "Endocrinology",
    "Endocrinology":            "Endocrinology",
    "Endocrine":                "Endocrinology",

    # Psychiatry
    "Psych":                    "Psychiatry",
    "Psychiatry":               "Psychiatry",
    "Mental Health":            "Psychiatry",
    "Behavioral Health":        "Psychiatry",

    # Oncology
    "Onc":                      "Oncology",
    "Onco":                     "Oncology",
    "Oncology":                 "Oncology",
    "Hematology Oncology":      "Oncology",
    "Hem/Onc":                  "Oncology",
    "Heme Onc":                 "Oncology",
    "Medical Oncology":         "Oncology",

    # Gastroenterology
    "GI":                       "Gastroenterology",
    "Gastro":                   "Gastroenterology",
    "Gastroenterology":         "Gastroenterology",
    "Hepatology":               "Gastroenterology",
}


# ---------------------------------------------------------------------------
# Insertion logic
# ---------------------------------------------------------------------------

def _flatten_priors() -> list[tuple[str, str, float, float | None, str, str]]:
    """Yield (specialty, hcc_code, weight, prevalence, source, notes)."""
    rows: list[tuple[str, str, float, float | None, str, str]] = []
    for specialty, items in PRIORS.items():
        for hcc, weight, prevalence, source, notes in items:
            rows.append((specialty, hcc, float(weight), prevalence, source, notes))
    return rows


def upsert_priors(dry_run: bool = False) -> dict[str, Any]:
    rows = _flatten_priors()
    log.info("Prepared %d prior rows across %d specialties", len(rows), len(PRIORS))

    if dry_run:
        log.info("[dry-run] skipping DB write")
        return {"priors": len(rows), "aliases": len(ALIASES), "dry_run": True}

    with raf_cursor() as cur:
        cur.executemany(
            """
            INSERT INTO kg_specialty_hcc_priors
                (specialty, hcc_code, prior_weight, panel_prevalence_pct, source, notes, is_active)
            VALUES (%s, %s, %s, %s, %s, %s, 1)
            ON DUPLICATE KEY UPDATE
                prior_weight        = VALUES(prior_weight),
                panel_prevalence_pct= VALUES(panel_prevalence_pct),
                source              = VALUES(source),
                notes               = VALUES(notes),
                is_active           = 1
            """,
            rows,
        )

    log.info("Inserted/updated %d prior rows", len(rows))
    return {"priors": len(rows), "aliases": len(ALIASES), "dry_run": False}


def upsert_aliases(dry_run: bool = False) -> int:
    rows = [(raw, canonical) for raw, canonical in ALIASES.items()]
    log.info("Prepared %d alias rows", len(rows))

    if dry_run:
        log.info("[dry-run] skipping alias DB write")
        return len(rows)

    with raf_cursor() as cur:
        cur.executemany(
            """
            INSERT INTO kg_specialty_aliases (raw_specialty, canonical_specialty)
            VALUES (%s, %s)
            ON DUPLICATE KEY UPDATE
                canonical_specialty = VALUES(canonical_specialty)
            """,
            rows,
        )

    log.info("Inserted/updated %d alias rows", len(rows))
    return len(rows)


# ---------------------------------------------------------------------------
# CLI entry-point
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Seed kg_specialty_hcc_priors and kg_specialty_aliases")
    parser.add_argument("--dry-run", action="store_true", help="Validate counts but skip DB writes")
    args = parser.parse_args(argv)

    summary = upsert_priors(dry_run=args.dry_run)
    upsert_aliases(dry_run=args.dry_run)

    log.info(
        "Done. priors=%d  specialties=%d  aliases=%d  dry_run=%s",
        summary["priors"],
        len(PRIORS),
        summary["aliases"],
        summary["dry_run"],
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
