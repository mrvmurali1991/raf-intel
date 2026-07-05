#!/usr/bin/env python3
"""
seed_medication_signals.py
---------------------------
Expands raf_medication_signals with comprehensive drug -> ICD-10 -> HCC
mappings derived from well-known clinical pharmacology indications.

Covers the highest-impact HCC categories for Medicare Advantage risk
adjustment:

    Diabetes, CHF, CKD, COPD, Atrial Fibrillation, Depression,
    Vascular Disease, Seizure/Epilepsy, Rheumatoid Arthritis,
    Parkinson's Disease, HIV/AIDS, Schizophrenia, Organ Transplant,
    Hepatitis C, Multiple Sclerosis, Bipolar Disorder,
    Cirrhosis / Liver Disease, Pulmonary Arterial Hypertension,
    Lupus / SLE, Dementia, Morbid Obesity, Sickle Cell Disease

Data sources:
    - FDA-approved indications (prescribing information)
    - CMS-HCC V24 / V28 crosswalk mappings
    - Standard clinical pharmacology references

Idempotent: checks existing (drug_name_pattern, suspect_icd10) pairs
before inserting.  Safe to run multiple times.

Usage:
    python scripts/seed_medication_signals.py

    # With custom DB connection:
    RAF_DB_HOST=10.1.0.204 RAF_DB_PORT=3306 RAF_DB_USER=root \\
      RAF_DB_PASSWORD=secret python scripts/seed_medication_signals.py
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
# Each tuple: (drug_name_pattern, drug_class, suspect_icd10, suspect_hcc,
#               confidence_base, notes)
#
# Patterns use SQL LIKE syntax (trailing %).  The scan engine strips '%'
# and performs substring matching against patient medication names.
#
# HCC numbers follow the model already seeded in the database.
# Confidence reflects drug specificity for the indicated condition.
# ---------------------------------------------------------------------------

SIGNALS: list[tuple[str, str, str, int, float, str]] = [

    # =========================================================================
    # DIABETES MELLITUS  (E11.9 -> HCC 19 uncomplicated)
    # HCC 19 consistent with existing seed; HCC 18 for complicated variants
    # =========================================================================

    # --- Thiazolidinediones ---
    ('pioglitazone%',             'Thiazolidinedione',           'E11.9',  19, 0.8200, 'Pioglitazone used exclusively for Type 2 Diabetes'),
    ('rosiglitazone%',            'Thiazolidinedione',           'E11.9',  19, 0.8200, 'Rosiglitazone used exclusively for Type 2 Diabetes'),
    ('actos%',                    'Thiazolidinedione',           'E11.9',  19, 0.8200, 'Actos (pioglitazone) for Type 2 Diabetes'),
    ('avandia%',                  'Thiazolidinedione',           'E11.9',  19, 0.8200, 'Avandia (rosiglitazone) for Type 2 Diabetes'),

    # --- Specific insulin formulations ---
    ('insulin lispro%',           'Rapid-Acting Insulin',        'E11.9',  19, 0.8500, 'Rapid-acting insulin analog for diabetes'),
    ('insulin aspart%',           'Rapid-Acting Insulin',        'E11.9',  19, 0.8500, 'Rapid-acting insulin analog for diabetes'),
    ('insulin glulisine%',        'Rapid-Acting Insulin',        'E11.9',  19, 0.8500, 'Rapid-acting insulin analog for diabetes'),
    ('insulin glargine%',         'Long-Acting Insulin',         'E11.9',  19, 0.8500, 'Long-acting basal insulin for diabetes'),
    ('insulin detemir%',          'Long-Acting Insulin',         'E11.9',  19, 0.8500, 'Long-acting basal insulin for diabetes'),
    ('insulin degludec%',         'Ultra-Long Insulin',          'E11.9',  19, 0.8500, 'Ultra-long-acting insulin for diabetes'),
    ('humalog%',                  'Rapid-Acting Insulin',        'E11.9',  19, 0.8500, 'Humalog (insulin lispro) for diabetes'),
    ('novolog%',                  'Rapid-Acting Insulin',        'E11.9',  19, 0.8500, 'NovoLog (insulin aspart) for diabetes'),
    ('lantus%',                   'Long-Acting Insulin',         'E11.9',  19, 0.8500, 'Lantus (insulin glargine) for diabetes'),
    ('levemir%',                  'Long-Acting Insulin',         'E11.9',  19, 0.8500, 'Levemir (insulin detemir) for diabetes'),
    ('tresiba%',                  'Ultra-Long Insulin',          'E11.9',  19, 0.8500, 'Tresiba (insulin degludec) for diabetes'),
    ('toujeo%',                   'Long-Acting Insulin',         'E11.9',  19, 0.8500, 'Toujeo (insulin glargine U-300) for diabetes'),
    ('basaglar%',                 'Long-Acting Insulin',         'E11.9',  19, 0.8500, 'Basaglar (insulin glargine biosimilar) for diabetes'),
    ('admelog%',                  'Rapid-Acting Insulin',        'E11.9',  19, 0.8500, 'Admelog (insulin lispro) for diabetes'),
    ('fiasp%',                    'Rapid-Acting Insulin',        'E11.9',  19, 0.8500, 'Fiasp (insulin aspart fast-acting) for diabetes'),
    ('humulin%',                  'Insulin',                     'E11.9',  19, 0.8500, 'Humulin (human insulin) for diabetes'),
    ('novolin%',                  'Insulin',                     'E11.9',  19, 0.8500, 'Novolin (human insulin) for diabetes'),

    # --- Additional DPP-4 inhibitors ---
    ('saxagliptin%',              'DPP-4 Inhibitor',             'E11.9',  19, 0.8200, 'DPP-4 inhibitor used exclusively for Type 2 Diabetes'),
    ('linagliptin%',              'DPP-4 Inhibitor',             'E11.9',  19, 0.8200, 'DPP-4 inhibitor used exclusively for Type 2 Diabetes'),
    ('alogliptin%',               'DPP-4 Inhibitor',             'E11.9',  19, 0.8200, 'DPP-4 inhibitor used exclusively for Type 2 Diabetes'),
    ('januvia%',                  'DPP-4 Inhibitor',             'E11.9',  19, 0.8200, 'Januvia (sitagliptin) for Type 2 Diabetes'),
    ('onglyza%',                  'DPP-4 Inhibitor',             'E11.9',  19, 0.8200, 'Onglyza (saxagliptin) for Type 2 Diabetes'),
    ('tradjenta%',                'DPP-4 Inhibitor',             'E11.9',  19, 0.8200, 'Tradjenta (linagliptin) for Type 2 Diabetes'),
    ('nesina%',                   'DPP-4 Inhibitor',             'E11.9',  19, 0.8200, 'Nesina (alogliptin) for Type 2 Diabetes'),

    # --- Additional SGLT2 inhibitors ---
    ('canagliflozin%',            'SGLT2 Inhibitor',             'E11.9',  19, 0.8200, 'SGLT2 inhibitor for Type 2 Diabetes'),
    ('ertugliflozin%',            'SGLT2 Inhibitor',             'E11.9',  19, 0.8200, 'SGLT2 inhibitor for Type 2 Diabetes'),
    ('jardiance%',                'SGLT2 Inhibitor',             'E11.9',  19, 0.8200, 'Jardiance (empagliflozin) for Type 2 Diabetes'),
    ('farxiga%',                  'SGLT2 Inhibitor',             'E11.9',  19, 0.8200, 'Farxiga (dapagliflozin) for Type 2 Diabetes'),
    ('invokana%',                 'SGLT2 Inhibitor',             'E11.9',  19, 0.8200, 'Invokana (canagliflozin) for Type 2 Diabetes'),
    ('steglatro%',                'SGLT2 Inhibitor',             'E11.9',  19, 0.8200, 'Steglatro (ertugliflozin) for Type 2 Diabetes'),

    # --- Additional GLP-1 agonists ---
    ('dulaglutide%',              'GLP-1 Agonist',               'E11.9',  19, 0.8200, 'GLP-1 agonist for Type 2 Diabetes'),
    ('exenatide%',                'GLP-1 Agonist',               'E11.9',  19, 0.8200, 'GLP-1 agonist for Type 2 Diabetes'),
    ('tirzepatide%',              'GLP-1/GIP Dual Agonist',      'E11.9',  19, 0.8500, 'Dual incretin agonist for Type 2 Diabetes'),
    ('ozempic%',                  'GLP-1 Agonist',               'E11.9',  19, 0.8200, 'Ozempic (semaglutide) for Type 2 Diabetes'),
    ('trulicity%',                'GLP-1 Agonist',               'E11.9',  19, 0.8200, 'Trulicity (dulaglutide) for Type 2 Diabetes'),
    ('victoza%',                  'GLP-1 Agonist',               'E11.9',  19, 0.8200, 'Victoza (liraglutide) for Type 2 Diabetes'),
    ('byetta%',                   'GLP-1 Agonist',               'E11.9',  19, 0.8200, 'Byetta (exenatide) for Type 2 Diabetes'),
    ('bydureon%',                 'GLP-1 Agonist',               'E11.9',  19, 0.8200, 'Bydureon (exenatide ER) for Type 2 Diabetes'),
    ('mounjaro%',                 'GLP-1/GIP Dual Agonist',      'E11.9',  19, 0.8500, 'Mounjaro (tirzepatide) for Type 2 Diabetes'),
    ('rybelsus%',                 'GLP-1 Agonist',               'E11.9',  19, 0.8200, 'Rybelsus (oral semaglutide) for Type 2 Diabetes'),

    # --- Meglitinides ---
    ('nateglinide%',              'Meglitinide',                 'E11.9',  19, 0.8000, 'Meglitinide used exclusively for Type 2 Diabetes'),
    ('repaglinide%',              'Meglitinide',                 'E11.9',  19, 0.8000, 'Meglitinide used exclusively for Type 2 Diabetes'),
    ('starlix%',                  'Meglitinide',                 'E11.9',  19, 0.8000, 'Starlix (nateglinide) for Type 2 Diabetes'),
    ('prandin%',                  'Meglitinide',                 'E11.9',  19, 0.8000, 'Prandin (repaglinide) for Type 2 Diabetes'),

    # --- Alpha-glucosidase inhibitors ---
    ('acarbose%',                 'Alpha-Glucosidase Inhibitor', 'E11.9',  19, 0.8200, 'Acarbose used exclusively for Type 2 Diabetes'),
    ('miglitol%',                 'Alpha-Glucosidase Inhibitor', 'E11.9',  19, 0.8200, 'Miglitol used exclusively for Type 2 Diabetes'),

    # --- Other diabetes-specific agents ---
    ('pramlintide%',              'Amylin Analog',               'E11.9',  19, 0.9000, 'Pramlintide (Symlin) used exclusively in diabetes'),
    ('colesevelam%',              'Bile Acid Sequestrant (DM)',   'E11.9',  19, 0.6500, 'Colesevelam for glucose-lowering; also used for lipids'),
    ('bromocriptine%',            'Dopamine Agonist (DM)',       'E11.9',  19, 0.6000, 'Cycloset (bromocriptine) FDA-approved for T2DM; also Parkinson'),

    # --- Combination products (branded) ---
    ('janumet%',                  'DPP-4/Metformin Combo',       'E11.9',  19, 0.8500, 'Janumet (sitagliptin + metformin) for T2DM'),
    ('kombiglyze%',               'DPP-4/Metformin Combo',       'E11.9',  19, 0.8500, 'Kombiglyze (saxagliptin + metformin) for T2DM'),
    ('jentadueto%',               'DPP-4/Metformin Combo',       'E11.9',  19, 0.8500, 'Jentadueto (linagliptin + metformin) for T2DM'),
    ('synjardy%',                 'SGLT2/Metformin Combo',       'E11.9',  19, 0.8500, 'Synjardy (empagliflozin + metformin) for T2DM'),
    ('xigduo%',                   'SGLT2/Metformin Combo',       'E11.9',  19, 0.8500, 'Xigduo (dapagliflozin + metformin) for T2DM'),
    ('glyxambi%',                 'SGLT2/DPP-4 Combo',           'E11.9',  19, 0.8500, 'Glyxambi (empagliflozin + linagliptin) for T2DM'),
    ('soliqua%',                  'GLP-1/Insulin Combo',         'E11.9',  19, 0.8800, 'Soliqua (insulin glargine + lixisenatide) for T2DM'),
    ('xultophy%',                 'GLP-1/Insulin Combo',         'E11.9',  19, 0.8800, 'Xultophy (insulin degludec + liraglutide) for T2DM'),

    # --- Glucometer / continuous glucose monitor (ancillary device signals) ---
    ('freestyle libre%',          'CGM Device',                  'E11.9',  19, 0.7500, 'CGM device prescription strongly implies diabetes'),
    ('dexcom%',                   'CGM Device',                  'E11.9',  19, 0.7500, 'CGM device prescription strongly implies diabetes'),

    # =========================================================================
    # CONGESTIVE HEART FAILURE  (I50.9 -> HCC 85)
    # =========================================================================

    # --- Beta blockers FDA-approved for HF ---
    ('bisoprolol%',               'Beta Blocker (HF)',           'I50.9',  85, 0.7000, 'Bisoprolol evidence-based for HFrEF; also used for HTN'),
    ('coreg%',                    'Beta Blocker (HF)',           'I50.9',  85, 0.7000, 'Coreg (carvedilol) FDA-approved for CHF'),
    ('toprol%xl%',                'Beta Blocker (HF)',           'I50.9',  85, 0.6500, 'Toprol-XL (metoprolol succinate) for CHF'),

    # --- ACE inhibitors (CHF indication; lower confidence, also used for HTN) ---
    ('lisinopril%',               'ACE Inhibitor',               'I50.9',  85, 0.5000, 'ACE inhibitor: guideline-directed for CHF; also used for HTN'),
    ('enalapril%',                'ACE Inhibitor',               'I50.9',  85, 0.5000, 'ACE inhibitor: guideline-directed for CHF; also used for HTN'),
    ('ramipril%',                 'ACE Inhibitor',               'I50.9',  85, 0.5000, 'ACE inhibitor: guideline-directed for CHF; also used for HTN'),
    ('benazepril%',               'ACE Inhibitor',               'I50.9',  85, 0.5000, 'ACE inhibitor: guideline-directed for CHF; also used for HTN'),
    ('captopril%',                'ACE Inhibitor',               'I50.9',  85, 0.5000, 'ACE inhibitor: guideline-directed for CHF; also used for HTN'),
    ('fosinopril%',               'ACE Inhibitor',               'I50.9',  85, 0.5000, 'ACE inhibitor: guideline-directed for CHF; also used for HTN'),
    ('quinapril%',                'ACE Inhibitor',               'I50.9',  85, 0.5000, 'ACE inhibitor: guideline-directed for CHF; also used for HTN'),
    ('trandolapril%',             'ACE Inhibitor',               'I50.9',  85, 0.5000, 'ACE inhibitor: guideline-directed for CHF; also used for HTN'),
    ('perindopril%',              'ACE Inhibitor',               'I50.9',  85, 0.5000, 'ACE inhibitor: guideline-directed for CHF; also used for HTN'),

    # --- ARBs (HF indication; lower confidence) ---
    ('valsartan%',                'ARB',                         'I50.9',  85, 0.5000, 'ARB: guideline-directed for CHF; also used for HTN'),
    ('losartan%',                 'ARB',                         'I50.9',  85, 0.4500, 'ARB: used for CHF and HTN; moderate CHF specificity'),
    ('candesartan%',              'ARB',                         'I50.9',  85, 0.5000, 'ARB: guideline-directed for CHF; also used for HTN'),

    # --- Aldosterone antagonists (strong CHF signal) ---
    ('spironolactone%',           'Aldosterone Antagonist',      'I50.9',  85, 0.7000, 'Spironolactone: used for HFrEF; also for resistant HTN, cirrhosis'),
    ('eplerenone%',               'Aldosterone Antagonist',      'I50.9',  85, 0.8000, 'Eplerenone: higher CHF specificity than spironolactone'),
    ('inspra%',                   'Aldosterone Antagonist',      'I50.9',  85, 0.8000, 'Inspra (eplerenone) for heart failure'),

    # --- ARNI ---
    ('entresto%',                 'ARNI',                        'I50.9',  85, 0.9200, 'Entresto (sacubitril/valsartan) exclusively for HFrEF'),

    # --- Other CHF-specific ---
    ('ivabradine%',               'If Channel Blocker',          'I50.9',  85, 0.9000, 'Ivabradine (Corlanor) indicated exclusively for HFrEF'),
    ('corlanor%',                 'If Channel Blocker',          'I50.9',  85, 0.9000, 'Corlanor (ivabradine) exclusively for HFrEF'),
    ('hydralazine%',              'Vasodilator (HF)',            'I50.9',  85, 0.6500, 'Hydralazine: guideline-directed for HFrEF in AA pts; also HTN'),
    ('isosorbide dinitrate%',     'Nitrate (HF)',                'I50.9',  85, 0.5500, 'Isosorbide dinitrate: used with hydralazine for CHF; also angina'),
    ('bidil%',                    'Vasodilator Combo (HF)',      'I50.9',  85, 0.9000, 'BiDil (hydralazine + isosorbide dinitrate) exclusively for CHF'),
    ('vericiguat%',               'sGC Stimulator',              'I50.9',  85, 0.9200, 'Vericiguat (Verquvo) indicated exclusively for worsening CHF'),
    ('verquvo%',                  'sGC Stimulator',              'I50.9',  85, 0.9200, 'Verquvo (vericiguat) exclusively for worsening CHF'),
    ('dapagliflozin%',            'SGLT2 Inhibitor (HF)',        'I50.9',  85, 0.7000, 'Dapagliflozin (Farxiga) approved for HFrEF; also used for DM'),
    ('empagliflozin%',            'SGLT2 Inhibitor (HF)',        'I50.9',  85, 0.7000, 'Empagliflozin (Jardiance) approved for HFrEF; also used for DM'),

    # --- Loop diuretic brands ---
    ('lasix%',                    'Loop Diuretic',               'I50.9',  85, 0.7500, 'Lasix (furosemide) for CHF volume management'),
    ('bumex%',                    'Loop Diuretic',               'I50.9',  85, 0.7500, 'Bumex (bumetanide) for CHF volume management'),
    ('demadex%',                  'Loop Diuretic',               'I50.9',  85, 0.7500, 'Demadex (torsemide) for CHF volume management'),

    # =========================================================================
    # CHRONIC KIDNEY DISEASE  (N18.x -> HCC 136/137/138)
    # HCC 138=Stage 3, HCC 137=Stage 4, HCC 136=Stage 5/ESRD
    # Consistent with existing seed data
    # =========================================================================

    # --- Phosphate binders (CKD Stage 3-5) ---
    ('lanthanum%',                'Phosphate Binder',            'N18.4',  137, 0.8500, 'Lanthanum carbonate for hyperphosphatemia in CKD'),
    ('calcium acetate%',          'Phosphate Binder',            'N18.4',  137, 0.8000, 'Calcium acetate (PhosLo) for hyperphosphatemia in CKD'),
    ('phoslo%',                   'Phosphate Binder',            'N18.4',  137, 0.8000, 'PhosLo (calcium acetate) for CKD hyperphosphatemia'),
    ('sucroferric%',              'Phosphate Binder',            'N18.4',  137, 0.8500, 'Sucroferric oxyhydroxide (Velphoro) for CKD'),
    ('velphoro%',                 'Phosphate Binder',            'N18.4',  137, 0.8500, 'Velphoro (sucroferric oxyhydroxide) for CKD'),
    ('ferric citrate%',           'Phosphate Binder',            'N18.4',  137, 0.8000, 'Ferric citrate (Auryxia) for CKD hyperphosphatemia'),
    ('auryxia%',                  'Phosphate Binder',            'N18.4',  137, 0.8000, 'Auryxia (ferric citrate) for CKD'),
    ('renagel%',                  'Phosphate Binder',            'N18.3',  138, 0.8500, 'Renagel (sevelamer HCl) for CKD hyperphosphatemia'),
    ('renvela%',                  'Phosphate Binder',            'N18.3',  138, 0.8500, 'Renvela (sevelamer carbonate) for CKD'),

    # --- ESA / anemia of CKD (advanced CKD signals) ---
    ('etelcalcetide%',            'Calcimimetic',                'N18.5',  136, 0.9000, 'Etelcalcetide (Parsabiv) for secondary hyperPTH in dialysis'),
    ('parsabiv%',                 'Calcimimetic',                'N18.5',  136, 0.9000, 'Parsabiv (etelcalcetide) for dialysis patients'),
    ('sensipar%',                 'Calcimimetic',                'N18.4',  137, 0.9000, 'Sensipar (cinacalcet) for secondary hyperPTH in CKD'),
    ('aranesp%',                  'ESA',                         'N18.4',  137, 0.9000, 'Aranesp (darbepoetin) for CKD-related anemia'),
    ('procrit%',                  'ESA',                         'N18.4',  137, 0.9000, 'Procrit (epoetin alfa) for CKD-related anemia'),
    ('epogen%',                   'ESA',                         'N18.4',  137, 0.9000, 'Epogen (epoetin alfa) for CKD-related anemia'),
    ('mircera%',                  'ESA (Long-Acting)',           'N18.4',  137, 0.9000, 'Mircera (methoxy PEG-epoetin beta) for CKD anemia'),

    # --- Potassium binders (CKD hyperkalemia) ---
    ('patiromer%',                'Potassium Binder',            'N18.4',  137, 0.8000, 'Patiromer (Veltassa) for hyperkalemia in CKD'),
    ('veltassa%',                 'Potassium Binder',            'N18.4',  137, 0.8000, 'Veltassa (patiromer) for hyperkalemia in CKD'),
    ('sodium zirconium%',         'Potassium Binder',            'N18.4',  137, 0.8000, 'Sodium zirconium cyclosilicate (Lokelma) for CKD hyperkalemia'),
    ('lokelma%',                  'Potassium Binder',            'N18.4',  137, 0.8000, 'Lokelma (sodium zirconium cyclosilicate) for CKD'),

    # --- Vitamin D analogs (CKD bone disease) ---
    ('calcitriol%',               'Active Vitamin D',            'N18.3',  138, 0.7000, 'Calcitriol for CKD mineral and bone disorder'),
    ('paricalcitol%',             'Active Vitamin D Analog',     'N18.3',  138, 0.8000, 'Paricalcitol (Zemplar) for secondary hyperPTH in CKD'),
    ('zemplar%',                  'Active Vitamin D Analog',     'N18.3',  138, 0.8000, 'Zemplar (paricalcitol) for CKD-related hyperPTH'),
    ('doxercalciferol%',          'Active Vitamin D Analog',     'N18.3',  138, 0.8000, 'Doxercalciferol (Hectorol) for secondary hyperPTH'),

    # =========================================================================
    # COPD  (J44.1 -> HCC 111)
    # =========================================================================

    # --- Short-acting bronchodilators (lower specificity: also used in asthma) ---
    ('albuterol%',                'SABA',                        'J44.1',  111, 0.4500, 'Albuterol: SABA for COPD and asthma; low COPD specificity'),
    ('levalbuterol%',             'SABA',                        'J44.1',  111, 0.4500, 'Levalbuterol: SABA for COPD and asthma'),
    ('proventil%',                'SABA',                        'J44.1',  111, 0.4500, 'Proventil (albuterol) for COPD and asthma'),
    ('ventolin%',                 'SABA',                        'J44.1',  111, 0.4500, 'Ventolin (albuterol) for COPD and asthma'),
    ('proair%',                   'SABA',                        'J44.1',  111, 0.4500, 'ProAir (albuterol) for COPD and asthma'),
    ('xopenex%',                  'SABA',                        'J44.1',  111, 0.4500, 'Xopenex (levalbuterol) for COPD and asthma'),

    # --- LAMA (high COPD specificity) ---
    ('glycopyrrolate%',           'LAMA Bronchodilator',         'J44.1',  111, 0.8500, 'LAMA: primarily for COPD maintenance therapy'),
    ('aclidinium%',               'LAMA Bronchodilator',         'J44.1',  111, 0.9000, 'Aclidinium (Tudorza) exclusively for COPD'),
    ('revefenacin%',              'LAMA Bronchodilator',         'J44.1',  111, 0.9200, 'Revefenacin (Yupelri) exclusively for COPD (nebulized)'),
    ('spiriva%',                  'LAMA Bronchodilator',         'J44.1',  111, 0.9000, 'Spiriva (tiotropium) for COPD maintenance'),
    ('tudorza%',                  'LAMA Bronchodilator',         'J44.1',  111, 0.9000, 'Tudorza (aclidinium) exclusively for COPD'),
    ('incruse%',                  'LAMA Bronchodilator',         'J44.1',  111, 0.9000, 'Incruse Ellipta (umeclidinium) exclusively for COPD'),
    ('lonhala%',                  'LAMA Bronchodilator',         'J44.1',  111, 0.9000, 'Lonhala (glycopyrrolate nebulized) for COPD'),
    ('yupelri%',                  'LAMA Bronchodilator',         'J44.1',  111, 0.9200, 'Yupelri (revefenacin) exclusively for COPD'),
    ('seebri%',                   'LAMA Bronchodilator',         'J44.1',  111, 0.9000, 'Seebri (glycopyrrolate) for COPD'),

    # --- LABA (moderate COPD specificity: some used for asthma) ---
    ('indacaterol%',              'LABA Bronchodilator',         'J44.1',  111, 0.8500, 'Indacaterol (Arcapta) for COPD maintenance'),
    ('olodaterol%',               'LABA Bronchodilator',         'J44.1',  111, 0.8500, 'Olodaterol (Striverdi) exclusively for COPD'),
    ('formoterol%',               'LABA Bronchodilator',         'J44.1',  111, 0.7000, 'Formoterol: LABA for COPD and severe asthma'),
    ('salmeterol%',               'LABA Bronchodilator',         'J44.1',  111, 0.7000, 'Salmeterol: LABA for COPD and asthma'),
    ('arcapta%',                  'LABA Bronchodilator',         'J44.1',  111, 0.8500, 'Arcapta (indacaterol) for COPD'),
    ('striverdi%',                'LABA Bronchodilator',         'J44.1',  111, 0.8500, 'Striverdi (olodaterol) exclusively for COPD'),

    # --- LAMA/LABA combinations (COPD-specific) ---
    ('umeclidinium%vilanterol%',  'LAMA/LABA Combo',             'J44.1',  111, 0.9200, 'Anoro Ellipta: LAMA/LABA exclusively for COPD'),
    ('anoro%',                    'LAMA/LABA Combo',             'J44.1',  111, 0.9200, 'Anoro Ellipta: LAMA/LABA exclusively for COPD'),
    ('tiotropium%olodaterol%',    'LAMA/LABA Combo',             'J44.1',  111, 0.9200, 'Stiolto Respimat: LAMA/LABA exclusively for COPD'),
    ('stiolto%',                  'LAMA/LABA Combo',             'J44.1',  111, 0.9200, 'Stiolto Respimat exclusively for COPD'),
    ('glycopyrrolate%formoterol%','LAMA/LABA Combo',             'J44.1',  111, 0.9200, 'Bevespi Aerosphere: LAMA/LABA exclusively for COPD'),
    ('bevespi%',                  'LAMA/LABA Combo',             'J44.1',  111, 0.9200, 'Bevespi Aerosphere exclusively for COPD'),
    ('glycopyrrolate%indacaterol%','LAMA/LABA Combo',            'J44.1',  111, 0.9200, 'Utibron Neohaler: LAMA/LABA exclusively for COPD'),
    ('utibron%',                  'LAMA/LABA Combo',             'J44.1',  111, 0.9200, 'Utibron exclusively for COPD'),

    # --- Triple therapy (COPD-specific) ---
    ('fluticasone%umeclidinium%vilanterol%', 'ICS/LAMA/LABA Triple', 'J44.1', 111, 0.9500, 'Trelegy Ellipta: triple therapy exclusively for COPD'),
    ('trelegy%',                  'ICS/LAMA/LABA Triple',        'J44.1',  111, 0.9500, 'Trelegy Ellipta triple therapy exclusively for COPD'),
    ('budesonide%glycopyrrolate%formoterol%', 'ICS/LAMA/LABA Triple', 'J44.1', 111, 0.9500, 'Breztri Aerosphere: triple therapy exclusively for COPD'),
    ('breztri%',                  'ICS/LAMA/LABA Triple',        'J44.1',  111, 0.9500, 'Breztri Aerosphere triple therapy exclusively for COPD'),

    # --- SAMA / SAMA+SABA (moderate COPD specificity) ---
    ('ipratropium%',              'SAMA',                        'J44.1',  111, 0.7500, 'Ipratropium: anticholinergic primarily for COPD'),
    ('ipratropium%albuterol%',    'SAMA/SABA Combo',             'J44.1',  111, 0.7500, 'Ipratropium/albuterol (DuoNeb/Combivent) for COPD'),
    ('combivent%',                'SAMA/SABA Combo',             'J44.1',  111, 0.7500, 'Combivent (ipratropium/albuterol) for COPD'),
    ('duoneb%',                   'SAMA/SABA Combo',             'J44.1',  111, 0.7500, 'DuoNeb (ipratropium/albuterol nebulized) for COPD'),
    ('atrovent%',                 'SAMA',                        'J44.1',  111, 0.7500, 'Atrovent (ipratropium) for COPD'),

    # --- PDE4 inhibitor ---
    ('daliresp%',                 'PDE4 Inhibitor',              'J44.1',  111, 0.9500, 'Daliresp (roflumilast) exclusively for severe COPD'),

    # --- Theophylline (older agent) ---
    ('theophylline%',             'Methylxanthine',              'J44.1',  111, 0.6500, 'Theophylline: used for COPD and severe asthma'),

    # =========================================================================
    # ATRIAL FIBRILLATION  (I48.91 -> HCC 96)
    # =========================================================================

    # --- Antiarrhythmics ---
    ('flecainide%',               'Antiarrhythmic Class IC',     'I48.91', 96, 0.8500, 'Flecainide for rhythm control in AFib; also flutter/SVT'),
    ('sotalol%',                  'Antiarrhythmic Class III',    'I48.91', 96, 0.8000, 'Sotalol for rhythm control in AFib; also VT'),
    ('dofetilide%',               'Antiarrhythmic Class III',    'I48.91', 96, 0.9200, 'Dofetilide (Tikosyn) primarily for AFib/AFL conversion'),
    ('tikosyn%',                  'Antiarrhythmic Class III',    'I48.91', 96, 0.9200, 'Tikosyn (dofetilide) primarily for AFib'),
    ('propafenone%',              'Antiarrhythmic Class IC',     'I48.91', 96, 0.8500, 'Propafenone for rhythm control in AFib'),
    ('multaq%',                   'Antiarrhythmic',              'I48.91', 96, 0.9000, 'Multaq (dronedarone) exclusively for AFib'),

    # --- DOAC brands ---
    ('eliquis%',                  'Factor Xa Inhibitor (DOAC)',  'I48.91', 96, 0.8000, 'Eliquis (apixaban) primarily for AFib stroke prevention'),
    ('xarelto%',                  'Factor Xa Inhibitor (DOAC)',  'I48.91', 96, 0.7800, 'Xarelto (rivaroxaban) for AFib stroke prevention and VTE'),
    ('pradaxa%',                  'Direct Thrombin Inhibitor',   'I48.91', 96, 0.8000, 'Pradaxa (dabigatran) for AFib stroke prevention'),
    ('savaysa%',                  'Factor Xa Inhibitor (DOAC)',  'I48.91', 96, 0.8000, 'Savaysa (edoxaban) for AFib stroke prevention'),

    # =========================================================================
    # MAJOR DEPRESSION  (F33.0 -> HCC 155)
    # =========================================================================

    # --- SSRIs (moderate specificity: also used for anxiety, OCD, PTSD) ---
    ('sertraline%',               'SSRI',                        'F33.0', 155, 0.6500, 'SSRI: first-line for major depression; also anxiety/OCD/PTSD'),
    ('fluoxetine%',               'SSRI',                        'F33.0', 155, 0.6500, 'SSRI: first-line for major depression; also anxiety/OCD/bulimia'),
    ('paroxetine%',               'SSRI',                        'F33.0', 155, 0.6500, 'SSRI: first-line for major depression; also anxiety/PTSD'),
    ('citalopram%',               'SSRI',                        'F33.0', 155, 0.6500, 'SSRI: first-line for major depression; also anxiety'),
    ('escitalopram%',             'SSRI',                        'F33.0', 155, 0.6500, 'SSRI: first-line for major depression and GAD'),
    ('fluvoxamine%',              'SSRI',                        'F33.0', 155, 0.6000, 'SSRI: primarily for OCD; also used for depression'),
    ('zoloft%',                   'SSRI',                        'F33.0', 155, 0.6500, 'Zoloft (sertraline) for major depression'),
    ('prozac%',                   'SSRI',                        'F33.0', 155, 0.6500, 'Prozac (fluoxetine) for major depression'),
    ('paxil%',                    'SSRI',                        'F33.0', 155, 0.6500, 'Paxil (paroxetine) for major depression'),
    ('lexapro%',                  'SSRI',                        'F33.0', 155, 0.6500, 'Lexapro (escitalopram) for major depression'),
    ('celexa%',                   'SSRI',                        'F33.0', 155, 0.6500, 'Celexa (citalopram) for major depression'),

    # --- SNRIs ---
    ('venlafaxine%',              'SNRI',                        'F33.0', 155, 0.6500, 'SNRI: for major depression and GAD; also neuropathic pain'),
    ('duloxetine%',               'SNRI',                        'F33.0', 155, 0.6000, 'SNRI: for depression, GAD, neuropathic pain, fibromyalgia'),
    ('desvenlafaxine%',           'SNRI',                        'F33.0', 155, 0.7000, 'SNRI: FDA-approved specifically for major depression'),
    ('levomilnacipran%',          'SNRI',                        'F33.0', 155, 0.7500, 'SNRI: FDA-approved specifically for major depression'),
    ('effexor%',                  'SNRI',                        'F33.0', 155, 0.6500, 'Effexor (venlafaxine) for major depression'),
    ('cymbalta%',                 'SNRI',                        'F33.0', 155, 0.6000, 'Cymbalta (duloxetine) for depression and chronic pain'),
    ('pristiq%',                  'SNRI',                        'F33.0', 155, 0.7000, 'Pristiq (desvenlafaxine) for major depression'),
    ('fetzima%',                  'SNRI',                        'F33.0', 155, 0.7500, 'Fetzima (levomilnacipran) for major depression'),

    # --- Atypical antidepressants ---
    ('bupropion%',                'Atypical Antidepressant',     'F33.0', 155, 0.6000, 'Bupropion: for depression; also smoking cessation (Zyban)'),
    ('mirtazapine%',              'Atypical Antidepressant',     'F33.0', 155, 0.7000, 'Mirtazapine: used primarily for major depression'),
    ('vilazodone%',               'SSRI/5-HT1A Partial Agonist', 'F33.0', 155, 0.7500, 'Vilazodone (Viibryd) FDA-approved for major depression'),
    ('vortioxetine%',             'Multimodal Antidepressant',   'F33.0', 155, 0.7500, 'Vortioxetine (Trintellix) for major depression'),
    ('wellbutrin%',               'Atypical Antidepressant',     'F33.0', 155, 0.6000, 'Wellbutrin (bupropion) for major depression'),
    ('remeron%',                  'Atypical Antidepressant',     'F33.0', 155, 0.7000, 'Remeron (mirtazapine) for major depression'),
    ('viibryd%',                  'SSRI/5-HT1A Partial Agonist', 'F33.0', 155, 0.7500, 'Viibryd (vilazodone) for major depression'),
    ('trintellix%',               'Multimodal Antidepressant',   'F33.0', 155, 0.7500, 'Trintellix (vortioxetine) for major depression'),

    # --- TCAs (higher depression specificity at therapeutic doses) ---
    ('amitriptyline%',            'TCA',                         'F33.0', 155, 0.5000, 'TCA: for depression; often used low-dose for pain/insomnia'),
    ('nortriptyline%',            'TCA',                         'F33.0', 155, 0.5500, 'TCA: for depression and neuropathic pain'),
    ('imipramine%',               'TCA',                         'F33.0', 155, 0.6000, 'TCA: for depression and enuresis'),
    ('desipramine%',              'TCA',                         'F33.0', 155, 0.6500, 'TCA: used primarily for major depression'),
    ('clomipramine%',             'TCA',                         'F33.0', 155, 0.6000, 'TCA: for depression and OCD'),
    ('doxepin%',                  'TCA',                         'F33.0', 155, 0.4500, 'TCA: for depression; low-dose (Silenor) for insomnia'),

    # --- MAOIs (high depression specificity) ---
    ('phenelzine%',               'MAOI',                        'F33.0', 155, 0.8500, 'MAOI: used exclusively for treatment-resistant depression'),
    ('tranylcypromine%',          'MAOI',                        'F33.0', 155, 0.8500, 'MAOI: used exclusively for treatment-resistant depression'),
    ('selegiline%patch%',         'MAOI (Transdermal)',          'F33.0', 155, 0.8500, 'Emsam (selegiline patch) exclusively for depression'),

    # --- Newer agents ---
    ('esketamine%',               'NMDA Antagonist',             'F33.0', 155, 0.9500, 'Spravato (esketamine) exclusively for treatment-resistant depression'),
    ('spravato%',                 'NMDA Antagonist',             'F33.0', 155, 0.9500, 'Spravato (esketamine nasal) exclusively for TRD'),
    ('brexanolone%',              'GABA Modulator',              'F33.0', 155, 0.9500, 'Zulresso (brexanolone) exclusively for postpartum depression'),

    # =========================================================================
    # VASCULAR DISEASE  (I70.0 -> HCC 107, I73.9 -> HCC 108)
    # =========================================================================

    # --- Antiplatelet agents (atherosclerotic vascular disease) ---
    ('clopidogrel%',              'Antiplatelet (P2Y12)',         'I70.0', 107, 0.7000, 'P2Y12 inhibitor: for atherosclerotic CVD, ACS, PAD, stents'),
    ('ticagrelor%',               'Antiplatelet (P2Y12)',         'I70.0', 107, 0.8000, 'P2Y12 inhibitor: primarily for ACS/coronary disease'),
    ('prasugrel%',                'Antiplatelet (P2Y12)',         'I70.0', 107, 0.8500, 'P2Y12 inhibitor: exclusively for ACS after PCI'),
    ('plavix%',                   'Antiplatelet (P2Y12)',         'I70.0', 107, 0.7000, 'Plavix (clopidogrel) for atherosclerotic CVD'),
    ('brilinta%',                 'Antiplatelet (P2Y12)',         'I70.0', 107, 0.8000, 'Brilinta (ticagrelor) for coronary artery disease'),
    ('effient%',                  'Antiplatelet (P2Y12)',         'I70.0', 107, 0.8500, 'Effient (prasugrel) for ACS after PCI'),
    ('vorapaxar%',                'PAR-1 Antagonist',            'I70.0', 107, 0.9000, 'Vorapaxar (Zontivity) exclusively for atherothrombotic events'),
    ('ticlopidine%',              'Antiplatelet',                'I70.0', 107, 0.7500, 'Ticlopidine: older antiplatelet for atherosclerotic disease'),

    # --- Peripheral vascular disease ---
    ('cilostazol%',               'PDE3 Inhibitor',              'I73.9', 108, 0.9000, 'Cilostazol (Pletal) indicated exclusively for intermittent claudication'),
    ('pentoxifylline%',           'Hemorrheologic Agent',        'I73.9', 108, 0.8500, 'Pentoxifylline (Trental) for peripheral vascular disease'),
    ('pletal%',                   'PDE3 Inhibitor',              'I73.9', 108, 0.9000, 'Pletal (cilostazol) exclusively for intermittent claudication'),
    ('trental%',                  'Hemorrheologic Agent',        'I73.9', 108, 0.8500, 'Trental (pentoxifylline) for peripheral vascular disease'),

    # =========================================================================
    # SEIZURE / EPILEPSY  (G40.909 -> HCC 79)
    # =========================================================================

    # --- Broad-spectrum AEDs ---
    ('levetiracetam%',            'Anticonvulsant',              'G40.909', 79, 0.7500, 'Levetiracetam (Keppra): broad-spectrum AED primarily for epilepsy'),
    ('lamotrigine%',              'Anticonvulsant',              'G40.909', 79, 0.6500, 'Lamotrigine: for epilepsy; also bipolar maintenance'),
    ('valproic acid%',            'Anticonvulsant',              'G40.909', 79, 0.6500, 'Valproic acid: for epilepsy; also bipolar mania and migraine'),
    ('divalproex%',               'Anticonvulsant',              'G40.909', 79, 0.6500, 'Divalproex: for epilepsy, bipolar, and migraine'),
    ('topiramate%',               'Anticonvulsant',              'G40.909', 79, 0.5500, 'Topiramate: for epilepsy; also migraine and weight management'),

    # --- Sodium channel blockers ---
    ('carbamazepine%',            'Anticonvulsant (Na Channel)', 'G40.909', 79, 0.7000, 'Carbamazepine: for epilepsy; also trigeminal neuralgia and bipolar'),
    ('oxcarbazepine%',            'Anticonvulsant (Na Channel)', 'G40.909', 79, 0.8000, 'Oxcarbazepine (Trileptal): primarily for partial seizures'),
    ('phenytoin%',                'Anticonvulsant (Na Channel)', 'G40.909', 79, 0.8000, 'Phenytoin (Dilantin): classic AED for epilepsy'),
    ('lacosamide%',               'Anticonvulsant (Na Channel)', 'G40.909', 79, 0.8500, 'Lacosamide (Vimpat): for partial-onset seizures'),
    ('eslicarbazepine%',          'Anticonvulsant (Na Channel)', 'G40.909', 79, 0.8500, 'Eslicarbazepine (Aptiom): exclusively for partial seizures'),
    ('cenobamate%',               'Anticonvulsant',              'G40.909', 79, 0.9000, 'Cenobamate (Xcopri): exclusively for partial-onset seizures'),

    # --- Older AEDs (high epilepsy specificity) ---
    ('phenobarbital%',            'Barbiturate Anticonvulsant',  'G40.909', 79, 0.8000, 'Phenobarbital: traditional AED for epilepsy'),
    ('primidone%',                'Anticonvulsant',              'G40.909', 79, 0.7500, 'Primidone: for epilepsy; also essential tremor'),
    ('ethosuximide%',             'Anticonvulsant (T-Type Ca)',  'G40.909', 79, 0.9500, 'Ethosuximide: exclusively for absence seizures'),

    # --- Newer AEDs ---
    ('brivaracetam%',             'Anticonvulsant (SV2A)',       'G40.909', 79, 0.9000, 'Brivaracetam (Briviact): exclusively for partial-onset seizures'),
    ('perampanel%',               'Anticonvulsant (AMPA)',       'G40.909', 79, 0.9000, 'Perampanel (Fycompa): exclusively for epilepsy'),
    ('vigabatrin%',               'Anticonvulsant (GABA)',       'G40.909', 79, 0.9000, 'Vigabatrin (Sabril): for refractory epilepsy/infantile spasms'),
    ('clobazam%',                 'Benzodiazepine AED',          'G40.909', 79, 0.8500, 'Clobazam (Onfi): adjunctive for Lennox-Gastaut epilepsy'),
    ('rufinamide%',               'Anticonvulsant',              'G40.909', 79, 0.9200, 'Rufinamide (Banzel): exclusively for Lennox-Gastaut syndrome'),
    ('felbamate%',                'Anticonvulsant',              'G40.909', 79, 0.9200, 'Felbamate: reserved for severe/refractory epilepsy'),
    ('zonisamide%',               'Anticonvulsant',              'G40.909', 79, 0.7500, 'Zonisamide: for epilepsy; off-label for migraine/weight'),
    ('cannabidiol%',              'Anticonvulsant (CBD)',         'G40.909', 79, 0.9500, 'Epidiolex (cannabidiol) exclusively for refractory epilepsy'),

    # --- Brand names ---
    ('keppra%',                   'Anticonvulsant',              'G40.909', 79, 0.7500, 'Keppra (levetiracetam) for epilepsy'),
    ('lamictal%',                 'Anticonvulsant',              'G40.909', 79, 0.6500, 'Lamictal (lamotrigine) for epilepsy and bipolar'),
    ('depakote%',                 'Anticonvulsant',              'G40.909', 79, 0.6500, 'Depakote (divalproex) for epilepsy and bipolar'),
    ('tegretol%',                 'Anticonvulsant',              'G40.909', 79, 0.7000, 'Tegretol (carbamazepine) for epilepsy'),
    ('dilantin%',                 'Anticonvulsant',              'G40.909', 79, 0.8000, 'Dilantin (phenytoin) for epilepsy'),
    ('trileptal%',                'Anticonvulsant',              'G40.909', 79, 0.8000, 'Trileptal (oxcarbazepine) for epilepsy'),
    ('vimpat%',                   'Anticonvulsant',              'G40.909', 79, 0.8500, 'Vimpat (lacosamide) for epilepsy'),
    ('topamax%',                  'Anticonvulsant',              'G40.909', 79, 0.5500, 'Topamax (topiramate) for epilepsy and migraine'),
    ('briviact%',                 'Anticonvulsant',              'G40.909', 79, 0.9000, 'Briviact (brivaracetam) for epilepsy'),
    ('fycompa%',                  'Anticonvulsant',              'G40.909', 79, 0.9000, 'Fycompa (perampanel) for epilepsy'),
    ('xcopri%',                   'Anticonvulsant',              'G40.909', 79, 0.9000, 'Xcopri (cenobamate) for epilepsy'),
    ('epidiolex%',                'Anticonvulsant (CBD)',         'G40.909', 79, 0.9500, 'Epidiolex (cannabidiol) for refractory epilepsy'),
    ('aptiom%',                   'Anticonvulsant',              'G40.909', 79, 0.8500, 'Aptiom (eslicarbazepine) for epilepsy'),

    # =========================================================================
    # RHEUMATOID ARTHRITIS / AUTOIMMUNE  (M05.9 -> HCC 40)
    # =========================================================================

    # --- Conventional DMARDs ---
    ('hydroxychloroquine%',       'DMARD (Antimalarial)',         'M05.9',  40, 0.7000, 'Hydroxychloroquine: anchor DMARD for RA and SLE'),
    ('sulfasalazine%',            'DMARD (Aminosalicylate)',      'M05.9',  40, 0.7000, 'Sulfasalazine: DMARD for RA; also used for IBD'),
    ('leflunomide%',              'DMARD (Pyrimidine Inhibitor)','M05.9',  40, 0.8500, 'Leflunomide (Arava): DMARD primarily for RA'),
    ('plaquenil%',                'DMARD (Antimalarial)',         'M05.9',  40, 0.7000, 'Plaquenil (hydroxychloroquine) for RA and SLE'),
    ('arava%',                    'DMARD (Pyrimidine Inhibitor)','M05.9',  40, 0.8500, 'Arava (leflunomide) for RA'),
    ('azulfidine%',               'DMARD (Aminosalicylate)',      'M05.9',  40, 0.7000, 'Azulfidine (sulfasalazine) for RA'),

    # --- TNF inhibitors ---
    ('infliximab%',               'TNF Inhibitor (Biologic)',     'M05.9',  40, 0.8500, 'Remicade: TNF inhibitor for RA, IBD, psoriasis, AS'),
    ('certolizumab%',             'TNF Inhibitor (Biologic)',     'M05.9',  40, 0.8500, 'Cimzia: TNF inhibitor for RA, Crohn, psoriasis, AS'),
    ('golimumab%',                'TNF Inhibitor (Biologic)',     'M05.9',  40, 0.9000, 'Simponi: TNF inhibitor for RA, PsA, AS, UC'),
    ('remicade%',                 'TNF Inhibitor (Biologic)',     'M05.9',  40, 0.8500, 'Remicade (infliximab) for RA and autoimmune'),
    ('humira%',                   'TNF Inhibitor (Biologic)',     'M05.9',  40, 0.9000, 'Humira (adalimumab) for RA and autoimmune'),
    ('enbrel%',                   'TNF Inhibitor (Biologic)',     'M05.9',  40, 0.9000, 'Enbrel (etanercept) for RA and autoimmune'),
    ('cimzia%',                   'TNF Inhibitor (Biologic)',     'M05.9',  40, 0.8500, 'Cimzia (certolizumab) for RA'),
    ('simponi%',                  'TNF Inhibitor (Biologic)',     'M05.9',  40, 0.9000, 'Simponi (golimumab) for RA'),

    # --- JAK inhibitors (high RA specificity) ---
    ('tofacitinib%',              'JAK Inhibitor',               'M05.9',  40, 0.9000, 'Xeljanz: JAK inhibitor for RA, PsA, UC'),
    ('baricitinib%',              'JAK Inhibitor',               'M05.9',  40, 0.9000, 'Olumiant: JAK inhibitor primarily for RA'),
    ('upadacitinib%',             'JAK Inhibitor',               'M05.9',  40, 0.9000, 'Rinvoq: JAK inhibitor for RA, PsA, AS, UC, AD'),
    ('xeljanz%',                  'JAK Inhibitor',               'M05.9',  40, 0.9000, 'Xeljanz (tofacitinib) for RA'),
    ('olumiant%',                 'JAK Inhibitor',               'M05.9',  40, 0.9000, 'Olumiant (baricitinib) for RA'),
    ('rinvoq%',                   'JAK Inhibitor',               'M05.9',  40, 0.9000, 'Rinvoq (upadacitinib) for RA'),

    # --- Other targeted therapies ---
    ('abatacept%',                'T-cell Co-stimulation Blocker','M05.9', 40, 0.9000, 'Orencia: T-cell modulator for RA'),
    ('tocilizumab%',              'IL-6 Receptor Inhibitor',     'M05.9',  40, 0.8500, 'Actemra: IL-6 inhibitor for RA and giant cell arteritis'),
    ('sarilumab%',                'IL-6 Receptor Inhibitor',     'M05.9',  40, 0.9000, 'Kevzara: IL-6 inhibitor for RA'),
    ('orencia%',                  'T-cell Co-stimulation Blocker','M05.9', 40, 0.9000, 'Orencia (abatacept) for RA'),
    ('actemra%',                  'IL-6 Receptor Inhibitor',     'M05.9',  40, 0.8500, 'Actemra (tocilizumab) for RA'),
    ('kevzara%',                  'IL-6 Receptor Inhibitor',     'M05.9',  40, 0.9000, 'Kevzara (sarilumab) for RA'),
    ('rituxan%',                  'Anti-CD20 Biologic',          'M05.9',  40, 0.8500, 'Rituxan (rituximab) for RA refractory to TNF'),

    # =========================================================================
    # PARKINSON DISEASE  (G20 -> HCC 78)
    # =========================================================================

    ('rotigotine%',               'Dopamine Agonist',            'G20',    78, 0.8500, 'Rotigotine (Neupro) for Parkinson disease and RLS'),
    ('entacapone%',               'COMT Inhibitor',              'G20',    78, 0.9500, 'Entacapone (Comtan): exclusively adjunct to levodopa for PD'),
    ('tolcapone%',                'COMT Inhibitor',              'G20',    78, 0.9500, 'Tolcapone (Tasmar): COMT inhibitor exclusively for PD'),
    ('opicapone%',                'COMT Inhibitor',              'G20',    78, 0.9500, 'Opicapone (Ongentys): COMT inhibitor exclusively for PD'),
    ('safinamide%',               'MAO-B Inhibitor',             'G20',    78, 0.9500, 'Safinamide (Xadago): MAO-B inhibitor exclusively for PD'),
    ('amantadine%',               'Dopaminergic (NMDA)',         'G20',    78, 0.7000, 'Amantadine: for PD dyskinesia; also influenza/MS fatigue'),
    ('apomorphine%',              'Dopamine Agonist',            'G20',    78, 0.9500, 'Apomorphine (Apokyn): exclusively for PD off episodes'),
    ('istradefylline%',           'Adenosine A2A Antagonist',    'G20',    78, 0.9500, 'Istradefylline (Nourianz): exclusively adjunct for PD'),
    ('stalevo%',                  'Levodopa/Carbidopa/Entacapone','G20',   78, 0.9500, 'Stalevo: triple combo exclusively for Parkinson disease'),
    ('sinemet%',                  'Dopaminergic',                'G20',    78, 0.9500, 'Sinemet (carbidopa/levodopa) for Parkinson disease'),
    ('neupro%',                   'Dopamine Agonist',            'G20',    78, 0.8500, 'Neupro (rotigotine) for Parkinson disease'),
    ('mirapex%',                  'Dopamine Agonist',            'G20',    78, 0.8500, 'Mirapex (pramipexole) for Parkinson disease'),
    ('requip%',                   'Dopamine Agonist',            'G20',    78, 0.8500, 'Requip (ropinirole) for Parkinson disease'),
    ('comtan%',                   'COMT Inhibitor',              'G20',    78, 0.9500, 'Comtan (entacapone) adjunct for Parkinson disease'),
    ('azilect%',                  'MAO-B Inhibitor',             'G20',    78, 0.9500, 'Azilect (rasagiline) for Parkinson disease'),
    ('xadago%',                   'MAO-B Inhibitor',             'G20',    78, 0.9500, 'Xadago (safinamide) for Parkinson disease'),
    ('eldepryl%',                 'MAO-B Inhibitor',             'G20',    78, 0.9200, 'Eldepryl (selegiline) for Parkinson disease'),
    ('nourianz%',                 'Adenosine A2A Antagonist',    'G20',    78, 0.9500, 'Nourianz (istradefylline) adjunct for PD'),
    ('inbrija%',                  'Levodopa Inhaler',            'G20',    78, 0.9500, 'Inbrija (inhaled levodopa) exclusively for PD off episodes'),
    ('gocovri%',                  'Amantadine ER',               'G20',    78, 0.9000, 'Gocovri (amantadine ER) for PD dyskinesia'),

    # =========================================================================
    # HIV / AIDS  (B20 -> HCC 1)
    # =========================================================================

    # --- NRTIs ---
    ('abacavir%',                 'NRTI (ART)',                  'B20',    1,  0.9500, 'NRTI backbone: indicates active HIV treatment'),
    ('lamivudine%',               'NRTI (ART)',                  'B20',    1,  0.8000, 'NRTI: for HIV ART; also used for Hepatitis B (lower dose)'),
    ('zidovudine%',               'NRTI (ART)',                  'B20',    1,  0.9500, 'AZT/ZDV: legacy NRTI for HIV ART'),
    ('stavudine%',                'NRTI (ART)',                  'B20',    1,  0.9500, 'Stavudine (d4T): legacy NRTI for HIV ART'),
    ('didanosine%',               'NRTI (ART)',                  'B20',    1,  0.9500, 'Didanosine (ddI): legacy NRTI for HIV ART'),
    ('epivir%',                   'NRTI (ART)',                  'B20',    1,  0.8000, 'Epivir (lamivudine) for HIV ART'),
    ('ziagen%',                   'NRTI (ART)',                  'B20',    1,  0.9500, 'Ziagen (abacavir) for HIV ART'),
    ('descovy%',                  'NRTI Combo (ART)',            'B20',    1,  0.9000, 'Descovy (TAF/FTC): NRTI backbone for HIV ART and PrEP'),
    ('truvada%',                  'NRTI Combo (ART)',            'B20',    1,  0.8500, 'Truvada (TDF/FTC): for HIV ART and PrEP'),

    # --- Integrase inhibitors ---
    ('raltegravir%',              'Integrase Inhibitor (ART)',   'B20',    1,  0.9800, 'Raltegravir (Isentress): HIV integrase inhibitor'),
    ('cabotegravir%',             'Integrase Inhibitor (ART)',   'B20',    1,  0.9500, 'Cabotegravir: long-acting HIV integrase inhibitor and PrEP'),
    ('isentress%',                'Integrase Inhibitor (ART)',   'B20',    1,  0.9800, 'Isentress (raltegravir) for HIV ART'),
    ('tivicay%',                  'Integrase Inhibitor (ART)',   'B20',    1,  0.9800, 'Tivicay (dolutegravir) for HIV ART'),

    # --- Protease inhibitors ---
    ('darunavir%',                'Protease Inhibitor (ART)',    'B20',    1,  0.9800, 'Darunavir: HIV protease inhibitor'),
    ('atazanavir%',               'Protease Inhibitor (ART)',    'B20',    1,  0.9800, 'Atazanavir: HIV protease inhibitor'),
    ('lopinavir%',                'Protease Inhibitor (ART)',    'B20',    1,  0.9800, 'Lopinavir (Kaletra combo): HIV protease inhibitor'),
    ('ritonavir%',                'Protease Inhibitor (ART)',    'B20',    1,  0.8000, 'Ritonavir: HIV PI booster; also used in COVID (Paxlovid)'),
    ('prezista%',                 'Protease Inhibitor (ART)',    'B20',    1,  0.9800, 'Prezista (darunavir) for HIV ART'),
    ('reyataz%',                  'Protease Inhibitor (ART)',    'B20',    1,  0.9800, 'Reyataz (atazanavir) for HIV ART'),

    # --- NNRTIs ---
    ('efavirenz%',                'NNRTI (ART)',                 'B20',    1,  0.9500, 'Efavirenz: NNRTI for HIV ART'),
    ('rilpivirine%',              'NNRTI (ART)',                 'B20',    1,  0.9500, 'Rilpivirine: NNRTI for HIV ART'),
    ('doravirine%',               'NNRTI (ART)',                 'B20',    1,  0.9500, 'Doravirine (Pifeltro): newer NNRTI for HIV ART'),
    ('etravirine%',               'NNRTI (ART)',                 'B20',    1,  0.9500, 'Etravirine (Intelence): NNRTI for treatment-experienced HIV'),
    ('nevirapine%',               'NNRTI (ART)',                 'B20',    1,  0.9500, 'Nevirapine: NNRTI for HIV ART'),
    ('sustiva%',                  'NNRTI (ART)',                 'B20',    1,  0.9500, 'Sustiva (efavirenz) for HIV ART'),
    ('edurant%',                  'NNRTI (ART)',                 'B20',    1,  0.9500, 'Edurant (rilpivirine) for HIV ART'),
    ('pifeltro%',                 'NNRTI (ART)',                 'B20',    1,  0.9500, 'Pifeltro (doravirine) for HIV ART'),

    # --- Fixed-dose combination ART regimens (very high specificity) ---
    ('biktarvy%',                 'STR (ART)',                   'B20',    1,  0.9800, 'Biktarvy (BIC/FTC/TAF): complete HIV ART regimen'),
    ('triumeq%',                  'STR (ART)',                   'B20',    1,  0.9800, 'Triumeq (DTG/ABC/3TC): complete HIV ART regimen'),
    ('genvoya%',                  'STR (ART)',                   'B20',    1,  0.9800, 'Genvoya (EVG/c/FTC/TAF): complete HIV ART regimen'),
    ('stribild%',                 'STR (ART)',                   'B20',    1,  0.9800, 'Stribild (EVG/c/FTC/TDF): complete HIV ART regimen'),
    ('dovato%',                   'STR (ART)',                   'B20',    1,  0.9800, 'Dovato (DTG/3TC): 2-drug HIV ART regimen'),
    ('juluca%',                   'STR (ART)',                   'B20',    1,  0.9800, 'Juluca (DTG/RPV): 2-drug HIV ART maintenance'),
    ('symtuza%',                  'STR (ART)',                   'B20',    1,  0.9800, 'Symtuza (DRV/c/FTC/TAF): complete HIV ART regimen'),
    ('delstrigo%',                'STR (ART)',                   'B20',    1,  0.9800, 'Delstrigo (DOR/3TC/TDF): complete HIV ART regimen'),
    ('odefsey%',                  'STR (ART)',                   'B20',    1,  0.9800, 'Odefsey (RPV/FTC/TAF): complete HIV ART regimen'),
    ('atripla%',                  'STR (ART)',                   'B20',    1,  0.9800, 'Atripla (EFV/FTC/TDF): complete HIV ART regimen'),
    ('complera%',                 'STR (ART)',                   'B20',    1,  0.9800, 'Complera (RPV/FTC/TDF): complete HIV ART regimen'),
    ('cabenuva%',                 'Long-Acting ART Injection',   'B20',    1,  0.9800, 'Cabenuva (CAB+RPV LA injection): monthly HIV ART'),
    ('apretude%',                 'Long-Acting ART Injection',   'B20',    1,  0.9000, 'Apretude (cabotegravir LA): for HIV PrEP; moderate HIV dx signal'),
    ('lenacapavir%',              'Capsid Inhibitor (ART)',      'B20',    1,  0.9800, 'Sunlenca (lenacapavir): for multidrug-resistant HIV'),

    # --- Entry/attachment inhibitors ---
    ('maraviroc%',                'CCR5 Antagonist (ART)',       'B20',    1,  0.9800, 'Maraviroc (Selzentry): HIV CCR5 antagonist'),
    ('fostemsavir%',              'Attachment Inhibitor (ART)',  'B20',    1,  0.9800, 'Fostemsavir (Rukobia): for heavily treatment-experienced HIV'),
    ('ibalizumab%',               'Post-Attachment Inhibitor',   'B20',    1,  0.9800, 'Ibalizumab (Trogarzo): for multidrug-resistant HIV'),

    # =========================================================================
    # SCHIZOPHRENIA / PSYCHOSIS  (F20.9 -> HCC 57)
    # =========================================================================

    # --- Atypical antipsychotics (SGAs) ---
    ('olanzapine%',               'Atypical Antipsychotic',      'F20.9',  57, 0.7500, 'Olanzapine: for schizophrenia and bipolar; moderate specificity'),
    ('risperidone%',              'Atypical Antipsychotic',      'F20.9',  57, 0.7500, 'Risperidone: for schizophrenia, bipolar, irritability in autism'),
    ('quetiapine%',               'Atypical Antipsychotic',      'F20.9',  57, 0.5000, 'Quetiapine: for schizophrenia/bipolar; heavily off-label for insomnia'),
    ('aripiprazole%',             'Atypical Antipsychotic',      'F20.9',  57, 0.6000, 'Aripiprazole: for schizophrenia/bipolar; also MDD augmentation'),
    ('ziprasidone%',              'Atypical Antipsychotic',      'F20.9',  57, 0.8000, 'Ziprasidone: primarily for schizophrenia and acute bipolar mania'),
    ('lurasidone%',               'Atypical Antipsychotic',      'F20.9',  57, 0.8000, 'Lurasidone (Latuda): for schizophrenia and bipolar depression'),
    ('brexpiprazole%',            'Atypical Antipsychotic',      'F20.9',  57, 0.7500, 'Brexpiprazole (Rexulti): for schizophrenia; also MDD adjunct'),
    ('cariprazine%',              'Atypical Antipsychotic',      'F20.9',  57, 0.8000, 'Cariprazine (Vraylar): for schizophrenia and bipolar'),
    ('asenapine%',                'Atypical Antipsychotic',      'F20.9',  57, 0.8000, 'Asenapine (Saphris): for schizophrenia and bipolar mania'),
    ('iloperidone%',              'Atypical Antipsychotic',      'F20.9',  57, 0.8500, 'Iloperidone (Fanapt): primarily for schizophrenia'),
    ('pimozide%',                 'Typical Antipsychotic',       'F20.9',  57, 0.8000, 'Pimozide: for schizophrenia and Tourette syndrome'),

    # --- Brand names ---
    ('zyprexa%',                  'Atypical Antipsychotic',      'F20.9',  57, 0.7500, 'Zyprexa (olanzapine) for schizophrenia'),
    ('risperdal%',                'Atypical Antipsychotic',      'F20.9',  57, 0.7500, 'Risperdal (risperidone) for schizophrenia'),
    ('seroquel%',                 'Atypical Antipsychotic',      'F20.9',  57, 0.5000, 'Seroquel (quetiapine) for schizophrenia/bipolar'),
    ('abilify%',                  'Atypical Antipsychotic',      'F20.9',  57, 0.6000, 'Abilify (aripiprazole) for schizophrenia/bipolar'),
    ('geodon%',                   'Atypical Antipsychotic',      'F20.9',  57, 0.8000, 'Geodon (ziprasidone) for schizophrenia'),
    ('latuda%',                   'Atypical Antipsychotic',      'F20.9',  57, 0.8000, 'Latuda (lurasidone) for schizophrenia'),
    ('rexulti%',                  'Atypical Antipsychotic',      'F20.9',  57, 0.7500, 'Rexulti (brexpiprazole) for schizophrenia'),
    ('vraylar%',                  'Atypical Antipsychotic',      'F20.9',  57, 0.8000, 'Vraylar (cariprazine) for schizophrenia'),
    ('invega%',                   'Atypical Antipsychotic',      'F20.9',  57, 0.8500, 'Invega (paliperidone) for schizophrenia'),
    ('saphris%',                  'Atypical Antipsychotic',      'F20.9',  57, 0.8000, 'Saphris (asenapine) for schizophrenia'),
    ('fanapt%',                   'Atypical Antipsychotic',      'F20.9',  57, 0.8500, 'Fanapt (iloperidone) for schizophrenia'),
    ('clozaril%',                 'Atypical Antipsychotic',      'F20.9',  57, 0.9500, 'Clozaril (clozapine) for treatment-resistant schizophrenia'),

    # --- Typical antipsychotics (FGAs) ---
    ('haloperidol%',              'Typical Antipsychotic',       'F20.9',  57, 0.7000, 'Haloperidol: FGA for schizophrenia and acute psychosis'),
    ('chlorpromazine%',           'Typical Antipsychotic',       'F20.9',  57, 0.7000, 'Chlorpromazine: FGA for schizophrenia'),
    ('fluphenazine%',             'Typical Antipsychotic',       'F20.9',  57, 0.8000, 'Fluphenazine (decanoate LAI): for chronic schizophrenia'),
    ('perphenazine%',             'Typical Antipsychotic',       'F20.9',  57, 0.7500, 'Perphenazine: FGA for schizophrenia'),
    ('thiothixene%',              'Typical Antipsychotic',       'F20.9',  57, 0.8000, 'Thiothixene: FGA primarily for schizophrenia'),
    ('trifluoperazine%',          'Typical Antipsychotic',       'F20.9',  57, 0.8000, 'Trifluoperazine: FGA primarily for schizophrenia'),
    ('loxapine%',                 'Typical Antipsychotic',       'F20.9',  57, 0.8000, 'Loxapine: for schizophrenia; inhaled form (Adasuve) for agitation'),

    # --- Long-acting injectables (high specificity for chronic psychosis) ---
    ('paliperidone palmitate%',   'LAI Antipsychotic',           'F20.9',  57, 0.9200, 'Invega Sustenna/Trinza: long-acting injectable for schizophrenia'),
    ('aripiprazole lauroxil%',    'LAI Antipsychotic',           'F20.9',  57, 0.9000, 'Aristada: long-acting injectable for schizophrenia'),
    ('aristada%',                 'LAI Antipsychotic',           'F20.9',  57, 0.9000, 'Aristada (aripiprazole lauroxil LAI) for schizophrenia'),
    ('abilify maintena%',         'LAI Antipsychotic',           'F20.9',  57, 0.9000, 'Abilify Maintena (aripiprazole LAI) for schizophrenia'),

    # =========================================================================
    # ORGAN TRANSPLANT  (Z94.0 -> HCC 186)
    # =========================================================================

    ('everolimus%',               'mTOR Inhibitor',              'Z94.0',  186, 0.8500, 'Everolimus: for transplant; also used for certain cancers'),
    ('zortress%',                 'mTOR Inhibitor',              'Z94.0',  186, 0.9200, 'Zortress (everolimus) for kidney transplant'),
    ('prograf%',                  'Calcineurin Inhibitor',       'Z94.0',  186, 0.9500, 'Prograf (tacrolimus) for organ transplant'),
    ('neoral%',                   'Calcineurin Inhibitor',       'Z94.0',  186, 0.9200, 'Neoral (cyclosporine) for organ transplant'),
    ('cellcept%',                 'Antimetabolite Immunosuppressant', 'Z94.0', 186, 0.9000, 'CellCept (mycophenolate) for organ transplant'),
    ('myfortic%',                 'Antimetabolite Immunosuppressant', 'Z94.0', 186, 0.9000, 'Myfortic (mycophenolic acid) for kidney transplant'),
    ('rapamune%',                 'mTOR Inhibitor',              'Z94.0',  186, 0.9200, 'Rapamune (sirolimus) for organ transplant'),
    ('azathioprine%',             'Immunosuppressant',           'Z94.0',  186, 0.6000, 'Azathioprine: for transplant and autoimmune; lower specificity'),
    ('imuran%',                   'Immunosuppressant',           'Z94.0',  186, 0.6000, 'Imuran (azathioprine) for transplant'),
    ('belatacept%',               'Co-stimulation Blocker',      'Z94.0',  186, 0.9500, 'Nulojix (belatacept) exclusively for kidney transplant'),
    ('nulojix%',                  'Co-stimulation Blocker',      'Z94.0',  186, 0.9500, 'Nulojix (belatacept) exclusively for kidney transplant'),
    ('basiliximab%',              'IL-2R Antagonist',             'Z94.0',  186, 0.9500, 'Simulect (basiliximab) induction for kidney transplant'),

    # =========================================================================
    # HEPATITIS C  (B18.2 -> HCC 6)
    # =========================================================================

    ('sofosbuvir%',               'NS5B Inhibitor (HCV DAA)',    'B18.2',  6,  0.9800, 'Sofosbuvir: HCV direct-acting antiviral exclusively for Hep C'),
    ('ledipasvir%',               'NS5A Inhibitor (HCV DAA)',    'B18.2',  6,  0.9800, 'Ledipasvir: HCV DAA component exclusively for Hep C'),
    ('velpatasvir%',              'NS5A Inhibitor (HCV DAA)',    'B18.2',  6,  0.9800, 'Velpatasvir: HCV DAA component exclusively for Hep C'),
    ('glecaprevir%',              'NS3/4A Inhibitor (HCV DAA)',  'B18.2',  6,  0.9800, 'Glecaprevir: HCV protease inhibitor exclusively for Hep C'),
    ('pibrentasvir%',             'NS5A Inhibitor (HCV DAA)',    'B18.2',  6,  0.9800, 'Pibrentasvir: HCV DAA component exclusively for Hep C'),
    ('elbasvir%',                 'NS5A Inhibitor (HCV DAA)',    'B18.2',  6,  0.9800, 'Elbasvir: HCV DAA component exclusively for Hep C'),
    ('grazoprevir%',              'NS3/4A Inhibitor (HCV DAA)',  'B18.2',  6,  0.9800, 'Grazoprevir: HCV protease inhibitor exclusively for Hep C'),
    ('daclatasvir%',              'NS5A Inhibitor (HCV DAA)',    'B18.2',  6,  0.9800, 'Daclatasvir: HCV DAA exclusively for Hep C'),
    ('voxilaprevir%',             'NS3/4A Inhibitor (HCV DAA)',  'B18.2',  6,  0.9800, 'Voxilaprevir: HCV protease inhibitor exclusively for Hep C'),
    ('harvoni%',                  'HCV DAA Combo',               'B18.2',  6,  0.9800, 'Harvoni (ledipasvir/sofosbuvir) exclusively for Hep C'),
    ('epclusa%',                  'HCV DAA Combo',               'B18.2',  6,  0.9800, 'Epclusa (sofosbuvir/velpatasvir) exclusively for Hep C'),
    ('mavyret%',                  'HCV DAA Combo',               'B18.2',  6,  0.9800, 'Mavyret (glecaprevir/pibrentasvir) exclusively for Hep C'),
    ('zepatier%',                 'HCV DAA Combo',               'B18.2',  6,  0.9800, 'Zepatier (elbasvir/grazoprevir) exclusively for Hep C'),
    ('vosevi%',                   'HCV DAA Combo',               'B18.2',  6,  0.9800, 'Vosevi (sofosbuvir/velpatasvir/voxilaprevir) for Hep C'),
    ('sovaldi%',                  'NS5B Inhibitor (HCV DAA)',    'B18.2',  6,  0.9800, 'Sovaldi (sofosbuvir) exclusively for Hep C'),
    ('ribavirin%',                'Antiviral (HCV Adjunct)',     'B18.2',  6,  0.7000, 'Ribavirin: adjunct for Hep C; also used for RSV, Hep E'),

    # =========================================================================
    # MULTIPLE SCLEROSIS  (G35 -> HCC 75)
    # =========================================================================

    ('dimethyl fumarate%',        'Nrf2 Activator (MS DMT)',     'G35',   75, 0.9500, 'Tecfidera: disease-modifying therapy exclusively for MS'),
    ('fingolimod%',               'S1P Receptor Modulator (MS)', 'G35',   75, 0.9500, 'Gilenya: S1P modulator exclusively for relapsing MS'),
    ('glatiramer%',               'Immunomodulator (MS DMT)',    'G35',   75, 0.9500, 'Copaxone: immunomodulator exclusively for relapsing MS'),
    ('interferon beta%',          'Interferon (MS DMT)',         'G35',   75, 0.9200, 'Interferon beta: for relapsing MS (Avonex, Rebif, Betaseron)'),
    ('natalizumab%',              'Anti-VLA4 mAb (MS)',          'G35',   75, 0.9500, 'Tysabri: for relapsing MS; also severe Crohn disease'),
    ('ocrelizumab%',              'Anti-CD20 mAb (MS)',          'G35',   75, 0.9500, 'Ocrevus: for relapsing and primary progressive MS'),
    ('siponimod%',                'S1P Receptor Modulator (MS)', 'G35',   75, 0.9500, 'Mayzent: S1P modulator for secondary progressive MS'),
    ('ozanimod%',                 'S1P Receptor Modulator (MS)', 'G35',   75, 0.9000, 'Zeposia: S1P modulator for relapsing MS; also UC'),
    ('ponesimod%',                'S1P Receptor Modulator (MS)', 'G35',   75, 0.9500, 'Ponvory: S1P modulator exclusively for relapsing MS'),
    ('teriflunomide%',            'Pyrimidine Inhibitor (MS)',   'G35',   75, 0.9500, 'Aubagio: for relapsing MS'),
    ('cladribine%',               'Purine Analog (MS)',          'G35',   75, 0.9000, 'Mavenclad: for relapsing MS; also hairy cell leukemia'),
    ('ofatumumab%',               'Anti-CD20 mAb (MS)',          'G35',   75, 0.9500, 'Kesimpta: for relapsing MS'),
    ('ublituximab%',              'Anti-CD20 mAb (MS)',          'G35',   75, 0.9500, 'Briumvi: for relapsing MS'),
    ('tecfidera%',                'Nrf2 Activator (MS DMT)',     'G35',   75, 0.9500, 'Tecfidera (dimethyl fumarate) for MS'),
    ('gilenya%',                  'S1P Receptor Modulator (MS)', 'G35',   75, 0.9500, 'Gilenya (fingolimod) for MS'),
    ('copaxone%',                 'Immunomodulator (MS DMT)',    'G35',   75, 0.9500, 'Copaxone (glatiramer) for MS'),
    ('tysabri%',                  'Anti-VLA4 mAb (MS)',          'G35',   75, 0.9500, 'Tysabri (natalizumab) for MS'),
    ('ocrevus%',                  'Anti-CD20 mAb (MS)',          'G35',   75, 0.9500, 'Ocrevus (ocrelizumab) for MS'),
    ('aubagio%',                  'Pyrimidine Inhibitor (MS)',   'G35',   75, 0.9500, 'Aubagio (teriflunomide) for MS'),
    ('mavenclad%',                'Purine Analog (MS)',          'G35',   75, 0.9000, 'Mavenclad (cladribine) for MS'),
    ('kesimpta%',                 'Anti-CD20 mAb (MS)',          'G35',   75, 0.9500, 'Kesimpta (ofatumumab) for MS'),
    ('avonex%',                   'Interferon Beta-1a (MS)',     'G35',   75, 0.9200, 'Avonex (interferon beta-1a) for MS'),
    ('rebif%',                    'Interferon Beta-1a (MS)',     'G35',   75, 0.9200, 'Rebif (interferon beta-1a) for MS'),
    ('betaseron%',                'Interferon Beta-1b (MS)',     'G35',   75, 0.9200, 'Betaseron (interferon beta-1b) for MS'),
    ('plegridy%',                 'PEG-Interferon Beta-1a (MS)', 'G35',   75, 0.9200, 'Plegridy (PEG-interferon beta-1a) for MS'),
    ('vumerity%',                 'Nrf2 Activator (MS DMT)',     'G35',   75, 0.9500, 'Vumerity (diroximel fumarate) for MS'),
    ('bafiertam%',                'Nrf2 Activator (MS DMT)',     'G35',   75, 0.9500, 'Bafiertam (monomethyl fumarate) for MS'),
    ('mayzent%',                  'S1P Receptor Modulator (MS)', 'G35',   75, 0.9500, 'Mayzent (siponimod) for MS'),
    ('zeposia%',                  'S1P Receptor Modulator (MS)', 'G35',   75, 0.9000, 'Zeposia (ozanimod) for MS/UC'),
    ('ponvory%',                  'S1P Receptor Modulator (MS)', 'G35',   75, 0.9500, 'Ponvory (ponesimod) for MS'),

    # =========================================================================
    # CIRRHOSIS / CHRONIC LIVER DISEASE  (K74.60 -> HCC 28)
    # =========================================================================

    ('lactulose%',                'Osmotic Laxative (HE)',       'K74.60', 28, 0.8500, 'Lactulose for hepatic encephalopathy indicates cirrhosis'),
    ('rifaximin%',                'Non-Absorbable Antibiotic',   'K74.60', 28, 0.8500, 'Rifaximin (Xifaxan 550): for hepatic encephalopathy in cirrhosis'),
    ('xifaxan%',                  'Non-Absorbable Antibiotic',   'K74.60', 28, 0.8500, 'Xifaxan (rifaximin) for hepatic encephalopathy'),
    ('nadolol%',                  'Beta Blocker (Portal HTN)',   'K74.60', 28, 0.6000, 'Nadolol: for portal hypertension prophylaxis in cirrhosis'),
    ('propranolol%',              'Beta Blocker (Portal HTN)',   'K74.60', 28, 0.4500, 'Propranolol: for portal HTN; also used for HTN/migraine/tremor'),
    ('terlipressin%',             'Vasopressin Analog',          'K74.60', 28, 0.9500, 'Terlipressin (Terlivaz) for hepatorenal syndrome in cirrhosis'),
    ('terlivaz%',                 'Vasopressin Analog',          'K74.60', 28, 0.9500, 'Terlivaz (terlipressin) for hepatorenal syndrome'),
    ('midodrine%',                'Alpha Agonist (HRS)',         'K74.60', 28, 0.5000, 'Midodrine: for HRS in cirrhosis; also orthostatic hypotension'),
    ('octreotide%',               'Somatostatin Analog',         'K74.60', 28, 0.5000, 'Octreotide: for variceal bleeding; also carcinoid/acromegaly'),

    # =========================================================================
    # PULMONARY ARTERIAL HYPERTENSION  (I27.0 -> HCC 85)
    # Using HCC 85 (same bucket as heart failure in V24/V28)
    # =========================================================================

    ('bosentan%',                 'Endothelin Receptor Antagonist', 'I27.0', 85, 0.9500, 'Tracleer: ERA exclusively for PAH'),
    ('ambrisentan%',              'Endothelin Receptor Antagonist', 'I27.0', 85, 0.9500, 'Letairis: ERA exclusively for PAH'),
    ('macitentan%',               'Endothelin Receptor Antagonist', 'I27.0', 85, 0.9500, 'Opsumit: ERA exclusively for PAH'),
    ('sildenafil%',               'PDE5 Inhibitor (PAH)',        'I27.0',  85, 0.6000, 'Sildenafil: Revatio dose for PAH; also used for ED (Viagra)'),
    ('tadalafil%',                'PDE5 Inhibitor (PAH)',        'I27.0',  85, 0.6000, 'Tadalafil: Adcirca for PAH; also used for ED/BPH (Cialis)'),
    ('riociguat%',                'sGC Stimulator (PAH)',        'I27.0',  85, 0.9500, 'Adempas: sGC stimulator exclusively for PAH/CTEPH'),
    ('epoprostenol%',             'Prostacyclin (PAH)',          'I27.0',  85, 0.9800, 'Flolan/Veletri: IV prostacyclin exclusively for PAH'),
    ('treprostinil%',             'Prostacyclin Analog (PAH)',   'I27.0',  85, 0.9500, 'Remodulin/Tyvaso: prostacyclin analog exclusively for PAH'),
    ('iloprost%',                 'Prostacyclin Analog (PAH)',   'I27.0',  85, 0.9500, 'Ventavis: inhaled prostacyclin exclusively for PAH'),
    ('selexipag%',                'IP Receptor Agonist (PAH)',   'I27.0',  85, 0.9800, 'Uptravi: IP receptor agonist exclusively for PAH'),
    ('tracleer%',                 'ERA (PAH)',                   'I27.0',  85, 0.9500, 'Tracleer (bosentan) for PAH'),
    ('letairis%',                 'ERA (PAH)',                   'I27.0',  85, 0.9500, 'Letairis (ambrisentan) for PAH'),
    ('opsumit%',                  'ERA (PAH)',                   'I27.0',  85, 0.9500, 'Opsumit (macitentan) for PAH'),
    ('revatio%',                  'PDE5 Inhibitor (PAH)',        'I27.0',  85, 0.8500, 'Revatio (sildenafil PAH dose) exclusively for PAH'),
    ('adcirca%',                  'PDE5 Inhibitor (PAH)',        'I27.0',  85, 0.8500, 'Adcirca (tadalafil PAH dose) exclusively for PAH'),
    ('adempas%',                  'sGC Stimulator (PAH)',        'I27.0',  85, 0.9500, 'Adempas (riociguat) for PAH/CTEPH'),
    ('uptravi%',                  'IP Receptor Agonist (PAH)',   'I27.0',  85, 0.9800, 'Uptravi (selexipag) for PAH'),
    ('tyvaso%',                   'Prostacyclin Analog (PAH)',   'I27.0',  85, 0.9500, 'Tyvaso (treprostinil inhaled) for PAH'),
    ('orenitram%',                'Prostacyclin Analog (PAH)',   'I27.0',  85, 0.9500, 'Orenitram (treprostinil oral) for PAH'),

    # =========================================================================
    # LUPUS / SLE  (M32.9 -> HCC 40, same autoimmune bucket as RA)
    # =========================================================================

    ('belimumab%',                'Anti-BLyS mAb',              'M32.9',  40, 0.9500, 'Benlysta: anti-BLyS exclusively for SLE and lupus nephritis'),
    ('benlysta%',                 'Anti-BLyS mAb',              'M32.9',  40, 0.9500, 'Benlysta (belimumab) exclusively for lupus'),
    ('anifrolumab%',              'Anti-IFNAR1 mAb',            'M32.9',  40, 0.9800, 'Saphnelo (anifrolumab) exclusively for SLE'),
    ('saphnelo%',                 'Anti-IFNAR1 mAb',            'M32.9',  40, 0.9800, 'Saphnelo (anifrolumab) exclusively for lupus'),
    ('voclosporin%',              'Calcineurin Inhibitor (LN)',  'M32.9',  40, 0.9500, 'Lupkynis (voclosporin) exclusively for lupus nephritis'),
    ('lupkynis%',                 'Calcineurin Inhibitor (LN)',  'M32.9',  40, 0.9500, 'Lupkynis (voclosporin) exclusively for lupus nephritis'),

    # =========================================================================
    # DEMENTIA (G30.9 -> HCC 52)  -- additional entries beyond existing seed
    # =========================================================================

    ('aducanumab%',               'Anti-Amyloid mAb',           'G30.9',  52, 0.9800, 'Aduhelm: anti-amyloid exclusively for Alzheimer disease'),
    ('lecanemab%',                'Anti-Amyloid mAb',           'G30.9',  52, 0.9800, 'Leqembi: anti-amyloid exclusively for early Alzheimer'),
    ('donanemab%',                'Anti-Amyloid mAb',           'G30.9',  52, 0.9800, 'Kisunla: anti-amyloid exclusively for early Alzheimer'),
    ('aduhelm%',                  'Anti-Amyloid mAb',           'G30.9',  52, 0.9800, 'Aduhelm (aducanumab) for Alzheimer disease'),
    ('leqembi%',                  'Anti-Amyloid mAb',           'G30.9',  52, 0.9800, 'Leqembi (lecanemab) for early Alzheimer disease'),
    ('kisunla%',                  'Anti-Amyloid mAb',           'G30.9',  52, 0.9800, 'Kisunla (donanemab) for early Alzheimer disease'),
    ('aricept%',                  'Cholinesterase Inhibitor',    'G30.9',  52, 0.9200, 'Aricept (donepezil) for Alzheimer dementia'),
    ('namenda%',                  'NMDA Receptor Antagonist',    'G30.9',  52, 0.9200, 'Namenda (memantine) for moderate-severe Alzheimer'),
    ('exelon%',                   'Cholinesterase Inhibitor',    'G30.9',  52, 0.9000, 'Exelon (rivastigmine) for Alzheimer/Parkinson dementia'),
    ('razadyne%',                 'Cholinesterase Inhibitor',    'G30.9',  52, 0.9000, 'Razadyne (galantamine) for Alzheimer dementia'),
    ('namzaric%',                 'ChEI/NMDA Combo',            'G30.9',  52, 0.9500, 'Namzaric (donepezil + memantine) exclusively for Alzheimer'),

    # =========================================================================
    # MORBID OBESITY  (E66.01 -> HCC 22)  -- additional entries
    # =========================================================================

    ('liraglutide%',              'GLP-1 Agonist (Obesity)',     'E66.01', 22, 0.6500, 'Liraglutide 3mg (Saxenda) for chronic weight management'),
    ('saxenda%',                  'GLP-1 Agonist (Obesity)',     'E66.01', 22, 0.8500, 'Saxenda (liraglutide 3mg) specifically for obesity'),
    ('wegovy%',                   'GLP-1 Agonist (Obesity)',     'E66.01', 22, 0.8500, 'Wegovy (semaglutide 2.4mg) specifically for obesity'),
    ('zepbound%',                 'GLP-1/GIP Agonist (Obesity)', 'E66.01', 22, 0.8500, 'Zepbound (tirzepatide) specifically for obesity'),
    ('qsymia%',                   'Anorectic Combination',       'E66.01', 22, 0.8500, 'Qsymia (phentermine/topiramate) for chronic weight management'),
    ('contrave%',                 'Anorectic Combination',       'E66.01', 22, 0.8500, 'Contrave (naltrexone/bupropion) for chronic weight management'),
    ('xenical%',                  'Lipase Inhibitor',            'E66.01', 22, 0.8000, 'Xenical (orlistat) for obesity management'),
    ('alli%',                     'Lipase Inhibitor',            'E66.01', 22, 0.7000, 'Alli (orlistat OTC) for weight management'),

    # =========================================================================
    # SICKLE CELL DISEASE  (D57.1 -> HCC 46)
    # =========================================================================

    ('hydroxyurea%',              'Antimetabolite (SCD)',        'D57.1',  46, 0.7500, 'Hydroxyurea: for sickle cell disease; also myeloproliferative'),
    ('voxelotor%',                'Hemoglobin S Polymerization Inhibitor', 'D57.1', 46, 0.9800, 'Oxbryta (voxelotor) exclusively for sickle cell disease'),
    ('crizanlizumab%',            'Anti-P-Selectin mAb',        'D57.1',  46, 0.9800, 'Adakveo (crizanlizumab) exclusively for SCD vaso-occlusive crises'),
    ('oxbryta%',                  'Hb S Inhibitor (SCD)',        'D57.1',  46, 0.9800, 'Oxbryta (voxelotor) exclusively for sickle cell disease'),
    ('adakveo%',                  'Anti-P-Selectin mAb',        'D57.1',  46, 0.9800, 'Adakveo (crizanlizumab) exclusively for SCD'),
    ('endari%',                   'Amino Acid (SCD)',            'D57.1',  46, 0.9500, 'Endari (L-glutamine) for sickle cell disease'),
    ('droxia%',                   'Antimetabolite (SCD)',        'D57.1',  46, 0.8500, 'Droxia (hydroxyurea) for sickle cell disease'),
    ('siklos%',                   'Antimetabolite (SCD)',        'D57.1',  46, 0.8500, 'Siklos (hydroxyurea) for sickle cell disease'),

    # =========================================================================
    # BIPOLAR DISORDER  (F31.9 -> HCC 59)
    # Additional entries beyond existing seed (lithium, valproate)
    # =========================================================================

    ('carbamazepine%',            'Mood Stabilizer/AED',         'F31.9',  59, 0.5500, 'Carbamazepine: for bipolar and epilepsy; moderate bipolar specificity'),
    ('lamotrigine%',              'Mood Stabilizer/AED',         'F31.9',  59, 0.5500, 'Lamotrigine: for bipolar maintenance and epilepsy'),
    ('lithobid%',                 'Mood Stabilizer',             'F31.9',  59, 0.9000, 'Lithobid (lithium) for bipolar disorder'),
    ('eskalith%',                 'Mood Stabilizer',             'F31.9',  59, 0.9000, 'Eskalith (lithium) for bipolar disorder'),

    # =========================================================================
    # CYSTIC FIBROSIS  (E84.0 -> HCC 110)
    # =========================================================================

    ('ivacaftor%',                'CFTR Modulator',              'E84.0', 110, 0.9800, 'Kalydeco (ivacaftor) exclusively for cystic fibrosis'),
    ('lumacaftor%',               'CFTR Modulator',              'E84.0', 110, 0.9800, 'Lumacaftor: CFTR modulator component exclusively for CF'),
    ('tezacaftor%',               'CFTR Modulator',              'E84.0', 110, 0.9800, 'Tezacaftor: CFTR modulator component exclusively for CF'),
    ('elexacaftor%',              'CFTR Modulator',              'E84.0', 110, 0.9800, 'Elexacaftor: CFTR modulator component exclusively for CF'),
    ('trikafta%',                 'CFTR Triple Combo',           'E84.0', 110, 0.9800, 'Trikafta (elexacaftor/tezacaftor/ivacaftor) exclusively for CF'),
    ('orkambi%',                  'CFTR Combo',                  'E84.0', 110, 0.9800, 'Orkambi (lumacaftor/ivacaftor) exclusively for CF'),
    ('symdeko%',                  'CFTR Combo',                  'E84.0', 110, 0.9800, 'Symdeko (tezacaftor/ivacaftor) exclusively for CF'),
    ('kalydeco%',                 'CFTR Modulator',              'E84.0', 110, 0.9800, 'Kalydeco (ivacaftor) exclusively for CF'),

    # =========================================================================
    # MYASTHENIA GRAVIS  (G70.0 -> HCC 75)
    # Same HCC bucket as MS in V24
    # =========================================================================

    ('pyridostigmine%',           'AChE Inhibitor (MG)',         'G70.0',  75, 0.9200, 'Mestinon (pyridostigmine) primarily for myasthenia gravis'),
    ('mestinon%',                 'AChE Inhibitor (MG)',         'G70.0',  75, 0.9200, 'Mestinon (pyridostigmine) for myasthenia gravis'),
    ('eculizumab%',               'Anti-C5 mAb',                'G70.0',  75, 0.8000, 'Soliris: for gMG, PNH, aHUS'),
    ('ravulizumab%',              'Anti-C5 mAb',                'G70.0',  75, 0.8000, 'Ultomiris: for gMG, PNH, aHUS'),
    ('efgartigimod%',             'FcRn Blocker',               'G70.0',  75, 0.9500, 'Vyvgart: for generalized myasthenia gravis'),
    ('vyvgart%',                  'FcRn Blocker',               'G70.0',  75, 0.9500, 'Vyvgart (efgartigimod) for gMG'),
    ('rozanolixizumab%',          'FcRn Blocker',               'G70.0',  75, 0.9500, 'Rystiggo (rozanolixizumab) for gMG'),
    ('rystiggo%',                 'FcRn Blocker',               'G70.0',  75, 0.9500, 'Rystiggo (rozanolixizumab) for gMG'),
    ('zilucoplan%',               'Anti-C5 Peptide',            'G70.0',  75, 0.9500, 'Zilbrysq (zilucoplan) for gMG'),

    # =========================================================================
    # HEMOPHILIA / COAGULATION DISORDERS  (D66 -> HCC 46)
    # Same HCC bucket as sickle cell
    # =========================================================================

    ('emicizumab%',               'Bispecific Factor IXa/X mAb', 'D66',   46, 0.9800, 'Hemlibra (emicizumab) exclusively for hemophilia A'),
    ('hemlibra%',                 'Bispecific Factor IXa/X mAb', 'D66',   46, 0.9800, 'Hemlibra (emicizumab) exclusively for hemophilia A'),
    ('factor viii%',              'Clotting Factor',             'D66',    46, 0.9500, 'Factor VIII replacement exclusively for hemophilia A'),
    ('factor ix%',                'Clotting Factor',             'D67',    46, 0.9500, 'Factor IX replacement exclusively for hemophilia B'),
    ('antihemophilic factor%',    'Clotting Factor',             'D66',    46, 0.9500, 'Antihemophilic factor for hemophilia A'),
    ('desmopressin%',             'Vasopressin Analog',          'D66',    46, 0.5500, 'DDAVP: for mild hemophilia A; also for nocturia/enuresis'),
    ('fitusiran%',                'Anti-Antithrombin siRNA',     'D66',    46, 0.9800, 'Alhemo (fitusiran) for hemophilia A and B with inhibitors'),

    # =========================================================================
    # INFLAMMATORY BOWEL DISEASE  (K50.90 Crohn / K51.90 UC -> HCC 35)
    # =========================================================================

    ('mesalamine%',               '5-ASA',                       'K51.90', 35, 0.8500, 'Mesalamine (5-ASA): first-line for ulcerative colitis'),
    ('balsalazide%',              '5-ASA',                       'K51.90', 35, 0.8500, 'Balsalazide: 5-ASA for ulcerative colitis'),
    ('olsalazine%',               '5-ASA',                       'K51.90', 35, 0.8500, 'Olsalazine: 5-ASA for ulcerative colitis'),
    ('vedolizumab%',              'Anti-Integrin mAb',           'K50.90', 35, 0.9200, 'Entyvio: gut-selective integrin inhibitor for IBD'),
    ('entyvio%',                  'Anti-Integrin mAb',           'K50.90', 35, 0.9200, 'Entyvio (vedolizumab) for Crohn and UC'),
    ('ustekinumab%',              'Anti-IL-12/23 mAb',          'K50.90', 35, 0.8000, 'Stelara: for Crohn, UC; also psoriasis and PsA'),
    ('stelara%',                  'Anti-IL-12/23 mAb',          'K50.90', 35, 0.8000, 'Stelara (ustekinumab) for Crohn disease'),
    ('risankizumab%',             'Anti-IL-23 mAb',             'K50.90', 35, 0.8000, 'Skyrizi: for Crohn; also psoriasis and PsA'),
    ('ozanimod%',                 'S1P Receptor Modulator',      'K51.90', 35, 0.8000, 'Zeposia: for UC; also relapsing MS'),
    ('asacol%',                   '5-ASA',                       'K51.90', 35, 0.8500, 'Asacol (mesalamine DR) for ulcerative colitis'),
    ('lialda%',                   '5-ASA',                       'K51.90', 35, 0.8500, 'Lialda (mesalamine) for ulcerative colitis'),
    ('pentasa%',                  '5-ASA',                       'K50.90', 35, 0.8500, 'Pentasa (mesalamine) for Crohn disease'),
    ('apriso%',                   '5-ASA',                       'K51.90', 35, 0.8500, 'Apriso (mesalamine) for ulcerative colitis'),
    ('canasa%',                   '5-ASA',                       'K51.90', 35, 0.8500, 'Canasa (mesalamine suppository) for ulcerative colitis'),
    ('rowasa%',                   '5-ASA',                       'K51.90', 35, 0.8500, 'Rowasa (mesalamine enema) for ulcerative colitis'),
    ('budesonide%',               'Local Corticosteroid (IBD)',  'K50.90', 35, 0.5000, 'Budesonide (Entocort): for Crohn; also used for asthma/COPD'),

    # =========================================================================
    # GOUT  (M10.9 -> HCC 39 in some models)
    # Not a traditional HCC in V24 but captured in V28 expansion
    # =========================================================================

    ('allopurinol%',              'Xanthine Oxidase Inhibitor',  'M10.9',  39, 0.7500, 'Allopurinol: first-line ULT for gout'),
    ('febuxostat%',               'Xanthine Oxidase Inhibitor',  'M10.9',  39, 0.8500, 'Febuxostat (Uloric): for gout when allopurinol fails'),
    ('colchicine%',               'Anti-Inflammatory (Gout)',    'M10.9',  39, 0.6500, 'Colchicine: for gout flares; also pericarditis and FMF'),
    ('pegloticase%',              'Uricase Enzyme',              'M10.9',  39, 0.9800, 'Krystexxa (pegloticase) exclusively for refractory chronic gout'),
    ('probenecid%',               'Uricosuric Agent',            'M10.9',  39, 0.8000, 'Probenecid: uricosuric for gout'),
    ('lesinurad%',                'URAT1 Inhibitor',             'M10.9',  39, 0.9000, 'Lesinurad: URAT1 inhibitor for gout'),
    ('uloric%',                   'Xanthine Oxidase Inhibitor',  'M10.9',  39, 0.8500, 'Uloric (febuxostat) for gout'),
    ('krystexxa%',                'Uricase Enzyme',              'M10.9',  39, 0.9800, 'Krystexxa (pegloticase) for refractory gout'),
    ('zyloprim%',                 'Xanthine Oxidase Inhibitor',  'M10.9',  39, 0.7500, 'Zyloprim (allopurinol) for gout'),

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
        cur.execute("SELECT COUNT(*) AS cnt FROM raf_medication_signals")
        existing_count = cur.fetchone()["cnt"]
        log.info("Table raf_medication_signals currently has %d rows.", existing_count)
    except MySQLError as exc:
        log.error("Table raf_medication_signals does not exist: %s", exc)
        log.error("Run the schema migration first (database/schema.sql).")
        cur.close()
        cnx.close()
        return 1

    # ------------------------------------------------------------------
    # 2.  Load existing (drug_name_pattern, suspect_icd10) pairs
    #     for duplicate detection (case-insensitive)
    # ------------------------------------------------------------------
    cur.execute("SELECT LOWER(drug_name_pattern) AS pat, suspect_icd10 FROM raf_medication_signals")
    existing_pairs: set[tuple[str, str]] = set()
    for row in cur.fetchall():
        existing_pairs.add((row["pat"], row["suspect_icd10"]))

    log.info("Loaded %d existing (pattern, icd10) pairs for dedup.", len(existing_pairs))

    # ------------------------------------------------------------------
    # 3.  Insert new signals
    # ------------------------------------------------------------------
    INSERT_SQL = """
        INSERT INTO raf_medication_signals
            (drug_name_pattern, drug_class, suspect_icd10, suspect_hcc,
             confidence_base, notes, is_active)
        VALUES (%s, %s, %s, %s, %s, %s, 1)
    """

    inserted = 0
    skipped = 0
    errors = 0

    for pattern, drug_class, icd10, hcc, confidence, notes in SIGNALS:
        key = (pattern.lower(), icd10)
        if key in existing_pairs:
            skipped += 1
            continue

        try:
            cur.execute(INSERT_SQL, (pattern, drug_class, icd10, hcc, confidence, notes))
            existing_pairs.add(key)
            inserted += 1
        except MySQLError as exc:
            log.warning("Failed to insert pattern=%r icd10=%s: %s", pattern, icd10, exc)
            errors += 1

    cnx.commit()

    # ------------------------------------------------------------------
    # 4.  Report
    # ------------------------------------------------------------------
    cur.execute("SELECT COUNT(*) AS cnt FROM raf_medication_signals")
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
