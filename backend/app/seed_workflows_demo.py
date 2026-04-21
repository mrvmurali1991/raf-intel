"""
Seed workflow demo data — care gap tasks, coder worklist, AWV schedules,
AWV visit results, and AWV outreach logs.

Idempotent: checks care_gap_tasks >= 30 before inserting.
Called at startup from main.py lifespan.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def seed_workflows_demo() -> None:
    """Populate workflow tables with demo data."""
    from app.db import raf_cursor

    # ── idempotency guard ────────────────────────────────────────────
    try:
        with raf_cursor() as cur:
            cur.execute("SELECT COUNT(*) AS cnt FROM care_gap_tasks")
            if cur.fetchone()["cnt"] >= 30:
                logger.info("Workflow demo data already seeded — skipping.")
                return
    except Exception as exc:
        logger.warning("Cannot check workflow demo data: %s", exc)
        return

    logger.info("Seeding workflow demo data …")

    # ==================================================================
    # care_gap_tasks  (30 rows)
    # ==================================================================
    care_gap_rows = [
        # (patient_id, provider_id, hcc_code, hcc_description, gap_type, priority, status, assigned_to, evidence_summary, due_date, suspect_condition_id)
        (1, 1, "HCC137", "CKD Stage 4", "suspect", "critical", "open", 1,
         "Creatinine 2.4 mg/dL, eGFR 28. Currently coded as CKD stage 3. Labs suggest stage 4.",
         "2026-04-15", 1),
        (2, 2, "HCC48", "Morbid Obesity", "suspect", "medium", "open", 2,
         "BMI 41.2 recorded. No morbid obesity diagnosis coded.",
         "2026-05-01", 2),
        (5, 3, "HCC112", "COPD", "suspect", "high", "in_progress", 3,
         "On tiotropium and albuterol. No COPD coded. Spirometry needed.",
         "2026-04-20", 3),
        (7, 4, "HCC48", "Morbid Obesity", "suspect", "low", "open", 4,
         "BMI 42.5, on weight management program. Morbid obesity not coded.",
         "2026-05-15", 4),
        (7, 4, "HCC141", "CKD Stage 3", "suspect", "high", "open", 4,
         "eGFR 48 on last two labs. No CKD diagnosis coded.",
         "2026-04-22", 5),
        (8, 1, "HCC37", "Diabetes Mellitus", "suspect", "critical", "in_progress", 1,
         "On metformin 1000mg BID and glipizide. No DM diagnosis coded. HbA1c pending.",
         "2026-04-12", 6),
        (12, 2, "HCC112", "COPD", "suspect", "medium", "open", 2,
         "Spiriva and ProAir prescribed. FEV1/FVC 0.62. COPD not coded.",
         "2026-05-10", 8),
        (13, 3, "HCC37", "Diabetes Mellitus", "suspect", "high", "scheduled", 3,
         "HbA1c 7.8% on two readings. On metformin without DM diagnosis.",
         "2026-04-25", 9),
        (14, 5, "HCC96", "Atrial Fibrillation", "suspect", "high", "open", 5,
         "On apixaban and metoprolol. AFib in cardiology notes, not coded by PCP.",
         "2026-04-18", 10),
        (17, 6, "HCC141", "CKD Stage 3", "suspect", "high", "open", 6,
         "Creatinine trending up (1.8-2.1). eGFR 42. CKD not coded.",
         "2026-04-28", 11),
        (18, 1, "HCC155", "Major Depression", "suspect", "medium", "open", 1,
         "On sertraline 100mg. PHQ-9 score 14. No depression diagnosis.",
         "2026-05-20", 12),
        (20, 2, "HCC96", "Atrial Fibrillation", "suspect", "medium", "completed", 2,
         "Cardiology referral mentions paroxysmal AFib. Not coded by PCP.",
         "2026-04-10", 13),
        (21, 3, "HCC141", "CKD Stage 3", "suspect", "medium", "open", 3,
         "eGFR 52 on consecutive labs. Metformin dose reduced. CKD not coded.",
         "2026-05-05", 14),
        (22, 4, "HCC37", "Diabetes Mellitus", "suspect", "critical", "in_progress", 4,
         "HbA1c 8.1%, fasting glucose 180. No DM coded despite counseling.",
         "2026-04-14", 15),
        (26, 5, "HCC137", "CKD Stage 4", "suspect", "critical", "open", 5,
         "eGFR 22, creatinine 3.1. Nephrology consult pending. No CKD stage 4 coded.",
         "2026-04-11", 17),
        (27, 6, "HCC48", "Morbid Obesity", "suspect", "low", "open", 6,
         "BMI 43.8. Morbid obesity not in problem list.",
         "2026-06-01", 18),
        (29, 1, "HCC37", "Diabetes Mellitus", "suspect", "low", "rejected", 1,
         "HbA1c 6.8% borderline. May be pre-diabetes rather than diabetes.",
         "2026-05-30", 19),
        (30, 2, "HCC79", "Epilepsy", "suspect", "high", "open", 2,
         "On levetiracetam 500mg BID. Epilepsy in historical records, not current problem list.",
         "2026-04-30", 20),
        (10, 3, "HCC85", "Heart Failure", "recapture", "critical", "in_progress", 3,
         "HF diagnosed 2024, on lisinopril/furosemide. Not recaptured in 2026 claims.",
         "2026-04-13", 7),
        (24, 5, "HCC85", "Heart Failure", "recapture", "high", "scheduled", 5,
         "CHF with EF 38% (2024 echo). On carvedilol/lisinopril. Not recaptured in 2026.",
         "2026-04-20", 16),
        (1, 1, "HCC18", "Diabetes with Chronic Complications", "new", "high", "open", 1,
         "Retinopathy noted in ophthalmology report. May indicate diabetic complications.",
         "2026-05-08", None),
        (5, 3, "HCC111", "Chronic Obstructive Asthma", "recapture", "medium", "completed", 3,
         "Asthma with COPD overlap documented in 2024. Needs recapture.",
         "2026-04-05", None),
        (8, 1, "HCC18", "Diabetes with Chronic Complications", "new", "medium", "completed", 1,
         "Peripheral neuropathy on EMG. Likely diabetic complication.",
         "2026-04-03", None),
        (13, 3, "HCC18", "Diabetes with Chronic Complications", "new", "low", "rejected", 3,
         "Mild tingling reported but EMG normal. Insufficient evidence.",
         "2026-05-25", None),
        (14, 5, "HCC108", "Vascular Disease", "suspect", "medium", "completed", 5,
         "Peripheral vascular disease noted on duplex ultrasound.",
         "2026-04-08", None),
        (17, 6, "HCC85", "Heart Failure", "new", "high", "scheduled", 6,
         "New echo shows EF 40%. BNP elevated. Possible new HF diagnosis.",
         "2026-04-22", None),
        (22, 4, "HCC18", "Diabetes with Chronic Complications", "new", "medium", "open", 4,
         "Microalbuminuria detected. Diabetic nephropathy suspected.",
         "2026-05-12", None),
        (26, 5, "HCC134", "ESRD", "new", "low", "open", 5,
         "eGFR declining rapidly. Monitor for progression to ESRD.",
         "2026-06-15", None),
        (30, 2, "HCC80", "Seizure Disorders", "recapture", "medium", "completed", 2,
         "Seizure disorder from 2024 records. Recaptured with current encounter.",
         "2026-04-06", None),
        (2, 2, "HCC22", "Type 1 Diabetes with Complications", "suspect", "low", "open", 2,
         "C-peptide low. May be Type 1 rather than Type 2. Further workup needed.",
         "2026-06-10", None),
    ]

    try:
        with raf_cursor() as cur:
            # ── care_gap_tasks ───────────────────────────────────────
            for r in care_gap_rows:
                cur.execute(
                    """INSERT INTO care_gap_tasks
                       (patient_id, provider_id, hcc_code, hcc_description,
                        gap_type, priority, status, assigned_to,
                        evidence_summary, due_date, suspect_condition_id)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                    r,
                )
            logger.info("Inserted %d care_gap_tasks rows.", len(care_gap_rows))

            # ── coder_worklist (18 rows) ─────────────────────────────
            coder_rows = [
                # (coder_user_id, patient_id, encounter_id, review_type, source, priority, status, hcc_codes, due_date)
                (1, 1,  101, "suspect_review",       "ai_engine",       1, "queued",      '["HCC137", "HCC18"]',        "2026-04-15"),
                (2, 5,  105, "suspect_review",       "ai_engine",       2, "queued",      '["HCC112"]',                 "2026-04-20"),
                (1, 8,  108, "suspect_review",       "provider_query",  1, "queued",      '["HCC37"]',                  "2026-04-12"),
                (3, 17, 117, "suspect_review",       "ai_engine",       2, "queued",      '["HCC141", "HCC85"]',        "2026-04-28"),
                (2, 26, 126, "suspect_review",       "ai_engine",       1, "queued",      '["HCC137"]',                 "2026-04-11"),
                (4, 22, 122, "documentation_review", "chart_review",    2, "queued",      '["HCC37", "HCC18"]',         "2026-04-25"),
                (3, 27, 127, "new_hcc_review",       "claims_analysis", 3, "queued",      '["HCC48"]',                  "2026-05-01"),
                (4, 2,  102, "new_hcc_review",       "chart_review",    3, "queued",      '["HCC48", "HCC22"]',         "2026-05-10"),
                (1, 10, 110, "recapture_review",     "ai_engine",       1, "in_progress", '["HCC85"]',                  "2026-04-13"),
                (2, 24, 124, "recapture_review",     "ai_engine",       1, "in_progress", '["HCC85"]',                  "2026-04-20"),
                (3, 14, 114, "suspect_review",       "provider_query",  2, "in_progress", '["HCC96"]',                  "2026-04-18"),
                (4, 13, 113, "documentation_review", "chart_review",    2, "in_progress", '["HCC37"]',                  "2026-04-25"),
                (1, 20, 120, "suspect_review",       "ai_engine",       2, "completed",   '["HCC96"]',                  "2026-04-10"),
                (2, 5,  105, "recapture_review",     "claims_analysis", 3, "completed",   '["HCC111"]',                 "2026-04-05"),
                (3, 8,  108, "new_hcc_review",       "chart_review",    2, "completed",   '["HCC18"]',                  "2026-04-03"),
                (1, 14, 114, "suspect_review",       "provider_query",  3, "completed",   '["HCC108"]',                 "2026-04-08"),
                (4, 30, 130, "recapture_review",     "ai_engine",       3, "completed",   '["HCC80"]',                  "2026-04-06"),
                (2, 7,  107, "documentation_review", "provider_query",  1, "escalated",   '["HCC48", "HCC141"]',        "2026-04-15"),
            ]
            for r in coder_rows:
                cur.execute(
                    """INSERT INTO coder_worklist
                       (coder_user_id, patient_id, encounter_id, review_type,
                        source, priority, status, hcc_codes, due_date)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                    r,
                )
            logger.info("Inserted %d coder_worklist rows.", len(coder_rows))

            # ── awv_schedules (18 rows) ──────────────────────────────
            awv_rows = [
                # (patient_id, schedule_year, provider_npi, status, visit_type, eligibility_date, scheduled_date, completed_date, location, outreach_attempts, hcc_gaps_to_review, estimated_raf_impact)
                (1,  2026, "1234567890", "completed",        "initial",    "2026-01-01", "2026-01-15 09:00:00", "2026-01-15", "Main Clinic - Room 3",  2, '["HCC18", "HCC85", "HCC108"]',                        0.35),
                (2,  2026, "1234567892", "completed",        "subsequent", "2026-01-01", "2026-01-22 10:30:00", "2026-01-22", "Main Clinic - Room 1",  1, '["HCC19", "HCC85", "HCC96"]',                         0.42),
                (5,  2026, "1234567890", "completed",        "subsequent", "2026-01-01", "2026-02-05 14:00:00", "2026-02-05", "Main Clinic - Room 2",  1, '["HCC18", "HCC111"]',                                 0.21),
                (11, 2026, "1234567895", "completed",        "subsequent", "2026-01-01", "2026-02-12 09:30:00", "2026-02-12", "Senior Care Center",    3, '["HCC12", "HCC18", "HCC85", "HCC96", "HCC108"]',      0.48),
                (14, 2026, "1234567890", "completed",        "subsequent", "2026-01-01", "2026-02-26 11:00:00", "2026-02-26", "Main Clinic - Room 3",  2, '["HCC19", "HCC85"]',                                  0.18),
                (19, 2026, "1234567892", "completed",        "subsequent", "2026-01-01", "2026-03-05 10:00:00", "2026-03-05", "Senior Care Center",    2, '["HCC12", "HCC18", "HCC85", "HCC108", "HCC111"]',     0.45),
                (25, 2026, "1234567895", "completed",        "subsequent", "2026-01-01", "2026-03-18 13:00:00", "2026-03-18", "Main Clinic - Room 1",  1, '["HCC12", "HCC19", "HCC85"]',                         0.32),
                (6,  2026, "1234567890", "scheduled",        "subsequent", "2026-01-01", "2026-04-10 09:00:00", None,         "Main Clinic - Room 2",  2, '["HCC19", "HCC85", "HCC96"]',                         0.38),
                (10, 2026, "1234567895", "scheduled",        "subsequent", "2026-01-01", "2026-04-22 10:00:00", None,         "Senior Care Center",    3, '["HCC18", "HCC85", "HCC108"]',                        0.28),
                (17, 2026, "1234567890", "scheduled",        "subsequent", "2026-01-01", "2026-05-01 11:30:00", None,         "Main Clinic - Room 3",  2, '["HCC12", "HCC85", "HCC111"]',                        0.31),
                (26, 2026, "1234567892", "scheduled",        "subsequent", "2026-01-01", "2026-05-08 09:00:00", None,         "Main Clinic - Room 2",  1, '["HCC18", "HCC96"]',                                  0.22),
                (28, 2026, "1234567895", "scheduled",        "subsequent", "2026-01-01", "2026-05-15 14:00:00", None,         "Senior Care Center",    2, '["HCC12", "HCC19", "HCC85", "HCC108"]',               0.41),
                (16, 2026, None,         "eligible",         "subsequent", "2026-01-01", None,                  None,         None,                    0, '["HCC12", "HCC18", "HCC85", "HCC96"]',                0.40),
                (23, 2026, None,         "eligible",         "subsequent", "2026-01-01", None,                  None,         None,                    0, '["HCC85", "HCC96"]',                                  0.25),
                (24, 2026, None,         "eligible",         "initial",    "2026-01-01", None,                  None,         None,                    0, '["HCC19", "HCC85"]',                                  0.16),
                (30, 2026, None,         "eligible",         "subsequent", "2026-01-01", None,                  None,         None,                    0, '["HCC12", "HCC18", "HCC85", "HCC108", "HCC111"]',     0.50),
                (7,  2026, None,         "outreach_pending", "initial",    "2026-01-01", None,                  None,         None,                    2, '["HCC18", "HCC19"]',                                  0.15),
                (21, 2026, None,         "outreach_pending", "initial",    "2026-01-01", None,                  None,         None,                    3, '["HCC18", "HCC19"]',                                  0.12),
            ]
            for r in awv_rows:
                cur.execute(
                    """INSERT INTO awv_schedules
                       (patient_id, schedule_year, provider_npi, status,
                        visit_type, eligibility_date, scheduled_date,
                        completed_date, location, outreach_attempts,
                        hcc_gaps_to_review, estimated_raf_impact)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                    r,
                )
            logger.info("Inserted %d awv_schedules rows.", len(awv_rows))

            # ── awv_visit_results (7 rows) ───────────────────────────
            # We need the auto-generated awv_schedule IDs for the 7 completed rows.
            # Fetch them in insertion order (the first 7 awv_rows are the completed ones).
            cur.execute(
                """SELECT id FROM awv_schedules
                   WHERE status = 'completed'
                   ORDER BY id DESC LIMIT 7"""
            )
            completed_ids = sorted(row["id"] for row in cur.fetchall())

            visit_results = [
                # (awv_id, conditions_reviewed, conditions_confirmed, new_conditions_identified, hcc_codes_captured, raf_score_before, raf_score_after, notes)
                (completed_ids[0], 5, 4, 1, '["HCC18", "HCC85", "HCC108"]',
                 1.25, 1.60,
                 "Diabetes with complications confirmed. New peripheral vascular disease identified. BP stable on current medications. Osteoporosis management reviewed."),
                (completed_ids[1], 7, 5, 2, '["HCC19", "HCC85", "HCC96", "HCC111"]',
                 1.82, 2.24,
                 "COPD exacerbation history reviewed. CHF stable on current regimen. New diagnosis of chronic kidney disease stage 3 documented. Polyneuropathy confirmed."),
                (completed_ids[2], 4, 3, 0, '["HCC18", "HCC111"]',
                 0.95, 1.16,
                 "Diabetes management reviewed - A1C at 7.2%. Polyneuropathy symptoms stable. No new conditions identified this visit."),
                (completed_ids[3], 8, 6, 3, '["HCC12", "HCC18", "HCC85", "HCC96", "HCC108"]',
                 2.10, 2.58,
                 "Complex patient with multiple comorbidities. Breast cancer history confirmed with oncology records. Diabetes, CHF, and vascular disease all active. New macular degeneration documented. Cognitive decline noted - referral placed."),
                (completed_ids[4], 3, 2, 1, '["HCC19", "HCC85"]',
                 1.10, 1.28,
                 "COPD confirmed via recent PFTs. CHF compensated. New atrial fibrillation identified on ECG, anticoagulation started."),
                (completed_ids[5], 6, 5, 2, '["HCC12", "HCC18", "HCC85", "HCC108", "HCC111"]',
                 2.35, 2.80,
                 "Extensive review with caregiver input. Cancer remission confirmed. Diabetes insulin-dependent. CHF with reduced EF. New pressure ulcer stage 2 documented. Polyneuropathy worsening."),
                (completed_ids[6], 5, 4, 1, '["HCC12", "HCC19", "HCC85"]',
                 1.68, 2.00,
                 "Prostate cancer surveillance ongoing. COPD with home oxygen confirmed. CHF stable. New depression diagnosis - PHQ-9 score of 14, SSRI initiated."),
            ]
            for r in visit_results:
                cur.execute(
                    """INSERT INTO awv_visit_results
                       (awv_id, conditions_reviewed, conditions_confirmed,
                        new_conditions_identified, hcc_codes_captured,
                        raf_score_before, raf_score_after, notes)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
                    r,
                )
            logger.info("Inserted %d awv_visit_results rows.", len(visit_results))

            # ── awv_outreach_log (15 rows) ───────────────────────────
            # Map: scheduled AWV IDs are the next 5 after completed (indexes 7-11 in awv_rows)
            # and outreach_pending are the last 2 (indexes 16-17).
            cur.execute(
                """SELECT id, status FROM awv_schedules
                   WHERE status IN ('scheduled', 'outreach_pending')
                   ORDER BY id DESC LIMIT 7"""
            )
            status_rows = {row["id"]: row["status"] for row in cur.fetchall()}
            scheduled_ids = sorted(k for k, v in status_rows.items() if v == "scheduled")
            outreach_ids = sorted(k for k, v in status_rows.items() if v == "outreach_pending")

            # scheduled_ids[0..4] map to patients 6,10,17,26,28
            # outreach_ids[0..1] map to patients 7,21
            outreach_rows = [
                # (awv_id, method, outcome, contact_date, contacted_by, notes)
                (scheduled_ids[0], "phone",          "scheduled",  "2026-03-25 10:15:00", 1, "Reached patient, scheduled for April 10"),
                (scheduled_ids[0], "phone",          "no_answer",  "2026-03-20 14:00:00", 1, "No answer, left voicemail"),
                (scheduled_ids[1], "phone",          "scheduled",  "2026-04-01 09:30:00", 2, "Patient confirmed April 22 appointment"),
                (scheduled_ids[1], "letter",         "sent",       "2026-03-15 08:00:00", 2, "Mailed AWV invitation letter"),
                (scheduled_ids[1], "phone",          "no_answer",  "2026-03-28 11:00:00", 2, "No answer on first call attempt"),
                (scheduled_ids[2], "phone",          "scheduled",  "2026-03-30 15:00:00", 1, "Rescheduled from March to May 1"),
                (scheduled_ids[2], "portal_message", "sent",       "2026-03-22 10:00:00", 1, "Sent patient portal message about AWV eligibility"),
                (scheduled_ids[3], "phone",          "scheduled",  "2026-04-04 13:45:00", 3, "Patient requested morning time slot on May 8"),
                (scheduled_ids[4], "phone",          "scheduled",  "2026-04-02 10:30:00", 3, "Spoke with daughter, arranged May 15 visit"),
                (scheduled_ids[4], "letter",         "sent",       "2026-03-20 08:00:00", 3, "Initial outreach letter mailed"),
                (outreach_ids[0],  "phone",          "no_answer",  "2026-04-03 09:00:00", 1, "Second voicemail left, requested callback"),
                (outreach_ids[0],  "phone",          "no_answer",  "2026-03-28 14:30:00", 1, "No answer, first attempt"),
                (outreach_ids[1],  "letter",         "sent",       "2026-03-28 08:00:00", 2, "AWV invitation letter mailed"),
                (outreach_ids[1],  "phone",          "no_answer",  "2026-04-01 11:00:00", 2, "No answer after letter sent"),
                (outreach_ids[1],  "portal_message", "sent",       "2026-03-20 09:00:00", 2, "Initial portal message about AWV scheduling"),
            ]
            for r in outreach_rows:
                cur.execute(
                    """INSERT INTO awv_outreach_log
                       (awv_id, method, outcome, contact_date,
                        contacted_by, notes)
                       VALUES (%s,%s,%s,%s,%s,%s)""",
                    r,
                )
            logger.info("Inserted %d awv_outreach_log rows.", len(outreach_rows))

        logger.info("Workflow demo data seeding complete.")

    except Exception as exc:
        logger.error("Failed to seed workflow demo data: %s", exc)
        raise
