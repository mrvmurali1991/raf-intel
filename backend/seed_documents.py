#!/usr/bin/env python3
"""Seed demo document data for RAF Intelligence platform."""

import mysql.connector
import json
import hashlib
import random

conn = mysql.connector.connect(host='127.0.0.1', port=3306, user='root', password='root', database='raf_intelligence')
cur = conn.cursor()

# Clear existing demo data
cur.execute("DELETE FROM document_diagnosis_lines")
cur.execute("DELETE FROM document_analysis")
cur.execute("DELETE FROM documents")
conn.commit()

documents = [
    # 1: PID 6 - Linda Wilson, 83F - Discharge Summary
    {
        "patient_id": 6, "document_name": "Discharge_Summary_Abeyta_Ronald_20260315.pdf",
        "document_type": "discharge_summary", "file_size_bytes": 245800, "page_count": 4,
        "source": "ehr_pull", "encounter_date": "2026-03-15", "provider_name": "Dr. James Richardson",
        "status": "analyzed", "created_at": "2026-03-16 08:30:00",
        "extracted_text": "DISCHARGE SUMMARY - Patient: Linda Wilson, 83F. Admitted 03/10/2026 for acute exacerbation of CHF with volume overload. PMH significant for COPD (GOLD Stage III), Type 2 DM with nephropathy, CKD Stage IV (GFR 22), chronic systolic heart failure (EF 30%), and persistent atrial fibrillation on warfarin. Hospital course: IV furosemide diuresis with 4.2kg fluid loss. BNP improved from 1840 to 620. Renal function stable, Cr 2.8. A1c 8.1%. Resumed home O2 at 2L. Discharged on metoprolol, lisinopril, furosemide 80mg BID, insulin glargine, tiotropium, apixaban.",
        "diagnoses": [
            {"icd10": "I50.22", "desc": "Chronic systolic (congestive) heart failure, acute on chronic", "hcc": 85, "conf": 0.96, "page": 1, "evidence": "chronic systolic heart failure (EF 30%), acute exacerbation of CHF with volume overload", "confirmed": 1},
            {"icd10": "J44.1", "desc": "Chronic obstructive pulmonary disease with acute exacerbation", "hcc": 111, "conf": 0.91, "page": 1, "evidence": "COPD (GOLD Stage III)", "confirmed": 1},
            {"icd10": "E11.22", "desc": "Type 2 diabetes mellitus with diabetic chronic kidney disease", "hcc": 18, "conf": 0.94, "page": 1, "evidence": "Type 2 DM with nephropathy, CKD Stage IV (GFR 22)", "confirmed": 1},
            {"icd10": "N18.4", "desc": "Chronic kidney disease, stage 4 (severe)", "hcc": 137, "conf": 0.95, "page": 2, "evidence": "CKD Stage IV (GFR 22), Cr 2.8", "confirmed": 0},
            {"icd10": "I48.2", "desc": "Chronic atrial fibrillation", "hcc": 96, "conf": 0.93, "page": 1, "evidence": "persistent atrial fibrillation on warfarin", "confirmed": 0},
        ],
        "medications": ["metoprolol 50mg BID", "lisinopril 10mg daily", "furosemide 80mg BID", "insulin glargine 24u bedtime", "tiotropium 18mcg daily", "apixaban 5mg BID"],
        "labs": [{"test": "BNP", "value": "620", "unit": "pg/mL"}, {"test": "Creatinine", "value": "2.8", "unit": "mg/dL"}, {"test": "HbA1c", "value": "8.1", "unit": "%"}, {"test": "GFR", "value": "22", "unit": "mL/min"}],
        "vitals": [{"type": "BP", "value": "128/74"}, {"type": "HR", "value": "72"}, {"type": "SpO2", "value": "94%"}],
        "hcc_codes": [85, 111, 18, 137, 96],
        "summary": "83-year-old female discharged after acute CHF exacerbation requiring IV diuresis. Multiple comorbidities including COPD, DM with nephropathy, CKD Stage IV, and AFib managed with anticoagulation.",
        "quality": 0.95, "processing_time": 5420, "tokens": 2180,
        "patient_name_detected": "Linda Wilson", "patient_dob_detected": "1942-08-14",
        "meat": {"M": "BNP 1840->620, Cr 2.8, EF 30%, A1c 8.1%", "E": "CHF exacerbation with volume overload requiring hospitalization", "A": "IV furosemide diuresis, medication optimization", "T": "Cardiology follow-up 1 week, nephrology 2 weeks, home health nursing"},
        "suspects": [{"condition": "Protein-calorie malnutrition", "rationale": "Elderly with multiple comorbidities, prolonged hospitalization"}],
    },
    # 2: PID 14 - Sarah Martin, 62F - Progress Note
    {
        "patient_id": 14, "document_name": "Progress_Note_Lee_Richard_20260228.pdf",
        "document_type": "progress_note", "file_size_bytes": 178400, "page_count": 3,
        "source": "upload", "encounter_date": "2026-02-28", "provider_name": "Dr. Emily Chen",
        "status": "analyzed", "created_at": "2026-03-01 10:15:00",
        "extracted_text": "PROGRESS NOTE - Sarah Martin, 62F. Hepatology follow-up for alcoholic cirrhosis, Child-Pugh B. Recent paracentesis removed 3.2L ascitic fluid. MELD score 18. Concurrent Type 2 DM poorly controlled (A1c 9.2) on insulin. CHF with preserved EF (55%). CKD Stage IIIB, GFR 38. Exam: moderate ascites, trace pedal edema, spider angiomata on chest. Plan: Continue lactulose, spironolactone 100mg, furosemide 40mg. Titrate insulin. Hepatology to evaluate transplant candidacy. Recheck labs in 4 weeks.",
        "diagnoses": [
            {"icd10": "K70.31", "desc": "Alcoholic cirrhosis of liver with ascites", "hcc": 28, "conf": 0.97, "page": 1, "evidence": "alcoholic cirrhosis, Child-Pugh B, paracentesis removed 3.2L ascitic fluid, MELD score 18", "confirmed": 1},
            {"icd10": "E11.65", "desc": "Type 2 diabetes mellitus with hyperglycemia", "hcc": 19, "conf": 0.92, "page": 1, "evidence": "Type 2 DM poorly controlled (A1c 9.2) on insulin", "confirmed": 1},
            {"icd10": "I50.32", "desc": "Chronic diastolic heart failure, chronic", "hcc": 85, "conf": 0.88, "page": 2, "evidence": "CHF with preserved EF (55%)", "confirmed": 0},
            {"icd10": "N18.3", "desc": "Chronic kidney disease, stage 3b", "hcc": 138, "conf": 0.90, "page": 2, "evidence": "CKD Stage IIIB, GFR 38", "confirmed": 0},
        ],
        "medications": ["lactulose 30mL TID", "spironolactone 100mg daily", "furosemide 40mg daily", "insulin glargine 30u bedtime", "insulin lispro sliding scale"],
        "labs": [{"test": "MELD", "value": "18", "unit": ""}, {"test": "HbA1c", "value": "9.2", "unit": "%"}, {"test": "GFR", "value": "38", "unit": "mL/min"}, {"test": "Albumin", "value": "2.8", "unit": "g/dL"}],
        "vitals": [{"type": "BP", "value": "118/68"}, {"type": "HR", "value": "82"}, {"type": "Weight", "value": "176 lbs"}],
        "hcc_codes": [28, 19, 85, 138],
        "summary": "62-year-old female with alcoholic cirrhosis (Child-Pugh B, MELD 18) with recurrent ascites, poorly controlled diabetes, CHF with preserved EF, and CKD Stage IIIB. Transplant evaluation initiated.",
        "quality": 0.92, "processing_time": 4870, "tokens": 1950,
        "patient_name_detected": "Sarah Martin", "patient_dob_detected": "1963-11-02",
        "meat": {"M": "MELD 18, A1c 9.2, GFR 38, moderate ascites", "E": "Decompensated cirrhosis with recurrent ascites", "A": "Paracentesis, diuretics, insulin titration", "T": "Transplant evaluation, labs in 4 weeks"},
        "suspects": [{"condition": "Hepatic encephalopathy", "rationale": "Cirrhosis Child-Pugh B with lactulose therapy"}],
    },
    # 3: PID 1 - Robert Johnson, 77M - Clinical Note
    {
        "patient_id": 1, "document_name": "Clinical_Note_Johnson_Dorothy_Marie_20260120.pdf",
        "document_type": "clinical_note", "file_size_bytes": 134500, "page_count": 2,
        "source": "upload", "encounter_date": "2026-01-20", "provider_name": "Dr. Michael Torres",
        "status": "analyzed", "created_at": "2026-01-21 09:00:00",
        "extracted_text": "OFFICE VISIT NOTE - Robert Johnson, 77M. Chief complaint: routine diabetes and hypertension follow-up. Type 2 DM on metformin and glipizide, last A1c 7.4. HTN controlled on amlodipine and losartan. BP today 136/82. No chest pain, no SOB, no visual changes. Foot exam: intact sensation, no ulcers. Microalbumin/Cr ratio 45 (mildly elevated). Plan: Continue current medications. Increase losartan to 100mg for microalbuminuria. Ophthalmology referral for diabetic eye exam. Labs in 3 months.",
        "diagnoses": [
            {"icd10": "E11.21", "desc": "Type 2 diabetes mellitus with diabetic nephropathy", "hcc": 18, "conf": 0.89, "page": 1, "evidence": "Type 2 DM on metformin and glipizide, Microalbumin/Cr ratio 45 (mildly elevated)", "confirmed": 1},
            {"icd10": "I10", "desc": "Essential (primary) hypertension", "hcc": None, "conf": 0.95, "page": 1, "evidence": "HTN controlled on amlodipine and losartan, BP today 136/82", "confirmed": 0},
        ],
        "medications": ["metformin 1000mg BID", "glipizide 10mg daily", "amlodipine 5mg daily", "losartan 100mg daily"],
        "labs": [{"test": "HbA1c", "value": "7.4", "unit": "%"}, {"test": "Microalbumin/Cr", "value": "45", "unit": "mg/g"}],
        "vitals": [{"type": "BP", "value": "136/82"}, {"type": "HR", "value": "74"}, {"type": "Weight", "value": "198 lbs"}],
        "hcc_codes": [18],
        "summary": "77-year-old male with Type 2 DM with early nephropathy and controlled hypertension. Losartan uptitrated for renal protection, ophthalmology referral placed.",
        "quality": 0.88, "processing_time": 3240, "tokens": 1420,
        "patient_name_detected": "Robert Johnson", "patient_dob_detected": "1948-05-22",
        "meat": {"M": "A1c 7.4, BP 136/82, microalbumin/Cr 45", "E": "Stable diabetes with early nephropathy", "A": "Losartan uptitration, ophthalmology referral", "T": "Labs in 3 months, diabetic eye exam"},
        "suspects": [],
    },
    # 4: PID 8 - Barbara Taylor, 78F - Lab Report
    {
        "patient_id": 8, "document_name": "Lab_Report_Thompson_James_20260210.pdf",
        "document_type": "lab_report", "file_size_bytes": 98200, "page_count": 2,
        "source": "ehr_pull", "encounter_date": "2026-02-10", "provider_name": "Dr. Patricia Nguyen",
        "status": "analyzed", "created_at": "2026-02-11 07:45:00",
        "extracted_text": "LABORATORY REPORT - Barbara Taylor, 78F, DOB 1947-09-30. Comprehensive metabolic panel and HbA1c. Results: Glucose 186 mg/dL (H), BUN 34 (H), Creatinine 1.9 (H), GFR 28, Sodium 138, Potassium 5.1 (H), CO2 20 (L), Calcium 9.1, Albumin 3.2 (L). HbA1c 8.6% (H). Lipid panel: TC 210, LDL 128, HDL 42, TG 198. TSH 2.4 (normal). Urinalysis: protein 2+. Ordering provider notes: Elevated creatinine trend (1.4->1.7->1.9 over 6 months), declining GFR, consider nephrology referral.",
        "diagnoses": [
            {"icd10": "N18.4", "desc": "Chronic kidney disease, stage 4 (severe)", "hcc": 137, "conf": 0.93, "page": 1, "evidence": "Creatinine 1.9, GFR 28, elevated creatinine trend (1.4->1.7->1.9 over 6 months)", "confirmed": 0},
            {"icd10": "E11.22", "desc": "Type 2 diabetes mellitus with diabetic chronic kidney disease", "hcc": 18, "conf": 0.91, "page": 1, "evidence": "HbA1c 8.6%, Glucose 186, protein 2+ on UA with declining GFR", "confirmed": 0},
            {"icd10": "E78.5", "desc": "Dyslipidemia, unspecified", "hcc": None, "conf": 0.85, "page": 1, "evidence": "TC 210, LDL 128, HDL 42, TG 198", "confirmed": 0},
        ],
        "medications": [],
        "labs": [{"test": "Creatinine", "value": "1.9", "unit": "mg/dL"}, {"test": "GFR", "value": "28", "unit": "mL/min"}, {"test": "HbA1c", "value": "8.6", "unit": "%"}, {"test": "Glucose", "value": "186", "unit": "mg/dL"}, {"test": "Potassium", "value": "5.1", "unit": "mEq/L"}, {"test": "Albumin", "value": "3.2", "unit": "g/dL"}],
        "vitals": [],
        "hcc_codes": [137, 18],
        "summary": "78-year-old female with worsening renal function (GFR 28, trending down) and poorly controlled diabetes (A1c 8.6%). Labs suggest CKD Stage 4 progression with diabetic nephropathy.",
        "quality": 0.84, "processing_time": 2890, "tokens": 1280,
        "patient_name_detected": "Barbara Taylor", "patient_dob_detected": "1947-09-30",
        "meat": {"M": "Cr 1.9 (trending up), GFR 28, A1c 8.6%, proteinuria 2+", "E": "Progressive CKD with diabetic nephropathy", "A": "Nephrology referral recommended", "T": "Repeat labs, nephrology consultation"},
        "suspects": [{"condition": "Hyperkalemia", "rationale": "K+ 5.1 with declining GFR, may need dietary counseling"}],
    },
    # 5: PID 10 - Susan Thomas, 65F - Referral
    {
        "patient_id": 10, "document_name": "Referral_Cardiology_Anderson_William_20260305.pdf",
        "document_type": "referral", "file_size_bytes": 112300, "page_count": 2,
        "source": "upload", "encounter_date": "2026-03-05", "provider_name": "Dr. Robert Kim",
        "status": "analyzed", "created_at": "2026-03-06 11:20:00",
        "extracted_text": "CARDIOLOGY REFERRAL - Patient: Susan Thomas, 65F. Reason for referral: New-onset atrial fibrillation detected on routine ECG. Patient reports intermittent palpitations x 3 months, occasional lightheadedness. PMH: Hypertension, hypothyroidism, obesity (BMI 34). CHA2DS2-VASc score: 3 (female, HTN, age 65). Current meds: levothyroxine 88mcg, lisinopril 20mg, HCTZ 25mg. ECG: irregularly irregular rhythm, rate 88, no ST changes. TSH normal. Requesting: evaluation for rate vs rhythm control, anticoagulation assessment, echocardiogram.",
        "diagnoses": [
            {"icd10": "I48.91", "desc": "Unspecified atrial fibrillation", "hcc": 96, "conf": 0.92, "page": 1, "evidence": "New-onset atrial fibrillation detected on routine ECG, irregularly irregular rhythm", "confirmed": 0},
            {"icd10": "I10", "desc": "Essential (primary) hypertension", "hcc": None, "conf": 0.94, "page": 1, "evidence": "PMH: Hypertension, lisinopril 20mg, HCTZ 25mg", "confirmed": 0},
            {"icd10": "E03.9", "desc": "Hypothyroidism, unspecified", "hcc": None, "conf": 0.90, "page": 1, "evidence": "hypothyroidism, levothyroxine 88mcg", "confirmed": 0},
        ],
        "medications": ["levothyroxine 88mcg daily", "lisinopril 20mg daily", "HCTZ 25mg daily"],
        "labs": [{"test": "TSH", "value": "2.1", "unit": "mIU/L"}],
        "vitals": [{"type": "BP", "value": "142/88"}, {"type": "HR", "value": "88 irregular"}, {"type": "BMI", "value": "34"}],
        "hcc_codes": [96],
        "summary": "65-year-old female referred to cardiology for new-onset atrial fibrillation with CHA2DS2-VASc of 3, requiring anticoagulation assessment and rhythm management evaluation.",
        "quality": 0.87, "processing_time": 3560, "tokens": 1540,
        "patient_name_detected": "Susan Thomas", "patient_dob_detected": "1960-12-18",
        "meat": {"M": "ECG showing AFib, HR 88, CHA2DS2-VASc 3", "E": "New-onset AFib with palpitations and lightheadedness", "A": "Cardiology referral for evaluation", "T": "Echo, rate/rhythm control assessment, anticoagulation decision"},
        "suspects": [{"condition": "Obstructive sleep apnea", "rationale": "BMI 34 with new AFib, high OSA prevalence in this population"}],
    },
    # 6: PID 7 - William Moore, 67M - Progress Note
    {
        "patient_id": 7, "document_name": "Progress_Note_Garcia_Maria_20260318.pdf",
        "document_type": "progress_note", "file_size_bytes": 156700, "page_count": 3,
        "source": "upload", "encounter_date": "2026-03-18", "provider_name": "Dr. Amanda Foster",
        "status": "analyzed", "created_at": "2026-03-19 14:00:00",
        "extracted_text": "PROGRESS NOTE - William Moore, 67M. Psychiatry follow-up for major depressive disorder, recurrent, moderate. PHQ-9 score: 14 (moderately severe). Reports poor sleep, decreased appetite, weight loss 8 lbs in 2 months. Concurrent Type 2 DM on metformin (A1c 7.8). Neuropathic pain in bilateral feet on gabapentin. Currently on sertraline 150mg with partial response. Assessment: MDD not adequately controlled. Plan: Augment with bupropion 150mg XL. Continue sertraline. Screen for diabetic complications given weight loss. Follow-up 4 weeks.",
        "diagnoses": [
            {"icd10": "F33.1", "desc": "Major depressive disorder, recurrent, moderate", "hcc": 59, "conf": 0.94, "page": 1, "evidence": "major depressive disorder, recurrent, moderate, PHQ-9 score: 14", "confirmed": 1},
            {"icd10": "E11.42", "desc": "Type 2 diabetes mellitus with diabetic polyneuropathy", "hcc": 18, "conf": 0.90, "page": 2, "evidence": "Type 2 DM, neuropathic pain in bilateral feet on gabapentin", "confirmed": 0},
        ],
        "medications": ["sertraline 150mg daily", "bupropion 150mg XL daily", "metformin 1000mg BID", "gabapentin 300mg TID"],
        "labs": [{"test": "HbA1c", "value": "7.8", "unit": "%"}, {"test": "PHQ-9", "value": "14", "unit": ""}],
        "vitals": [{"type": "BP", "value": "124/76"}, {"type": "HR", "value": "68"}, {"type": "Weight", "value": "172 lbs"}],
        "hcc_codes": [59, 18],
        "summary": "67-year-old male with moderately severe MDD (PHQ-9: 14) inadequately controlled on sertraline, augmented with bupropion. Concurrent DM with peripheral neuropathy and recent weight loss.",
        "quality": 0.90, "processing_time": 3980, "tokens": 1680,
        "patient_name_detected": "William Moore", "patient_dob_detected": "1958-07-11",
        "meat": {"M": "PHQ-9: 14, weight loss 8 lbs in 2 months, A1c 7.8", "E": "MDD with partial response to SSRI", "A": "Augment with bupropion, continue sertraline", "T": "Follow-up 4 weeks, screen for diabetic complications"},
        "suspects": [],
    },
    # 7: PID 2 - Mary Williams, 73F - Annual Wellness Visit
    {
        "patient_id": 2, "document_name": "AWV_Williams_Robert_James_20260115.pdf",
        "document_type": "clinical_note", "file_size_bytes": 189600, "page_count": 4,
        "source": "ehr_pull", "encounter_date": "2026-01-15", "provider_name": "Dr. Susan Park",
        "status": "analyzed", "created_at": "2026-01-16 08:00:00",
        "extracted_text": "ANNUAL WELLNESS VISIT - Mary Williams, 73F. Health risk assessment completed. PMH: Osteoporosis (T-score -2.8), GERD, mild cognitive impairment (MoCA 22/30), hyperlipidemia, bilateral knee osteoarthritis. Medications: alendronate 70mg weekly, omeprazole 20mg, donepezil 5mg, atorvastatin 40mg. Screening: mammogram current, colonoscopy due. Fall risk: moderate (TUG 14 seconds). Cognitive screen: MoCA 22/30, stable from last year. Depression screen: PHQ-2 negative. Advanced care planning discussed. Immunizations: flu and COVID boosters given.",
        "diagnoses": [
            {"icd10": "G31.84", "desc": "Mild cognitive impairment", "hcc": 52, "conf": 0.88, "page": 2, "evidence": "mild cognitive impairment (MoCA 22/30), donepezil 5mg", "confirmed": 0},
            {"icd10": "M81.0", "desc": "Age-related osteoporosis without current pathological fracture", "hcc": None, "conf": 0.92, "page": 1, "evidence": "Osteoporosis (T-score -2.8), alendronate 70mg weekly", "confirmed": 0},
            {"icd10": "M17.0", "desc": "Bilateral primary osteoarthritis of knee", "hcc": None, "conf": 0.86, "page": 1, "evidence": "bilateral knee osteoarthritis", "confirmed": 0},
        ],
        "medications": ["alendronate 70mg weekly", "omeprazole 20mg daily", "donepezil 5mg daily", "atorvastatin 40mg daily"],
        "labs": [{"test": "MoCA", "value": "22", "unit": "/30"}, {"test": "TUG", "value": "14", "unit": "seconds"}],
        "vitals": [{"type": "BP", "value": "132/78"}, {"type": "HR", "value": "70"}, {"type": "Weight", "value": "148 lbs"}, {"type": "BMI", "value": "25.2"}],
        "hcc_codes": [52],
        "summary": "73-year-old female annual wellness visit. Stable mild cognitive impairment on donepezil, osteoporosis managed, moderate fall risk. Advanced care planning discussed, colonoscopy screening due.",
        "quality": 0.91, "processing_time": 4210, "tokens": 1820,
        "patient_name_detected": "Mary Williams", "patient_dob_detected": "1952-03-08",
        "meat": {"M": "MoCA 22/30 stable, T-score -2.8, TUG 14s", "E": "Stable MCI, osteoporosis, moderate fall risk", "A": "Continue donepezil, alendronate; immunizations given", "T": "Colonoscopy referral, follow-up 1 year"},
        "suspects": [{"condition": "Vitamin D deficiency", "rationale": "Osteoporosis with fall risk, no vitamin D level documented"}],
    },
    # 8: PID 5 - Michael Miller, 75M - Pulmonology Note
    {
        "patient_id": 5, "document_name": "Pulmonology_Note_Jackson_Synagog_Julia_20260203.pdf",
        "document_type": "progress_note", "file_size_bytes": 167300, "page_count": 3,
        "source": "upload", "encounter_date": "2026-02-03", "provider_name": "Dr. David Martinez",
        "status": "analyzed", "created_at": "2026-02-04 10:30:00",
        "extracted_text": "PULMONOLOGY CONSULTATION - Michael Miller, 75M. Referred for COPD management. FEV1 42% predicted (severe obstruction). On tiotropium and fluticasone/salmeterol. Two exacerbations in past year requiring oral steroids. O2 sat 91% on room air, drops to 86% with ambulation. 40 pack-year smoking history, quit 5 years ago. Also carries diagnosis of peripheral vascular disease with claudication. CT chest: emphysematous changes bilateral upper lobes, no mass. Plan: Add roflumilast for exacerbation reduction. Home O2 for exertional use. Pulmonary rehab referral.",
        "diagnoses": [
            {"icd10": "J44.1", "desc": "Chronic obstructive pulmonary disease with acute exacerbation", "hcc": 111, "conf": 0.95, "page": 1, "evidence": "COPD, FEV1 42% predicted (severe obstruction), two exacerbations in past year", "confirmed": 1},
            {"icd10": "I73.9", "desc": "Peripheral vascular disease, unspecified", "hcc": 108, "conf": 0.87, "page": 2, "evidence": "peripheral vascular disease with claudication", "confirmed": 0},
            {"icd10": "J98.4", "desc": "Other disorders of lung", "hcc": None, "conf": 0.78, "page": 2, "evidence": "emphysematous changes bilateral upper lobes on CT chest", "confirmed": 0},
        ],
        "medications": ["tiotropium 18mcg daily", "fluticasone/salmeterol 250/50 BID", "roflumilast 500mcg daily", "albuterol PRN"],
        "labs": [{"test": "FEV1", "value": "42", "unit": "% predicted"}, {"test": "SpO2 rest", "value": "91", "unit": "%"}, {"test": "SpO2 exertion", "value": "86", "unit": "%"}],
        "vitals": [{"type": "BP", "value": "138/84"}, {"type": "HR", "value": "78"}, {"type": "SpO2", "value": "91%"}, {"type": "RR", "value": "20"}],
        "hcc_codes": [111, 108],
        "summary": "75-year-old male with severe COPD (FEV1 42%) and frequent exacerbations. Roflumilast added, home oxygen initiated for exertional desaturation, pulmonary rehab ordered. Concurrent PVD with claudication.",
        "quality": 0.93, "processing_time": 4120, "tokens": 1750,
        "patient_name_detected": "Michael Miller", "patient_dob_detected": "1950-10-25",
        "meat": {"M": "FEV1 42%, SpO2 91% rest/86% exertion, 2 exacerbations/year", "E": "Severe COPD with exertional hypoxia and frequent exacerbations", "A": "Added roflumilast, home O2, pulmonary rehab referral", "T": "Pulmonary rehab, follow-up 3 months, 6MWT scheduled"},
        "suspects": [],
    },
    # 9: PID 12 - Jessica White, 69F - Endocrinology Referral
    {
        "patient_id": 12, "document_name": "Endo_Referral_Martinez_David_20260322.pdf",
        "document_type": "referral", "file_size_bytes": 125400, "page_count": 2,
        "source": "upload", "encounter_date": "2026-03-22", "provider_name": "Dr. Lisa Park",
        "status": "analyzed", "created_at": "2026-03-23 09:15:00",
        "extracted_text": "ENDOCRINOLOGY REFERRAL - Jessica White, 69F. Reason: Uncontrolled Type 2 DM despite triple oral therapy. A1c 9.8% (up from 8.4% six months ago). Current regimen: metformin 2000mg, glipizide 20mg, pioglitazone 30mg. Recurrent UTIs (3 in past year), ruling out SGLT2i. BMI 38.2. Complications: background diabetic retinopathy (seen by ophthalmology), microalbuminuria. Fasting glucose 234. C-peptide 2.8 (adequate). Requesting insulin initiation guidance and GLP-1 RA consideration given obesity.",
        "diagnoses": [
            {"icd10": "E11.65", "desc": "Type 2 diabetes mellitus with hyperglycemia", "hcc": 19, "conf": 0.96, "page": 1, "evidence": "Uncontrolled Type 2 DM, A1c 9.8%, fasting glucose 234, despite triple oral therapy", "confirmed": 1},
            {"icd10": "E11.319", "desc": "Type 2 DM with unspecified diabetic retinopathy without macular edema", "hcc": 18, "conf": 0.88, "page": 1, "evidence": "background diabetic retinopathy (seen by ophthalmology)", "confirmed": 0},
            {"icd10": "E66.01", "desc": "Morbid obesity due to excess calories", "hcc": 22, "conf": 0.90, "page": 1, "evidence": "BMI 38.2", "confirmed": 0},
        ],
        "medications": ["metformin 1000mg BID", "glipizide 10mg BID", "pioglitazone 30mg daily"],
        "labs": [{"test": "HbA1c", "value": "9.8", "unit": "%"}, {"test": "Fasting glucose", "value": "234", "unit": "mg/dL"}, {"test": "C-peptide", "value": "2.8", "unit": "ng/mL"}],
        "vitals": [{"type": "BP", "value": "146/90"}, {"type": "HR", "value": "76"}, {"type": "BMI", "value": "38.2"}, {"type": "Weight", "value": "228 lbs"}],
        "hcc_codes": [19, 18, 22],
        "summary": "69-year-old female with uncontrolled Type 2 DM (A1c 9.8%) failing triple oral therapy, referred for insulin initiation and GLP-1 RA evaluation. Concurrent morbid obesity, diabetic retinopathy, and microalbuminuria.",
        "quality": 0.89, "processing_time": 3670, "tokens": 1590,
        "patient_name_detected": "Jessica White", "patient_dob_detected": "1956-06-14",
        "meat": {"M": "A1c 9.8% (up from 8.4%), FG 234, C-peptide 2.8, BMI 38.2", "E": "Uncontrolled DM despite max oral therapy with complications", "A": "Endocrinology referral for insulin/GLP-1 RA", "T": "Endo consult, consider semaglutide vs insulin, recheck A1c 3 months"},
        "suspects": [],
    },
    # 10: PID 15 - Thomas Thompson, 81M - Discharge Summary Post-Stroke
    {
        "patient_id": 15, "document_name": "Discharge_Summary_Wilson_Barbara_20260401.pdf",
        "document_type": "discharge_summary", "file_size_bytes": 278900, "page_count": 5,
        "source": "ehr_pull", "encounter_date": "2026-04-01", "provider_name": "Dr. John Williams",
        "status": "analyzed", "created_at": "2026-04-02 16:00:00",
        "extracted_text": "DISCHARGE SUMMARY - Thomas Thompson, 81M. Admitted 03/28 for acute left MCA ischemic stroke. Presented with right-sided weakness and expressive aphasia. tPA administered within 3-hour window. MRI confirmed left MCA territory infarct. Hospital course: ICU x 2 days, improved to modified Rankin 3. Residual right hemiparesis and mild expressive aphasia. PMH: HTN, AFib (not on anticoagulation - contributing factor), Type 2 DM, hyperlipidemia. Started on apixaban 5mg BID for stroke prevention. Discharged to acute rehab facility. NIHSS admission 14, discharge 6.",
        "diagnoses": [
            {"icd10": "I63.512", "desc": "Cerebral infarction due to unspecified occlusion of left middle cerebral artery", "hcc": 100, "conf": 0.97, "page": 1, "evidence": "acute left MCA ischemic stroke, MRI confirmed left MCA territory infarct, tPA administered", "confirmed": 1},
            {"icd10": "I48.91", "desc": "Unspecified atrial fibrillation", "hcc": 96, "conf": 0.93, "page": 2, "evidence": "AFib (not on anticoagulation - contributing factor), started apixaban", "confirmed": 1},
            {"icd10": "G81.91", "desc": "Hemiplegia, unspecified, affecting right dominant side", "hcc": 104, "conf": 0.91, "page": 2, "evidence": "Residual right hemiparesis, modified Rankin 3", "confirmed": 0},
            {"icd10": "R47.01", "desc": "Aphasia", "hcc": None, "conf": 0.89, "page": 2, "evidence": "mild expressive aphasia", "confirmed": 0},
            {"icd10": "E11.9", "desc": "Type 2 diabetes mellitus without complications", "hcc": 19, "conf": 0.85, "page": 3, "evidence": "PMH: Type 2 DM", "confirmed": 0},
        ],
        "medications": ["apixaban 5mg BID", "atorvastatin 80mg daily", "lisinopril 20mg daily", "metformin 500mg BID", "aspirin 81mg daily"],
        "labs": [{"test": "NIHSS admission", "value": "14", "unit": ""}, {"test": "NIHSS discharge", "value": "6", "unit": ""}, {"test": "INR", "value": "1.1", "unit": ""}, {"test": "LDL", "value": "142", "unit": "mg/dL"}],
        "vitals": [{"type": "BP", "value": "148/86"}, {"type": "HR", "value": "82 irregular"}, {"type": "SpO2", "value": "96%"}],
        "hcc_codes": [100, 96, 104, 19],
        "summary": "81-year-old male discharged after acute left MCA stroke (tPA treated) with residual right hemiparesis and mild aphasia. AFib identified as etiology - anticoagulation initiated. Discharged to acute rehab.",
        "quality": 0.96, "processing_time": 6180, "tokens": 2450,
        "patient_name_detected": "Thomas Thompson", "patient_dob_detected": "1944-11-30",
        "meat": {"M": "NIHSS 14->6, MRI confirmed LT MCA infarct, modified Rankin 3", "E": "Acute ischemic stroke secondary to untreated AFib", "A": "tPA, anticoagulation initiated, ICU care", "T": "Acute rehab, neurology follow-up 2 weeks, PT/OT/Speech therapy"},
        "suspects": [{"condition": "Dysphagia", "rationale": "Post-stroke with expressive aphasia, swallowing eval recommended"}],
    },
    # 11: PID 3 - James Brown, 68M - Clinical Note
    {
        "patient_id": 3, "document_name": "Clinical_Note_Cisneros_Patrick_20260125.pdf",
        "document_type": "clinical_note", "file_size_bytes": 142100, "page_count": 2,
        "source": "upload", "encounter_date": "2026-01-25", "provider_name": "Dr. Karen Lee",
        "status": "analyzed", "created_at": "2026-01-26 11:00:00",
        "extracted_text": "OFFICE VISIT - James Brown, 68M. Follow-up for rheumatoid arthritis and GERD. RA well-controlled on methotrexate 15mg weekly and folic acid. DAS28 score 2.4 (low disease activity). GERD managed with pantoprazole 40mg. Reports occasional heartburn with spicy foods. Joints: no swelling, mild bilateral hand stiffness AM <30 min. Labs: CRP 0.4, ESR 12, CBC wnl, LFTs wnl. Plan: Continue current regimen. Annual labs in 6 months.",
        "diagnoses": [
            {"icd10": "M06.09", "desc": "Rheumatoid arthritis without rheumatoid factor, multiple sites", "hcc": 40, "conf": 0.91, "page": 1, "evidence": "rheumatoid arthritis well-controlled on methotrexate, DAS28 score 2.4", "confirmed": 0},
            {"icd10": "K21.0", "desc": "Gastro-esophageal reflux disease with esophagitis", "hcc": None, "conf": 0.82, "page": 1, "evidence": "GERD managed with pantoprazole 40mg, occasional heartburn", "confirmed": 0},
        ],
        "medications": ["methotrexate 15mg weekly", "folic acid 1mg daily", "pantoprazole 40mg daily"],
        "labs": [{"test": "CRP", "value": "0.4", "unit": "mg/L"}, {"test": "ESR", "value": "12", "unit": "mm/hr"}, {"test": "DAS28", "value": "2.4", "unit": ""}],
        "vitals": [{"type": "BP", "value": "128/76"}, {"type": "HR", "value": "72"}],
        "hcc_codes": [40],
        "summary": "68-year-old male with well-controlled rheumatoid arthritis (DAS28 2.4) on methotrexate and stable GERD. No medication changes needed.",
        "quality": 0.86, "processing_time": 2780, "tokens": 1180,
        "patient_name_detected": "James Brown", "patient_dob_detected": "1957-12-03",
        "meat": {"M": "DAS28 2.4, CRP 0.4, ESR 12, joints without swelling", "E": "RA in low disease activity", "A": "Continue methotrexate, folic acid, pantoprazole", "T": "Annual labs in 6 months"},
        "suspects": [],
    },
    # 12: PID 4 - Patricia Jones, 71F - Progress Note
    {
        "patient_id": 4, "document_name": "Progress_Note_Adams_Terry_20260212.pdf",
        "document_type": "progress_note", "file_size_bytes": 151200, "page_count": 3,
        "source": "ehr_pull", "encounter_date": "2026-02-12", "provider_name": "Dr. James Richardson",
        "status": "analyzed", "created_at": "2026-02-13 09:45:00",
        "extracted_text": "PROGRESS NOTE - Patricia Jones, 71F. Cardiology follow-up. Paroxysmal atrial fibrillation on flecainide and metoprolol. No episodes per Holter monitor x 30 days. On apixaban for anticoagulation. Echocardiogram: LVEF 60%, mild MR, LA mildly dilated 4.2cm. Also managing hypertension (BP well controlled) and hyperlipidemia (LDL 68 on rosuvastatin). Assessment: PAF well-controlled on current rhythm control strategy. Continue current regimen.",
        "diagnoses": [
            {"icd10": "I48.0", "desc": "Paroxysmal atrial fibrillation", "hcc": 96, "conf": 0.95, "page": 1, "evidence": "Paroxysmal atrial fibrillation on flecainide and metoprolol, no episodes per Holter", "confirmed": 1},
            {"icd10": "I34.0", "desc": "Nonrheumatic mitral (valve) insufficiency", "hcc": None, "conf": 0.83, "page": 2, "evidence": "mild MR on echocardiogram", "confirmed": 0},
        ],
        "medications": ["flecainide 100mg BID", "metoprolol 50mg BID", "apixaban 5mg BID", "rosuvastatin 20mg daily", "lisinopril 10mg daily"],
        "labs": [{"test": "LDL", "value": "68", "unit": "mg/dL"}, {"test": "LVEF", "value": "60", "unit": "%"}],
        "vitals": [{"type": "BP", "value": "126/74"}, {"type": "HR", "value": "66 regular"}],
        "hcc_codes": [96],
        "summary": "71-year-old female with paroxysmal AFib well-controlled on flecainide/metoprolol rhythm control. No arrhythmia episodes in 30 days. Preserved LVEF with mild MR.",
        "quality": 0.90, "processing_time": 3450, "tokens": 1490,
        "patient_name_detected": "Patricia Jones", "patient_dob_detected": "1954-09-17",
        "meat": {"M": "Holter: no AFib episodes x 30 days, LVEF 60%, LDL 68", "E": "PAF in rhythm control", "A": "Continue flecainide, metoprolol, apixaban", "T": "Repeat Holter in 6 months, cardiology follow-up 6 months"},
        "suspects": [],
    },
    # 13: PID 9 - Richard Anderson, 70M - Lab Report (analyzed)
    {
        "patient_id": 9, "document_name": "Lab_Report_Chen_Sarah_20260402.pdf",
        "document_type": "lab_report", "file_size_bytes": 89400, "page_count": 1,
        "source": "ehr_pull", "encounter_date": "2026-04-02", "provider_name": "Dr. Patricia Nguyen",
        "status": "analyzed", "created_at": "2026-04-03 07:30:00",
        "extracted_text": None,
        "diagnoses": [
            {"icd10": "E03.9", "desc": "Hypothyroidism, unspecified", "hcc": None, "conf": 0.90, "page": 1, "evidence": "TSH 5.8 slightly elevated, on levothyroxine", "confirmed": 0},
            {"icd10": "F41.9", "desc": "Anxiety disorder, unspecified", "hcc": None, "conf": 0.85, "page": 1, "evidence": "Anxiety disorder on record, sertraline 50mg", "confirmed": 0},
        ],
        "medications": ["Levothyroxine 50mcg daily", "Sertraline 50mg daily"],
        "labs": [{"test": "TSH", "value": "5.8", "unit": "mIU/L"}, {"test": "Free T4", "value": "0.9", "unit": "ng/dL"}, {"test": "HbA1c", "value": "5.2", "unit": "%"}, {"test": "TC", "value": "195", "unit": "mg/dL"}, {"test": "LDL", "value": "118", "unit": "mg/dL"}],
        "vitals": [],
        "hcc_codes": [],
        "summary": "Lab report for Sarah Chen, 54F. Comprehensive metabolic panel and CBC. Mild hypothyroidism with TSH slightly elevated. Anxiety disorder on record. All other values within normal limits.",
        "quality": 0.935, "processing_time": 3800, "tokens": 2900,
        "patient_name_detected": "Sarah Chen", "patient_dob_detected": None,
        "meat": {"M": "TSH 5.8 mIU/L (slightly elevated)", "E": "Subclinical hypothyroidism, dose adjustment needed", "A": "Increase levothyroxine to 75mcg daily", "T": "Thyroid function monitored quarterly"},
        "suspects": [],
    },
    # 14: PID 11 - David Jackson, 74M - Progress Note (analyzed)
    {
        "patient_id": 11, "document_name": "Progress_Note_Brown_Margaret_20260404.pdf",
        "document_type": "progress_note", "file_size_bytes": 145600, "page_count": 3,
        "source": "upload", "encounter_date": "2026-04-04", "provider_name": "Dr. Emily Chen",
        "status": "analyzed", "created_at": "2026-04-05 10:00:00",
        "extracted_text": None,
        "diagnoses": [
            {"icd10": "I10", "desc": "Essential hypertension", "hcc": None, "conf": 0.94, "page": 1, "evidence": "Hypertension controlled on lisinopril", "confirmed": 0},
            {"icd10": "M17.9", "desc": "Osteoarthritis of knee, unspecified", "hcc": None, "conf": 0.88, "page": 1, "evidence": "Knee pain managed with acetaminophen", "confirmed": 0},
        ],
        "medications": ["Lisinopril 20mg daily", "Acetaminophen 500mg PRN", "Calcium/Vitamin D supplement"],
        "labs": [{"test": "eGFR", "value": "62", "unit": "mL/min"}],
        "vitals": [],
        "hcc_codes": [],
        "summary": "Progress note for Margaret Brown, 85F. Follow-up for hypertension and osteoarthritis. BP well controlled on current regimen. Knee pain managed with acetaminophen. Cognitive screening MMSE 28/30. Independent in ADLs.",
        "quality": 0.918, "processing_time": 3500, "tokens": 2700,
        "patient_name_detected": "Margaret Brown", "patient_dob_detected": None,
        "meat": {"M": "BP log reviewed, well controlled, MMSE 28/30", "E": "Hypertension controlled, OA stable", "A": "Continue current medications, annual wellness visit scheduled", "T": "BP log reviewed, well controlled"},
        "suspects": [],
    },
    # 15: PID 13 - Karen Harris, 66F - Discharge Summary (analyzed)
    {
        "patient_id": 13, "document_name": "Discharge_Summary_Taylor_Linda_20260330.pdf",
        "document_type": "discharge_summary", "file_size_bytes": 312400, "page_count": 6,
        "source": "upload", "encounter_date": "2026-03-30", "provider_name": "Dr. Robert Kim",
        "status": "analyzed", "created_at": "2026-03-31 14:20:00",
        "extracted_text": None,
        "diagnoses": [
            {"icd10": "R55", "desc": "Syncope and collapse", "hcc": None, "conf": 0.92, "page": 1, "evidence": "Admitted for observation following syncopal episode", "confirmed": 0},
            {"icd10": "E03.9", "desc": "Hypothyroidism, unspecified", "hcc": None, "conf": 0.88, "page": 1, "evidence": "History of hypothyroidism on levothyroxine", "confirmed": 0},
            {"icd10": "F41.9", "desc": "Anxiety disorder, unspecified", "hcc": None, "conf": 0.85, "page": 1, "evidence": "Anxiety disorder managed with buspirone", "confirmed": 0},
        ],
        "medications": ["Levothyroxine 75mcg daily", "Buspirone 10mg BID"],
        "labs": [{"test": "TSH", "value": "2.4", "unit": "mIU/L"}, {"test": "Troponin", "value": "<0.01", "unit": "ng/mL"}],
        "vitals": [],
        "hcc_codes": [],
        "summary": "Discharge summary for Linda Taylor, 50F. Admitted for observation following syncopal episode. Workup negative for cardiac etiology. History of hypothyroidism and anxiety disorder managed with levothyroxine and buspirone. Discharged stable with outpatient cardiology follow-up.",
        "quality": 0.912, "processing_time": 4200, "tokens": 3100,
        "patient_name_detected": "Linda Taylor", "patient_dob_detected": None,
        "meat": {"M": "Troponin <0.01, echo normal EF 60%, telemetry normal sinus", "E": "Vasovagal syncope, benign", "A": "Conservative management, hydration counseling", "T": "Cardiac telemetry x 24hrs normal sinus"},
        "suspects": [],
    },
    # 16: PID 6 - Linda Wilson - 2nd doc, progress note
    {
        "patient_id": 6, "document_name": "Progress_Note_Abeyta_Ronald_20260125.pdf",
        "document_type": "progress_note", "file_size_bytes": 138900, "page_count": 2,
        "source": "upload", "encounter_date": "2026-01-25", "provider_name": "Dr. James Richardson",
        "status": "analyzed", "created_at": "2026-01-26 13:00:00",
        "extracted_text": "PROGRESS NOTE - Linda Wilson, 83F. Cardiology follow-up for CHF management. NYHA Class III symptoms with exertional dyspnea at 50 feet. Last echo EF 30%. Dry weight 156 lbs, current 158 lbs (slight volume up). BNP 480. On optimized GDMT: sacubitril/valsartan 97/103 BID, carvedilol 25mg BID, spironolactone 25mg, furosemide 60mg BID. Considering CRT-D given EF <35% and LBBB on ECG. Also monitoring COPD - stable on current inhalers.",
        "diagnoses": [
            {"icd10": "I50.22", "desc": "Chronic systolic heart failure", "hcc": 85, "conf": 0.97, "page": 1, "evidence": "CHF NYHA Class III, EF 30%, on optimized GDMT, considering CRT-D", "confirmed": 1},
            {"icd10": "J44.9", "desc": "Chronic obstructive pulmonary disease, unspecified", "hcc": 111, "conf": 0.84, "page": 2, "evidence": "COPD - stable on current inhalers", "confirmed": 0},
        ],
        "medications": ["sacubitril/valsartan 97/103 BID", "carvedilol 25mg BID", "spironolactone 25mg daily", "furosemide 60mg BID"],
        "labs": [{"test": "BNP", "value": "480", "unit": "pg/mL"}, {"test": "LVEF", "value": "30", "unit": "%"}],
        "vitals": [{"type": "BP", "value": "110/68"}, {"type": "HR", "value": "68"}, {"type": "Weight", "value": "158 lbs"}],
        "hcc_codes": [85, 111],
        "summary": "83-year-old female with NYHA Class III systolic heart failure (EF 30%) on optimized GDMT. CRT-D evaluation planned given LBBB and reduced EF. Concurrent COPD stable.",
        "quality": 0.91, "processing_time": 3890, "tokens": 1620,
        "patient_name_detected": "Linda Wilson", "patient_dob_detected": "1942-08-14",
        "meat": {"M": "EF 30%, BNP 480, NYHA III, weight 158 lbs", "E": "Advanced systolic HF with LBBB", "A": "Optimized GDMT, CRT-D evaluation", "T": "EP consult for CRT-D, follow-up 4 weeks"},
        "suspects": [],
    },
    # 17: PID 14 - Sarah Martin - 2nd doc, lab report
    {
        "patient_id": 14, "document_name": "Lab_Report_Lee_Richard_20260320.pdf",
        "document_type": "lab_report", "file_size_bytes": 94500, "page_count": 2,
        "source": "ehr_pull", "encounter_date": "2026-03-20", "provider_name": "Dr. Emily Chen",
        "status": "analyzed", "created_at": "2026-03-21 08:00:00",
        "extracted_text": "LABORATORY REPORT - Sarah Martin, 62F. Hepatic function panel and metabolic workup. Results: AST 68 (H), ALT 52 (H), Alk Phos 142 (H), Total Bilirubin 2.4 (H), Direct Bilirubin 1.6 (H), Albumin 2.6 (L), INR 1.4 (H), Platelets 98K (L). AFP 8.2 (normal). Ammonia 62 (H). Creatinine 1.6, GFR 36. Glucose 198 (H). A1c pending. Na 134, K 4.2. Assessment: Worsening hepatic synthetic function with rising bilirubin and declining albumin. MELD score now 21 (up from 18).",
        "diagnoses": [
            {"icd10": "K70.31", "desc": "Alcoholic cirrhosis of liver with ascites", "hcc": 28, "conf": 0.95, "page": 1, "evidence": "Worsening hepatic synthetic function, MELD 21, Albumin 2.6, INR 1.4, Bilirubin 2.4", "confirmed": 0},
            {"icd10": "N18.3", "desc": "Chronic kidney disease, stage 3b", "hcc": 138, "conf": 0.88, "page": 1, "evidence": "Creatinine 1.6, GFR 36", "confirmed": 0},
        ],
        "medications": [],
        "labs": [{"test": "AST", "value": "68", "unit": "U/L"}, {"test": "ALT", "value": "52", "unit": "U/L"}, {"test": "Bilirubin Total", "value": "2.4", "unit": "mg/dL"}, {"test": "Albumin", "value": "2.6", "unit": "g/dL"}, {"test": "INR", "value": "1.4", "unit": ""}, {"test": "Platelets", "value": "98", "unit": "K/uL"}, {"test": "Ammonia", "value": "62", "unit": "umol/L"}, {"test": "MELD", "value": "21", "unit": ""}],
        "vitals": [],
        "hcc_codes": [28, 138],
        "summary": "62-year-old female with worsening hepatic function. MELD increased from 18 to 21 with declining albumin and rising bilirubin. Concurrent CKD Stage IIIB stable.",
        "quality": 0.85, "processing_time": 2960, "tokens": 1340,
        "patient_name_detected": "Sarah Martin", "patient_dob_detected": "1963-11-02",
        "meat": {"M": "MELD 21 (up from 18), Albumin 2.6, Bilirubin 2.4, INR 1.4, Platelets 98K", "E": "Progressive hepatic decompensation", "A": "Labs for transplant workup monitoring", "T": "Urgent hepatology follow-up, transplant evaluation acceleration"},
        "suspects": [{"condition": "Hepatic encephalopathy", "rationale": "Ammonia 62 elevated in setting of decompensated cirrhosis"}],
    },
    # 18: PID 1 - Robert Johnson - 2nd doc, Lab Report (analyzed)
    {
        "patient_id": 1, "document_name": "Lab_Report_Johnson_Dorothy_Marie_20260405.pdf",
        "document_type": "lab_report", "file_size_bytes": 76800, "page_count": 1,
        "source": "ehr_pull", "encounter_date": "2026-04-05", "provider_name": "Dr. Michael Torres",
        "status": "analyzed", "created_at": "2026-04-06 07:00:00",
        "extracted_text": None,
        "diagnoses": [
            {"icd10": "E11.65", "desc": "Type 2 diabetes with hyperglycemia", "hcc": 38, "conf": 0.94, "page": 1, "evidence": "HbA1c 8.1% elevated, fasting glucose 178", "confirmed": 0},
            {"icd10": "E11.9", "desc": "Type 2 diabetes without complications", "hcc": None, "conf": 0.88, "page": 1, "evidence": "Type 2 DM on metformin and glipizide", "confirmed": 0},
            {"icd10": "E78.5", "desc": "Hyperlipidemia, unspecified", "hcc": None, "conf": 0.85, "page": 1, "evidence": "TC 228, LDL 142, TG 205", "confirmed": 0},
        ],
        "medications": ["Metformin 1000mg BID", "Glipizide 10mg daily", "Atorvastatin 40mg daily", "Lisinopril 10mg daily"],
        "labs": [{"test": "HbA1c", "value": "8.1", "unit": "%"}, {"test": "Fasting glucose", "value": "178", "unit": "mg/dL"}, {"test": "Creatinine", "value": "1.1", "unit": "mg/dL"}, {"test": "eGFR", "value": "58", "unit": "mL/min"}, {"test": "TC", "value": "228", "unit": "mg/dL"}, {"test": "LDL", "value": "142", "unit": "mg/dL"}],
        "vitals": [],
        "hcc_codes": [38],
        "summary": "Lab report for Dorothy Marie Johnson, 78F. Diabetes monitoring labs. HbA1c elevated at 8.1% indicating poor glycemic control. Renal function stable. Lipids slightly elevated.",
        "quality": 0.948, "processing_time": 4100, "tokens": 3200,
        "patient_name_detected": "Dorothy Marie Johnson", "patient_dob_detected": None,
        "meat": {"M": "HbA1c 8.1% (up from 7.8%), fasting glucose 178, eGFR 58", "E": "Worsening glycemic control despite current regimen", "A": "Add Jardiance 10mg daily, increase Metformin to 1000mg BID, dietary counseling referral", "T": "HbA1c every 3 months"},
        "suspects": [],
    },
    # 19: PID 28 - Dorothy Wright, 80F - Progress Note
    {
        "patient_id": 28, "document_name": "Progress_Note_Wright_Dorothy_20260218.pdf",
        "document_type": "progress_note", "file_size_bytes": 245000, "page_count": 4,
        "source": "emr_sync", "encounter_date": "2026-02-18", "provider_name": "Dr. Sarah Mitchell",
        "status": "analyzed", "created_at": "2026-04-06 13:32:26",
        "extracted_text": None,
        "diagnoses": [
            {"icd10": "G20", "desc": "Parkinson disease", "hcc": 78, "conf": 0.96, "page": 1, "evidence": "Parkinson disease, bilateral resting tremor, cogwheel rigidity, Hoehn-Yahr Stage 3", "confirmed": 1},
            {"icd10": "F03.90", "desc": "Unspecified dementia without behavioral disturbance", "hcc": 52, "conf": 0.93, "page": 1, "evidence": "Vascular dementia, MMSE 18/30 declining", "confirmed": 1},
            {"icd10": "I50.9", "desc": "Heart failure, unspecified", "hcc": 85, "conf": 0.91, "page": 2, "evidence": "CHF stable on current diuretic regimen, BNP 285", "confirmed": 0},
            {"icd10": "I48.91", "desc": "Unspecified atrial fibrillation", "hcc": 96, "conf": 0.90, "page": 2, "evidence": "AF rate-controlled on metoprolol, on apixaban for stroke prevention", "confirmed": 0},
        ],
        "medications": ["Carbidopa-Levodopa 25/100 TID", "Donepezil 10mg daily", "Furosemide 40mg daily", "Metoprolol 50mg BID", "Apixaban 5mg BID", "Lisinopril 20mg daily"],
        "labs": [{"test": "BNP", "value": "285", "unit": "pg/mL"}, {"test": "Na", "value": "138", "unit": "mEq/L"}, {"test": "Cr", "value": "1.3", "unit": "mg/dL"}, {"test": "eGFR", "value": "42", "unit": "mL/min"}],
        "vitals": [],
        "hcc_codes": [78, 52, 85, 96],
        "summary": "Progress note for Dorothy Wright, 80F. Complex patient with Parkinson disease, vascular dementia, CHF, and atrial fibrillation. Neurological exam shows bilateral resting tremor, cogwheel rigidity. MMSE 18/30 declining. CHF stable on current diuretic regimen. AF rate-controlled.",
        "quality": 0.965, "processing_time": 5200, "tokens": 4100,
        "patient_name_detected": "Dorothy Wright", "patient_dob_detected": None,
        "meat": {"M": "MMSE trending 22->20->18 over 18 months. BNP stable. Weight stable.", "E": "Parkinson: Hoehn-Yahr Stage 3. Dementia: progressive decline. CHF: NYHA Class II stable. AF: rate controlled.", "A": "Carbidopa-Levodopa optimized. Donepezil continued. Diuretic dose maintained. Apixaban for stroke prevention.", "T": "Carbidopa-Levodopa optimized. Donepezil continued. Diuretic dose maintained. Apixaban for stroke prevention."},
        "suspects": [],
    },
    # 20: PID 28 - Dorothy Wright, 80F - Cardiology Consult
    {
        "patient_id": 28, "document_name": "Cardiology_Consult_Wright_Dorothy_20251105.pdf",
        "document_type": "consultation", "file_size_bytes": 312000, "page_count": 6,
        "source": "emr_sync", "encounter_date": "2025-11-05", "provider_name": "Dr. Michael Torres",
        "status": "analyzed", "created_at": "2026-04-06 13:32:26",
        "extracted_text": None,
        "diagnoses": [
            {"icd10": "I50.9", "desc": "Heart failure, unspecified", "hcc": 85, "conf": 0.95, "page": 1, "evidence": "Systolic heart failure with AF, EF 35%, NYHA Class II-III", "confirmed": 1},
            {"icd10": "I48.91", "desc": "Unspecified atrial fibrillation", "hcc": 96, "conf": 0.93, "page": 1, "evidence": "AF with controlled ventricular rate on metoprolol", "confirmed": 0},
        ],
        "medications": ["Metoprolol succinate 50mg BID", "Apixaban 5mg BID", "Furosemide 40mg daily", "Lisinopril 20mg daily", "Spironolactone 25mg daily"],
        "labs": [{"test": "EF", "value": "35", "unit": "%"}, {"test": "BNP", "value": "310", "unit": "pg/mL"}],
        "vitals": [],
        "hcc_codes": [85, 96],
        "summary": "Cardiology consultation for Dorothy Wright, 80F. Referred for CHF management and AF rate control. Echocardiogram shows EF 35%, moderate LV dilation. AF with controlled ventricular rate. Recommended titrating metoprolol and continuing DOAC.",
        "quality": 0.952, "processing_time": 4800, "tokens": 3800,
        "patient_name_detected": "Dorothy Wright", "patient_dob_detected": None,
        "meat": {"M": "Serial echo shows EF decline from 40% to 35%", "E": "NYHA Class II-III, Echo EF 35%", "A": "Add spironolactone 25mg, titrate metoprolol to 75mg BID, cardiology follow-up 3 months", "T": "Add spironolactone 25mg, titrate metoprolol to 75mg BID, cardiology follow-up 3 months"},
        "suspects": [],
    },
    # 21: PID 16 - Charles Moore, 87M - Annual Wellness Visit
    {
        "patient_id": 16, "document_name": "AWV_Moore_Charles_20260110.pdf",
        "document_type": "annual_wellness", "file_size_bytes": 380000, "page_count": 8,
        "source": "emr_sync", "encounter_date": "2026-01-10", "provider_name": "Dr. Lisa Wong",
        "status": "analyzed", "created_at": "2026-04-06 13:32:26",
        "extracted_text": None,
        "diagnoses": [
            {"icd10": "G20", "desc": "Parkinson disease", "hcc": 78, "conf": 0.96, "page": 1, "evidence": "Parkinson disease Hoehn-Yahr 3, on Carbidopa-Levodopa", "confirmed": 1},
            {"icd10": "N18.4", "desc": "Chronic kidney disease, stage 4", "hcc": 137, "conf": 0.95, "page": 2, "evidence": "CKD Stage 4, eGFR 22, Cr 2.8", "confirmed": 1},
            {"icd10": "J44.1", "desc": "COPD with acute exacerbation", "hcc": 112, "conf": 0.93, "page": 2, "evidence": "COPD GOLD D, on tiotropium and albuterol", "confirmed": 0},
            {"icd10": "I50.9", "desc": "Heart failure, unspecified", "hcc": 85, "conf": 0.92, "page": 3, "evidence": "CHF NYHA III, BNP 420", "confirmed": 0},
            {"icd10": "F03.90", "desc": "Unspecified dementia", "hcc": 52, "conf": 0.90, "page": 3, "evidence": "Vascular dementia moderate, MMSE 16/30", "confirmed": 0},
        ],
        "medications": ["Carbidopa-Levodopa 25/250 TID", "Memantine 10mg BID", "Furosemide 60mg daily", "Carvedilol 12.5mg BID", "Tiotropium 18mcg inhaled daily", "Albuterol PRN", "Sodium bicarbonate 650mg TID", "Epoetin alfa 4000u weekly"],
        "labs": [{"test": "eGFR", "value": "22", "unit": "mL/min"}, {"test": "Cr", "value": "2.8", "unit": "mg/dL"}, {"test": "BUN", "value": "42", "unit": "mg/dL"}, {"test": "Hgb", "value": "10.2", "unit": "g/dL"}, {"test": "BNP", "value": "420", "unit": "pg/mL"}, {"test": "Albumin", "value": "3.2", "unit": "g/dL"}],
        "vitals": [],
        "hcc_codes": [78, 137, 112, 85, 52],
        "summary": "Annual wellness visit for Charles Moore, 87M. Complex multimorbid patient with Parkinson disease, CKD Stage 4, COPD, CHF, and vascular dementia. Functional status declining; uses walker. Caregiver present. Advance directive on file. Comprehensive medication reconciliation performed.",
        "quality": 0.978, "processing_time": 6100, "tokens": 5200,
        "patient_name_detected": "Charles Moore", "patient_dob_detected": None,
        "meat": {"M": "CKD labs q3mo, BNP trending up 380->420. Spirometry annually. MMSE 16/30 stable.", "E": "Parkinson Hoehn-Yahr 3. CKD Stage 4 stable. COPD GOLD D. CHF NYHA III. Dementia moderate.", "A": "Nephrology co-managing CKD. Pulmonology managing COPD. Cardiology for CHF. Neurology for Parkinson/dementia. Home health referral.", "T": "Complex multimorbid elderly male. All 5 HCCs active and documented. Palliative goals discussion initiated."},
        "suspects": [],
    },
    # 22: PID 16 - Charles Moore, 87M - Nephrology Consult
    {
        "patient_id": 16, "document_name": "Nephrology_Consult_Moore_Charles_20251202.pdf",
        "document_type": "consultation", "file_size_bytes": 275000, "page_count": 5,
        "source": "emr_sync", "encounter_date": "2025-12-02", "provider_name": "Dr. Amy Nguyen",
        "status": "analyzed", "created_at": "2026-04-06 13:32:26",
        "extracted_text": None,
        "diagnoses": [
            {"icd10": "N18.4", "desc": "Chronic kidney disease, stage 4", "hcc": 137, "conf": 0.95, "page": 1, "evidence": "CKD Stage 4 progressive, eGFR 22, Cr 2.8", "confirmed": 1},
            {"icd10": "D63.1", "desc": "Anemia in chronic kidney disease", "hcc": None, "conf": 0.90, "page": 1, "evidence": "Anemia of CKD on erythropoietin, Hgb 10.2", "confirmed": 0},
            {"icd10": "E87.2", "desc": "Acidosis", "hcc": None, "conf": 0.85, "page": 2, "evidence": "Metabolic acidosis managed with bicarbonate", "confirmed": 0},
        ],
        "medications": ["Sodium bicarbonate 650mg TID", "Epoetin alfa 4000u weekly", "Sevelamer 800mg TID with meals", "Calcitriol 0.25mcg daily"],
        "labs": [{"test": "eGFR", "value": "22", "unit": "mL/min"}, {"test": "Cr", "value": "2.8", "unit": "mg/dL"}, {"test": "Phos", "value": "5.2", "unit": "mg/dL"}, {"test": "PTH", "value": "188", "unit": "pg/mL"}, {"test": "Hgb", "value": "10.2", "unit": "g/dL"}, {"test": "Ferritin", "value": "180", "unit": "ng/mL"}],
        "vitals": [],
        "hcc_codes": [137],
        "summary": "Nephrology consultation for Charles Moore, 87M. CKD Stage 4 with eGFR 22. Anemia of CKD on erythropoietin. Metabolic acidosis managed with bicarbonate. Discussion of conservative vs dialysis pathway given comorbidities.",
        "quality": 0.941, "processing_time": 4500, "tokens": 3600,
        "patient_name_detected": "Charles Moore", "patient_dob_detected": None,
        "meat": {"M": "eGFR declining from 28 to 22 over 12 months. Hgb improved from 9.6 to 10.2 on EPO.", "E": "CKD Stage 4 progressive. Anemia responding to EPO. Metabolic acidosis compensated.", "A": "Continue EPO, bicarbonate, phosphate binder. Avoid nephrotoxins. Palliative care referral if further decline.", "T": "Progressive CKD likely to reach ESRD within 12-18 months. Patient prefers conservative management."},
        "suspects": [],
    },
    # 23: PID 30 - Karen Green, 94F - Discharge Summary
    {
        "patient_id": 30, "document_name": "Discharge_Summary_Green_Karen_20260125.pdf",
        "document_type": "discharge_summary", "file_size_bytes": 420000, "page_count": 7,
        "source": "emr_sync", "encounter_date": "2026-01-25", "provider_name": "Dr. Sarah Mitchell",
        "status": "analyzed", "created_at": "2026-04-06 13:32:26",
        "extracted_text": None,
        "diagnoses": [
            {"icd10": "J44.1", "desc": "COPD with acute exacerbation", "hcc": 112, "conf": 0.96, "page": 1, "evidence": "COPD exacerbation with acute-on-chronic CHF, IV steroids, nebulizers", "confirmed": 1},
            {"icd10": "I50.9", "desc": "Heart failure, unspecified", "hcc": 85, "conf": 0.94, "page": 1, "evidence": "Acute-on-chronic CHF, BNP 580 on admit, bilateral pleural effusions", "confirmed": 1},
            {"icd10": "I63.9", "desc": "Cerebral infarction, unspecified", "hcc": 100, "conf": 0.91, "page": 2, "evidence": "History of CVA with residual mild hemiparesis, CT head stable old infarct", "confirmed": 0},
            {"icd10": "N18.4", "desc": "CKD Stage 4", "hcc": 137, "conf": 0.90, "page": 2, "evidence": "CKD Stage 4, Cr 3.1 admit -> 2.6 discharge, eGFR 18", "confirmed": 0},
            {"icd10": "F03.90", "desc": "Unspecified dementia", "hcc": 52, "conf": 0.88, "page": 3, "evidence": "Vascular dementia, MMSE 15/30", "confirmed": 0},
        ],
        "medications": ["Prednisone taper 40mg x5d then 20mg x5d", "Tiotropium 18mcg daily", "Albuterol/Ipratropium neb Q6H", "Furosemide 80mg daily", "Carvedilol 6.25mg BID", "Aspirin 81mg daily", "Donepezil 5mg daily", "Home O2 2L NC"],
        "labs": [{"test": "BNP admit", "value": "580", "unit": "pg/mL"}, {"test": "BNP discharge", "value": "320", "unit": "pg/mL"}, {"test": "Cr admit", "value": "3.1", "unit": "mg/dL"}, {"test": "Cr discharge", "value": "2.6", "unit": "mg/dL"}, {"test": "eGFR", "value": "18", "unit": "mL/min"}],
        "vitals": [],
        "hcc_codes": [112, 85, 100, 137, 52],
        "summary": "Discharge summary for Karen Green, 94F. Admitted for COPD exacerbation with acute-on-chronic CHF. History of CVA with residual mild hemiparesis, CKD Stage 4, and vascular dementia. Treated with IV steroids, nebulizers, and diuresis. Improved and discharged with home oxygen.",
        "quality": 0.972, "processing_time": 5800, "tokens": 4800,
        "patient_name_detected": "Karen Green", "patient_dob_detected": None,
        "meat": {"M": "Daily weights, I/O, BNP trending. SpO2 monitoring. Renal function daily.", "E": "COPD exacerbation overlapping CHF decompensation. CT head stable old infarct. MMSE 15/30.", "A": "Steroid taper, home O2, increased diuretic, home health for monitoring, nephrology and pulmonology follow-up.", "T": "Acute COPD/CHF overlap resolved. 5 active HCCs documented. High complexity care."},
        "suspects": [],
    },
    # 24: PID 19 - Elizabeth White, 92F - Neurology Note
    {
        "patient_id": 19, "document_name": "Neurology_Note_White_Elizabeth_20260305.pdf",
        "document_type": "consultation", "file_size_bytes": 290000, "page_count": 5,
        "source": "emr_sync", "encounter_date": "2026-03-05", "provider_name": "Dr. Michael Torres",
        "status": "analyzed", "created_at": "2026-04-06 13:32:26",
        "extracted_text": None,
        "diagnoses": [
            {"icd10": "F03.90", "desc": "Unspecified dementia", "hcc": 52, "conf": 0.95, "page": 1, "evidence": "Progressive vascular dementia, MMSE decline from 18 to 14 over 12 months", "confirmed": 1},
            {"icd10": "I63.9", "desc": "Cerebral infarction, unspecified", "hcc": 100, "conf": 0.93, "page": 1, "evidence": "History of CVA (2023) with residual left-sided weakness, MRI chronic left MCA infarct", "confirmed": 1},
            {"icd10": "G40.909", "desc": "Epilepsy, unspecified, not intractable", "hcc": 79, "conf": 0.92, "page": 2, "evidence": "Post-stroke epilepsy controlled on levetiracetam, seizure-free 8 months", "confirmed": 0},
            {"icd10": "I50.9", "desc": "Heart failure, unspecified", "hcc": 85, "conf": 0.88, "page": 2, "evidence": "CHF managed with furosemide and carvedilol", "confirmed": 0},
            {"icd10": "N18.4", "desc": "CKD Stage 4", "hcc": 137, "conf": 0.86, "page": 3, "evidence": "CKD Stage 4 on record", "confirmed": 0},
        ],
        "medications": ["Levetiracetam 500mg BID", "Donepezil 10mg daily", "Aspirin 81mg daily", "Furosemide 40mg daily", "Carvedilol 6.25mg BID"],
        "labs": [{"test": "Levetiracetam level", "value": "18", "unit": "mcg/mL"}],
        "vitals": [],
        "hcc_codes": [52, 100, 79, 85, 137],
        "summary": "Neurology follow-up for Elizabeth White, 92F. History of CVA (2023) with residual left-sided weakness, post-stroke epilepsy controlled on levetiracetam, and progressive vascular dementia. Also managing CHF and CKD Stage 4. Seizure-free 8 months. Cognitive decline progressing.",
        "quality": 0.958, "processing_time": 5100, "tokens": 4200,
        "patient_name_detected": "Elizabeth White", "patient_dob_detected": None,
        "meat": {"M": "Seizure diary reviewed - seizure-free 8 months. MMSE decline from 18 to 14 over 12 months.", "E": "Post-stroke epilepsy well controlled. Vascular dementia progressive. MRI stable chronic infarct.", "A": "Continue levetiracetam. Donepezil maintained. PT/OT referral. Caregiver support resources.", "T": "5 active HCC conditions. Epilepsy controlled. Dementia progressive. Functional decline."},
        "suspects": [],
    },
    # 25: PID 25 - George Robinson, 90M - ID Clinic Note
    {
        "patient_id": 25, "document_name": "ID_Clinic_Note_Robinson_George_20260220.pdf",
        "document_type": "progress_note", "file_size_bytes": 310000, "page_count": 5,
        "source": "emr_sync", "encounter_date": "2026-02-20", "provider_name": "Dr. Robert Kim",
        "status": "analyzed", "created_at": "2026-04-06 13:32:27",
        "extracted_text": None,
        "diagnoses": [
            {"icd10": "B20", "desc": "HIV disease", "hcc": 1, "conf": 0.97, "page": 1, "evidence": "HIV on stable ART with undetectable viral load and CD4 580", "confirmed": 1},
            {"icd10": "E11.9", "desc": "Type 2 diabetes mellitus without complications", "hcc": 37, "conf": 0.92, "page": 1, "evidence": "Type 2 DM on metformin, HbA1c 7.2%", "confirmed": 0},
            {"icd10": "N18.3", "desc": "CKD Stage 3", "hcc": 141, "conf": 0.90, "page": 2, "evidence": "CKD Stage 3, eGFR 48, Cr 1.6", "confirmed": 0},
            {"icd10": "F33.0", "desc": "Major depressive disorder, recurrent, mild", "hcc": 155, "conf": 0.88, "page": 2, "evidence": "MDD on sertraline, PHQ-9 score 6 (mild)", "confirmed": 0},
        ],
        "medications": ["Biktarvy (bictegravir/emtricitabine/TAF) 1 tab daily", "Metformin 500mg BID", "Sertraline 100mg daily", "Lisinopril 10mg daily", "Atorvastatin 20mg daily"],
        "labs": [{"test": "HIV VL", "value": "<20", "unit": "copies"}, {"test": "CD4", "value": "580", "unit": "cells/uL"}, {"test": "HbA1c", "value": "7.2", "unit": "%"}, {"test": "eGFR", "value": "48", "unit": "mL/min"}, {"test": "Cr", "value": "1.6", "unit": "mg/dL"}],
        "vitals": [],
        "hcc_codes": [1, 37, 141, 155],
        "summary": "Infectious disease clinic note for George Robinson, 90M. HIV on stable ART with undetectable viral load and CD4 580. Also managing Type 2 DM, CKD Stage 3, and major depressive disorder. Compliant with medications. Depression stable on sertraline.",
        "quality": 0.962, "processing_time": 4900, "tokens": 4000,
        "patient_name_detected": "George Robinson", "patient_dob_detected": None,
        "meat": {"M": "HIV VL undetectable x 5 years. CD4 stable >500. HbA1c trending 7.0->7.2. eGFR stable 48-50. PHQ-9 score 6 (mild).", "E": "HIV well controlled on Biktarvy. DM fair control. CKD stable. Depression managed.", "A": "Continue ART, metformin, sertraline. Annual diabetic eye exam due. Renal follow-up 6 months.", "T": "4 active HCCs. HIV virologically suppressed. DM and CKD stable. Depression in partial remission."},
        "suspects": [],
    },
    # 26: PID 23 - Nancy Walker, 83F - Progress Note
    {
        "patient_id": 23, "document_name": "Progress_Note_Walker_Nancy_20260312.pdf",
        "document_type": "progress_note", "file_size_bytes": 265000, "page_count": 4,
        "source": "emr_sync", "encounter_date": "2026-03-12", "provider_name": "Dr. Sarah Mitchell",
        "status": "analyzed", "created_at": "2026-04-06 13:32:27",
        "extracted_text": None,
        "diagnoses": [
            {"icd10": "N18.3", "desc": "CKD Stage 3", "hcc": 141, "conf": 0.93, "page": 1, "evidence": "CKD Stage 3, eGFR 52, Cr 1.2", "confirmed": 0},
            {"icd10": "I50.9", "desc": "Heart failure, unspecified", "hcc": 85, "conf": 0.92, "page": 1, "evidence": "CHF NYHA II, BNP 180, compensated", "confirmed": 0},
            {"icd10": "I48.91", "desc": "Unspecified atrial fibrillation", "hcc": 96, "conf": 0.91, "page": 2, "evidence": "AF rate controlled on metoprolol, on apixaban", "confirmed": 0},
            {"icd10": "E11.9", "desc": "Type 2 DM without complications", "hcc": 37, "conf": 0.89, "page": 2, "evidence": "Type 2 DM, HbA1c 7.4% improved", "confirmed": 0},
        ],
        "medications": ["Metformin 500mg daily (renal-dosed)", "Apixaban 5mg BID", "Furosemide 20mg daily", "Metoprolol 25mg BID", "Lisinopril 10mg daily"],
        "labs": [{"test": "eGFR", "value": "52", "unit": "mL/min"}, {"test": "Cr", "value": "1.2", "unit": "mg/dL"}, {"test": "HbA1c", "value": "7.4", "unit": "%"}, {"test": "BNP", "value": "180", "unit": "pg/mL"}],
        "vitals": [],
        "hcc_codes": [141, 85, 96, 37],
        "summary": "Follow-up for Nancy Walker, 83F. Managing CKD Stage 3, CHF NYHA II, atrial fibrillation, and Type 2 DM. Stable on current regimen. Renal function unchanged. A1c improved to 7.4%.",
        "quality": 0.938, "processing_time": 4200, "tokens": 3400,
        "patient_name_detected": "Nancy Walker", "patient_dob_detected": None,
        "meat": {"M": "eGFR stable 50-52 over 12 months. BNP improved from 220 to 180. A1c down from 7.8 to 7.4.", "E": "CKD stable Stage 3. CHF compensated. AF rate controlled. DM improving.", "A": "Continue current regimen. Renal labs in 3 months. Cardiology annual follow-up.", "T": "4 active HCCs all well managed. Stable clinical course."},
        "suspects": [],
    },
    # 27: PID 26 - Helen Young, 73F - Oncology Note
    {
        "patient_id": 26, "document_name": "Oncology_Note_Young_Helen_20260128.pdf",
        "document_type": "consultation", "file_size_bytes": 340000, "page_count": 6,
        "source": "emr_sync", "encounter_date": "2026-01-28", "provider_name": "Dr. Amy Nguyen",
        "status": "analyzed", "created_at": "2026-04-06 13:32:27",
        "extracted_text": None,
        "diagnoses": [
            {"icd10": "C34.90", "desc": "Malignant neoplasm of unspecified part of bronchus or lung", "hcc": 12, "conf": 0.96, "page": 1, "evidence": "Lung cancer RUL NSCLC Stage IIIA, status post chemoradiation, surveillance", "confirmed": 1},
            {"icd10": "J44.1", "desc": "COPD with acute exacerbation", "hcc": 112, "conf": 0.91, "page": 2, "evidence": "COPD GOLD C, FEV1 52% predicted, limiting function", "confirmed": 0},
            {"icd10": "E11.9", "desc": "Type 2 DM without complications", "hcc": 37, "conf": 0.88, "page": 2, "evidence": "Type 2 DM on metformin and glipizide, HbA1c 7.6%", "confirmed": 0},
        ],
        "medications": ["Tiotropium 18mcg daily", "Albuterol PRN", "Metformin 1000mg BID", "Glipizide 5mg daily", "Prednisone 5mg daily (maintenance)"],
        "labs": [{"test": "CEA", "value": "3.2", "unit": "ng/mL"}, {"test": "FEV1", "value": "52", "unit": "% predicted"}, {"test": "HbA1c", "value": "7.6", "unit": "%"}],
        "vitals": [],
        "hcc_codes": [12, 112, 37],
        "summary": "Oncology follow-up for Helen Young, 73F. Lung cancer (right upper lobe NSCLC Stage IIIA) status post chemoradiation, currently on surveillance. Also managing COPD and Type 2 DM. CT chest shows stable post-treatment changes. No evidence of recurrence.",
        "quality": 0.951, "processing_time": 5000, "tokens": 4100,
        "patient_name_detected": "Helen Young", "patient_dob_detected": None,
        "meat": {"M": "CT surveillance q6 months. CEA q3 months. PFTs annually. A1c q3 months.", "E": "NSCLC Stage IIIA post-chemoradiation, NED at 14 months. COPD GOLD C. DM fair control.", "A": "Continue surveillance imaging. Pulmonary rehab ongoing. Increase glipizide to 10mg for better glycemic control.", "T": "3 active HCCs. Cancer in remission under surveillance. COPD limiting function. DM needs optimization."},
        "suspects": [],
    },
    # 28: PID 21 - Susan Clark, 65F - Rheumatology Note
    {
        "patient_id": 21, "document_name": "Rheumatology_Note_Clark_Susan_20260215.pdf",
        "document_type": "consultation", "file_size_bytes": 285000, "page_count": 4,
        "source": "emr_sync", "encounter_date": "2026-02-15", "provider_name": "Dr. Michael Torres",
        "status": "analyzed", "created_at": "2026-04-06 13:32:27",
        "extracted_text": None,
        "diagnoses": [
            {"icd10": "M06.9", "desc": "Rheumatoid arthritis, unspecified", "hcc": 40, "conf": 0.95, "page": 1, "evidence": "RA with active symmetric polyarthritis, DAS28 score 3.8, on methotrexate and adalimumab", "confirmed": 1},
            {"icd10": "E11.9", "desc": "Type 2 DM without complications", "hcc": 37, "conf": 0.90, "page": 2, "evidence": "Type 2 DM on metformin, HbA1c 7.1%", "confirmed": 0},
            {"icd10": "F33.0", "desc": "Major depressive disorder, recurrent, mild", "hcc": 155, "conf": 0.88, "page": 2, "evidence": "MDD on duloxetine, PHQ-9 score 8", "confirmed": 0},
        ],
        "medications": ["Methotrexate 15mg weekly", "Adalimumab 40mg biweekly", "Folic acid 1mg daily", "Metformin 500mg BID", "Duloxetine 60mg daily", "Prednisone 5mg daily"],
        "labs": [{"test": "ESR", "value": "38", "unit": "mm/hr"}, {"test": "CRP", "value": "1.8", "unit": "mg/dL"}, {"test": "HbA1c", "value": "7.1", "unit": "%"}, {"test": "PHQ-9", "value": "8", "unit": ""}],
        "vitals": [],
        "hcc_codes": [40, 37, 155],
        "summary": "Rheumatology follow-up for Susan Clark, 65F. Rheumatoid arthritis with active symmetric polyarthritis on methotrexate and adalimumab. Also managing Type 2 DM and major depressive disorder. DAS28 score 3.8 (moderate activity). Depression stable.",
        "quality": 0.945, "processing_time": 4600, "tokens": 3700,
        "patient_name_detected": "Susan Clark", "patient_dob_detected": None,
        "meat": {"M": "DAS28 trending 4.2->3.8 on adalimumab. ESR/CRP improving. PHQ-9 stable at 8.", "E": "RA moderate disease activity improving on biologic. DM controlled. Depression mild-moderate.", "A": "Continue adalimumab and methotrexate. Taper prednisone to 2.5mg. Duloxetine dual benefit for depression and pain.", "T": "3 active HCCs. RA responding to adalimumab. Consider DMARD adjustment if not at goal by 3 months."},
        "suspects": [],
    },
    # 29: PID 17 - Patricia Davis, 78F - Cardiology Note
    {
        "patient_id": 17, "document_name": "Cardiology_Note_Davis_Patricia_20260130.pdf",
        "document_type": "consultation", "file_size_bytes": 295000, "page_count": 5,
        "source": "emr_sync", "encounter_date": "2026-01-30", "provider_name": "Dr. James Patel",
        "status": "analyzed", "created_at": "2026-04-06 13:32:27",
        "extracted_text": None,
        "diagnoses": [
            {"icd10": "I48.91", "desc": "Unspecified atrial fibrillation", "hcc": 96, "conf": 0.94, "page": 1, "evidence": "AF with RVR event in December, now rate controlled on metoprolol", "confirmed": 1},
            {"icd10": "I50.9", "desc": "Heart failure, unspecified", "hcc": 85, "conf": 0.92, "page": 1, "evidence": "CHF with preserved EF 55%, HFpEF, mild diastolic dysfunction", "confirmed": 0},
            {"icd10": "E11.9", "desc": "Type 2 DM without complications", "hcc": 37, "conf": 0.88, "page": 2, "evidence": "Type 2 DM on metformin, HbA1c 7.3%", "confirmed": 0},
        ],
        "medications": ["Metoprolol succinate 100mg daily", "Apixaban 5mg BID", "Furosemide 20mg daily", "Lisinopril 20mg daily", "Metformin 1000mg BID"],
        "labs": [{"test": "EF", "value": "55", "unit": "%"}, {"test": "BNP", "value": "165", "unit": "pg/mL"}, {"test": "HbA1c", "value": "7.3", "unit": "%"}],
        "vitals": [],
        "hcc_codes": [96, 85, 37],
        "summary": "Cardiology follow-up for Patricia Davis, 78F. AF with RVR event in December, now rate controlled. CHF with preserved EF (55%). Type 2 DM on metformin. Stable. Echo shows mild diastolic dysfunction.",
        "quality": 0.939, "processing_time": 4400, "tokens": 3500,
        "patient_name_detected": "Patricia Davis", "patient_dob_detected": None,
        "meat": {"M": "HR and rhythm on telemetry patch x 2 weeks - AF rate controlled. BNP down from 210 to 165. Weight stable.", "E": "AF rate controlled on metoprolol 100mg. HFpEF stable. DM fair control.", "A": "Continue rate control and anticoagulation. Sodium restriction reinforced. Follow-up 3 months.", "T": "3 active HCCs. AF now stable after December RVR. CHF compensated. DM needs slight improvement."},
        "suspects": [],
    },
]

doc_id_map = {}  # index -> doc_id
analysis_id_map = {}  # index -> analysis_id

for i, doc in enumerate(documents):
    file_hash = hashlib.sha256(f"demo_{doc['document_name']}_{i}".encode()).hexdigest()
    file_path = f"/uploads/demo/{doc['document_name']}"

    cur.execute("""
        INSERT INTO documents (tenant_id, patient_id, document_name, document_type, file_type,
            file_size_bytes, file_path, file_hash, page_count, source, encounter_date,
            provider_name, status, uploaded_by, created_at, updated_at)
        VALUES (%s,%s,%s,%s,'pdf',%s,%s,%s,%s,%s,%s,%s,%s,'1',%s,%s)
    """, ('default', doc['patient_id'], doc['document_name'], doc['document_type'],
          doc['file_size_bytes'], file_path, file_hash, doc['page_count'], doc['source'],
          doc['encounter_date'], doc['provider_name'], doc['status'],
          doc['created_at'], doc['created_at']))

    doc_id = cur.lastrowid
    doc_id_map[i] = doc_id

    # Insert analysis for analyzed documents
    if doc['status'] == 'analyzed':
        cur.execute("""
            INSERT INTO document_analysis (document_id, analysis_type, gemini_model,
                extracted_text, extracted_diagnoses, extracted_medications, extracted_labs,
                extracted_vitals, extracted_procedures, extracted_providers, clinical_summary,
                hcc_codes_found, suspect_conditions, meat_evidence, quality_score,
                processing_time_ms, token_count, status, error_message,
                patient_name_detected, patient_dob_detected, created_at, updated_at)
            VALUES (%s,'full','gemini-2.5-pro',%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'completed',NULL,%s,%s,%s,%s)
        """, (doc_id, doc['extracted_text'],
              json.dumps(doc['diagnoses']), json.dumps(doc['medications']),
              json.dumps(doc['labs']), json.dumps(doc['vitals']),
              json.dumps([]), json.dumps([doc['provider_name']]),
              doc['summary'], json.dumps(doc['hcc_codes']),
              json.dumps(doc['suspects']), json.dumps(doc['meat']),
              doc['quality'], doc['processing_time'], doc['tokens'],
              doc['patient_name_detected'], doc['patient_dob_detected'],
              doc['created_at'], doc['created_at']))

        analysis_id = cur.lastrowid
        analysis_id_map[i] = analysis_id

        # Insert diagnosis lines
        for dx in doc['diagnoses']:
            reviewed_at = doc['created_at'] if dx.get('confirmed') else None
            reviewed_by = '1' if dx.get('confirmed') else None
            review_status = 'confirmed' if dx.get('confirmed') else 'pending'
            is_new_hcc = 1 if dx.get('hcc') else 0

            cur.execute("""
                INSERT INTO document_diagnosis_lines (document_id, analysis_id, icd10_code,
                    icd10_description, hcc_code, confidence_score, page_number, evidence_text,
                    is_confirmed, is_rejected, is_new_hcc, reviewed_by, reviewed_at,
                    created_at, review_status)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,0,%s,%s,%s,%s,%s)
            """, (doc_id, analysis_id, dx['icd10'], dx['desc'],
                  dx.get('hcc'), dx['conf'], dx['page'], dx['evidence'],
                  1 if dx.get('confirmed') else 0,
                  is_new_hcc, reviewed_by, reviewed_at,
                  doc['created_at'], review_status))

    elif doc['status'] == 'error':
        cur.execute("""
            INSERT INTO document_analysis (document_id, analysis_type, gemini_model,
                status, error_message, created_at, updated_at)
            VALUES (%s,'full','gemini-2.5-pro','failed',%s,%s,%s)
        """, (doc_id, doc.get('error_message', 'Unknown error'),
              doc['created_at'], doc['created_at']))

conn.commit()

# Verify
cur.execute("SELECT COUNT(*) FROM documents")
print(f"Documents: {cur.fetchone()[0]}")
cur.execute("SELECT COUNT(*) FROM document_analysis")
print(f"Analyses: {cur.fetchone()[0]}")
cur.execute("SELECT COUNT(*) FROM document_diagnosis_lines")
print(f"Diagnosis lines: {cur.fetchone()[0]}")
cur.execute("SELECT status, COUNT(*) FROM documents GROUP BY status")
print("By status:", cur.fetchall())
cur.execute("SELECT document_type, COUNT(*) FROM documents GROUP BY document_type")
print("By type:", cur.fetchall())
cur.execute("SELECT review_status, COUNT(*) FROM document_diagnosis_lines GROUP BY review_status")
print("Dx review status:", cur.fetchall())

conn.close()
print("\nDone! Demo document data seeded successfully.")
