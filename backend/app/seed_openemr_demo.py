"""
Seed OpenEMR demo data — idempotent.

Called at startup from main.py lifespan.  Every INSERT uses
INSERT IGNORE or checks for existing rows so it is safe to run
repeatedly without duplicating data.
"""
from __future__ import annotations

import logging
from contextlib import suppress

logger = logging.getLogger(__name__)


def seed_openemr_demo() -> None:
    """Populate the OpenEMR database with rich clinical demo data."""
    from app.db import openemr_cursor, NoActiveEMRConnection

    try:
        with openemr_cursor() as cur:
            cur.execute("SELECT 1")
            cur.fetchone()
    except (NoActiveEMRConnection, Exception) as exc:
        logger.info("OpenEMR not available for seeding: %s", exc)
        return

    logger.info("Checking OpenEMR demo data completeness …")

    # ------------------------------------------------------------------
    # Clinical notes — detailed progress notes with ICD-10 codes
    # ------------------------------------------------------------------
    _CLINICAL_NOTES = [
        (1, 1001, '2025-10-15 09:00:00', 'Progress Note',
         'Annual wellness visit. Patient is a 72-year-old male with Type 2 Diabetes Mellitus (E11.65) with hyperglycemia, HbA1c 7.8%. '
         'Also managing Essential Hypertension (I10), currently on Lisinopril 20mg. BMI 31.2, discussed weight management. '
         'Diabetic retinopathy screening ordered. Colonoscopy due. Pneumococcal vaccine administered. '
         'ASSESSMENT: 1) T2DM with hyperglycemia - adjust Metformin to 1000mg BID 2) HTN - well controlled 3) Obesity - lifestyle counseling provided.'),
        (1, 1002, '2026-01-20 14:00:00', 'Progress Note',
         'Diabetes follow-up. HbA1c improved to 7.2%. Fasting glucose 142. Patient reports improved dietary compliance. '
         'Chronic Kidney Disease Stage 3a (N18.31), GFR 52. Microalbuminuria present. Continue current regimen. '
         'ASSESSMENT: 1) T2DM improving 2) CKD Stage 3a - stable 3) HTN controlled on current meds.'),
        (2, 1003, '2025-09-12 10:30:00', 'Progress Note',
         'Hypertension management visit. 68-year-old female with Essential Hypertension (I10), BP today 148/92. '
         'History of Hyperlipidemia (E78.5), LDL 142. Started on Atorvastatin 20mg. '
         'Also noted Peripheral Vascular Disease (I73.9) with intermittent claudication. ABI ordered. '
         'ASSESSMENT: 1) HTN - uncontrolled, increase Amlodipine to 10mg 2) Hyperlipidemia - start statin 3) PVD - workup initiated.'),
        (3, 1004, '2025-11-08 11:00:00', 'Progress Note',
         'CHF management. 78-year-old male with Chronic Systolic Heart Failure (I50.22), EF 30% on last echo. '
         'Weight up 4 lbs, mild peripheral edema. BNP 580. Also managing Chronic Atrial Fibrillation (I48.2) on Warfarin, INR 2.4. '
         'COPD (J44.1) stable. '
         'ASSESSMENT: 1) CHF acute exacerbation - increase Furosemide to 40mg BID 2) AFib - INR therapeutic 3) COPD - continue inhalers.'),
        (3, 1005, '2026-02-14 09:30:00', 'Progress Note',
         'Cardiology follow-up. Echo shows EF 35%, improved from 30%. Weight stable. BNP 320, improved. '
         'Continue optimized HF regimen. Warfarin INR 2.1, therapeutic. COPD stable on Spiriva and Breo. '
         'CKD Stage 4 (N18.4), GFR 22, nephrology co-managing. '
         'ASSESSMENT: 1) CHF - improving on optimized therapy 2) AFib controlled 3) CKD Stage 4 - stable.'),
        (4, 1006, '2025-12-01 15:00:00', 'Progress Note',
         'COPD evaluation. 70-year-old male with COPD GOLD Stage III (J44.1), FEV1 42% predicted. '
         'Experiencing increased dyspnea on exertion. O2 sat 91% on RA. History of Lung Cancer status post lobectomy 2023 (Z85.118). '
         'Depression (F33.1) managed with Sertraline. '
         'ASSESSMENT: 1) COPD severe - add Trelegy Ellipta 2) Monitor for recurrence 3) Depression - stable on current SSRI. Pulmonary rehab referral.'),
        (5, 1007, '2026-01-10 08:00:00', 'Progress Note',
         'CKD Stage 3 follow-up. 65-year-old female with CKD Stage 3b (N18.32), GFR 38. Proteinuria 450mg/day. '
         'Type 2 DM (E11.22) with diabetic nephropathy. HTN (I10) on ACE inhibitor. Anemia of CKD (D63.1), Hgb 10.2. '
         'ASSESSMENT: 1) CKD 3b - progressive, nephrology referral 2) DM nephropathy - optimize glycemic control 3) Anemia - start Epoetin if Hgb drops below 10.'),
        (6, 1008, '2025-10-22 13:00:00', 'Progress Note',
         'Annual exam. 62-year-old female. Major Depressive Disorder recurrent (F33.1), PHQ-9 score 14. '
         'Morbid Obesity BMI 42 (E66.01). Type 2 DM (E11.9) HbA1c 8.1%. Obstructive Sleep Apnea (G47.33) on CPAP. '
         'ASSESSMENT: 1) Depression - increase Duloxetine to 60mg 2) Morbid obesity - bariatric surgery consult '
         '3) DM - poorly controlled, add GLP-1 agonist 4) OSA - CPAP compliance reviewed.'),
        (7, 1009, '2025-11-30 10:00:00', 'Progress Note',
         'Diabetes and hypertension visit. 74-year-old male with T2DM (E11.65), HbA1c 8.4% despite triple therapy. '
         'HTN (I10) BP 156/88. Diabetic Peripheral Neuropathy (E11.42), numbness in feet bilaterally. PAD (I73.9) with reduced pulses. '
         'ASSESSMENT: 1) DM uncontrolled - start insulin Lantus 10 units at bedtime 2) HTN - add Chlorthalidone '
         '3) Neuropathy - start Gabapentin 300mg TID 4) PAD - vascular surgery referral.'),
        (8, 1010, '2026-02-05 09:00:00', 'Progress Note',
         'Atrial fibrillation follow-up. 80-year-old female with Persistent AFib (I48.1), on Eliquis. '
         'CHF with preserved EF (I50.32), EF 55%. Hypothyroidism (E03.9) on Levothyroxine. CKD Stage 3a (N18.31) GFR 48. '
         'Osteoporosis (M81.0) with recent T-score -2.8. '
         'ASSESSMENT: 1) AFib - rate controlled, continue Eliquis 2) HFpEF - stable 3) Hypothyroid - TSH normal '
         '4) CKD - stable 5) Osteoporosis - start Alendronate.'),
        # Patient 9: David Anderson 72M
        (9, 1011, '2025-11-03 09:00:00', 'Progress Note',
         '72M with Type 2 diabetes mellitus with diabetic chronic kidney disease (E11.22) and stage 3 CKD (N18.3). '
         'A1c improved to 7.2% from 8.1%. eGFR stable at 42. Continue metformin 1000mg BID, lisinopril 20mg daily. '
         'Added semaglutide 0.25mg weekly for weight management. BMI 31.2. Bilateral diabetic retinopathy (E11.319) '
         'stable per recent ophthalmology note. Patient also reports intermittent lower back pain. '
         'Screening PHQ-9 score 4 (minimal depression).'),
        # Patient 10: Susan Thomas 65F
        (10, 1012, '2025-12-10 10:30:00', 'Progress Note',
         '65F with essential hypertension (I10) poorly controlled on current regimen. BP today 158/92. '
         'Also managing major depressive disorder, recurrent, moderate (F33.1). PHQ-9 score 14. '
         'Increased amlodipine to 10mg daily, continue sertraline 100mg daily. New diagnosis of prediabetes (R73.03) '
         'with fasting glucose 118. Discussed lifestyle modifications. Obesity (E66.01) with BMI 33.5. Referred to nutritionist.'),
        # Patient 11: Richard Jackson 83M
        (11, 1013, '2026-01-15 08:45:00', 'Progress Note',
         '83M presenting with worsening dyspnea on exertion. History of congestive heart failure, unspecified (I50.9), '
         'now with 2+ pitting edema bilateral lower extremities. BNP elevated at 890. Also has COPD (J44.1) with moderate '
         'obstruction, chronic atrial fibrillation (I48.2). Increased furosemide to 80mg daily, continue carvedilol 25mg BID '
         'and warfarin. CXR shows mild pulmonary congestion. Type 2 diabetes (E11.65) with hyperglycemia, A1c 8.4%. '
         'Peripheral vascular disease (I73.9) noted.'),
        # Patient 12: Jessica White 69F
        (12, 1014, '2026-02-05 11:00:00', 'Progress Note',
         '69F follow-up for COPD (J44.1) with recent exacerbation requiring oral steroids. FEV1 52% predicted. '
         'Continue tiotropium and albuterol PRN. Osteoporosis (M81.0) with T-score -2.8 at lumbar spine. '
         'Started alendronate 70mg weekly. Also managing hypothyroidism (E03.9), TSH 3.2 on levothyroxine 75mcg. '
         'Mild anxiety disorder (F41.1). BP well controlled at 128/76 on lisinopril.'),
        # Patient 13: Charles Harris 76M
        (13, 1015, '2026-02-20 09:30:00', 'Progress Note',
         '76M with chronic atrial fibrillation (I48.2) on apixaban. INR management no longer needed since switch from warfarin. '
         'CKD stage 4 (N18.4) with eGFR 22, nephrology co-managing. Type 2 diabetes with diabetic nephropathy (E11.22). '
         'Peripheral neuropathy (G62.9) in bilateral feet. Benign prostatic hyperplasia (N40.0) with LUTS, on tamsulosin. '
         'Gout (M10.9) with recent flare treated with colchicine. Weight stable.'),
        # Patient 14: Sarah Martin 63F
        (14, 1016, '2026-03-10 14:00:00', 'Progress Note',
         '63F with Type 2 diabetes mellitus without complications (E11.9), A1c 6.9% well controlled on metformin 500mg BID. '
         'Hypothyroidism (E03.9) stable on levothyroxine 100mcg, TSH 2.1. Obesity (E66.01) BMI 34.2, discussed bariatric referral. '
         'New complaint of bilateral knee pain consistent with primary osteoarthritis (M17.0). '
         'Vitamin D deficiency (E55.0), started supplementation 2000 IU daily. Depression screening negative.'),
        # Patient 15: Thomas Thompson 81M
        (15, 1017, '2026-03-25 10:00:00', 'Progress Note',
         '81M with severe COPD (J44.1), FEV1 38% predicted, on home oxygen 2L NC. '
         'Congestive heart failure with reduced ejection fraction (I50.22), EF 30%. '
         'Chronic kidney disease stage 3b (N18.32), eGFR 38. Type 2 diabetes (E11.65) with hyperglycemia, A1c 7.8%. '
         'History of CVA (I63.9) with residual left-sided weakness. Cachexia noted, BMI 18.9, referred to nutrition. '
         'Continue sacubitril/valsartan, carvedilol, insulin glargine.'),
    ]

    # ------------------------------------------------------------------
    # Vitals
    # ------------------------------------------------------------------
    _VITALS = [
        (1, 1001, '2025-10-15 09:00:00', 95.3, 175.0, 138, 82),
        (1, 1002, '2026-01-20 14:00:00', 93.8, 175.0, 132, 78),
        (2, 1003, '2025-09-12 10:30:00', 78.2, 162.0, 148, 92),
        (3, 1004, '2025-11-08 11:00:00', 88.5, 170.0, 142, 88),
        (3, 1005, '2026-02-14 09:30:00', 86.2, 170.0, 136, 82),
        (4, 1006, '2025-12-01 15:00:00', 72.1, 178.0, 128, 76),
        (5, 1007, '2026-01-10 08:00:00', 82.5, 165.0, 144, 86),
        (6, 1008, '2025-10-22 13:00:00', 118.0, 160.0, 140, 88),
        (7, 1009, '2025-11-30 10:00:00', 90.7, 172.0, 156, 88),
        (8, 1010, '2026-02-05 09:00:00', 68.0, 158.0, 130, 78),
        (9, 1011, '2025-11-03 09:00:00', 95.3, 175.0, 138, 82),
        (10, 1012, '2025-12-10 10:30:00', 89.8, 163.0, 158, 92),
        (11, 1013, '2026-01-15 08:45:00', 78.2, 170.0, 142, 88),
        (12, 1014, '2026-02-05 11:00:00', 68.5, 160.0, 128, 76),
        (13, 1015, '2026-02-20 09:30:00', 82.1, 178.0, 134, 80),
        (14, 1016, '2026-03-10 14:00:00', 92.4, 165.0, 126, 78),
        (15, 1017, '2026-03-25 10:00:00', 58.2, 172.0, 118, 70),
    ]

    # ------------------------------------------------------------------
    # Problem list  (lists type='medical_problem')
    # ------------------------------------------------------------------
    _PROBLEMS = [
        # Patient 1: T2DM, HTN, CKD3, Obesity
        (1, 'Type 2 Diabetes Mellitus with hyperglycemia', 'ICD10:E11.65', '2020-03-15', 'HbA1c 7.2%, on Metformin'),
        (1, 'Essential Hypertension', 'ICD10:I10', '2018-06-01', 'Controlled on Lisinopril'),
        (1, 'Chronic Kidney Disease Stage 3a', 'ICD10:N18.31', '2024-08-20', 'GFR 52'),
        (1, 'Obesity', 'ICD10:E66.01', '2019-01-10', 'BMI 31.2'),
        # Patient 2: HTN, Hyperlipidemia, PVD
        (2, 'Essential Hypertension', 'ICD10:I10', '2017-04-20', 'Uncontrolled, adjusting meds'),
        (2, 'Hyperlipidemia', 'ICD10:E78.5', '2023-09-12', 'LDL 142, starting statin'),
        (2, 'Peripheral Vascular Disease', 'ICD10:I73.9', '2025-09-12', 'Intermittent claudication'),
        # Patient 3: CHF, AFib, COPD, CKD4
        (3, 'Chronic Systolic Heart Failure', 'ICD10:I50.22', '2021-05-10', 'EF 35%'),
        (3, 'Chronic Atrial Fibrillation', 'ICD10:I48.2', '2020-08-15', 'On Warfarin, INR therapeutic'),
        (3, 'COPD GOLD Stage III', 'ICD10:J44.1', '2019-03-22', 'FEV1 45%'),
        (3, 'Chronic Kidney Disease Stage 4', 'ICD10:N18.4', '2024-11-08', 'GFR 22'),
        # Patient 4: COPD, Lung Cancer hx, Depression
        (4, 'COPD GOLD Stage III', 'ICD10:J44.1', '2018-12-01', 'Severe, FEV1 42%'),
        (4, 'Personal history of lung cancer', 'ICD10:Z85.118', '2023-06-15', 'Status post lobectomy 2023'),
        (4, 'Major Depressive Disorder recurrent', 'ICD10:F33.1', '2022-04-10', 'On Sertraline'),
        # Patient 5: CKD3b, DM nephropathy, Anemia
        (5, 'CKD Stage 3b', 'ICD10:N18.32', '2023-07-10', 'GFR 38, proteinuria'),
        (5, 'Type 2 DM with diabetic nephropathy', 'ICD10:E11.22', '2020-01-15', 'On insulin'),
        (5, 'Anemia of CKD', 'ICD10:D63.1', '2025-01-10', 'Hgb 10.2'),
        # Patient 6: Depression, Morbid Obesity, DM, OSA
        (6, 'Major Depressive Disorder recurrent', 'ICD10:F33.1', '2021-10-22', 'PHQ-9 score 14'),
        (6, 'Morbid Obesity', 'ICD10:E66.01', '2019-05-01', 'BMI 42'),
        (6, 'Type 2 Diabetes Mellitus', 'ICD10:E11.9', '2022-03-15', 'HbA1c 8.1%'),
        (6, 'Obstructive Sleep Apnea', 'ICD10:G47.33', '2020-10-22', 'On CPAP'),
        # Patient 7: DM, HTN, Neuropathy, PAD
        (7, 'Type 2 DM with hyperglycemia', 'ICD10:E11.65', '2018-11-30', 'HbA1c 8.4%'),
        (7, 'Essential Hypertension', 'ICD10:I10', '2016-05-20', 'BP 156/88'),
        (7, 'Diabetic Peripheral Neuropathy', 'ICD10:E11.42', '2023-11-30', 'Bilateral foot numbness'),
        (7, 'Peripheral Arterial Disease', 'ICD10:I73.9', '2024-06-15', 'Reduced pedal pulses'),
        # Patient 8: AFib, HFpEF, Hypothyroid, CKD3a, Osteoporosis
        (8, 'Persistent Atrial Fibrillation', 'ICD10:I48.1', '2020-02-05', 'On Eliquis'),
        (8, 'Heart Failure with preserved EF', 'ICD10:I50.32', '2022-08-20', 'EF 55%'),
        (8, 'Hypothyroidism', 'ICD10:E03.9', '2015-03-10', 'On Levothyroxine, TSH normal'),
        (8, 'CKD Stage 3a', 'ICD10:N18.31', '2024-02-05', 'GFR 48'),
        (8, 'Osteoporosis', 'ICD10:M81.0', '2025-02-05', 'T-score -2.8'),
        # Patient 9: DM with CKD3, diabetic retinopathy, obesity
        (9, 'Type 2 diabetes with diabetic CKD', 'ICD10:E11.22', '2018-03-15', 'On metformin and semaglutide'),
        (9, 'Chronic kidney disease, stage 3', 'ICD10:N18.3', '2020-06-10', 'eGFR 42, nephrology monitoring'),
        (9, 'Diabetic retinopathy, bilateral', 'ICD10:E11.319', '2021-01-20', 'Stable per ophthalmology'),
        (9, 'Obesity', 'ICD10:E66.01', '2015-05-01', 'BMI 31.2'),
        # Patient 10: HTN, depression, prediabetes, obesity
        (10, 'Essential hypertension', 'ICD10:I10', '2012-07-22', 'Poorly controlled, on amlodipine'),
        (10, 'Major depressive disorder, recurrent, moderate', 'ICD10:F33.1', '2019-11-05', 'On sertraline, PHQ-9 14'),
        (10, 'Prediabetes', 'ICD10:R73.03', '2025-12-10', 'Fasting glucose 118'),
        (10, 'Obesity', 'ICD10:E66.01', '2016-03-01', 'BMI 33.5'),
        # Patient 11: CHF, COPD, AFib, DM, PVD
        (11, 'Congestive heart failure, unspecified', 'ICD10:I50.9', '2017-09-12', 'BNP 890, worsening'),
        (11, 'COPD with acute exacerbation', 'ICD10:J44.1', '2015-04-18', 'Moderate obstruction'),
        (11, 'Chronic atrial fibrillation', 'ICD10:I48.2', '2016-01-30', 'On warfarin'),
        (11, 'Type 2 diabetes with hyperglycemia', 'ICD10:E11.65', '2010-08-05', 'A1c 8.4%'),
        (11, 'Peripheral vascular disease', 'ICD10:I73.9', '2019-06-15', None),
        # Patient 12: COPD, osteoporosis, hypothyroid, anxiety
        (12, 'COPD with acute exacerbation', 'ICD10:J44.1', '2018-02-20', 'FEV1 52% predicted'),
        (12, 'Osteoporosis without fracture', 'ICD10:M81.0', '2022-05-14', 'T-score -2.8 lumbar'),
        (12, 'Hypothyroidism', 'ICD10:E03.9', '2014-09-10', 'TSH 3.2 on levothyroxine'),
        (12, 'Generalized anxiety disorder', 'ICD10:F41.1', '2020-11-01', 'Mild'),
        # Patient 13: AFib, CKD4, DM nephropathy, neuropathy, BPH, gout
        (13, 'Chronic atrial fibrillation', 'ICD10:I48.2', '2016-05-22', 'On apixaban'),
        (13, 'CKD stage 4', 'ICD10:N18.4', '2021-03-08', 'eGFR 22'),
        (13, 'Type 2 diabetes with diabetic nephropathy', 'ICD10:E11.22', '2013-10-15', None),
        (13, 'Peripheral neuropathy', 'ICD10:G62.9', '2019-07-20', 'Bilateral feet'),
        (13, 'Benign prostatic hyperplasia', 'ICD10:N40.0', '2018-12-01', 'On tamsulosin'),
        (13, 'Gout', 'ICD10:M10.9', '2020-04-15', 'Recent flare'),
        # Patient 14: DM controlled, hypothyroid, obesity, knee OA
        (14, 'Type 2 diabetes without complications', 'ICD10:E11.9', '2019-06-30', 'A1c 6.9%, well controlled'),
        (14, 'Hypothyroidism', 'ICD10:E03.9', '2017-01-15', 'TSH 2.1 on levothyroxine'),
        (14, 'Obesity', 'ICD10:E66.01', '2015-08-20', 'BMI 34.2'),
        (14, 'Primary osteoarthritis, bilateral knees', 'ICD10:M17.0', '2026-03-10', 'New diagnosis'),
        (14, 'Vitamin D deficiency', 'ICD10:E55.0', '2026-03-10', 'Started supplementation'),
        # Patient 15: Severe COPD, HFrEF, CKD 3b, DM, CVA history
        (15, 'COPD, severe', 'ICD10:J44.1', '2014-11-05', 'FEV1 38%, on home O2'),
        (15, 'Heart failure with reduced EF', 'ICD10:I50.22', '2018-07-20', 'EF 30%'),
        (15, 'CKD stage 3b', 'ICD10:N18.32', '2020-09-12', 'eGFR 38'),
        (15, 'Type 2 diabetes with hyperglycemia', 'ICD10:E11.65', '2012-03-01', 'A1c 7.8%'),
        (15, 'Cerebrovascular accident', 'ICD10:I63.9', '2022-06-15', 'Residual left-sided weakness'),
    ]

    # ------------------------------------------------------------------
    # Allergies
    # ------------------------------------------------------------------
    _ALLERGIES = [
        (1, 'Penicillin', '2010-01-01', 'Rash'),
        (2, 'Lisinopril', '2017-04-10', 'Dry cough, switched to ARB'),
        (3, 'Sulfonamides', '2015-06-01', 'Anaphylaxis'),
        (4, 'Aspirin', '2016-11-20', 'Bronchospasm - aspirin-exacerbated respiratory disease'),
        (5, 'NSAIDs', '2018-03-15', 'GI bleeding risk with CKD'),
        (6, 'Codeine', '2020-08-01', 'Nausea/vomiting'),
        (7, 'Metformin', '2019-02-14', 'Severe GI intolerance, lactic acidosis risk with CKD'),
        (8, 'ACE Inhibitors', '2019-12-01', 'Angioedema'),
        (9, 'Penicillin', '2010-01-01', 'Rash'),
        (10, 'Tramadol', '2021-06-15', 'Seizure risk with SSRI interaction'),
        (11, 'Sulfa drugs', '2005-03-15', 'Hives'),
        (12, 'Erythromycin', '2014-08-22', 'GI upset, QT prolongation concern'),
        (13, 'Iodine contrast', '2018-06-01', 'Anaphylaxis - premedicate'),
        (14, 'Latex', '2020-03-05', 'Contact dermatitis'),
        (15, 'ACE inhibitors', '2016-09-10', 'Angioedema'),
    ]

    # ------------------------------------------------------------------
    # Insurance data
    # ------------------------------------------------------------------
    # ------------------------------------------------------------------
    # Insurance — realistic CMS-HCC MA plans with MBIs
    # (pid, type, provider, plan_name, subscriber_ss/MBI)
    # ------------------------------------------------------------------
    _INSURANCE = [
        # Patient 1: UnitedHealthcare MA-HMO
        (1, 'primary', 'UnitedHealthcare', 'UHC Medicare Advantage (HMO)', '1EG4-TE5-MK72'),
        # Patient 2: Humana MA-PPO + Part D
        (2, 'primary', 'Humana', 'Humana Gold Plus (MA-PPO)', '2AB9-YK3-PL18'),
        (2, 'secondary', 'Humana', 'Humana Walmart Value Rx (Part D)', '2AB9-YK3-PL18'),
        # Patient 3: Original Medicare + Medicaid (full dual)
        (3, 'primary', 'Medicare', 'Medicare Part A & B (Original)', '3CD7-WN8-QR45'),
        (3, 'secondary', 'Medicaid', 'Texas Medicaid STAR+PLUS (Full Dual)', '3CD7-WN8-QR45'),
        # Patient 4: Aetna MA-HMO-POS
        (4, 'primary', 'Aetna', 'Aetna Medicare Eagle (HMO-POS)', '4FH2-RM6-JN83'),
        # Patient 5: Original Medicare + Medicaid QMB (partial dual)
        (5, 'primary', 'Medicare', 'Medicare Part A & B (Original)', '5GK1-TP4-BV29'),
        (5, 'secondary', 'Medicaid', 'Florida Medicaid QMB (Qualified Medicare Beneficiary)', '5GK1-TP4-BV29'),
        # Patient 6: Cigna MA-PPO
        (6, 'primary', 'Cigna', 'Cigna True Choice Medicare (PPO)', '6HL3-SQ7-DW64'),
        # Patient 7: Anthem BCBS MA-HMO
        (7, 'primary', 'Anthem BCBS', 'Anthem MediBlue Plus (MA-HMO)', '7JM5-VR9-FX17'),
        # Patient 8: Original Medicare + Medicaid SLMB (partial dual)
        (8, 'primary', 'Medicare', 'Medicare Part A & B (Original)', '8KN8-WS2-GY53'),
        (8, 'secondary', 'Medicaid', 'California Medi-Cal SLMB', '8KN8-WS2-GY53'),
        # Patient 9: Humana MA-HMO
        (9, 'primary', 'Humana', 'Humana Honor (MA-HMO)', '9LP4-XT6-HZ81'),
        # Patient 10: Original Medicare + AARP Medigap Plan F
        (10, 'primary', 'Medicare', 'Medicare Part A & B (Original)', '1MQ7-YU1-JA26'),
        (10, 'secondary', 'UnitedHealthcare', 'AARP Medicare Supplement Plan F', '1MQ7-YU1-JA26'),
        # Patient 11: Wellcare D-SNP (dual special needs)
        (11, 'primary', 'Wellcare', 'Wellcare Dual Liberty (HMO D-SNP)', '2NR3-ZV5-KB72'),
        (11, 'secondary', 'Medicaid', 'Ohio Medicaid CareSource (Full Dual)', '2NR3-ZV5-KB72'),
        # Patient 12: Anthem BCBS MA-PPO
        (12, 'primary', 'Anthem BCBS', 'Anthem MediBlue Access (MA-PPO)', '3PS6-AW8-LC49'),
        # Patient 13: Original Medicare + Medicaid (full dual)
        (13, 'primary', 'Medicare', 'Medicare Part A & B (Original)', '4QT9-BX3-MD95'),
        (13, 'secondary', 'Medicaid', 'New York Medicaid Managed Long Term Care', '4QT9-BX3-MD95'),
        # Patient 14: Aetna MA-PPO
        (14, 'primary', 'Aetna', 'Aetna Medicare Value (PPO)', '5RU2-CY7-NE31'),
        # Patient 15: UHC C-SNP + Medigap
        (15, 'primary', 'UnitedHealthcare', 'UHC Chronic Complete (MA C-SNP)', '6SV5-DZ1-PF68'),
        (15, 'secondary', 'Humana', 'Humana Medigap Plan G Supplement', '6SV5-DZ1-PF68'),
    ]

    # ------------------------------------------------------------------
    # Immunizations
    # ------------------------------------------------------------------
    _IMMUNIZATIONS = [
        (1, '2025-10-15', '33', 'Pneumococcal PCV20'),
        (1, '2025-10-15', '197', 'Influenza 2025-2026'),
        (2, '2025-09-20', '197', 'Influenza 2025-2026'),
        (2, '2025-09-20', '213', 'COVID-19 Pfizer Bivalent 2025'),
        (3, '2025-11-08', '197', 'Influenza 2025-2026'),
        (3, '2025-11-08', '33', 'Pneumococcal PCV20'),
        (4, '2025-12-01', '197', 'Influenza 2025-2026'),
        (4, '2025-12-01', '213', 'COVID-19 Moderna Bivalent 2025'),
        (5, '2025-12-01', '197', 'Influenza 2025-2026'),
        (5, '2025-12-01', '213', 'COVID-19 Pfizer Bivalent 2025'),
        (6, '2025-10-22', '197', 'Influenza 2025-2026'),
        (6, '2025-10-22', '121', 'Zoster Recombinant (Shingrix) Dose 1'),
        (7, '2025-11-30', '197', 'Influenza 2025-2026'),
        (7, '2025-11-30', '33', 'Pneumococcal PCV20'),
        (8, '2026-01-15', '197', 'Influenza 2025-2026'),
        (8, '2026-01-15', '121', 'Zoster Recombinant (Shingrix) Dose 2'),
        (9, '2025-11-03', '197', 'Influenza 2025-2026'),
        (9, '2025-11-03', '213', 'COVID-19 Pfizer Bivalent 2025'),
        (10, '2025-12-10', '197', 'Influenza 2025-2026'),
        (10, '2025-12-10', '121', 'Zoster Recombinant (Shingrix) Dose 1'),
        (11, '2026-01-15', '197', 'Influenza 2025-2026'),
        (11, '2026-01-15', '33', 'Pneumococcal PCV20'),
        (12, '2026-02-05', '197', 'Influenza 2025-2026'),
        (12, '2026-02-05', '213', 'COVID-19 Moderna Bivalent 2025'),
        (13, '2026-02-20', '197', 'Influenza 2025-2026'),
        (13, '2026-02-20', '33', 'Pneumococcal PCV20'),
        (14, '2026-03-10', '197', 'Influenza 2025-2026'),
        (14, '2026-03-10', '121', 'Zoster Recombinant (Shingrix) Dose 1'),
        (15, '2026-03-25', '197', 'Influenza 2025-2026'),
        (15, '2026-03-25', '33', 'Pneumococcal PPSV23'),
        (15, '2026-03-25', '213', 'COVID-19 Pfizer Bivalent 2025'),
    ]

    # ------------------------------------------------------------------
    # Prescription notes (diagnosis indications)
    # ------------------------------------------------------------------
    # ------------------------------------------------------------------
    # Prescriptions for patients 9-15
    # ------------------------------------------------------------------
    _PRESCRIPTIONS = [
        # Patient 1: DM + CKD + HTN
        (1, 'Metformin HCl', '1000mg BID', 60, 'T2DM management, monitor renal function'),
        (1, 'Lisinopril', '20mg daily', 30, 'HTN and renal protection'),
        (1, 'Atorvastatin', '40mg daily', 30, 'Cardiovascular risk reduction'),
        # Patient 2: HTN + Hyperlipidemia + PVD
        (2, 'Amlodipine', '10mg daily', 30, 'HTN, increased from 5mg'),
        (2, 'Atorvastatin', '20mg daily', 30, 'Hyperlipidemia, LDL 142'),
        (2, 'Losartan', '100mg daily', 30, 'HTN, ARB due to ACE cough'),
        (2, 'Aspirin', '81mg daily', 90, 'PVD secondary prevention'),
        # Patient 3: CHF + AFib + COPD
        (3, 'Furosemide', '40mg BID', 60, 'CHF volume management'),
        (3, 'Carvedilol', '25mg BID', 60, 'CHF beta-blocker therapy'),
        (3, 'Warfarin', '5mg daily', 30, 'AFib anticoagulation, target INR 2-3'),
        (3, 'Spiriva HandiHaler', '18mcg daily', 30, 'COPD maintenance'),
        # Patient 4: COPD + Lung Cancer hx + Depression
        (4, 'Trelegy Ellipta', '100/62.5/25mcg daily', 30, 'COPD GOLD III triple therapy'),
        (4, 'Albuterol HFA', '90mcg PRN', 1, 'COPD rescue inhaler'),
        (4, 'Sertraline', '100mg daily', 30, 'Major depressive disorder'),
        # Patient 5: CKD3b + DM nephropathy + Anemia
        (5, 'Insulin Glargine', '18 units bedtime', 1, 'T2DM, metformin contraindicated CKD'),
        (5, 'Sevelamer', '800mg TID with meals', 90, 'Phosphate binder for CKD'),
        (5, 'Losartan', '50mg daily', 30, 'Renal protection, proteinuria'),
        (5, 'Ferrous sulfate', '325mg daily', 30, 'Anemia of CKD'),
        # Patient 6: Depression + Morbid Obesity + DM + OSA
        (6, 'Duloxetine', '60mg daily', 30, 'MDD, increased from 30mg'),
        (6, 'Metformin', '1000mg BID', 60, 'T2DM'),
        (6, 'Semaglutide', '1mg weekly', 4, 'Weight management and glycemic control'),
        # Patient 7: DM + HTN + Neuropathy + PAD
        (7, 'Insulin Glargine', '10 units bedtime', 1, 'T2DM uncontrolled, new start'),
        (7, 'Metformin', '500mg BID', 60, 'T2DM, reduced dose for tolerability'),
        (7, 'Chlorthalidone', '25mg daily', 30, 'HTN, added to regimen'),
        (7, 'Gabapentin', '300mg TID', 90, 'Diabetic peripheral neuropathy'),
        (7, 'Cilostazol', '100mg BID', 60, 'PAD, improve walking distance'),
        # Patient 8: AFib + HFpEF + Hypothyroid + CKD3a + Osteoporosis
        (8, 'Apixaban', '5mg BID', 60, 'AFib anticoagulation (Eliquis)'),
        (8, 'Levothyroxine', '75mcg daily', 30, 'Hypothyroidism replacement'),
        (8, 'Alendronate', '70mg weekly', 4, 'Osteoporosis, T-score -2.8, new start'),
        (8, 'Metoprolol Succinate', '50mg daily', 30, 'AFib rate control and HFpEF'),
        # Patient 9: DM + CKD + retinopathy
        (9, 'Metformin HCl', '1000mg BID', 60, 'T2DM management, monitor renal function'),
        (9, 'Lisinopril', '20mg daily', 30, 'HTN and renal protection'),
        (9, 'Semaglutide', '0.25mg weekly', 4, 'New start for weight management'),
        (10, 'Amlodipine', '10mg', 30, 'Increased from 5mg'),
        (10, 'Sertraline', '100mg', 30, None),
        (11, 'Furosemide', '80mg', 30, 'Increased from 40mg'),
        (11, 'Carvedilol', '25mg', 60, None),
        (11, 'Warfarin', '5mg', 30, None),
        (11, 'Metformin', '500mg', 60, None),
        (12, 'Tiotropium', '18mcg', 30, None),
        (12, 'Albuterol', '90mcg', 1, 'Rescue inhaler'),
        (12, 'Alendronate', '70mg', 4, 'New start'),
        (12, 'Levothyroxine', '75mcg', 30, None),
        (13, 'Apixaban', '5mg', 60, None),
        (13, 'Tamsulosin', '0.4mg', 30, None),
        (13, 'Colchicine', '0.6mg', 30, 'Gout prophylaxis'),
        (13, 'Insulin Glargine', '20 units', 1, None),
        (14, 'Metformin', '500mg', 60, None),
        (14, 'Levothyroxine', '100mcg', 30, None),
        (14, 'Vitamin D3', '2000 IU', 30, None),
        (15, 'Sacubitril/Valsartan', '49/51mg', 60, None),
        (15, 'Carvedilol', '12.5mg', 60, None),
        (15, 'Insulin Glargine', '24 units', 1, None),
        (15, 'Tiotropium', '18mcg', 30, None),
        (15, 'Furosemide', '40mg', 30, None),
    ]

    _RX_NOTES = {
        'Metformin': 'Type 2 diabetes mellitus E11.65',
        'Lisinopril': 'Essential hypertension I10',
        'Amlodipine': 'Essential hypertension I10',
        'Atorvastatin': 'Hyperlipidemia E78.5',
        'Furosemide': 'Chronic systolic heart failure I50.22',
        'Carvedilol': 'Chronic systolic heart failure I50.22',
        'Warfarin': 'Atrial fibrillation I48.2',
        'Eliquis': 'Atrial fibrillation I48.2',
        'Tiotropium': 'COPD J44.1',
        'Losartan': 'Essential hypertension I10',
        'Donepezil': 'Alzheimer disease G30.9',
        'Insulin': 'Type 2 diabetes mellitus E11.65',
        'Sertraline': 'Major depressive disorder F33.1',
        'Duloxetine': 'Major depressive disorder F33.1',
        'Levothyroxine': 'Hypothyroidism E03.9',
        'Gabapentin': 'Diabetic neuropathy E11.42',
    }

    # ------------------------------------------------------------------
    # Labs (procedure_order → procedure_report → procedure_result)
    # (pid, test_name, result_value, units, range, abnormal, date)
    # ------------------------------------------------------------------
    _LABS = [
        # Patient 1: Diabetic + CKD
        (1, 'HbA1c', '7.2', '%', '4.0-5.6', 'abnormal', '2026-01-20'),
        (1, 'Glucose Fasting', '142', 'mg/dL', '70-100', 'abnormal', '2026-01-20'),
        (1, 'Creatinine', '1.4', 'mg/dL', '0.7-1.3', 'abnormal', '2026-01-20'),
        (1, 'eGFR', '52', 'mL/min', '>60', 'abnormal', '2026-01-20'),
        (1, 'Total Cholesterol', '198', 'mg/dL', '<200', 'normal', '2026-01-20'),
        (1, 'LDL', '112', 'mg/dL', '<100', 'abnormal', '2026-01-20'),
        # Patient 2: HTN + Hyperlipidemia
        (2, 'Total Cholesterol', '242', 'mg/dL', '<200', 'abnormal', '2025-09-12'),
        (2, 'LDL', '158', 'mg/dL', '<100', 'abnormal', '2025-09-12'),
        (2, 'HDL', '42', 'mg/dL', '>40', 'normal', '2025-09-12'),
        (2, 'Triglycerides', '210', 'mg/dL', '<150', 'abnormal', '2025-09-12'),
        (2, 'BMP', '138', 'mEq/L', '136-145', 'normal', '2025-09-12'),
        # Patient 3: CHF + AFib
        (3, 'BNP', '320', 'pg/mL', '<100', 'abnormal', '2026-02-14'),
        (3, 'INR', '2.4', '', '2.0-3.0', 'normal', '2026-02-14'),
        (3, 'Creatinine', '2.1', 'mg/dL', '0.7-1.3', 'abnormal', '2026-02-14'),
        (3, 'eGFR', '22', 'mL/min', '>60', 'abnormal', '2026-02-14'),
        (3, 'Hemoglobin', '10.8', 'g/dL', '12-16', 'abnormal', '2026-02-14'),
        (3, 'Potassium', '4.8', 'mEq/L', '3.5-5.0', 'normal', '2026-02-14'),
        # Patient 4: DM + HTN
        (4, 'HbA1c', '8.1', '%', '4.0-5.6', 'abnormal', '2025-12-01'),
        (4, 'Glucose Fasting', '168', 'mg/dL', '70-100', 'abnormal', '2025-12-01'),
        (4, 'TSH', '3.2', 'mIU/L', '0.4-4.0', 'normal', '2025-12-01'),
        (4, 'ALT', '28', 'U/L', '7-56', 'normal', '2025-12-01'),
        # Patient 5: CKD + DM
        (5, 'Creatinine', '1.8', 'mg/dL', '0.7-1.3', 'abnormal', '2025-12-15'),
        (5, 'eGFR', '38', 'mL/min', '>60', 'abnormal', '2025-12-15'),
        (5, 'HbA1c', '7.5', '%', '4.0-5.6', 'abnormal', '2025-12-15'),
        (5, 'Potassium', '5.2', 'mEq/L', '3.5-5.0', 'abnormal', '2025-12-15'),
        (5, 'Phosphorus', '5.1', 'mg/dL', '2.5-4.5', 'abnormal', '2025-12-15'),
        # Patient 6: Alzheimer + DM
        (6, 'HbA1c', '6.8', '%', '4.0-5.6', 'abnormal', '2025-10-22'),
        (6, 'Vitamin B12', '380', 'pg/mL', '200-900', 'normal', '2025-10-22'),
        (6, 'TSH', '2.1', 'mIU/L', '0.4-4.0', 'normal', '2025-10-22'),
        (6, 'CBC WBC', '7.2', 'K/uL', '4.5-11.0', 'normal', '2025-10-22'),
        # Patient 7: COPD + Lung cancer
        (7, 'CBC WBC', '12.4', 'K/uL', '4.5-11.0', 'abnormal', '2026-01-05'),
        (7, 'Hemoglobin', '11.2', 'g/dL', '12-16', 'abnormal', '2026-01-05'),
        (7, 'Platelets', '342', 'K/uL', '150-400', 'normal', '2026-01-05'),
        (7, 'LDH', '280', 'U/L', '140-280', 'normal', '2026-01-05'),
        (7, 'CEA', '8.5', 'ng/mL', '<3.0', 'abnormal', '2026-01-05'),
        # Patient 8: RA + COPD
        (8, 'ESR', '42', 'mm/hr', '0-20', 'abnormal', '2026-01-15'),
        (8, 'CRP', '2.8', 'mg/dL', '<1.0', 'abnormal', '2026-01-15'),
        (8, 'RF Factor', '86', 'IU/mL', '<14', 'abnormal', '2026-01-15'),
        (8, 'Hemoglobin', '11.5', 'g/dL', '12-16', 'abnormal', '2026-01-15'),
        (8, 'ALT', '32', 'U/L', '7-56', 'normal', '2026-01-15'),
        # Patient 9: DM + CKD
        (9, 'HbA1c', '7.8', '%', '4.0-5.6', 'abnormal', '2025-11-03'),
        (9, 'Creatinine', '1.6', 'mg/dL', '0.7-1.3', 'abnormal', '2025-11-03'),
        (9, 'eGFR', '45', 'mL/min', '>60', 'abnormal', '2025-11-03'),
        (9, 'Urine Albumin', '120', 'mg/g', '<30', 'abnormal', '2025-11-03'),
        (9, 'LDL', '95', 'mg/dL', '<100', 'normal', '2025-11-03'),
        # Patient 10: Depression + HTN
        (10, 'TSH', '4.8', 'mIU/L', '0.4-4.0', 'abnormal', '2025-12-10'),
        (10, 'Glucose Fasting', '118', 'mg/dL', '70-100', 'abnormal', '2025-12-10'),
        (10, 'Total Cholesterol', '215', 'mg/dL', '<200', 'abnormal', '2025-12-10'),
        (10, 'Vitamin D', '18', 'ng/mL', '30-100', 'abnormal', '2025-12-10'),
        # Patient 11: CHF + COPD + DM
        (11, 'BNP', '890', 'pg/mL', '<100', 'abnormal', '2026-01-15'),
        (11, 'HbA1c', '8.4', '%', '4.0-5.6', 'abnormal', '2026-01-15'),
        (11, 'INR', '2.1', '', '2.0-3.0', 'normal', '2026-01-15'),
        (11, 'Creatinine', '1.5', 'mg/dL', '0.7-1.3', 'abnormal', '2026-01-15'),
        (11, 'Hemoglobin', '10.2', 'g/dL', '12-16', 'abnormal', '2026-01-15'),
        # Patient 12: COPD + Osteoporosis
        (12, 'Vitamin D', '22', 'ng/mL', '30-100', 'abnormal', '2026-02-05'),
        (12, 'Calcium', '9.2', 'mg/dL', '8.5-10.5', 'normal', '2026-02-05'),
        (12, 'TSH', '3.2', 'mIU/L', '0.4-4.0', 'normal', '2026-02-05'),
        (12, 'CBC WBC', '8.1', 'K/uL', '4.5-11.0', 'normal', '2026-02-05'),
        # Patient 13: AFib + CKD4
        (13, 'Creatinine', '2.8', 'mg/dL', '0.7-1.3', 'abnormal', '2026-02-20'),
        (13, 'eGFR', '22', 'mL/min', '>60', 'abnormal', '2026-02-20'),
        (13, 'Potassium', '5.4', 'mEq/L', '3.5-5.0', 'abnormal', '2026-02-20'),
        (13, 'Uric Acid', '9.2', 'mg/dL', '3.5-7.2', 'abnormal', '2026-02-20'),
        (13, 'HbA1c', '7.6', '%', '4.0-5.6', 'abnormal', '2026-02-20'),
        (13, 'PSA', '3.8', 'ng/mL', '<4.0', 'normal', '2026-02-20'),
        # Patient 14: DM controlled + hypothyroid
        (14, 'HbA1c', '6.9', '%', '4.0-5.6', 'abnormal', '2026-03-10'),
        (14, 'TSH', '2.1', 'mIU/L', '0.4-4.0', 'normal', '2026-03-10'),
        (14, 'Vitamin D', '15', 'ng/mL', '30-100', 'abnormal', '2026-03-10'),
        (14, 'Total Cholesterol', '188', 'mg/dL', '<200', 'normal', '2026-03-10'),
        # Patient 15: Severe COPD + HFrEF + CKD3b
        (15, 'BNP', '650', 'pg/mL', '<100', 'abnormal', '2026-03-25'),
        (15, 'Creatinine', '1.9', 'mg/dL', '0.7-1.3', 'abnormal', '2026-03-25'),
        (15, 'eGFR', '38', 'mL/min', '>60', 'abnormal', '2026-03-25'),
        (15, 'HbA1c', '7.8', '%', '4.0-5.6', 'abnormal', '2026-03-25'),
        (15, 'Hemoglobin', '10.5', 'g/dL', '12-16', 'abnormal', '2026-03-25'),
        (15, 'ABG pO2', '62', 'mmHg', '80-100', 'abnormal', '2026-03-25'),
    ]

    # ------------------------------------------------------------------
    # Billing ICD-10 codes (linked to encounters)
    # ------------------------------------------------------------------
    _BILLING = [
        # (pid, encounter, code, code_text)
        (1, 1001, 'E11.65', 'T2DM with hyperglycemia'),
        (1, 1001, 'I10', 'Essential hypertension'),
        (1, 1002, 'E11.65', 'T2DM with hyperglycemia'),
        (1, 1002, 'N18.31', 'CKD Stage 3a'),
        (2, 1003, 'I10', 'Essential hypertension'),
        (2, 1003, 'E78.5', 'Hyperlipidemia'),
        (2, 1003, 'I73.9', 'Peripheral vascular disease'),
        (3, 1004, 'I50.22', 'Chronic systolic heart failure'),
        (3, 1004, 'I48.2', 'Chronic atrial fibrillation'),
        (3, 1004, 'J44.1', 'COPD'),
        (3, 1005, 'I50.22', 'Chronic systolic heart failure'),
        (3, 1005, 'N18.4', 'CKD Stage 4'),
        (4, 1006, 'E11.65', 'T2DM with hyperglycemia'),
        (4, 1006, 'I10', 'Essential hypertension'),
        (5, 1007, 'N18.4', 'CKD Stage 4'),
        (5, 1007, 'E11.22', 'T2DM with diabetic nephropathy'),
        (6, 1008, 'G30.9', 'Alzheimer disease'),
        (6, 1008, 'E11.9', 'Type 2 diabetes'),
        (7, 1009, 'J44.1', 'COPD'),
        (7, 1009, 'C34.90', 'Lung cancer'),
        (8, 1010, 'M06.9', 'Rheumatoid arthritis'),
        (8, 1010, 'J44.1', 'COPD'),
        (9, 1011, 'E11.65', 'T2DM with hyperglycemia'),
        (9, 1011, 'N18.31', 'CKD Stage 3a'),
        (9, 1011, 'E11.319', 'Diabetic retinopathy'),
        (10, 1012, 'I10', 'Essential hypertension'),
        (10, 1012, 'F33.1', 'Major depressive disorder'),
        (10, 1012, 'R73.03', 'Prediabetes'),
        (11, 1013, 'I50.9', 'Heart failure'),
        (11, 1013, 'J44.1', 'COPD'),
        (11, 1013, 'I48.2', 'Atrial fibrillation'),
        (11, 1013, 'E11.65', 'T2DM with hyperglycemia'),
        (12, 1014, 'J44.1', 'COPD'),
        (12, 1014, 'M81.0', 'Osteoporosis'),
        (12, 1014, 'E03.9', 'Hypothyroidism'),
        (13, 1015, 'I48.2', 'Atrial fibrillation'),
        (13, 1015, 'N18.4', 'CKD Stage 4'),
        (13, 1015, 'E11.22', 'T2DM nephropathy'),
        (13, 1015, 'M10.9', 'Gout'),
        (14, 1016, 'E11.9', 'Type 2 diabetes'),
        (14, 1016, 'E03.9', 'Hypothyroidism'),
        (14, 1016, 'E55.0', 'Vitamin D deficiency'),
        (15, 1017, 'J44.1', 'COPD severe'),
        (15, 1017, 'I50.22', 'HFrEF'),
        (15, 1017, 'N18.32', 'CKD Stage 3b'),
        (15, 1017, 'E11.65', 'T2DM with hyperglycemia'),
        (15, 1017, 'I63.9', 'CVA history'),
    ]

    # ------------------------------------------------------------------
    # SDOH Z-codes (billed codes for social determinants)
    # ------------------------------------------------------------------
    _SDOH = [
        (1, 1001, 'Z71.3', 'Dietary counseling'),
        (2, 1003, 'Z60.2', 'Living alone'),
        (3, 1004, 'Z74.1', 'Need for assistance with personal care'),
        (4, 1006, 'Z63.0', 'Relationship distress'),
        (5, 1007, 'Z59.7', 'Insufficient social insurance'),
        (6, 1008, 'Z74.1', 'Need for caregiver assistance'),
        (7, 1009, 'Z87.891', 'History of nicotine dependence'),
        (8, 1010, 'Z63.4', 'Disappearance of family member'),
        (9, 1011, 'Z71.3', 'Dietary counseling'),
        (10, 1012, 'Z56.0', 'Unemployment'),
        (10, 1012, 'Z60.2', 'Living alone'),
        (11, 1013, 'Z74.1', 'Need for assistance'),
        (12, 1014, 'Z60.2', 'Living alone'),
        (13, 1015, 'Z87.891', 'History of nicotine dependence'),
        (14, 1016, 'Z71.3', 'Dietary counseling'),
        (15, 1017, 'Z99.81', 'Dependence on supplemental oxygen'),
    ]

    # ------------------------------------------------------------------
    # Referrals
    # ------------------------------------------------------------------
    _REFERRALS = [
        (1, 'Endocrinology', 'Dr. Patel', '2026-01-20', 'Diabetic management, A1c optimization'),
        (1, 'Ophthalmology', 'Dr. Kim', '2026-01-20', 'Annual diabetic retinopathy screening'),
        (2, 'Cardiology', 'Dr. Shah', '2025-09-12', 'PVD workup, ABI testing'),
        (3, 'Nephrology', 'Dr. Chen', '2026-02-14', 'CKD Stage 4 co-management'),
        (3, 'Cardiology', 'Dr. Shah', '2026-02-14', 'Heart failure optimization'),
        (4, 'Endocrinology', 'Dr. Patel', '2025-12-01', 'Uncontrolled diabetes'),
        (5, 'Nephrology', 'Dr. Chen', '2025-12-15', 'CKD Stage 4 progression'),
        (6, 'Neurology', 'Dr. Brooks', '2025-10-22', 'Alzheimer disease management'),
        (7, 'Oncology', 'Dr. Martinez', '2026-01-05', 'Lung cancer staging and treatment'),
        (7, 'Pulmonology', 'Dr. Adams', '2026-01-05', 'COPD optimization'),
        (8, 'Rheumatology', 'Dr. Lee', '2026-01-15', 'RA disease activity assessment'),
        (9, 'Ophthalmology', 'Dr. Kim', '2025-11-03', 'Diabetic retinopathy follow-up'),
        (10, 'Psychiatry', 'Dr. Gomez', '2025-12-10', 'Depression management'),
        (11, 'Cardiology', 'Dr. Shah', '2026-01-15', 'CHF exacerbation evaluation'),
        (12, 'Pulmonology', 'Dr. Adams', '2026-02-05', 'COPD management'),
        (12, 'Endocrinology', 'Dr. Patel', '2026-02-05', 'Osteoporosis management'),
        (13, 'Nephrology', 'Dr. Chen', '2026-02-20', 'CKD Stage 4, dialysis planning'),
        (13, 'Urology', 'Dr. Torres', '2026-02-20', 'BPH evaluation'),
        (14, 'Orthopedics', 'Dr. Wilson', '2026-03-10', 'Bilateral knee OA evaluation'),
        (15, 'Pulmonology', 'Dr. Adams', '2026-03-25', 'Severe COPD, home O2 management'),
        (15, 'Cardiology', 'Dr. Shah', '2026-03-25', 'HFrEF optimization'),
    ]

    # ------------------------------------------------------------------
    # Family History
    # ------------------------------------------------------------------
    _FAMILY_HISTORY = [
        (1, 'Father: MI at age 58. Mother: Type 2 diabetes. Brother: Hypertension.'),
        (2, 'Mother: Stroke at age 72. Father: Hypertension, died age 80.'),
        (3, 'Father: CHF, died age 65. Mother: Type 2 diabetes. Sister: Breast cancer.'),
        (4, 'Mother: Type 2 diabetes. Father: CAD, CABG at 62. No cancer history.'),
        (5, 'Father: ESRD on dialysis. Mother: Hypertension. Brother: CKD.'),
        (6, 'Mother: Alzheimer disease, onset age 70. Father: Stroke. Sister: Dementia.'),
        (7, 'Father: Lung cancer (smoker), died age 62. Mother: COPD. No diabetes.'),
        (8, 'Mother: Rheumatoid arthritis. Sister: Lupus. Father: Healthy, age 82.'),
        (9, 'Father: Type 2 diabetes, retinopathy. Mother: Hypertension. Brother: Obesity.'),
        (10, 'Mother: Depression, suicide attempt. Father: Hypertension. Sister: Anxiety disorder.'),
        (11, 'Father: CHF, died age 60. Mother: AFib. Brother: Type 2 diabetes.'),
        (12, 'Mother: Osteoporosis, hip fracture age 75. Father: COPD. Sister: Hypothyroidism.'),
        (13, 'Father: CKD, dialysis. Mother: AFib. Brother: Gout, Type 2 diabetes.'),
        (14, 'Mother: Hypothyroidism. Father: Type 2 diabetes. No cancer history.'),
        (15, 'Father: COPD, died age 58 (smoker). Mother: CHF. Brother: CVA at age 55.'),
    ]

    # ------------------------------------------------------------------
    # Patient demographics (race, ethnicity, address, phone, email, SSN)
    # Updates patient_data rows that already exist in OpenEMR
    # (pid, race, ethnicity, language, street, city, state, postal_code, phone_home, phone_cell, email, ss)
    # ------------------------------------------------------------------
    _DEMOGRAPHICS = [
        (1,  'white',             'not_hisp_or_latino', 'English',    '4521 Oak Ridge Dr',      'Houston',        'TX', '77054', '713-555-0142', '832-555-0198', 'robert.johnson@email.com',    '412-55-8834'),
        (2,  'black_or_afri_amer','not_hisp_or_latino', 'English',    '782 Magnolia Ln',        'Houston',        'TX', '77004', '713-555-0267', '281-555-0341', 'mary.williams@email.com',     '267-83-4419'),
        (3,  'white',             'not_hisp_or_latino', 'English',    '1903 Peachtree St NW',   'Atlanta',        'GA', '30309', '404-555-0183', '678-555-0294', 'james.smith@email.com',       '583-21-7762'),
        (4,  'white',             'hisp_or_latino',     'Spanish',    '510 W Commerce St',      'San Antonio',    'TX', '78207', '210-555-0372', '210-555-0418', 'carlos.garcia@email.com',     '459-72-3318'),
        (5,  'black_or_afri_amer','not_hisp_or_latino', 'English',    '2245 MLK Blvd',          'Dallas',         'TX', '75215', '214-555-0156', '469-555-0287', 'patricia.brown@email.com',    '621-44-9953'),
        (6,  'white',             'not_hisp_or_latino', 'English',    '8834 Westheimer Rd',     'Houston',        'TX', '77063', '713-555-0491', '346-555-0163', 'linda.davis@email.com',       '538-19-6647'),
        (7,  'white',             'hisp_or_latino',     'Spanish',    '1127 S Flores St',       'San Antonio',    'TX', '78204', '210-555-0528', '210-555-0639', 'miguel.rodriguez@email.com',  '473-66-2281'),
        (8,  'asian',             'not_hisp_or_latino', 'Mandarin',   '6402 Bellaire Blvd',     'Houston',        'TX', '77074', '713-555-0714', '832-555-0852', 'nancy.chen@email.com',        '384-27-5594'),
        (9,  'white',             'not_hisp_or_latino', 'English',    '3317 Travis St',         'Houston',        'TX', '77006', '713-555-0836', '832-555-0947', 'david.anderson@email.com',    '291-58-8837'),
        (10, 'black_or_afri_amer','not_hisp_or_latino', 'English',    '1456 Wheeler Ave',       'Houston',        'TX', '77004', '713-555-0953', '281-555-0174', 'susan.thomas@email.com',      '617-33-4426'),
        (11, 'white',             'not_hisp_or_latino', 'English',    '920 Memorial Dr',        'Houston',        'TX', '77024', '713-555-0128', '832-555-0365', 'richard.jackson@email.com',   '745-82-1198'),
        (12, 'white',             'not_hisp_or_latino', 'English',    '4718 Richmond Ave',      'Houston',        'TX', '77027', '713-555-0247', '346-555-0482', 'jessica.white@email.com',     '528-41-7763'),
        (13, 'white',             'not_hisp_or_latino', 'English',    '2201 Fannin St',         'Houston',        'TX', '77002', '713-555-0369', '832-555-0518', 'charles.harris@email.com',    '693-14-5547'),
        (14, 'white',             'hisp_or_latino',     'Spanish',    '5533 Kirby Dr',          'Houston',        'TX', '77005', '713-555-0481', '281-555-0627', 'sarah.martinez@email.com',    '356-79-2234'),
        (15, 'white',             'not_hisp_or_latino', 'English',    '1842 Post Oak Blvd',     'Houston',        'TX', '77056', '713-555-0592', '832-555-0738', 'thomas.thompson@email.com',   '814-26-9981'),
    ]

    # ------------------------------------------------------------------
    # Execute all INSERTs
    # ------------------------------------------------------------------
    # ------------------------------------------------------------------
    # Encounters for ALL patients (1-15)
    # ------------------------------------------------------------------
    _ENCOUNTERS = [
        # Patients 1-8
        (1, 1001, '2025-10-15 09:00:00', 'Annual wellness visit, diabetes and CKD management'),
        (1, 1002, '2026-01-20 14:00:00', 'Diabetes follow-up, CKD monitoring'),
        (2, 1003, '2025-09-12 10:30:00', 'Hypertension management, hyperlipidemia workup'),
        (3, 1004, '2025-11-08 11:00:00', 'CHF exacerbation, atrial fibrillation management'),
        (3, 1005, '2026-02-14 09:30:00', 'Cardiology follow-up, CKD Stage 4 review'),
        (4, 1006, '2025-12-01 15:00:00', 'COPD evaluation, lung cancer surveillance'),
        (5, 1007, '2026-01-10 08:00:00', 'CKD Stage 3b follow-up, diabetic nephropathy'),
        (6, 1008, '2025-10-22 13:00:00', 'Annual exam, depression and obesity management'),
        (7, 1009, '2025-11-30 10:00:00', 'Diabetes and hypertension visit, neuropathy evaluation'),
        (8, 1010, '2026-02-05 09:00:00', 'Atrial fibrillation follow-up, osteoporosis management'),
        # Patients 9-15
        (9, 1011, '2025-11-03 09:00:00', 'Diabetes and CKD follow-up'),
        (10, 1012, '2025-12-10 10:30:00', 'Hypertension and depression management'),
        (11, 1013, '2026-01-15 08:45:00', 'CHF exacerbation evaluation'),
        (12, 1014, '2026-02-05 11:00:00', 'COPD and osteoporosis follow-up'),
        (13, 1015, '2026-02-20 09:30:00', 'Atrial fibrillation and CKD management'),
        (14, 1016, '2026-03-10 14:00:00', 'Diabetes and hypothyroidism review'),
        (15, 1017, '2026-03-25 10:00:00', 'COPD and heart failure follow-up'),
    ]

    try:
        with openemr_cursor() as cur:
            # Encounters for patients 9-15
            for pid, enc, dt, reason in _ENCOUNTERS:
                cur.execute(
                    "SELECT encounter FROM form_encounter WHERE pid=%s AND encounter=%s LIMIT 1",
                    (pid, enc),
                )
                if not cur.fetchone():
                    cur.execute(
                        "INSERT INTO form_encounter (pid, encounter, date, reason) "
                        "VALUES (%s, %s, %s, %s)",
                        (pid, enc, dt, reason),
                    )

            # Demographics (update existing patient_data rows)
            for pid, race, eth, lang, street, city, state, zipcode, phone_h, phone_c, email, ss in _DEMOGRAPHICS:
                cur.execute(
                    "UPDATE patient_data SET "
                    "race=%s, ethnicity=%s, language=%s, street=%s, city=%s, state=%s, postal_code=%s, "
                    "phone_home=%s, phone_cell=%s, email=%s, ss=%s "
                    "WHERE pid=%s AND (race IS NULL OR race='' OR language IS NULL OR language='')",
                    (race, eth, lang, street, city, state, zipcode, phone_h, phone_c, email, ss, pid),
                )

            # Clinical notes (check before insert to avoid duplicates)
            # OpenEMR pattern: forms.form_id references the child row's id, but
            # form_clinical_notes.form_id is NOT NULL with no default — so we must
            # 1) INSERT forms with form_id=0 placeholder, 2) INSERT child using
            # forms.id as its form_id, 3) UPDATE forms.form_id to the child row id.
            for pid, enc, dt, ntype, note in _CLINICAL_NOTES:
                try:
                    cur.execute(
                        "SELECT id FROM form_clinical_notes WHERE pid=%s AND encounter=%s AND clinical_notes_type=%s LIMIT 1",
                        (pid, enc, ntype),
                    )
                    if not cur.fetchone():
                        cur.execute(
                            "INSERT INTO forms (date, encounter, form_name, form_id, pid, formdir) "
                            "VALUES (%s, %s, 'Clinical Notes', 0, %s, 'clinical_notes')",
                            (dt, enc, pid),
                        )
                        forms_id = cur.lastrowid
                        cur.execute(
                            "INSERT INTO form_clinical_notes (pid, encounter, date, clinical_notes_type, description, form_id) "
                            "VALUES (%s, %s, %s, %s, %s, %s)",
                            (pid, enc, dt, ntype, note, forms_id),
                        )
                        cn_id = cur.lastrowid
                        cur.execute(
                            "UPDATE forms SET form_id=%s WHERE id=%s",
                            (cn_id, forms_id),
                        )
                except Exception as exc:
                    logger.warning("Seed clinical_notes skipped for pid=%s enc=%s: %s", pid, enc, exc)

            # Vitals — form_vitals has no `encounter` column; link via forms registry only.
            # Same ordering trick as clinical_notes above.
            for pid, enc, dt, wt, ht, bps, bpd in _VITALS:
                try:
                    cur.execute(
                        "SELECT fv.id FROM form_vitals fv "
                        "JOIN forms f ON f.form_id=fv.id AND f.formdir='vitals' "
                        "WHERE fv.pid=%s AND f.encounter=%s LIMIT 1",
                        (pid, enc),
                    )
                    if not cur.fetchone():
                        cur.execute(
                            "INSERT INTO forms (date, encounter, form_name, form_id, pid, formdir) "
                            "VALUES (%s, %s, 'Vitals', 0, %s, 'vitals')",
                            (dt, enc, pid),
                        )
                        forms_id = cur.lastrowid
                        cur.execute(
                            "INSERT INTO form_vitals (pid, date, weight, height, bps, bpd, activity) "
                            "VALUES (%s, %s, %s, %s, %s, %s, 1)",
                            (pid, dt, wt, ht, bps, bpd),
                        )
                        v_id = cur.lastrowid
                        cur.execute(
                            "UPDATE forms SET form_id=%s WHERE id=%s",
                            (v_id, forms_id),
                        )
                except Exception as exc:
                    logger.warning("Seed vitals skipped for pid=%s enc=%s: %s", pid, enc, exc)

            # Problem list
            for pid, title, dx, begdate, comments in _PROBLEMS:
                cur.execute(
                    "SELECT id FROM lists WHERE pid=%s AND type='medical_problem' AND diagnosis=%s LIMIT 1",
                    (pid, dx),
                )
                if not cur.fetchone():
                    cur.execute(
                        "INSERT INTO lists (pid, type, title, diagnosis, begdate, activity, comments) "
                        "VALUES (%s, 'medical_problem', %s, %s, %s, 1, %s)",
                        (pid, title, dx, begdate, comments),
                    )

            # Ensure ALL problems for our 15 patients are active
            cur.execute(
                "UPDATE lists SET activity=1 "
                "WHERE type='medical_problem' AND pid BETWEEN 1 AND 15 AND activity != 1"
            )

            # Allergies
            for pid, title, begdate, comments in _ALLERGIES:
                cur.execute(
                    "SELECT id FROM lists WHERE pid=%s AND type='allergy' AND title=%s LIMIT 1",
                    (pid, title),
                )
                if not cur.fetchone():
                    cur.execute(
                        "INSERT INTO lists (pid, type, title, diagnosis, begdate, activity, comments) "
                        "VALUES (%s, 'allergy', %s, '', %s, 1, %s)",
                        (pid, title, begdate, comments),
                    )

            # Insurance
            for pid, itype, provider, plan, mbi in _INSURANCE:
                cur.execute(
                    "SELECT id FROM insurance_data WHERE pid=%s AND type=%s AND plan_name=%s LIMIT 1",
                    (pid, itype, plan),
                )
                if not cur.fetchone():
                    cur.execute(
                        "INSERT INTO insurance_data "
                        "(pid, type, provider, plan_name, subscriber_ss) "
                        "VALUES (%s, %s, %s, %s, %s)",
                        (pid, itype, provider, plan, mbi),
                    )

            # Immunizations
            for pid, dt, cvx, title in _IMMUNIZATIONS:
                cur.execute(
                    "SELECT id FROM immunizations WHERE patient_id=%s AND cvx_code=%s AND title=%s LIMIT 1",
                    (pid, cvx, title),
                )
                if not cur.fetchone():
                    cur.execute(
                        "INSERT INTO immunizations (patient_id, administered_date, cvx_code, title) "
                        "VALUES (%s, %s, %s, %s)",
                        (pid, dt, cvx, title),
                    )

            # Prescriptions for patients 9-15
            for pid, drug, dosage, qty, note in _PRESCRIPTIONS:
                cur.execute(
                    "SELECT id FROM prescriptions WHERE patient_id=%s AND drug=%s AND dosage=%s LIMIT 1",
                    (pid, drug, dosage),
                )
                if not cur.fetchone():
                    cur.execute(
                        "INSERT INTO prescriptions (patient_id, drug, dosage, quantity, note) "
                        "VALUES (%s, %s, %s, %s, %s)",
                        (pid, drug, dosage, qty, note),
                    )

            # Prescription notes
            for drug_prefix, note in _RX_NOTES.items():
                cur.execute(
                    "UPDATE prescriptions SET note = %s WHERE drug LIKE %s AND (note IS NULL OR note = '')",
                    (note, f"%{drug_prefix}%"),
                )

            # Forms registry backfill — safety net for any legacy child rows inserted
            # without a parent `forms` entry (e.g. from older seed runs).
            try:
                cur.execute(
                    "INSERT IGNORE INTO forms (date, encounter, form_name, form_id, pid, formdir) "
                    "SELECT fcn.date, fcn.encounter, 'Clinical Notes', fcn.id, fcn.pid, 'clinical_notes' "
                    "FROM form_clinical_notes fcn "
                    "WHERE NOT EXISTS (SELECT 1 FROM forms f WHERE f.form_id=fcn.id AND f.formdir='clinical_notes')"
                )
                # form_vitals has no `encounter` column — backfill with encounter=0
                cur.execute(
                    "INSERT IGNORE INTO forms (date, encounter, form_name, form_id, pid, formdir) "
                    "SELECT fv.date, 0, 'Vitals', fv.id, fv.pid, 'vitals' "
                    "FROM form_vitals fv "
                    "WHERE NOT EXISTS (SELECT 1 FROM forms f WHERE f.form_id=fv.id AND f.formdir='vitals')"
                )
            except Exception as exc:
                logger.warning("Seed forms-registry backfill skipped: %s", exc)

            # SOAP notes — required for the AI analysis pipeline (Gemini)
            _SOAP_NOTES = [
                # (pid, encounter, date, subjective, objective, assessment, plan)
                (1, 1001, '2025-10-15 09:00:00',
                 'Patient reports increased thirst and frequent urination over the past 3 weeks. Occasional blurry vision. Denies chest pain or shortness of breath. Has been compliant with Metformin 500mg BID. Diet has been inconsistent. Reports numbness in bilateral feet, worse at night.',
                 'Vitals: BP 138/82, HR 76, Temp 98.4F, Wt 198 lbs, BMI 31.2. General: well-appearing, NAD. HEENT: diabetic retinopathy screening ordered. Lungs: CTA bilaterally. Cardiac: RRR, no murmurs. Extremities: decreased monofilament sensation bilateral feet, no ulcers. Labs: HbA1c 7.8%, FBG 168, BUN 28, Cr 1.4, GFR 52, microalbumin/creatinine ratio 45.',
                 'Type 2 Diabetes Mellitus with hyperglycemia (E11.65). Diabetic polyneuropathy (E11.42). Chronic Kidney Disease Stage 3a (N18.31). Essential Hypertension (I10), controlled. Obesity (E66.01).',
                 'Increase Metformin to 1000mg BID. Start Gabapentin 300mg TID for neuropathy. Continue Lisinopril 20mg daily. Refer to ophthalmology for diabetic retinopathy screening. Recheck HbA1c in 3 months. Dietary counseling provided. Follow up in 3 months.'),
                (1, 1002, '2026-01-20 14:00:00',
                 'Follow-up for diabetes. Patient reports improved dietary compliance. Neuropathy symptoms improved with Gabapentin. No hypoglycemic episodes. Denies any new symptoms.',
                 'Vitals: BP 132/78, HR 72, Wt 194 lbs. General: well-appearing. Lungs: CTA. Cardiac: RRR. Extremities: improved sensation bilateral feet. Labs: HbA1c 7.2%, FBG 142, Cr 1.3, GFR 52, microalbumin stable.',
                 'Type 2 Diabetes Mellitus improving on current regimen (E11.65). Diabetic polyneuropathy improving (E11.42). CKD Stage 3a stable (N18.31). Hypertension controlled (I10).',
                 'Continue Metformin 1000mg BID. Continue Gabapentin 300mg TID. Continue Lisinopril 20mg. Recheck labs in 3 months. Continue dietary modifications. Return in 3 months.'),
                (2, 1003, '2025-09-12 10:30:00',
                 'Patient presents for hypertension management. Reports occasional headaches. Denies chest pain, dyspnea. Notes leg cramping with walking 2 blocks, relieved by rest. Has been taking Amlodipine 5mg as prescribed.',
                 'Vitals: BP 148/92, HR 80, Wt 172 lbs. General: well-nourished female. Cardiac: RRR, S4 gallop. Lungs: CTA. Peripheral pulses: diminished dorsalis pedis bilaterally. Labs: LDL 142, Total cholesterol 238, HDL 42. ABI 0.72 right, 0.68 left.',
                 'Essential Hypertension, uncontrolled (I10). Hyperlipidemia (E78.5). Peripheral Vascular Disease with intermittent claudication (I73.9).',
                 'Increase Amlodipine to 10mg daily. Start Atorvastatin 20mg daily. Refer to vascular surgery for PVD evaluation. Supervised exercise program. Low sodium, heart-healthy diet. Follow up in 4 weeks for BP recheck.'),
                (3, 1004, '2025-11-08 11:00:00',
                 'Patient presents with weight gain of 4 lbs over 1 week, increased ankle swelling, and worsening dyspnea on exertion. Now SOB walking to bathroom. Sleeping on 3 pillows. Denies chest pain. Has been compliant with medications including Warfarin.',
                 'Vitals: BP 142/88, HR 92 irregular, RR 22, O2 sat 93% RA, Wt 214 lbs (+4 from last visit). JVD to 10cm. Lungs: bibasilar crackles. Cardiac: irregularly irregular, S3 gallop, 2/6 systolic murmur. Extremities: 2+ pitting edema bilateral. BNP 580. INR 2.4. Echo: EF 30%, moderate MR.',
                 'Chronic Systolic Heart Failure, acute exacerbation (I50.22). Chronic Atrial Fibrillation (I48.2), rate controlled, INR therapeutic. COPD stable (J44.1). CKD Stage 4 (N18.4).',
                 'Increase Furosemide to 40mg BID. Daily weights and 2L fluid restriction. Low sodium diet. Continue Warfarin, target INR 2-3. Continue Spiriva and Breo for COPD. Recheck BNP and renal function in 1 week. If no improvement, consider IV diuretics. Follow up in 1 week.'),
                (3, 1005, '2026-02-14 09:30:00',
                 'Cardiology follow-up. Patient reports significant improvement in dyspnea. Can now walk 1 block without SOB. Sleeping on 2 pillows. Weight stable. No chest pain or palpitations.',
                 'Vitals: BP 128/76, HR 78 irregular, RR 18, O2 sat 96% RA, Wt 210 lbs. JVD 6cm. Lungs: trace bibasilar crackles. Cardiac: irregularly irregular, no S3. Extremities: trace pedal edema. BNP 320. INR 2.1. Echo: EF 35%, mild MR. GFR 22.',
                 'CHF improving on optimized therapy (I50.22). Atrial Fibrillation controlled (I48.2). COPD stable (J44.1). CKD Stage 4 stable (N18.4), nephrology co-managing.',
                 'Continue Furosemide 40mg BID. Continue Warfarin, INR therapeutic. Continue COPD inhalers. Nephrology follow-up for CKD. Repeat echo in 6 months. Continue fluid and sodium restriction. Follow up in 2 months.'),
                (4, 1006, '2025-12-01 15:00:00',
                 'Patient reports increasing dyspnea on exertion over past 6 weeks. Can walk about half a block before needing to rest. Using rescue inhaler 4-5 times per week. Productive cough with white sputum. Former smoker, 40 pack-years, quit 2023 after lobectomy.',
                 'Vitals: BP 136/84, HR 82, RR 20, O2 sat 91% RA, Wt 165 lbs. Barrel chest. Lungs: diminished breath sounds bilateral bases, scattered expiratory wheezes. No consolidation. Cardiac: RRR. Extremities: no edema, mild digital clubbing. PFTs: FEV1 42% predicted. CT chest: no recurrence, stable post-lobectomy changes.',
                 'COPD GOLD Stage III with acute worsening (J44.1). History of lung cancer s/p lobectomy 2023 (Z85.118). Cachexia/protein-calorie malnutrition (E46).',
                 'Add Prednisone taper 40mg x 5 days. Continue Spiriva 18mcg daily and Breo 200/25 daily. Start pulmonary rehabilitation referral. Supplemental O2 for exertion. Chest CT in 6 months for cancer surveillance. Nutrition consult for weight optimization. Follow up in 2 weeks.'),
                (5, 1007, '2026-01-10 08:00:00',
                 'Follow-up for CKD and diabetes. Patient reports fatigue and decreased appetite. Occasional nausea. Increased urinary frequency. Denies hematuria. Blood sugars running 160-200.',
                 'Vitals: BP 144/88, HR 76, Wt 188 lbs. General: appears fatigued. Lungs: CTA. Cardiac: RRR, no murmurs. Extremities: 1+ pedal edema bilateral. Labs: Cr 2.1, GFR 32, HbA1c 8.1%, K 5.2, Phos 4.8, albumin 3.2.',
                 'CKD Stage 3b, diabetic nephropathy (N18.32). Type 2 Diabetes with diabetic CKD (E11.22). Hyperkalemia (E87.5). Essential Hypertension (I10).',
                 'Reduce Lisinopril to 10mg due to hyperkalemia. Add Sodium polystyrene for K management. Adjust insulin regimen. Nephrology referral for AV fistula planning. Low potassium, renal diet. Recheck K and renal function in 1 week. Follow up in 1 month.'),
                (6, 1008, '2025-10-22 13:00:00',
                 'Annual exam. Patient reports persistent low mood, fatigue, poor sleep, and decreased interest in activities for past 4 months. Weight gain of 15 lbs. Difficulty concentrating at work. Denies suicidal ideation.',
                 'Vitals: BP 128/78, HR 68, Wt 242 lbs, BMI 38.2. PHQ-9 score: 16 (moderately severe). General: overweight female, flat affect. Thyroid: no nodules. Lungs: CTA. Cardiac: RRR. Labs: TSH 2.4 (normal), lipid panel normal, FBG 98.',
                 'Major Depressive Disorder, recurrent, moderate (F33.1). Morbid Obesity, BMI 38.2 (E66.01). Vitamin D deficiency (E55.9).',
                 'Start Sertraline 50mg daily for depression. Refer to behavioral health for CBT. Start Vitamin D3 50,000 IU weekly x 8 weeks. Nutritional counseling and structured exercise program. Safety plan reviewed. PHQ-9 recheck in 4 weeks. Follow up in 4 weeks.'),
                (7, 1009, '2025-11-30 10:00:00',
                 'Patient presents for diabetes and hypertension management. Reports tingling and burning sensation in both feet, worse at night. Occasional dizziness when standing. Blood sugars 150-220. Has missed some doses of insulin.',
                 'Vitals: BP 152/94 sitting, 138/82 standing (orthostatic), HR 84, Wt 205 lbs. Lungs: CTA. Cardiac: RRR. Neurological: decreased vibration sense bilateral feet, absent ankle reflexes. Monofilament: 4/10 bilateral. Labs: HbA1c 8.8%, Cr 1.1, GFR 72.',
                 'Type 2 Diabetes with diabetic neuropathy (E11.42). Essential Hypertension, uncontrolled (I10). Diabetic polyneuropathy, severe (G63). Orthostatic hypotension (I95.1).',
                 'Adjust Lantus to 30 units at bedtime. Continue Metformin 1000mg BID. Start Duloxetine 60mg daily for neuropathic pain. Increase Amlodipine to 10mg. Compression stockings for orthostatic symptoms. Foot care education. Podiatry referral. Follow up in 6 weeks.'),
                (8, 1010, '2026-02-05 09:00:00',
                 'Follow-up for atrial fibrillation. Patient reports occasional palpitations, about twice weekly, lasting minutes. Denies syncope or near-syncope. Also reports right hip pain, worse with weight-bearing.',
                 'Vitals: BP 134/78, HR 82 irregularly irregular, Wt 148 lbs. Cardiac: irregularly irregular, no murmurs. Lungs: CTA. Musculoskeletal: tenderness right greater trochanter, limited ROM right hip. DEXA: T-score -2.8 lumbar spine, -2.6 right hip. INR 2.3.',
                 'Chronic Atrial Fibrillation (I48.2), rate controlled. Osteoporosis with pathological fracture risk (M81.0). Vitamin D deficiency (E55.9). Right hip trochanteric bursitis.',
                 'Continue Metoprolol 50mg BID and Warfarin. Start Alendronate 70mg weekly for osteoporosis. Calcium 1200mg + Vitamin D 2000 IU daily. Physical therapy for right hip. Fall prevention assessment. DEXA repeat in 2 years. Follow up in 3 months.'),
                (9, 1011, '2025-11-03 09:00:00',
                 'Patient presents for diabetes and CKD follow-up. Reports stable blood sugars on current regimen. Mild bilateral lower extremity swelling noted for past 2 weeks. No chest pain or shortness of breath. Vision has been blurry intermittently.',
                 'Vitals: BP 140/86, HR 74, Wt 196 lbs. Eyes: bilateral dot hemorrhages on fundoscopy. Lungs: CTA. Cardiac: RRR. Extremities: 1+ pitting edema bilateral ankles. Labs: HbA1c 7.6%, Cr 1.5, GFR 48, microalbumin 62, K 4.8.',
                 'Type 2 Diabetes with diabetic CKD (E11.22). Diabetic retinopathy, bilateral (E11.319). CKD Stage 3a (N18.31). Essential Hypertension (I10). Obesity (E66.01).',
                 'Continue Metformin 1000mg BID. Continue Lisinopril 20mg. Urgent ophthalmology referral for diabetic retinopathy. Low sodium renal diet. Recheck labs in 3 months. Compression stockings for edema. Follow up in 3 months.'),
                (10, 1012, '2025-12-10 10:30:00',
                 'Hypertension and depression follow-up. Patient reports medication compliance but persistent elevated readings at home (avg 145/90). Mood slightly improved on Sertraline but still has low energy and poor sleep.',
                 'Vitals: BP 146/92, HR 72, Wt 168 lbs. PHQ-9: 12 (moderate). General: well-appearing but flat affect. Cardiac: RRR. Lungs: CTA. Labs: BMP normal, lipid panel: LDL 128.',
                 'Essential Hypertension, uncontrolled (I10). Major Depressive Disorder, recurrent, moderate (F33.1). Hyperlipidemia (E78.5).',
                 'Add Hydrochlorothiazide 25mg daily. Increase Sertraline to 100mg daily. Start Atorvastatin 10mg. Home BP log for 2 weeks. Follow up in 4 weeks. Continue behavioral health.'),
                (11, 1013, '2026-01-15 08:45:00',
                 'Patient presents with increasing dyspnea and leg swelling over past 10 days. Weight up 6 lbs. Has been eating salty foods over holidays. Sleeping on 3 pillows. Compliant with medications.',
                 'Vitals: BP 156/94, HR 98, RR 24, O2 sat 91% RA, Wt 228 lbs. JVD present. Lungs: bilateral crackles to mid-lung fields. Cardiac: S3 gallop, 2/6 systolic murmur. Extremities: 3+ pitting edema bilateral. BNP 890. Pro-BNP 4200. CXR: bilateral pleural effusions, cardiomegaly.',
                 'Acute on chronic systolic heart failure, severe exacerbation (I50.23). Essential Hypertension (I10). Type 2 Diabetes (E11.65). CKD Stage 3 (N18.3).',
                 'Admit consideration vs aggressive outpatient management. IV Furosemide 80mg now, then 40mg BID oral. Strict 1.5L fluid restriction. 2g sodium diet. Daily weights. Telemetry monitoring. Cardiology consult. Recheck BNP and renal function in 48 hours. Close follow-up in 3 days.'),
                (12, 1014, '2026-02-05 11:00:00',
                 'COPD follow-up. Patient reports chronic productive cough, worse in mornings. Dyspnea walking one flight of stairs. Using rescue inhaler 3 times weekly. Also reports mid-back pain for past month.',
                 'Vitals: BP 132/78, HR 78, RR 18, O2 sat 93% RA, Wt 142 lbs. Lungs: decreased breath sounds bilateral bases, scattered wheezes. Cardiac: RRR. Spine: tenderness T8-T10. DEXA: T-score -3.1 lumbar spine. PFTs: FEV1 52% predicted. CXR: hyperinflation, T9 compression fracture.',
                 'COPD GOLD Stage II (J44.1). Osteoporosis with vertebral compression fracture (M80.08XA). Tobacco use disorder in remission (F17.211).',
                 'Continue Spiriva 18mcg daily. Continue Albuterol PRN. Start Trelegy 100/62.5/25 inhaler. Thoracic brace for compression fracture. Start Denosumab 60mg SC q6months. Pain management with Acetaminophen. Calcium and Vitamin D supplementation. Follow up in 6 weeks.'),
                (13, 1015, '2026-02-20 09:30:00',
                 'Atrial fibrillation and CKD management. Patient reports palpitations 2-3 times per week, lasting 5-10 minutes. Occasional lightheadedness. No syncope. Swelling in legs has been worsening.',
                 'Vitals: BP 138/82, HR 88 irregularly irregular, Wt 192 lbs. Cardiac: irregularly irregular, no murmurs. Lungs: CTA. Extremities: 2+ pitting edema bilateral. Labs: INR 2.6, Cr 2.4, GFR 28, K 5.1, BNP 340.',
                 'Chronic Atrial Fibrillation (I48.2). CKD Stage 4 (N18.4). Hyperkalemia (E87.5). Essential Hypertension (I10). Type 2 Diabetes (E11.9).',
                 'Continue Warfarin, reduce dose slightly for INR 2.6. Continue Metoprolol 50mg BID. Start Patiromer for hyperkalemia. Nephrology referral for CKD Stage 4. Low potassium, low sodium diet. Recheck labs in 1 week. Follow up in 4 weeks.'),
                (14, 1016, '2026-03-10 14:00:00',
                 'Diabetes and hypothyroidism review. Patient reports fatigue, cold intolerance, and constipation over past 2 months. Blood sugars running 180-240. Weight gain of 8 lbs.',
                 'Vitals: BP 134/82, HR 62, Wt 178 lbs. General: dry skin, periorbital puffiness. Thyroid: diffusely enlarged, no nodules. Cardiac: bradycardic, regular. Reflexes: delayed relaxation phase. Labs: TSH 14.2, Free T4 0.6, HbA1c 8.4%, lipid panel: LDL 168.',
                 'Hypothyroidism, uncontrolled (E03.9). Type 2 Diabetes with hyperglycemia (E11.65). Hyperlipidemia (E78.5). Obesity (E66.01).',
                 'Start Levothyroxine 75mcg daily on empty stomach. Increase Metformin to 1000mg BID. Start Atorvastatin 20mg. Recheck TSH in 6-8 weeks. Dietary counseling. Endocrinology referral for co-management. Follow up in 6 weeks.'),
                (15, 1017, '2026-03-25 10:00:00',
                 'COPD and heart failure follow-up. Patient reports worsening dyspnea, now SOB at rest intermittently. Increased sputum production, yellow-green. Fever of 100.4F last night. Using rescue inhaler every 2 hours.',
                 'Vitals: BP 128/76, HR 102, RR 26, O2 sat 88% RA, Temp 100.2F, Wt 198 lbs. Lungs: diffuse wheezes and rhonchi, right base consolidation. Cardiac: tachycardic, regular, S3 present. Extremities: 2+ edema. WBC 14.2, BNP 620. CXR: right lower lobe infiltrate, cardiomegaly, bilateral effusions.',
                 'Acute COPD exacerbation with pneumonia (J44.0). Acute on chronic systolic heart failure (I50.23). Community-acquired pneumonia, right lower lobe (J18.1). CKD Stage 3 (N18.3).',
                 'Hospital admission recommended. Start Levofloxacin 750mg daily and Prednisone 40mg daily. Nebulized albuterol and ipratropium q4h. Supplemental O2 to maintain sat >92%. IV Furosemide 40mg BID. Telemetry. Sputum culture. Blood cultures x2. Infectious disease consult if no improvement in 48 hours.'),
            ]

            for pid, enc, dt, subj, obj, assess, plan in _SOAP_NOTES:
                # Check if SOAP already exists for this encounter via forms registry
                cur.execute(
                    "SELECT f.form_id FROM forms f WHERE f.pid=%s AND f.encounter=%s AND f.formdir='soap' LIMIT 1",
                    (pid, enc),
                )
                if not cur.fetchone():
                    cur.execute(
                        "INSERT INTO form_soap (pid, subjective, objective, assessment, plan, activity) "
                        "VALUES (%s, %s, %s, %s, %s, 1)",
                        (pid, subj, obj, assess, plan),
                    )
                    soap_id = cur.lastrowid
                    # Link via forms registry
                    cur.execute(
                        "INSERT INTO forms (date, encounter, form_name, form_id, pid, formdir) "
                        "VALUES (%s, %s, 'SOAP', %s, %s, 'soap')",
                        (dt, enc, soap_id, pid),
                    )

            # Labs (procedure_order + procedure_result — no procedure_report in this schema)
            for pid, test_name, result_val, units, ref_range, abnormal, dt in _LABS:
                # Find encounter for this patient closest to the lab date
                cur.execute(
                    "SELECT encounter FROM form_encounter WHERE pid=%s ORDER BY ABS(DATEDIFF(date, %s)) LIMIT 1",
                    (pid, dt),
                )
                row = cur.fetchone()
                enc = row["encounter"] if row else 0
                # Check if this lab already exists
                cur.execute(
                    "SELECT id FROM procedure_result WHERE pid=%s AND result_text LIKE %s LIMIT 1",
                    (pid, f"%{test_name}%"),
                )
                if not cur.fetchone():
                    cur.execute(
                        "INSERT INTO procedure_order (patient_id, encounter_id, date_ordered) "
                        "VALUES (%s, %s, %s)",
                        (pid, enc, dt),
                    )
                    # Pack all lab details into result_text
                    detail = f"{test_name}: {result_val} {units} (Ref: {ref_range}) [{abnormal.upper()}]"
                    cur.execute(
                        "INSERT INTO procedure_result (pid, encounter, date, result_text) "
                        "VALUES (%s, %s, %s, %s)",
                        (pid, enc, dt, detail),
                    )

            # Billing ICD-10 codes
            for pid, enc, code, code_text in _BILLING:
                cur.execute(
                    "SELECT id FROM billing WHERE pid=%s AND encounter=%s AND code=%s AND code_type='ICD10' LIMIT 1",
                    (pid, enc, code),
                )
                if not cur.fetchone():
                    cur.execute(
                        "INSERT INTO billing (pid, encounter, code_type, code, code_text, activity, authorized) "
                        "VALUES (%s, %s, 'ICD10', %s, %s, 1, 1)",
                        (pid, enc, code, code_text),
                    )

            # SDOH Z-codes (also billing entries)
            for pid, enc, code, code_text in _SDOH:
                cur.execute(
                    "SELECT id FROM billing WHERE pid=%s AND encounter=%s AND code=%s LIMIT 1",
                    (pid, enc, code),
                )
                if not cur.fetchone():
                    cur.execute(
                        "INSERT INTO billing (pid, encounter, code_type, code, code_text, activity, authorized) "
                        "VALUES (%s, %s, 'ICD10', %s, %s, 1, 1)",
                        (pid, enc, code, code_text),
                    )

            # Referrals (transactions table)
            for pid, specialty, refer_to, dt, reason_text in _REFERRALS:
                cur.execute(
                    "SELECT id FROM transactions WHERE pid=%s AND refer_to=%s AND date=%s LIMIT 1",
                    (pid, refer_to, dt),
                )
                if not cur.fetchone():
                    cur.execute(
                        "INSERT INTO transactions (pid, title, refer_to, refer_from, date, reason, body, authorized) "
                        "VALUES (%s, %s, %s, 'Dr. Primary Care', %s, %s, %s, 1)",
                        (pid, f"Referral: {specialty}", refer_to, dt, reason_text, reason_text),
                    )

            # Family history (history_data table)
            for pid, fh_text in _FAMILY_HISTORY:
                # Parse father/mother/sibling from text
                father = mother = siblings = ''
                for part in fh_text.split('.'):
                    p = part.strip()
                    if p.startswith('Father'):
                        father = p
                    elif p.startswith('Mother'):
                        mother = p
                    elif p.startswith('Brother') or p.startswith('Sister'):
                        siblings = (siblings + '. ' + p).strip('. ')
                    elif p.startswith('No '):
                        siblings = (siblings + '. ' + p).strip('. ')

                cur.execute(
                    "SELECT id FROM history_data WHERE pid=%s LIMIT 1",
                    (pid,),
                )
                existing = cur.fetchone()
                if existing:
                    cur.execute(
                        "UPDATE history_data SET history_father=%s, history_mother=%s, history_siblings=%s "
                        "WHERE pid=%s AND (history_father IS NULL OR history_father='')",
                        (father, mother, siblings, pid),
                    )
                else:
                    cur.execute(
                        "INSERT INTO history_data (pid, date, history_father, history_mother, history_siblings) "
                        "VALUES (%s, NOW(), %s, %s, %s)",
                        (pid, father, mother, siblings),
                    )

        logger.info("OpenEMR demo data seeded successfully (all data types).")

        # Generate demo PDF files for document viewing
        _generate_demo_pdfs()

    except Exception as exc:
        logger.error("Failed to seed OpenEMR demo data: %s", exc)


def _generate_demo_pdfs() -> None:
    """Create actual PDF files on disk for all demo documents so the View button works."""
    from pathlib import Path

    try:
        from reportlab.lib.pagesizes import letter
        from reportlab.pdfgen import canvas as pdf_canvas
    except ImportError:
        logger.warning("reportlab not installed — skipping demo PDF generation")
        return

    from app.db import raf_cursor

    project_root = Path(__file__).resolve().parent.parent

    try:
        with raf_cursor() as cur:
            cur.execute(
                "SELECT d.id, d.file_path, d.document_name, d.document_type, d.patient_id, "
                "p.fname, p.lname "
                "FROM documents d "
                "LEFT JOIN openemr.patient_data p ON p.pid = d.patient_id "
                "ORDER BY d.id"
            )
            docs = cur.fetchall()
    except Exception as exc:
        logger.debug("_generate_demo_pdfs: could not query documents: %s", exc)
        return

    created = 0
    for doc in docs:
        fp = doc.get("file_path")
        if not fp:
            continue
        full_path = (project_root / fp.lstrip("/")).resolve()
        if full_path.exists():
            continue

        full_path.parent.mkdir(parents=True, exist_ok=True)

        try:
            c = pdf_canvas.Canvas(str(full_path), pagesize=letter)
            w, h = letter

            c.setFont("Helvetica-Bold", 18)
            c.drawString(50, h - 60, doc.get("document_name") or f"Document {doc['id']}")

            c.setFont("Helvetica", 12)
            c.drawString(50, h - 90, f"Patient: {doc.get('fname', '')} {doc.get('lname', '')} (PID: {doc['patient_id']})")
            c.drawString(50, h - 110, f"Document Type: {doc.get('document_type') or 'Clinical Document'}")
            c.drawString(50, h - 130, f"Document ID: {doc['id']}")

            c.setStrokeColorRGB(0.8, 0.8, 0.8)
            c.line(50, h - 145, w - 50, h - 145)

            doc_name_lower = (doc.get("document_name") or "").lower()
            y = h - 175
            c.setFont("Helvetica", 11)

            if "lab" in doc_name_lower:
                lines = [
                    "LABORATORY RESULTS", "",
                    "Date of Service: 2026-03-15",
                    "Provider: Dr. Sarah Chen, MD", "",
                    "Complete Metabolic Panel:",
                    "  Glucose: 126 mg/dL (H)     Reference: 70-100",
                    "  BUN: 28 mg/dL (H)          Reference: 7-20",
                    "  Creatinine: 1.8 mg/dL (H)  Reference: 0.7-1.3",
                    "  eGFR: 45 mL/min (L)        Reference: >60",
                    "  Sodium: 140 mEq/L          Reference: 136-145", "",
                    "HbA1c: 7.8% (H)              Reference: <5.7%", "",
                    "Lipid Panel:",
                    "  Total Cholesterol: 210 mg/dL  Reference: <200",
                    "  LDL: 130 mg/dL (H)           Reference: <100",
                    "  HDL: 42 mg/dL (L)            Reference: >40",
                ]
            elif "discharge" in doc_name_lower:
                lines = [
                    "DISCHARGE SUMMARY", "",
                    "Admission Date: 2026-03-10",
                    "Discharge Date: 2026-03-15",
                    "Length of Stay: 5 days", "",
                    "Principal Diagnosis: Type 2 Diabetes Mellitus with CKD (E11.22)",
                    "Secondary Diagnoses:",
                    "  - Chronic Kidney Disease, Stage 3 (N18.3)",
                    "  - Essential Hypertension (I10)",
                    "  - Morbid Obesity, BMI 40+ (E66.01)", "",
                    "Hospital Course:",
                    "  Patient admitted for acute kidney injury superimposed on CKD.",
                    "  Treated with IV fluids, insulin adjustment, and nephrology consult.",
                    "  Renal function improved. Discharge on adjusted medications.",
                ]
            else:
                lines = [
                    "PROGRESS NOTE / CLINICAL NOTE", "",
                    "Date of Service: 2026-03-15",
                    "Provider: Dr. Sarah Chen, MD", "",
                    "Chief Complaint: Follow-up for chronic conditions", "",
                    "Assessment & Plan:",
                    "  1. Type 2 DM (E11.22) - Continue Metformin, recheck HbA1c",
                    "  2. CKD Stage 3 (N18.3) - Monitor eGFR, nephrology f/u",
                    "  3. HTN (I10) - BP at goal on Lisinopril",
                    "  4. Obesity (E66.01) - Counseled on diet and exercise", "",
                    "Follow-up: Return in 3 months",
                ]

            for line in lines:
                c.drawString(50, y, line)
                y -= 16
                if y < 80:
                    c.showPage()
                    y = h - 60

            c.setFont("Helvetica-Oblique", 9)
            c.setFillColorRGB(0.5, 0.5, 0.5)
            c.drawString(50, 40, "RAF Intelligence - Demo Clinical Document")
            c.save()
            created += 1
        except Exception as exc:
            logger.debug("Failed to create PDF for doc %s: %s", doc["id"], exc)

    if created:
        logger.info("Generated %d demo PDF files for document viewing.", created)
