"""
Idempotent seed script for claims data, cohorts, cohort members,
cohort snapshots, and dashboard alerts.

Skips seeding if claims_records already has >= 35 rows.

Usage:
    python -m app.seed_claims_cohorts_demo
"""

import json
import pymysql
import os
import sys

DB_CONFIG = {
    # Prefer RAF_DB_* (used by the FastAPI pool and docker-compose .env) and
    # fall back to DB_* for backward-compat with older local environments.
    "host": os.getenv("RAF_DB_HOST") or os.getenv("DB_HOST", "127.0.0.1"),
    "port": int(os.getenv("RAF_DB_PORT") or os.getenv("DB_PORT", 3306)),
    "user": os.getenv("RAF_DB_USER") or os.getenv("DB_USER", "root"),
    "password": os.getenv("RAF_DB_PASSWORD") or os.getenv("DB_PASSWORD", "root"),
    "database": os.getenv("RAF_DB_NAME") or os.getenv("DB_NAME", "raf_intelligence"),
    "charset": "utf8mb4",
}

# ---------------------------------------------------------------------------
# Data definitions
# ---------------------------------------------------------------------------

CLAIMS_BATCH = {
    "id": 1,
    "tenant_id": "default",
    "batch_name": "Medicare_Claims_Q1_2026",
    "file_type": "CSV",
    "file_name": "medicare_claims_q1_2026.csv",
    "total_claims": 35,
    "processed_claims": 35,
    "failed_claims": 0,
    "status": "completed",
    "error_message": None,
    "uploaded_by": "admin@rafiq.health",
    "claim_count": 35,
    "matched_patient_count": 18,
    "hcc_codes_found": 42,
    "batch_uuid": "409e8688-318e-11f1-ab52-f916824cf5e6",
    "filename": "medicare_claims_q1_2026.csv",
    "file_format": "CSV",
    "file_size": 245000,
    "unique_patient_count": 18,
    "unique_provider_count": 6,
    "total_charges": 10800.00,
}

CLAIMS_RECORDS = [
    (1, 1, "CLM-2026-0001", "Dorothy Wright", "1945-06-14", "F", "MBI-DW-1028", "1234567890", "Dr. Sarah Mitchell", "2025-09-15", "I48.91,I50.9,F03.90", "99215", 350.00, "Medicare Part B", "11", "professional"),
    (2, 1, "CLM-2026-0002", "Dorothy Wright", "1945-06-14", "F", "MBI-DW-1028", "1234567893", "Dr. Michael Torres", "2025-12-10", "G20,F03.90", "99214", 275.00, "Medicare Part B", "11", "professional"),
    (3, 1, "CLM-2026-0003", "Dorothy Wright", "1945-06-14", "F", "MBI-DW-1028", "1234567890", "Dr. Sarah Mitchell", "2026-03-05", "I48.91,I50.9,G20,F03.90", "99215", 350.00, "Medicare Advantage", "11", "professional"),
    (4, 1, "CLM-2026-0004", "Robert James Williams", "1944-07-15", "M", "MBI-RW-1002", "1234567891", "Dr. James Patel", "2025-08-20", "E11.65,I50.9,J44.1", "99215", 375.00, "Medicare Part B", "11", "professional"),
    (5, 1, "CLM-2026-0005", "Robert James Williams", "1944-07-15", "M", "MBI-RW-1002", "1234567891", "Dr. James Patel", "2026-01-15", "E11.65,I50.9,J44.1,N18.3", "99387", 450.00, "Medicare Part B", "11", "professional"),
    (6, 1, "CLM-2026-0006", "Charles Moore", "1938-03-27", "M", "MBI-CM-1016", "1234567892", "Dr. Lisa Wong", "2025-07-12", "G20,N18.4,J44.1", "99214", 280.00, "Medicare Advantage", "11", "professional"),
    (7, 1, "CLM-2026-0007", "Charles Moore", "1938-03-27", "M", "MBI-CM-1016", "1234567890", "Dr. Sarah Mitchell", "2025-11-18", "I50.9,F03.90,G20", "99215", 350.00, "Medicare Part B", "11", "professional"),
    (8, 1, "CLM-2026-0008", "Charles Moore", "1938-03-27", "M", "MBI-CM-1016", "1234567892", "Dr. Lisa Wong", "2026-02-20", "G20,N18.4,J44.1,I50.9,F03.90", "99215", 375.00, "Medicare Part B", "21", "institutional"),
    (9, 1, "CLM-2026-0009", "Ronald Abeyta", "1943-09-16", "M", "MBI-RA-1006", "1234567893", "Dr. Michael Torres", "2025-10-05", "G30.9", "99215", 325.00, "Medicare Part B", "11", "professional"),
    (10, 1, "CLM-2026-0010", "Ronald Abeyta", "1943-09-16", "M", "MBI-RA-1006", "1234567893", "Dr. Michael Torres", "2026-01-22", "G30.9", "99214", 275.00, "Medicare Advantage", "11", "professional"),
    (11, 1, "CLM-2026-0011", "Karen Green", "1931-09-25", "F", "MBI-KG-1030", "1234567890", "Dr. Sarah Mitchell", "2025-06-18", "F03.90,I50.9,J44.1", "99214", 280.00, "Medicare Part B", "11", "professional"),
    (12, 1, "CLM-2026-0012", "Karen Green", "1931-09-25", "F", "MBI-KG-1030", "1234567894", "Dr. Amy Nguyen", "2025-10-30", "I63.9,N18.4", "99215", 350.00, "Medicare Part B", "21", "institutional"),
    (13, 1, "CLM-2026-0013", "Karen Green", "1931-09-25", "F", "MBI-KG-1030", "1234567890", "Dr. Sarah Mitchell", "2026-02-14", "F03.90,I50.9,J44.1,I63.9,N18.4", "99387", 475.00, "Medicare Advantage", "11", "professional"),
    (14, 1, "CLM-2026-0014", "Elizabeth White", "1933-05-20", "F", "MBI-EW-1019", "1234567891", "Dr. James Patel", "2025-08-08", "F03.90,I50.9,G40.909", "99214", 295.00, "Medicare Part B", "11", "professional"),
    (15, 1, "CLM-2026-0015", "Elizabeth White", "1933-05-20", "F", "MBI-EW-1019", "1234567894", "Dr. Amy Nguyen", "2026-01-10", "N18.4,I63.9,I50.9", "99215", 350.00, "Medicare Advantage", "11", "professional"),
    (16, 1, "CLM-2026-0016", "George Robinson", "1936-02-11", "M", "MBI-GR-1025", "1234567895", "Dr. Robert Kim", "2025-09-22", "B20,E11.9,N18.3", "99214", 290.00, "Medicare Part B", "11", "professional"),
    (17, 1, "CLM-2026-0017", "George Robinson", "1936-02-11", "M", "MBI-GR-1025", "1234567895", "Dr. Robert Kim", "2026-03-18", "B20,E11.9,F33.0,N18.3", "99215", 350.00, "Medicare Part B", "11", "professional"),
    (18, 1, "CLM-2026-0018", "Richard Lee", "1950-11-05", "M", "MBI-RL-1014", "1234567892", "Dr. Lisa Wong", "2025-07-30", "E11.9,N18.3,I50.9,K74.60", "99215", 360.00, "Medicare Part B", "11", "professional"),
    (19, 1, "CLM-2026-0019", "Nancy Walker", "1942-04-07", "F", "MBI-NW-1023", "1234567890", "Dr. Sarah Mitchell", "2025-11-05", "N18.3,I50.9,I48.91,E11.9", "99214", 285.00, "Medicare Part B", "11", "professional"),
    (20, 1, "CLM-2026-0020", "Nancy Walker", "1942-04-07", "F", "MBI-NW-1023", "1234567890", "Dr. Sarah Mitchell", "2026-03-12", "I50.9,I48.91,E11.9", "99387", 450.00, "Medicare Advantage", "11", "professional"),
    (21, 1, "CLM-2026-0021", "Dorothy Marie Johnson", "1948-01-15", "F", "MBI-DJ-1001", "1234567891", "Dr. James Patel", "2025-10-12", "E11.65,E11.9", "99213", 195.00, "Medicare Part B", "11", "professional"),
    (22, 1, "CLM-2026-0022", "Helen Young", "1952-07-03", "F", "MBI-HY-1026", "1234567894", "Dr. Amy Nguyen", "2025-08-15", "C34.90,E11.9,J44.1", "99215", 395.00, "Medicare Part B", "11", "professional"),
    (23, 1, "CLM-2026-0023", "Helen Young", "1952-07-03", "F", "MBI-HY-1026", "1234567894", "Dr. Amy Nguyen", "2026-02-28", "C34.90,J44.1", "99214", 275.00, "Medicare Advantage", "21", "institutional"),
    (24, 1, "CLM-2026-0024", "William Anderson", "1955-04-12", "M", "MBI-WA-1010", "1234567892", "Dr. Lisa Wong", "2025-09-02", "J44.1,I48.91,E11.9", "99214", 270.00, "Medicare Part B", "11", "professional"),
    (25, 1, "CLM-2026-0025", "Susan Clark", "1960-10-31", "F", "MBI-SC-1021", "1234567893", "Dr. Michael Torres", "2025-12-01", "E11.9,M06.9,F33.0", "99214", 265.00, "Medicare Part B", "11", "professional"),
    (26, 1, "CLM-2026-0026", "Susan Clark", "1960-10-31", "F", "MBI-SC-1021", "1234567893", "Dr. Michael Torres", "2026-03-25", "M06.9,F33.0", "99213", 195.00, "Medicare Advantage", "11", "professional"),
    (27, 1, "CLM-2026-0027", "Patricia Davis", "1947-12-01", "F", "MBI-PD-1017", "1234567891", "Dr. James Patel", "2025-07-22", "I48.91,E11.9,I50.9", "99215", 340.00, "Medicare Part B", "11", "professional"),
    (28, 1, "CLM-2026-0028", "Patricia Davis", "1947-12-01", "F", "MBI-PD-1017", "1234567891", "Dr. James Patel", "2026-01-30", "I48.91,I50.9", "99214", 280.00, "Medicare Part B", "11", "professional"),
    (29, 1, "CLM-2026-0029", "Barbara Wilson", "1968-09-14", "F", "MBI-BW-1015", "1234567895", "Dr. Robert Kim", "2025-11-15", "E66.01,F33.0", "99213", 185.00, "Medicare Advantage", "11", "professional"),
    (30, 1, "CLM-2026-0030", "James Thompson", "1965-11-22", "M", "MBI-JT-1008", "1234567892", "Dr. Lisa Wong", "2025-08-28", "F33.0,J44.1,I50.9,I48.0", "99215", 395.00, "Medicare Part B", "21", "institutional"),
    (31, 1, "CLM-2026-0031", "James Thompson", "1965-11-22", "M", "MBI-JT-1008", "1234567892", "Dr. Lisa Wong", "2026-02-05", "J44.1,I50.9", "99214", 275.00, "Medicare Part B", "11", "professional"),
    (32, 1, "CLM-2026-0032", "David Martinez", "1962-01-30", "M", "MBI-DM-1012", "1234567895", "Dr. Robert Kim", "2025-10-18", "I73.9,E11.9", "99213", 195.00, "Medicare Part B", "11", "professional"),
    (33, 1, "CLM-2026-0033", "Julia Jackson Synagog", "1951-10-18", "F", "MBI-JJ-1005", "1234567893", "Dr. Michael Torres", "2026-01-08", "E11.9", "99213", 175.00, "Medicare Advantage", "11", "professional"),
    (34, 1, "CLM-2026-0034", "Daniel Hall", "1957-12-19", "M", "MBI-DH-1024", "1234567894", "Dr. Amy Nguyen", "2025-09-10", "J44.1,E11.9,I73.9", "99214", 285.00, "Medicare Part B", "11", "professional"),
    (35, 1, "CLM-2026-0035", "Sarah Chen", "1972-03-08", "F", "MBI-SC-1009", "1234567890", "Dr. Sarah Mitchell", "2025-12-20", "E03.9,F41.9", "99213", 185.00, "Medicare Part B", "11", "professional"),
]

# (batch_id, claim_id, icd10_code, hcc_code, hcc_mapped)
# hcc_code is None for unmapped codes
CLAIMS_DIAGNOSES = [
    (1, 1, "I48.91", "96", 1),
    (1, 1, "I50.9", "85", 1),
    (1, 1, "F03.90", "52", 1),
    (1, 2, "G20", "78", 1),
    (1, 2, "F03.90", "52", 1),
    (1, 3, "I48.91", "96", 1),
    (1, 3, "I50.9", "85", 1),
    (1, 3, "G20", "78", 1),
    (1, 3, "F03.90", "52", 1),
    (1, 4, "E11.65", "18", 1),
    (1, 4, "I50.9", "85", 1),
    (1, 4, "J44.1", "112", 1),
    (1, 5, "E11.65", "18", 1),
    (1, 5, "I50.9", "85", 1),
    (1, 5, "J44.1", "112", 1),
    (1, 5, "N18.3", "141", 1),
    (1, 6, "G20", "78", 1),
    (1, 6, "N18.4", "137", 1),
    (1, 6, "J44.1", "112", 1),
    (1, 7, "I50.9", "85", 1),
    (1, 7, "F03.90", "52", 1),
    (1, 7, "G20", "78", 1),
    (1, 8, "G20", "78", 1),
    (1, 8, "N18.4", "137", 1),
    (1, 8, "J44.1", "112", 1),
    (1, 8, "I50.9", "85", 1),
    (1, 8, "F03.90", "52", 1),
    (1, 9, "G30.9", "127", 1),
    (1, 10, "G30.9", "127", 1),
    (1, 11, "F03.90", "52", 1),
    (1, 11, "I50.9", "85", 1),
    (1, 11, "J44.1", "112", 1),
    (1, 12, "I63.9", "100", 1),
    (1, 12, "N18.4", "137", 1),
    (1, 13, "F03.90", "52", 1),
    (1, 13, "I50.9", "85", 1),
    (1, 13, "J44.1", "112", 1),
    (1, 13, "I63.9", "100", 1),
    (1, 13, "N18.4", "137", 1),
    (1, 14, "F03.90", "52", 1),
    (1, 14, "I50.9", "85", 1),
    (1, 14, "G40.909", "79", 1),
    (1, 15, "N18.4", "137", 1),
    (1, 15, "I63.9", "100", 1),
    (1, 15, "I50.9", "85", 1),
    (1, 16, "B20", "1", 1),
    (1, 16, "E11.9", "37", 1),
    (1, 16, "N18.3", "141", 1),
    (1, 17, "B20", "1", 1),
    (1, 17, "E11.9", "37", 1),
    (1, 17, "F33.0", "155", 1),
    (1, 17, "N18.3", "141", 1),
    (1, 18, "E11.9", "37", 1),
    (1, 18, "N18.3", "141", 1),
    (1, 18, "I50.9", "85", 1),
    (1, 18, "K74.60", "29", 1),
    (1, 19, "N18.3", "141", 1),
    (1, 19, "I50.9", "85", 1),
    (1, 19, "I48.91", "96", 1),
    (1, 19, "E11.9", "37", 1),
    (1, 20, "I50.9", "85", 1),
    (1, 20, "I48.91", "96", 1),
    (1, 20, "E11.9", "37", 1),
    (1, 21, "E11.65", "18", 1),
    (1, 21, "E11.9", "37", 1),
    (1, 22, "C34.90", "12", 1),
    (1, 22, "E11.9", "37", 1),
    (1, 22, "J44.1", "112", 1),
    (1, 23, "C34.90", "12", 1),
    (1, 23, "J44.1", "112", 1),
    (1, 24, "J44.1", "112", 1),
    (1, 24, "I48.91", "96", 1),
    (1, 24, "E11.9", "37", 1),
    (1, 25, "E11.9", "37", 1),
    (1, 25, "M06.9", "40", 1),
    (1, 25, "F33.0", "155", 1),
    (1, 26, "M06.9", "40", 1),
    (1, 26, "F33.0", "155", 1),
    (1, 27, "I48.91", "96", 1),
    (1, 27, "E11.9", "37", 1),
    (1, 27, "I50.9", "85", 1),
    (1, 28, "I48.91", "96", 1),
    (1, 28, "I50.9", "85", 1),
    (1, 29, "E66.01", "48", 1),
    (1, 29, "F33.0", "155", 1),
    (1, 30, "F33.0", "155", 1),
    (1, 30, "J44.1", "112", 1),
    (1, 30, "I50.9", "85", 1),
    (1, 30, "I48.0", "96", 1),
    (1, 31, "J44.1", "112", 1),
    (1, 31, "I50.9", "85", 1),
    (1, 32, "I73.9", "108", 1),
    (1, 32, "E11.9", "37", 1),
    (1, 33, "E11.9", "37", 1),
    (1, 34, "J44.1", "112", 1),
    (1, 34, "E11.9", "37", 1),
    (1, 34, "I73.9", "108", 1),
    (1, 35, "E03.9", None, 0),
    (1, 35, "F41.9", None, 0),
]

COHORTS = [
    (1, "default", "High Risk (RAF > 2.0)", "Patients with prospective RAF score exceeding 2.0, requiring intensive care management and frequent follow-up.", "risk_tier", json.dumps({"min_raf": 2.0, "score_type": "prospective"}), 4, 2.2842, 40200.00, "active", 1),
    (2, "default", "Dual Eligible", "Medicare-Medicaid dual eligible patients who qualify for additional benefits and require coordinated care across programs.", "custom", json.dumps({"dual_status": 1}), 7, 1.6500, 28875.00, "active", 1),
    (3, "default", "Diabetes Management", "Patients with diabetes-related HCC codes (HCC 18, 19, 37) enrolled in the chronic disease management program.", "chronic_condition", json.dumps({"condition": "diabetes", "hcc_codes": [18, 19, 37]}), 13, 1.4200, 24885.00, "active", 1),
    (4, "default", "Heart Failure Program", "Patients with heart failure HCC codes (HCC 85, 86) requiring cardiology oversight and regular monitoring.", "chronic_condition", json.dumps({"condition": "heart_failure", "hcc_codes": [85, 86]}), 7, 1.7800, 31150.00, "active", 1),
    (5, "default", "AWV Due 2026", "Medicare-eligible patients who have not yet completed their Annual Wellness Visit for the 2026 measurement year.", "custom", json.dumps({"awv_status": "due", "measurement_year": 2026}), 10, 1.3500, 23625.00, "active", 1),
]

# (cohort_id, patient_id)
COHORT_MEMBERS = [
    (1, 6), (1, 16), (1, 2), (1, 28),
    (2, 1), (2, 6), (2, 16), (2, 19), (2, 23), (2, 25), (2, 30),
    (3, 7), (3, 10), (3, 12), (3, 14), (3, 17), (3, 18), (3, 20), (3, 21), (3, 23), (3, 24), (3, 25), (3, 26), (3, 27),
    (4, 14), (4, 16), (4, 17), (4, 19), (4, 23), (4, 28), (4, 30),
    (5, 3), (5, 4), (5, 5), (5, 8), (5, 9), (5, 11), (5, 13), (5, 15), (5, 22), (5, 29),
]

# (cohort_id, tenant_id, snapshot_date, patient_count, avg_raf_score, avg_age,
#  gender_distribution, top_hccs, risk_tier_distribution, total_revenue, metrics)
COHORT_SNAPSHOTS = [
    (1, "default", "2026-01-01", 3, 2.1800, 74.50, {"male": 2, "female": 1}, [{"hcc": 85, "count": 3}, {"hcc": 18, "count": 2}, {"hcc": 96, "count": 2}], {"very_high": 3}, 28350.00, {"avg_hcc_count": 4.7, "recapture_rate": 0.82}),
    (1, "default", "2026-02-01", 4, 2.2200, 75.10, {"male": 2, "female": 2}, [{"hcc": 85, "count": 3}, {"hcc": 18, "count": 3}, {"hcc": 96, "count": 2}], {"very_high": 4}, 35520.00, {"avg_hcc_count": 4.8, "recapture_rate": 0.85}),
    (1, "default", "2026-03-01", 4, 2.2842, 75.30, {"male": 2, "female": 2}, [{"hcc": 85, "count": 3}, {"hcc": 18, "count": 3}, {"hcc": 96, "count": 3}], {"very_high": 4}, 40200.00, {"avg_hcc_count": 5.0, "recapture_rate": 0.88}),
    (2, "default", "2026-01-01", 6, 1.5800, 71.20, {"male": 3, "female": 3}, [{"hcc": 37, "count": 4}, {"hcc": 85, "count": 3}, {"hcc": 19, "count": 2}], {"high": 4, "medium": 2}, 23700.00, {"dual_pct": 1.0, "avg_hcc_count": 3.2}),
    (2, "default", "2026-02-01", 7, 1.6100, 71.50, {"male": 3, "female": 4}, [{"hcc": 37, "count": 4}, {"hcc": 85, "count": 3}, {"hcc": 19, "count": 3}], {"high": 5, "medium": 2}, 26425.00, {"dual_pct": 1.0, "avg_hcc_count": 3.4}),
    (2, "default", "2026-03-01", 7, 1.6500, 71.80, {"male": 3, "female": 4}, [{"hcc": 37, "count": 5}, {"hcc": 85, "count": 3}, {"hcc": 19, "count": 3}], {"high": 5, "medium": 2}, 28875.00, {"dual_pct": 1.0, "avg_hcc_count": 3.5}),
    (3, "default", "2026-01-01", 11, 1.3500, 68.40, {"male": 6, "female": 5}, [{"hcc": 37, "count": 8}, {"hcc": 18, "count": 5}, {"hcc": 19, "count": 4}], {"low": 3, "high": 3, "medium": 5}, 18900.00, {"avg_hcc_count": 2.8, "a1c_controlled_pct": 0.62}),
    (3, "default", "2026-02-01", 12, 1.3800, 68.70, {"male": 6, "female": 6}, [{"hcc": 37, "count": 9}, {"hcc": 18, "count": 6}, {"hcc": 19, "count": 5}], {"low": 3, "high": 3, "medium": 6}, 21600.00, {"avg_hcc_count": 2.9, "a1c_controlled_pct": 0.65}),
    (3, "default", "2026-03-01", 13, 1.4200, 69.00, {"male": 7, "female": 6}, [{"hcc": 37, "count": 10}, {"hcc": 18, "count": 7}, {"hcc": 19, "count": 5}], {"low": 3, "high": 4, "medium": 6}, 24885.00, {"avg_hcc_count": 3.0, "a1c_controlled_pct": 0.68}),
    (4, "default", "2026-01-01", 6, 1.7000, 73.00, {"male": 4, "female": 2}, [{"hcc": 85, "count": 4}, {"hcc": 86, "count": 3}, {"hcc": 96, "count": 2}], {"high": 4, "medium": 2}, 25500.00, {"avg_hcc_count": 3.5, "readmission_rate": 0.18}),
    (4, "default", "2026-02-01", 7, 1.7400, 73.30, {"male": 4, "female": 3}, [{"hcc": 85, "count": 5}, {"hcc": 86, "count": 4}, {"hcc": 96, "count": 2}], {"high": 5, "medium": 2}, 28350.00, {"avg_hcc_count": 3.6, "readmission_rate": 0.15}),
    (4, "default", "2026-03-01", 7, 1.7800, 73.50, {"male": 4, "female": 3}, [{"hcc": 85, "count": 5}, {"hcc": 86, "count": 4}, {"hcc": 96, "count": 3}], {"high": 5, "medium": 2}, 31150.00, {"avg_hcc_count": 3.7, "readmission_rate": 0.12}),
    (5, "default", "2026-01-01", 15, 1.2000, 66.50, {"male": 8, "female": 7}, [{"hcc": 37, "count": 3}, {"hcc": 19, "count": 2}, {"hcc": 108, "count": 2}], {"low": 7, "medium": 8}, 22500.00, {"gap_count": 15, "awv_completion_pct": 0.45}),
    (5, "default", "2026-02-01", 12, 1.2800, 67.00, {"male": 6, "female": 6}, [{"hcc": 37, "count": 3}, {"hcc": 19, "count": 2}, {"hcc": 108, "count": 2}], {"low": 6, "medium": 6}, 23040.00, {"gap_count": 12, "awv_completion_pct": 0.58}),
    (5, "default", "2026-03-01", 10, 1.3500, 67.30, {"male": 5, "female": 5}, [{"hcc": 37, "count": 2}, {"hcc": 19, "count": 2}, {"hcc": 108, "count": 1}], {"low": 5, "medium": 5}, 23625.00, {"gap_count": 10, "awv_completion_pct": 0.65}),
]

# (alert_type, severity, title, message, patient_id, provider_npi, metadata, is_read, user_id, tenant_id)
DASHBOARD_ALERTS = [
    ("recapture", "high", "HCC Recapture Due", "3 patients have HCC codes from prior year that have not been recaptured in 2026. Immediate provider review recommended.", None, None, {"deadline": "2026-04-30", "hcc_codes": ["HCC 85", "HCC 18", "HCC 96"], "patient_ids": [6, 16, 28]}, 0, None, "default"),
    ("suspect", "medium", "New Suspect Condition Identified", "NLP analysis of recent clinical notes identified a potential undiagnosed condition for patient. Review recommended.", 19, None, {"source": "clinical_notes", "confidence": 0.87, "document_id": 42, "suspect_hcc": "HCC 111"}, 0, None, "default"),
    ("quality", "high", "AWV Completion Below Target", "Annual Wellness Visit completion rate is at 65%, which is below the 80% organizational target. 10 patients still pending.", None, None, {"cohort_id": 5, "target_rate": 0.8, "current_rate": 0.65, "patients_pending": 10}, 0, None, "default"),
    ("attestation", "medium", "Pending Provider Attestations", "Dr. Martinez has 5 HCC coding attestations pending review. These must be completed before the next submission deadline.", None, "1234567890", {"deadline": "2026-04-15", "pending_count": 5, "provider_name": "Dr. Martinez"}, 0, None, "default"),
    ("claims", "low", "Claims Batch Processed", "Claims batch #2026-Q1-047 has been processed successfully. 12 new HCC codes were mapped from submitted diagnosis codes.", None, None, {"batch_id": "2026-Q1-047", "total_claims": 87, "new_hcc_count": 12, "processing_time_sec": 14}, 1, None, "default"),
    ("raf_update", "low", "RAF Scores Updated After Document Analysis", "RAF scores increased for 8 patients following NLP-driven document analysis of uploaded clinical records.", None, None, {"analysis_date": "2026-03-28", "avg_raf_increase": 0.15, "patients_affected": 8, "documents_analyzed": 23}, 1, None, "default"),
    ("suspect", "critical", "CKD Stage 4 Upgrade Recommended", "Lab results and clinical documentation support upgrading CKD classification from Stage 3 to Stage 4 (HCC 138) for this patient. Significant RAF impact expected.", 1, None, {"evidence": "eGFR 22 mL/min, documented in nephrology note 2026-03-15", "raf_impact": 0.42, "current_hcc": "HCC 139", "recommended_hcc": "HCC 138"}, 0, None, "default"),
    ("compliance", "high", "RADV Audit Preparation Deadline", "Quarterly RADV audit preparation deadline is in 30 days. Ensure all supporting documentation is uploaded and attestations are complete.", None, None, {"deadline": "2026-05-06", "audit_type": "RADV", "completion_pct": 0.35, "records_to_review": 45}, 0, None, "default"),
    ("raf_update", "medium", "Significant RAF Drop Detected", "Patient RAF score decreased by 0.45 in latest recalculation. Verify if HCC codes were intentionally removed or if this is a data issue.", 2, None, {"current_raf": 2.27, "recalc_date": "2026-04-01", "dropped_hccs": ["HCC 96"], "previous_raf": 2.72}, 0, None, "default"),
    ("quality", "medium", "Star Rating Measure Gap", "HEDIS measure gap detected: 4 diabetic patients in the Diabetes Management cohort are overdue for retinal eye exam.", None, None, {"measure": "Diabetic Retinal Eye Exam", "cohort_id": 3, "gap_count": 4, "patient_ids": [10, 12, 20, 26]}, 0, None, "default"),
]


# ---------------------------------------------------------------------------
# Seed logic
# ---------------------------------------------------------------------------

def get_connection():
    return pymysql.connect(**DB_CONFIG)


def row_count(cur, table):
    cur.execute(f"SELECT COUNT(*) FROM {table}")
    return cur.fetchone()[0]


def seed():
    conn = get_connection()
    cur = conn.cursor()

    # ---- idempotency guard ----
    count = row_count(cur, "claims_records")
    if count >= 35:
        print(f"[seed] claims_records already has {count} rows -- skipping seed.")
        cur.close()
        conn.close()
        return

    print("[seed] Seeding claims, cohorts, cohort members, snapshots, and alerts ...")

    # -- claims_batches --
    cur.execute("SELECT COUNT(*) FROM claims_batches WHERE id = %s", (CLAIMS_BATCH["id"],))
    if cur.fetchone()[0] == 0:
        cols = ", ".join(CLAIMS_BATCH.keys())
        phs = ", ".join(["%s"] * len(CLAIMS_BATCH))
        cur.execute(f"INSERT INTO claims_batches ({cols}) VALUES ({phs})", list(CLAIMS_BATCH.values()))
        print(f"  [+] claims_batches: inserted batch id={CLAIMS_BATCH['id']}")
    else:
        print("  [=] claims_batches: batch already exists")

    # -- claims_records --
    for row in CLAIMS_RECORDS:
        rid = row[0]
        cur.execute("SELECT COUNT(*) FROM claims_records WHERE id = %s", (rid,))
        if cur.fetchone()[0] == 0:
            cur.execute(
                """INSERT INTO claims_records
                   (id, batch_id, source_claim_id, patient_name, patient_dob,
                    patient_gender, member_id, provider_npi, provider_name,
                    date_of_service, icd10_codes, cpt_codes, charges,
                    payer_name, place_of_service, claim_type)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                row,
            )
    print(f"  [+] claims_records: ensured {len(CLAIMS_RECORDS)} rows")

    # -- claims_diagnoses --
    for row in CLAIMS_DIAGNOSES:
        batch_id, claim_id, icd10, hcc, mapped = row
        cur.execute(
            "SELECT COUNT(*) FROM claims_diagnoses WHERE batch_id=%s AND claim_record_id=%s AND icd10_code=%s",
            (batch_id, claim_id, icd10),
        )
        if cur.fetchone()[0] == 0:
            cur.execute(
                """INSERT INTO claims_diagnoses
                   (batch_id, claim_record_id, icd10_code, hcc_code)
                   VALUES (%s,%s,%s,%s)""",
                row[:4],
            )
    print(f"  [+] claims_diagnoses: ensured {len(CLAIMS_DIAGNOSES)} rows")

    # -- cohorts --
    for row in COHORTS:
        cid = row[0]
        cur.execute("SELECT COUNT(*) FROM cohorts WHERE id = %s", (cid,))
        if cur.fetchone()[0] == 0:
            cur.execute(
                """INSERT INTO cohorts
                   (id, tenant_id, name, description, cohort_type, criteria,
                    patient_count, avg_raf_score, total_raf_revenue, status, created_by)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                row,
            )
    print(f"  [+] cohorts: ensured {len(COHORTS)} rows")

    # -- cohort_members --
    for cohort_id, patient_id in COHORT_MEMBERS:
        cur.execute(
            "SELECT COUNT(*) FROM cohort_members WHERE cohort_id=%s AND patient_id=%s",
            (cohort_id, patient_id),
        )
        if cur.fetchone()[0] == 0:
            cur.execute(
                "INSERT INTO cohort_members (cohort_id, patient_id, is_active) VALUES (%s,%s,1)",
                (cohort_id, patient_id),
            )
    print(f"  [+] cohort_members: ensured {len(COHORT_MEMBERS)} rows")

    # -- cohort_snapshots --
    for row in COHORT_SNAPSHOTS:
        cohort_id, tenant_id, snap_date = row[0], row[1], row[2]
        cur.execute(
            "SELECT COUNT(*) FROM cohort_snapshots WHERE cohort_id=%s AND tenant_id=%s AND snapshot_date=%s",
            (cohort_id, tenant_id, snap_date),
        )
        if cur.fetchone()[0] == 0:
            cur.execute(
                """INSERT INTO cohort_snapshots
                   (cohort_id, tenant_id, snapshot_date, patient_count, avg_raf_score,
                    avg_age, gender_distribution, top_hccs, risk_tier_distribution,
                    total_revenue, metrics)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (
                    row[0], row[1], row[2], row[3], row[4], row[5],
                    json.dumps(row[6]), json.dumps(row[7]),
                    json.dumps(row[8]), row[9], json.dumps(row[10]),
                ),
            )
    print(f"  [+] cohort_snapshots: ensured {len(COHORT_SNAPSHOTS)} rows")

    # -- dashboard_alerts --
    for row in DASHBOARD_ALERTS:
        alert_type, severity, title = row[0], row[1], row[2]
        cur.execute(
            "SELECT COUNT(*) FROM dashboard_alerts WHERE alert_type=%s AND title=%s AND tenant_id=%s",
            (alert_type, title, row[9]),
        )
        if cur.fetchone()[0] == 0:
            cur.execute(
                """INSERT INTO dashboard_alerts
                   (alert_type, severity, title, message, patient_id,
                    provider_npi, metadata, is_read, user_id, tenant_id)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (
                    row[0], row[1], row[2], row[3], row[4],
                    row[5], json.dumps(row[6]), row[7], row[8], row[9],
                ),
            )
    print(f"  [+] dashboard_alerts: ensured {len(DASHBOARD_ALERTS)} rows")

    conn.commit()
    cur.close()
    conn.close()
    print("[seed] Done.")


if __name__ == "__main__":
    seed()
