"""
Seed RAF Intelligence demo data — idempotent.

Called at startup from main.py lifespan.  Checks if data already exists
before inserting so it is safe to run on every restart.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime

logger = logging.getLogger(__name__)


def seed_raf_demo() -> None:
    """Populate the RAF Intelligence database with 15-patient demo dataset (matching OpenEMR)."""
    from app.db import raf_cursor

    # Check if already seeded
    try:
        with raf_cursor() as cur:
            cur.execute("SELECT COUNT(*) AS cnt FROM raf_patient_demographics WHERE patient_id BETWEEN 1 AND 15")
            if cur.fetchone()["cnt"] >= 15:
                logger.info("RAF demo data already seeded (15 patients) — skipping.")
                return
    except Exception as exc:
        logger.warning("Cannot check RAF demo data: %s", exc)
        return

    logger.info("Seeding RAF Intelligence demo data (15 patients matching OpenEMR) …")

    # ------------------------------------------------------------------
    # Patient definitions
    # ------------------------------------------------------------------
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

    synthetic_patients = {
        25: ('George',    'Robinson',  '1936-02-11', 'M'),
        26: ('Helen',     'Young',     '1952-07-03', 'F'),
        27: ('Kenneth',   'King',      '1969-11-28', 'M'),
        28: ('Dorothy',   'Wright',    '1945-06-14', 'F'),
        29: ('Steven',    'Scott',     '1988-03-17', 'M'),
        30: ('Karen',     'Green',     '1931-09-25', 'F'),
    }

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _age_band(dob_str: str) -> str:
        age = 2026 - int(dob_str[:4])
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

    # Combine all patients
    all_patients = {}
    for rid, (fn, ln, dob, sex) in fhir_patients.items():
        all_patients[rid] = (fn, ln, dob, sex)
    for rid, (pid, fn, ln, dob, sex) in local_patients.items():
        all_patients[rid] = (fn, ln, dob, sex)
    for rid, (fn, ln, dob, sex) in synthetic_patients.items():
        all_patients[rid] = (fn, ln, dob, sex)

    # HCC mapping
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

    patient_hccs = {
        1:  ['I50.9', 'I48.91', 'E11.9', 'N18.3'],
        2:  ['G20', 'F03.90', 'I73.9', 'E11.9', 'J44.1'],
        3:  [], 4: [],
        5:  ['M06.9', 'E11.9', 'E66.01'],
        6:  ['J44.1', 'I50.9', 'N18.4', 'I63.9', 'E11.9'],
        7:  ['E11.9', 'F33.0'], 8: ['I48.91', 'E11.9'], 9: ['F33.0'],
        10: ['J44.1', 'E11.9', 'I48.91'],
        11: ['F03.90', 'I50.9', 'N18.4', 'G40.909', 'E11.9'],
        12: ['E11.9', 'I73.9'], 13: ['E66.01'],
        14: ['K74.60', 'I50.9', 'E11.9', 'N18.3'],
        15: ['F33.0', 'E66.01'],
        16: ['G20', 'F03.90', 'I50.9', 'J44.1', 'N18.4'],
        17: ['I50.9', 'I48.91', 'E11.9'],
        18: ['E11.9'],
        19: ['F03.90', 'I50.9', 'N18.4', 'I63.9', 'G40.909'],
        20: ['E11.9', 'E66.01'],
        21: ['M06.9', 'F33.0', 'E11.9'],
        22: [],
        23: ['I50.9', 'I48.91', 'N18.3', 'E11.9'],
        24: ['J44.1', 'E11.9', 'I73.9'],
        25: ['B20', 'F33.0', 'E11.9', 'N18.3'],
        26: ['C34.90', 'J44.1', 'E11.9'],
        27: ['F20.9', 'E11.9'],
        28: ['G20', 'F03.90', 'I50.9', 'I48.91'],
        29: ['E66.01', 'F33.0'],
        30: ['F03.90', 'I50.9', 'N18.4', 'J44.1', 'I63.9'],
    }

    suspects = [
        (1,  'N18.4', 137, 'lab',        0.88, 0.2710, 'Creatinine 2.4 mg/dL and eGFR 28 suggest CKD stage 4, currently coded as stage 3.'),
        (2,  'E66.01', 48, 'lab',        0.72, 0.1161, 'BMI recorded at 41.2. No morbid obesity diagnosis coded.'),
        (5,  'J44.1',  112, 'medication', 0.81, 0.3350, 'Patient on tiotropium and albuterol. No COPD diagnosis coded.'),
        (7,  'E66.01', 48, 'lab',        0.77, 0.1161, 'BMI 42.5. No morbid obesity ICD-10 coded.'),
        (7,  'N18.3',  141, 'lab',       0.83, 0.0690, 'eGFR 48 mL/min on last two labs. No CKD diagnosis coded.'),
        (8,  'E11.9',  37,  'medication', 0.91, 0.1053, 'On metformin 1000mg BID and glipizide. No diabetes coded for 2026.'),
        (10, 'I50.9',  85,  'historical', 0.74, 0.3680, 'Heart failure diagnosed in 2024. Not recaptured in 2026.'),
        (12, 'J44.1',  112, 'medication', 0.69, 0.3350, 'Spiriva and ProAir prescribed. FEV1/FVC 0.62. COPD not coded.'),
        (13, 'E11.9',  37,  'lab',       0.85, 0.1053, 'HbA1c 7.8%. On metformin but no diabetes coded.'),
        (14, 'I48.91', 96,  'medication', 0.79, 0.2660, 'On apixaban and metoprolol. AFib in cardiology notes not coded.'),
        (17, 'N18.3',  141, 'lab',       0.87, 0.0690, 'Creatinine trending up. eGFR 42. CKD stage 3 not coded.'),
        (18, 'F33.0',  155, 'medication', 0.71, 0.3090, 'On sertraline. PHQ-9 score 14. No depression coded.'),
        (20, 'I48.91', 96,  'referral',  0.66, 0.2660, 'Cardiology referral mentions paroxysmal AFib. Not coded by PCP.'),
        (21, 'N18.3',  141, 'lab',       0.82, 0.0690, 'eGFR 52 on consecutive labs. CKD not coded.'),
        (22, 'E11.9',  37,  'lab',       0.90, 0.1053, 'HbA1c 8.1%, fasting glucose 180. No diabetes ICD-10 coded.'),
        (24, 'I50.9',  85,  'historical', 0.76, 0.3680, 'CHF with EF 38% in 2024 echo. Not recaptured for 2026.'),
        (26, 'N18.4',  137, 'lab',       0.84, 0.2710, 'eGFR 22, creatinine 3.1. No CKD stage 4 coded.'),
        (27, 'E66.01', 48,  'lab',       0.73, 0.1161, 'BMI 43.8. Morbid obesity not in problem list.'),
        (29, 'E11.9',  37,  'lab',       0.68, 0.1053, 'HbA1c 6.8%, borderline. Pre-diabetes or diabetes may be appropriate.'),
        (30, 'G40.909',79,  'medication', 0.80, 0.1640, 'On levetiracetam. Epilepsy not coded in 2026.'),
    ]

    # ------------------------------------------------------------------
    # Execute
    # ------------------------------------------------------------------
    try:
        # Load demographic coefficients
        demo_coeffs = {}
        with raf_cursor() as cur:
            cur.execute('SELECT age_band, sex, coefficient FROM hcc_demographic_coefficients WHERE model_segment="CNA"')
            for row in cur.fetchall():
                demo_coeffs[(row["age_band"], row["sex"])] = float(row["coefficient"])

        # Step 1: emr_patient_matches for local + synthetic
        with raf_cursor() as cur:
            for raf_id, (pid, fn, ln, dob, sex) in local_patients.items():
                cur.execute("SELECT id FROM emr_patient_matches WHERE raf_patient_id=%s LIMIT 1", (raf_id,))
                if not cur.fetchone():
                    cur.execute(
                        "INSERT INTO emr_patient_matches "
                        "(connection_id, external_id, emr_pid, match_score, match_method, status, "
                        "first_name, last_name, date_of_birth, sex, mrn, match_status, raf_patient_id) "
                        "VALUES (7, %s, %s, 1.0, 'openemr_local', 'matched', %s, %s, %s, %s, %s, 'auto', %s)",
                        (f'local-pid-{pid}', pid, fn, ln, dob, sex, f'MRN-{1000+pid}', raf_id),
                    )

            for raf_id, (fn, ln, dob, sex) in synthetic_patients.items():
                cur.execute("SELECT id FROM emr_patient_matches WHERE raf_patient_id=%s LIMIT 1", (raf_id,))
                if not cur.fetchone():
                    cur.execute(
                        "INSERT INTO emr_patient_matches "
                        "(connection_id, external_id, emr_pid, match_score, match_method, status, "
                        "first_name, last_name, date_of_birth, sex, mrn, match_status, raf_patient_id) "
                        "VALUES (7, %s, 0, 1.0, 'manual_import', 'matched', %s, %s, %s, %s, %s, 'manual', %s)",
                        (f'synthetic-{raf_id}', fn, ln, dob, sex, f'MRN-{2000+raf_id}', raf_id),
                    )

        # Step 2: Demographics
        patient_demo = {}
        with raf_cursor() as cur:
            for rid in sorted(all_patients.keys()):
                fn, ln, dob, sex = all_patients[rid]
                ab = _age_band(dob)
                ds = demo_coeffs.get((ab, sex), 0.3)
                patient_demo[rid] = (ab, sex, ds)
                dual = 1 if rid in [1, 6, 16, 19, 23, 25, 30] else 0
                disabled = 1 if rid in [6, 16, 28] else 0

                cur.execute("SELECT patient_id FROM raf_patient_demographics WHERE patient_id=%s AND measurement_year=2026 LIMIT 1", (rid,))
                if not cur.fetchone():
                    cur.execute(
                        "INSERT INTO raf_patient_demographics (patient_id, measurement_year, age_band, sex, dual_status, disabled, model_segment) "
                        "VALUES (%s, 2026, %s, %s, %s, %s, 'CNA')",
                        (rid, ab, sex, dual, disabled),
                    )

        # Step 3: HCC mappings
        patient_disease_scores = {}
        with raf_cursor() as cur:
            for rid in sorted(patient_hccs.keys()):
                codes = patient_hccs[rid]
                disease_total = 0.0
                for icd in codes:
                    hcc, coeff = hcc_map[icd]
                    cur.execute(
                        "SELECT id FROM raf_patient_hcc WHERE patient_id=%s AND hcc_code=%s AND measurement_year=2026 LIMIT 1",
                        (rid, hcc),
                    )
                    if not cur.fetchone():
                        cur.execute(
                            "INSERT INTO raf_patient_hcc (patient_id, measurement_year, hcc_code, icd10_codes, source_encounter_ids, raf_coefficient, meat_status, is_trumped, trumped_by_hcc, model_version) "
                            "VALUES (%s, 2026, %s, %s, '[]', %s, 'complete', 0, NULL, 'V28')",
                            (rid, hcc, json.dumps([icd]), coeff),
                        )
                    disease_total += coeff
                patient_disease_scores[rid] = round(disease_total, 4)

        # Step 4: RAF scores
        with raf_cursor() as cur:
            for rid in sorted(all_patients.keys()):
                ab, sex, demo_score = patient_demo[rid]
                disease_score = patient_disease_scores.get(rid, 0.0)
                total_raw = round(demo_score + disease_score, 4)
                hcc_count = len(patient_hccs.get(rid, []))

                cur.execute("SELECT patient_id FROM raf_scores WHERE patient_id=%s AND measurement_year=2026 AND score_type='prospective' LIMIT 1", (rid,))
                if not cur.fetchone():
                    cur.execute(
                        "INSERT INTO raf_scores (patient_id, measurement_year, score_type, model_segment, "
                        "demographic_score, disease_score, interaction_score, total_raw, normalization_factor, final_raf, hcc_count) "
                        "VALUES (%s, 2026, 'prospective', 'CNA', %s, %s, 0, %s, 1.0, %s, %s)",
                        (rid, demo_score, disease_score, total_raw, total_raw, hcc_count),
                    )

        # Step 5: Suspect conditions
        with raf_cursor() as cur:
            for pid, icd, hcc, etype, conf, hcc_coeff, rationale in suspects:
                cur.execute(
                    "SELECT id FROM raf_suspect_conditions WHERE patient_id=%s AND suspect_icd10=%s AND measurement_year=2026 LIMIT 1",
                    (pid, icd),
                )
                if not cur.fetchone():
                    evidence = json.dumps({
                        "source": etype,
                        "description": rationale,
                        "detected_at": "2026-04-01T00:00:00Z",
                    })
                    cur.execute(
                        "INSERT INTO raf_suspect_conditions "
                        "(patient_id, measurement_year, suspect_hcc, suspect_icd10, evidence_type, evidence_detail, "
                        "confidence_score, status, hcc_coefficient, confidence, rationale) "
                        "VALUES (%s, 2026, %s, %s, %s, %s, %s, 'open', %s, %s, %s)",
                        (pid, hcc, icd, etype, evidence, conf, hcc_coeff, conf, rationale),
                    )

        # Step 6: Enable sync on FHIR connection
        with raf_cursor() as cur:
            cur.execute("UPDATE emr_connections SET sync_enabled = 1 WHERE id = 7 AND sync_enabled = 0")

        # Step 7: Delete HCC code 0 rows (bad data cleanup)
        with raf_cursor() as cur:
            cur.execute("DELETE FROM raf_patient_hcc WHERE hcc_code = 0")

        # Step 8: Fix duplicate ICD-10 arrays in raf_patient_hcc
        with raf_cursor() as cur:
            cur.execute("SELECT id, icd10_codes FROM raf_patient_hcc WHERE icd10_codes IS NOT NULL")
            for row in cur.fetchall():
                try:
                    codes = json.loads(row["icd10_codes"])
                    if isinstance(codes, list) and len(codes) != len(set(codes)):
                        deduped = json.dumps(list(dict.fromkeys(codes)))
                        cur.execute("UPDATE raf_patient_hcc SET icd10_codes=%s WHERE id=%s", (deduped, row["id"]))
                except (json.JSONDecodeError, TypeError):
                    pass

        # Step 9: Set MEAT status to 'complete' for demo patients
        with raf_cursor() as cur:
            for pid in [1, 5, 6, 14, 16, 19]:
                cur.execute(
                    "UPDATE raf_patient_hcc SET meat_status='complete' "
                    "WHERE patient_id=%s AND measurement_year=2026 AND meat_status != 'complete'",
                    (pid,),
                )

        # Step 10: Seed HCC hierarchy rules
        _HIERARCHY_RULES = [
            (18, 17), (19, 17), (19, 18),
            (86, 85), (87, 85), (87, 86), (88, 85), (88, 86), (88, 87),
            (112, 111),
            (137, 136), (138, 136), (138, 137), (139, 136), (139, 137), (139, 138),
            (140, 136), (140, 137), (140, 138), (140, 139),
            (141, 136), (141, 137), (141, 138), (141, 139), (141, 140),
            (107, 106), (108, 106), (108, 107),
            (12, 11), (13, 11), (13, 12),
            (28, 27), (29, 27), (29, 28), (30, 27), (30, 28), (30, 29),
            (58, 57), (59, 57), (59, 58), (60, 57), (60, 58), (60, 59),
            (156, 155),
            (100, 99), (101, 99), (101, 100),
            (52, 51),
        ]
        with raf_cursor() as cur:
            for hcc_code, trumped_by in _HIERARCHY_RULES:
                cur.execute(
                    "SELECT id FROM hcc_hierarchy_rules WHERE hcc_code=%s AND trumped_by_hcc=%s LIMIT 1",
                    (hcc_code, trumped_by),
                )
                if not cur.fetchone():
                    cur.execute(
                        "INSERT INTO hcc_hierarchy_rules (hcc_code, trumped_by_hcc, model_year) "
                        "VALUES (%s, %s, 2024)",
                        (hcc_code, trumped_by),
                    )

        # Step 11: Seed HCC interaction terms
        _INTERACTION_TERMS = [
            ('DM_CHF',  [47, 85],  'CNA', 0.1210),
            ('DM_CHF',  [47, 85],  'CFA', 0.1210),
            ('DM_CKD',  [47, 137], 'CNA', 0.0580),
            ('DM_CKD',  [47, 137], 'CFA', 0.0580),
            ('CHF_CKD', [85, 137], 'CNA', 0.0780),
            ('CHF_CKD', [85, 137], 'CFA', 0.0780),
            ('CHF_COPD',[85, 111], 'CNA', 0.0650),
            ('CHF_COPD',[85, 111], 'CFA', 0.0650),
            ('DM_VASC', [47, 108], 'CNA', 0.0960),
            ('DM_VASC', [47, 108], 'CFA', 0.0960),
        ]
        with raf_cursor() as cur:
            for term_name, hcc_codes, segment, coeff in _INTERACTION_TERMS:
                codes_json = json.dumps(hcc_codes)
                cur.execute(
                    "SELECT id FROM hcc_interaction_terms WHERE term_name=%s AND model_segment=%s LIMIT 1",
                    (term_name, segment),
                )
                if not cur.fetchone():
                    cur.execute(
                        "INSERT INTO hcc_interaction_terms (term_name, hcc_codes_required, model_segment, coefficient, model_year) "
                        "VALUES (%s, %s, %s, %s, 2024)",
                        (term_name, codes_json, segment, coeff),
                    )

        logger.info("RAF demo data seeded: 30 patients, HCC mappings, RAF scores, 20 suspects, hierarchy rules, interaction terms.")

    except Exception as exc:
        logger.error("Failed to seed RAF demo data: %s", exc)
