"""Seed rich clinical data into OpenEMR local DB for demo patients."""
import uuid
import random

random.seed(42)

from app.db import openemr_cursor

# MEDS: (drug_name, rxnorm, dosage, size, route, instructions)
MEDS = {
    "I50.20": [
        ("Lisinopril 10mg", "29046", "10mg", "10", "oral", "Take 1 tablet by mouth daily"),
        ("Carvedilol 12.5mg", "20352", "12.5mg", "12.5", "oral", "Take 1 tablet by mouth twice daily"),
        ("Furosemide 40mg", "4603", "40mg", "40", "oral", "Take 1 tablet by mouth daily"),
    ],
    "I48.91": [
        ("Apixaban 5mg", "1364430", "5mg", "5", "oral", "Take 1 tablet by mouth twice daily"),
    ],
    "N18.4": [
        ("Sodium Bicarbonate 650mg", "8865", "650mg", "650", "oral", "Take 1 tablet three times daily"),
    ],
    "I10": [
        ("Amlodipine 5mg", "329526", "5mg", "5", "oral", "Take 1 tablet by mouth daily"),
    ],
    "E78.5": [
        ("Atorvastatin 40mg", "259255", "40mg", "40", "oral", "Take 1 tablet daily at bedtime"),
    ],
    "E11.9": [
        ("Metformin 500mg", "861007", "500mg", "500", "oral", "Take 1 tablet twice daily with meals"),
        ("Glipizide 5mg", "310488", "5mg", "5", "oral", "Take 1 tablet daily before breakfast"),
    ],
    "J44.1": [
        ("Tiotropium 18mcg", "896209", "18mcg", "18", "inhalation", "Inhale 1 capsule daily"),
        ("Albuterol 90mcg", "245314", "90mcg", "90", "inhalation", "Inhale 2 puffs every 4-6 hours as needed"),
    ],
    "G20": [
        ("Carbidopa-Levodopa 25/100", "858810", "25/100mg", "100", "oral", "Take 1 tablet three times daily"),
    ],
    "F32.9": [
        ("Sertraline 50mg", "312940", "50mg", "50", "oral", "Take 1 tablet by mouth daily"),
    ],
    "M81.0": [
        ("Alendronate 70mg", "993955", "70mg", "70", "oral", "Take 1 tablet weekly on empty stomach"),
    ],
    "N18.3": [
        ("Sodium Bicarbonate 650mg", "8865", "650mg", "650", "oral", "Take 1 tablet twice daily"),
    ],
    "I25.10": [
        ("Aspirin 81mg", "243670", "81mg", "81", "oral", "Take 1 tablet by mouth daily"),
        ("Clopidogrel 75mg", "309362", "75mg", "75", "oral", "Take 1 tablet by mouth daily"),
    ],
    "E11.65": [
        ("Metformin 1000mg", "861004", "1000mg", "1000", "oral", "Take 1 tablet twice daily with meals"),
        ("Insulin Glargine 20u", "311040", "20 units", "20", "subcutaneous", "Inject 20 units daily at bedtime"),
    ],
    "G30.9": [
        ("Donepezil 10mg", "997221", "10mg", "10", "oral", "Take 1 tablet daily at bedtime"),
    ],
    "J44.0": [
        ("Tiotropium 18mcg", "896209", "18mcg", "18", "inhalation", "Inhale 1 capsule daily"),
        ("Fluticasone/Salmeterol", "896188", "250/50mcg", "250", "inhalation", "Inhale 1 puff twice daily"),
    ],
}

LANGUAGES = {
    28: "English", 29: "English", 30: "Spanish", 31: "English",
    32: "English", 33: "English", 34: "English", 35: "English",
    36: "English", 37: "English", 38: "Vietnamese", 39: "English",
    40: "English", 41: "Spanish", 42: "English",
}

ALLERGIES = [
    ("Penicillin", "ICD10:Z88.0"),
    ("Sulfonamides", "ICD10:Z88.2"),
    ("Aspirin", "ICD10:Z88.1"),
    ("Latex", ""),
    ("Codeine", "ICD10:Z88.5"),
    ("Iodine contrast dye", ""),
    ("Shellfish", ""),
]

LAB_PANELS = [
    ("Comprehensive Metabolic Panel", "CMP", [
        ("Glucose", "2345-7", "mg/dL", "70-100"),
        ("BUN", "3094-0", "mg/dL", "7-20"),
        ("Creatinine", "2160-0", "mg/dL", "0.7-1.3"),
        ("Sodium", "2951-2", "mEq/L", "136-145"),
        ("Potassium", "2823-3", "mEq/L", "3.5-5.0"),
        ("eGFR", "33914-3", "mL/min", ">60"),
        ("ALT", "1742-6", "U/L", "7-56"),
        ("AST", "1920-8", "U/L", "10-40"),
    ]),
    ("Complete Blood Count", "CBC", [
        ("WBC", "6690-2", "/uL", "4500-11000"),
        ("Hemoglobin", "718-7", "g/dL", "12.0-17.5"),
        ("Hematocrit", "4544-3", "%", "36-51"),
        ("Platelets", "777-3", "/uL", "150000-400000"),
    ]),
    ("Lipid Panel", "LIPID", [
        ("Total Cholesterol", "2093-3", "mg/dL", "<200"),
        ("LDL Cholesterol", "2089-1", "mg/dL", "<100"),
        ("HDL Cholesterol", "2085-9", "mg/dL", ">40"),
        ("Triglycerides", "2571-8", "mg/dL", "<150"),
    ]),
    ("Hemoglobin A1c", "HBA1C", [
        ("HbA1c", "4548-4", "%", "<5.7"),
    ]),
]


def lab_value(name):
    return str({
        "Glucose": random.randint(85, 180),
        "BUN": random.randint(12, 45),
        "Creatinine": round(random.uniform(0.8, 3.5), 1),
        "Sodium": random.randint(134, 146),
        "Potassium": round(random.uniform(3.4, 5.6), 1),
        "eGFR": random.randint(15, 90),
        "ALT": random.randint(12, 65),
        "AST": random.randint(14, 55),
        "WBC": random.randint(4000, 12000),
        "Hemoglobin": round(random.uniform(9.5, 16.0), 1),
        "Hematocrit": round(random.uniform(30, 48), 1),
        "Platelets": random.randint(130000, 380000),
        "Total Cholesterol": random.randint(150, 260),
        "LDL Cholesterol": random.randint(60, 180),
        "HDL Cholesterol": random.randint(30, 70),
        "Triglycerides": random.randint(90, 250),
        "HbA1c": round(random.uniform(5.2, 9.8), 1),
    }.get(name, random.randint(50, 150)))


def main():
    with openemr_cursor(tenant_id="1") as cur:
        # 1) Update languages
        for pid, lang in LANGUAGES.items():
            cur.execute("UPDATE patient_data SET language=%s WHERE pid=%s", (lang, pid))
        print(f"[1] Updated language for {len(LANGUAGES)} patients")

        # 2) Get diagnoses per patient
        cur.execute(
            "SELECT pid, diagnosis FROM lists "
            "WHERE type='medical_problem' AND diagnosis IS NOT NULL AND diagnosis != ''"
        )
        patient_dx = {}
        for r in cur.fetchall():
            code = r["diagnosis"].replace("ICD10:", "")
            patient_dx.setdefault(r["pid"], []).append(code)

        # 3) Get first encounter per patient
        cur.execute("SELECT pid, MIN(id) AS eid FROM form_encounter GROUP BY pid")
        first_enc = {r["pid"]: r["eid"] for r in cur.fetchall()}

        # 4) Insert prescriptions (form=1=tablet, unit=5=mg, interval=0)
        med_count = 0
        for pid, codes in patient_dx.items():
            enc = first_enc.get(pid, 0)
            for code in codes:
                for med in MEDS.get(code, []):
                    drug, rxnorm, dosage, size, route, instructions = med
                    days = random.randint(30, 365)
                    cur.execute(
                        "INSERT INTO prescriptions "
                        "(uuid, patient_id, encounter, date_added, date_modified, start_date, "
                        " drug, rxnorm_drugcode, form, dosage, quantity, size, unit, route, "
                        " `interval`, active, medication, txDate, "
                        " usage_category, usage_category_title, "
                        " request_intent, request_intent_title, drug_dosage_instructions) "
                        "VALUES (%s,%s,%s,NOW(),NOW(),DATE_SUB(CURDATE(), INTERVAL %s DAY),"
                        " %s,%s,1,%s,'30',%s,5,%s,"
                        " 0,1,1,NOW(),"
                        " 'active','Active',"
                        " 'order','Order',%s)",
                        (uuid.uuid4().bytes, pid, enc, days,
                         drug, rxnorm, dosage, size, route, instructions),
                    )
                    med_count += 1
        print(f"[2] Inserted {med_count} prescriptions")

        # 5) Insert lab orders + results
        lab_count = 0
        for pid in range(28, 43):
            enc = first_enc.get(pid, 0)
            for panel_name, panel_code, results in LAB_PANELS:
                days_ago = random.randint(5, 90)
                cur.execute(
                    "INSERT INTO procedure_order "
                    "(uuid, provider_id, patient_id, encounter_id, date_collected, date_ordered, "
                    " order_priority, order_status, activity, procedure_order_type) "
                    "VALUES (%s, 1, %s, %s, DATE_SUB(CURDATE(), INTERVAL %s DAY), "
                    " DATE_SUB(CURDATE(), INTERVAL %s DAY), "
                    " 'normal', 'complete', 1, 'order')",
                    (uuid.uuid4().bytes, pid, enc, days_ago, days_ago),
                )
                order_id = cur.lastrowid

                cur.execute(
                    "INSERT INTO procedure_order_code "
                    "(procedure_order_id, procedure_order_seq, procedure_code, procedure_name, "
                    " diagnoses, procedure_order_title) "
                    "VALUES (%s, 1, %s, %s, '', %s)",
                    (order_id, panel_code, panel_name, panel_name),
                )

                cur.execute(
                    "INSERT INTO procedure_report "
                    "(procedure_order_id, procedure_order_seq, date_collected, date_report, "
                    " report_status, review_status) "
                    "VALUES (%s, 1, DATE_SUB(CURDATE(), INTERVAL %s DAY), "
                    " DATE_SUB(CURDATE(), INTERVAL %s DAY), 'final', 'reviewed')",
                    (order_id, days_ago, max(days_ago - 1, 0)),
                )
                report_id = cur.lastrowid

                for rname, loinc, units, ref_range in results:
                    val = lab_value(rname)
                    cur.execute(
                        "INSERT INTO procedure_result "
                        "(procedure_report_id, result_code, result_text, result, "
                        " units, `range`, abnormal, result_status, date) "
                        "VALUES (%s, %s, %s, %s, %s, %s, '', 'final', "
                        " DATE_SUB(CURDATE(), INTERVAL %s DAY))",
                        (report_id, loinc, rname, val, units, ref_range, days_ago),
                    )
                    lab_count += 1
        print(f"[3] Inserted {lab_count} lab results for 15 patients")

        # 6) Insert allergies
        allergy_count = 0
        for pid in range(28, 43):
            n = random.randint(1, 3)
            chosen = random.sample(ALLERGIES, n)
            for title, dx in chosen:
                cur.execute(
                    "INSERT INTO lists (uuid, pid, type, title, diagnosis, begdate, activity) "
                    "VALUES (%s, %s, 'allergy', %s, %s, "
                    " DATE_SUB(CURDATE(), INTERVAL %s DAY), 1)",
                    (uuid.uuid4().bytes, pid, title, dx, random.randint(100, 2000)),
                )
                allergy_count += 1
        print(f"[4] Inserted {allergy_count} allergies")

    print("DONE - committed")


if __name__ == "__main__":
    main()
