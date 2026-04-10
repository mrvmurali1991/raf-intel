#!/usr/bin/env python3
"""
seed_sample_patients.py
-----------------------
Populates the OpenEMR database (port 3309) with 18 realistic sample patients
for RAF Intelligence testing.

Each patient has:
  - patient_data row
  - 2–3 form_encounter rows (dated 2025–2026)
  - billing rows with ICD-10 codes (some intentionally incomplete → suspects)
  - form_soap notes with MEAT-compliant clinical text
  - forms registry rows linking encounters to SOAP notes
  - prescriptions linked to encounters

Suspects are patients where a medication strongly implies an uncoded HCC
condition.  These are flagged via a trailing comment in the SOAP assessment.

Dependencies:
    pip install mysql-connector-python

Usage:
    python scripts/seed_sample_patients.py
"""

from __future__ import annotations

import sys
import logging
from datetime import date, datetime
from typing import Optional

import mysql.connector
from mysql.connector import Error as MySQLError

# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

DB_CONFIG = dict(
    host="127.0.0.1",
    port=3309,
    user="root",
    password="root",
    database="openemr",
    charset="utf8mb4",
    collation="utf8mb4_unicode_ci",
    autocommit=False,
    connect_timeout=10,
)

# ---------------------------------------------------------------------------
# Patient definitions
# ---------------------------------------------------------------------------
# Each entry is a dict consumed by the seeder.
# 'suspect_note': plain text flag for the HCC suspect scenario
# 'encounters': list of encounter dicts, each with:
#   - date, reason
#   - diagnoses: list of (code, code_text) – ONLY what is actually billed
#   - soap: {subjective, objective, assessment, plan}
#   - medications: list of (drug, dosage, sig)
# ---------------------------------------------------------------------------
PATIENTS: list[dict] = [

    # ------------------------------------------------------------------
    # Patient 1: 72 y/o Male – DM2 + CKD stage 3 + CHF
    # SUSPECT: CKD not coded in billing despite furosemide + lisinopril
    # ------------------------------------------------------------------
    {
        "fname": "Robert", "lname": "Harrison", "sex": "Male",
        "dob": date(1952, 4, 15), "city": "Chicago", "state": "IL",
        "suspect": "CKD stage 3 not coded – lisinopril + furosemide imply renal management",
        "encounters": [
            {
                "date": datetime(2025, 3, 10, 9, 0),
                "reason": "Chronic disease management – DM/CHF follow-up",
                "diagnoses": [
                    ("E11.65",  "Type 2 diabetes mellitus with hyperglycemia"),
                    ("I50.32",  "Chronic diastolic congestive heart failure"),
                ],
                "soap": {
                    "subjective": (
                        "72-year-old male presents for routine follow-up of type 2 diabetes "
                        "and chronic diastolic heart failure. Reports mild lower extremity edema, "
                        "fatigue with exertion. Denies chest pain or orthopnea. "
                        "Compliant with medications: metformin 1000mg BID, insulin glargine 20 units QHS, "
                        "furosemide 40mg daily, lisinopril 10mg daily."
                    ),
                    "objective": (
                        "VS: BP 138/82 mmHg, HR 76 bpm, RR 16, SpO2 96%. Weight 192 lbs (stable). "
                        "Lungs: bibasilar crackles, mild. Extremities: 1+ pitting edema bilateral. "
                        "Labs: HbA1c 8.2%, BNP 310 pg/mL, Creatinine 1.8 mg/dL (eGFR 41 mL/min), "
                        "K+ 4.4 mEq/L."
                    ),
                    "assessment": (
                        "1. Type 2 diabetes mellitus with hyperglycemia – HbA1c improved from 8.9%; "
                        "continue current regimen, referral to endocrinology. "
                        "2. Chronic diastolic heart failure, NYHA class II – BNP stable, euvolemic. "
                        "3. Note: Creatinine 1.8 with eGFR 41 consistent with CKD stage 3b – "
                        "patient is on ACEi and diuretic consistent with renal protective therapy. "
                        "[SUSPECT HCC: CKD stage 3b not coded in billing this encounter]"
                    ),
                    "plan": (
                        "1. Continue metformin 1000mg BID, insulin glargine 20 units QHS. "
                        "2. Furosemide 40mg daily – continue for volume management. "
                        "3. Lisinopril 10mg daily – renal and cardiac protection. "
                        "4. Repeat BMP in 6 weeks. Nephrology referral placed. "
                        "5. Return in 3 months or sooner if worsening edema."
                    ),
                },
                "medications": [
                    ("Metformin",        "1000 mg",  "BID with meals"),
                    ("Insulin glargine", "20 units", "QHS subcutaneous"),
                    ("Furosemide",       "40 mg",    "Daily"),
                    ("Lisinopril",       "10 mg",    "Daily"),
                ],
            },
            {
                "date": datetime(2025, 9, 5, 10, 30),
                "reason": "DM/CHF quarterly follow-up",
                "diagnoses": [
                    ("E11.65",  "Type 2 diabetes mellitus with hyperglycemia"),
                    ("I50.32",  "Chronic diastolic congestive heart failure"),
                ],
                "soap": {
                    "subjective": (
                        "Patient returns for quarterly chronic care visit. "
                        "Edema improved since diuretic dose uptitration. Energy improved. "
                        "No hypoglycemic episodes. Creatinine monitored at nephrology."
                    ),
                    "objective": (
                        "BP 132/78, HR 72. Weight 188 lbs (down 4 lbs). "
                        "No peripheral edema. Lungs clear. "
                        "HbA1c 7.8%, Creatinine 1.9, eGFR 39, BNP 265."
                    ),
                    "assessment": (
                        "1. T2DM – glycemic control improving. "
                        "2. CHF diastolic – stable, NYHA class I-II. "
                        "3. CKD stage 3b per nephrology – on ACEi, monitoring per renal protocol. "
                        "[SUSPECT HCC: N18.32 still not billed in this facility]"
                    ),
                    "plan": (
                        "Continue current medication regimen. "
                        "Next visit in 3 months. "
                        "Ensure nephrology sends updated problem list for billing reconciliation."
                    ),
                },
                "medications": [
                    ("Metformin",        "1000 mg",  "BID with meals"),
                    ("Insulin glargine", "22 units", "QHS subcutaneous"),
                    ("Furosemide",       "40 mg",    "Daily"),
                    ("Lisinopril",       "10 mg",    "Daily"),
                ],
            },
        ],
    },

    # ------------------------------------------------------------------
    # Patient 2: 85 y/o Female – Dementia + COPD + AFib
    # SUSPECT: AFib not coded – apixaban strongly implies it
    # ------------------------------------------------------------------
    {
        "fname": "Eleanor", "lname": "Whitmore", "sex": "Female",
        "dob": date(1939, 11, 22), "city": "Detroit", "state": "MI",
        "suspect": "Atrial fibrillation not coded – patient on apixaban with irregular HR documented",
        "encounters": [
            {
                "date": datetime(2025, 2, 14, 11, 0),
                "reason": "Dementia and COPD management",
                "diagnoses": [
                    ("G30.1",  "Alzheimer disease with late onset"),
                    ("F02.80", "Dementia in other diseases, without behavioral disturbance"),
                    ("J44.9",  "Chronic obstructive pulmonary disease, unspecified"),
                ],
                "soap": {
                    "subjective": (
                        "85-year-old female with late-onset Alzheimer dementia and COPD, "
                        "accompanied by daughter. Caregiver reports mild worsening of confusion "
                        "over past 2 months. Shortness of breath on minimal exertion. "
                        "Current medications: donepezil 10mg QHS, memantine 10mg BID, "
                        "albuterol MDI PRN, tiotropium 18mcg daily, apixaban 5mg BID."
                    ),
                    "objective": (
                        "VS: BP 128/74, HR 82 irregular, RR 20, SpO2 93% on RA. "
                        "Pulmonary: prolonged expiratory phase, mild diffuse wheezes. "
                        "Neurological: MMSE 14/30 (was 17 last year). "
                        "Cardiac: irregular rhythm, no murmurs."
                    ),
                    "assessment": (
                        "1. Alzheimer dementia with late onset – moderate stage, MMSE 14. "
                        "Donepezil and memantine continued. "
                        "2. COPD – FEV1 52% predicted, GOLD stage 2. Albuterol and tiotropium maintained. "
                        "3. Irregular cardiac rhythm noted on exam – apixaban on medication list, "
                        "consistent with known atrial fibrillation per prior cardiology note. "
                        "[SUSPECT HCC: Atrial fibrillation I48.91 not coded in active problem list or billing]"
                    ),
                    "plan": (
                        "1. Continue donepezil 10mg QHS, memantine 10mg BID. "
                        "2. Pulmonary rehab referral for COPD management. "
                        "3. Cardiology to confirm AFib status and update problem list for billing. "
                        "4. Caregiver education on safety and fall prevention. "
                        "5. Follow up 3 months."
                    ),
                },
                "medications": [
                    ("Donepezil",    "10 mg",  "QHS"),
                    ("Memantine",    "10 mg",  "BID"),
                    ("Albuterol",    "2 puffs", "PRN q4-6h"),
                    ("Tiotropium",   "18 mcg", "Daily inhaled"),
                    ("Apixaban",     "5 mg",   "BID"),
                ],
            },
            {
                "date": datetime(2026, 1, 8, 9, 30),
                "reason": "Annual wellness visit – geriatric assessment",
                "diagnoses": [
                    ("G30.1",  "Alzheimer disease with late onset"),
                    ("J44.9",  "COPD, unspecified"),
                ],
                "soap": {
                    "subjective": (
                        "Annual wellness visit. Daughter reports patient more dependent in ADLs. "
                        "No falls since last visit. Appetite stable. Continues apixaban without bleeding events."
                    ),
                    "objective": (
                        "BP 122/70, HR 86 and irregular. SpO2 91% on RA. MMSE 12/30. "
                        "Bilateral ankle edema 1+. Gait slow with walker."
                    ),
                    "assessment": (
                        "1. Alzheimer dementia – advancing, MMSE declined 2 points. "
                        "2. COPD – partially controlled. "
                        "3. Anticoagulation with apixaban ongoing; irregular rhythm confirmed again – "
                        "AFib diagnosis must be added to encounter billing. "
                        "[SUSPECT HCC: I48.91 again absent from billing codes]"
                    ),
                    "plan": (
                        "Add I48.91 to problem list and billing. "
                        "Consider hospice evaluation discussion with family given disease trajectory. "
                        "Continue current medications."
                    ),
                },
                "medications": [
                    ("Donepezil",    "10 mg",  "QHS"),
                    ("Memantine",    "10 mg",  "BID"),
                    ("Albuterol",    "2 puffs", "PRN"),
                    ("Apixaban",     "5 mg",   "BID"),
                ],
            },
        ],
    },

    # ------------------------------------------------------------------
    # Patient 3: 68 y/o Female – Metastatic breast cancer + Depression
    # All conditions fully coded
    # ------------------------------------------------------------------
    {
        "fname": "Sandra", "lname": "Kowalski", "sex": "Female",
        "dob": date(1956, 7, 4), "city": "Milwaukee", "state": "WI",
        "suspect": None,
        "encounters": [
            {
                "date": datetime(2025, 4, 22, 13, 0),
                "reason": "Oncology follow-up – metastatic breast cancer",
                "diagnoses": [
                    ("C79.81", "Secondary malignant neoplasm of breast"),
                    ("C50.912","Malignant neoplasm of unspecified site of left female breast"),
                    ("F32.1",  "Major depressive disorder, single episode, moderate"),
                    ("E66.01", "Morbid obesity due to excess calories"),
                ],
                "soap": {
                    "subjective": (
                        "68-year-old female with metastatic breast cancer (bone mets confirmed on PET), "
                        "presenting for oncology follow-up after cycle 4 of palbociclib + letrozole. "
                        "Reports fatigue, mild nausea, mood low. On sertraline 100mg daily for depression, "
                        "which was started 6 months ago. BMI 42."
                    ),
                    "objective": (
                        "ECOG performance status 1. Weight 248 lbs, BMI 42.1. "
                        "No new skeletal pain. CBC: ANC 1.2 (mild neutropenia). "
                        "Tumor markers: CA 27-29 declining trend (from 89 to 62). "
                        "PHQ-9 score: 12 (moderate depression)."
                    ),
                    "assessment": (
                        "1. Metastatic breast cancer to bone – partial response to palbociclib + letrozole. "
                        "CA 27-29 trending down. Continue current regimen with dose modification for neutropenia. "
                        "2. Major depressive disorder, moderate – PHQ-9 12, partially responsive to sertraline. "
                        "Increase sertraline to 150mg, refer to oncology social work. "
                        "3. Morbid obesity BMI 42 – limiting activity tolerance. Nutrition consultation placed."
                    ),
                    "plan": (
                        "1. Palbociclib dose reduced to 100mg for one cycle due to ANC. "
                        "2. Letrozole 2.5mg daily – continue. "
                        "3. Sertraline uptitrated to 150mg daily. "
                        "4. Zoledronic acid 4mg IV every 3 months – bone protection. "
                        "5. Repeat PET/CT in 3 months. Return in 4 weeks."
                    ),
                },
                "medications": [
                    ("Palbociclib",   "125 mg", "Daily x21 days, then 7 days off"),
                    ("Letrozole",     "2.5 mg", "Daily"),
                    ("Sertraline",    "150 mg", "Daily"),
                    ("Zoledronic acid","4 mg IV","Every 3 months"),
                ],
            },
        ],
    },

    # ------------------------------------------------------------------
    # Patient 4: 55 y/o Male – HIV + Hepatitis C + Substance use disorder
    # SUSPECT: Hepatitis C not coded – prescribed ledipasvir/sofosbuvir
    # ------------------------------------------------------------------
    {
        "fname": "Marcus", "lname": "Thompson", "sex": "Male",
        "dob": date(1969, 2, 28), "city": "Baltimore", "state": "MD",
        "suspect": "Hepatitis C not coded – patient on ledipasvir/sofosbuvir (Harvoni)",
        "encounters": [
            {
                "date": datetime(2025, 5, 16, 14, 0),
                "reason": "HIV and infectious disease management",
                "diagnoses": [
                    ("B20",   "Human immunodeficiency virus [HIV] disease"),
                    ("F11.21","Opioid dependence, in remission"),
                ],
                "soap": {
                    "subjective": (
                        "55-year-old male with HIV on ART (bictegravir/emtricitabine/tenofovir), "
                        "opioid use disorder in remission on buprenorphine-naloxone 16/4mg daily, "
                        "and hepatitis C currently on ledipasvir-sofosbuvir (Harvoni) week 8 of 12. "
                        "Reports fatigue, mild nausea attributed to Harvoni. No active drug use."
                    ),
                    "objective": (
                        "VS: BP 122/76, HR 68, Weight 168 lbs. "
                        "No jaundice, no scleral icterus. Abdomen: mild hepatomegaly. "
                        "Labs: CD4 count 612 cells/uL (up from 524), HIV VL undetectable. "
                        "HCV RNA: 45 IU/mL (down from 2.3M at treatment start). "
                        "AST 48, ALT 52, Total bili 0.9."
                    ),
                    "assessment": (
                        "1. HIV disease – virologically suppressed. CD4 improving. Continue ART. "
                        "2. Opioid dependence in sustained remission – on MOUD (buprenorphine). "
                        "Continue current dose. "
                        "3. Hepatitis C genotype 1a – week 8 of 12-week Harvoni; SVR on track, HCV RNA declining. "
                        "[SUSPECT HCC: B18.2 Chronic hepatitis C not coded in billing this encounter – "
                        "ledipasvir/sofosbuvir treatment strongly implies active HCV management]"
                    ),
                    "plan": (
                        "1. Continue bictegravir/emtricitabine/tenofovir daily. "
                        "2. Buprenorphine-naloxone 16/4mg daily – continue MOUD. "
                        "3. Ledipasvir-sofosbuvir – complete week 12, then SVR12 testing. "
                        "4. Repeat LFTs, CBC in 4 weeks. "
                        "5. Ensure B18.2 added to billing at next encounter."
                    ),
                },
                "medications": [
                    ("Bictegravir/emtricitabine/tenofovir", "50/200/25 mg", "Daily"),
                    ("Buprenorphine-naloxone",              "16/4 mg",      "Daily sublingual"),
                    ("Ledipasvir-sofosbuvir",               "90/400 mg",    "Daily x 12 weeks"),
                ],
            },
        ],
    },

    # ------------------------------------------------------------------
    # Patient 5: 78 y/o Male – Parkinson's + CHF + DM2 (all coded)
    # ------------------------------------------------------------------
    {
        "fname": "William", "lname": "Okafor", "sex": "Male",
        "dob": date(1946, 9, 12), "city": "Houston", "state": "TX",
        "suspect": None,
        "encounters": [
            {
                "date": datetime(2025, 6, 3, 10, 0),
                "reason": "Parkinson's and cardiac management",
                "diagnoses": [
                    ("G20",   "Parkinson disease"),
                    ("I50.22","Chronic systolic congestive heart failure"),
                    ("E11.65","Type 2 diabetes mellitus with hyperglycemia"),
                ],
                "soap": {
                    "subjective": (
                        "78-year-old male with Parkinson disease (H&Y stage 3), chronic systolic CHF "
                        "(EF 38%), and type 2 diabetes. Reports increased rigidity and tremor. "
                        "Fell once last month. Mild dyspnea with walking. "
                        "On carbidopa-levodopa 25/100mg TID, carvedilol 12.5mg BID, "
                        "sacubitril/valsartan 49/51mg BID, metformin 500mg BID."
                    ),
                    "objective": (
                        "BP 118/70 (orthostatic drop to 98/62 standing). HR 58. "
                        "Resting tremor bilateral hands, bradykinesia, shuffling gait. "
                        "Chest: bibasilar crackles mild. Echo (3mo ago): EF 38%. "
                        "BNP 428. HbA1c 7.9%."
                    ),
                    "assessment": (
                        "1. Parkinson disease H&Y stage 3 – worsening motor function. "
                        "Add entacapone 200mg with each levodopa dose. Neurology referral for DBS evaluation. "
                        "2. Chronic systolic CHF EF 38% – BNP elevated. Uptitrate sacubitril/valsartan. "
                        "3. Type 2 DM – HbA1c 7.9%, glycemic control suboptimal. "
                        "Increase metformin, add empagliflozin for cardiorenal benefit. "
                        "4. Orthostatic hypotension – likely medication effect; adjust carbidopa-levodopa timing."
                    ),
                    "plan": (
                        "1. Carbidopa-levodopa 25/100mg TID + entacapone 200mg with each dose. "
                        "2. Sacubitril/valsartan 97/103mg BID (uptitrated). "
                        "3. Carvedilol 12.5mg BID – continue. "
                        "4. Empagliflozin 10mg daily added. Metformin 1000mg BID. "
                        "5. Physical therapy referral for fall prevention. "
                        "6. 2-week follow-up for BP monitoring post uptitration."
                    ),
                },
                "medications": [
                    ("Carbidopa-levodopa",   "25/100 mg", "TID"),
                    ("Entacapone",           "200 mg",    "With each levodopa dose"),
                    ("Sacubitril/valsartan", "97/103 mg", "BID"),
                    ("Carvedilol",           "12.5 mg",   "BID"),
                    ("Empagliflozin",        "10 mg",     "Daily"),
                    ("Metformin",            "1000 mg",   "BID"),
                ],
            },
        ],
    },

    # ------------------------------------------------------------------
    # Patient 6: 62 y/o Female – Multiple sclerosis + Depression
    # SUSPECT: Depression coded but inadequate MEAT documentation
    # ------------------------------------------------------------------
    {
        "fname": "Patricia", "lname": "Okonkwo", "sex": "Female",
        "dob": date(1962, 5, 30), "city": "Phoenix", "state": "AZ",
        "suspect": None,
        "encounters": [
            {
                "date": datetime(2025, 7, 18, 11, 30),
                "reason": "MS relapse management and depression follow-up",
                "diagnoses": [
                    ("G35",   "Multiple sclerosis"),
                    ("F33.1", "Major depressive disorder, recurrent, moderate"),
                ],
                "soap": {
                    "subjective": (
                        "62-year-old female with relapsing-remitting multiple sclerosis on "
                        "natalizumab 300mg IV q28 days. Reports new episode of left leg weakness "
                        "and paresthesias for 3 weeks consistent with relapse. "
                        "Depression worsening with PHQ-9 of 14 (moderate). "
                        "Currently on duloxetine 60mg daily. No suicidal ideation."
                    ),
                    "objective": (
                        "EDSS 3.5 (increased from 2.5). Left leg: 4/5 strength, hyperreflexia. "
                        "Sensory loss L3-S1 distribution left side. "
                        "MRI brain/spine (last month): 2 new T2 lesions. "
                        "PHQ-9: 14. No SI."
                    ),
                    "assessment": (
                        "1. RRMS with active relapse – new lesions and clinical symptoms. "
                        "IV methylprednisolone 1g daily x 3 days for acute relapse. "
                        "2. Recurrent major depressive disorder, moderate – PHQ-9 14, duloxetine partially effective. "
                        "Uptitrate duloxetine to 90mg, psychiatry co-management referral. "
                        "3. JC virus antibody index 2.8 – discuss natalizumab risk/benefit; "
                        "transition to ocrelizumab considered."
                    ),
                    "plan": (
                        "1. IV methylprednisolone 1g daily x 3 days. "
                        "2. Duloxetine 90mg daily. Psychiatry referral placed. "
                        "3. Neurology discussion regarding DMT switch to ocrelizumab. "
                        "4. PT/OT for gait rehabilitation. "
                        "5. Follow-up in 6 weeks."
                    ),
                },
                "medications": [
                    ("Natalizumab",      "300 mg IV",  "Every 28 days"),
                    ("Duloxetine",       "90 mg",      "Daily"),
                    ("Methylprednisolone","1000 mg IV", "Daily x3 days (acute)"),
                ],
            },
        ],
    },

    # ------------------------------------------------------------------
    # Patient 7: 91 y/o Female – Pressure ulcer stage 3 + CHF + Dementia
    # ------------------------------------------------------------------
    {
        "fname": "Dorothy", "lname": "Chambers", "sex": "Female",
        "dob": date(1933, 1, 5), "city": "Philadelphia", "state": "PA",
        "suspect": None,
        "encounters": [
            {
                "date": datetime(2025, 8, 12, 14, 30),
                "reason": "Skilled nursing facility – wound management + CHF",
                "diagnoses": [
                    ("L89.303","Pressure ulcer of unspecified buttock, stage 3"),
                    ("I50.32", "Chronic diastolic congestive heart failure"),
                    ("F03.90", "Unspecified dementia without behavioral disturbance"),
                ],
                "soap": {
                    "subjective": (
                        "91-year-old female in skilled nursing facility with severe dementia, "
                        "diastolic CHF, and a stage 3 pressure ulcer on sacrum/buttock. "
                        "Caregiver reports ulcer not improving despite wound care. "
                        "Patient unable to provide history. "
                        "On furosemide 80mg daily, metoprolol succinate 25mg daily, "
                        "donepezil 10mg QHS."
                    ),
                    "objective": (
                        "Non-verbal. BP 110/68, HR 80. "
                        "Wound: 4.2cm x 3.8cm stage 3 pressure ulcer right buttock, "
                        "clean base, no undermining, minimal slough. "
                        "Bilateral lower extremity edema 2+. BNP 892. "
                        "MMSE not assessable."
                    ),
                    "assessment": (
                        "1. Stage 3 pressure ulcer sacrum/right buttock – improving trajectory. "
                        "Continue collagen wound dressing with moisture barrier. "
                        "2. Chronic diastolic CHF – volume overloaded, increase furosemide to 80mg BID. "
                        "3. Dementia, unspecified – advanced stage, comfort-focused care goals confirmed "
                        "with family – DNR/DNI on file."
                    ),
                    "plan": (
                        "1. Wound care: collagen dressing changes every 48 hours, "
                        "positioning protocol q2h. Wound care specialist consult. "
                        "2. Furosemide 80mg BID. Repeat BMP in 3 days. "
                        "3. Palliative care team co-management. "
                        "4. Family meeting scheduled for goals of care discussion."
                    ),
                },
                "medications": [
                    ("Furosemide",          "80 mg",  "BID"),
                    ("Metoprolol succinate", "25 mg",  "Daily"),
                    ("Donepezil",           "10 mg",  "QHS"),
                ],
            },
        ],
    },

    # ------------------------------------------------------------------
    # Patient 8: 48 y/o Male – Schizophrenia + Morbid obesity
    # SUSPECT: No morbid obesity coded despite BMI 48 documented in note
    # ------------------------------------------------------------------
    {
        "fname": "Antoine", "lname": "Dubois", "sex": "Male",
        "dob": date(1976, 10, 17), "city": "New Orleans", "state": "LA",
        "suspect": "Morbid obesity not coded – BMI 48 documented, implies E66.01",
        "encounters": [
            {
                "date": datetime(2025, 6, 25, 9, 0),
                "reason": "Psychiatric medication management",
                "diagnoses": [
                    ("F20.9",  "Schizophrenia, unspecified"),
                ],
                "soap": {
                    "subjective": (
                        "48-year-old male with chronic schizophrenia, undifferentiated type. "
                        "Medication adherent on clozapine 300mg QHS. No active psychosis. "
                        "Reports increased appetite and weight gain on clozapine. "
                        "BMI at last visit 47.8. Endorses fatigue, dyspnea on minimal exertion. "
                        "No diabetes currently diagnosed but fasting glucose last month was 118."
                    ),
                    "objective": (
                        "VS: BP 142/88, HR 82, Weight 316 lbs, Height 5'8\", BMI 48.0. "
                        "Abdomen: obese, no organomegaly. "
                        "ANC 2100 (within clozapine monitoring threshold). "
                        "Fasting glucose 122, HbA1c 6.3% (prediabetes range). "
                        "Lipids: LDL 148, HDL 32."
                    ),
                    "assessment": (
                        "1. Schizophrenia, undifferentiated – stable on clozapine. No active psychosis. "
                        "Continue current dose with ANC monitoring. "
                        "2. BMI 48 – severe morbid obesity. Weight gain secondary to atypical antipsychotic. "
                        "Nutrition and bariatric evaluation referral placed. "
                        "[SUSPECT HCC: E66.01 morbid obesity not coded in billing – BMI 48 documented] "
                        "3. Prediabetes – lifestyle modification counseling. Repeat HbA1c in 6 months."
                    ),
                    "plan": (
                        "1. Clozapine 300mg QHS – continue. ANC every 4 weeks. "
                        "2. Metformin 500mg BID initiated for prediabetes prevention. "
                        "3. Dietary consult ordered. Weight loss target 10% over 6 months. "
                        "4. BP: start amlodipine 5mg daily for hypertension. "
                        "5. Follow up psychiatry in 4 weeks."
                    ),
                },
                "medications": [
                    ("Clozapine",   "300 mg",  "QHS"),
                    ("Metformin",   "500 mg",  "BID"),
                    ("Amlodipine",  "5 mg",    "Daily"),
                ],
            },
        ],
    },

    # ------------------------------------------------------------------
    # Patient 9: 66 y/o Female – Rheumatoid arthritis + CKD stage 4
    # All conditions coded
    # ------------------------------------------------------------------
    {
        "fname": "Carmen", "lname": "Vega", "sex": "Female",
        "dob": date(1958, 3, 19), "city": "Miami", "state": "FL",
        "suspect": None,
        "encounters": [
            {
                "date": datetime(2025, 4, 8, 10, 30),
                "reason": "Rheumatology follow-up – RA and CKD monitoring",
                "diagnoses": [
                    ("M05.70","Rheumatoid arthritis with rheumatoid factor, unspecified site"),
                    ("N18.4", "Chronic kidney disease, stage 4"),
                ],
                "soap": {
                    "subjective": (
                        "66-year-old female with seropositive rheumatoid arthritis on "
                        "abatacept 125mg SQ weekly and methotrexate 15mg weekly. "
                        "Also has CKD stage 4 (eGFR 22 mL/min) due to membranous nephropathy. "
                        "Joint symptoms improved, morning stiffness < 15 minutes. "
                        "Reports fatigue and mild lower extremity edema."
                    ),
                    "objective": (
                        "Joint exam: minimal synovitis bilateral MCP joints. "
                        "DAS28-CRP 2.4 (low disease activity). "
                        "Creatinine 2.8, eGFR 22, potassium 5.1, bicarbonate 19. "
                        "Anemia: Hgb 10.2 (normocytic). Urinalysis: 2+ protein."
                    ),
                    "assessment": (
                        "1. RA with RF+ – low disease activity on abatacept + MTX. Maintain current regimen. "
                        "2. CKD stage 4 – eGFR declining from 28 to 22 over 12 months. "
                        "Nephrology co-management. Restrict NSAID use. Anemia of CKD – start erythropoietin. "
                        "3. Metabolic acidosis mild – sodium bicarbonate supplementation initiated."
                    ),
                    "plan": (
                        "1. Abatacept 125mg SQ weekly – continue. "
                        "2. Methotrexate 15mg weekly – dose reduction to 10mg due to renal impairment. "
                        "3. Erythropoietin alpha 10,000 units SQ weekly. "
                        "4. Sodium bicarbonate 650mg TID. "
                        "5. Nephrology referral for pre-dialysis planning. "
                        "6. Avoid NSAIDs, gadolinium contrast. Return in 6 weeks."
                    ),
                },
                "medications": [
                    ("Abatacept",           "125 mg SQ",    "Weekly"),
                    ("Methotrexate",        "10 mg",        "Weekly"),
                    ("Erythropoietin alpha","10000 units SQ","Weekly"),
                    ("Sodium bicarbonate",  "650 mg",       "TID"),
                ],
            },
        ],
    },

    # ------------------------------------------------------------------
    # Patient 10: 59 y/o Male – Bipolar I + Vascular disease
    # ------------------------------------------------------------------
    {
        "fname": "Raymond", "lname": "Fitzgerald", "sex": "Male",
        "dob": date(1965, 8, 24), "city": "Seattle", "state": "WA",
        "suspect": None,
        "encounters": [
            {
                "date": datetime(2025, 3, 28, 13, 30),
                "reason": "Psychiatric and vascular disease co-management",
                "diagnoses": [
                    ("F31.32","Bipolar disorder, current episode depressed, moderate"),
                    ("I73.9", "Peripheral vascular disease, unspecified"),
                    ("I70.211","Atherosclerosis of native arteries with intermittent claudication, right leg"),
                ],
                "soap": {
                    "subjective": (
                        "59-year-old male smoker (40 pack-years, quit 2 years ago) with bipolar I disorder, "
                        "currently in a depressive episode (moderate) on lithium 900mg daily + quetiapine 200mg QHS. "
                        "Also has peripheral arterial disease with claudication right leg at 1.5 blocks. "
                        "ABI last month 0.68 right, 0.74 left. "
                        "On aspirin 81mg, cilostazol 100mg BID, atorvastatin 40mg."
                    ),
                    "objective": (
                        "BP 148/92, HR 76. "
                        "Right pedal pulses diminished. ABI 0.68. Skin: bilateral lower leg hair loss. "
                        "Mood: depressed, affect blunted. PHQ-9 13. No SI. "
                        "Lithium level 0.8 mEq/L (therapeutic). LDL 88 on statin."
                    ),
                    "assessment": (
                        "1. Bipolar I, current depressive episode moderate – PHQ-9 13. "
                        "Lithium therapeutic. Add lamotrigine 25mg titrating to 200mg for depression adjunct. "
                        "2. PAD with claudication right leg – vascular surgery referral for assessment. "
                        "Consider endovascular intervention if symptoms progress. "
                        "3. Hypertension – add amlodipine 5mg daily."
                    ),
                    "plan": (
                        "1. Lithium 900mg daily – continue, recheck level in 3 months. "
                        "2. Quetiapine 200mg QHS – continue. "
                        "3. Lamotrigine 25mg daily titrating up over 8 weeks. "
                        "4. Cilostazol 100mg BID, aspirin 81mg, atorvastatin 40mg – continue. "
                        "5. Amlodipine 5mg daily added. "
                        "6. Vascular surgery referral placed. Supervised walking program recommended."
                    ),
                },
                "medications": [
                    ("Lithium",      "300 mg",  "TID (900mg/day)"),
                    ("Quetiapine",   "200 mg",  "QHS"),
                    ("Lamotrigine",  "25 mg",   "Daily (titrating)"),
                    ("Cilostazol",   "100 mg",  "BID"),
                    ("Aspirin",      "81 mg",   "Daily"),
                    ("Atorvastatin", "40 mg",   "QHS"),
                    ("Amlodipine",   "5 mg",    "Daily"),
                ],
            },
        ],
    },

    # ------------------------------------------------------------------
    # Patient 11: 74 y/o Male – Kidney transplant + DM2 + AFib
    # SUSPECT: Post-transplant diabetes not fully coded to HCC level
    # ------------------------------------------------------------------
    {
        "fname": "James", "lname": "Nakamura", "sex": "Male",
        "dob": date(1950, 12, 3), "city": "Portland", "state": "OR",
        "suspect": None,
        "encounters": [
            {
                "date": datetime(2025, 5, 7, 11, 0),
                "reason": "Transplant nephrology follow-up",
                "diagnoses": [
                    ("Z94.0", "Kidney transplant status"),
                    ("E11.9", "Type 2 diabetes mellitus without complications"),
                    ("I48.21","Permanent atrial fibrillation"),
                ],
                "soap": {
                    "subjective": (
                        "74-year-old male with renal transplant (deceased donor, 2019) on tacrolimus + "
                        "mycophenolate. Stable allograft function. Also has type 2 diabetes (post-transplant) "
                        "and permanent atrial fibrillation on rivaroxaban. "
                        "Reports stable energy, no rejection symptoms. "
                        "HbA1c last month 7.4%."
                    ),
                    "objective": (
                        "BP 128/76, HR 80 irregular. "
                        "Creatinine 1.4, eGFR 52. Tacrolimus trough 6.2. "
                        "HbA1c 7.4%. BNP 92. No peripheral edema."
                    ),
                    "assessment": (
                        "1. Kidney transplant status – stable allograft, eGFR 52. Tacrolimus therapeutic. "
                        "2. T2DM without complications – HbA1c 7.4%, acceptable target for transplant patient. "
                        "Continue metformin with caution given eGFR; add sitagliptin as SGLT2i avoided post-transplant. "
                        "3. Permanent AFib on rivaroxaban – CHA2DS2-VASc 4, anticoagulation appropriate. "
                        "Rate controlled with metoprolol."
                    ),
                    "plan": (
                        "1. Tacrolimus adjust per levels – current 3mg BID. "
                        "2. Metformin 500mg BID (lower dose, eGFR 52). Add sitagliptin 50mg daily. "
                        "3. Rivaroxaban 20mg daily with evening meal – continue. "
                        "4. Metoprolol succinate 50mg daily – continue. "
                        "5. Next transplant visit in 3 months."
                    ),
                },
                "medications": [
                    ("Tacrolimus",          "3 mg",   "BID"),
                    ("Mycophenolate",       "750 mg", "BID"),
                    ("Metformin",           "500 mg", "BID"),
                    ("Sitagliptin",         "50 mg",  "Daily"),
                    ("Rivaroxaban",         "20 mg",  "Daily with evening meal"),
                    ("Metoprolol succinate","50 mg",  "Daily"),
                ],
            },
        ],
    },

    # ------------------------------------------------------------------
    # Patient 12: 82 y/o Female – CHF + COPD + CKD stage 4
    # Interaction: CHF + COPD (HCC85 x HCC111)
    # ------------------------------------------------------------------
    {
        "fname": "Agnes", "lname": "Kowalczyk", "sex": "Female",
        "dob": date(1942, 6, 14), "city": "Cleveland", "state": "OH",
        "suspect": None,
        "encounters": [
            {
                "date": datetime(2025, 7, 1, 9, 30),
                "reason": "Decompensated CHF hospitalization follow-up",
                "diagnoses": [
                    ("I50.43","Acute on chronic combined systolic and diastolic heart failure"),
                    ("J44.1", "COPD with acute exacerbation"),
                    ("N18.4", "Chronic kidney disease, stage 4"),
                ],
                "soap": {
                    "subjective": (
                        "82-year-old female discharged 5 days ago after 4-day hospitalization for "
                        "acute-on-chronic combined systolic/diastolic CHF with concurrent COPD exacerbation. "
                        "Today reports improved breathing, weight down 6 lbs from admission. "
                        "CKD stage 4 (eGFR 24) – on renally adjusted medications."
                    ),
                    "objective": (
                        "BP 118/72, HR 78, SpO2 94% on 2L NC. Weight 148 lbs. "
                        "Mild bibasilar crackles. 1+ ankle edema. "
                        "BNP 678 (down from 2100 on admission). "
                        "Creatinine 2.9, eGFR 24. Peak flow 180 L/min."
                    ),
                    "assessment": (
                        "1. Acute-on-chronic CHF (combined) – improving post-hospitalization. "
                        "BNP trending down. Continue aggressive diuresis. "
                        "2. COPD exacerbation – resolving; completing prednisone taper and azithromycin. "
                        "3. CKD stage 4 – close monitoring, avoid nephrotoxins. "
                        "Note: CHF+COPD interaction significantly elevates RAF score (interaction term applies)."
                    ),
                    "plan": (
                        "1. Furosemide 80mg BID – continue diuresis. Daily weights. "
                        "2. Prednisone 20mg daily x 3 more days (completing taper). "
                        "3. Azithromycin 250mg daily x 2 more days. "
                        "4. Inhaled tiotropium daily, albuterol PRN. "
                        "5. Home health nursing 3x/week for weight/edema monitoring. "
                        "6. Return 1 week."
                    ),
                },
                "medications": [
                    ("Furosemide",   "80 mg",   "BID"),
                    ("Prednisone",   "20 mg",   "Daily (tapering)"),
                    ("Azithromycin", "250 mg",  "Daily x2 more days"),
                    ("Tiotropium",   "18 mcg",  "Daily inhaled"),
                    ("Albuterol",    "2 puffs", "PRN q4-6h"),
                    ("Carvedilol",   "6.25 mg", "BID"),
                ],
            },
        ],
    },

    # ------------------------------------------------------------------
    # Patient 13: 45 y/o Female – HIV + Metastatic cervical cancer
    # ------------------------------------------------------------------
    {
        "fname": "Destiny", "lname": "Williams", "sex": "Female",
        "dob": date(1979, 4, 10), "city": "Atlanta", "state": "GA",
        "suspect": None,
        "encounters": [
            {
                "date": datetime(2025, 9, 22, 14, 0),
                "reason": "Oncology – metastatic cervical cancer in HIV-positive patient",
                "diagnoses": [
                    ("B20",   "Human immunodeficiency virus [HIV] disease"),
                    ("C79.51","Secondary malignant neoplasm of bone"),
                    ("C80.1", "Malignant (primary) neoplasm, unspecified"),
                ],
                "soap": {
                    "subjective": (
                        "45-year-old female with HIV (CD4 388, VL undetectable on ART) and "
                        "stage IVB cervical cancer with bone metastases. "
                        "On pembrolizumab + chemotherapy cycle 3. "
                        "Reports severe fatigue, bone pain right hip managed with oxycodone ER 20mg q12h."
                    ),
                    "objective": (
                        "ECOG 2. Weight 102 lbs (down 8 lbs in 2 months). "
                        "Right hip: tenderness with palpation, mobility limited. "
                        "CBC: Hgb 9.1, ANC 1800, platelets 98K. "
                        "CD4 388, HIV VL undetectable."
                    ),
                    "assessment": (
                        "1. Metastatic cervical cancer (bone mets) – partial response per imaging. "
                        "Continue pembrolizumab + cisplatin/5-FU. Bone-modifying agent added. "
                        "2. HIV disease – virologically suppressed. ART continued. "
                        "3. Malignancy-related weight loss and pain – palliative care co-management. "
                        "4. Transfusion threshold Hgb < 8.0."
                    ),
                    "plan": (
                        "1. Pembrolizumab 200mg IV q21 days – continue cycle 3. "
                        "2. Zoledronic acid 4mg IV – start for bone metastases. "
                        "3. Oxycodone ER 20mg q12h – continue; add oxazepam 15mg for sleep. "
                        "4. Continue ART (dolutegravir/lamivudine). "
                        "5. Palliative care and social work referral. "
                        "6. Next cycle in 3 weeks."
                    ),
                },
                "medications": [
                    ("Pembrolizumab",      "200 mg IV",  "Every 21 days"),
                    ("Zoledronic acid",    "4 mg IV",    "Monthly"),
                    ("Oxycodone ER",       "20 mg",      "Every 12 hours"),
                    ("Dolutegravir/lamivudine", "50/300 mg", "Daily"),
                ],
            },
        ],
    },

    # ------------------------------------------------------------------
    # Patient 14: 53 y/o Male – DM2 + Neuropathy + Depression
    # SUSPECT: Diabetic neuropathy (E11.40) not coded in billing
    # ------------------------------------------------------------------
    {
        "fname": "Kevin", "lname": "Patel", "sex": "Male",
        "dob": date(1971, 11, 7), "city": "Dallas", "state": "TX",
        "suspect": "Diabetic neuropathy not coded – patient on duloxetine + gabapentin, HbA1c 10.1%",
        "encounters": [
            {
                "date": datetime(2025, 8, 19, 10, 0),
                "reason": "DM2 poorly controlled + neuropathic pain follow-up",
                "diagnoses": [
                    ("E11.65","Type 2 diabetes mellitus with hyperglycemia"),
                    ("F32.1", "Major depressive disorder, single episode, moderate"),
                ],
                "soap": {
                    "subjective": (
                        "53-year-old male with poorly controlled type 2 diabetes (HbA1c 10.1%) "
                        "and major depressive disorder. "
                        "Reports burning, tingling pain bilateral feet and lower legs, worse at night. "
                        "On duloxetine 60mg (treats both depression and neuropathic pain) and "
                        "gabapentin 300mg TID. "
                        "Currently on metformin 1000mg BID + glipizide 10mg BID."
                    ),
                    "objective": (
                        "BP 134/84, HR 78. Weight 214 lbs, BMI 31. "
                        "Monofilament testing: absent sensation bilateral feet (5/10 sites). "
                        "Vibration sense decreased. Deep tendon reflexes absent at ankles. "
                        "HbA1c 10.1%. eGFR 68. 10-foot walk mildly impaired."
                    ),
                    "assessment": (
                        "1. Type 2 DM with hyperglycemia – HbA1c 10.1%, add semaglutide. "
                        "2. Diabetic peripheral neuropathy – confirmed by monofilament and reflex loss. "
                        "Duloxetine and gabapentin continued. "
                        "[SUSPECT HCC: E11.40 diabetic neuropathy not coded – "
                        "clinical findings and medications clearly document this condition] "
                        "3. Major depressive disorder, moderate – partially responsive to duloxetine. "
                        "Continue current dose."
                    ),
                    "plan": (
                        "1. Add semaglutide 0.25mg SQ weekly, titrating to 1mg. "
                        "2. Continue metformin 1000mg BID, glipizide 10mg BID. "
                        "3. Gabapentin 300mg TID, duloxetine 60mg daily – continue. "
                        "4. Podiatry referral for diabetic foot care. "
                        "5. Code E11.40 on all future encounters. "
                        "6. HbA1c in 3 months. Return in 4 weeks."
                    ),
                },
                "medications": [
                    ("Metformin",   "1000 mg",  "BID"),
                    ("Glipizide",   "10 mg",    "BID"),
                    ("Semaglutide", "0.25 mg SQ","Weekly (titrating)"),
                    ("Gabapentin",  "300 mg",   "TID"),
                    ("Duloxetine",  "60 mg",    "Daily"),
                ],
            },
        ],
    },

    # ------------------------------------------------------------------
    # Patient 15: 80 y/o Male – Vascular disease with gangrene + Amputation
    # ------------------------------------------------------------------
    {
        "fname": "Harold", "lname": "Jenkins", "sex": "Male",
        "dob": date(1944, 3, 30), "city": "Memphis", "state": "TN",
        "suspect": None,
        "encounters": [
            {
                "date": datetime(2025, 10, 2, 11, 0),
                "reason": "Post-BKA wound management and vascular follow-up",
                "diagnoses": [
                    ("Z89.511","Acquired absence of right leg below knee"),
                    ("I70.261","Atherosclerosis of native arteries of extremities with gangrene, right leg"),
                    ("E11.52", "Type 2 diabetes with diabetic peripheral angiopathy with gangrene"),
                ],
                "soap": {
                    "subjective": (
                        "80-year-old male, 3 weeks post right below-knee amputation (BKA) for "
                        "diabetic foot with dry gangrene from critical limb ischemia. "
                        "Wound healing well per prosthetics team. "
                        "DM2 managed with insulin. Still has contralateral left leg PAD (ABI 0.62). "
                        "On clopidogrel, atorvastatin, insulin glargine, lisinopril."
                    ),
                    "objective": (
                        "BKA stump: well-healed, no erythema, no discharge. "
                        "Left leg: ABI 0.62, diminished pulses, no ulcers. "
                        "BP 132/80, HR 70. HbA1c 8.4%. "
                        "Creatinine 1.6, eGFR 44."
                    ),
                    "assessment": (
                        "1. Right BKA status post gangrene/CLI – stump healing well. "
                        "Prosthetic fitting initiated. PT for rehabilitation. "
                        "2. Atherosclerosis of lower extremities with prior gangrene – "
                        "aggressive risk factor management essential to protect remaining limb. "
                        "3. T2DM with peripheral angiopathy – HbA1c suboptimal. "
                        "Consider GLP-1 agonist if tolerated. "
                        "4. Left leg PAD monitoring – ABI 0.62, surveillance imaging in 6 months."
                    ),
                    "plan": (
                        "1. Clopidogrel 75mg daily – continue antiplatelet. "
                        "2. Atorvastatin 80mg QHS – high-intensity for lipid lowering. "
                        "3. Insulin glargine 28 units QHS – increase to 32 units. "
                        "4. Lisinopril 10mg daily – continue. "
                        "5. Vascular surgery: surveillance CTA left lower extremity in 6 months. "
                        "6. Prosthetics and PT 3x/week. Return in 3 weeks."
                    ),
                },
                "medications": [
                    ("Clopidogrel",    "75 mg",    "Daily"),
                    ("Atorvastatin",   "80 mg",    "QHS"),
                    ("Insulin glargine","32 units", "QHS subcutaneous"),
                    ("Lisinopril",     "10 mg",    "Daily"),
                ],
            },
        ],
    },

    # ------------------------------------------------------------------
    # Patient 16: 70 y/o Female – Malnutrition + Dementia + Stroke sequelae
    # ------------------------------------------------------------------
    {
        "fname": "Mildred", "lname": "Santos", "sex": "Female",
        "dob": date(1954, 7, 21), "city": "San Antonio", "state": "TX",
        "suspect": None,
        "encounters": [
            {
                "date": datetime(2025, 11, 14, 13, 0),
                "reason": "Long-term care management – malnutrition and post-stroke",
                "diagnoses": [
                    ("E43",   "Unspecified severe protein-calorie malnutrition"),
                    ("I69.351","Hemiplegia/hemiparesis following cerebral infarction, right dominant side"),
                    ("F01.50","Vascular dementia without behavioral disturbance"),
                ],
                "soap": {
                    "subjective": (
                        "70-year-old female, long-term care resident, with vascular dementia following "
                        "large left MCA stroke (2022), right-sided hemiplegia. "
                        "Currently tube-fed via PEG tube – poor oral intake. "
                        "Dietitian assessment: severe protein-calorie malnutrition (albumin 2.1). "
                        "Recurrent aspiration pneumonia (3 episodes this year)."
                    ),
                    "objective": (
                        "Non-ambulatory, right hemiplegia. MMSE not assessable. "
                        "Weight 94 lbs (BMI 17.2). "
                        "Albumin 2.1, prealbumin 9 mg/dL (severely low). "
                        "Hgb 10.4 (anemia of chronic disease). "
                        "PEG tube site: clean and intact."
                    ),
                    "assessment": (
                        "1. Severe protein-calorie malnutrition – albumin 2.1, prealbumin 9. "
                        "Optimize tube feeding formula and rate. Dietitian monthly monitoring. "
                        "2. Right hemiplegia post-stroke – ADL assistance required for all tasks. "
                        "3. Vascular dementia without behavioral disturbance – stable. "
                        "4. Recurrent aspiration pneumonia – maintain HOB >30 degrees, "
                        "speech therapy for compensatory strategies."
                    ),
                    "plan": (
                        "1. Increase PEG tube feeding to 1.5 cal/mL formula at 70 mL/hr x 18h. "
                        "2. Albumin recheck in 4 weeks. "
                        "3. Speech therapy dysphagia evaluation. "
                        "4. Aspiration precautions: HOB 30-45 degrees at all times. "
                        "5. Monthly facility rounds. Family updated on prognosis."
                    ),
                },
                "medications": [
                    ("Tube feeding formula", "1.5 cal/mL", "70 mL/hr via PEG"),
                    ("Aspirin",             "81 mg",      "Daily via PEG"),
                    ("Donepezil",           "10 mg",      "Daily via PEG"),
                ],
            },
        ],
    },

    # ------------------------------------------------------------------
    # Patient 17: 57 y/o Male – ALS (amyotrophic lateral sclerosis)
    # High RAF impact HCC 73
    # ------------------------------------------------------------------
    {
        "fname": "Gregory", "lname": "Thornton", "sex": "Male",
        "dob": date(1967, 1, 29), "city": "Denver", "state": "CO",
        "suspect": None,
        "encounters": [
            {
                "date": datetime(2025, 12, 5, 10, 0),
                "reason": "ALS – multidisciplinary clinic visit",
                "diagnoses": [
                    ("G12.21","Amyotrophic lateral sclerosis"),
                    ("J44.9", "Chronic obstructive pulmonary disease, unspecified"),
                ],
                "soap": {
                    "subjective": (
                        "57-year-old male with ALS diagnosed 18 months ago, now ALSFRS-R 28. "
                        "Uses BiPAP at night. Uses power wheelchair for mobility. "
                        "Dysarthria significant – uses speech-generating device. "
                        "PEG placed 4 months ago. "
                        "Also has concurrent COPD (former smoker). "
                        "On riluzole 50mg BID and edaravone 60mg IV x 10 days/month."
                    ),
                    "objective": (
                        "FVC 44% predicted (down from 62% 6 months ago). "
                        "Bulbar: severe dysarthria, tongue fasciculations. "
                        "UE strength 3/5 bilateral, LE strength 2/5. "
                        "BiPAP settings: IPAP 16, EPAP 8. "
                        "SpO2 94% on RA at rest."
                    ),
                    "assessment": (
                        "1. ALS – ALSFRS-R 28, progressing. FVC 44% – respiratory failure risk. "
                        "Riluzole and edaravone continued. Advance care planning updated. "
                        "2. Respiratory decline – BiPAP settings reviewed and optimized. "
                        "Pulmonology co-management. "
                        "3. COPD concurrent – FVC may be confounded; bronchodilators continued. "
                        "4. Nutrition: PEG tube adequate – weight stable at 168 lbs."
                    ),
                    "plan": (
                        "1. Riluzole 50mg BID – continue. "
                        "2. Edaravone 60mg IV cycle – continue monthly. "
                        "3. BiPAP upgrade settings to IPAP 18/EPAP 8 per respiratory therapy. "
                        "4. PT/OT – assistive device assessment. "
                        "5. Palliative care quarterly visits. "
                        "6. Return to ALS multidisciplinary clinic in 6 weeks."
                    ),
                },
                "medications": [
                    ("Riluzole",    "50 mg",   "BID"),
                    ("Edaravone",   "60 mg IV","Daily x10 days/month"),
                    ("Albuterol",   "2 puffs", "PRN"),
                    ("Tiotropium",  "18 mcg",  "Daily"),
                ],
            },
        ],
    },

    # ------------------------------------------------------------------
    # Patient 18: 40 y/o Female – Lupus + CKD stage 3 + Depression
    # SUSPECT: CKD from lupus nephritis not coded
    # ------------------------------------------------------------------
    {
        "fname": "Aaliyah", "lname": "Robinson", "sex": "Female",
        "dob": date(1984, 8, 8), "city": "Los Angeles", "state": "CA",
        "suspect": "CKD stage 3 from lupus nephritis not coded – on hydroxychloroquine + mycophenolate",
        "encounters": [
            {
                "date": datetime(2025, 10, 28, 14, 30),
                "reason": "SLE flare management",
                "diagnoses": [
                    ("M32.10","Systemic lupus erythematosus, organ or system involvement unspecified"),
                    ("F32.2", "Major depressive disorder, single episode, severe"),
                ],
                "soap": {
                    "subjective": (
                        "40-year-old female with SLE (lupus nephritis class III, in partial remission) "
                        "and severe major depression. "
                        "Presents with 3 weeks of arthralgias, facial rash, fatigue – SLE flare. "
                        "On hydroxychloroquine 400mg daily, mycophenolate 1g BID. "
                        "Creatinine trend: 1.4 → 1.6 → 1.9 over 6 months (eGFR now 42). "
                        "PHQ-9 score: 19."
                    ),
                    "objective": (
                        "Malar rash present. Alopecia noted. Synovitis bilateral wrists. "
                        "Creatinine 1.9, eGFR 42. 24hr urine protein 1.8g. "
                        "ANA 1:640, anti-dsDNA 1:80, low C3/C4. "
                        "PHQ-9 19 (severe), no SI currently."
                    ),
                    "assessment": (
                        "1. SLE flare with worsening lupus nephritis – creatinine 1.9 consistent with "
                        "CKD stage 3b (eGFR 42) from LN. Add pulse-dose steroids. "
                        "[SUSPECT HCC: N18.32 CKD stage 3b not coded in billing – "
                        "documented eGFR 42 from lupus nephritis clearly qualifies] "
                        "2. Major depressive disorder, severe – PHQ-9 19. "
                        "Start escitalopram, urgent psychiatry referral. "
                        "3. Lupus nephritis class III – increase mycophenolate to 1.5g BID, "
                        "add tacrolimus-based protocol."
                    ),
                    "plan": (
                        "1. Methylprednisolone 1g IV daily x 3 days, then prednisone 1mg/kg taper. "
                        "2. Mycophenolate 1.5g BID. Hydroxychloroquine 400mg daily – continue. "
                        "3. Escitalopram 10mg daily (titrate to 20mg in 2 weeks). "
                        "Urgent psychiatry referral. Safety plan discussed. "
                        "4. Add code N18.32 to active problem list and billing. "
                        "5. Nephrology referral for LN management protocol. "
                        "6. Return in 2 weeks."
                    ),
                },
                "medications": [
                    ("Hydroxychloroquine",  "400 mg", "Daily"),
                    ("Mycophenolate",       "1500 mg","BID"),
                    ("Prednisone",          "60 mg",  "Daily (tapering)"),
                    ("Escitalopram",        "10 mg",  "Daily"),
                ],
            },
        ],
    },
]

# ---------------------------------------------------------------------------
# SQL helpers
# ---------------------------------------------------------------------------

PROVIDER_ID = 1   # default provider in OpenEMR
FACILITY_ID  = 3  # default facility


def next_pid(cursor) -> int:
    cursor.execute("SELECT COALESCE(MAX(pid), 0) + 1 FROM patient_data;")
    return cursor.fetchone()[0]


def insert_patient(cursor, pid: int, p: dict) -> None:
    dob: date = p["dob"]
    cursor.execute(
        """
        INSERT INTO patient_data
            (pid, pubpid, fname, lname, DOB, sex, city, state,
             date, street, postal_code, country_code,
             phone_home, phone_cell, status)
        VALUES
            (%s,  %s,     %s,    %s,    %s,  %s,  %s,   %s,
             NOW(), '',   '00000',       'US',
             '555-000-0000', '555-000-0000', 'active')
        ON DUPLICATE KEY UPDATE lname = VALUES(lname);
        """,
        (pid, str(pid), p["fname"], p["lname"],
         dob.strftime("%Y-%m-%d"), p["sex"], p["city"], p["state"]),
    )


def next_encounter_id(cursor) -> int:
    cursor.execute("SELECT COALESCE(MAX(encounter), 0) + 1 FROM form_encounter;")
    return cursor.fetchone()[0]


def insert_encounter(cursor, enc_id: int, pid: int, enc: dict) -> None:
    cursor.execute(
        """
        INSERT INTO form_encounter
            (encounter, pid, date, reason, facility_id, provider_id, class_code, pc_catid)
        VALUES (%s, %s, %s, %s, %s, %s, 'AMB', 5)
        ON DUPLICATE KEY UPDATE reason = VALUES(reason);
        """,
        (enc_id, pid, enc["date"].strftime("%Y-%m-%d %H:%M:%S"),
         enc["reason"], FACILITY_ID, PROVIDER_ID),
    )


def insert_billing(cursor, pid: int, enc_id: int, enc_date: datetime,
                   diagnoses: list[tuple[str, str]]) -> None:
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
             code, code_text[:255], PROVIDER_ID),
        )


def next_soap_id(cursor) -> int:
    cursor.execute("SELECT COALESCE(MAX(id), 0) + 1 FROM form_soap;")
    return cursor.fetchone()[0]


def insert_soap(cursor, soap_id: int, pid: int, enc_date: datetime,
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
         soap["subjective"], soap["objective"],
         soap["assessment"], soap["plan"]),
    )


def insert_forms_registry(cursor, pid: int, enc_id: int,
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


def insert_prescription(cursor, pid: int, enc_id: int,
                         enc_date: datetime, med: tuple[str, str, str]) -> None:
    drug, dosage, sig = med
    enc_date_str = enc_date.strftime("%Y-%m-%d %H:%M:%S")
    enc_date_d   = enc_date.strftime("%Y-%m-%d")
    cursor.execute(
        """
        INSERT INTO prescriptions
            (patient_id, encounter, drug, dosage, note,
             date_added, active, provider_id,
             txDate, usage_category_title, request_intent_title)
        VALUES (%s, %s, %s, %s, %s, %s, 1, %s, %s, %s, %s)
        """,
        (pid, enc_id, drug[:150], dosage[:100], sig,
         enc_date_str,
         PROVIDER_ID,
         enc_date_d,
         "Chronic",     # usage_category_title – required NOT NULL
         "order"),      # request_intent_title – required NOT NULL
    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    log.info("Connecting to OpenEMR MySQL at 127.0.0.1:3309 …")
    try:
        conn = mysql.connector.connect(**DB_CONFIG)
    except MySQLError as exc:
        log.error("Cannot connect: %s", exc)
        sys.exit(1)

    cursor = conn.cursor()
    patients_created = 0
    encounters_created = 0
    billing_rows = 0
    soap_rows = 0
    rx_rows = 0

    try:
        for p in PATIENTS:
            # --- patient_data ---
            pid = next_pid(cursor)
            insert_patient(cursor, pid, p)
            patients_created += 1

            suspect_flag = f"  [SUSPECT: {p['suspect']}]" if p["suspect"] else ""
            log.info(
                "  Patient %d: %s %s (DOB %s)%s",
                pid, p["fname"], p["lname"],
                p["dob"].strftime("%Y-%m-%d"), suspect_flag,
            )

            for enc in p["encounters"]:
                # --- form_encounter ---
                enc_id = next_encounter_id(cursor)
                insert_encounter(cursor, enc_id, pid, enc)
                encounters_created += 1

                # --- billing (ICD-10) ---
                insert_billing(cursor, pid, enc_id, enc["date"], enc["diagnoses"])
                billing_rows += len(enc["diagnoses"])

                # --- form_soap + forms registry ---
                soap_id = next_soap_id(cursor)
                insert_soap(cursor, soap_id, pid, enc["date"], enc["soap"])
                insert_forms_registry(cursor, pid, enc_id, soap_id, enc["date"])
                soap_rows += 1

                # --- prescriptions ---
                for med in enc.get("medications", []):
                    insert_prescription(cursor, pid, enc_id, enc["date"], med)
                    rx_rows += 1

            conn.commit()

    except MySQLError as exc:
        conn.rollback()
        log.error("MySQL error during seeding: %s", exc)
        raise
    finally:
        cursor.close()
        conn.close()

    log.info("Seeding complete:")
    log.info("  Patients created   : %d", patients_created)
    log.info("  Encounters created : %d", encounters_created)
    log.info("  Billing codes      : %d", billing_rows)
    log.info("  SOAP notes         : %d", soap_rows)
    log.info("  Prescriptions      : %d", rx_rows)
    suspects = [p for p in PATIENTS if p["suspect"]]
    log.info("  Suspect patients   : %d", len(suspects))
    for p in suspects:
        log.info("    %s %s – %s", p["fname"], p["lname"], p["suspect"])


if __name__ == "__main__":
    main()
