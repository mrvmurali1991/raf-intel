"""Auto-seed the demo patient panel at backend startup.

This module is called from main.py ``_run_demo_seeds()`` when
``APP_ENV`` is ``development`` or ``demo``.  It is idempotent:

    SELECT COUNT(*) FROM patient_data WHERE is_demo = 1

If that count is already >= 12 (the full PANEL size), the module
exits immediately — no writes, no duplicates.

Combines the logic from:
    backend/scripts/seed_demo_panel.py  — patient panel, HCCs, gaps, suspects
    backend/scripts/seed_irr_demo.py    — IRR labelling for audit-readiness kappa

Tags every inserted row so the demo is purgeable:
    is_demo = 1                              (patient_data)
    audit_notes = 'DEMO_PANEL'              (recapture_gaps)
    reviewed_by = 'DEMO_PANEL'             (raf_suspect_conditions)
    source_encounter_ids LIKE '%DEMO_PANEL%' (raf_patient_hcc)
    encounter_id LIKE 'DEMO_PANEL%'         (normalized_encounters)
"""
from __future__ import annotations

import json
import logging
import random
from datetime import date
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
DEMO_TAG = "DEMO_PANEL"
IRR_TAG = "IRR_DEMO"
TENANT_ID = "1"
DEMO_YEAR = date.today().year
DEMO_PROVIDER_NPI = "1234567890"
DEMO_USER_ID = 1

PANEL = [
    # (first, last, dob, sex, race, ethnicity)
    ("Alex",    "Anderson", "1948-03-12", "F", "White", "Not Hispanic"),
    ("Beverly", "Brown",    "1952-07-23", "F", "Black", "Not Hispanic"),
    ("Carlos",  "Castro",   "1955-11-04", "M", "White", "Hispanic"),
    ("Diane",   "Diaz",     "1949-02-18", "F", "White", "Hispanic"),
    ("Edward",  "Evans",    "1957-09-30", "M", "Black", "Not Hispanic"),
    ("Frances", "Foster",   "1944-12-09", "F", "White", "Not Hispanic"),
    ("Gerald",  "Gonzalez", "1951-05-15", "M", "White", "Hispanic"),
    ("Helen",   "Harris",   "1953-08-25", "F", "Asian", "Not Hispanic"),
    ("Isaac",   "Ibarra",   "1947-01-19", "M", "White", "Hispanic"),
    ("Joyce",   "Jackson",  "1956-04-08", "F", "Black", "Not Hispanic"),
    ("Kenneth", "Kim",      "1950-10-27", "M", "Asian", "Not Hispanic"),
    ("Linda",   "Lopez",    "1958-06-14", "F", "White", "Hispanic"),
]

PRIOR_YEAR_HCCS = [
    ("E11.65", 19,  "Diabetes with hyperglycemia",         0.302),
    ("J44.9",  111, "COPD, unspecified",                   0.347),
    ("I50.9",  85,  "Heart failure, unspecified",           0.331),
    ("N18.4",  138, "CKD stage 4",                         0.421),
    ("F03.90", 52,  "Dementia, unspecified",                0.305),
    ("D63.8",  48,  "Anemia in chronic disease",            0.245),
    ("Z99.81", 84,  "Dependence on supplemental O2",        0.288),
    ("R65.20", 2,   "Severe sepsis",                        0.435),
    ("M06.9",  40,  "Rheumatoid arthritis",                 0.288),
    ("C50.911", 12, "Breast cancer",                        0.150),
]

SUSPECT_CONDITIONS = [
    ("E11.65", 19,  "medication", "metformin + insulin combination",        0.92),
    ("I50.9",  85,  "lab",        "BNP > 400, EF < 40%",                    0.88),
    ("J44.9",  111, "imaging",    "CT chest: emphysematous changes",         0.81),
    ("N18.4",  138, "lab",        "eGFR 22 over 3 consecutive labs",         0.94),
    ("F03.90", 52,  "referral",   "neurology consult: cognitive decline",    0.76),
    ("D63.8",  48,  "lab",        "Hgb 9.8 with chronic disease history",   0.71),
    ("M06.9",  40,  "medication", "methotrexate + biologic DMARD",           0.83),
    ("Z99.81", 84,  "medication", "home oxygen prescription active",         0.90),
    ("E11.65", 19,  "lab",        "HbA1c 9.2% sustained 12mo",              0.86),
    ("I50.9",  85,  "imaging",    "echo: LVEF 35%, biplane",                0.79),
]

# Target number of IRR-labelled rows for kappa computation.
IRR_TARGET = 20


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _table_exists(cur: Any, name: str) -> bool:
    cur.execute(
        "SELECT 1 FROM INFORMATION_SCHEMA.TABLES "
        "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s",
        (name,),
    )
    return cur.fetchone() is not None


def _column_exists(cur: Any, table: str, column: str) -> bool:
    cur.execute(
        "SELECT 1 FROM INFORMATION_SCHEMA.COLUMNS "
        "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s AND COLUMN_NAME = %s",
        (table, column),
    )
    return cur.fetchone() is not None


# ---------------------------------------------------------------------------
# Panel seeding — mirrors seed_demo_panel.py exactly
# ---------------------------------------------------------------------------

def _ensure_patients_view(cur: Any) -> None:
    cur.execute(
        """
        CREATE OR REPLACE VIEW patients AS
        SELECT
            pid                        AS id,
            CAST(pid AS CHAR(20))      AS emr_pid,
            fname                      AS first_name,
            lname                      AS last_name,
            mname                      AS middle_name,
            DOB                        AS dob,
            sex                        AS gender,
            race,
            ethnicity,
            street, city, state, postal_code,
            phone_home, phone_cell, email,
            providerID                 AS provider_id,
            CASE WHEN is_demo = 1 THEN 'demo' ELSE 'emr' END AS data_source,
            1                          AS is_active,
            CAST(1 AS CHAR(64))        AS tenant_id,
            date                       AS created_at
        FROM patient_data
        """
    )


def _seed_patient_data(cur: Any) -> dict[int, str]:
    inserted: dict[int, str] = {}
    for first, last, dob, sex, race, ethn in PANEL:
        cur.execute(
            "SELECT pid FROM patient_data WHERE fname=%s AND lname=%s AND DOB=%s",
            (first, last, dob),
        )
        row = cur.fetchone()
        if row:
            inserted[row["pid"]] = f"{first} {last}"
            continue
        cur.execute(
            "INSERT INTO patient_data (fname, lname, DOB, sex, race, ethnicity, is_demo) "
            "VALUES (%s, %s, %s, %s, %s, %s, 1)",
            (first, last, dob, sex, race, ethn),
        )
        inserted[cur.lastrowid] = f"{first} {last}"
    return inserted


def _seed_demo_provider(cur: Any) -> int:
    cur.execute(
        "SELECT id FROM providers WHERE user_id = %s AND tenant_id = %s LIMIT 1",
        (DEMO_USER_ID, TENANT_ID),
    )
    row = cur.fetchone()
    if row:
        cur.execute(
            "UPDATE providers SET npi = %s WHERE id = %s",
            (DEMO_PROVIDER_NPI, row["id"]),
        )
        return int(row["id"])

    cur.execute(
        "SELECT id FROM providers WHERE openemr_user_id = %s LIMIT 1",
        (DEMO_USER_ID,),
    )
    row = cur.fetchone()
    if row:
        cur.execute(
            "UPDATE providers SET user_id = %s, tenant_id = %s, npi = %s WHERE id = %s",
            (DEMO_USER_ID, TENANT_ID, DEMO_PROVIDER_NPI, row["id"]),
        )
        return int(row["id"])

    cur.execute(
        """
        INSERT INTO providers
            (openemr_user_id, user_id, npi, first_name, last_name, full_name,
             specialty, status, is_active, tenant_id)
        VALUES (%s, %s, %s, 'Demo', 'Provider', 'Demo Provider, MD',
                'Internal Medicine', 'active', 1, %s)
        """,
        (DEMO_USER_ID, DEMO_USER_ID, DEMO_PROVIDER_NPI, TENANT_ID),
    )
    return int(cur.lastrowid)


def _link_patients_to_provider(cur: Any, patients: dict[int, str], provider_id: int) -> None:
    if not patients:
        return
    placeholders = ", ".join(["%s"] * len(patients))
    cur.execute(
        f"UPDATE patient_data SET providerID = %s WHERE pid IN ({placeholders})",
        (provider_id, *patients.keys()),
    )


def _seed_emr_connection(cur: Any) -> None:
    cur.execute(
        "SELECT id FROM emr_connections WHERE name = %s LIMIT 1",
        ("Demo OpenEMR (local seed)",),
    )
    row = cur.fetchone()
    if row:
        cur.execute(
            "UPDATE emr_connections SET is_active = 1 WHERE id = %s",
            (row["id"],),
        )
        return
    cur.execute(
        """
        INSERT INTO emr_connections
            (name, display_name, base_url, vendor, connection_type,
             auth_type, is_active, tenant_id)
        VALUES (%s, %s, %s, %s, %s, %s, 1, %s)
        """,
        (
            "Demo OpenEMR (local seed)",
            "Demo OpenEMR Panel",
            "http://localhost:8080",
            "openemr",
            "direct_db",
            "api_key",
            TENANT_ID,
        ),
    )


def _seed_demographics(cur: Any, patients: dict[int, str]) -> None:
    for pid in patients:
        for yr in (DEMO_YEAR - 1, DEMO_YEAR):
            cur.execute(
                "SELECT id FROM raf_patient_demographics "
                "WHERE patient_id = %s AND measurement_year = %s LIMIT 1",
                (pid, yr),
            )
            if cur.fetchone():
                continue
            cur.execute(
                """
                INSERT INTO raf_patient_demographics
                    (patient_id, measurement_year, age_band, sex,
                     dual_status, dual_type, disabled, orec,
                     institutional, enrollment_source, model_segment)
                VALUES (%s, %s, '70-74', 'F', 0, 'non_dual', 0, '0', 0, 'derived', 'CNA')
                """,
                (pid, yr),
            )


def _ensure_normalized_encounters_table(cur: Any) -> None:
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS normalized_encounters (
            id            INT UNSIGNED    NOT NULL AUTO_INCREMENT,
            encounter_id  VARCHAR(100)    NOT NULL,
            patient_id    INT UNSIGNED    NOT NULL,
            tenant_id     VARCHAR(64)     NOT NULL DEFAULT '1',
            provider_npi  VARCHAR(20)     DEFAULT NULL,
            encounter_date DATE           NOT NULL,
            encounter_type VARCHAR(50)    DEFAULT 'office_visit',
            facility_name  VARCHAR(200)   DEFAULT NULL,
            is_demo        TINYINT(1)     NOT NULL DEFAULT 0,
            created_at    DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (id),
            UNIQUE KEY uq_enc_id_tenant (encounter_id, tenant_id),
            KEY idx_ne_patient   (patient_id),
            KEY idx_ne_provider  (provider_npi),
            KEY idx_ne_tenant    (tenant_id),
            KEY idx_ne_date      (encounter_date)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """
    )


def _seed_normalized_encounters(cur: Any, patients: dict[int, str]) -> None:
    prior_year = DEMO_YEAR - 1
    current_year_date = date(DEMO_YEAR, 1, 15)
    prior_year_date = date(prior_year, 6, 10)
    for pid in patients:
        for enc_date, enc_id in [
            (prior_year_date, f"DEMO_PANEL_enc_{pid}"),
            (current_year_date, f"DEMO_PANEL_enc_{pid}_cy"),
        ]:
            cur.execute(
                "SELECT id FROM normalized_encounters "
                "WHERE encounter_id = %s AND tenant_id = %s LIMIT 1",
                (enc_id, TENANT_ID),
            )
            if cur.fetchone():
                continue
            cur.execute(
                """
                INSERT INTO normalized_encounters
                    (encounter_id, patient_id, tenant_id,
                     provider_npi, encounter_date, encounter_type,
                     facility_name, is_demo)
                VALUES (%s, %s, %s, %s, %s, 'office_visit', 'Demo Clinic', 1)
                """,
                (enc_id, pid, TENANT_ID, DEMO_PROVIDER_NPI, enc_date),
            )


def _seed_prior_year_hccs(cur: Any, patients: dict[int, str]) -> None:
    rng = random.Random(2027)
    prior_year = DEMO_YEAR - 1
    for pid in patients:
        n = rng.randint(2, 4)
        chosen = rng.sample(PRIOR_YEAR_HCCS, n)
        for icd, hcc, _label, raf in chosen:
            cur.execute(
                "SELECT id FROM raf_patient_hcc "
                "WHERE patient_id = %s AND hcc_code = %s "
                "AND measurement_year = %s AND tenant_id = %s LIMIT 1",
                (pid, hcc, prior_year, TENANT_ID),
            )
            if cur.fetchone():
                continue
            cur.execute(
                """
                INSERT INTO raf_patient_hcc
                    (patient_id, measurement_year, hcc_code, icd10_codes,
                     source_encounter_ids, raf_coefficient, meat_status,
                     model_version, tenant_id)
                VALUES (%s, %s, %s, %s, %s, %s, 'complete', 'V28', %s)
                """,
                (
                    pid, prior_year, hcc,
                    json.dumps([icd]),
                    json.dumps([f"DEMO_PANEL_enc_{pid}"]),
                    raf, TENANT_ID,
                ),
            )


def _seed_recapture_gaps(cur: Any, patients: dict[int, str]) -> None:
    rng = random.Random(4242)
    pids = list(patients.keys())
    pairs = [(pid, hcc) for pid in pids for hcc in PRIOR_YEAR_HCCS]
    sample = rng.sample(pairs, int(len(pairs) * 0.45))
    for pid, (icd, hcc, label, _raf) in sample[:16]:
        cur.execute(
            "SELECT id FROM recapture_gaps "
            "WHERE patient_id = %s AND hcc_code = %s "
            "AND payment_year = %s AND tenant_id = %s LIMIT 1",
            (pid, str(hcc), DEMO_YEAR, 1),
        )
        if cur.fetchone():
            continue
        cur.execute(
            """
            INSERT INTO recapture_gaps
                (tenant_id, patient_id, icd10_code, hcc_code,
                 condition_label, payment_year, status,
                 evidence_phrase, meat_element, revenue_impact,
                 audit_status, primary_coder_id, secondary_coder_id,
                 audit_notes)
            VALUES (1, %s, %s, %s, %s, %s, 'open',
                    %s, 'M', 3000.00,
                    'approved', 999, 998, %s)
            """,
            (
                pid, icd, str(hcc), label, DEMO_YEAR,
                f"Documented {label.lower()} per chart 12mo prior",
                DEMO_TAG,
            ),
        )


def _seed_suspects(cur: Any, patients: dict[int, str]) -> None:
    rng = random.Random(99)
    pids = list(patients.keys())
    for i in range(15):
        pid = pids[i % len(pids)]
        icd, hcc, evtype, detail, conf = SUSPECT_CONDITIONS[i % len(SUSPECT_CONDITIONS)]
        cur.execute(
            "SELECT id FROM raf_suspect_conditions "
            "WHERE patient_id = %s AND suspect_hcc = %s AND measurement_year = %s LIMIT 1",
            (pid, hcc, DEMO_YEAR),
        )
        if cur.fetchone():
            continue
        raw = round(min(0.99, conf + rng.uniform(0.05, 0.15)), 4)
        cur.execute(
            """
            INSERT INTO raf_suspect_conditions
                (patient_id, measurement_year, suspect_hcc, suspect_icd10,
                 evidence_type, evidence_detail, confidence_score,
                 status, reviewed_by)
            VALUES (%s, %s, %s, %s, %s, %s, %s, 'open', %s)
            """,
            (
                pid, DEMO_YEAR, hcc, icd, evtype,
                json.dumps({
                    "raw_confidence": raw,
                    "calibrated_confidence": conf,
                    "summary": detail,
                    "calibration_a": 1.0341,
                    "calibration_b": 0.1189,
                }),
                conf, DEMO_TAG,
            ),
        )


def _seed_raf_scores(cur: Any, patients: dict[int, str]) -> None:
    if not _table_exists(cur, "raf_scores"):
        return
    rng = random.Random(7)
    for pid in patients:
        cur.execute(
            "SELECT id FROM raf_scores "
            "WHERE patient_id = %s AND measurement_year = %s LIMIT 1",
            (pid, DEMO_YEAR),
        )
        if cur.fetchone():
            continue
        demo_raf = round(rng.uniform(0.50, 0.75), 4)
        hcc_raf = round(rng.uniform(0.60, 1.40), 4)
        final = round(demo_raf + hcc_raf, 4)
        cur.execute(
            """
            INSERT INTO raf_scores
                (patient_id, measurement_year, score_type, model_segment,
                 demographic_score, disease_score, interaction_score,
                 total_raw, normalization_factor, final_raf, hcc_count,
                 calculated_at)
            VALUES (%s, %s, 'prospective', 'CNA',
                    %s, %s, 0.0000,
                    %s, 1.0000, %s, 3,
                    NOW())
            """,
            (pid, DEMO_YEAR, demo_raf, hcc_raf, final, final),
        )


# ---------------------------------------------------------------------------
# IRR seeding — mirrors seed_irr_demo.py exactly
# ---------------------------------------------------------------------------

def _seed_irr_rows(cur: Any) -> None:
    """Insert IRR_DEMO rows into recapture_gaps if the table is thin."""
    if not _table_exists(cur, "recapture_gaps"):
        logger.warning("recapture_gaps table not found — skipping IRR seed.")
        return
    for col in ("primary_coder_label", "secondary_coder_label", "audit_status"):
        if not _column_exists(cur, "recapture_gaps", col):
            logger.warning(
                "Missing column recapture_gaps.%s — skipping IRR seed.", col
            )
            return

    cur.execute(
        "SELECT COUNT(*) AS n FROM recapture_gaps WHERE audit_notes = %s",
        (IRR_TAG,),
    )
    existing = int(cur.fetchone()["n"])
    if existing >= IRR_TARGET:
        logger.info("IRR demo rows already present (%d) — re-labelling only.", existing)
        _label_irr_rows(cur)
        return

    sample_hccs = [
        ("E11.65", "19",  "Diabetes with hyperglycemia"),
        ("J44.9",  "111", "COPD, unspecified"),
        ("I50.9",  "85",  "Heart failure, unspecified"),
        ("N18.4",  "138", "CKD stage 4"),
        ("F03.90", "52",  "Dementia, unspecified"),
        ("D63.8",  "48",  "Anemia in chronic disease"),
        ("R65.20", "2",   "Severe sepsis"),
        ("Z99.81", "84",  "Dependence on supplemental oxygen"),
    ]
    n_to_add = IRR_TARGET - existing
    rows = []
    for i in range(n_to_add):
        icd, hcc, label = sample_hccs[i % len(sample_hccs)]
        rows.append((
            1,
            (i % 8) + 1,
            icd, hcc,
            f"{label} (demo)",
            DEMO_YEAR,
            "open",
            f"Patient with documented {label.lower()} per chart note",
            "M",
            3000.0,
            "approved",
            999, 998,
            IRR_TAG,
        ))
    cur.executemany(
        """
        INSERT INTO recapture_gaps (
            tenant_id, patient_id, icd10_code, hcc_code, condition_label,
            payment_year, status, evidence_phrase, meat_element,
            revenue_impact, audit_status, primary_coder_id, secondary_coder_id,
            audit_notes
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """,
        rows,
    )
    _label_irr_rows(cur)


def _label_irr_rows(cur: Any) -> None:
    cur.execute(
        "SELECT id FROM recapture_gaps WHERE audit_notes = %s ORDER BY id ASC",
        (IRR_TAG,),
    )
    ids = [row["id"] for row in cur.fetchall()]
    if not ids:
        return
    rng = random.Random(1234)
    n = len(ids)
    n_aa = round(n * 0.60)
    n_rr = round(n * 0.20)
    n_ar = round(n * 0.10)
    n_ra = n - n_aa - n_rr - n_ar
    pattern: list[tuple[str, str]] = (
        [("accept", "accept")] * n_aa
        + [("reject", "reject")] * n_rr
        + [("accept", "reject")] * n_ar
        + [("reject", "accept")] * n_ra
    )
    rng.shuffle(pattern)
    for gap_id, (primary, secondary) in zip(ids, pattern):
        if primary == secondary == "accept":
            new_status = "approved"
        elif primary == secondary == "reject":
            new_status = "approved"
        else:
            new_status = "rejected"
        cur.execute(
            """
            UPDATE recapture_gaps
            SET primary_coder_label = %s,
                secondary_coder_label = %s,
                audit_status = %s,
                primary_coded_at   = COALESCE(primary_coded_at, NOW()),
                secondary_approved_at = COALESCE(secondary_approved_at, NOW())
            WHERE id = %s
            """,
            (primary, secondary, new_status, gap_id),
        )


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def seed_panel_demo() -> None:
    """Seed the full demo panel if patient_data has no demo rows.

    Called from main.py ``_run_demo_seeds()``.  Safe to call on every
    container restart — no-op when data is present.
    """
    from app.db import raf_cursor  # late import — avoids circular at module load

    try:
        with raf_cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) AS cnt FROM patient_data WHERE is_demo = 1"
            )
            cnt = int(cur.fetchone()["cnt"])
    except Exception as exc:
        logger.warning("Cannot check demo patient count (DB may not be ready): %s", exc)
        return

    if cnt >= len(PANEL):
        logger.info(
            "Demo panel already seeded (%d patients) — skipping panel seed.", cnt
        )
        # Still re-run IRR labelling so coder labels survive restarts that
        # don't wipe the volume (labels are UPDATEs, safe to repeat).
        try:
            with raf_cursor() as cur:
                _seed_irr_rows(cur)
        except Exception as exc:
            logger.warning("IRR re-label failed (non-fatal): %s", exc)
        return

    logger.info("Demo panel not found (%d rows) — seeding %d patients …", cnt, len(PANEL))
    try:
        with raf_cursor() as cur:
            _ensure_patients_view(cur)
            patients = _seed_patient_data(cur)
            provider_id = _seed_demo_provider(cur)
            _link_patients_to_provider(cur, patients, provider_id)
            _seed_emr_connection(cur)
            _seed_demographics(cur, patients)
            _ensure_normalized_encounters_table(cur)
            _seed_normalized_encounters(cur, patients)
            _seed_prior_year_hccs(cur, patients)
            _seed_recapture_gaps(cur, patients)
            _seed_suspects(cur, patients)
            _seed_raf_scores(cur, patients)
            _seed_irr_rows(cur)
    except Exception as exc:
        logger.error("Demo panel seed failed (non-fatal): %s", exc, exc_info=True)
        return

    logger.info(
        "Demo panel seeded: %d patients, measurement_year=%d, tenant_id=%s",
        len(patients), DEMO_YEAR, TENANT_ID,
    )
    logger.info("  -> /api/emr/status      should return connected=true")
    logger.info("  -> /api/dashboard/stats should return total_patients=%d", len(patients))
    logger.info("  -> /worklist            should show prioritized cards")
    logger.info("  -> /recapture           should show ~16 open gaps")
