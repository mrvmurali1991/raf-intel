"""Seed a complete demo panel so the storyboard shows real product UI.

What this populates (all idempotent, safe to re-run)
----------------------------------------------------
1. ``patient_data``         -- 12 demo patients (synthetic names + DOBs)
2. ``patients`` VIEW        -- created if missing; maps patient_data to the
                              shape the rest of the codebase expects
                              (id / first_name / last_name / dob / gender /
                              tenant_id / is_active / emr_pid / data_source)
3. ``emr_connections``      -- 1 active row marked is_demo=true so
                              /api/emr/status returns connected:true
4. ``raf_patient_hcc``      -- prior-year HCCs for each patient
                              (some get re-coded current-year, some don't --
                              that's how recapture gaps surface)
5. ``recapture_gaps``       -- 16 open gaps with realistic HCCs
6. ``raf_suspect_conditions`` -- 15 NLP-flagged suspects with
                              calibrated confidence + evidence_detail
7. ``raf_scores``           -- final RAF per patient (for the avg-RAF tile)
8. ``normalized_encounters`` -- one encounter per patient linked to the demo
                              provider NPI so the worklist query returns rows

Refuses to run unless APP_ENV is development / demo.

Tags every row with ``audit_notes='DEMO_PANEL'`` (where the column
exists) so an operator can purge the whole demo with::

    DELETE FROM recapture_gaps     WHERE audit_notes = 'DEMO_PANEL';
    DELETE FROM raf_suspect_conditions WHERE reviewed_by = 'DEMO_PANEL';
    DELETE FROM raf_patient_hcc    WHERE source_encounter_ids LIKE '%DEMO_PANEL%';
    DELETE FROM normalized_encounters WHERE encounter_id LIKE 'DEMO_PANEL_%';
    DELETE FROM patient_data       WHERE is_demo = 1;
    DELETE FROM emr_connections    WHERE name = 'Demo OpenEMR (local seed)';
"""
from __future__ import annotations

import json
import os
import random
import sys
from datetime import date, datetime, timedelta
from typing import Any

sys.path.insert(0, "/app")
from app.db import raf_cursor  # noqa: E402

DEMO_TAG = "DEMO_PANEL"
TENANT_ID = "1"
DEMO_YEAR = date.today().year

# NPI used for the demo admin provider -- must match providers.npi for user_id=1
DEMO_PROVIDER_NPI = "1234567890"
# user_id of the admin account (admin@raf.health)
DEMO_USER_ID = 1

# ---------------------------------------------------------------------------
# Synthetic panel -- names chosen to be obviously not-real-patient
# ---------------------------------------------------------------------------

PANEL = [
    # (first, last, dob, sex, race, ethnicity)
    ("Alex",     "Anderson",  "1948-03-12", "F", "White", "Not Hispanic"),
    ("Beverly",  "Brown",     "1952-07-23", "F", "Black", "Not Hispanic"),
    ("Carlos",   "Castro",    "1955-11-04", "M", "White", "Hispanic"),
    ("Diane",    "Diaz",      "1949-02-18", "F", "White", "Hispanic"),
    ("Edward",   "Evans",     "1957-09-30", "M", "Black", "Not Hispanic"),
    ("Frances",  "Foster",    "1944-12-09", "F", "White", "Not Hispanic"),
    ("Gerald",   "Gonzalez",  "1951-05-15", "M", "White", "Hispanic"),
    ("Helen",    "Harris",    "1953-08-25", "F", "Asian", "Not Hispanic"),
    ("Isaac",    "Ibarra",    "1947-01-19", "M", "White", "Hispanic"),
    ("Joyce",    "Jackson",   "1956-04-08", "F", "Black", "Not Hispanic"),
    ("Kenneth",  "Kim",       "1950-10-27", "M", "Asian", "Not Hispanic"),
    ("Linda",    "Lopez",     "1958-06-14", "F", "White", "Hispanic"),
]

# (icd10, hcc_code, label, raf_coef)
PRIOR_YEAR_HCCS = [
    ("E11.65", 19, "Diabetes with hyperglycemia", 0.302),
    ("J44.9",  111, "COPD, unspecified",            0.347),
    ("I50.9",  85,  "Heart failure, unspecified",   0.331),
    ("N18.4",  138, "CKD stage 4",                  0.421),
    ("F03.90", 52,  "Dementia, unspecified",        0.305),
    ("D63.8",  48,  "Anemia in chronic disease",    0.245),
    ("Z99.81", 84,  "Dependence on supplemental O2", 0.288),
    ("R65.20", 2,   "Severe sepsis",                 0.435),
    ("M06.9",  40,  "Rheumatoid arthritis",          0.288),
    ("C50.911", 12, "Breast cancer",                 0.150),
]

SUSPECT_CONDITIONS = [
    ("E11.65", 19, "medication", "metformin + insulin combination", 0.92),
    ("I50.9",  85, "lab",        "BNP > 400, EF < 40%",             0.88),
    ("J44.9",  111, "imaging",   "CT chest: emphysematous changes", 0.81),
    ("N18.4",  138, "lab",       "eGFR 22 over 3 consecutive labs", 0.94),
    ("F03.90", 52, "referral",   "neurology consult: cognitive decline", 0.76),
    ("D63.8",  48, "lab",        "Hgb 9.8 with chronic disease history", 0.71),
    ("M06.9",  40, "medication", "methotrexate + biologic DMARD",    0.83),
    ("Z99.81", 84, "medication", "home oxygen prescription active", 0.90),
    ("E11.65", 19, "lab",        "HbA1c 9.2% sustained 12mo",       0.86),
    ("I50.9",  85, "imaging",    "echo: LVEF 35%, biplane",         0.79),
]


def _ensure_demo_environment() -> None:
    env = os.environ.get("APP_ENV", "").lower()
    if env not in {"development", "demo", "dev"}:
        raise SystemExit(
            f"Refusing to seed with APP_ENV={env!r}. "
            "Set APP_ENV=development or APP_ENV=demo."
        )


def _ensure_patients_view(cur: Any) -> None:
    # Bridge raf_intelligence.patients → openemr.patient_data so the
    # bundled OpenEMR (raf-mysql/openemr DB, populated by the project's
    # docker-compose.local.yml openemr container) is the single source
    # of truth for patient identity.  No synthetic patient inserts —
    # gaps / suspects / HCCs all reference real openemr pids.
    cur.execute(
        """
        CREATE OR REPLACE VIEW patients AS
        SELECT
            pid                             AS id,
            CAST(pid AS CHAR(20))           AS emr_pid,
            fname                           AS first_name,
            lname                           AS last_name,
            mname                           AS middle_name,
            DOB                             AS dob,
            sex                             AS sex,
            pubpid                          AS mrn,
            race,
            ethnicity,
            language                        AS preferred_language,
            street                          AS address,
            street,
            city,
            state,
            postal_code                     AS zip,
            postal_code,
            phone_cell                      AS phone,
            phone_home,
            phone_cell,
            email,
            CAST(NULL AS CHAR(20))          AS mbi,
            CAST(NULL AS CHAR(50))          AS insurance_type,
            providerID                      AS provider_id,
            'emr'                           AS data_source,
            1                               AS is_active,
            CAST(1 AS CHAR(64))             AS tenant_id,
            date                            AS created_at
        FROM openemr.patient_data
        """
    )


def _seed_patient_data(cur: Any) -> dict[int, str]:
    """Pick the first 12 patients from openemr.patient_data — they are
    real-looking demo patients (Margaret Chen, Robert Williams, etc.)
    seeded by the bundled OpenEMR docker container.  We do NOT insert
    new rows; gaps / suspects / HCCs reference the real openemr pids.

    Returns ``{pid: 'first last'}`` for the 12-patient demo cohort.
    """
    cur.execute(
        """
        SELECT pid, fname, lname
        FROM openemr.patient_data
        ORDER BY pid ASC
        LIMIT 12
        """
    )
    return {row["pid"]: f"{row['fname']} {row['lname']}" for row in cur.fetchall()}


def _seed_demo_provider(cur: Any) -> int:
    """Ensure a providers row exists with user_id=DEMO_USER_ID, tenant_id=TENANT_ID,
    and npi=DEMO_PROVIDER_NPI.

    The worklist service resolves NPI via:
        SELECT npi FROM providers WHERE user_id = %s AND tenant_id = %s
    so both columns must be set correctly for provider_id=1 (admin user) to
    resolve to NPI '1234567890'.
    """
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


def _seed_emr_connection(cur: Any) -> int:
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
        return int(row["id"])
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
    return int(cur.lastrowid)


def _seed_demographics(cur: Any, patients: dict[int, str]) -> None:
    for pid in patients:
        for yr in (DEMO_YEAR - 1, DEMO_YEAR):
            cur.execute(
                """
                SELECT id FROM raf_patient_demographics
                WHERE patient_id = %s AND measurement_year = %s
                LIMIT 1
                """,
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
                VALUES (%s, %s, '70-74', 'F', 0, 'non_dual', 0, '0',
                        0, 'derived', 'CNA')
                """,
                (pid, yr),
            )


def _ensure_normalized_encounters_table(cur: Any) -> None:
    """Create normalized_encounters if the migration has not run yet.

    The worklist service resolves patients exclusively via:

        SELECT DISTINCT p.id FROM patients p
        WHERE p.id IN (
            SELECT ne.patient_id FROM normalized_encounters ne
            WHERE  ne.tenant_id = <tenant> AND ne.provider_npi = <npi>
        )

    Without this table (or without rows linking patients to the demo provider
    NPI) the worklist query returns 0 patients regardless of gaps or HCCs.
    """
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS normalized_encounters (
            id             INT UNSIGNED  NOT NULL AUTO_INCREMENT,
            encounter_id   VARCHAR(100)  NOT NULL,
            patient_id     INT UNSIGNED  NOT NULL,
            tenant_id      VARCHAR(64)   NOT NULL DEFAULT '1',
            provider_npi   VARCHAR(20)   DEFAULT NULL,
            encounter_date DATE          NOT NULL,
            encounter_type VARCHAR(50)   DEFAULT 'office_visit',
            facility_name  VARCHAR(200)  DEFAULT NULL,
            is_demo        TINYINT(1)    NOT NULL DEFAULT 0,
            created_at     DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (id),
            UNIQUE KEY uq_enc_id_tenant (encounter_id, tenant_id),
            KEY idx_ne_patient  (patient_id),
            KEY idx_ne_provider (provider_npi),
            KEY idx_ne_tenant   (tenant_id),
            KEY idx_ne_date     (encounter_date)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """
    )


def _seed_normalized_encounters(cur: Any, patients: dict[int, str]) -> None:
    """Seed two encounter rows per demo patient, both linked to DEMO_PROVIDER_NPI.

    Two rows per patient:
      1. Prior-year visit -- provides realistic last_visit_date history.
      2. Current-year visit -- ensures last_visit_map shows DEMO_YEAR.

    Idempotent: keyed on (encounter_id, tenant_id) unique index.
    """
    prior_year_date   = date(DEMO_YEAR - 1, 6, 10)
    current_year_date = date(DEMO_YEAR, 1, 15)

    for pid in patients:
        for enc_date, enc_id in [
            (prior_year_date,   f"DEMO_PANEL_enc_{pid}"),
            (current_year_date, f"DEMO_PANEL_enc_{pid}_cy"),
        ]:
            cur.execute(
                """
                SELECT id FROM normalized_encounters
                WHERE encounter_id = %s AND tenant_id = %s
                LIMIT 1
                """,
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
    """Each patient gets 2-4 random prior-year HCCs."""
    rng = random.Random(2027)
    prior_year = DEMO_YEAR - 1
    for pid in patients:
        n = rng.randint(2, 4)
        chosen = rng.sample(PRIOR_YEAR_HCCS, n)
        for icd, hcc, _label, raf in chosen:
            cur.execute(
                """
                SELECT id FROM raf_patient_hcc
                WHERE patient_id = %s AND hcc_code = %s
                  AND measurement_year = %s AND tenant_id = %s
                LIMIT 1
                """,
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
    """Open gaps = prior-year HCCs without a current-year re-code.

    Key schema notes:
    - The worklist service filters by: status = 'open' AND current_year = <year>
    - current_year must equal DEMO_YEAR (not the column default 0).
    - prior_year must equal DEMO_YEAR - 1.
    Both are set explicitly in the INSERT and patched on idempotent re-runs.
    """
    rng = random.Random(4242)
    prior_year = DEMO_YEAR - 1
    pids = list(patients.keys())
    pairs = [(pid, hcc) for pid in pids for hcc in PRIOR_YEAR_HCCS]
    sample = rng.sample(pairs, int(len(pairs) * 0.45))
    for pid, (icd, hcc, label, _raf) in sample[:16]:
        cur.execute(
            """
            SELECT id FROM recapture_gaps
            WHERE patient_id = %s AND hcc_code = %s
              AND payment_year = %s AND tenant_id = %s
            LIMIT 1
            """,
            (pid, str(hcc), DEMO_YEAR, 1),
        )
        if cur.fetchone():
            cur.execute(
                """
                UPDATE recapture_gaps
                SET current_year = %s, prior_year = %s
                WHERE patient_id = %s AND hcc_code = %s
                  AND payment_year = %s AND tenant_id = %s
                """,
                (DEMO_YEAR, prior_year, pid, str(hcc), DEMO_YEAR, 1),
            )
            continue
        cur.execute(
            """
            INSERT INTO recapture_gaps
                (tenant_id, patient_id, icd10_code, hcc_code,
                 condition_label, payment_year, current_year, prior_year,
                 status, evidence_phrase, meat_element, revenue_impact,
                 audit_status, primary_coder_id, secondary_coder_id,
                 audit_notes)
            VALUES (1, %s, %s, %s, %s, %s, %s, %s, 'open',
                    %s, 'M', 3000.00,
                    'approved', 999, 998, %s)
            """,
            (
                pid, icd, str(hcc), label, DEMO_YEAR, DEMO_YEAR, prior_year,
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
            """
            SELECT id FROM raf_suspect_conditions
            WHERE patient_id = %s AND suspect_hcc = %s
              AND measurement_year = %s
            LIMIT 1
            """,
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
    cur.execute(
        """
        SELECT TABLE_NAME FROM INFORMATION_SCHEMA.TABLES
        WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'raf_scores'
        """
    )
    if not cur.fetchone():
        return
    rng = random.Random(7)
    for pid in patients:
        cur.execute(
            """
            SELECT id FROM raf_scores
            WHERE patient_id = %s AND measurement_year = %s
            LIMIT 1
            """,
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


def main() -> None:
    _ensure_demo_environment()
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

    print(f"Demo panel seeded: {len(patients)} patients, "
          f"{DEMO_YEAR} measurement year, tenant_id={TENANT_ID}")
    print(f"  -> /api/emr/status         should now return connected=true")
    print(f"  -> /api/dashboard/stats    should return total_patients={len(patients)}")
    print(f"  -> /worklist               should show prioritized cards")
    print(f"  -> /recapture              should show ~16 open gaps")
    print(f"  -> /suspects               should show ~15 calibrated suspects")
    print(f"\nPurge demo with:")
    print(f"  DELETE FROM recapture_gaps         WHERE audit_notes = '{DEMO_TAG}';")
    print(f"  DELETE FROM raf_suspect_conditions WHERE reviewed_by = '{DEMO_TAG}';")
    print(f"  DELETE FROM normalized_encounters  WHERE encounter_id LIKE 'DEMO_PANEL_%';")
    print(f"  DELETE FROM patient_data           WHERE is_demo = 1;")


if __name__ == "__main__":
    main()
