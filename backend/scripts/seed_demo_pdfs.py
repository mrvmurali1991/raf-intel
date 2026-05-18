#!/usr/bin/env python3
"""
Synthetic Clinical PDF Seeder
==============================
Generates 10 realistic SOAP clinical notes as PDFs and inserts matching rows
into openemr.documents so the Gemini vision ingest pipeline can find them.

Usage
-----
    python backend/scripts/seed_demo_pdfs.py \\
        --tenant 1 \\
        --patients 3,7,8,12,14,22,23,25,30,35

Each run is idempotent: if a document with the same url_filepath already
exists in openemr.documents it is not inserted again, and the PDF is not
regenerated.

PDF sizes are kept small (< 50 KB) by using Helvetica only, no embedded
images, and concise but clinically realistic content.

Constraints
-----------
- reportlab is lazy-imported so the module is importable even if not installed.
- All filesystem paths are absolute.
- Output directory: /tmp/raf-demo-pdfs/
- Each document row has: pid, url, url_filepath, mimetype, owner, date
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
from datetime import date
from pathlib import Path
from typing import Any

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
)
log = logging.getLogger("seed_demo_pdfs")

# ---------------------------------------------------------------------------
# Clinical note templates — one per HCC
# ---------------------------------------------------------------------------

CLINICAL_NOTES: list[dict[str, Any]] = [
    {
        "filename": "cardiology_consult_2026-03-15.pdf",
        "title": "Cardiology Consult — CHF (HCC 85)",
        "date": "2026-03-15",
        "icd10": "I50.22",
        "hcc": "HCC85",
        "pages": 2,
        "note": """\
CARDIOLOGY CONSULTATION NOTE
Date: 2026-03-15    Referring Provider: Dr. Anne Reyes, MD
Patient: [PATIENT]    DOB: [DOB]    MRN: [PID]

REASON FOR VISIT: Dyspnea on exertion, bilateral lower-extremity edema.

HISTORY OF PRESENT ILLNESS:
The patient is a 68-year-old male presenting with a 6-week history of progressive
dyspnea on exertion, now occurring with minimal activity. He reports orthopnea
requiring 3 pillows and paroxysmal nocturnal dyspnea twice in the past month.
Bilateral ankle swelling has worsened over the same period.

PAST MEDICAL HISTORY:
- Ischemic cardiomyopathy, diagnosed 2019
- Type 2 diabetes mellitus (E11.9)
- Hypertension (I10)
- Hyperlipidemia

MEDICATIONS:
1. Carvedilol 25 mg BID for heart failure
2. Lisinopril 10 mg daily for heart failure / hypertension
3. Furosemide 40 mg daily for volume management
4. Spironolactone 25 mg daily for HFrEF
5. Sacubitril/Valsartan 97/103 mg BID — titrated last visit
6. Metformin 1000 mg BID for diabetes

VITALS:
BP: 128/78 mmHg    HR: 82 bpm    Weight: 214 lbs (up 8 lbs from last month)
O2 Sat: 93% on room air    RR: 18/min    Temp: 98.4 F

PHYSICAL EXAMINATION:
General: Mild respiratory distress. Speaks in full sentences.
Cardiovascular: Regular rate and rhythm, S3 gallop present, JVD at 8 cm.
Lungs: Bibasilar crackles consistent with pulmonary congestion.
Extremities: 2+ pitting edema bilateral ankles.

LABORATORY / DIAGNOSTICS:
- BNP: 1,420 pg/mL (markedly elevated; prior 680 pg/mL 3 months ago)
- Creatinine: 1.4 mg/dL    Na: 138 mEq/L    K: 4.2 mEq/L
- Echocardiogram (2026-03-10): Left ventricular ejection fraction (LVEF) 25%.
  Moderately dilated LV. Moderate mitral regurgitation. Diastolic dysfunction Grade III.

ASSESSMENT:
I50.22 - Chronic systolic (congestive) heart failure — decompensated, NYHA Class III
  MONITORING: BNP trending from 680 to 1,420 pg/mL. Echo showing EF 25% on 2026-03-10.
  EVALUATION: Clinical picture consistent with decompensated HFrEF; S3 gallop, JVD elevated.
  ASSESSMENT: Volume overloaded; poor response to current diuresis; EF severely reduced.
  TREATMENT: Increase furosemide to 80 mg daily. Consider IV diuresis if no improvement
    in 48 hours. Continue GDMT — carvedilol, sacubitril/valsartan, spironolactone.
    Refer to advanced heart failure clinic for LVAD evaluation.

PLAN:
1. Increase furosemide 80 mg daily; daily weights, low-sodium diet reinforcement.
2. Repeat BMP in 3 days.
3. Repeat echocardiogram in 6 weeks.
4. Follow-up cardiology in 2 weeks or sooner if symptoms worsen.
5. Referral to advanced heart failure program placed today.

Electronically signed: Dr. Marcus Chen, MD, FACC
""",
    },
    {
        "filename": "endo_followup_2026-04-02.pdf",
        "title": "Endocrinology Follow-up — DM with Complications (HCC 18)",
        "date": "2026-04-02",
        "icd10": "E11.65",
        "hcc": "HCC18",
        "pages": 2,
        "note": """\
ENDOCRINOLOGY FOLLOW-UP NOTE
Date: 2026-04-02    Provider: Dr. Priya Nair, MD, FACE
Patient: [PATIENT]    DOB: [DOB]    MRN: [PID]

REASON FOR VISIT: Diabetes management; HbA1c review.

HISTORY OF PRESENT ILLNESS:
Patient is a 55-year-old female with a 12-year history of Type 2 diabetes mellitus
with multiple complications. She presents today for follow-up after laboratory
results showed persistently uncontrolled glycemia. She reports frequent episodes
of hyperglycemia in the 280-350 mg/dL range per home glucometer logs.

PAST MEDICAL HISTORY:
- Type 2 diabetes mellitus with hyperglycemia (E11.65) — 12 years
- Diabetic peripheral neuropathy (E11.40) — confirmed nerve conduction study 2024
- Early diabetic nephropathy — microalbuminuria on two consecutive specimens
- Hypertension (I10)

MEDICATIONS:
1. Metformin 1000 mg BID for type 2 diabetes
2. Semaglutide 1.0 mg weekly (Ozempic) for type 2 diabetes
3. Lisinopril 5 mg daily for diabetic nephropathy / hypertension

VITALS:
BP: 138/86 mmHg    HR: 78 bpm    Weight: 187 lbs    BMI: 31.2 kg/m2
O2 Sat: 98%

LABORATORY RESULTS (drawn 2026-03-28):
HbA1c: 9.2% (target <7.0%; prior 8.4% six months ago — worsening)
Fasting glucose: 218 mg/dL
Creatinine: 1.1 mg/dL    eGFR: 64 mL/min/1.73m2
Microalbuminuria: 92 mg/g creatinine (moderate albuminuria)
LDL: 112 mg/dL    HDL: 44 mg/dL    Triglycerides: 198 mg/dL

ASSESSMENT:
E11.65 - Type 2 diabetes mellitus with hyperglycemia — uncontrolled
  MONITORING: HbA1c 9.2% on 2026-03-28; worsening from 8.4% six months ago.
    Home logs show BG 280-350 mg/dL consistently.
  EVALUATION: Inadequate glycemic control on dual-agent oral/injectable therapy.
    Evidence of early nephropathy (microalbuminuria 92 mg/g) and neuropathy.
  ASSESSMENT: HbA1c 9.2% indicates significantly uncontrolled diabetes with
    active complications including hyperglycemia, nephropathy, and neuropathy.
  TREATMENT: Add basal insulin glargine 10 units nightly; titrate by 2U every
    3 days targeting fasting BG <130. Increase semaglutide to 2.0 mg weekly.
    Start atorvastatin 40 mg for elevated triglycerides/LDL. Nephrology referral.

PLAN:
1. Start insulin glargine (Lantus) 10 units nightly; patient education provided.
2. Increase semaglutide to 2.0 mg weekly after 4-week titration.
3. Atorvastatin 40 mg nightly for lipid management.
4. Diabetic eye exam referral placed.
5. Nephrology consultation for progressive microalbuminuria.
6. Follow-up in 6 weeks with repeat fasting glucose and 4-point glucose log.

Electronically signed: Dr. Priya Nair, MD, FACE
""",
    },
    {
        "filename": "nephrology_consult_2026-02-10.pdf",
        "title": "Nephrology Consult — CKD Stage 4 (HCC 137)",
        "date": "2026-02-10",
        "icd10": "N18.4",
        "hcc": "HCC137",
        "pages": 2,
        "note": """\
NEPHROLOGY CONSULTATION NOTE
Date: 2026-02-10    Provider: Dr. Samuel Okafor, MD, FASN
Patient: [PATIENT]    DOB: [DOB]    MRN: [PID]

REASON FOR VISIT: Progressive CKD evaluation and management.

HISTORY OF PRESENT ILLNESS:
Patient is a 72-year-old male referred for worsening renal function. Baseline
creatinine was 1.8 mg/dL two years ago; now 3.1 mg/dL. He reports fatigue,
mild ankle swelling, and nocturia 3-4 times nightly. No hematuria or dysuria.

PAST MEDICAL HISTORY:
- Hypertensive nephropathy (I12.9) — primary etiology of CKD
- Type 2 diabetes mellitus (E11.9)
- Anemia of chronic kidney disease (D63.1)
- Hypertension (I10)

MEDICATIONS:
1. Amlodipine 10 mg daily for hypertension
2. Furosemide 20 mg daily for volume management
3. Sodium bicarbonate 650 mg TID for metabolic acidosis
4. Epoetin alfa 10,000 units SC weekly for CKD anemia
5. Sevelamer 800 mg TID with meals for hyperphosphatemia

VITALS:
BP: 152/94 mmHg    HR: 76 bpm    Weight: 198 lbs    Temp: 98.2 F
O2 Sat: 96%    RR: 16/min

LABORATORY RESULTS (2026-02-05):
Creatinine: 3.1 mg/dL    BUN: 54 mg/dL
eGFR: 24 mL/min/1.73m2 (CKD Stage G4, severely reduced)
Potassium: 5.3 mEq/L    Sodium: 137 mEq/L    Bicarbonate: 18 mEq/L
Phosphorus: 5.8 mg/dL    PTH: 312 pg/mL (elevated secondary hyperparathyroidism)
Hgb: 9.4 g/dL    Hematocrit: 28%

ASSESSMENT:
N18.4 - Chronic kidney disease, stage 4 (severe) — eGFR 24 mL/min/1.73m2
  MONITORING: eGFR declined from 38 six months ago to 24 today; creatinine 3.1.
    Hyperphosphatemia and secondary hyperparathyroidism developing.
  EVALUATION: Stage G4 CKD with metabolic complications — acidosis, anemia,
    hyperphosphatemia. Trajectory suggests ESRD within 12-18 months.
  ASSESSMENT: Rapid progression likely from poorly controlled hypertension
    and diabetes. AV fistula planning should begin now.
  TREATMENT: Optimize BP to <130/80; add losartan 50 mg for reno-protection.
    Increase sevelamer dosing. Start calcitriol 0.25 mcg daily. ESRD education.

PLAN:
1. Add losartan 50 mg daily — renoprotection, hold if K >5.5.
2. Nephrology education session for ESRD/dialysis options.
3. Vascular surgery referral for AV fistula creation.
4. Low-phosphorus, low-potassium renal diet consult.
5. Return in 6 weeks with repeat BMP, CBC, phosphorus, PTH.

Electronically signed: Dr. Samuel Okafor, MD, FASN
""",
    },
    {
        "filename": "cardiology_arrhythmia_2026-04-22.pdf",
        "title": "Cardiology — Chronic Atrial Fibrillation (HCC 96)",
        "date": "2026-04-22",
        "icd10": "I48.11",
        "hcc": "HCC96",
        "pages": 1,
        "note": """\
CARDIOLOGY FOLLOW-UP NOTE
Date: 2026-04-22    Provider: Dr. Lisa Huang, MD, FHRS
Patient: [PATIENT]    DOB: [DOB]    MRN: [PID]

REASON FOR VISIT: Chronic atrial fibrillation management.

HISTORY OF PRESENT ILLNESS:
Patient is a 74-year-old male with a 5-year history of persistent atrial
fibrillation, cardioverted twice without sustained sinus rhythm. He presents
for rate-control and anticoagulation follow-up. He denies palpitations,
presyncope, or TIA symptoms. INR in therapeutic range last month.

PAST MEDICAL HISTORY:
- Chronic persistent atrial fibrillation (I48.11)
- Hypertension (I10)
- Prior CVA (I63.9) — 2022
- CHA2DS2-VASc score: 5

MEDICATIONS:
1. Metoprolol succinate 100 mg daily for rate control
2. Apixaban 5 mg BID for anticoagulation (AF + CVA history)
3. Amlodipine 5 mg daily for hypertension

VITALS:
BP: 136/82 mmHg    HR: 74 bpm (irregularly irregular)    Weight: 182 lbs
O2 Sat: 97%

EKG (today): Atrial fibrillation, ventricular rate 74 bpm. No ST changes.

ASSESSMENT:
I48.11 - Longstanding persistent atrial fibrillation — rate controlled
  MONITORING: Ventricular rate 74 bpm on EKG today. INR therapeutic last month.
    CHA2DS2-VASc score 5 — high stroke risk.
  EVALUATION: Adequate rate control achieved. No thromboembolic events since
    starting apixaban.
  ASSESSMENT: Stable chronic AF. Rhythm control not pursued given prior
    cardioversion failures and patient preference.
  TREATMENT: Continue apixaban 5 mg BID indefinitely. Maintain metoprolol
    succinate for rate control. Annual echocardiogram.

PLAN:
1. Continue apixaban 5 mg BID — no dose change.
2. Continue metoprolol succinate 100 mg daily.
3. Echocardiogram in 6 months.
4. Return 3 months for routine follow-up.

Electronically signed: Dr. Lisa Huang, MD, FHRS
""",
    },
    {
        "filename": "mental_health_followup_2026-03-30.pdf",
        "title": "Mental Health — Major Depressive Disorder (HCC 155)",
        "date": "2026-03-30",
        "icd10": "F33.1",
        "hcc": "HCC155",
        "pages": 1,
        "note": """\
MENTAL HEALTH FOLLOW-UP NOTE
Date: 2026-03-30    Provider: Dr. Karen Foster, MD, Psychiatry
Patient: [PATIENT]    DOB: [DOB]    MRN: [PID]

REASON FOR VISIT: Medication management — major depressive disorder.

HISTORY OF PRESENT ILLNESS:
Patient is a 49-year-old female with recurrent major depressive disorder, moderate
severity, with her most recent episode ongoing for 8 months. She reports persistent
low mood, anhedonia, hypersomnia, and difficulty concentrating that affect daily
functioning. PHQ-9 score today: 16/27 (moderate-to-severe depression).
No suicidal ideation. No psychotic features.

PAST MEDICAL HISTORY:
- Major depressive disorder, recurrent, moderate (F33.1)
- Generalized anxiety disorder (F41.1)
- Hypothyroidism (E03.9)

MEDICATIONS:
1. Sertraline 100 mg daily for MDD / GAD
2. Bupropion XL 300 mg daily for MDD (augmentation)
3. Levothyroxine 75 mcg daily for hypothyroidism

VITALS:
BP: 118/72 mmHg    HR: 70 bpm    Weight: 158 lbs    BMI: 27.1 kg/m2
TSH: 2.1 mIU/L (within normal range)

ASSESSMENT:
F33.1 - Major depressive disorder, recurrent episode, moderate
  MONITORING: PHQ-9 score 16 today; prior score 18 at last visit — slight improvement.
    Sleep diary shows hypersomnia (10-12 hrs/night). GAD-7 score: 14 (moderate anxiety).
  EVALUATION: Inadequate response to current dual antidepressant regimen at 8 months.
    Functional impairment in occupational and social domains.
  ASSESSMENT: Moderate MDD with partial response; anxiety comorbidity adding to burden.
    No safety concerns. Thyroid function stable.
  TREATMENT: Increase sertraline to 150 mg. Add aripiprazole 2 mg (adjunctive).
    Refer to cognitive behavioral therapy — biweekly sessions. Sleep hygiene counseling.

PLAN:
1. Increase sertraline to 150 mg daily.
2. Start aripiprazole 2 mg daily — monitor for akathisia.
3. CBT referral placed with licensed therapist.
4. Follow-up psychiatry in 4 weeks.
5. Emergency plan reviewed; patient has crisis line number.

Electronically signed: Dr. Karen Foster, MD
""",
    },
    {
        "filename": "oncology_followup_2026-01-15.pdf",
        "title": "Oncology — Breast Cancer History (HCC 12)",
        "date": "2026-01-15",
        "icd10": "Z85.3",
        "hcc": "HCC12",
        "pages": 2,
        "note": """\
ONCOLOGY FOLLOW-UP NOTE
Date: 2026-01-15    Provider: Dr. Angela Moore, MD, FASCO
Patient: [PATIENT]    DOB: [DOB]    MRN: [PID]

REASON FOR VISIT: Breast cancer surveillance — 3-year post-treatment follow-up.

HISTORY OF PRESENT ILLNESS:
Patient is a 62-year-old female with a personal history of invasive ductal carcinoma
of the right breast, Stage IIB (T2N1M0), ER+/PR+/HER2-, diagnosed March 2023.
She completed lumpectomy, adjuvant chemotherapy (AC-T), and radiation therapy.
Now on anastrozole for hormone suppression. Presents for routine surveillance.
No new breast symptoms, no bone pain, no neurological complaints.

PAST MEDICAL HISTORY:
- Personal history of malignant neoplasm of breast (Z85.3) — IDC, right breast, 2023
- Chemotherapy-induced peripheral neuropathy (G62.0) — improving
- Osteopenia (M85.80) — DEXA 2025: T-score -1.8 lumbar spine
- Hypertension (I10)

MEDICATIONS:
1. Anastrozole 1 mg daily for ER+ breast cancer hormone suppression
2. Calcium carbonate 1200 mg daily for bone health
3. Vitamin D3 2000 IU daily for bone health
4. Amlodipine 5 mg for hypertension

VITALS:
BP: 124/78 mmHg    HR: 68 bpm    Weight: 154 lbs    BMI: 26.3 kg/m2
O2 Sat: 99%

LABORATORY RESULTS (2026-01-10):
CBC: WBC 5.4, Hgb 12.8, Plt 198
CA 15-3: 18 U/mL (within normal limits; prior 16 U/mL)
LFTs: Normal
Calcium: 9.1 mg/dL

IMAGING (2026-01-08):
Bilateral diagnostic mammogram: No suspicious mass or calcification.
Ultrasound right breast: No suspicious lesion. Post-surgical changes stable.

ASSESSMENT:
Z85.3 - Personal history of malignant neoplasm of breast — no evidence of recurrence
  MONITORING: CA 15-3 stable at 18; bilateral mammogram negative 2026-01-08.
    Clinical breast exam today: no masses, no lymphadenopathy, no skin changes.
  EVALUATION: 3 years post-treatment, currently NED (no evidence of disease).
    Tolerating anastrozole well with mild joint stiffness.
  ASSESSMENT: Excellent response to treatment; surveillance imaging and markers reassuring.
    Continued annual mammogram and aromatase inhibitor therapy for planned 10-year course.
  TREATMENT: Continue anastrozole indefinitely. Annual mammogram. DEXA in 12 months.
    Consider zoledronic acid infusion if T-score worsens.

PLAN:
1. Continue anastrozole 1 mg daily — year 3 of 10.
2. Annual mammogram scheduled for January 2027.
3. DEXA bone density scan in 12 months.
4. Physical therapy for arthralgia from anastrozole.
5. Return to oncology in 6 months.

Electronically signed: Dr. Angela Moore, MD, FASCO
""",
    },
    {
        "filename": "pulmonology_consult_2026-02-20.pdf",
        "title": "Pulmonology — COPD with Exacerbations (HCC 111)",
        "date": "2026-02-20",
        "icd10": "J44.1",
        "hcc": "HCC111",
        "pages": 2,
        "note": """\
PULMONOLOGY CONSULTATION NOTE
Date: 2026-02-20    Provider: Dr. Robert Torres, MD, FCCP
Patient: [PATIENT]    DOB: [DOB]    MRN: [PID]

REASON FOR VISIT: Acute exacerbation of COPD; pulmonary management.

HISTORY OF PRESENT ILLNESS:
Patient is a 71-year-old male, 60 pack-year smoking history (quit 2018), presenting
with worsening dyspnea, increased sputum production (green, purulent), and decreased
exercise tolerance over the past 10 days. He reports two hospitalizations for COPD
exacerbations in the past 12 months. Uses rescue inhaler 4-5 times daily.

PAST MEDICAL HISTORY:
- COPD, severe, with acute exacerbation (J44.1) — GOLD Stage III
- Chronic hypoxic respiratory failure on home oxygen 2L/min
- Cor pulmonale (I27.81)
- Hypertension (I10)
- 60 pack-year tobacco history (quit 2018)

MEDICATIONS:
1. Tiotropium inhaler 18 mcg daily (Spiriva) for COPD
2. Fluticasone/salmeterol 500/50 mcg BID for COPD
3. Albuterol MDI 2 puffs Q4H PRN for rescue
4. Prednisone 40 mg daily x 5 days (current exacerbation)
5. Azithromycin 250 mg daily x 5 days (empirical antibiotic)
6. Home O2 2L/min continuous

VITALS:
BP: 142/88 mmHg    HR: 96 bpm    RR: 24/min    Temp: 99.8 F
O2 Sat: 88% on room air; 93% on 2L NC    Weight: 167 lbs

PULMONARY FUNCTION TESTS (2025-11-15):
FEV1: 42% of predicted (severe obstruction)
FEV1/FVC: 0.54 (obstructive pattern)
Post-bronchodilator FEV1: 46% (minimal reversibility)
DLCO: 38% of predicted (emphysema)

ASSESSMENT:
J44.1 - COPD with acute exacerbation
  MONITORING: O2 sat 88% on room air today; FEV1 42% predicted on last PFT.
    Two prior hospitalizations in 12 months for exacerbations.
  EVALUATION: Infectious exacerbation (purulent sputum, low-grade fever).
    Current GOLD classification Stage III-D (high symptom burden, frequent exacerbations).
  ASSESSMENT: Frequent exacerbator phenotype; meeting criteria for triple therapy.
    Cor pulmonale adds cardiovascular risk.
  TREATMENT: Complete prednisone 40 mg x 5 days. Complete azithromycin x 5 days.
    Upgrade to triple inhaled therapy: fluticasone/umeclidinium/vilanterol (Trelegy).

PLAN:
1. Switch to Trelegy Ellipta 100/62.5/25 mcg once daily — triple therapy.
2. Pulmonary rehabilitation referral.
3. Sputum culture — adjust antibiotics based on results.
4. Chest CT to rule out COPD-related malignancy (current smoker history).
5. Follow-up in 4 weeks; hospitalization if not improved in 48 hours.

Electronically signed: Dr. Robert Torres, MD, FCCP
""",
    },
    {
        "filename": "vascular_consult_2026-03-05.pdf",
        "title": "Vascular Surgery — Peripheral Vascular Disease (HCC 108)",
        "date": "2026-03-05",
        "icd10": "I70.219",
        "hcc": "HCC108",
        "pages": 1,
        "note": """\
VASCULAR SURGERY CONSULTATION NOTE
Date: 2026-03-05    Provider: Dr. Carlos Mendez, MD, RVT
Patient: [PATIENT]    DOB: [DOB]    MRN: [PID]

REASON FOR VISIT: Lower extremity claudication; peripheral arterial disease evaluation.

HISTORY OF PRESENT ILLNESS:
Patient is a 69-year-old male with progressive calf claudication bilaterally, left
greater than right, for 18 months. Pain onset at 1-2 blocks walking; resolves with
rest within 5 minutes (Fontaine Stage IIb). No rest pain or ulceration.

PAST MEDICAL HISTORY:
- Peripheral arterial disease, bilateral lower extremities (I70.219)
- Type 2 diabetes mellitus (E11.9)
- Hypertension (I10)
- 45 pack-year smoking history (active smoker — 1 PPD)

MEDICATIONS:
1. Cilostazol 100 mg BID for claudication
2. Aspirin 81 mg daily (antiplatelet)
3. Atorvastatin 80 mg daily for PAD / hyperlipidemia
4. Metformin 1000 mg BID for diabetes
5. Lisinopril 10 mg daily for hypertension

VITALS:
BP: 144/92 mmHg (right arm)    BP: 138/88 (left arm)    HR: 82 bpm
ABI (right): 0.61    ABI (left): 0.54 (severe arterial insufficiency)
O2 Sat: 97%

VASCULAR DUPLEX ULTRASOUND (2026-02-28):
Left superficial femoral artery: 70-80% stenosis at Hunter's canal.
Right SFA: 50-60% stenosis, mid-segment.
Left popliteal: Patent; triphasic flow preserved distal to SFA stenosis.

ASSESSMENT:
I70.219 - Atherosclerosis of native arteries of bilateral extremities, with claudication
  MONITORING: ABI 0.54 left (severe), 0.61 right. Duplex shows 70-80% left SFA stenosis.
  EVALUATION: Fontaine IIb claudication limiting activities of daily living.
    Active tobacco use continues to accelerate atherosclerotic progression.
  ASSESSMENT: Hemodynamically significant PAD; revascularization candidate.
    Risk factor modification critical — smoking cessation highest priority.
  TREATMENT: Structured exercise program (supervised). Smoking cessation referral
    urgent. Plan for left SFA percutaneous transluminal angioplasty +/- stenting.

PLAN:
1. Smoking cessation referral — varenicline prescription.
2. Supervised exercise therapy referral.
3. Catheter-directed angiography left lower extremity — schedule in 3 weeks.
4. Continue aspirin 81 mg and atorvastatin 80 mg indefinitely.
5. Return in 6 weeks post-procedure.

Electronically signed: Dr. Carlos Mendez, MD, RVT
""",
    },
    {
        "filename": "hospital_discharge_2026-04-15.pdf",
        "title": "Hospital Discharge — Sepsis Hospitalization (HCC 2)",
        "date": "2026-04-15",
        "icd10": "A41.9",
        "hcc": "HCC2",
        "pages": 2,
        "note": """\
HOSPITAL DISCHARGE SUMMARY
Admission Date: 2026-04-08    Discharge Date: 2026-04-15
Attending Physician: Dr. James Liu, MD, FACP
Patient: [PATIENT]    DOB: [DOB]    MRN: [PID]

PRINCIPAL DIAGNOSIS: Sepsis, unspecified organism (A41.9)
SECONDARY DIAGNOSES: Septic shock, acute kidney injury (AKI), type 2 diabetes

REASON FOR ADMISSION:
Patient is a 78-year-old male admitted via ED with fever (T 39.8°C), tachycardia
(HR 118), hypotension (BP 82/54), confusion, and WBC 22,400/uL. Lactate on
arrival: 4.8 mmol/L. Source identified as left lower lobe pneumonia on CXR.

HOSPITAL COURSE:
Day 1-2: ICU admission. SOFA score 10 on admission. Broad-spectrum antibiotics
initiated (vancomycin + piperacillin-tazobactam). Fluid resuscitation 4L NS.
Norepinephrine required for vasopressor support 18 hours.
Day 3-4: Vasopressors weaned. Blood cultures: Streptococcus pneumoniae bacteremia.
Antibiotics narrowed to ceftriaxone 2g IV daily. Creatinine peaked at 2.8 mg/dL
(AKI Stage 2 — baseline 1.1).
Day 5-7: Transferred to general medicine floor. Improving respiratory status.
  Creatinine trending down to 1.6 mg/dL. Tolerating oral diet. Ambulating with PT.
Day 7 (today): Discharge to home with oral step-down antibiotics. Home oxygen not required.

DISCHARGE CONDITION: Improved but guarded.

VITALS AT DISCHARGE:
BP: 118/72 mmHg    HR: 88 bpm    Temp: 37.2°C    O2 Sat: 95% RA
WBC: 12,800/uL    Creatinine: 1.6 mg/dL    Lactate: 1.2 mmol/L (normalized)

ASSESSMENT:
A41.9 - Sepsis, unspecified organism — resolving, bacteremic
  MONITORING: SOFA score 10 on admission, improving daily. WBC 22,400 -> 12,800.
    Creatinine trending down from peak 2.8 to 1.6 mg/dL at discharge.
  EVALUATION: Pneumococcal bacteremia with septic shock; ICU level care required.
    AKI resolving. No end-organ damage persisting at discharge.
  ASSESSMENT: Survived septic shock from pneumococcal pneumonia-bacteremia.
    Full recovery expected; close outpatient follow-up essential.
  TREATMENT: Amoxicillin-clavulanate 875/125 mg BID x 7 days (step-down).
    PCV20 (pneumococcal vaccine) administered today.

DISCHARGE MEDICATIONS:
1. Amoxicillin-clavulanate 875/125 mg BID x 7 days
2. Resume home medications (metformin, lisinopril, atorvastatin)
3. Continue fluid intake 2L/day; low-sodium diet

DISCHARGE INSTRUCTIONS:
- Return to ED immediately for fever >38.5°C, chest pain, worsening SOB.
- Primary care follow-up in 7 days.
- Infectious disease follow-up in 14 days.
- Repeat metabolic panel in 1 week to confirm AKI resolution.

FOLLOW-UP: Primary care within 7 days. Infectious Disease in 14 days.

Electronically signed: Dr. James Liu, MD, FACP
""",
    },
    {
        "filename": "rheumatology_consult_2026-04-10.pdf",
        "title": "Rheumatology — Rheumatoid Arthritis (HCC 40)",
        "date": "2026-04-10",
        "icd10": "M05.79",
        "hcc": "HCC40",
        "pages": 2,
        "note": """\
RHEUMATOLOGY CONSULTATION NOTE
Date: 2026-04-10    Provider: Dr. Susan Park, MD, FACR
Patient: [PATIENT]    DOB: [DOB]    MRN: [PID]

REASON FOR VISIT: Rheumatoid arthritis follow-up; disease activity assessment.

HISTORY OF PRESENT ILLNESS:
Patient is a 58-year-old female with seropositive rheumatoid arthritis diagnosed
in 2018. She presents with worsening morning stiffness (>90 minutes), bilateral
PIP and MCP joint swelling, and decreased grip strength over the past 6 weeks.
DAS28-CRP score today: 5.1 (high disease activity). She completed methotrexate
15 mg weekly without adequate response after 12 months of therapy.

PAST MEDICAL HISTORY:
- Rheumatoid arthritis, seropositive, with other organs/systems involvement (M05.79)
- RA interstitial lung disease — CT chest 2025: mild UIP pattern
- Osteoporosis (M81.0) — T-score -2.7 femoral neck
- Hypertension (I10)

MEDICATIONS:
1. Methotrexate 15 mg PO weekly for RA
2. Folic acid 1 mg daily (methotrexate supplementation)
3. Prednisone 10 mg daily (bridging therapy)
4. Alendronate 70 mg weekly for osteoporosis
5. Hydroxychloroquine 200 mg BID for RA

VITALS:
BP: 132/84 mmHg    HR: 74 bpm    Weight: 148 lbs    BMI: 25.4 kg/m2
Temperature: 98.6 F    O2 Sat: 96%

JOINT EXAMINATION:
- Bilateral MCP 2-4 joints: Active synovitis, warmth, tenderness
- Bilateral PIP 2-5: Swelling, decreased range of motion
- Bilateral wrists: Swelling, 25% reduction in flexion/extension
- No joint erosions on x-ray (2026-03-15); soft tissue swelling bilateral hands

LABORATORY RESULTS (2026-04-05):
RF: 480 IU/mL (strongly positive; reference <20)
Anti-CCP: >250 U/mL (strongly positive)
CRP: 4.2 mg/L (elevated; prior 1.8)    ESR: 68 mm/hr
CBC: WBC 8.2, Hgb 11.2, Plt 312
LFTs: Normal (important for methotrexate monitoring)

ASSESSMENT:
M05.79 - Rheumatoid arthritis with rheumatoid factor, multiple sites — active
  MONITORING: DAS28-CRP 5.1 today (high activity). RF 480, anti-CCP >250.
    CRP 4.2 mg/L worsened from 1.8 mg/L at last visit 3 months ago.
  EVALUATION: Inadequate disease control on methotrexate + hydroxychloroquine.
    RA-ILD noted on CT chest. Hands showing active synovitis across multiple joints.
  ASSESSMENT: Moderate-to-high disease activity RA, biologic-naive, failing
    conventional DMARD therapy. Meets criteria for biologic initiation.
  TREATMENT: Start adalimumab 40 mg SC every 2 weeks (TNF inhibitor). Continue
    methotrexate 15 mg weekly as anchor therapy. Screen for TB and Hep B before starting.

PLAN:
1. TB screening (QuantiFERON) and Hepatitis B serology before starting adalimumab.
2. Start adalimumab 40 mg SC Q2W pending clearance labs.
3. Taper prednisone to 7.5 mg over 4 weeks.
4. Rheumatology follow-up in 6 weeks to assess biologic response.
5. Pulmonology co-management for RA-ILD monitoring.
6. DEXA bone density repeat in 12 months.

Electronically signed: Dr. Susan Park, MD, FACR
""",
    },
]


# ---------------------------------------------------------------------------
# PDF generation
# ---------------------------------------------------------------------------

def _lazy_import_reportlab():
    """Lazy-import reportlab components. Raises ImportError with a clear message."""
    try:
        from reportlab.lib.pagesizes import LETTER
        from reportlab.lib.styles import getSampleStyleSheet
        from reportlab.lib.units import inch
        from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer
        return LETTER, getSampleStyleSheet, inch, Paragraph, SimpleDocTemplate, Spacer
    except ImportError as exc:
        raise ImportError(
            "reportlab is required for PDF generation. "
            "Install it with: pip install reportlab"
        ) from exc


def _generate_pdf(
    output_path: Path,
    note_def: dict[str, Any],
    patient_info: dict[str, str],
) -> None:
    """
    Generate a small (<50 KB) clinical PDF for the given note definition.
    Uses Helvetica only (no font embedding) to keep file size minimal.
    """
    LETTER, getSampleStyleSheet, inch, Paragraph, SimpleDocTemplate, Spacer = (
        _lazy_import_reportlab()
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)

    doc = SimpleDocTemplate(
        str(output_path),
        pagesize=LETTER,
        rightMargin=0.75 * inch,
        leftMargin=0.75 * inch,
        topMargin=0.75 * inch,
        bottomMargin=0.75 * inch,
    )

    styles = getSampleStyleSheet()
    title_style = styles["Heading1"]
    body_style = styles["BodyText"]
    body_style.fontName = "Helvetica"
    body_style.fontSize = 9
    body_style.leading = 12

    # Substitute patient placeholders
    note_text = note_def["note"]
    note_text = note_text.replace("[PATIENT]", patient_info.get("name", "Demo Patient"))
    note_text = note_text.replace("[DOB]", patient_info.get("dob", "01/01/1950"))
    note_text = note_text.replace("[PID]", str(patient_info.get("pid", "0")))

    story = [
        Paragraph(note_def["title"], title_style),
        Spacer(1, 0.1 * inch),
    ]

    for line in note_text.splitlines():
        if not line.strip():
            story.append(Spacer(1, 0.05 * inch))
        else:
            # Escape XML special chars for reportlab
            safe = (
                line.replace("&", "&amp;")
                    .replace("<", "&lt;")
                    .replace(">", "&gt;")
            )
            story.append(Paragraph(safe, body_style))

    doc.build(story)
    size_kb = output_path.stat().st_size / 1024
    log.info("  Generated: %s  (%.1f KB)", output_path.name, size_kb)
    if size_kb > 50:
        log.warning("  PDF exceeds 50 KB target: %.1f KB", size_kb)


# ---------------------------------------------------------------------------
# OpenEMR documents INSERT
# ---------------------------------------------------------------------------

def _insert_openemr_document(
    cursor,
    pid: int,
    filepath: str,
    doc_date: str,
    doc_name: str,
    owner: int = 1,
) -> int:
    """
    Insert a row into openemr.documents for the given PDF, if not already present.
    Returns the document id (existing or newly created).
    The url_filepath is used as the idempotency key.
    """
    cursor.execute(
        "SELECT id FROM documents WHERE url_filepath = %s LIMIT 1",
        (filepath,),
    )
    row = cursor.fetchone()
    if row:
        doc_id = row["id"] if isinstance(row, dict) else row[0]
        log.info("  Document already exists (id=%s): %s", doc_id, filepath)
        return doc_id

    cursor.execute(
        """
        INSERT INTO documents
            (owner, patient_id, type, size, date, url, url_filepath,
             mimetype, list_id, foreign_id, couch_docid, couch_revid,
             storagemethod, couch_dbname, encrypted)
        VALUES
            (%s, %s, 'file_url', 0, %s, %s, %s,
             'application/pdf', 0, 0, '', '',
             0, '', 0)
        """,
        (
            owner,
            pid,
            doc_date,
            f"file://{filepath}",
            filepath,
        ),
    )
    doc_id = cursor.lastrowid
    log.info("  Inserted openemr.documents id=%s for pid=%s: %s", doc_id, pid, filepath)
    return doc_id


# ---------------------------------------------------------------------------
# DB connection helper (standalone — does not use app.db pool)
# ---------------------------------------------------------------------------

def _get_db_connection(env_overrides: dict[str, str] | None = None):
    """
    Return a mysql-connector-python connection to the OpenEMR database.
    Reads from environment variables with the same names used by app/config.py.
    """
    try:
        import mysql.connector
    except ImportError as exc:
        raise ImportError(
            "mysql-connector-python is required. "
            "Install with: pip install mysql-connector-python"
        ) from exc

    cfg = {
        "host":     (env_overrides or {}).get("OPENEMR_DB_HOST")     or os.getenv("OPENEMR_DB_HOST", "127.0.0.1"),
        "port":     int((env_overrides or {}).get("OPENEMR_DB_PORT") or os.getenv("OPENEMR_DB_PORT", "3309")),
        "user":     (env_overrides or {}).get("OPENEMR_DB_USER")     or os.getenv("OPENEMR_DB_USER", "root"),
        "password": (env_overrides or {}).get("OPENEMR_DB_PASSWORD") or os.getenv("OPENEMR_DB_PASSWORD", "root"),
        "database": (env_overrides or {}).get("OPENEMR_DB_NAME")     or os.getenv("OPENEMR_DB_NAME", "openemr"),
        "charset":  "utf8mb4",
        "autocommit": True,
    }
    return mysql.connector.connect(**cfg)


def _get_patient_info(cursor, pid: int) -> dict[str, str]:
    """Return name and DOB for a patient, with safe fallbacks."""
    cursor.execute(
        "SELECT fname, lname, DOB FROM patient_data WHERE pid = %s LIMIT 1",
        (pid,),
    )
    row = cursor.fetchone()
    if not row:
        return {"name": f"Patient {pid}", "dob": "01/01/1950", "pid": str(pid)}
    if isinstance(row, dict):
        fname, lname, dob = row.get("fname", ""), row.get("lname", ""), row.get("DOB", "")
    else:
        fname, lname, dob = row[0] or "", row[1] or "", row[2] or ""
    name = f"{fname} {lname}".strip() or f"Patient {pid}"
    dob_str = str(dob) if dob else "01/01/1950"
    return {"name": name, "dob": dob_str, "pid": str(pid)}


# ---------------------------------------------------------------------------
# Main seeder
# ---------------------------------------------------------------------------

def seed(
    patient_ids: list[int],
    output_dir: Path,
    tenant_id: int = 1,
    dry_run: bool = False,
) -> list[dict[str, Any]]:
    """
    Generate PDFs and insert openemr.documents rows for every
    (patient, note_template) combination.

    Returns a list of result dicts with keys:
        pid, filename, doc_id, pdf_path, skipped (bool)
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    results: list[dict[str, Any]] = []

    # Pair each patient with one note (round-robin if fewer patients than notes)
    pairs: list[tuple[int, dict]] = []
    for i, pid in enumerate(patient_ids):
        note_def = CLINICAL_NOTES[i % len(CLINICAL_NOTES)]
        pairs.append((pid, note_def))

    if dry_run:
        log.info("[DRY RUN] Would generate %d PDFs for patients: %s", len(pairs), patient_ids)
        return [{"pid": pid, "filename": nd["filename"], "dry_run": True} for pid, nd in pairs]

    conn = _get_db_connection()
    cursor = conn.cursor(dictionary=True)

    try:
        for pid, note_def in pairs:
            log.info("Processing patient %s — %s", pid, note_def["filename"])
            patient_info = _get_patient_info(cursor, pid)

            # Place PDF in a per-patient subfolder matching OpenEMR's layout
            patient_dir = output_dir / str(pid)
            pdf_path = patient_dir / note_def["filename"]

            # Idempotency: skip PDF gen if file already exists and non-empty
            if pdf_path.exists() and pdf_path.stat().st_size > 0:
                log.info("  PDF already exists, skipping generation: %s", pdf_path)
            else:
                _generate_pdf(pdf_path, note_def, patient_info)

            doc_id = _insert_openemr_document(
                cursor,
                pid=pid,
                filepath=str(pdf_path.resolve()),
                doc_date=note_def["date"],
                doc_name=note_def["title"],
            )

            results.append({
                "pid": pid,
                "filename": note_def["filename"],
                "pdf_path": str(pdf_path.resolve()),
                "doc_id": doc_id,
                "hcc": note_def["hcc"],
                "icd10": note_def["icd10"],
                "skipped": False,
            })
    finally:
        cursor.close()
        conn.close()

    log.info(
        "Seeding complete. %d PDFs processed for %d patients.",
        len(results),
        len(patient_ids),
    )
    return results


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Seed synthetic clinical PDFs into OpenEMR for Gemini extraction testing.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python backend/scripts/seed_demo_pdfs.py --tenant 1 --patients 3,7,8,12,14,22,23,25,30,35
  python backend/scripts/seed_demo_pdfs.py --patients 3,7 --output-dir /tmp/my-pdfs --dry-run
        """,
    )
    parser.add_argument(
        "--tenant",
        type=int,
        default=1,
        help="Tenant/owner ID for document rows (default: 1)",
    )
    parser.add_argument(
        "--patients",
        required=True,
        help="Comma-separated list of OpenEMR patient IDs (pids)",
    )
    parser.add_argument(
        "--output-dir",
        default="/tmp/raf-demo-pdfs",
        help="Directory for generated PDFs (default: /tmp/raf-demo-pdfs)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would be done without writing files or touching DB",
    )

    args = parser.parse_args()

    try:
        pids = [int(p.strip()) for p in args.patients.split(",") if p.strip()]
    except ValueError as exc:
        parser.error(f"Invalid patient IDs: {exc}")

    if not pids:
        parser.error("At least one patient ID is required.")

    output_dir = Path(args.output_dir).resolve()

    log.info("=== RAF Demo PDF Seeder ===")
    log.info("Tenant: %s  |  Patients: %s  |  Output: %s", args.tenant, pids, output_dir)

    results = seed(pids, output_dir, tenant_id=args.tenant, dry_run=args.dry_run)

    print("\n--- Seeding Results ---")
    for r in results:
        if r.get("dry_run"):
            print(f"  [DRY RUN] pid={r['pid']}  file={r['filename']}")
        else:
            print(
                f"  pid={r['pid']}  doc_id={r.get('doc_id')}  "
                f"hcc={r.get('hcc')}  icd={r.get('icd10')}  "
                f"file={r.get('filename')}"
            )
    print(f"\nTotal: {len(results)} documents processed.")


if __name__ == "__main__":
    main()
