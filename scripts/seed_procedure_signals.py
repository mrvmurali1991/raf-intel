#!/usr/bin/env python3
"""
seed_procedure_signals.py
--------------------------
Creates and seeds the raf_procedure_signals table with CPT/procedure code
to ICD-10/HCC mappings for the RAF Intelligence suspect detection engine.

Covers the highest-impact clinical areas for Medicare Advantage risk
adjustment:

    Diabetes Management, Cardiac, Renal, Pulmonary, Oncology,
    Mental Health, Neurology, Rheumatology, Transplant, Vascular,
    GI, HIV/Infectious, DME (Durable Medical Equipment)

Data sources:
    - CMS CPT code descriptions and clinical indications
    - CMS-HCC V24 / V28 crosswalk mappings
    - Standard procedure→diagnosis clinical associations

Idempotent: checks existing (cpt_code, suspect_icd10) pairs before
inserting.  Safe to run multiple times.

Usage:
    python scripts/seed_procedure_signals.py

    # With custom DB connection:
    RAF_DB_HOST=10.1.0.204 RAF_DB_PORT=3306 RAF_DB_USER=root \\
      RAF_DB_PASSWORD=secret python scripts/seed_procedure_signals.py
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
# Table DDL
# ---------------------------------------------------------------------------
CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS raf_procedure_signals (
    id                  INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    cpt_code            VARCHAR(10)   NOT NULL,
    cpt_description     VARCHAR(255)  NOT NULL DEFAULT '',
    suspect_icd10       VARCHAR(10)   NOT NULL,
    suspect_hcc         SMALLINT UNSIGNED NOT NULL,
    confidence_base     DECIMAL(5,4)  NOT NULL DEFAULT 0.6000,
    notes               VARCHAR(500)  NOT NULL DEFAULT '',
    is_active           TINYINT(1)    NOT NULL DEFAULT 1,
    created_at          DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at          DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uq_proc (cpt_code, suspect_icd10),
    INDEX idx_cpt (cpt_code)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
"""

# ---------------------------------------------------------------------------
# Signal Data
#
# Each tuple: (cpt_code, cpt_description, suspect_icd10, suspect_hcc,
#               confidence_base, notes)
#
# CPT codes include standard numeric codes as well as HCPCS Level II codes
# (alpha-numeric) for DME, drugs, and services.
#
# HCC numbers follow the CMS-HCC V24/V28 model.
# Confidence reflects specificity of the procedure for the indicated condition.
# ---------------------------------------------------------------------------

SIGNALS: list[tuple[str, str, str, int, float, str]] = [

    # =========================================================================
    # DIABETES MANAGEMENT
    # =========================================================================

    ('83036', 'Hemoglobin A1c (HbA1c) test',
     'E11.9', 19, 0.5500, 'HbA1c test ordered suggests diabetes monitoring'),
    ('82947', 'Glucose; quantitative, blood',
     'E11.9', 19, 0.4500, 'Glucose test — screening or monitoring for diabetes'),
    ('82950', 'Glucose; post glucose dose (tolerance test)',
     'E11.9', 19, 0.5000, 'Glucose tolerance test suggests diabetes workup'),
    ('36415', 'Collection of venous blood by venipuncture (with HbA1c context)',
     'E11.9', 19, 0.5000, 'Blood draw in context of A1c testing suggests DM monitoring'),
    ('99490', 'Chronic care management services, 20+ minutes',
     'E11.9', 19, 0.4000, 'Chronic care management — screen for chronic conditions including DM'),
    ('S9140', 'Diabetic management program, day/visit',
     'E11.9', 19, 0.8000, 'Diabetic management program strongly implies diabetes'),
    ('S9141', 'Diabetic management program, follow-up visit',
     'E11.9', 19, 0.8000, 'Diabetic management follow-up strongly implies diabetes'),

    # =========================================================================
    # CARDIAC
    # =========================================================================

    # --- Echocardiogram / Heart Failure ---
    ('93306', 'Echocardiography, transthoracic, complete',
     'I50.9', 85, 0.6000, 'Echocardiogram commonly ordered for CHF evaluation'),
    ('93307', 'Echocardiography, transthoracic, limited',
     'I50.9', 85, 0.5500, 'Limited echo for CHF monitoring'),
    ('93308', 'Echocardiography, follow-up or limited',
     'I50.9', 85, 0.5500, 'Follow-up echo for CHF'),
    ('93312', 'Echocardiography, transesophageal (TEE), real-time',
     'I50.9', 85, 0.6000, 'TEE for structural heart disease/CHF workup'),
    ('93320', 'Doppler echocardiography, complete',
     'I50.9', 85, 0.5500, 'Doppler echo for hemodynamic assessment in CHF'),

    # --- ECG / Arrhythmia ---
    ('93000', 'Electrocardiogram (ECG/EKG), routine, 12-lead',
     'I48.91', 96, 0.3500, 'ECG commonly ordered — low specificity but screens for AFib'),
    ('93040', 'Rhythm ECG, 1-3 leads, tracing only',
     'I48.91', 96, 0.3500, 'Rhythm strip for arrhythmia detection'),
    ('93224', 'ECG monitoring, 24-hour (Holter), recording',
     'I48.91', 96, 0.5000, 'Holter monitor for arrhythmia detection (AFib)'),
    ('93225', 'ECG monitoring, 24-hour (Holter), scanning analysis',
     'I48.91', 96, 0.5000, 'Holter analysis for arrhythmia detection'),
    ('93226', 'ECG monitoring, 24-hour (Holter), review and interpretation',
     'I48.91', 96, 0.5000, 'Holter interpretation for arrhythmia'),
    ('93241', 'External ECG monitoring, up to 7 days',
     'I48.91', 96, 0.5500, 'Extended cardiac monitoring for paroxysmal AFib'),
    ('93243', 'External ECG monitoring, 7-15 days',
     'I48.91', 96, 0.5500, 'Extended monitoring for paroxysmal AFib'),
    ('93245', 'External ECG monitoring, > 15 days',
     'I48.91', 96, 0.6000, 'Long-term monitoring — high suspicion for AFib'),

    # --- Stress Testing / CAD ---
    ('93350', 'Echocardiography, stress (exercise/pharmacologic)',
     'I25.10', 86, 0.5500, 'Stress echo for coronary artery disease evaluation'),
    ('93015', 'Cardiovascular stress test, exercise, complete',
     'I25.10', 86, 0.5000, 'Exercise stress test for CAD evaluation'),
    ('93016', 'Cardiovascular stress test, supervision only',
     'I25.10', 86, 0.5000, 'Stress test supervision for CAD'),
    ('93017', 'Cardiovascular stress test, tracing only',
     'I25.10', 86, 0.5000, 'Stress test tracing for CAD'),
    ('93018', 'Cardiovascular stress test, interpretation only',
     'I25.10', 86, 0.5000, 'Stress test interpretation for CAD'),
    ('78451', 'Myocardial perfusion imaging (MPI), single study',
     'I25.10', 86, 0.6000, 'Nuclear stress test strongly suggests CAD workup'),
    ('78452', 'Myocardial perfusion imaging (MPI), multiple studies',
     'I25.10', 86, 0.6500, 'Multiple MPI studies for CAD evaluation'),

    # --- Cardiac Catheterization ---
    ('93458', 'Catheter placement, left heart, retrograde, with angiography',
     'I25.10', 86, 0.7500, 'Left heart cath with angiography — strong CAD signal'),
    ('93459', 'Catheter placement, left heart and coronary angiography',
     'I25.10', 86, 0.7500, 'Combined left heart cath and coronary angio for CAD'),
    ('93460', 'Catheter placement, right and left heart, with angiography',
     'I25.10', 86, 0.7500, 'Right and left heart cath — complex CAD/CHF workup'),
    ('93461', 'Catheter placement, combined right/left heart with angiography',
     'I25.10', 86, 0.7500, 'Combined cath with coronary angiography for CAD'),

    # --- CABG ---
    ('33533', 'Coronary artery bypass, single arterial graft',
     'I25.10', 86, 0.9000, 'CABG surgery — definitive CAD treatment'),
    ('33534', 'Coronary artery bypass, two arterial grafts',
     'I25.10', 86, 0.9000, 'CABG x2 — definitive for severe CAD'),
    ('33535', 'Coronary artery bypass, three arterial grafts',
     'I25.10', 86, 0.9000, 'CABG x3 — definitive for multivessel CAD'),
    ('33536', 'Coronary artery bypass, four or more arterial grafts',
     'I25.10', 86, 0.9000, 'CABG x4+ — definitive for severe multivessel CAD'),

    # --- PCI / Stent ---
    ('92920', 'Percutaneous transluminal coronary angioplasty, single vessel',
     'I25.10', 86, 0.8500, 'PCI/angioplasty — definitive CAD intervention'),
    ('92921', 'PCI, each additional branch of a major coronary artery',
     'I25.10', 86, 0.8500, 'Additional PCI vessel — multivessel CAD'),
    ('92924', 'PCI with atherectomy, single vessel',
     'I25.10', 86, 0.8500, 'PCI with atherectomy for CAD'),
    ('92928', 'PCI with stent placement, single vessel',
     'I25.10', 86, 0.8500, 'Coronary stent placement — definitive CAD'),
    ('92929', 'PCI with stent, each additional branch',
     'I25.10', 86, 0.8500, 'Additional stent — multivessel CAD'),
    ('92933', 'PCI with stent and atherectomy, single vessel',
     'I25.10', 86, 0.8500, 'Complex PCI for CAD'),
    ('92937', 'PCI with stent in bypass graft',
     'I25.10', 86, 0.8500, 'Stent in bypass graft — recurrent CAD'),
    ('92941', 'PCI with stent during acute MI',
     'I25.10', 86, 0.9000, 'Emergency PCI during acute MI — definitive CAD'),

    # --- Pacemaker ---
    ('33207', 'Insertion of permanent pacemaker, ventricular',
     'I49.9', 96, 0.8000, 'Pacemaker insertion for cardiac arrhythmia/conduction disorder'),
    ('33208', 'Insertion of permanent pacemaker, atrial and ventricular',
     'I49.9', 96, 0.8000, 'Dual-chamber pacemaker for arrhythmia'),
    ('33210', 'Insertion of temporary transvenous pacemaker',
     'I49.9', 96, 0.7500, 'Temporary pacemaker for acute arrhythmia'),
    ('33212', 'Insertion of pacemaker pulse generator only, single chamber',
     'I49.9', 96, 0.8000, 'Pacemaker generator replacement'),
    ('33213', 'Insertion of pacemaker pulse generator only, dual chamber',
     'I49.9', 96, 0.8000, 'Dual-chamber pacemaker generator replacement'),
    ('33214', 'Upgrade of pacemaker to dual chamber',
     'I49.9', 96, 0.8000, 'Pacemaker upgrade — progressive conduction disease'),

    # --- ICD (Implantable Cardioverter-Defibrillator) ---
    ('33249', 'Insertion/replacement of ICD, single or dual chamber',
     'I49.9', 96, 0.8500, 'ICD insertion for life-threatening arrhythmia or cardiomyopathy'),
    ('33230', 'Insertion of ICD pulse generator, dual lead',
     'I49.9', 96, 0.8500, 'ICD generator for arrhythmia management'),
    ('33231', 'Insertion of ICD pulse generator, multiple leads',
     'I49.9', 96, 0.8500, 'Multi-lead ICD for arrhythmia'),
    ('33240', 'Insertion of ICD pulse generator only (replacement)',
     'I49.9', 96, 0.8500, 'ICD generator replacement — chronic arrhythmia'),
    ('33262', 'Removal and replacement of ICD pulse generator, single lead',
     'I49.9', 96, 0.8500, 'ICD replacement — ongoing arrhythmia management'),
    ('33263', 'Removal and replacement of ICD pulse generator, dual lead',
     'I49.9', 96, 0.8500, 'Dual ICD replacement'),
    ('33264', 'Removal and replacement of ICD pulse generator, multiple leads',
     'I49.9', 96, 0.8500, 'Multi-lead ICD replacement'),

    # --- Device Checks ---
    ('93280', 'Programming device evaluation, single/dual/multi-lead pacemaker',
     'I49.9', 96, 0.5500, 'Pacemaker device check — ongoing arrhythmia management'),
    ('93281', 'Programming device evaluation, single/dual/multi-lead ICD',
     'I49.9', 96, 0.5500, 'ICD device check — ongoing arrhythmia management'),
    ('93282', 'Programming device evaluation, single lead pacemaker',
     'I49.9', 96, 0.5500, 'Single lead pacemaker check'),
    ('93283', 'Programming device evaluation, dual lead pacemaker',
     'I49.9', 96, 0.5500, 'Dual lead pacemaker check'),
    ('93284', 'Programming device evaluation, multi lead pacemaker',
     'I49.9', 96, 0.5500, 'Multi lead device check'),
    ('93285', 'Programming device evaluation, ICD single lead',
     'I49.9', 96, 0.5500, 'ICD single lead check'),
    ('93286', 'Peri-procedural device evaluation, pacemaker',
     'I49.9', 96, 0.5000, 'Peri-procedural pacemaker eval'),
    ('93287', 'Peri-procedural device evaluation, ICD',
     'I49.9', 96, 0.5000, 'Peri-procedural ICD eval'),
    ('93288', 'Interrogation device evaluation, pacemaker in person',
     'I49.9', 96, 0.5500, 'In-person pacemaker interrogation'),
    ('93289', 'Interrogation device evaluation, ICD in person',
     'I49.9', 96, 0.5500, 'In-person ICD interrogation'),

    # --- Anticoagulant Management ---
    ('93793', 'Anticoagulant management, physician review and interpretation',
     'I48.91', 96, 0.7000, 'Anticoagulant management — strong signal for AFib'),

    # =========================================================================
    # RENAL
    # =========================================================================

    # --- Hemodialysis ---
    ('90935', 'Hemodialysis procedure with single evaluation',
     'N18.5', 136, 0.9500, 'Hemodialysis — definitive ESRD'),
    ('90937', 'Hemodialysis procedure with repeated evaluation',
     'N18.5', 136, 0.9500, 'Hemodialysis with multiple evaluations — ESRD'),
    ('90940', 'Hemodialysis access flow study',
     'N18.5', 136, 0.9000, 'Dialysis access study — ESRD patient'),

    # --- Peritoneal Dialysis ---
    ('90945', 'Dialysis procedure other than hemodialysis, single evaluation',
     'N18.5', 136, 0.9500, 'Peritoneal dialysis — definitive ESRD'),
    ('90947', 'Dialysis procedure other than hemodialysis, repeated evaluation',
     'N18.5', 136, 0.9500, 'Peritoneal dialysis with repeated evals — ESRD'),

    # --- ESRD Monthly Services ---
    ('90960', 'ESRD related services, per month, 4+ face-to-face visits',
     'N18.5', 136, 0.9500, 'Monthly ESRD services — definitive ESRD'),
    ('90961', 'ESRD related services, per month, 2-3 face-to-face visits',
     'N18.5', 136, 0.9500, 'Monthly ESRD services — definitive ESRD'),
    ('90962', 'ESRD related services, per month, 1 face-to-face visit',
     'N18.5', 136, 0.9500, 'Monthly ESRD services — definitive ESRD'),
    ('90963', 'ESRD related services, home dialysis, per month, < 2 yrs',
     'N18.5', 136, 0.9500, 'Home dialysis ESRD monthly services'),
    ('90964', 'ESRD related services, home dialysis, per month, 2-11 yrs',
     'N18.5', 136, 0.9500, 'Home dialysis ESRD monthly services'),
    ('90965', 'ESRD related services, home dialysis, per month, 12-19 yrs',
     'N18.5', 136, 0.9500, 'Home dialysis ESRD monthly services'),
    ('90966', 'ESRD related services, home dialysis, per month, 20+ yrs',
     'N18.5', 136, 0.9500, 'Home dialysis ESRD monthly services'),

    # --- Kidney Transplant ---
    ('50360', 'Renal allotransplantation, implantation of graft',
     'Z94.0', 186, 0.9500, 'Kidney transplant — definitive transplant status'),
    ('50365', 'Renal allotransplantation, from cadaver donor',
     'Z94.0', 186, 0.9500, 'Cadaveric kidney transplant'),

    # --- AV Fistula / Graft Creation ---
    ('36800', 'Insertion of cannula for hemodialysis',
     'N18.5', 136, 0.9000, 'Dialysis cannula insertion — ESRD preparation'),
    ('36810', 'Arteriovenous anastomosis, open; by upper arm cephalic vein',
     'N18.5', 136, 0.9000, 'AV fistula creation — ESRD access'),
    ('36815', 'Arteriovenous anastomosis, open; by upper arm basilic vein',
     'N18.5', 136, 0.9000, 'AV fistula creation — ESRD access'),
    ('36818', 'Arteriovenous anastomosis, autogenous graft',
     'N18.5', 136, 0.9000, 'AV graft creation — ESRD access'),
    ('36819', 'Arteriovenous anastomosis, autogenous graft, upper arm',
     'N18.5', 136, 0.9000, 'Upper arm AV graft — ESRD access'),
    ('36820', 'Arteriovenous anastomosis, by forearm vein',
     'N18.5', 136, 0.9000, 'Forearm AV fistula — ESRD access'),
    ('36821', 'Arteriovenous anastomosis, direct, any site',
     'N18.5', 136, 0.9000, 'AV fistula creation — ESRD access'),
    ('36825', 'Arteriovenous anastomosis with synthetic graft',
     'N18.5', 136, 0.9000, 'Synthetic AV graft — ESRD access'),
    ('36830', 'Arteriovenous anastomosis with nonautogenous graft',
     'N18.5', 136, 0.9000, 'Non-autogenous AV graft — ESRD access'),
    ('36831', 'Thrombectomy of AV fistula/graft',
     'N18.5', 136, 0.9000, 'AV access thrombectomy — ESRD maintenance'),
    ('36832', 'Revision of AV fistula',
     'N18.5', 136, 0.9000, 'AV fistula revision — ESRD maintenance'),
    ('36833', 'Revision of AV fistula with thrombectomy',
     'N18.5', 136, 0.9000, 'AV fistula revision/thrombectomy — ESRD'),

    # --- Renal Function Testing ---
    ('82565', 'Creatinine; blood',
     'N18.3', 138, 0.3500, 'Creatinine blood test — screening for CKD'),
    ('82575', 'Creatinine; clearance',
     'N18.3', 138, 0.4500, 'Creatinine clearance — CKD staging assessment'),
    ('82570', 'Creatinine; other source (urine)',
     'N18.3', 138, 0.3500, 'Urine creatinine — CKD assessment'),

    # =========================================================================
    # PULMONARY
    # =========================================================================

    # --- Spirometry / PFTs ---
    ('94010', 'Spirometry, including vital capacity and flow measurements',
     'J44.1', 111, 0.5500, 'Spirometry for COPD/obstructive disease evaluation'),
    ('94060', 'Bronchodilator responsiveness, spirometry pre and post',
     'J44.1', 111, 0.5500, 'Bronchodilator response testing for COPD/asthma'),
    ('94070', 'Bronchospasm provocation evaluation',
     'J44.1', 111, 0.5000, 'Bronchoprovocation for reactive airway disease'),
    ('94375', 'Respiratory flow volume loop',
     'J44.1', 111, 0.5000, 'Flow volume loop for obstructive disease'),

    # --- Lung Volumes / Diffusion ---
    ('94726', 'Plethysmography for lung volumes',
     'J44.1', 111, 0.5500, 'Lung volume measurement for COPD/restrictive disease'),
    ('94727', 'Gas dilution or washout for lung volumes',
     'J44.1', 111, 0.5500, 'Lung volume by gas dilution for COPD'),
    ('94728', 'Airway resistance by oscillometry',
     'J44.1', 111, 0.5500, 'Airway resistance measurement for obstructive disease'),
    ('94729', 'Diffusing capacity (DLCO)',
     'J44.1', 111, 0.5500, 'DLCO for COPD/ILD evaluation'),

    # --- Ventilator Management ---
    ('94002', 'Ventilation assist and management, initial day, hospital inpatient',
     'J96.11', 84, 0.8000, 'Ventilator management — chronic respiratory failure'),
    ('94003', 'Ventilation assist and management, subsequent day, hospital inpatient',
     'J96.11', 84, 0.8000, 'Ongoing ventilator management — respiratory failure'),
    ('94004', 'Ventilation assist and management, nursing facility',
     'J96.11', 84, 0.8000, 'Ventilator in nursing facility — chronic resp failure'),
    ('94005', 'Home ventilator management',
     'J96.11', 84, 0.8500, 'Home ventilator — chronic respiratory failure'),

    # --- Bronchoscopy ---
    ('31622', 'Bronchoscopy, rigid or flexible; diagnostic',
     'J44.1', 111, 0.5000, 'Diagnostic bronchoscopy — screen for lung disease'),
    ('31623', 'Bronchoscopy with brushing or lavage',
     'J44.1', 111, 0.5000, 'Bronchoscopy with lavage for lung disease workup'),
    ('31624', 'Bronchoscopy with bronchial alveolar lavage',
     'J44.1', 111, 0.5000, 'BAL for lung disease evaluation'),
    ('31625', 'Bronchoscopy with biopsy',
     'J44.1', 111, 0.5500, 'Bronchoscopy with biopsy — lung pathology workup'),
    ('31628', 'Bronchoscopy with transbronchial biopsy',
     'J44.1', 111, 0.5500, 'Transbronchial biopsy for lung disease'),

    # --- Home Oxygen / Ventilator Supplies ---
    ('E0424', 'Stationary compressed gaseous oxygen system, rental',
     'J96.11', 84, 0.7500, 'Home oxygen — chronic respiratory failure'),
    ('E0431', 'Portable gaseous oxygen system, rental',
     'J96.11', 84, 0.7500, 'Portable oxygen — chronic respiratory failure'),
    ('E0433', 'Portable liquid oxygen system, rental',
     'J96.11', 84, 0.7500, 'Portable liquid oxygen — chronic resp failure'),
    ('E0434', 'Portable liquid oxygen system, contents',
     'J96.11', 84, 0.7500, 'Portable liquid oxygen contents — resp failure'),
    ('E0439', 'Stationary liquid oxygen system, rental',
     'J96.11', 84, 0.7500, 'Stationary liquid oxygen — chronic resp failure'),
    ('E0441', 'Oxygen contents, gaseous, stationary',
     'J96.11', 84, 0.7500, 'Oxygen contents for stationary system'),
    ('E0442', 'Oxygen contents, gaseous, portable',
     'J96.11', 84, 0.7500, 'Oxygen contents for portable system'),
    ('E0443', 'Portable oxygen contents, liquid',
     'J96.11', 84, 0.7500, 'Portable liquid oxygen contents'),
    ('E1390', 'Oxygen concentrator, single delivery port',
     'J96.11', 84, 0.7500, 'Oxygen concentrator — chronic resp failure'),
    ('E1391', 'Oxygen concentrator, dual delivery port',
     'J96.11', 84, 0.7500, 'Dual-port oxygen concentrator — resp failure'),
    ('99504', 'Home visit for mechanical ventilation care',
     'J96.11', 84, 0.8500, 'Home visit for ventilator — chronic respiratory failure'),

    # =========================================================================
    # ONCOLOGY
    # =========================================================================

    # --- Chemotherapy Administration ---
    ('96401', 'Chemotherapy admin, subcutaneous/intramuscular; non-hormonal',
     'C80.1', 12, 0.9000, 'Chemo admin SC/IM — active cancer treatment'),
    ('96402', 'Chemotherapy admin, subcutaneous/intramuscular; hormonal',
     'C80.1', 12, 0.8500, 'Hormonal chemo admin — cancer treatment'),
    ('96405', 'Chemotherapy admin; intralesional, up to 7 lesions',
     'C80.1', 12, 0.9000, 'Intralesional chemo — cancer treatment'),
    ('96406', 'Chemotherapy admin; intralesional, more than 7 lesions',
     'C80.1', 12, 0.9000, 'Intralesional chemo, multiple lesions — cancer'),
    ('96409', 'Chemotherapy admin; IV push, single drug',
     'C80.1', 12, 0.9000, 'IV push chemo — active cancer treatment'),
    ('96411', 'Chemotherapy admin; IV push, additional drug',
     'C80.1', 12, 0.9000, 'Additional IV push chemo — multi-drug cancer regimen'),
    ('96413', 'Chemotherapy admin; infusion, up to 1 hour, single drug',
     'C80.1', 12, 0.9000, 'Chemo infusion — active cancer treatment'),
    ('96415', 'Chemotherapy admin; infusion, each additional hour',
     'C80.1', 12, 0.9000, 'Extended chemo infusion — cancer treatment'),
    ('96416', 'Chemotherapy admin; infusion, initiation of prolonged (>8 hrs)',
     'C80.1', 12, 0.9000, 'Prolonged chemo infusion — intensive cancer treatment'),
    ('96417', 'Chemotherapy admin; infusion, each additional sequential drug',
     'C80.1', 12, 0.9000, 'Multi-drug chemo infusion — cancer treatment'),

    # --- Radiation Therapy ---
    ('77385', 'Intensity modulated radiation treatment (IMRT), simple',
     'C80.1', 12, 0.8500, 'IMRT radiation therapy — cancer treatment'),
    ('77386', 'Intensity modulated radiation treatment (IMRT), complex',
     'C80.1', 12, 0.8500, 'Complex IMRT — advanced cancer treatment'),
    ('77387', 'Radiation treatment guidance, image-guided',
     'C80.1', 12, 0.8500, 'Image-guided radiation therapy — cancer'),
    ('77401', 'Radiation treatment delivery, superficial',
     'C80.1', 12, 0.8500, 'Superficial radiation — cancer treatment'),
    ('77402', 'Radiation treatment delivery, simple',
     'C80.1', 12, 0.8500, 'Simple radiation delivery — cancer treatment'),
    ('77407', 'Radiation treatment delivery, intermediate',
     'C80.1', 12, 0.8500, 'Intermediate radiation — cancer treatment'),
    ('77412', 'Radiation treatment delivery, complex',
     'C80.1', 12, 0.8500, 'Complex radiation delivery — advanced cancer'),
    ('77427', 'Radiation treatment management, 5 treatments',
     'C80.1', 12, 0.8500, 'Radiation treatment management — cancer'),

    # --- Bone Marrow Transplant ---
    ('38240', 'Hematopoietic progenitor cell (HPC); allogeneic transplantation',
     'C80.1', 8, 0.9000, 'Allogeneic bone marrow transplant — cancer/blood disorder'),
    ('38241', 'Hematopoietic progenitor cell (HPC); autologous transplantation',
     'C80.1', 8, 0.9000, 'Autologous bone marrow transplant — cancer/blood disorder'),
    ('38242', 'Allogeneic donor lymphocyte infusion',
     'C80.1', 8, 0.9000, 'Donor lymphocyte infusion — cancer treatment'),

    # --- Pathology / Biopsy ---
    ('88305', 'Surgical pathology, level IV',
     'C80.1', 12, 0.4000, 'Surgical pathology — screen for malignancy'),
    ('88307', 'Surgical pathology, level V',
     'C80.1', 12, 0.4500, 'Complex surgical pathology — malignancy screen'),
    ('88309', 'Surgical pathology, level VI',
     'C80.1', 12, 0.5000, 'High-complexity pathology — strong cancer signal'),
    ('88312', 'Special stains, group I, for microorganisms/enzymes',
     'C80.1', 12, 0.3500, 'Special pathology stains — cancer workup'),
    ('88313', 'Special stains, group II, all other',
     'C80.1', 12, 0.3500, 'Special stains for tumor characterization'),
    ('88342', 'Immunohistochemistry, per specimen, first stain',
     'C80.1', 12, 0.5000, 'IHC staining — cancer diagnosis/staging'),
    ('88341', 'Immunohistochemistry, each additional stain',
     'C80.1', 12, 0.5000, 'Additional IHC — cancer characterization'),

    # =========================================================================
    # MENTAL HEALTH
    # =========================================================================

    # --- Psychotherapy ---
    ('90832', 'Psychotherapy, 30 minutes',
     'F33.0', 155, 0.4000, 'Psychotherapy 30 min — screen for depression/mental health'),
    ('90834', 'Psychotherapy, 45 minutes',
     'F33.0', 155, 0.4000, 'Psychotherapy 45 min — screen for depression/mental health'),
    ('90837', 'Psychotherapy, 60 minutes',
     'F33.0', 155, 0.4000, 'Psychotherapy 60 min — screen for depression/mental health'),
    ('90838', 'Psychotherapy, 75 minutes',
     'F33.0', 155, 0.4000, 'Extended psychotherapy — mental health condition'),
    ('90839', 'Psychotherapy for crisis; first 60 minutes',
     'F33.0', 155, 0.5000, 'Crisis psychotherapy — acute mental health'),
    ('90840', 'Psychotherapy for crisis; additional 30 minutes',
     'F33.0', 155, 0.5000, 'Extended crisis therapy — severe mental health'),

    # --- Group Therapy ---
    ('90853', 'Group psychotherapy (other than family)',
     'F33.0', 155, 0.3500, 'Group therapy — substance use or psychiatric condition'),

    # --- Health Behavior Assessment ---
    ('96156', 'Health behavior assessment, first 30 minutes',
     'F33.0', 155, 0.3500, 'Health behavior assessment — mental health screen'),
    ('96158', 'Health behavior intervention, first 30 minutes',
     'F33.0', 155, 0.3500, 'Health behavior intervention — mental health'),
    ('96159', 'Health behavior intervention, each additional 15 minutes',
     'F33.0', 155, 0.3500, 'Additional health behavior intervention'),

    # --- Substance Use Disorder ---
    ('H0020', 'Methadone administration and/or service',
     'F11.20', 55, 0.9000, 'Methadone administration — opioid use disorder'),
    ('H0033', 'Oral medication administration, direct observation for SUD',
     'F11.20', 55, 0.8000, 'Observed medication admin for substance use disorder'),
    ('H0015', 'Alcohol and/or drug services; intensive outpatient',
     'F10.20', 55, 0.8000, 'Intensive outpatient SUD treatment'),
    ('H0014', 'Alcohol and/or drug services; ambulatory detoxification',
     'F10.20', 55, 0.8500, 'Ambulatory detox — substance use disorder'),
    ('H0016', 'Alcohol and/or drug services; medical/somatic',
     'F10.20', 55, 0.8000, 'Medical SUD services'),

    # --- Psychiatric Evaluation ---
    ('90791', 'Psychiatric diagnostic evaluation',
     'F33.0', 155, 0.4500, 'Psychiatric evaluation — mental health diagnosis'),
    ('90792', 'Psychiatric diagnostic evaluation with medical services',
     'F33.0', 155, 0.4500, 'Psychiatric eval with medical — complex mental health'),

    # =========================================================================
    # NEUROLOGY
    # =========================================================================

    # --- EEG / Epilepsy ---
    ('95816', 'EEG, awake and asleep',
     'G40.909', 79, 0.5500, 'EEG awake/asleep — epilepsy evaluation'),
    ('95817', 'EEG, awake and asleep with stimulation',
     'G40.909', 79, 0.5500, 'EEG with stimulation for seizure evaluation'),
    ('95818', 'EEG, awake and drowsy',
     'G40.909', 79, 0.5500, 'EEG awake/drowsy — seizure evaluation'),
    ('95819', 'EEG, awake and asleep with stimulation (extended)',
     'G40.909', 79, 0.5500, 'Extended EEG for epilepsy'),
    ('95812', 'EEG extended monitoring, 41-60 minutes',
     'G40.909', 79, 0.6000, 'Extended EEG monitoring for epilepsy'),
    ('95813', 'EEG extended monitoring, >1 hour',
     'G40.909', 79, 0.6000, 'Extended EEG >1 hr for epilepsy'),

    # --- Video EEG Monitoring ---
    ('95711', 'Video EEG monitoring, 2-12 hours unmonitored',
     'G40.909', 79, 0.7000, 'Video EEG monitoring — epilepsy workup'),
    ('95712', 'Video EEG monitoring, 2-12 hours with monitoring',
     'G40.909', 79, 0.7000, 'Monitored video EEG — epilepsy diagnosis'),
    ('95713', 'Video EEG monitoring, 2-12 hours each increment',
     'G40.909', 79, 0.7000, 'Extended video EEG — epilepsy'),
    ('95714', 'Video EEG monitoring, 12-26 hours unmonitored',
     'G40.909', 79, 0.7500, 'Overnight video EEG — epilepsy'),
    ('95715', 'Video EEG monitoring, 12-26 hours with monitoring',
     'G40.909', 79, 0.7500, 'Overnight monitored video EEG — epilepsy'),
    ('95716', 'Video EEG monitoring, 12-26 hours each increment',
     'G40.909', 79, 0.7500, 'Extended overnight video EEG'),
    ('95717', 'Electroencephalogram (EEG) continuous monitoring setup',
     'G40.909', 79, 0.6500, 'EEG continuous monitoring setup for epilepsy'),
    ('95718', 'EEG continuous monitoring, maintenance',
     'G40.909', 79, 0.6500, 'EEG continuous monitoring — epilepsy'),
    ('95720', 'EEG continuous monitoring, 24 hours or more',
     'G40.909', 79, 0.7500, 'Continuous EEG 24+ hrs — refractory epilepsy workup'),

    # --- Brain MRI ---
    ('70551', 'MRI brain without contrast',
     'G40.909', 79, 0.3000, 'Brain MRI — screen for neurological conditions'),
    ('70552', 'MRI brain with contrast',
     'G40.909', 79, 0.3000, 'Brain MRI with contrast — neuro evaluation'),
    ('70553', 'MRI brain without and with contrast',
     'G40.909', 79, 0.3000, 'Brain MRI pre/post contrast — neuro workup'),

    # --- EMG / Nerve Conduction Studies ---
    ('95860', 'EMG, 1 extremity, limited study',
     'G62.9', 75, 0.5000, 'EMG limited — neuropathy evaluation'),
    ('95861', 'EMG, 2 extremities, limited study',
     'G62.9', 75, 0.5000, 'EMG 2 extremities — neuropathy'),
    ('95863', 'EMG, 2 extremities with paraspinals',
     'G62.9', 75, 0.5000, 'EMG with paraspinals — neuropathy/radiculopathy'),
    ('95864', 'EMG, 3 extremities with paraspinals',
     'G62.9', 75, 0.5500, 'EMG 3 extremities — extensive neuropathy workup'),
    ('95865', 'EMG, larynx',
     'G62.9', 75, 0.4500, 'Laryngeal EMG for neuromuscular evaluation'),
    ('95866', 'EMG, hemidiaphragm',
     'G62.9', 75, 0.5000, 'Diaphragm EMG — neuromuscular disease'),
    ('95867', 'EMG, cranial nerve supplied muscle, unilateral',
     'G62.9', 75, 0.5000, 'Cranial nerve EMG — neuromuscular evaluation'),
    ('95868', 'EMG, cranial nerve supplied muscles, bilateral',
     'G62.9', 75, 0.5000, 'Bilateral cranial nerve EMG'),
    ('95869', 'EMG, thoracic paraspinal muscles',
     'G62.9', 75, 0.5000, 'Thoracic EMG — neuropathy/radiculopathy'),
    ('95870', 'EMG, non-extremity (cranial/thoracic) limited',
     'G62.9', 75, 0.5000, 'Non-extremity EMG — neuromuscular disease'),
    ('95907', 'Nerve conduction studies, 1-2 studies',
     'G62.9', 75, 0.5000, 'NCS 1-2 studies — neuropathy screen'),
    ('95908', 'Nerve conduction studies, 3-4 studies',
     'G62.9', 75, 0.5000, 'NCS 3-4 studies — neuropathy evaluation'),
    ('95909', 'Nerve conduction studies, 5-6 studies',
     'G62.9', 75, 0.5500, 'NCS 5-6 studies — extensive neuropathy workup'),
    ('95910', 'Nerve conduction studies, 7-8 studies',
     'G62.9', 75, 0.5500, 'NCS 7-8 studies — complex neuropathy'),
    ('95911', 'Nerve conduction studies, 9-10 studies',
     'G62.9', 75, 0.5500, 'NCS 9-10 studies — comprehensive neuropathy'),
    ('95912', 'Nerve conduction studies, 11-12 studies',
     'G62.9', 75, 0.5500, 'NCS 11-12 studies — severe neuropathy workup'),
    ('95913', 'Nerve conduction studies, 13+ studies',
     'G62.9', 75, 0.6000, 'NCS 13+ studies — complex neuromuscular disease'),

    # =========================================================================
    # RHEUMATOLOGY
    # =========================================================================

    ('86200', 'Cyclic citrullinated peptide (CCP) antibody',
     'M05.9', 40, 0.5500, 'Anti-CCP antibody test — RA evaluation'),
    ('86235', 'Nuclear antigen antibody (ENA)',
     'M05.9', 40, 0.5000, 'ENA antibody panel — autoimmune disease workup'),
    ('86431', 'Rheumatoid factor, quantitative',
     'M05.9', 40, 0.4500, 'Rheumatoid factor test — RA screening'),
    ('86430', 'Rheumatoid factor, qualitative',
     'M05.9', 40, 0.4000, 'Qualitative RF — RA screening'),
    ('J0129', 'Injection, abatacept, 10 mg',
     'M05.9', 40, 0.8000, 'Abatacept injection — RA biologic therapy'),
    ('J0135', 'Injection, adalimumab, 20 mg',
     'M05.9', 40, 0.8000, 'Adalimumab injection — RA/autoimmune biologic'),
    ('J1438', 'Injection, etanercept, 25 mg',
     'M05.9', 40, 0.8000, 'Etanercept injection — RA biologic therapy'),
    ('J1745', 'Injection, infliximab, 10 mg',
     'M05.9', 40, 0.8000, 'Infliximab injection — RA/IBD biologic'),
    ('J3262', 'Injection, tocilizumab, 1 mg',
     'M05.9', 40, 0.8000, 'Tocilizumab injection — RA IL-6 inhibitor'),
    ('J0717', 'Injection, certolizumab pegol, 1 mg',
     'M06.9', 40, 0.8000, 'Certolizumab injection — RA biologic'),
    ('J1602', 'Injection, golimumab, 1 mg',
     'M06.9', 40, 0.8000, 'Golimumab injection — RA biologic'),
    ('20610', 'Arthrocentesis/injection, major joint',
     'M06.9', 40, 0.4000, 'Major joint injection — RA or inflammatory arthritis'),
    ('20611', 'Arthrocentesis/injection, major joint with ultrasound',
     'M06.9', 40, 0.4000, 'US-guided joint injection — inflammatory arthritis'),

    # =========================================================================
    # TRANSPLANT
    # =========================================================================

    ('33945', 'Heart transplantation, with or without recipient cardiectomy',
     'Z94.1', 186, 0.9500, 'Heart transplant — definitive transplant status'),
    ('33935', 'Heart-lung transplantation with recipient cardiectomy-pneumonectomy',
     'Z94.1', 186, 0.9500, 'Heart-lung transplant'),
    ('32851', 'Lung transplant, single, without cardiopulmonary bypass',
     'Z94.2', 186, 0.9500, 'Single lung transplant without bypass'),
    ('32852', 'Lung transplant, single, with cardiopulmonary bypass',
     'Z94.2', 186, 0.9500, 'Single lung transplant with bypass'),
    ('32853', 'Lung transplant, double, without cardiopulmonary bypass',
     'Z94.2', 186, 0.9500, 'Double lung transplant without bypass'),
    ('32854', 'Lung transplant, double, with cardiopulmonary bypass',
     'Z94.2', 186, 0.9500, 'Double lung transplant with bypass'),
    ('47135', 'Liver allotransplantation; orthotopic, partial or whole',
     'Z94.4', 186, 0.9500, 'Liver transplant — definitive transplant status'),
    ('47136', 'Liver allotransplantation; heterotopic',
     'Z94.4', 186, 0.9500, 'Heterotopic liver transplant'),
    ('48554', 'Pancreas transplantation',
     'Z94.83', 186, 0.9500, 'Pancreas transplant'),
    ('44135', 'Intestinal allotransplantation from cadaver donor',
     'Z94.82', 186, 0.9500, 'Intestinal transplant from cadaver'),
    ('44136', 'Intestinal allotransplantation from living donor',
     'Z94.82', 186, 0.9500, 'Intestinal transplant from living donor'),

    # =========================================================================
    # VASCULAR
    # =========================================================================

    # --- Endarterectomy ---
    ('35301', 'Thromboendarterectomy, carotid, by neck incision',
     'I70.0', 107, 0.8500, 'Carotid endarterectomy — atherosclerotic vascular disease'),
    ('35302', 'Thromboendarterectomy, superficial femoral artery',
     'I70.0', 107, 0.8500, 'Femoral endarterectomy — PVD/atherosclerosis'),
    ('35303', 'Thromboendarterectomy, popliteal artery',
     'I70.0', 107, 0.8500, 'Popliteal endarterectomy — PVD'),
    ('35304', 'Thromboendarterectomy, tibioperoneal trunk artery',
     'I70.0', 107, 0.8500, 'Tibioperoneal endarterectomy — severe PVD'),
    ('35305', 'Thromboendarterectomy, tibial or peroneal artery',
     'I70.0', 107, 0.8500, 'Tibial/peroneal endarterectomy — severe PVD'),
    ('35321', 'Thromboendarterectomy, axillary-brachial',
     'I70.0', 107, 0.8500, 'Upper extremity endarterectomy — atherosclerosis'),
    ('35331', 'Thromboendarterectomy, abdominal aorta',
     'I70.0', 107, 0.8500, 'Aortic endarterectomy — severe atherosclerosis'),
    ('35341', 'Thromboendarterectomy, mesenteric/celiac/renal',
     'I70.0', 107, 0.8500, 'Visceral endarterectomy — atherosclerosis'),
    ('35351', 'Thromboendarterectomy, iliac',
     'I70.0', 107, 0.8500, 'Iliac endarterectomy — atherosclerosis'),
    ('35355', 'Thromboendarterectomy, iliofemoral',
     'I70.0', 107, 0.8500, 'Iliofemoral endarterectomy — atherosclerosis'),
    ('35361', 'Thromboendarterectomy, combined aortoiliac',
     'I70.0', 107, 0.8500, 'Aortoiliac endarterectomy — severe atherosclerosis'),
    ('35363', 'Thromboendarterectomy, combined aortoiliofemoral',
     'I70.0', 107, 0.8500, 'Aortoiliofemoral endarterectomy'),
    ('35371', 'Thromboendarterectomy, common femoral',
     'I70.0', 107, 0.8500, 'Common femoral endarterectomy — PVD'),
    ('35372', 'Thromboendarterectomy, deep (profunda) femoral',
     'I70.0', 107, 0.8500, 'Profunda femoral endarterectomy — PVD'),
    ('35381', 'Thromboendarterectomy, femoral and/or popliteal',
     'I70.0', 107, 0.8500, 'Femoropopliteal endarterectomy — PVD'),
    ('35390', 'Reoperation, carotid endarterectomy',
     'I70.0', 107, 0.8500, 'Redo carotid endarterectomy — recurrent atherosclerosis'),

    # --- Bypass Graft ---
    ('35501', 'Bypass graft, common carotid-internal carotid',
     'I70.0', 107, 0.8500, 'Carotid bypass — severe atherosclerosis'),
    ('35506', 'Bypass graft, carotid-vertebral',
     'I70.0', 107, 0.8500, 'Carotid-vertebral bypass — atherosclerosis'),
    ('35508', 'Bypass graft, carotid-vertebral with vein',
     'I70.0', 107, 0.8500, 'Carotid-vertebral vein bypass'),
    ('35509', 'Bypass graft, carotid-contralateral carotid with vein',
     'I70.0', 107, 0.8500, 'Carotid-carotid vein bypass'),
    ('35511', 'Bypass graft, subclavian-subclavian',
     'I70.0', 107, 0.8500, 'Subclavian bypass — atherosclerosis'),
    ('35516', 'Bypass graft, subclavian-axillary',
     'I70.0', 107, 0.8500, 'Subclavian-axillary bypass'),
    ('35518', 'Bypass graft, axillary-axillary',
     'I70.0', 107, 0.8500, 'Axillary-axillary bypass'),
    ('35521', 'Bypass graft, axillary-femoral',
     'I70.0', 107, 0.8500, 'Axillary-femoral bypass — severe PVD'),
    ('35526', 'Bypass graft, aortosubclavian or carotid',
     'I70.0', 107, 0.8500, 'Aorto-subclavian/carotid bypass'),
    ('35531', 'Bypass graft, aorto-celiac/mesenteric',
     'I70.0', 107, 0.8500, 'Aorto-visceral bypass'),
    ('35533', 'Bypass graft, axillary-femoral-femoral',
     'I70.0', 107, 0.8500, 'Ax-fem-fem bypass — bilateral PVD'),
    ('35536', 'Bypass graft, splenorenal',
     'I70.0', 107, 0.8500, 'Splenorenal bypass'),
    ('35537', 'Bypass graft, aortobiliac',
     'I70.0', 107, 0.8500, 'Aortobiliac bypass — atherosclerosis'),
    ('35538', 'Bypass graft, aorto-bi-iliac',
     'I70.0', 107, 0.8500, 'Aorto-bi-iliac bypass'),
    ('35539', 'Bypass graft, aortofemoral',
     'I70.0', 107, 0.8500, 'Aortofemoral bypass — severe atherosclerosis'),
    ('35540', 'Bypass graft, aortobifemoral',
     'I70.0', 107, 0.8500, 'Aortobifemoral bypass — bilateral PVD'),
    ('35556', 'Bypass graft, femoral-popliteal',
     'I70.0', 107, 0.8500, 'Femoropopliteal bypass — PVD'),
    ('35558', 'Bypass graft, femoral-femoral',
     'I70.0', 107, 0.8500, 'Fem-fem bypass — PVD'),
    ('35560', 'Bypass graft, aortorenal',
     'I70.0', 107, 0.8500, 'Aortorenal bypass'),
    ('35563', 'Bypass graft, ilioiliac',
     'I70.0', 107, 0.8500, 'Ilioiliac bypass — atherosclerosis'),
    ('35565', 'Bypass graft, iliofemoral',
     'I70.0', 107, 0.8500, 'Iliofemoral bypass — PVD'),
    ('35566', 'Bypass graft, femoral-anterior tibial',
     'I70.0', 107, 0.8500, 'Fem-tibial bypass — severe PVD/CLI'),
    ('35571', 'Bypass graft, popliteal-tibial or peroneal',
     'I70.0', 107, 0.8500, 'Popliteal-tibial bypass — critical limb ischemia'),

    # --- Endovascular Revascularization ---
    ('37228', 'Revascularization, endovascular, iliac, initial vessel',
     'I70.0', 108, 0.8000, 'Endovascular iliac revascularization — PVD'),
    ('37229', 'Revascularization, endovascular, iliac, each additional vessel',
     'I70.0', 108, 0.8000, 'Additional iliac endovascular revasc'),
    ('37230', 'Revascularization, endovascular, tibial/peroneal, initial',
     'I70.0', 108, 0.8000, 'Endovascular tibial revascularization — CLI'),
    ('37231', 'Revascularization, endovascular, tibial/peroneal, additional',
     'I70.0', 108, 0.8000, 'Additional tibial endovascular revasc'),
    ('37232', 'Revascularization, endovascular, tibial/peroneal, transluminal stent',
     'I70.0', 108, 0.8000, 'Tibial stent placement — critical limb ischemia'),
    ('37233', 'Revascularization, endovascular, tibial/peroneal, atherectomy',
     'I70.0', 108, 0.8000, 'Tibial atherectomy — severe PVD'),
    ('37234', 'Revascularization, endovascular, tibial, stent and atherectomy',
     'I70.0', 108, 0.8000, 'Complex tibial endovascular revasc'),
    ('37235', 'Revascularization, endovascular, femoral/popliteal, initial',
     'I70.0', 108, 0.8000, 'Femoropopliteal endovascular revascularization'),
    ('37236', 'Open/percutaneous stent placement, initial artery',
     'I70.0', 108, 0.8000, 'Arterial stent placement — PVD'),
    ('37237', 'Open/percutaneous stent placement, each additional artery',
     'I70.0', 108, 0.8000, 'Additional arterial stent — PVD'),
    ('37238', 'Intravascular stent, open or percutaneous, initial vein',
     'I70.0', 108, 0.7000, 'Venous stent — vascular disease'),

    # --- Catheter Placement Arterial ---
    ('36245', 'Catheter placement, arterial, 2nd order abdominal/pelvic/lower ext',
     'I70.0', 108, 0.6000, 'Arterial catheter 2nd order — vascular disease evaluation'),
    ('36246', 'Catheter placement, arterial, initial 3rd order',
     'I70.0', 108, 0.6000, 'Arterial catheter 3rd order — vascular workup'),
    ('36247', 'Catheter placement, arterial, initial 3rd order, superselective',
     'I70.0', 108, 0.6000, 'Superselective arterial catheter — vascular disease'),
    ('36248', 'Catheter placement, additional 2nd/3rd order branch',
     'I70.0', 108, 0.6000, 'Additional arterial catheter placement'),

    # --- Duplex Scan ---
    ('93880', 'Duplex scan of extracranial arteries (carotid), complete',
     'I65.29', 107, 0.5000, 'Carotid duplex scan — carotid stenosis screening'),
    ('93882', 'Duplex scan of extracranial arteries, limited',
     'I65.29', 107, 0.5000, 'Limited carotid duplex — stenosis follow-up'),
    ('93925', 'Duplex scan of lower extremity arteries, complete',
     'I73.9', 108, 0.5000, 'Lower extremity arterial duplex — PVD evaluation'),
    ('93926', 'Duplex scan of lower extremity arteries, limited',
     'I73.9', 108, 0.5000, 'Limited LE arterial duplex — PVD follow-up'),
    ('93930', 'Duplex scan of upper extremity arteries, complete',
     'I73.9', 108, 0.4500, 'Upper extremity arterial duplex'),
    ('93931', 'Duplex scan of upper extremity arteries, limited',
     'I73.9', 108, 0.4500, 'Limited UE arterial duplex'),

    # =========================================================================
    # GASTROINTESTINAL
    # =========================================================================

    # --- Upper GI ---
    ('43239', 'EGD with biopsy, single or multiple',
     'K21.0', 0, 0.3500, 'EGD with biopsy — screen for GI conditions'),
    ('43235', 'EGD, diagnostic, including collection of specimen(s)',
     'K21.0', 0, 0.3500, 'Diagnostic EGD with specimen collection'),
    ('43249', 'EGD with balloon dilation of esophagus',
     'K22.2', 0, 0.4000, 'EGD with dilation — esophageal stricture'),
    ('43251', 'EGD with removal of tumor(s), polyp(s), or other lesion(s)',
     'C80.1', 12, 0.4000, 'EGD with lesion removal — GI neoplasm screen'),

    # --- Colonoscopy ---
    ('45380', 'Colonoscopy with biopsy, single or multiple',
     'C80.1', 12, 0.3500, 'Colonoscopy with biopsy — GI/cancer screen'),
    ('45385', 'Colonoscopy with removal of tumor(s), polyp(s)',
     'C80.1', 12, 0.3500, 'Colonoscopy with polypectomy — cancer screening'),
    ('45378', 'Colonoscopy, diagnostic',
     'C80.1', 12, 0.3000, 'Diagnostic colonoscopy'),
    ('45381', 'Colonoscopy with submucosal injection',
     'C80.1', 12, 0.3500, 'Colonoscopy with injection — GI pathology'),
    ('45384', 'Colonoscopy with removal by hot biopsy',
     'C80.1', 12, 0.3500, 'Colonoscopy hot biopsy — polyp/cancer screen'),
    ('45388', 'Colonoscopy with ablation of tumor(s)',
     'C80.1', 12, 0.4500, 'Colonoscopy with ablation — GI neoplasm'),

    # --- Cholecystectomy ---
    ('47562', 'Laparoscopic cholecystectomy',
     'K80.20', 0, 0.5000, 'Laparoscopic cholecystectomy — gallstones'),
    ('47563', 'Laparoscopic cholecystectomy with cholangiography',
     'K80.20', 0, 0.5000, 'Lap chole with cholangiography — gallstones'),
    ('47564', 'Laparoscopic cholecystectomy with exploration of common duct',
     'K80.20', 0, 0.5000, 'Lap chole with CBD exploration — gallstones'),
    ('47600', 'Cholecystectomy, open',
     'K80.20', 0, 0.5000, 'Open cholecystectomy — gallstones'),

    # --- Bariatric Surgery ---
    ('43644', 'Laparoscopic gastric bypass (Roux-en-Y)',
     'E66.01', 22, 0.9500, 'Gastric bypass — morbid obesity'),
    ('43645', 'Laparoscopic gastric bypass with small bowel reconstruction',
     'E66.01', 22, 0.9500, 'Complex gastric bypass — morbid obesity'),
    ('43770', 'Laparoscopic gastric restrictive procedure (band placement)',
     'E66.01', 22, 0.9500, 'Lap band placement — morbid obesity'),
    ('43775', 'Laparoscopic sleeve gastrectomy',
     'E66.01', 22, 0.9500, 'Sleeve gastrectomy — morbid obesity'),
    ('43842', 'Gastric restrictive procedure, vertical banded',
     'E66.01', 22, 0.9500, 'Vertical banded gastroplasty — morbid obesity'),
    ('43843', 'Gastric restrictive procedure with bypass',
     'E66.01', 22, 0.9500, 'Gastric restrictive with bypass — morbid obesity'),
    ('43846', 'Gastric bypass for morbid obesity, Roux-en-Y',
     'E66.01', 22, 0.9500, 'Open Roux-en-Y bypass — morbid obesity'),
    ('43847', 'Gastric bypass with small intestine reconstruction',
     'E66.01', 22, 0.9500, 'Complex gastric bypass — morbid obesity'),

    # =========================================================================
    # HIV / INFECTIOUS
    # =========================================================================

    ('87389', 'HIV-1 antigen with HIV-1 and HIV-2 antibodies (4th gen)',
     'B20', 1, 0.3000, 'HIV-1/2 Ag/Ab combo test — test ordered does not equal positive'),
    ('87390', 'HIV-1 antigen detection',
     'B20', 1, 0.3000, 'HIV-1 antigen detection'),
    ('87391', 'HIV-2 antigen detection',
     'B20', 1, 0.3000, 'HIV-2 antigen detection'),
    ('87534', 'HIV-1 quantitative RNA (viral load)',
     'B20', 1, 0.7500, 'HIV viral load — confirms active HIV management'),
    ('87535', 'HIV-1 quantitative RNA, second method',
     'B20', 1, 0.7500, 'HIV viral load alternate method'),
    ('87536', 'HIV-1 quantitative RNA, ultrasensitive',
     'B20', 1, 0.7500, 'Ultrasensitive HIV viral load'),
    ('87521', 'Hepatitis C, quantitative RNA (viral load)',
     'B18.2', 6, 0.5000, 'HCV RNA viral load — active Hepatitis C monitoring'),
    ('87522', 'Hepatitis C, quantitative RNA, reverse transcription',
     'B18.2', 6, 0.5000, 'HCV RNA by RT-PCR — Hepatitis C management'),
    ('86803', 'Hepatitis C antibody',
     'B18.2', 6, 0.3500, 'HCV antibody test — Hepatitis C screening'),

    # =========================================================================
    # DME (DURABLE MEDICAL EQUIPMENT)
    # =========================================================================

    # --- Hospital Bed ---
    ('E0260', 'Hospital bed, semi-electric (head-only)',
     'R53.81', 0, 0.3000, 'Hospital bed — screen for debility/chronic condition'),
    ('E0261', 'Hospital bed, semi-electric, with mattress',
     'R53.81', 0, 0.3000, 'Hospital bed with mattress — chronic debility'),
    ('E0265', 'Hospital bed, total electric',
     'R53.81', 0, 0.3000, 'Total electric hospital bed — debility'),
    ('E0266', 'Hospital bed, total electric, with mattress',
     'R53.81', 0, 0.3000, 'Total electric bed with mattress — debility'),
    ('E0290', 'Hospital bed, fixed height, without rails',
     'R53.81', 0, 0.3000, 'Fixed height hospital bed — chronic illness'),
    ('E0291', 'Hospital bed, fixed height, with rails',
     'R53.81', 0, 0.3000, 'Hospital bed with rails — chronic illness'),
    ('E0292', 'Hospital bed, variable height, without rails',
     'R53.81', 0, 0.3000, 'Variable height hospital bed'),
    ('E0293', 'Hospital bed, variable height, with rails',
     'R53.81', 0, 0.3000, 'Variable height bed with rails'),
    ('E0294', 'Hospital bed, semi-electric, without rails',
     'R53.81', 0, 0.3000, 'Semi-electric bed without rails'),
    ('E0295', 'Hospital bed, semi-electric, with rails',
     'R53.81', 0, 0.3000, 'Semi-electric bed with rails'),
    ('E0296', 'Hospital bed, total electric, without rails',
     'R53.81', 0, 0.3000, 'Total electric bed without rails'),
    ('E0297', 'Hospital bed, total electric, with rails',
     'R53.81', 0, 0.3000, 'Total electric bed with rails'),

    # --- CPAP / BiPAP ---
    ('E0601', 'CPAP device',
     'G47.33', 0, 0.7500, 'CPAP device — obstructive sleep apnea'),
    ('E0470', 'RAD (respiratory assist device), bi-level without backup rate',
     'G47.33', 0, 0.7500, 'BiPAP without backup — sleep apnea'),
    ('E0471', 'RAD, bi-level with backup rate',
     'J96.11', 84, 0.8000, 'BiPAP with backup rate — respiratory failure/COPD'),
    ('E0472', 'RAD, bi-level with backup rate, auto-titrating',
     'J96.11', 84, 0.8000, 'Auto BiPAP with backup — respiratory failure'),

    # --- Power Wheelchair ---
    ('K0800', 'Power wheelchair, group 1, standard, sling seat',
     'G82.50', 103, 0.6000, 'Power wheelchair group 1 — mobility impairment'),
    ('K0801', 'Power wheelchair, group 1, standard, captain seat',
     'G82.50', 103, 0.6000, 'Power wheelchair group 1 captain — mobility impairment'),
    ('K0802', 'Power wheelchair, group 1, heavy duty, sling seat',
     'G82.50', 103, 0.6000, 'Power wheelchair group 1 heavy — mobility impairment'),
    ('K0806', 'Power wheelchair, group 1, standard, single power option',
     'G82.50', 103, 0.6000, 'Power wheelchair with power option'),
    ('K0813', 'Power wheelchair, group 1, standard, multiple power options',
     'G82.50', 103, 0.6500, 'Power wheelchair multiple options — significant impairment'),
    ('K0814', 'Power wheelchair, group 2, standard, sling seat',
     'G82.50', 103, 0.6500, 'Power wheelchair group 2 — moderate-severe impairment'),
    ('K0815', 'Power wheelchair, group 2, standard, captain seat',
     'G82.50', 103, 0.6500, 'Power wheelchair group 2 captain'),
    ('K0816', 'Power wheelchair, group 2, heavy duty, sling seat',
     'G82.50', 103, 0.6500, 'Power wheelchair group 2 heavy duty'),
    ('K0820', 'Power wheelchair, group 2, standard, single power option',
     'G82.50', 103, 0.6500, 'Power wheelchair group 2 with power option'),
    ('K0835', 'Power wheelchair, group 2, standard, multiple power options',
     'G82.50', 103, 0.7000, 'Power wheelchair group 2 multiple options'),
    ('K0843', 'Power wheelchair, group 3, heavy duty',
     'G82.50', 103, 0.7000, 'Power wheelchair group 3 heavy — severe impairment'),
    ('K0848', 'Power wheelchair, group 3, very heavy duty',
     'G82.50', 103, 0.7000, 'Power wheelchair group 3 very heavy duty'),
    ('K0856', 'Power wheelchair, group 3, standard, single power option',
     'G82.50', 103, 0.7000, 'Power wheelchair group 3 with options'),
    ('K0861', 'Power wheelchair, group 3, standard, multiple power options',
     'G82.50', 103, 0.7000, 'Power wheelchair group 3 multiple options'),
    ('K0868', 'Power wheelchair, group 4, standard',
     'G82.50', 103, 0.7500, 'Power wheelchair group 4 — severe mobility deficit'),
    ('K0869', 'Power wheelchair, group 4, standard, captain seat',
     'G82.50', 103, 0.7500, 'Power wheelchair group 4 captain'),
    ('K0877', 'Power wheelchair, group 4, heavy duty',
     'G82.50', 103, 0.7500, 'Power wheelchair group 4 heavy duty'),
    ('K0878', 'Power wheelchair, group 4, very heavy duty',
     'G82.50', 103, 0.7500, 'Power wheelchair group 4 very heavy duty'),
    ('K0884', 'Power wheelchair, group 4, standard, single power option',
     'G82.50', 103, 0.7500, 'Power wheelchair group 4 with option'),
    ('K0886', 'Power wheelchair, group 4, standard, multiple power options',
     'G82.50', 103, 0.7500, 'Power wheelchair group 4 multiple options'),
    ('K0890', 'Power wheelchair, group 5, pediatric, single power option',
     'G82.50', 103, 0.7000, 'Power wheelchair group 5 pediatric'),
    ('K0891', 'Power wheelchair, group 5, pediatric, multiple power options',
     'G82.50', 103, 0.7000, 'Power wheelchair group 5 pediatric multi-option'),
    ('K0898', 'Power wheelchair, not otherwise classified',
     'G82.50', 103, 0.6000, 'Power wheelchair NOS — mobility impairment'),

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
        log.info("Table raf_procedure_signals: CREATE TABLE IF NOT EXISTS executed.")
    except MySQLError as exc:
        log.error("Failed to create table: %s", exc)
        cur.close()
        cnx.close()
        return 1

    # ------------------------------------------------------------------
    # 2.  Count existing rows
    # ------------------------------------------------------------------
    cur.execute("SELECT COUNT(*) AS cnt FROM raf_procedure_signals")
    existing_count = cur.fetchone()["cnt"]
    log.info("Table raf_procedure_signals currently has %d rows.", existing_count)

    # ------------------------------------------------------------------
    # 3.  Load existing (cpt_code, suspect_icd10) pairs
    #     for duplicate detection
    # ------------------------------------------------------------------
    cur.execute("SELECT cpt_code, suspect_icd10 FROM raf_procedure_signals")
    existing_pairs: set[tuple[str, str]] = set()
    for row in cur.fetchall():
        existing_pairs.add((row["cpt_code"], row["suspect_icd10"]))

    log.info("Loaded %d existing (cpt_code, icd10) pairs for dedup.", len(existing_pairs))

    # ------------------------------------------------------------------
    # 4.  Insert new signals
    # ------------------------------------------------------------------
    INSERT_SQL = """
        INSERT INTO raf_procedure_signals
            (cpt_code, cpt_description, suspect_icd10, suspect_hcc,
             confidence_base, notes, is_active)
        VALUES (%s, %s, %s, %s, %s, %s, 1)
    """

    inserted = 0
    skipped = 0
    errors = 0

    for cpt_code, cpt_desc, icd10, hcc, confidence, notes in SIGNALS:
        key = (cpt_code, icd10)
        if key in existing_pairs:
            skipped += 1
            continue

        try:
            cur.execute(INSERT_SQL, (cpt_code, cpt_desc, icd10, hcc, confidence, notes))
            existing_pairs.add(key)
            inserted += 1
        except MySQLError as exc:
            log.warning("Failed to insert cpt_code=%r icd10=%s: %s", cpt_code, icd10, exc)
            errors += 1

    cnx.commit()

    # ------------------------------------------------------------------
    # 5.  Report
    # ------------------------------------------------------------------
    cur.execute("SELECT COUNT(*) AS cnt FROM raf_procedure_signals")
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
