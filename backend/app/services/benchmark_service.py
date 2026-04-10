# DISCLAIMER: Benchmark results measure the NLP pipeline against synthetic gold-standard
# test cases only. Accuracy metrics do not constitute CMS validation. All pipeline
# outputs require clinician review before use in coding or payment determinations.

"""
Benchmark Service
=================
Runs the NLP pipeline against gold-standard test cases and computes accuracy metrics.

Metrics produced:
  - ICD-10 precision / recall / F1 (per-code and aggregate)
  - HCC capture rate / precision / recall / F1
  - RAF score mean absolute error and within-range rate

Design notes:
  - The pipeline is called synchronously; callers should run this in a thread pool
    executor when invoked from an async FastAPI endpoint.
  - Each benchmark run is persisted to the RAF Intelligence DB so results can be
    trended over time.
  - Gold-standard test cases are version-stamped; adding new cases increments the
    test suite version without invalidating old run history.
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Test suite version — bump when cases are added or modified
# ---------------------------------------------------------------------------

BENCHMARK_SUITE_VERSION = "v1.0"

# ---------------------------------------------------------------------------
# 25 gold-standard test cases
# ---------------------------------------------------------------------------

GOLD_STANDARD_TEST_CASES: list[dict] = [

    # ------------------------------------------------------------------
    # 1. Type 2 Diabetes with hyperglycemia (HCC 19)
    # ------------------------------------------------------------------
    {
        "id": "GS-001",
        "name": "DM2 with hyperglycemia",
        "category": "Diabetes",
        "note_text": (
            "SUBJECTIVE: 68-year-old female presents for diabetes follow-up. "
            "Reports poor dietary compliance. Blood sugars running 180-240 mg/dL fasting. "
            "On metformin 1000mg BID and glipizide 10mg daily.\n"
            "OBJECTIVE: BP 134/82, HR 74, Weight 178 lbs. HbA1c 9.1%. "
            "Fasting glucose 218 mg/dL. eGFR 72 mL/min.\n"
            "ASSESSMENT:\n"
            "1. Type 2 diabetes mellitus with hyperglycemia – HbA1c 9.1%, above goal.\n"
            "2. Hypertension – blood pressure adequately controlled.\n"
            "PLAN: Increase glipizide to 10mg BID. Reinforce dietary counseling. "
            "Recheck HbA1c in 3 months. Continue lisinopril 10mg daily."
        ),
        "expected_icd10_codes": ["E11.65", "I10"],
        "expected_hcc_codes": [19],
        "expected_raf_score_range": [0.30, 0.80],
    },

    # ------------------------------------------------------------------
    # 2. Type 2 Diabetes with diabetic CKD (HCC 17 + HCC 326)
    # ------------------------------------------------------------------
    {
        "id": "GS-002",
        "name": "DM2 with diabetic CKD stage 3",
        "category": "Diabetes with Complications",
        "note_text": (
            "SUBJECTIVE: 74-year-old male with type 2 diabetes and CKD stage 3. "
            "Presents for quarterly follow-up. Denies chest pain or shortness of breath. "
            "Taking metformin 500mg BID, lisinopril 20mg, furosemide 40mg.\n"
            "OBJECTIVE: BP 142/86, HR 78. Weight 204 lbs. "
            "Labs: HbA1c 7.8%, Creatinine 1.9 mg/dL, eGFR 38 mL/min, Albumin 3.4 g/dL. "
            "Urine microalbumin/creatinine ratio 320 mg/g.\n"
            "ASSESSMENT:\n"
            "1. Type 2 diabetes mellitus with diabetic chronic kidney disease, stage 3 – "
            "eGFR declining, microalbuminuria present. HbA1c at goal.\n"
            "2. Hypertension – moderately controlled.\n"
            "PLAN: Continue current regimen. Nephrology referral. "
            "Repeat CMP and urine microalbumin in 3 months."
        ),
        "expected_icd10_codes": ["E11.65", "E11.22", "N18.3", "I10"],
        "expected_hcc_codes": [17, 326],
        "expected_raf_score_range": [0.50, 1.20],
    },

    # ------------------------------------------------------------------
    # 3. DM2 with peripheral neuropathy (HCC 17)
    # ------------------------------------------------------------------
    {
        "id": "GS-003",
        "name": "DM2 with diabetic peripheral neuropathy",
        "category": "Diabetes with Complications",
        "note_text": (
            "SUBJECTIVE: 71-year-old female. Reports burning, tingling in bilateral feet x 2 years. "
            "History of type 2 diabetes for 12 years. On gabapentin 300mg TID for neuropathic pain.\n"
            "OBJECTIVE: Monofilament testing: absent sensation bilateral plantar surface. "
            "Vibratory sense diminished at hallux bilaterally. HbA1c 8.4%.\n"
            "ASSESSMENT:\n"
            "1. Type 2 diabetes mellitus with diabetic peripheral neuropathy – "
            "confirmed by clinical exam and symptom history.\n"
            "2. Chronic pain syndrome related to neuropathy.\n"
            "PLAN: Continue gabapentin. Refer to podiatry. Foot care education."
        ),
        "expected_icd10_codes": ["E11.40", "E11.65"],
        "expected_hcc_codes": [17],
        "expected_raf_score_range": [0.35, 0.90],
    },

    # ------------------------------------------------------------------
    # 4. CHF systolic, chronic (HCC 85)
    # ------------------------------------------------------------------
    {
        "id": "GS-004",
        "name": "CHF systolic chronic",
        "category": "Heart Failure",
        "note_text": (
            "SUBJECTIVE: 77-year-old male with chronic systolic heart failure. "
            "Reports increased dyspnea on exertion (2 flights of stairs). "
            "Bilateral ankle swelling worse over past week. "
            "Current meds: carvedilol 25mg BID, lisinopril 40mg, furosemide 80mg.\n"
            "OBJECTIVE: BP 118/74, HR 68. Weight 196 lbs (up 4 lbs from last visit). "
            "JVD present at 45 degrees. S3 gallop heard. "
            "2+ pitting edema bilateral lower extremities. BNP 820 pg/mL. "
            "Echo (3 months ago): EF 30-35%.\n"
            "ASSESSMENT:\n"
            "1. Chronic systolic congestive heart failure – BNP elevated, volume overloaded. "
            "EF 30-35% on last echo.\n"
            "PLAN: Increase furosemide to 80mg BID x 5 days, then return to daily. "
            "Recheck BNP and BMP in 1 week."
        ),
        "expected_icd10_codes": ["I50.22"],
        "expected_hcc_codes": [85],
        "expected_raf_score_range": [0.30, 0.90],
    },

    # ------------------------------------------------------------------
    # 5. COPD with acute exacerbation (HCC 111)
    # ------------------------------------------------------------------
    {
        "id": "GS-005",
        "name": "COPD with acute exacerbation",
        "category": "COPD",
        "note_text": (
            "SUBJECTIVE: 69-year-old male with known COPD, 45 pack-year smoking history. "
            "Presents with worsening dyspnea and increased sputum production x 3 days. "
            "Sputum yellow-green. On albuterol MDI, tiotropium, and fluticasone/salmeterol.\n"
            "OBJECTIVE: RR 24, SpO2 88% on room air. Diffuse expiratory wheezes. "
            "Accessory muscle use present. Peak flow 180 L/min (personal best 320). "
            "CXR: hyperinflation, no infiltrate.\n"
            "ASSESSMENT:\n"
            "1. COPD with acute exacerbation – triggered by possible viral upper respiratory infection. "
            "Worsening airflow obstruction on spirometry (FEV1/FVC 0.58).\n"
            "PLAN: Prednisone 40mg daily x 5 days. Azithromycin 500mg x 3 days. "
            "Increase albuterol frequency. Recheck in 3 days."
        ),
        "expected_icd10_codes": ["J44.1"],
        "expected_hcc_codes": [111],
        "expected_raf_score_range": [0.25, 0.80],
    },

    # ------------------------------------------------------------------
    # 6. CKD Stage 4 (HCC 328)
    # ------------------------------------------------------------------
    {
        "id": "GS-006",
        "name": "CKD Stage 4",
        "category": "CKD",
        "note_text": (
            "SUBJECTIVE: 82-year-old female with advanced chronic kidney disease. "
            "Reports fatigue, nausea, decreased appetite. No chest pain. "
            "Sees nephrology every 2 months. "
            "Labs from last week reviewed.\n"
            "OBJECTIVE: BP 152/88, HR 80. Weight 148 lbs. "
            "Creatinine 3.4 mg/dL, eGFR 19 mL/min, BUN 52 mg/dL, "
            "Hemoglobin 9.8 g/dL, Potassium 5.2 mEq/L, Phosphorus 5.8 mg/dL.\n"
            "ASSESSMENT:\n"
            "1. Chronic kidney disease, stage 4 – eGFR 19, approaching dialysis threshold. "
            "Discussed dialysis planning with patient.\n"
            "2. Anemia of chronic kidney disease.\n"
            "3. Secondary hyperparathyroidism related to CKD.\n"
            "PLAN: Nephrology to guide dialysis timing. Start cinacalcet for PTH. "
            "Dietary phosphate restriction."
        ),
        "expected_icd10_codes": ["N18.4", "D63.1", "N25.81"],
        "expected_hcc_codes": [328],
        "expected_raf_score_range": [0.30, 0.90],
    },

    # ------------------------------------------------------------------
    # 7. Morbid obesity with BMI ≥ 40 (HCC 22)
    # ------------------------------------------------------------------
    {
        "id": "GS-007",
        "name": "Morbid obesity BMI 42",
        "category": "Obesity",
        "note_text": (
            "SUBJECTIVE: 52-year-old male presents for weight management follow-up. "
            "Weight 310 lbs, height 5'9\". BMI 45.8. Reports difficulty with ambulation. "
            "Snores heavily, evaluated for sleep apnea.\n"
            "OBJECTIVE: BP 148/92, HR 88. BMI 45.8 kg/m2. "
            "Neck circumference 18 inches. Abdominal girth 54 inches. "
            "Lower extremity edema 1+. Knees show crepitus.\n"
            "ASSESSMENT:\n"
            "1. Morbid (severe) obesity with BMI of 45.8 – weight increased 8 lbs since last visit.\n"
            "2. Obstructive sleep apnea suspected – referral placed for polysomnography.\n"
            "3. Hypertension – poorly controlled.\n"
            "PLAN: Structured caloric restriction program. Refer to bariatric surgery consult. "
            "CPAP trial pending sleep study."
        ),
        "expected_icd10_codes": ["E66.01", "I10"],
        "expected_hcc_codes": [22],
        "expected_raf_score_range": [0.25, 0.80],
    },

    # ------------------------------------------------------------------
    # 8. Major depressive disorder, recurrent (HCC 155)
    # ------------------------------------------------------------------
    {
        "id": "GS-008",
        "name": "Major depressive disorder recurrent",
        "category": "Mental Health",
        "note_text": (
            "SUBJECTIVE: 64-year-old female with history of recurrent major depressive disorder. "
            "Reports persistent low mood x 3 weeks, insomnia, anhedonia, decreased appetite. "
            "PHQ-9 score 18 (moderate-severe). On sertraline 100mg daily. "
            "Denies suicidal ideation.\n"
            "OBJECTIVE: Appears fatigued, psychomotor slowing noted. "
            "Affect flat. Thought process logical and goal-directed. "
            "No psychotic features.\n"
            "ASSESSMENT:\n"
            "1. Major depressive disorder, recurrent, moderate – PHQ-9 18. "
            "Partial response to current SSRI.\n"
            "PLAN: Augment sertraline with bupropion XL 150mg. "
            "Refer for cognitive behavioral therapy. Follow up in 4 weeks."
        ),
        "expected_icd10_codes": ["F33.1"],
        "expected_hcc_codes": [155],
        "expected_raf_score_range": [0.20, 0.70],
    },

    # ------------------------------------------------------------------
    # 9. Rheumatoid arthritis (HCC 40)
    # ------------------------------------------------------------------
    {
        "id": "GS-009",
        "name": "Rheumatoid arthritis seropositive",
        "category": "Autoimmune",
        "note_text": (
            "SUBJECTIVE: 61-year-old female with seropositive rheumatoid arthritis x 8 years. "
            "Reports morning stiffness > 1 hour, bilateral wrist and MCP joint swelling. "
            "On methotrexate 15mg weekly and hydroxychloroquine 200mg BID.\n"
            "OBJECTIVE: Bilateral wrist synovitis with tenderness to palpation. "
            "MCP joints 2-4 bilaterally swollen and warm. "
            "DAS28 score 4.2 (moderate disease activity). "
            "RF positive 120 IU/mL, anti-CCP > 250 U/mL, ESR 44 mm/hr.\n"
            "ASSESSMENT:\n"
            "1. Rheumatoid arthritis, seropositive – moderate disease activity, "
            "inadequate response to current DMARD regimen.\n"
            "PLAN: Initiate adalimumab biologic therapy. "
            "Continue methotrexate and hydroxychloroquine. TB screening prior to biologic."
        ),
        "expected_icd10_codes": ["M05.79"],
        "expected_hcc_codes": [40],
        "expected_raf_score_range": [0.25, 0.75],
    },

    # ------------------------------------------------------------------
    # 10. Atrial fibrillation (HCC 96)
    # ------------------------------------------------------------------
    {
        "id": "GS-010",
        "name": "Atrial fibrillation persistent",
        "category": "Cardiac Arrhythmia",
        "note_text": (
            "SUBJECTIVE: 76-year-old male with persistent atrial fibrillation. "
            "Reports palpitations and mild exertional dyspnea. "
            "CHA2DS2-VASc score 4. On apixaban 5mg BID and metoprolol succinate 100mg.\n"
            "OBJECTIVE: BP 126/78, HR irregularly irregular at 88 bpm. "
            "No JVD. ECG confirms atrial fibrillation, ventricular rate 86. "
            "Echo: EF 55%, mild left atrial enlargement.\n"
            "ASSESSMENT:\n"
            "1. Persistent atrial fibrillation – rate controlled, anticoagulated. "
            "CHA2DS2-VASc 4, appropriate anticoagulation with apixaban.\n"
            "PLAN: Continue current rate control and anticoagulation. "
            "Discuss rhythm control options. Follow up in 3 months."
        ),
        "expected_icd10_codes": ["I48.11"],
        "expected_hcc_codes": [96],
        "expected_raf_score_range": [0.20, 0.70],
    },

    # ------------------------------------------------------------------
    # 11. Peripheral vascular disease (HCC 107)
    # ------------------------------------------------------------------
    {
        "id": "GS-011",
        "name": "Peripheral vascular disease with claudication",
        "category": "Vascular Disease",
        "note_text": (
            "SUBJECTIVE: 72-year-old male with peripheral artery disease. "
            "Bilateral calf claudication at 2 blocks walking. ABI performed last month. "
            "Smoked 1 PPD x 30 years, quit 5 years ago.\n"
            "OBJECTIVE: BP 144/82 right arm. Femoral pulses 2+ bilaterally. "
            "Popliteal pulses diminished bilaterally. Dorsalis pedis absent bilaterally. "
            "ABI right 0.62, left 0.58. No ulcers.\n"
            "ASSESSMENT:\n"
            "1. Peripheral arterial disease of bilateral lower extremities with claudication – "
            "ABI 0.58-0.62, consistent with moderate severity.\n"
            "2. Hypertension.\n"
            "PLAN: Cilostazol 100mg BID. Vascular surgery referral. "
            "Supervised exercise program. Continue aspirin 81mg."
        ),
        "expected_icd10_codes": ["I73.9", "I10"],
        "expected_hcc_codes": [107],
        "expected_raf_score_range": [0.25, 0.75],
    },

    # ------------------------------------------------------------------
    # 12. Protein-calorie malnutrition (HCC 21)
    # ------------------------------------------------------------------
    {
        "id": "GS-012",
        "name": "Protein-calorie malnutrition moderate",
        "category": "Malnutrition",
        "note_text": (
            "SUBJECTIVE: 84-year-old female with recent 18-lb weight loss over 3 months. "
            "Poor oral intake, lives alone, reports difficulty cooking. "
            "History of dementia (mild), COPD. No fever or diarrhea.\n"
            "OBJECTIVE: BMI 17.8. Temporal wasting noted. Triceps skinfold 8mm. "
            "Albumin 2.8 g/dL, prealbumin 11 mg/dL, transferrin 138 mg/dL. "
            "Mid-arm circumference 21 cm.\n"
            "ASSESSMENT:\n"
            "1. Moderate protein-calorie malnutrition – albumin 2.8, prealbumin 11, "
            "significant unintentional weight loss per ASPEN criteria.\n"
            "2. Failure to thrive in elderly.\n"
            "PLAN: Dietary consult. High-calorie nutritional supplements BID. "
            "Social work referral for meal assistance. Consider PEG tube discussion with family."
        ),
        "expected_icd10_codes": ["E44.0", "R62.7"],
        "expected_hcc_codes": [21],
        "expected_raf_score_range": [0.30, 0.90],
    },

    # ------------------------------------------------------------------
    # 13. CKD Stage 5 (HCC 329)
    # ------------------------------------------------------------------
    {
        "id": "GS-013",
        "name": "CKD Stage 5 pre-dialysis",
        "category": "CKD",
        "note_text": (
            "SUBJECTIVE: 68-year-old male with end-stage renal disease approaching dialysis. "
            "Uremic symptoms: nausea, fatigue, decreased urine output. "
            "Hemodialysis catheter placed last month.\n"
            "OBJECTIVE: BP 168/98, HR 84. Pitting edema 2+. "
            "Creatinine 6.8 mg/dL, eGFR 9 mL/min, BUN 88 mg/dL, "
            "K 5.8 mEq/L, Bicarb 16 mEq/L, Hemoglobin 8.2 g/dL.\n"
            "ASSESSMENT:\n"
            "1. Chronic kidney disease, stage 5 – eGFR 9 mL/min, uremic symptoms present. "
            "HD catheter in place.\n"
            "2. Metabolic acidosis secondary to CKD.\n"
            "3. Hyperkalemia.\n"
            "PLAN: Initiate hemodialysis via tunneled catheter. "
            "Sodium bicarbonate 650mg TID. Kayexalate PRN for potassium."
        ),
        "expected_icd10_codes": ["N18.5", "E87.5", "E72.29"],
        "expected_hcc_codes": [329],
        "expected_raf_score_range": [0.35, 1.00],
    },

    # ------------------------------------------------------------------
    # 14. Multiple conditions — DM2, CHF, A-fib, CKD3 (multiple HCCs)
    # ------------------------------------------------------------------
    {
        "id": "GS-014",
        "name": "Complex multi-morbidity: DM2 + CHF + AFib + CKD3",
        "category": "Multi-Morbidity",
        "note_text": (
            "SUBJECTIVE: 79-year-old male with multiple chronic conditions presents for follow-up. "
            "Reports mild dyspnea and peripheral edema. Adherent to medications: "
            "metformin 500mg BID (dose-reduced for CKD), insulin lispro, carvedilol 12.5mg BID, "
            "apixaban 2.5mg BID (renally adjusted), furosemide 40mg daily.\n"
            "OBJECTIVE: BP 132/78, HR 72 irregular. Weight 188 lbs (stable). "
            "SpO2 94% on RA. Bilateral crackles basilar. 1+ pitting edema. "
            "Labs: HbA1c 7.4%, BNP 640 pg/mL, Creatinine 2.1 mg/dL (eGFR 34), "
            "K 4.6, INR not applicable (apixaban).\n"
            "ASSESSMENT:\n"
            "1. Type 2 diabetes mellitus, controlled – HbA1c 7.4% at goal.\n"
            "2. Chronic systolic heart failure – compensated, EF 40% on last echo.\n"
            "3. Persistent atrial fibrillation – rate controlled, anticoagulated.\n"
            "4. Chronic kidney disease, stage 3b – eGFR 34, doses adjusted.\n"
            "PLAN: Continue current regimen. Cardiology and nephrology co-management. "
            "Repeat labs in 6 weeks."
        ),
        "expected_icd10_codes": ["E11.9", "I50.22", "I48.11", "N18.32"],
        "expected_hcc_codes": [19, 85, 96, 326],
        "expected_raf_score_range": [1.00, 2.50],
    },

    # ------------------------------------------------------------------
    # 15. Negation test — denied diagnoses should NOT appear
    # ------------------------------------------------------------------
    {
        "id": "GS-015",
        "name": "Negation: no diabetes, no CHF",
        "category": "Negation Handling",
        "note_text": (
            "SUBJECTIVE: 65-year-old female. Annual wellness exam. No complaints. "
            "Family history of diabetes mellitus and heart failure in father. "
            "OBJECTIVE: BP 122/76, HR 68. BMI 24. HbA1c 5.4%, fasting glucose 92. "
            "No peripheral edema. BNP 18 pg/mL. Echo EF 65% normal.\n"
            "ASSESSMENT:\n"
            "1. Hypertension – well controlled.\n"
            "2. No evidence of diabetes mellitus – HbA1c 5.4%, normal.\n"
            "3. Denies history of congestive heart failure – EF normal on recent echo.\n"
            "4. Hyperlipidemia – controlled on statin.\n"
            "PLAN: Continue lisinopril 10mg. Continue atorvastatin 40mg. "
            "Annual labs. Mammogram referral."
        ),
        "expected_icd10_codes": ["I10", "E78.5"],
        "expected_hcc_codes": [],
        "expected_raf_score_range": [0.10, 0.50],
    },

    # ------------------------------------------------------------------
    # 16. Historical mention — resolved pneumonia should NOT be HCC
    # ------------------------------------------------------------------
    {
        "id": "GS-016",
        "name": "Historical mention: past pneumonia vs. active COPD",
        "category": "Historical Mention",
        "note_text": (
            "SUBJECTIVE: 71-year-old male. Follow-up for COPD. History of pneumonia 2 years ago "
            "requiring hospitalization (fully recovered). No current respiratory infection symptoms. "
            "OBJECTIVE: SpO2 95% on room air. FEV1 52% predicted. "
            "CXR no acute infiltrate. No fever.\n"
            "ASSESSMENT:\n"
            "1. COPD without exacerbation – stable on current inhaler regimen.\n"
            "2. History of community-acquired pneumonia (resolved 2022) – no active infection.\n"
            "PLAN: Continue tiotropium and fluticasone/salmeterol. Influenza vaccine today. "
            "Pneumococcal vaccine due next visit."
        ),
        "expected_icd10_codes": ["J44.0"],
        "expected_hcc_codes": [111],
        "expected_raf_score_range": [0.20, 0.70],
    },

    # ------------------------------------------------------------------
    # 17. Stroke with hemiplegia (HCC 103 + HCC 104)
    # ------------------------------------------------------------------
    {
        "id": "GS-017",
        "name": "Ischemic stroke with residual hemiplegia",
        "category": "Neurological",
        "note_text": (
            "SUBJECTIVE: 73-year-old male with history of ischemic stroke 6 months ago. "
            "Residual left-sided hemiplegia. Currently in outpatient rehab. "
            "On aspirin 325mg and clopidogrel 75mg.\n"
            "OBJECTIVE: Left upper and lower extremity strength 2/5. "
            "Brunnstrom stage II left arm. Ambulates with walker, max assist. "
            "Speech intact. MRI brain: established right MCA territory infarct.\n"
            "ASSESSMENT:\n"
            "1. Sequela of ischemic cerebrovascular accident – right MCA infarct with "
            "residual left hemiplegia.\n"
            "2. Left hemiplegia dominant side as sequela of stroke.\n"
            "PLAN: Continue PT/OT 3x/week. Antiplatelet dual therapy. "
            "Carotid ultrasound surveillance."
        ),
        "expected_icd10_codes": ["I69.351", "I69.354"],
        "expected_hcc_codes": [103],
        "expected_raf_score_range": [0.40, 1.20],
    },

    # ------------------------------------------------------------------
    # 18. Schizophrenia (HCC 157)
    # ------------------------------------------------------------------
    {
        "id": "GS-018",
        "name": "Schizophrenia paranoid type",
        "category": "Mental Health",
        "note_text": (
            "SUBJECTIVE: 45-year-old male with schizophrenia, paranoid type. "
            "Followed by psychiatry monthly. Reports auditory hallucinations decreased "
            "since medication adjustment. No suicidal ideation. "
            "On olanzapine 20mg QHS and benztropine 1mg BID.\n"
            "OBJECTIVE: Appearance disheveled but cooperative. "
            "Speech: logical, no tangentiality. Hallucinations reported 1-2x/day (previously 8-10x). "
            "No delusions elicited today. PANSS score improved.\n"
            "ASSESSMENT:\n"
            "1. Schizophrenia, paranoid type – partial response to olanzapine, "
            "improvement in positive symptoms.\n"
            "PLAN: Continue olanzapine 20mg. Monthly injection depot conversion discussed. "
            "Social work for housing support."
        ),
        "expected_icd10_codes": ["F20.0"],
        "expected_hcc_codes": [157],
        "expected_raf_score_range": [0.25, 0.80],
    },

    # ------------------------------------------------------------------
    # 19. HIV/AIDS (HCC 1)
    # ------------------------------------------------------------------
    {
        "id": "GS-019",
        "name": "HIV disease on ART",
        "category": "Infectious Disease",
        "note_text": (
            "SUBJECTIVE: 52-year-old male with HIV disease, on antiretroviral therapy x 7 years. "
            "Adherent to bictegravir/emtricitabine/tenofovir. "
            "Reports no opportunistic infections. Labs reviewed.\n"
            "OBJECTIVE: BP 124/78, HR 72. Weight 174 lbs (stable). "
            "CD4 count 680 cells/mm3, HIV RNA undetectable < 20 copies/mL. "
            "CBC normal. LFTs normal. Creatinine 0.9 mg/dL.\n"
            "ASSESSMENT:\n"
            "1. HIV disease, on ART – virologically suppressed, immunologically stable. "
            "CD4 count appropriate.\n"
            "PLAN: Continue Biktarvy once daily. Annual STI screening. "
            "Pneumococcal vaccine updated."
        ),
        "expected_icd10_codes": ["B20"],
        "expected_hcc_codes": [1],
        "expected_raf_score_range": [0.30, 0.90],
    },

    # ------------------------------------------------------------------
    # 20. Lung cancer (HCC 9)
    # ------------------------------------------------------------------
    {
        "id": "GS-020",
        "name": "Non-small cell lung cancer",
        "category": "Oncology",
        "note_text": (
            "SUBJECTIVE: 67-year-old female with newly diagnosed non-small cell lung cancer, "
            "adenocarcinoma, right lower lobe. Stage IIIA. "
            "Currently undergoing concurrent chemoradiation. "
            "Tolerable fatigue and mild nausea.\n"
            "OBJECTIVE: Weight 142 lbs (down 6 lbs). ECOG performance status 1. "
            "Breath sounds decreased right base. "
            "CT chest: 4.2 cm right lower lobe mass, mediastinal adenopathy. "
            "PET: uptake in mediastinal nodes, no distant metastasis.\n"
            "ASSESSMENT:\n"
            "1. Non-small cell lung cancer, right lower lobe, stage IIIA (T2bN2M0) – "
            "on concurrent chemoradiation per oncology.\n"
            "2. Malnutrition risk – dietician referral placed.\n"
            "PLAN: Continue carboplatin/paclitaxel with radiation. "
            "Antiemetics as needed. Follow up post-chemoradiation restaging CT."
        ),
        "expected_icd10_codes": ["C34.31"],
        "expected_hcc_codes": [9],
        "expected_raf_score_range": [0.50, 1.50],
    },

    # ------------------------------------------------------------------
    # 21. Septicemia (HCC 2)
    # ------------------------------------------------------------------
    {
        "id": "GS-021",
        "name": "Septicemia gram-negative",
        "category": "Infectious Disease",
        "note_text": (
            "SUBJECTIVE: 76-year-old male admitted via ED with fever, rigors, hypotension. "
            "History of recurrent UTIs. Foley catheter in place. "
            "OBJECTIVE: Temp 39.2°C, BP 88/52, HR 116, RR 24. "
            "WBC 18,400 with 86% PMN. Lactic acid 4.2 mmol/L. "
            "Blood cultures: gram-negative rods (Klebsiella pneumoniae). "
            "Urine culture: 100,000 CFU Klebsiella.\n"
            "ASSESSMENT:\n"
            "1. Septicemia due to Klebsiella pneumoniae – septic shock criteria met, "
            "source urinary tract.\n"
            "2. Urinary tract infection.\n"
            "PLAN: IV meropenem. Aggressive fluid resuscitation. "
            "ICU monitoring. Remove and replace Foley."
        ),
        "expected_icd10_codes": ["A41.51", "N39.0"],
        "expected_hcc_codes": [2],
        "expected_raf_score_range": [0.50, 1.50],
    },

    # ------------------------------------------------------------------
    # 22. Multiple conditions with negation and historical — complex
    # ------------------------------------------------------------------
    {
        "id": "GS-022",
        "name": "Complex: DM2 complications + negated CAD + historical DVT",
        "category": "Multi-Morbidity + Negation",
        "note_text": (
            "SUBJECTIVE: 70-year-old female. Diabetes management visit. "
            "Reports blurry vision and decreased sensation feet. "
            "History of deep vein thrombosis 3 years ago (resolved, off anticoagulation). "
            "Denies chest pain or history of coronary artery disease.\n"
            "OBJECTIVE: Funduscopic exam: bilateral dot-blot hemorrhages, microaneurysms "
            "consistent with non-proliferative diabetic retinopathy. "
            "HbA1c 8.8%. Creatinine 1.2 mg/dL, eGFR 58. "
            "Monofilament: absent sensation at 3 sites bilaterally.\n"
            "ASSESSMENT:\n"
            "1. Type 2 diabetes with non-proliferative diabetic retinopathy – bilateral.\n"
            "2. Type 2 diabetes with diabetic peripheral neuropathy – confirmed by exam.\n"
            "3. No evidence of coronary artery disease – denies symptoms, not evaluated.\n"
            "4. History of DVT, resolved – no current anticoagulation indicated.\n"
            "PLAN: Ophthalmology referral. Podiatry referral. Optimise glycemic control."
        ),
        "expected_icd10_codes": ["E11.3519", "E11.40", "E11.65"],
        "expected_hcc_codes": [17],
        "expected_raf_score_range": [0.40, 1.10],
    },

    # ------------------------------------------------------------------
    # 23. ESRD on dialysis (HCC 134)
    # ------------------------------------------------------------------
    {
        "id": "GS-023",
        "name": "ESRD on hemodialysis",
        "category": "ESRD",
        "note_text": (
            "SUBJECTIVE: 58-year-old male on hemodialysis three times weekly x 2 years. "
            "History of diabetic nephropathy as etiology. Tolerating HD well. "
            "Tunneled catheter, listed for kidney transplant.\n"
            "OBJECTIVE: BP 144/90 pre-HD. Weight 78 kg (dry weight 75 kg). "
            "Potassium 5.4, Hemoglobin 10.2 (on erythropoietin). "
            "Kt/V 1.42 (adequate dialysis).\n"
            "ASSESSMENT:\n"
            "1. End-stage renal disease on hemodialysis – ESRD due to diabetic nephropathy. "
            "Adequate dialysis per Kt/V.\n"
            "2. Anemia of ESRD – managed with erythropoietin.\n"
            "PLAN: Continue HD TIW. Continue EPO and IV iron. "
            "Transplant workup in progress."
        ),
        "expected_icd10_codes": ["N18.6", "Z99.2", "D63.1"],
        "expected_hcc_codes": [134],
        "expected_raf_score_range": [0.50, 1.50],
    },

    # ------------------------------------------------------------------
    # 24. Dementia with behavioral disturbance (HCC 52)
    # ------------------------------------------------------------------
    {
        "id": "GS-024",
        "name": "Alzheimer's dementia with behavioral disturbance",
        "category": "Neurological",
        "note_text": (
            "SUBJECTIVE: 85-year-old female with Alzheimer's disease, moderate stage. "
            "Caregiver (daughter) reports increasing agitation, wandering at night, "
            "and aggressive behavior toward caregivers. "
            "On donepezil 10mg QHS and memantine 10mg BID.\n"
            "OBJECTIVE: MMSE 14/30. Disoriented to time and place. "
            "Agitated during exam, required redirection x3. "
            "No focal neurologic deficits.\n"
            "ASSESSMENT:\n"
            "1. Alzheimer's disease dementia with behavioral disturbance – "
            "worsening agitation and wandering, caregiver burden significant.\n"
            "PLAN: Add low-dose quetiapine 12.5mg QHS for behavioral symptoms. "
            "Memory care facility consult. Caregiver support group referral. "
            "Restart scheduled exercise program."
        ),
        "expected_icd10_codes": ["F02.81"],
        "expected_hcc_codes": [52],
        "expected_raf_score_range": [0.35, 1.00],
    },

    # ------------------------------------------------------------------
    # 25. Amputated limb + DM2 + PVD (multiple HCCs, complex coding)
    # ------------------------------------------------------------------
    {
        "id": "GS-025",
        "name": "Trans-tibial amputation with DM2 and PVD",
        "category": "Amputee + Multi-Morbidity",
        "note_text": (
            "SUBJECTIVE: 67-year-old male with type 2 diabetes and peripheral vascular disease. "
            "Status post right below-knee amputation 4 months ago due to non-healing diabetic ulcer. "
            "Now using prosthesis. Wound healed well. Left foot with callus formation.\n"
            "OBJECTIVE: BP 138/84, HR 76. Right residual limb well-healed, no erythema. "
            "Prosthesis fitting appropriate. Left foot: callus plantar aspect, intact skin. "
            "ABI left 0.72. HbA1c 9.2%. Creatinine 1.6 mg/dL.\n"
            "ASSESSMENT:\n"
            "1. Acquired absence of right foot – post-traumatic/surgical, below-knee amputation.\n"
            "2. Type 2 diabetes mellitus with peripheral circulatory complications – "
            "contributed to non-healing ulcer requiring amputation.\n"
            "3. Peripheral arterial disease of left lower extremity – ABI 0.72, monitoring.\n"
            "4. Diabetic foot care – left foot at risk.\n"
            "PLAN: Podiatry monthly. Optimize glycemic control. "
            "Vascular surgery follow-up for left leg."
        ),
        "expected_icd10_codes": ["Z89.511", "E11.51", "I73.9"],
        "expected_hcc_codes": [189, 17, 107],
        "expected_raf_score_range": [0.80, 2.00],
    },
]


# ---------------------------------------------------------------------------
# Metric helpers
# ---------------------------------------------------------------------------

def _precision_recall_f1(
    predicted: list[str],
    expected: list[str],
) -> tuple[float, float, float]:
    """Compute precision, recall, F1 for string list comparison."""
    pred_set = set(c.upper().replace(".", "").replace(" ", "") for c in predicted)
    exp_set  = set(c.upper().replace(".", "").replace(" ", "") for c in expected)

    if not exp_set and not pred_set:
        return 1.0, 1.0, 1.0
    if not pred_set:
        return 0.0, 0.0, 0.0
    if not exp_set:
        return 0.0, 1.0, 0.0  # predicted something when nothing expected

    tp = len(pred_set & exp_set)
    precision = tp / len(pred_set) if pred_set else 0.0
    recall    = tp / len(exp_set)  if exp_set  else 0.0
    f1        = (2 * precision * recall / (precision + recall)) if (precision + recall) > 0 else 0.0
    return round(precision, 4), round(recall, 4), round(f1, 4)


def _hcc_int_set(hcc_list: list) -> set[int]:
    """Normalise HCC codes to a set of ints."""
    result: set[int] = set()
    for h in hcc_list:
        try:
            s = str(h).upper().replace("HCC", "").strip()
            result.add(int(s))
        except (ValueError, AttributeError):
            pass
    return result


# ---------------------------------------------------------------------------
# Pipeline invocation helper
# ---------------------------------------------------------------------------

def _run_pipeline_for_note(note_text: str) -> dict[str, Any]:
    """
    Call the verified pipeline with minimal demographics (unknown).
    Returns the pipeline result dict.
    Wrapped in try/except so a single case failure does not abort the benchmark.
    """
    try:
        from app.services.pipeline_orchestrator import run_verified_pipeline
        return run_verified_pipeline(note_text, patient_age=70, patient_sex="M")
    except Exception as exc:
        logger.warning("[Benchmark] Pipeline call failed: %s", exc)
        return {"diagnoses": [], "hcc_details": [], "raf_score": None, "_error": str(exc)}


def _extract_predicted_icd10(pipeline_result: dict) -> list[str]:
    """Pull ICD-10 codes from pipeline diagnoses list."""
    codes: list[str] = []
    for dx in pipeline_result.get("diagnoses") or []:
        code = dx.get("icd10_code") or dx.get("icd10") or dx.get("code") or ""
        if code:
            codes.append(code.strip().upper())
    return codes


def _extract_predicted_hccs(pipeline_result: dict) -> list[int]:
    """Pull HCC numbers from pipeline hcc_details or diagnoses."""
    hccs: set[int] = set()

    # From hcc_details (RAF calculator output)
    for h in pipeline_result.get("hcc_details") or []:
        hcc_val = h.get("hcc_code") or h.get("hcc") or ""
        try:
            hccs.add(int(str(hcc_val).upper().replace("HCC", "")))
        except (ValueError, AttributeError):
            pass

    # Also scan diagnoses entries
    for dx in pipeline_result.get("diagnoses") or []:
        hcc_val = dx.get("hcc") or dx.get("hcc_code") or ""
        if hcc_val:
            try:
                hccs.add(int(str(hcc_val).upper().replace("HCC", "")))
            except (ValueError, AttributeError):
                pass

    return list(hccs)


def _extract_predicted_raf(pipeline_result: dict) -> float | None:
    """Extract the numeric RAF score from pipeline result."""
    score = pipeline_result.get("raf_score")
    if score is None:
        # Try nested raf breakdown
        breakdown = pipeline_result.get("raf_breakdown") or {}
        score = breakdown.get("blended_raf") or breakdown.get("raw_raf")
    try:
        return float(score)
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Core benchmark runner
# ---------------------------------------------------------------------------

def run_accuracy_benchmark(test_cases: list[dict] | None = None) -> dict[str, Any]:
    """
    Run the NLP pipeline against a set of gold-standard test cases and compute
    accuracy metrics.

    Parameters
    ----------
    test_cases:
        Optional list of custom test case dicts.  When None, the built-in
        GOLD_STANDARD_TEST_CASES are used.

    Each test_case dict:
    {
        "id": str,                           (optional, auto-generated if missing)
        "note_text": str,
        "expected_icd10_codes": list[str],
        "expected_hcc_codes": list[int],
        "expected_raf_score_range": [min, max],
    }

    Returns
    -------
    {
        "run_id": str,
        "run_timestamp": str (ISO-8601),
        "suite_version": str,
        "total_cases": int,
        "icd10_metrics": {
            "precision": float,
            "recall": float,
            "f1_score": float,
            "per_code_accuracy": dict[str, dict],
        },
        "hcc_metrics": {
            "precision": float,
            "recall": float,
            "f1_score": float,
            "capture_rate": float,
        },
        "raf_metrics": {
            "mean_absolute_error": float,
            "within_range_rate": float,
        },
        "per_case_results": list[dict],
        "duration_seconds": float,
    }
    """
    cases = test_cases if test_cases is not None else GOLD_STANDARD_TEST_CASES
    run_id = str(uuid.uuid4())
    run_start = time.time()

    per_case_results: list[dict] = []

    # Aggregate containers
    all_icd10_precisions: list[float] = []
    all_icd10_recalls: list[float]    = []
    all_icd10_f1s: list[float]        = []
    all_hcc_precisions: list[float]   = []
    all_hcc_recalls: list[float]      = []
    all_hcc_f1s: list[float]          = []
    raf_absolute_errors: list[float]  = []
    raf_within_range: list[bool]      = []

    # Per-code ICD-10 tracking: code -> {tp, fp, fn}
    per_code_stats: dict[str, dict[str, int]] = {}

    logger.info("[Benchmark] Starting run %s with %d test cases", run_id, len(cases))

    for idx, case in enumerate(cases):
        case_id   = case.get("id") or f"CASE-{idx + 1:03d}"
        note_text = case.get("note_text", "")
        exp_icd   = [c.upper() for c in (case.get("expected_icd10_codes") or [])]
        exp_hcc   = list(case.get("expected_hcc_codes") or [])
        raf_range = case.get("expected_raf_score_range") or [0.0, 99.0]

        t_case = time.time()
        pipeline_result = _run_pipeline_for_note(note_text)
        case_duration = round(time.time() - t_case, 3)

        pred_icd = _extract_predicted_icd10(pipeline_result)
        pred_hcc = _extract_predicted_hccs(pipeline_result)
        pred_raf = _extract_predicted_raf(pipeline_result)

        # ICD-10 metrics for this case
        icd_prec, icd_rec, icd_f1 = _precision_recall_f1(pred_icd, exp_icd)
        all_icd10_precisions.append(icd_prec)
        all_icd10_recalls.append(icd_rec)
        all_icd10_f1s.append(icd_f1)

        # Per-code tracking
        pred_norm = set(c.replace(".", "").replace(" ", "") for c in pred_icd)
        exp_norm  = set(c.replace(".", "").replace(" ", "") for c in exp_icd)
        for code in exp_norm:
            if code not in per_code_stats:
                per_code_stats[code] = {"tp": 0, "fp": 0, "fn": 0}
            if code in pred_norm:
                per_code_stats[code]["tp"] += 1
            else:
                per_code_stats[code]["fn"] += 1
        for code in pred_norm - exp_norm:
            if code not in per_code_stats:
                per_code_stats[code] = {"tp": 0, "fp": 0, "fn": 0}
            per_code_stats[code]["fp"] += 1

        # HCC metrics for this case
        hcc_prec, hcc_rec, hcc_f1 = _precision_recall_f1(
            [str(h) for h in pred_hcc],
            [str(h) for h in exp_hcc],
        )
        all_hcc_precisions.append(hcc_prec)
        all_hcc_recalls.append(hcc_rec)
        all_hcc_f1s.append(hcc_f1)

        # RAF metrics
        if pred_raf is not None:
            raf_min, raf_max = float(raf_range[0]), float(raf_range[1])
            raf_absolute_errors.append(abs(pred_raf - (raf_min + raf_max) / 2.0))
            raf_within_range.append(raf_min <= pred_raf <= raf_max)

        per_case_results.append({
            "case_id":             case_id,
            "name":                case.get("name", ""),
            "category":            case.get("category", ""),
            "expected_icd10":      exp_icd,
            "predicted_icd10":     pred_icd,
            "expected_hcc":        exp_hcc,
            "predicted_hcc":       pred_hcc,
            "expected_raf_range":  raf_range,
            "predicted_raf":       pred_raf,
            "icd10_precision":     icd_prec,
            "icd10_recall":        icd_rec,
            "icd10_f1":            icd_f1,
            "hcc_precision":       hcc_prec,
            "hcc_recall":          hcc_rec,
            "hcc_f1":              hcc_f1,
            "raf_within_range":    raf_within_range[-1] if raf_within_range else None,
            "duration_seconds":    case_duration,
            "pipeline_error":      pipeline_result.get("_error"),
        })

        logger.info(
            "[Benchmark] Case %s (%s): ICD-F1=%.2f HCC-F1=%.2f RAF=%s",
            case_id, case.get("name", ""),
            icd_f1, hcc_f1,
            f"{pred_raf:.3f}" if pred_raf is not None else "N/A",
        )

    total_cases = len(cases)
    n = total_cases or 1  # guard divide-by-zero

    # Aggregate ICD-10 metrics
    agg_icd_prec = round(sum(all_icd10_precisions) / n, 4)
    agg_icd_rec  = round(sum(all_icd10_recalls) / n, 4)
    agg_icd_f1   = round(sum(all_icd10_f1s) / n, 4)

    # Per-code accuracy: precision per code
    per_code_accuracy: dict[str, dict] = {}
    for code, stats in per_code_stats.items():
        tp, fp, fn = stats["tp"], stats["fp"], stats["fn"]
        prec = round(tp / (tp + fp), 4) if (tp + fp) > 0 else 0.0
        rec  = round(tp / (tp + fn), 4) if (tp + fn) > 0 else 0.0
        f1   = round(2 * prec * rec / (prec + rec), 4) if (prec + rec) > 0 else 0.0
        per_code_accuracy[code] = {"precision": prec, "recall": rec, "f1": f1, **stats}

    # HCC aggregate metrics
    agg_hcc_prec = round(sum(all_hcc_precisions) / n, 4)
    agg_hcc_rec  = round(sum(all_hcc_recalls) / n, 4)
    agg_hcc_f1   = round(sum(all_hcc_f1s) / n, 4)

    # HCC capture rate = macro-average recall across cases that had expected HCCs
    cases_with_hcc = [r for r in per_case_results if r["expected_hcc"]]
    hcc_capture = round(
        sum(r["hcc_recall"] for r in cases_with_hcc) / len(cases_with_hcc), 4
    ) if cases_with_hcc else 0.0

    # RAF metrics
    raf_mae  = round(sum(raf_absolute_errors) / len(raf_absolute_errors), 4) if raf_absolute_errors else 0.0
    raf_rate = round(sum(raf_within_range) / len(raf_within_range), 4) if raf_within_range else 0.0

    duration = round(time.time() - run_start, 2)

    result: dict[str, Any] = {
        "run_id":         run_id,
        "run_timestamp":  datetime.utcnow().isoformat() + "Z",
        "suite_version":  BENCHMARK_SUITE_VERSION,
        "total_cases":    total_cases,
        "icd10_metrics": {
            "precision":       agg_icd_prec,
            "recall":          agg_icd_rec,
            "f1_score":        agg_icd_f1,
            "per_code_accuracy": per_code_accuracy,
        },
        "hcc_metrics": {
            "precision":    agg_hcc_prec,
            "recall":       agg_hcc_rec,
            "f1_score":     agg_hcc_f1,
            "capture_rate": hcc_capture,
        },
        "raf_metrics": {
            "mean_absolute_error": raf_mae,
            "within_range_rate":   raf_rate,
        },
        "per_case_results": per_case_results,
        "duration_seconds": duration,
    }

    logger.info(
        "[Benchmark] Run %s complete in %.1fs — ICD-F1=%.3f HCC-F1=%.3f HCC-Capture=%.3f",
        run_id, duration, agg_icd_f1, agg_hcc_f1, hcc_capture,
    )

    # Persist to RAF DB (best-effort — do not fail the caller if DB is unavailable)
    _persist_benchmark_result(result)

    return result


# ---------------------------------------------------------------------------
# Persistence helpers
# ---------------------------------------------------------------------------

def _persist_benchmark_result(result: dict[str, Any]) -> None:
    """Save a completed benchmark run to the RAF Intelligence database."""
    try:
        from app.db import raf_cursor
        with raf_cursor() as cur:
            cur.execute(
                """
                INSERT INTO benchmark_runs
                    (run_id, run_timestamp, suite_version, total_cases,
                     icd10_f1, hcc_f1, hcc_capture_rate, raf_mae, raf_within_range_rate,
                     duration_seconds, result_json)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                    result_json = VALUES(result_json)
                """,
                (
                    result["run_id"],
                    result["run_timestamp"],
                    result["suite_version"],
                    result["total_cases"],
                    result["icd10_metrics"]["f1_score"],
                    result["hcc_metrics"]["f1_score"],
                    result["hcc_metrics"]["capture_rate"],
                    result["raf_metrics"]["mean_absolute_error"],
                    result["raf_metrics"]["within_range_rate"],
                    result["duration_seconds"],
                    json.dumps(result),
                ),
            )
    except Exception as exc:
        logger.warning("[Benchmark] Could not persist run to DB (non-fatal): %s", exc)


def get_latest_benchmark_result() -> dict[str, Any] | None:
    """Retrieve the most recent benchmark run from the database."""
    try:
        from app.db import raf_cursor
        with raf_cursor() as cur:
            cur.execute(
                "SELECT result_json FROM benchmark_runs ORDER BY run_timestamp DESC LIMIT 1"
            )
            row = cur.fetchone()
        if row:
            return json.loads(row["result_json"])
    except Exception as exc:
        logger.warning("[Benchmark] Could not retrieve latest result: %s", exc)
    return None


def get_benchmark_history(limit: int = 20) -> list[dict[str, Any]]:
    """Retrieve benchmark run history (summary rows, no per-case detail)."""
    try:
        from app.db import raf_cursor
        with raf_cursor() as cur:
            cur.execute(
                """
                SELECT run_id, run_timestamp, suite_version, total_cases,
                       icd10_f1, hcc_f1, hcc_capture_rate, raf_mae,
                       raf_within_range_rate, duration_seconds
                FROM benchmark_runs
                ORDER BY run_timestamp DESC
                LIMIT %s
                """,
                (limit,),
            )
            rows = cur.fetchall()
        return [dict(r) for r in rows] if rows else []
    except Exception as exc:
        logger.warning("[Benchmark] Could not retrieve history: %s", exc)
    return []


def get_test_cases() -> list[dict[str, Any]]:
    """Return the built-in gold-standard test cases (note text truncated for listings)."""
    return [
        {
            "id":                     c.get("id"),
            "name":                   c.get("name"),
            "category":               c.get("category"),
            "note_text_preview":      (c.get("note_text") or "")[:300] + "...",
            "expected_icd10_codes":   c.get("expected_icd10_codes"),
            "expected_hcc_codes":     c.get("expected_hcc_codes"),
            "expected_raf_score_range": c.get("expected_raf_score_range"),
        }
        for c in GOLD_STANDARD_TEST_CASES
    ]
