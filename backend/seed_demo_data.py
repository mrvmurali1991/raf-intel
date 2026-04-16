#!/usr/bin/env python3
"""Seed comprehensive demo data for RAF Intelligence platform - 30 patients."""

import mysql.connector
import json
import os
from datetime import datetime, date
from decimal import Decimal

conn = mysql.connector.connect(
    host=os.getenv("RAF_DB_HOST", "127.0.0.1"),
    port=int(os.getenv("RAF_DB_PORT", "3306")),
    user=os.getenv("RAF_DB_USER", "root"),
    password=os.getenv("RAF_DB_PASSWORD", ""),
    database=os.getenv("RAF_DB_NAME", "raf_intelligence"),
)
cur = conn.cursor()

# ============================================================
# STEP 0: Clear existing data
# Whitelist tables to prevent SQL injection via table-name interpolation.
# ============================================================
print("Clearing existing data...")
_ALLOWED_TABLES = {
    "raf_suspect_conditions",
    "raf_scores",
    "raf_patient_hcc",
    "raf_patient_demographics",
}
for table in ['raf_suspect_conditions', 'raf_scores', 'raf_patient_hcc', 'raf_patient_demographics']:
    if table not in _ALLOWED_TABLES:
        raise ValueError(f"Refusing to DELETE from non-whitelisted table: {table!r}")
    cur.execute(f'DELETE FROM {table}')
    print(f"  Deleted {cur.rowcount} rows from {table}")

# Delete non-original FHIR matches (keep raf_patient_id 1-9, delete the rest including duplicates)
cur.execute('DELETE FROM emr_patient_matches WHERE raf_patient_id IS NULL OR raf_patient_id NOT BETWEEN 1 AND 9')
print(f"  Deleted {cur.rowcount} duplicate/unmapped rows from emr_patient_matches")
conn.commit()

# ============================================================
# Patient definitions
# ============================================================
# Existing FHIR patients (raf_patient_id 1-9) - already in emr_patient_matches
fhir_patients = {
    1:  ('Dorothy Marie', 'Johnson',   '1948-01-15', 'F'),
    2:  ('Robert James',  'Williams',  '1944-07-15', 'M'),
    3:  ('Patrick',       'Cisneros',  '2009-03-23', 'M'),
    4:  ('Terry',         'Adams',     '2006-08-15', 'F'),
    5:  ('Julia',         'Jackson',   '1951-10-18', 'F'),
    6:  ('Ronald',        'Abeyta',    '1943-09-16', 'M'),
    7:  ('Maria',         'Garcia',    '1958-06-15', 'F'),
    8:  ('James',         'Thompson',  '1965-11-22', 'M'),
    9:  ('Sarah',         'Chen',      '1972-03-08', 'F'),
}

# Local OpenEMR patients (pid 1-15) -> raf_patient_id 10-24
local_patients = {
    10: (1,  'William',    'Anderson',   '1955-04-12', 'M'),
    11: (2,  'Margaret',   'Brown',      '1940-08-22', 'F'),
    12: (3,  'David',      'Martinez',   '1962-01-30', 'M'),
    13: (4,  'Linda',      'Taylor',     '1975-06-18', 'F'),
    14: (5,  'Richard',    'Lee',        '1950-11-05', 'M'),
    15: (6,  'Barbara',    'Wilson',     '1968-09-14', 'F'),
    16: (7,  'Charles',    'Moore',      '1938-03-27', 'M'),
    17: (8,  'Patricia',   'Davis',      '1947-12-01', 'F'),
    18: (9,  'Michael',    'Rodriguez',  '1980-07-09', 'M'),
    19: (10, 'Elizabeth',  'White',      '1933-05-20', 'F'),
    20: (11, 'Joseph',     'Harris',     '1971-02-14', 'M'),
    21: (12, 'Susan',      'Clark',      '1960-10-31', 'F'),
    22: (13, 'Thomas',     'Lewis',      '1985-08-25', 'M'),
    23: (14, 'Nancy',      'Walker',     '1942-04-07', 'F'),
    24: (15, 'Daniel',     'Hall',       '1957-12-19', 'M'),
}

# Synthetic patients (raf_patient_id 25-30)
synthetic_patients = {
    25: ('George',    'Robinson',  '1936-02-11', 'M'),
    26: ('Helen',     'Young',     '1952-07-03', 'F'),
    27: ('Kenneth',   'King',      '1969-11-28', 'M'),
    28: ('Dorothy',   'Wright',    '1945-06-14', 'F'),
    29: ('Steven',    'Scott',     '1988-03-17', 'M'),
    30: ('Karen',     'Green',     '1931-09-25', 'F'),
}

# ============================================================
# STEP 1: Insert emr_patient_matches for local + synthetic
# ============================================================
print("\nInserting emr_patient_matches...")

# Local OpenEMR patients
for raf_id, (pid, fn, ln, dob, sex) in local_patients.items():
    cur.execute("""
        INSERT INTO emr_patient_matches
        (connection_id, external_id, emr_pid, match_score, match_method, status, first_name, last_name, date_of_birth, sex, mrn, match_status, raf_patient_id)
        VALUES (7, %s, %s, 1.0, 'openemr_local', 'matched', %s, %s, %s, %s, %s, 'auto', %s)
    """, (f'local-pid-{pid}', pid, fn, ln, dob, sex, f'MRN-{1000+pid}', raf_id))

# Synthetic patients
for raf_id, (fn, ln, dob, sex) in synthetic_patients.items():
    cur.execute("""
        INSERT INTO emr_patient_matches
        (connection_id, external_id, emr_pid, match_score, match_method, status, first_name, last_name, date_of_birth, sex, mrn, match_status, raf_patient_id)
        VALUES (7, %s, 0, 1.0, 'manual_import', 'matched', %s, %s, %s, %s, %s, 'manual', %s)
    """, (f'synthetic-{raf_id}', fn, ln, dob, sex, f'MRN-{2000+raf_id}', raf_id))

conn.commit()
print(f"  Inserted 21 patient matches (15 local + 6 synthetic)")

# ============================================================
# STEP 2: Build all 30 patients info and demographics
# ============================================================
# Combine all patient info: raf_id -> (first, last, dob_str, sex)
all_patients = {}
for rid, (fn, ln, dob, sex) in fhir_patients.items():
    all_patients[rid] = (fn, ln, dob, sex)
for rid, (pid, fn, ln, dob, sex) in local_patients.items():
    all_patients[rid] = (fn, ln, dob, sex)
for rid, (fn, ln, dob, sex) in synthetic_patients.items():
    all_patients[rid] = (fn, ln, dob, sex)

def get_age_band(dob_str):
    dob = datetime.strptime(dob_str, '%Y-%m-%d').date()
    age = 2026 - dob.year - (1 if (1, 1) < (dob.month, dob.day) else 0)
    # approximate - good enough
    age = 2026 - dob.year
    if age < 35: return '0-34'
    if age < 45: return '35-44'
    if age < 55: return '45-54'
    if age < 60: return '55-59'
    if age < 65: return '60-64'
    if age < 70: return '65-69'
    if age < 75: return '70-74'
    if age < 80: return '75-79'
    if age < 85: return '80-84'
    if age < 90: return '85-89'
    if age < 95: return '90-94'
    return '95+'

# Load demographic coefficients
cur.execute('SELECT age_band, sex, coefficient FROM hcc_demographic_coefficients WHERE model_segment="CNA"')
demo_coeffs = {}
for ab, sx, coeff in cur.fetchall():
    demo_coeffs[(ab, sx)] = float(coeff)

print("\nInserting raf_patient_demographics...")
patient_demo = {}  # raf_id -> (age_band, sex, demo_score)
for rid in sorted(all_patients.keys()):
    fn, ln, dob, sex = all_patients[rid]
    ab = get_age_band(dob)
    ds = demo_coeffs.get((ab, sex), 0.3)
    patient_demo[rid] = (ab, sex, ds)

    # Some patients dual/disabled for variety
    dual = 1 if rid in [1, 6, 16, 19, 23, 25, 30] else 0
    disabled = 1 if rid in [6, 16, 28] else 0

    cur.execute("""
        INSERT INTO raf_patient_demographics (patient_id, measurement_year, age_band, sex, dual_status, disabled, model_segment)
        VALUES (%s, 2026, %s, %s, %s, %s, 'CNA')
    """, (rid, ab, sex, dual, disabled))

conn.commit()
print(f"  Inserted 30 demographics")

# ============================================================
# STEP 3: HCC mappings
# ============================================================
# ICD-10 -> (HCC, coefficient)
hcc_map = {
    'E11.9':   (37,  0.1053),
    'J44.1':   (112, 0.3350),
    'F33.0':   (155, 0.3090),
    'I50.9':   (85,  0.3680),
    'I48.91':  (96,  0.2660),
    'N18.4':   (137, 0.2710),
    'N18.3':   (141, 0.0690),
    'E66.01':  (48,  0.1161),
    'I63.9':   (100, 0.2630),
    'I73.9':   (108, 0.2380),
    'F20.9':   (57,  0.3410),
    'G20':     (78,  0.5780),
    'B20':     (1,   0.3543),
    'C34.90':  (12,  0.2714),
    'K74.60':  (29,  0.3712),
    'M06.9':   (40,  0.3614),
    'F03.90':  (52,  0.2660),
    'G40.909': (79,  0.1640),
}

icd_list = list(hcc_map.keys())

# Patient HCC assignments - carefully designed for realism
# Elderly/sick patients get more conditions, young get fewer
patient_hccs = {
    # FHIR patients (1-9)
    1:  ['I50.9', 'I48.91', 'E11.9', 'N18.3'],          # Dorothy 78F - CHF, AFib, diabetes, CKD3
    2:  ['G20', 'F03.90', 'I73.9', 'E11.9', 'J44.1'],   # Robert 82M - Parkinson's, dementia, PVD, diabetes, COPD
    3:  [],                                                # Patrick 17M - healthy teen
    4:  [],                                                # Terry 20F - healthy young adult
    5:  ['M06.9', 'E11.9', 'E66.01'],                    # Julia 75F - RA, diabetes, obesity
    6:  ['J44.1', 'I50.9', 'N18.4', 'I63.9', 'E11.9'],  # Ronald 83M - COPD, CHF, CKD4, stroke, diabetes
    7:  ['E11.9', 'F33.0'],                               # Maria 68F - diabetes, depression
    8:  ['I48.91', 'E11.9'],                              # James 61M - AFib, diabetes
    9:  ['F33.0'],                                         # Sarah 54F - depression only

    # Local OpenEMR patients (10-24)
    10: ['J44.1', 'E11.9', 'I48.91'],                    # William 71M - COPD, diabetes, AFib
    11: ['F03.90', 'I50.9', 'N18.4', 'G40.909', 'E11.9'], # Margaret 86F - dementia, CHF, CKD4, epilepsy, diabetes
    12: ['E11.9', 'I73.9'],                               # David 64M - diabetes, PVD
    13: ['E66.01'],                                        # Linda 51F - obesity
    14: ['K74.60', 'I50.9', 'E11.9', 'N18.3'],           # Richard 76M - cirrhosis, CHF, diabetes, CKD3
    15: ['F33.0', 'E66.01'],                              # Barbara 58F - depression, obesity
    16: ['G20', 'F03.90', 'I50.9', 'J44.1', 'N18.4'],   # Charles 88M - Parkinson's, dementia, CHF, COPD, CKD4
    17: ['I50.9', 'I48.91', 'E11.9'],                    # Patricia 79F - CHF, AFib, diabetes
    18: ['E11.9'],                                         # Michael 46M - diabetes only
    19: ['F03.90', 'I50.9', 'N18.4', 'I63.9', 'G40.909'], # Elizabeth 93F - dementia, CHF, CKD4, stroke, epilepsy
    20: ['E11.9', 'E66.01'],                              # Joseph 55M - diabetes, obesity
    21: ['M06.9', 'F33.0', 'E11.9'],                     # Susan 66F - RA, depression, diabetes
    22: [],                                                # Thomas 41M - healthy
    23: ['I50.9', 'I48.91', 'N18.3', 'E11.9'],           # Nancy 84F - CHF, AFib, CKD3, diabetes
    24: ['J44.1', 'E11.9', 'I73.9'],                     # Daniel 69M - COPD, diabetes, PVD

    # Synthetic patients (25-30)
    25: ['B20', 'F33.0', 'E11.9', 'N18.3'],              # George 90M - HIV, depression, diabetes, CKD3
    26: ['C34.90', 'J44.1', 'E11.9'],                    # Helen 74F - lung cancer, COPD, diabetes
    27: ['F20.9', 'E11.9'],                               # Kenneth 57M - schizophrenia, diabetes
    28: ['G20', 'F03.90', 'I50.9', 'I48.91'],            # Dorothy 81F - Parkinson's, dementia, CHF, AFib
    29: ['E66.01', 'F33.0'],                              # Steven 38M - obesity, depression
    30: ['F03.90', 'I50.9', 'N18.4', 'J44.1', 'I63.9'], # Karen 95F - dementia, CHF, CKD4, COPD, stroke
}

print("\nInserting raf_patient_hcc...")
total_hcc = 0
patient_disease_scores = {}
for rid in sorted(patient_hccs.keys()):
    codes = patient_hccs[rid]
    disease_total = 0.0
    for icd in codes:
        hcc, coeff = hcc_map[icd]
        cur.execute("""
            INSERT INTO raf_patient_hcc (patient_id, measurement_year, hcc_code, icd10_codes, source_encounter_ids, raf_coefficient, meat_status, is_trumped, trumped_by_hcc)
            VALUES (%s, 2026, %s, %s, '[]', %s, 'complete', 0, NULL)
        """, (rid, hcc, json.dumps([icd]), coeff))
        disease_total += coeff
        total_hcc += 1
    patient_disease_scores[rid] = round(disease_total, 4)

conn.commit()
print(f"  Inserted {total_hcc} HCC mappings")

# ============================================================
# STEP 4: RAF scores
# ============================================================
print("\nInserting raf_scores...")
for rid in sorted(all_patients.keys()):
    ab, sex, demo_score = patient_demo[rid]
    disease_score = patient_disease_scores.get(rid, 0.0)
    total_raw = round(demo_score + disease_score, 4)
    final_raf = total_raw  # normalization=1.0
    hcc_count = len(patient_hccs.get(rid, []))

    cur.execute("""
        INSERT INTO raf_scores (patient_id, measurement_year, score_type, model_segment, demographic_score, disease_score, interaction_score, total_raw, normalization_factor, final_raf, hcc_count)
        VALUES (%s, 2026, 'prospective', 'CNA', %s, %s, 0, %s, 1.0, %s, %s)
    """, (rid, demo_score, disease_score, total_raw, final_raf, hcc_count))

conn.commit()
print(f"  Inserted 30 RAF scores")

# ============================================================
# STEP 5: Suspect conditions
# ============================================================
print("\nInserting raf_suspect_conditions...")

suspects = [
    # (patient_id, icd10, hcc, evidence_type, confidence, hcc_coeff, rationale)
    (1,  'N18.4', 137, 'lab',        0.88, 0.2710, 'Creatinine 2.4 mg/dL and eGFR 28 suggest CKD stage 4, currently coded as stage 3 (N18.3). Recommend upgrading diagnosis.'),
    (2,  'E66.01', 48, 'lab',        0.72, 0.1161, 'BMI recorded at 41.2 in last encounter. No morbid obesity diagnosis coded.'),
    (5,  'J44.1',  112, 'medication', 0.81, 0.3350, 'Patient on tiotropium and albuterol inhalers. No COPD diagnosis coded in current year.'),
    (7,  'E66.01', 48, 'lab',        0.77, 0.1161, 'BMI 42.5 recorded. Patient on weight management program but no morbid obesity ICD-10 coded.'),
    (7,  'N18.3',  141, 'lab',       0.83, 0.0690, 'eGFR 48 mL/min on last two labs. No CKD diagnosis currently coded.'),
    (8,  'E11.9',  37,  'medication', 0.91, 0.1053, 'Patient on metformin 1000mg BID and glipizide. No diabetes mellitus diagnosis coded for 2026.'),
    (10, 'I50.9',  85,  'historical', 0.74, 0.3680, 'Heart failure diagnosed in 2024, on lisinopril and furosemide. Not recaptured in 2026.'),
    (12, 'J44.1',  112, 'medication', 0.69, 0.3350, 'Spiriva and ProAir prescribed. FEV1/FVC ratio 0.62 on last PFT. COPD not coded.'),
    (13, 'E11.9',  37,  'lab',       0.85, 0.1053, 'HbA1c 7.8% on last two readings. Patient on metformin but no diabetes diagnosis coded.'),
    (14, 'I48.91', 96,  'medication', 0.79, 0.2660, 'Patient on apixaban and metoprolol. Atrial fibrillation documented in cardiology notes but not coded.'),
    (17, 'N18.3',  141, 'lab',       0.87, 0.0690, 'Creatinine trending up (1.8, 2.0, 2.1). eGFR 42. CKD stage 3 not currently coded.'),
    (18, 'F33.0',  155, 'medication', 0.71, 0.3090, 'Patient on sertraline 100mg. PHQ-9 score 14 (moderate depression). No depression diagnosis coded.'),
    (20, 'I48.91', 96,  'referral',  0.66, 0.2660, 'Cardiology referral notes mention paroxysmal atrial fibrillation. Not coded by PCP.'),
    (21, 'N18.3',  141, 'lab',       0.82, 0.0690, 'eGFR 52 on consecutive labs. Metformin dose reduced due to renal function. CKD not coded.'),
    (22, 'E11.9',  37,  'lab',       0.90, 0.1053, 'HbA1c 8.1%, fasting glucose 180. Patient counseled on lifestyle changes. No diabetes ICD-10 coded.'),
    (24, 'I50.9',  85,  'historical', 0.76, 0.3680, 'CHF with EF 38% documented in 2024 echo. On carvedilol and lisinopril. Not recaptured for 2026.'),
    (26, 'N18.4',  137, 'lab',       0.84, 0.2710, 'eGFR 22, creatinine 3.1. Nephrology consult pending. No CKD stage 4 coded despite lab evidence.'),
    (27, 'E66.01', 48,  'lab',       0.73, 0.1161, 'BMI 43.8 on recent vitals. Morbid obesity not captured in problem list.'),
    (29, 'E11.9',  37,  'lab',       0.68, 0.1053, 'HbA1c 6.8%, borderline. Family history of T2DM. Pre-diabetes or diabetes may be appropriate.'),
    (30, 'G40.909',79,  'medication', 0.80, 0.1640, 'Patient on levetiracetam 500mg BID. Epilepsy documented in historical records but not coded in 2026.'),
]

for pid, icd, hcc, etype, conf, hcc_coeff, rationale in suspects:
    evidence = json.dumps({
        "source": etype,
        "description": rationale,
        "detected_at": "2026-04-01T00:00:00Z"
    })
    cur.execute("""
        INSERT INTO raf_suspect_conditions
        (patient_id, measurement_year, suspect_hcc, suspect_icd10, evidence_type, evidence_detail, confidence_score, status, hcc_coefficient, confidence, rationale)
        VALUES (%s, 2026, %s, %s, %s, %s, %s, 'open', %s, %s, %s)
    """, (pid, hcc, icd, etype, evidence, conf, hcc_coeff, conf, rationale))

conn.commit()
print(f"  Inserted {len(suspects)} suspect conditions")

# ============================================================
# VERIFICATION
# ============================================================
print("\n" + "="*60)
print("VERIFICATION")
print("="*60)

tables = [
    ('emr_patient_matches', 'SELECT COUNT(*) FROM emr_patient_matches WHERE raf_patient_id BETWEEN 1 AND 30'),
    ('raf_patient_demographics', 'SELECT COUNT(*) FROM raf_patient_demographics'),
    ('raf_patient_hcc', 'SELECT COUNT(*) FROM raf_patient_hcc'),
    ('raf_scores', 'SELECT COUNT(*) FROM raf_scores'),
    ('raf_suspect_conditions', 'SELECT COUNT(*) FROM raf_suspect_conditions'),
]
for name, q in tables:
    cur.execute(q)
    print(f"  {name}: {cur.fetchone()[0]} rows")

# Show RAF score distribution
print("\nRAF Score Distribution:")
cur.execute("""
    SELECT rs.patient_id, epm.first_name, epm.last_name, rpd.age_band, rpd.sex,
           rs.demographic_score, rs.disease_score, rs.final_raf, rs.hcc_count
    FROM raf_scores rs
    JOIN raf_patient_demographics rpd ON rs.patient_id = rpd.patient_id
    LEFT JOIN emr_patient_matches epm ON epm.raf_patient_id = rs.patient_id
    WHERE rs.measurement_year = 2026 AND rpd.measurement_year = 2026
    GROUP BY rs.patient_id
    ORDER BY rs.final_raf DESC
""")
print(f"  {'ID':>3} {'Name':<25} {'Age':>5} {'S':>1} {'Demo':>6} {'Dis':>6} {'RAF':>6} {'HCC':>3}")
print(f"  {'---':>3} {'----':<25} {'---':>5} {'-':>1} {'----':>6} {'---':>6} {'---':>6} {'---':>3}")
for row in cur.fetchall():
    pid, fn, ln, ab, sex, demo, dis, raf, hcc = row
    name = f"{fn} {ln}"[:25] if fn else f"Patient {pid}"
    print(f"  {pid:>3} {name:<25} {ab:>5} {sex:>1} {float(demo):>6.4f} {float(dis):>6.4f} {float(raf):>6.4f} {hcc:>3}")

conn.close()
print("\nDone! All demo data seeded successfully.")
