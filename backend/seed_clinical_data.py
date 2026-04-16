"""
Seed comprehensive clinical data into OpenEMR for all 15 patients.
Run: source .venv/bin/activate && python seed_clinical_data.py
"""
import sys
import os
import random
from datetime import date, timedelta, datetime

sys.path.insert(0, os.path.dirname(__file__))
from app.db import openemr_cursor


def rand_date(start_year=2024, end_year=2026):
    start = date(start_year, 1, 1)
    end = date(end_year, 3, 31)
    return start + timedelta(days=random.randint(0, (end - start).days))


# ---------------------------------------------------------------------------
# Data pools
# ---------------------------------------------------------------------------
PROBLEMS = [
    ("E11.9", "Type 2 diabetes mellitus without complications"),
    ("I50.9", "Heart failure, unspecified"),
    ("J44.1", "COPD with acute exacerbation"),
    ("I10", "Essential hypertension"),
    ("F32.1", "Major depressive disorder, single episode, moderate"),
    ("N18.3", "Chronic kidney disease, stage 3"),
    ("E78.5", "Hyperlipidemia, unspecified"),
    ("I25.10", "Atherosclerotic heart disease of native coronary artery"),
    ("G47.33", "Obstructive sleep apnea"),
    ("M17.11", "Primary osteoarthritis, right knee"),
    ("E03.9", "Hypothyroidism, unspecified"),
    ("G20", "Parkinson disease"),
    ("I48.91", "Unspecified atrial fibrillation"),
    ("J45.40", "Moderate persistent asthma, uncomplicated"),
    ("K21.0", "GERD with esophagitis"),
    ("M81.0", "Age-related osteoporosis"),
    ("E66.01", "Morbid obesity due to excess calories"),
    ("I63.9", "Cerebral infarction, unspecified"),
    ("C50.919", "Malignant neoplasm of breast"),
    ("N40.0", "Benign prostatic hyperplasia"),
]

LAB_TEMPLATES = [
    ("HbA1c", "4614-6", "%", "4.0-5.6", 5.0, 11.0),
    ("Glucose", "2345-7", "mg/dL", "70-100", 70, 250),
    ("Creatinine", "2160-0", "mg/dL", "0.6-1.2", 0.5, 3.0),
    ("eGFR", "33914-3", "mL/min/1.73m2", ">60", 25, 120),
    ("Total Cholesterol", "2093-3", "mg/dL", "<200", 150, 300),
    ("LDL", "2089-1", "mg/dL", "<100", 60, 200),
    ("HDL", "2085-9", "mg/dL", ">40", 30, 80),
    ("Triglycerides", "2571-8", "mg/dL", "<150", 80, 400),
    ("TSH", "3016-3", "mIU/L", "0.4-4.0", 0.1, 10.0),
    ("WBC", "6690-2", "K/uL", "4.5-11.0", 3.0, 15.0),
    ("Hemoglobin", "718-7", "g/dL", "12.0-17.5", 9.0, 17.0),
    ("Platelets", "777-3", "K/uL", "150-400", 100, 500),
    ("BUN", "3094-0", "mg/dL", "7-20", 5, 45),
    ("ALT", "1742-6", "U/L", "7-56", 10, 90),
    ("AST", "1920-8", "U/L", "10-40", 10, 80),
]

IMMUNIZATIONS = [
    ("213", "COVID-19 Vaccine (Pfizer)"),
    ("213", "COVID-19 Vaccine (Moderna)"),
    ("140", "Influenza Vaccine"),
    ("33", "Pneumococcal Vaccine"),
    ("115", "Tdap Vaccine"),
    ("187", "Zoster Vaccine Recombinant"),
    ("43", "Hepatitis B Vaccine"),
]

ALLERGIES = [
    ("Penicillin", "Rash, hives"),
    ("Sulfa drugs", "Anaphylaxis"),
    ("Aspirin", "GI upset"),
    ("Latex", "Contact dermatitis"),
    ("Codeine", "Nausea, vomiting"),
    ("Ibuprofen", "GI bleeding"),
    ("Amoxicillin", "Rash"),
    ("Lisinopril", "Angioedema"),
    ("Morphine", "Respiratory depression"),
    ("Metformin", "Lactic acidosis"),
    ("Shellfish", "Anaphylaxis"),
    ("Peanuts", "Anaphylaxis"),
    ("Contrast dye", "Anaphylactoid reaction"),
]

SDOH_CODES = [
    ("Z59.0", "Homelessness"),
    ("Z63.0", "Problems in relationship with spouse or partner"),
    ("Z56.0", "Unemployment, unspecified"),
    ("Z60.2", "Problems related to living alone"),
    ("Z71.3", "Dietary counseling and surveillance"),
    ("Z59.1", "Inadequate housing"),
    ("Z91.120", "Intentional underdosing due to financial hardship"),
]

REFERRAL_SPECIALTIES = [
    ("Cardiology", "Dr. Sarah Chen", "Cardiac evaluation and management"),
    ("Endocrinology", "Dr. James Wright", "Diabetes management optimization"),
    ("Pulmonology", "Dr. Maria Garcia", "COPD management and PFT"),
    ("Nephrology", "Dr. Robert Kim", "CKD monitoring and renal assessment"),
    ("Psychiatry", "Dr. Lisa Patel", "Depression management"),
    ("Orthopedics", "Dr. Michael Brown", "Joint pain evaluation"),
    ("Neurology", "Dr. Amanda Foster", "Neurological evaluation"),
    ("Gastroenterology", "Dr. David Lee", "GI symptom evaluation"),
    ("Oncology", "Dr. Rachel Adams", "Cancer screening follow-up"),
    ("Sleep Medicine", "Dr. Kevin Nguyen", "Sleep study for suspected OSA"),
]

NOTE_TEMPLATES = [
    "Patient presents for follow-up of {cond}. Reports compliance with current medications. "
    "Vital signs stable. Physical exam notable for {finding}. "
    "Plan: Continue current regimen, follow up in {weeks} weeks. Order labs for monitoring.",
    "Established patient seen for management of {cond}. Patient reports {symptom}. "
    "Review of systems positive for {ros}. Assessment: {cond} - stable. "
    "Plan: Adjust {med} dosage, recheck in {weeks} weeks.",
    "Annual wellness visit. History of {cond}. Preventive screening reviewed. "
    "Immunizations up to date. HCC recapture documented for {hcc}. Referral placed to {spec}.",
    "Chronic care management visit for {cond}. Patient endorses {symptom}. "
    "Labs reviewed showing {lab_find}. A1c {a1c}%. eGFR {egfr} mL/min. "
    "Assessment: {cond} with {status}. Plan: Continue medications, lifestyle modifications.",
]

FINDINGS = ["mild pedal edema", "decreased breath sounds bilaterally", "BMI 32.4",
            "BP 148/92", "irregular heart rhythm", "joint crepitus right knee",
            "mild hepatomegaly", "bilateral wheezing", "diminished peripheral pulses"]
SYMPTOMS = ["fatigue", "shortness of breath on exertion", "increased thirst and urination",
            "joint stiffness", "difficulty sleeping", "chest tightness",
            "intermittent dizziness", "weight gain of 5 lbs", "mild peripheral neuropathy"]
ROS = ["fatigue, mild dyspnea", "polyuria, polydipsia", "chest pain on exertion",
       "joint pain and stiffness", "depressed mood, insomnia", "peripheral edema"]
MEDS = ["metformin", "lisinopril", "atorvastatin", "amlodipine", "sertraline", "albuterol"]

FAMILY_HISTORIES = [
    "Father: MI at 55, Type 2 diabetes. Mother: Hypertension, breast cancer at 62.",
    "Father: COPD, died at 70. Mother: Stroke at 68, hypertension.",
    "Father: Healthy, age 78. Mother: Type 2 diabetes, CKD.",
    "Father: Colon cancer at 60. Mother: Depression, anxiety.",
    "Father: Atrial fibrillation, CHF. Mother: Osteoporosis, hip fracture at 72.",
    "Father: Alcoholism, liver cirrhosis. Mother: Type 2 diabetes, obesity.",
    "Father: Prostate cancer at 65. Mother: Alzheimer at 75.",
    "Father: Hypertension, hyperlipidemia. Mother: Asthma, GERD.",
    "Father: Type 2 diabetes, CKD. Mother: Breast cancer at 58, hypothyroidism.",
    "Father: MI at 48, sudden cardiac death. Mother: Rheumatoid arthritis.",
    "Father: Lung cancer (smoker). Mother: Hypertension, stroke at 70.",
    "Father: Healthy. Mother: Type 1 diabetes, retinopathy.",
    "Father: Parkinson disease at 65. Mother: Osteoporosis, depression.",
    "Father: Hepatitis C, cirrhosis. Mother: Ovarian cancer at 55.",
    "Father: CAD, triple bypass at 60. Mother: Type 2 diabetes, neuropathy.",
]


def main():
    random.seed(42)

    with openemr_cursor() as cur:
        # Get patient PIDs
        cur.execute("SELECT pid FROM patient_data ORDER BY pid LIMIT 15")
        pids = [r["pid"] for r in cur.fetchall()]
        print(f"Found {len(pids)} patients: {pids}")

        # Get encounters
        enc_map = {}
        for pid in pids:
            cur.execute("SELECT encounter FROM form_encounter WHERE pid = %s ORDER BY date DESC", (pid,))
            enc_map[pid] = [r["encounter"] for r in cur.fetchall()]
        print(f"Encounters: { {p: len(e) for p, e in enc_map.items()} }")

        # Check existing data
        cur.execute("SELECT pid, COUNT(*) c FROM lists WHERE type='medical_problem' AND activity=1 GROUP BY pid")
        existing_problems = {r["pid"]: r["c"] for r in cur.fetchall()}
        cur.execute("SELECT pid, COUNT(*) c FROM lists WHERE type='allergy' AND activity=1 GROUP BY pid")
        existing_allergies = {r["pid"]: r["c"] for r in cur.fetchall()}
        cur.execute("SELECT DISTINCT pid FROM billing WHERE activity=1 AND code_type='ICD10'")
        existing_billing_pids = {r["pid"] for r in cur.fetchall()}

        # =============================================================
        # 1. PROBLEM LIST
        # =============================================================
        print("\n--- Problem List ---")
        for i, pid in enumerate(pids):
            if existing_problems.get(pid, 0) >= 3:
                print(f"  PID {pid}: already has {existing_problems[pid]} problems, skipping")
                continue
            num = random.randint(3, 5)
            for code, title in random.sample(PROBLEMS, num):
                bd = rand_date(2022, 2025)
                cur.execute(
                    "INSERT INTO lists (pid, type, title, diagnosis, begdate, activity) "
                    "VALUES (%s, 'medical_problem', %s, %s, %s, 1)",
                    (pid, title, f"ICD10:{code}", bd.isoformat()))
            print(f"  PID {pid}: inserted {num} problems")

        # =============================================================
        # 2. LABS (procedure_result - simplified schema)
        # procedure_result has: id, pid, encounter, date, result_text
        # We store structured lab data as formatted text in result_text
        # and also create procedure_order for the join path
        # =============================================================
        print("\n--- Labs ---")
        for pid in pids:
            encs = enc_map.get(pid, [])
            enc_id = encs[0] if encs else 0
            num_labs = random.randint(5, 8)
            selected = random.sample(LAB_TEMPLATES, num_labs)
            lab_date = rand_date(2025, 2026)

            # Create procedure_order
            cur.execute(
                "INSERT INTO procedure_order (patient_id, encounter_id, date_ordered) VALUES (%s, %s, %s)",
                (pid, enc_id, lab_date.isoformat()))
            order_id = cur.lastrowid

            for name, loinc, units, ref_range, lo, hi in selected:
                val = round(random.uniform(lo, hi), 1)
                # Determine abnormal
                abnormal = ""
                try:
                    if "-" in ref_range:
                        rlo, rhi = ref_range.split("-")
                        if val < float(rlo): abnormal = " [LOW]"
                        elif val > float(rhi): abnormal = " [HIGH]"
                    elif ref_range.startswith(">"):
                        if val < float(ref_range[1:]): abnormal = " [LOW]"
                    elif ref_range.startswith("<"):
                        if val > float(ref_range[1:]): abnormal = " [HIGH]"
                except (ValueError, TypeError):
                    pass

                result_text = f"{name} ({loinc}): {val} {units} (Ref: {ref_range}){abnormal}"
                cur.execute(
                    "INSERT INTO procedure_result (pid, encounter, date, result_text) VALUES (%s, %s, %s, %s)",
                    (pid, enc_id, lab_date.isoformat(), result_text))
            print(f"  PID {pid}: inserted {num_labs} lab results")

        # =============================================================
        # 3. CLINICAL NOTES (form_clinical_notes + forms)
        # form_clinical_notes: id, pid, encounter, date, note_type, note
        # forms: id, date, encounter, form_name, form_id, pid, formdir, deleted
        # =============================================================
        print("\n--- Clinical Notes ---")
        for pid in pids:
            encs = enc_map.get(pid, [])
            if not encs:
                print(f"  PID {pid}: no encounters, skipping")
                continue
            cur.execute("SELECT title FROM lists WHERE pid=%s AND type='medical_problem' AND activity=1", (pid,))
            pt_probs = [r["title"] for r in cur.fetchall()]
            cond = ", ".join(pt_probs[:3]) if pt_probs else "chronic conditions"

            for enc_id in encs[:2]:
                tmpl = random.choice(NOTE_TEMPLATES)
                note = tmpl.format(
                    cond=cond, finding=random.choice(FINDINGS), weeks=random.choice([4,6,8,12]),
                    symptom=random.choice(SYMPTOMS), ros=random.choice(ROS), med=random.choice(MEDS),
                    hcc=pt_probs[0] if pt_probs else "diabetes",
                    spec=random.choice(["Cardiology","Endocrinology","Pulmonology"]),
                    lab_find="improving trends", a1c=round(random.uniform(5.5,10),1),
                    egfr=random.randint(30,90), status="stable control")
                nd = rand_date(2025, 2026)
                try:
                    cur.execute(
                        "INSERT INTO form_clinical_notes (pid, encounter, date, note_type, note) "
                        "VALUES (%s, %s, %s, 'clinical_note', %s)",
                        (pid, enc_id, nd.isoformat(), note))
                    fid = cur.lastrowid
                    cur.execute(
                        "INSERT INTO forms (date, encounter, form_name, form_id, pid, formdir, deleted) "
                        "VALUES (%s, %s, 'Clinical Notes', %s, %s, 'clinical_notes', 0)",
                        (nd.isoformat(), enc_id, fid, pid))
                    print(f"  PID {pid}, Enc {enc_id}: inserted note")
                except Exception as e:
                    print(f"  PID {pid}, Enc {enc_id}: FAILED - {e}")

        # =============================================================
        # 4. IMMUNIZATIONS
        # immunizations: id, patient_id, administered_date, cvx_code, title, activity, added_erroneously
        # =============================================================
        print("\n--- Immunizations ---")
        for pid in pids:
            num = random.randint(2, 4)
            for cvx, title in random.sample(IMMUNIZATIONS, num):
                ad = rand_date(2023, 2026)
                cur.execute(
                    "INSERT INTO immunizations (patient_id, administered_date, cvx_code, title, activity, added_erroneously) "
                    "VALUES (%s, %s, %s, %s, 1, 0)",
                    (pid, ad.isoformat(), cvx, title))
            print(f"  PID {pid}: inserted {num} immunizations")

        # =============================================================
        # 5. FAMILY HISTORY - create history_data table if needed
        # =============================================================
        print("\n--- Family History ---")
        try:
            cur.execute("SELECT 1 FROM history_data LIMIT 1")
            cur.fetchall()
        except Exception:
            print("  Creating history_data table...")
            cur.execute("""
                CREATE TABLE IF NOT EXISTS history_data (
                    id BIGINT AUTO_INCREMENT PRIMARY KEY,
                    pid BIGINT,
                    date DATETIME DEFAULT CURRENT_TIMESTAMP,
                    relatives_cancer TEXT,
                    relatives_diabetes TEXT,
                    relatives_heart_disease TEXT,
                    relatives_hypertension TEXT,
                    relatives_stroke TEXT,
                    relatives_epilepsy TEXT,
                    relatives_mental_illness TEXT,
                    relatives_suicide TEXT,
                    relatives_alcohol TEXT,
                    relatives_drug TEXT,
                    relatives_tuberculosis TEXT,
                    relatives_arthritis TEXT,
                    relatives_asthma TEXT,
                    relatives_blood_disorder TEXT,
                    relatives_hiv TEXT,
                    relatives_other TEXT,
                    history_father TEXT,
                    history_mother TEXT,
                    history_siblings TEXT,
                    history_offspring TEXT,
                    history_spouse TEXT,
                    INDEX idx_pid (pid)
                )
            """)
            print("  Created history_data table")

        for i, pid in enumerate(pids):
            fh_text = FAMILY_HISTORIES[i % len(FAMILY_HISTORIES)]
            # Parse into father/mother
            father = ""
            mother = ""
            for part in fh_text.split(". "):
                if part.startswith("Father:"):
                    father = part.replace("Father: ", "")
                elif part.startswith("Mother:"):
                    mother = part.replace("Mother: ", "")

            cur.execute("SELECT id FROM history_data WHERE pid = %s LIMIT 1", (pid,))
            row = cur.fetchone()
            if row:
                cur.execute(
                    "UPDATE history_data SET history_father=%s, history_mother=%s, "
                    "relatives_heart_disease=%s, relatives_diabetes=%s, relatives_cancer=%s WHERE pid=%s",
                    (father, mother,
                     "Yes" if "MI" in fh_text or "CHF" in fh_text or "CAD" in fh_text else "",
                     "Yes" if "diabetes" in fh_text.lower() else "",
                     "Yes" if "cancer" in fh_text.lower() else "",
                     pid))
                print(f"  PID {pid}: updated family history")
            else:
                cur.execute(
                    "INSERT INTO history_data (pid, history_father, history_mother, "
                    "relatives_heart_disease, relatives_diabetes, relatives_cancer) "
                    "VALUES (%s, %s, %s, %s, %s, %s)",
                    (pid, father, mother,
                     "Yes" if "MI" in fh_text or "CHF" in fh_text or "CAD" in fh_text else "",
                     "Yes" if "diabetes" in fh_text.lower() else "",
                     "Yes" if "cancer" in fh_text.lower() else ""))
                print(f"  PID {pid}: inserted family history")

        # =============================================================
        # 6. SDOH Z-codes in billing
        # =============================================================
        print("\n--- SDOH Z-codes ---")
        for pid in pids:
            encs = enc_map.get(pid, [])
            if not encs: continue
            num = random.randint(1, 2)
            for code, text in random.sample(SDOH_CODES, num):
                cur.execute(
                    "INSERT INTO billing (pid, encounter, code_type, code, code_text, authorized, activity) "
                    "VALUES (%s, %s, 'ICD10', %s, %s, 1, 1)",
                    (pid, encs[0], code, text))
            print(f"  PID {pid}: inserted {num} SDOH Z-codes")

        # =============================================================
        # 7. ALLERGIES (for patients missing them)
        # =============================================================
        print("\n--- Allergies ---")
        for pid in pids:
            if existing_allergies.get(pid, 0) >= 1:
                print(f"  PID {pid}: already has allergies, skipping")
                continue
            num = random.randint(1, 3)
            for title, reaction in random.sample(ALLERGIES, num):
                bd = rand_date(2018, 2023)
                cur.execute(
                    "INSERT INTO lists (pid, type, title, comments, begdate, activity) "
                    "VALUES (%s, 'allergy', %s, %s, %s, 1)",
                    (pid, title, reaction, bd.isoformat()))
            print(f"  PID {pid}: inserted {num} allergies")

        # =============================================================
        # 8. BILLING CODES (for patients missing them)
        # =============================================================
        print("\n--- Billing Codes ---")
        for pid in pids:
            if pid in existing_billing_pids:
                print(f"  PID {pid}: already has billing, skipping")
                continue
            encs = enc_map.get(pid, [])
            if not encs: continue
            cur.execute(
                "SELECT diagnosis FROM lists WHERE pid=%s AND type='medical_problem' AND activity=1",
                (pid,))
            diags = [r["diagnosis"] for r in cur.fetchall() if r.get("diagnosis")]
            count = 0
            for d in diags[:4]:
                code = d.replace("ICD10:", "") if d else ""
                if not code: continue
                match = [p for p in PROBLEMS if p[0] == code]
                text = match[0][1] if match else code
                cur.execute(
                    "INSERT INTO billing (pid, encounter, code_type, code, code_text, authorized, activity) "
                    "VALUES (%s, %s, 'ICD10', %s, %s, 1, 1)",
                    (pid, encs[0], code, text))
                count += 1
            print(f"  PID {pid}: inserted {count} billing codes")

        # =============================================================
        # 9. REFERRALS - create transactions table if needed
        # =============================================================
        print("\n--- Referrals ---")
        try:
            cur.execute("SELECT 1 FROM transactions LIMIT 1")
            cur.fetchall()
        except Exception:
            print("  Creating transactions table...")
            cur.execute("""
                CREATE TABLE IF NOT EXISTS transactions (
                    id BIGINT AUTO_INCREMENT PRIMARY KEY,
                    date DATETIME DEFAULT CURRENT_TIMESTAMP,
                    title VARCHAR(255),
                    pid BIGINT,
                    body TEXT,
                    refer_to VARCHAR(255),
                    refer_from VARCHAR(255),
                    reason TEXT,
                    reply_date DATE,
                    user VARCHAR(100),
                    groupname VARCHAR(100),
                    authorized TINYINT DEFAULT 1,
                    INDEX idx_pid (pid)
                )
            """)
            print("  Created transactions table")

        for pid in pids:
            num = random.randint(1, 2)
            for spec, doc, reason in random.sample(REFERRAL_SPECIALTIES, num):
                rd = rand_date(2025, 2026)
                body = (f"Referral to {spec} - {doc}. Reason: {reason}. "
                        f"Patient has relevant diagnoses requiring specialist evaluation.")
                cur.execute(
                    "INSERT INTO transactions (date, title, pid, body, refer_to, refer_from, reason, "
                    "user, groupname, authorized) VALUES (%s, 'Referral', %s, %s, %s, 'Dr. Primary Care', %s, "
                    "'admin', 'Default', 1)",
                    (rd.isoformat(), pid, body, doc, reason))
            print(f"  PID {pid}: inserted {num} referrals")

    print("\n=== SEEDING COMPLETE ===")


if __name__ == "__main__":
    main()
