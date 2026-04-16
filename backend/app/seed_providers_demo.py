"""
Seed providers, scorecards, attestations, patient panels — idempotent.
Called at startup from main.py lifespan.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def seed_providers_demo() -> None:
    """Populate provider-related demo data (providers, scorecards, attestations, panels)."""
    from app.db import raf_cursor

    # Check if already seeded
    try:
        with raf_cursor() as cur:
            cur.execute("SELECT COUNT(*) AS cnt FROM providers")
            if cur.fetchone()["cnt"] >= 6:
                logger.info("Provider demo data already seeded — skipping.")
                return
    except Exception as exc:
        logger.warning("Cannot check providers: %s", exc)
        return

    logger.info("Seeding provider demo data …")
    try:
        with raf_cursor() as cur:
            # ----------------------------------------------------------
            # Providers
            # ----------------------------------------------------------
            providers = [
                ("default", "1234567890", "James", "Richardson", "MD", "Internal Medicine",
                 "pcp", "Meridian Primary Care", "j.richardson@meridianprimarycare.com",
                 "555-201-1001", "active", "Dr. James Richardson, MD", 1),
                ("default", "1234567891", "Emily", "Chen", "MD", "Endocrinology",
                 "specialist", "Metro Endocrine Associates", "e.chen@metroendocrine.com",
                 "555-201-1002", "active", "Dr. Emily Chen, MD", 1),
                ("default", "1234567892", "Robert", "Martinez", "DO", "Family Medicine",
                 "pcp", "Valley Family Health", "r.martinez@valleyfamily.com",
                 "555-201-1003", "active", "Dr. Robert Martinez, DO", 1),
                ("default", "1234567893", "Sarah", "Williams", "MD", "Cardiology",
                 "specialist", "HeartCare Cardiology Group", "s.williams@heartcaregroup.com",
                 "555-201-1004", "active", "Dr. Sarah Williams, MD", 1),
                ("default", "1234567894", "Michael", "Davis", "MD", "Pulmonology",
                 "specialist", "Breathe Well Pulmonary", "m.davis@breathewell.com",
                 "555-201-1005", "active", "Dr. Michael Davis, MD", 1),
                ("default", "1234567895", "Patricia", "Lee", "NP", "Geriatrics",
                 "pcp", "Senior Wellness Partners", "p.lee@seniorwellness.com",
                 "555-201-1006", "active", "Patricia Lee, NP", 1),
            ]
            for p in providers:
                cur.execute(
                    """INSERT INTO providers
                       (tenant_id, npi, first_name, last_name, credential, specialty,
                        specialty_category, practice_name, email, phone, status,
                        full_name, is_active)
                       SELECT %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s
                       FROM DUAL
                       WHERE NOT EXISTS (SELECT 1 FROM providers WHERE npi = %s)""",
                    (*p, p[1]),
                )

            # ----------------------------------------------------------
            # Resolve provider NPI -> actual DB id (AUTO_INCREMENT may not
            # yield 1..6 on re-seed / multi-tenant / prior rows).
            # ----------------------------------------------------------
            cur.execute(
                "SELECT id, npi FROM providers WHERE tenant_id = 'default' "
                "AND npi IN ('1234567890','1234567891','1234567892',"
                "'1234567893','1234567894','1234567895')"
            )
            npi_to_id = {row["npi"]: row["id"] for row in cur.fetchall()}
            # Ordered list of NPIs matching the providers list above (indexes 1..6)
            ordered_npis = [
                "1234567890", "1234567891", "1234567892",
                "1234567893", "1234567894", "1234567895",
            ]

            # ----------------------------------------------------------
            # Provider scorecard snapshots
            # Use logical index (1..6) into ordered_npis; resolve to real id.
            # ----------------------------------------------------------
            scorecards = [
                # (logical_idx, year, date, total_patients, patients_with_raf, ...)
                (1, 2026, "2026-04-01", 12, 10, 1.1240, 28, 35, 0.8000, 0.7200,
                 4, 22, 3, 4200.00, 3150.00, 0.8200, 0.8500, 72.00,
                 10, 4, 22, 3, 0.8200),
                (2, 2026, "2026-04-01", 6, 6, 1.3850, 18, 20, 0.9000, 0.8500,
                 1, 16, 1, 2800.00, 2450.00, 0.9100, 0.9200, 88.00,
                 6, 1, 16, 1, 0.9100),
                (3, 2026, "2026-04-01", 15, 13, 0.9560, 32, 42, 0.7619, 0.6800,
                 7, 25, 4, 4800.00, 3200.00, 0.7600, 0.7800, 58.00,
                 13, 7, 25, 4, 0.7600),
                (4, 2026, "2026-04-01", 8, 8, 1.5200, 24, 27, 0.8889, 0.8200,
                 2, 20, 2, 3500.00, 2975.00, 0.8800, 0.9000, 82.00,
                 8, 2, 20, 2, 0.8800),
                (5, 2026, "2026-04-01", 5, 5, 1.4100, 15, 17, 0.8824, 0.7900,
                 1, 13, 1, 2200.00, 1870.00, 0.8500, 0.8700, 78.00,
                 5, 1, 13, 1, 0.8500),
                (6, 2026, "2026-04-01", 10, 9, 1.2800, 26, 30, 0.8667, 0.8000,
                 3, 21, 2, 3800.00, 3040.00, 0.8400, 0.8600, 75.00,
                 9, 3, 21, 2, 0.8400),
            ]
            for s in scorecards:
                logical_idx = s[0]
                npi = ordered_npis[logical_idx - 1]
                real_pid = npi_to_id.get(npi)
                if real_pid is None:
                    logger.warning(
                        "Skipping scorecard for NPI %s — provider row missing.", npi
                    )
                    continue
                s_real = (real_pid,) + s[1:]
                try:
                    cur.execute(
                        """INSERT INTO provider_scorecard_snapshots
                           (provider_id, measurement_year, snapshot_date,
                            total_patients, patients_with_raf, average_raf,
                            total_hccs_captured, total_hccs_possible, hcc_capture_rate,
                            recapture_rate, suspect_conditions_open,
                            suspect_conditions_accepted, suspect_conditions_dismissed,
                            revenue_opportunity, revenue_captured,
                            avg_meat_completeness, documentation_quality_score,
                            percentile_rank, patients_with_scores,
                            suspects_open, suspects_accepted, suspects_dismissed,
                            meat_completeness_avg)
                           SELECT %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s
                           FROM DUAL
                           WHERE NOT EXISTS (
                               SELECT 1 FROM provider_scorecard_snapshots
                               WHERE provider_id = %s AND measurement_year = %s AND snapshot_date = %s
                           )""",
                        (*s_real, s_real[0], s_real[1], s_real[2]),
                    )
                except Exception as sc_exc:
                    logger.warning(
                        "Skipping scorecard (pid=%s, year=%s): %s",
                        real_pid, s_real[1], sc_exc,
                    )

            # ----------------------------------------------------------
            # Provider attestations
            # ----------------------------------------------------------
            attestations = [
                # (patient_id, encounter_id, hcc_code, hcc_description,
                #  icd10_code, icd10_description, source, provider_npi,
                #  status, attestation_type, clinical_justification,
                #  attested_at, tenant_id)
                (1, None, "HCC38", "",
                 "E1165", "Type 2 diabetes with hyperglycemia",
                 "manual", "1234567891",
                 "attested", "confirm_active",
                 "Patient has persistent hyperglycemia with A1C 8.2%, on metformin and glipizide. Condition actively managed with quarterly lab monitoring.",
                 "2026-03-15 10:30:00", "default"),
                (1, None, "HCC38", "",
                 "E119", "Type 2 diabetes without complications",
                 "manual", "1234567890",
                 "attested", "confirm_active",
                 "Confirmed ongoing diabetes management per recent endocrine consult. Continuing current regimen.",
                 "2026-03-18 14:00:00", "default"),
                (6, None, "HCC127", "",
                 "G309", "Alzheimer disease, unspecified",
                 "manual", "1234567895",
                 "attested", "confirm_active",
                 "Progressive cognitive decline documented over 18 months. MMSE score 18/30. Caregiver reports worsening short-term memory and ADL impairment.",
                 "2026-02-20 09:15:00", "default"),
                (6, None, "HCC127", "",
                 "G309", "Alzheimer disease, unspecified",
                 "suspect", "1234567890",
                 "pending", "defer_need_info",
                 None,
                 None, "default"),
                (14, None, "HCC29", "",
                 "K74.60", "Unspecified cirrhosis of liver",
                 "manual", "1234567890",
                 "attested", "confirm_active",
                 "Liver cirrhosis confirmed by imaging and elevated LFTs. Child-Pugh A. Monitored with biannual ultrasound.",
                 "2026-03-01 11:00:00", "default"),
                (14, None, "HCC37", "",
                 "E11.9", "Type 2 diabetes mellitus without complications",
                 "manual", "1234567891",
                 "attested", "confirm_active",
                 "Diabetes well-controlled on metformin. A1C 7.1%. No microvascular complications on exam.",
                 "2026-03-05 13:30:00", "default"),
                (14, None, "HCC85", "",
                 "I50.9", "Heart failure, unspecified",
                 "manual", "1234567893",
                 "attested", "confirm_active",
                 "Systolic HF with EF 35% on echo 2026-01. On lisinopril, carvedilol, spironolactone. NYHA Class II.",
                 "2026-03-10 15:45:00", "default"),
                (14, None, "HCC141", "",
                 "N18.3", "Chronic kidney disease, stage 3",
                 "manual", "1234567890",
                 "attested", "confirm_active",
                 "eGFR 48 mL/min stable over 6 months. Managed with ACE inhibitor dose adjustment and dietary counseling.",
                 "2026-03-12 10:00:00", "default"),
                (16, None, "HCC52", "",
                 "F03.90", "Unspecified dementia without behavioral disturbance",
                 "manual", "1234567895",
                 "attested", "confirm_active",
                 "Moderate dementia per neuropsych eval. Patient requires 24hr supervision. On donepezil 10mg.",
                 "2026-02-28 11:30:00", "default"),
                (16, None, "HCC78", "",
                 "G20", "Parkinson disease",
                 "manual", "1234567890",
                 "attested", "confirm_active",
                 "Parkinsonism with resting tremor and bradykinesia. Managed with carbidopa-levodopa. Neurology co-managing.",
                 "2026-03-02 09:00:00", "default"),
                (16, None, "HCC85", "",
                 "I50.9", "Heart failure, unspecified",
                 "manual", "1234567893",
                 "attested", "confirm_active",
                 "Diastolic HF with preserved EF 50%. BNP elevated at 340. On diuretic therapy with fluid restriction.",
                 "2026-03-08 14:15:00", "default"),
                (16, None, "HCC112", "",
                 "J44.1", "COPD with acute exacerbation",
                 "encounter", "1234567894",
                 "rejected", "reject_inaccurate",
                 None,
                 None, "default"),
                (16, None, "HCC112", "",
                 "J44.1", "COPD with acute exacerbation",
                 "suspect", "1234567894",
                 "pending", "defer_need_info",
                 None,
                 None, "default"),
                (16, None, "HCC137", "",
                 "N18.4", "Chronic kidney disease, stage 4",
                 "manual", "1234567890",
                 "attested", "confirm_active",
                 "CKD stage 4 with eGFR 22. Nephrology referral completed. Monitoring for dialysis readiness.",
                 "2026-03-14 16:00:00", "default"),
                (19, None, "HCC52", "",
                 "F03.90", "Unspecified dementia without behavioral disturbance",
                 "manual", "1234567895",
                 "attested", "confirm_active",
                 "Vascular dementia with stepwise decline post-CVA. MMSE 15/30. Requires full-time caregiver assistance.",
                 "2026-02-25 10:00:00", "default"),
                (19, None, "HCC79", "",
                 "G40.909", "Epilepsy, unspecified, not intractable",
                 "suspect", "1234567890",
                 "pending", "defer_need_info",
                 None,
                 None, "default"),
                (19, None, "HCC85", "",
                 "I50.9", "Heart failure, unspecified",
                 "manual", "1234567893",
                 "attested", "confirm_active",
                 "CHF with reduced EF 30%. On guideline-directed therapy. ICD placed 2025-11.",
                 "2026-03-06 11:45:00", "default"),
                (19, None, "HCC100", "",
                 "I63.9", "Cerebral infarction, unspecified",
                 "manual", "1234567890",
                 "attested", "confirm_active",
                 "History of ischemic stroke 2025-06. Residual left-sided weakness. On dual antiplatelet and statin therapy.",
                 "2026-03-09 09:30:00", "default"),
                (19, None, "HCC137", "",
                 "N18.4", "Chronic kidney disease, stage 4",
                 "manual", "1234567890",
                 "attested", "confirm_active",
                 "CKD stage 4 with eGFR 25. Secondary to diabetic nephropathy. AV fistula planned.",
                 "2026-03-11 13:00:00", "default"),
            ]
            for a in attestations:
                # Resolve provider_user_id from provider NPI (required on some
                # deployments where the column has been altered to NOT NULL).
                provider_npi = a[7]
                resolved_pid = npi_to_id.get(provider_npi) or 0
                cur.execute(
                    """INSERT INTO provider_attestations
                       (patient_id, encounter_id, hcc_code, hcc_description,
                        icd10_code, icd10_description, source, provider_npi,
                        status, attestation_type, clinical_justification,
                        attested_at, tenant_id, provider_user_id)
                       SELECT %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s
                       FROM DUAL
                       WHERE NOT EXISTS (
                           SELECT 1 FROM provider_attestations
                           WHERE patient_id = %s AND hcc_code = %s
                             AND icd10_code = %s AND provider_npi = %s AND source = %s
                       )""",
                    (*a, resolved_pid, a[0], a[2], a[4], a[7], a[6]),
                )

            # ----------------------------------------------------------
            # Provider patient panel
            # ----------------------------------------------------------
            panels = [
                # (provider_id, patient_id, panel_type, attribution_date,
                #  last_visit_date, attribution)
                (1, 1, "attributed", "2026-01-01", "2026-03-18", "cms"),
                (1, 5, "attributed", "2026-01-01", "2026-02-12", "cms"),
                (1, 6, "attributed", "2026-01-01", "2026-03-05", "cms"),
                (1, 7, "attributed", "2026-01-01", "2026-01-22", "cms"),
                (1, 8, "attributed", "2026-01-01", "2026-03-28", "cms"),
                (1, 9, "attributed", "2026-01-01", "2026-02-15", "cms"),
                (1, 10, "attributed", "2026-01-01", "2026-03-10", "cms"),
                (1, 12, "attributed", "2026-01-01", "2026-01-30", "cms"),
                (1, 14, "attributed", "2026-01-01", "2026-03-12", "cms"),
                (1, 15, "attributed", "2026-01-01", "2026-02-20", "cms"),
                (1, 16, "attributed", "2026-01-01", "2026-03-14", "cms"),
                (1, 17, "attributed", "2026-01-01", "2026-03-01", "cms"),
                (3, 18, "attributed", "2026-01-01", "2026-02-10", "cms"),
                (3, 19, "attributed", "2026-01-01", "2026-03-09", "cms"),
                (3, 20, "attributed", "2026-01-01", "2026-03-20", "cms"),
                (3, 21, "attributed", "2026-01-01", "2026-01-15", "cms"),
                (3, 23, "attributed", "2026-01-01", "2026-02-28", "cms"),
                (3, 24, "attributed", "2026-01-01", "2026-03-25", "cms"),
                (3, 25, "attributed", "2026-01-01", "2026-02-05", "cms"),
                (3, 26, "attributed", "2026-01-01", "2026-03-15", "cms"),
                (3, 27, "attributed", "2026-01-01", "2026-01-20", "cms"),
                (3, 28, "attributed", "2026-01-01", "2026-02-18", "cms"),
                (3, 29, "attributed", "2026-01-01", "2026-03-05", "cms"),
                (3, 30, "attributed", "2026-01-01", "2026-03-30", "cms"),
                (6, 6, "assigned", "2026-01-15", "2026-02-20", "manual"),
                (6, 16, "assigned", "2026-01-15", "2026-02-28", "manual"),
                (6, 19, "assigned", "2026-01-15", "2026-02-25", "manual"),
                (2, 1, "seen", "2026-01-10", "2026-03-15", "manual"),
                (2, 14, "seen", "2026-01-10", "2026-03-05", "manual"),
                (4, 14, "seen", "2026-01-20", "2026-03-10", "manual"),
                (4, 16, "seen", "2026-01-20", "2026-03-08", "manual"),
                (4, 19, "seen", "2026-01-20", "2026-03-06", "manual"),
                (5, 16, "seen", "2026-02-01", "2026-03-22", "manual"),
            ]
            for pp in panels:
                logical_idx = pp[0]
                npi = ordered_npis[logical_idx - 1]
                real_pid = npi_to_id.get(npi)
                if real_pid is None:
                    logger.warning(
                        "Skipping panel for NPI %s — provider row missing.", npi
                    )
                    continue
                pp_real = (real_pid,) + pp[1:]
                try:
                    cur.execute(
                        """INSERT INTO provider_patient_panel
                           (provider_id, patient_id, panel_type, attribution_date,
                            last_visit_date, attribution)
                           SELECT %s,%s,%s,%s,%s,%s
                           FROM DUAL
                           WHERE NOT EXISTS (
                               SELECT 1 FROM provider_patient_panel
                               WHERE provider_id = %s AND patient_id = %s AND panel_type = %s
                           )""",
                        (*pp_real, pp_real[0], pp_real[1], pp_real[2]),
                    )
                except Exception as pp_exc:
                    logger.warning(
                        "Skipping panel (pid=%s, patient=%s): %s",
                        real_pid, pp_real[1], pp_exc,
                    )

        logger.info("Provider demo data seeded successfully.")
    except Exception as exc:
        logger.error("Failed to seed provider demo data: %s", exc)
