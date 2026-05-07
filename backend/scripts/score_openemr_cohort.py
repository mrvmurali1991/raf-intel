"""Score the full 30-patient OpenEMR cohort with synthetic RAF scores.

What this populates (all idempotent, safe to re-run)
-----------------------------------------------------
For EVERY patient in openemr.patient_data (up to 30):

1. ``raf_patient_demographics`` — realistic age-band / sex / dual_status variants
2. ``raf_patient_hcc``          — 1-5 prior-year HCCs per patient with raf_coefficients
                                   sourced from PRIOR_YEAR_HCCS; 0-3 current-year HCCs
                                   so some patients have recapture gaps
3. ``raf_scores``               — one row per patient with final_raf computed as
                                   sum(raf_coefficients) + demographic_raf
   Also seeds normalized_encounters so the worklist subquery finds every patient.

Target risk distribution (30 patients)
---------------------------------------
  High   (>=2.0)  : ~6  patients
  Medium (1.0-1.99): ~12 patients
  Low    (<1.0)   : ~9  patients
  Unscored        : ~3  patients  (no raf_scores row inserted)

All seeded rows are tagged so they can be purged:
  raf_patient_hcc.source_encounter_ids  LIKE '%OPENEMR_COHORT%'
  raf_patient_demographics rows have no dedicated tag column but are keyed
  on (patient_id, measurement_year) — deleting via patient list is sufficient.

Purge command:
  DELETE FROM raf_patient_hcc    WHERE source_encounter_ids LIKE '%OPENEMR_COHORT%';
  DELETE FROM raf_scores         WHERE model_version = 'V28_COHORT_SEED';
  DELETE FROM normalized_encounters WHERE encounter_id LIKE 'COHORT_enc_%';

Refuses to run unless APP_ENV is development / demo.
"""
from __future__ import annotations

import json
import os
import random
import sys
from datetime import date, timedelta
from typing import Any

sys.path.insert(0, "/app")
from app.db import raf_cursor  # noqa: E402

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

COHORT_TAG = "OPENEMR_COHORT"
TENANT_ID = "1"
DEMO_YEAR = date.today().year
PRIOR_YEAR = DEMO_YEAR - 1

# Must match the demo provider seeded by seed_demo_panel.py
DEMO_PROVIDER_NPI = "1234567890"

# RNG seed for deterministic output across re-runs
_RNG_SEED = 42

# (icd10, hcc_code, label, raf_coefficient)
# Sourced from CMS-HCC V28 coefficient table (informational, not CMS-validated).
PRIOR_YEAR_HCCS = [
    ("E11.65",  19,  "Diabetes with hyperglycemia",         0.302),
    ("J44.9",   111, "COPD, unspecified",                   0.347),
    ("I50.9",   85,  "Heart failure, unspecified",           0.331),
    ("N18.4",   138, "CKD stage 4",                         0.421),
    ("F03.90",  52,  "Dementia, unspecified",               0.305),
    ("D63.8",   48,  "Anemia in chronic disease",           0.245),
    ("Z99.81",  84,  "Dependence on supplemental O2",       0.288),
    ("R65.20",  2,   "Severe sepsis",                       0.435),
    ("M06.9",   40,  "Rheumatoid arthritis",                0.288),
    ("C50.911", 12,  "Breast cancer",                       0.150),
    ("I21.9",   86,  "Acute MI, unspecified",               0.398),
    ("G20",     77,  "Parkinson disease",                   0.335),
    ("E13.65",  19,  "Other specified diabetes mellitus",   0.302),
    ("N18.3",   137, "CKD stage 3",                         0.189),
    ("I10",     89,  "Essential hypertension",              0.140),
]

CURRENT_YEAR_HCCS = [
    ("E11.65",  19,  "Diabetes with hyperglycemia",         0.302),
    ("J44.9",   111, "COPD, unspecified",                   0.347),
    ("I50.9",   85,  "Heart failure, unspecified",           0.331),
    ("N18.4",   138, "CKD stage 4",                         0.421),
    ("M06.9",   40,  "Rheumatoid arthritis",                0.288),
    ("I10",     89,  "Essential hypertension",              0.140),
    ("G20",     77,  "Parkinson disease",                   0.335),
]

# Demographic RAF contribution by age band and sex (approximate CMS model)
DEMO_RAF_TABLE: dict[str, float] = {
    "35-44": 0.198,
    "45-54": 0.282,
    "55-59": 0.335,
    "60-64": 0.399,
    "65-69": 0.440,
    "70-74": 0.493,
    "75-79": 0.552,
    "80-84": 0.619,
    "85-89": 0.710,
    "90-94": 0.792,
    "95+":   0.874,
}

# Age bands available for synthetic demo assignment
AGE_BANDS = [
    "65-69", "70-74", "70-74", "75-79", "75-79",
    "80-84", "85-89", "60-64", "55-59", "70-74",
]

SEXES = ["F", "M", "F", "M", "F", "F", "M", "F", "M", "M"]

# dual_status: 0=non-dual, 1=dual
DUAL_STATUS_PATTERN = [0, 0, 1, 0, 0, 1, 0, 0, 0, 1]


# ---------------------------------------------------------------------------
# Schema migration helpers (idempotent)
# ---------------------------------------------------------------------------


def _ensure_raf_scores_tenant_id(cur: Any) -> None:
    """Add tenant_id column to raf_scores if it is missing.

    The column is required by the dashboard stats query:
        WHERE raf_scores.tenant_id = %s
    This is a lightweight schema migration — safe to run repeatedly because
    MySQL ignores the ADD COLUMN when the column already exists (caught below).
    """
    try:
        cur.execute(
            "ALTER TABLE raf_scores ADD COLUMN tenant_id VARCHAR(64) NOT NULL DEFAULT '1'"
        )
        cur.execute("ALTER TABLE raf_scores ADD KEY idx_raf_scores_tenant (tenant_id)")
    except Exception:
        pass  # Column already exists — no-op


def _ensure_raf_scores_model_version(cur: Any) -> None:
    """Add model_version column to raf_scores for purgeability tagging."""
    try:
        cur.execute(
            "ALTER TABLE raf_scores ADD COLUMN model_version VARCHAR(40) DEFAULT NULL"
        )
    except Exception:
        pass  # Column already exists — no-op


# ---------------------------------------------------------------------------
# Guard
# ---------------------------------------------------------------------------


def _ensure_demo_environment() -> None:
    env = os.environ.get("APP_ENV", "").lower()
    if env not in {"development", "demo", "dev"}:
        raise SystemExit(
            f"Refusing to seed with APP_ENV={env!r}. "
            "Set APP_ENV=development or APP_ENV=demo."
        )


# ---------------------------------------------------------------------------
# Patient fetch
# ---------------------------------------------------------------------------


def _fetch_all_openemr_patients(cur: Any) -> dict[int, str]:
    """Return ALL patients from openemr.patient_data ordered by pid."""
    cur.execute(
        """
        SELECT pid, fname, lname
        FROM openemr.patient_data
        ORDER BY pid ASC
        LIMIT 30
        """
    )
    return {row["pid"]: f"{row['fname']} {row['lname']}" for row in cur.fetchall()}


# ---------------------------------------------------------------------------
# Demographics
# ---------------------------------------------------------------------------


def _seed_demographics(cur: Any, patients: dict[int, str]) -> None:
    """Insert varied demographics for all 30 patients, both prior and current year.

    Uses a deterministic pattern so the distribution is stable across re-runs.
    ON DUPLICATE KEY UPDATE is used for idempotency — the unique key is
    (patient_id, measurement_year) on raf_patient_demographics.

    Note: raf_patient_demographics has no tenant_id column in the base schema.
    """
    rng = random.Random(_RNG_SEED)
    for idx, pid in enumerate(patients):
        age_band = AGE_BANDS[idx % len(AGE_BANDS)]
        sex = SEXES[idx % len(SEXES)]
        dual = DUAL_STATUS_PATTERN[idx % len(DUAL_STATUS_PATTERN)]
        dual_type = "dual_full" if dual else "non_dual"
        orec = "1" if rng.random() < 0.15 else "0"  # ~15% disabled

        for yr in (PRIOR_YEAR, DEMO_YEAR):
            cur.execute(
                """
                INSERT INTO raf_patient_demographics
                    (patient_id, measurement_year, age_band, sex,
                     dual_status, dual_type, disabled, orec,
                     institutional, enrollment_source, model_segment)
                VALUES (%s, %s, %s, %s,
                        %s, %s, %s, %s,
                        0, 'derived', 'CNA')
                ON DUPLICATE KEY UPDATE
                    age_band    = VALUES(age_band),
                    sex         = VALUES(sex),
                    dual_status = VALUES(dual_status),
                    dual_type   = VALUES(dual_type),
                    disabled    = VALUES(disabled),
                    orec        = VALUES(orec)
                """,
                (pid, yr, age_band, sex, dual, dual_type,
                 1 if orec == "1" else 0, orec),
            )


# ---------------------------------------------------------------------------
# HCC seeding — stratified by target risk tier
# ---------------------------------------------------------------------------


def _compute_prior_hcc_budget(tier: str, rng: random.Random) -> list[tuple]:
    """Return a list of (icd10, hcc_code, label, raf_coef) for prior year based on tier."""
    if tier == "high":
        # 4-5 prior-year HCCs from high-coefficient pool
        n = rng.randint(4, 5)
        pool = sorted(PRIOR_YEAR_HCCS, key=lambda x: -x[3])  # highest coef first
        return rng.sample(pool[:8], n)
    elif tier == "medium":
        # 2-3 prior-year HCCs from mid-coefficient pool
        n = rng.randint(2, 3)
        return rng.sample(PRIOR_YEAR_HCCS, n)
    else:  # low
        # 1-2 prior-year HCCs from lower-coefficient pool
        n = rng.randint(1, 2)
        pool = sorted(PRIOR_YEAR_HCCS, key=lambda x: x[3])  # lowest coef first
        return rng.sample(pool[:8], n)


def _compute_current_hcc_budget(
    tier: str, prior_hccs: list[tuple], rng: random.Random
) -> list[tuple]:
    """Return current-year HCCs — some re-captured, some new, creating gaps."""
    if tier == "high":
        # High-risk: re-capture most prior HCCs + add new ones
        recapture = rng.sample(prior_hccs, min(len(prior_hccs), rng.randint(2, 3)))
        extras = [h for h in CURRENT_YEAR_HCCS if h not in recapture]
        new_cy = rng.sample(extras, min(len(extras), rng.randint(1, 2)))
        return list(recapture) + new_cy
    elif tier == "medium":
        # Medium-risk: re-capture some prior HCCs, leave some as gaps
        n_recapture = max(1, len(prior_hccs) - 1)
        return rng.sample(prior_hccs, n_recapture)
    else:  # low
        # Low-risk: capture zero or one prior HCC (rest are gaps)
        if rng.random() < 0.5 and prior_hccs:
            return [rng.choice(prior_hccs)]
        return []


def _seed_hccs_for_patient(
    cur: Any,
    pid: int,
    prior_hccs: list[tuple],
    current_hccs: list[tuple],
) -> None:
    """Upsert prior-year and current-year HCCs for a single patient."""
    # Prior year HCCs
    for icd, hcc, label, raf in prior_hccs:
        cur.execute(
            """
            INSERT INTO raf_patient_hcc
                (patient_id, measurement_year, hcc_code, icd10_codes,
                 source_encounter_ids, raf_coefficient, meat_status,
                 model_version, tenant_id)
            VALUES (%s, %s, %s, %s, %s, %s, 'complete', 'V28', %s)
            ON DUPLICATE KEY UPDATE
                icd10_codes         = VALUES(icd10_codes),
                raf_coefficient     = VALUES(raf_coefficient),
                source_encounter_ids = VALUES(source_encounter_ids),
                tenant_id           = VALUES(tenant_id)
            """,
            (
                pid, PRIOR_YEAR, hcc,
                json.dumps([icd]),
                json.dumps([f"COHORT_enc_{pid}_py", COHORT_TAG]),
                raf, TENANT_ID,
            ),
        )

    # Current year HCCs
    for icd, hcc, label, raf in current_hccs:
        cur.execute(
            """
            INSERT INTO raf_patient_hcc
                (patient_id, measurement_year, hcc_code, icd10_codes,
                 source_encounter_ids, raf_coefficient, meat_status,
                 model_version, tenant_id)
            VALUES (%s, %s, %s, %s, %s, %s, 'complete', 'V28', %s)
            ON DUPLICATE KEY UPDATE
                icd10_codes         = VALUES(icd10_codes),
                raf_coefficient     = VALUES(raf_coefficient),
                source_encounter_ids = VALUES(source_encounter_ids),
                tenant_id           = VALUES(tenant_id)
            """,
            (
                pid, DEMO_YEAR, hcc,
                json.dumps([icd]),
                json.dumps([f"COHORT_enc_{pid}_cy", COHORT_TAG]),
                raf, TENANT_ID,
            ),
        )


# ---------------------------------------------------------------------------
# RAF score insertion
# ---------------------------------------------------------------------------


def _seed_raf_score(
    cur: Any,
    pid: int,
    prior_hccs: list[tuple],
    current_hccs: list[tuple],
    age_band: str,
    rng: random.Random,
    has_tenant_id: bool = False,
    has_model_version: bool = False,
) -> float:
    """Insert a raf_scores row. Returns final_raf.

    final_raf = demographic_raf + sum(current_year hcc raf_coefficients)
    If no current HCCs, use prior-year coefficients with a decay factor.

    Dynamically adapts INSERT to include tenant_id / model_version only if
    those columns exist (detected by caller via _ensure_* helpers).
    """
    demo_raf = DEMO_RAF_TABLE.get(age_band, 0.440)
    # Add small noise to demo_raf so values aren't identical across same age bands
    demo_raf = round(demo_raf + rng.uniform(-0.02, 0.02), 4)

    if current_hccs:
        disease_raf = round(sum(h[3] for h in current_hccs), 4)
    elif prior_hccs:
        # No current HCCs — use prior-year with ~60% persistence factor
        disease_raf = round(sum(h[3] for h in prior_hccs) * 0.60, 4)
    else:
        disease_raf = 0.0

    final_raf = round(demo_raf + disease_raf, 4)
    hcc_count = len(current_hccs) if current_hccs else len(prior_hccs)

    # Determine risk_tier for the risk_tier column
    if final_raf >= 2.0:
        risk_tier = "high"
    elif final_raf >= 1.0:
        risk_tier = "moderate"
    else:
        risk_tier = "low"

    # Build the INSERT dynamically so we work with both old and migrated schemas
    extra_cols = ["risk_tier"]
    extra_vals: list = [risk_tier]
    extra_updates = ["risk_tier = VALUES(risk_tier)"]

    if has_tenant_id:
        extra_cols.append("tenant_id")
        extra_vals.append(TENANT_ID)
        extra_updates.append("tenant_id = VALUES(tenant_id)")

    if has_model_version:
        extra_cols.append("model_version")
        extra_vals.append("V28_COHORT_SEED")
        extra_updates.append("model_version = VALUES(model_version)")

    cols_str = ", ".join(extra_cols)
    placeholders = ", ".join(["%s"] * len(extra_cols))
    updates_str = ",\n                    ".join(extra_updates)

    cur.execute(
        f"""
        INSERT INTO raf_scores
            (patient_id, measurement_year, score_type, model_segment,
             demographic_score, disease_score, interaction_score,
             total_raw, normalization_factor, final_raf, hcc_count,
             calculated_at, {cols_str})
        VALUES (%s, %s, 'prospective', 'CNA',
                %s, %s, 0.0000,
                %s, 1.0000, %s, %s,
                NOW(), {placeholders})
        ON DUPLICATE KEY UPDATE
            demographic_score = VALUES(demographic_score),
            disease_score     = VALUES(disease_score),
            total_raw         = VALUES(total_raw),
            final_raf         = VALUES(final_raf),
            hcc_count         = VALUES(hcc_count),
            calculated_at     = NOW(),
            {updates_str}
        """,
        (pid, DEMO_YEAR, demo_raf, disease_raf, final_raf, final_raf, hcc_count, *extra_vals),
    )
    return final_raf


# ---------------------------------------------------------------------------
# Normalized encounters (required for worklist subquery)
# ---------------------------------------------------------------------------


def _ensure_normalized_encounters_table(cur: Any) -> None:
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
    """Seed two encounters per patient linked to DEMO_PROVIDER_NPI."""
    prior_year_date = date(PRIOR_YEAR, 6, 10)
    current_year_date = date(DEMO_YEAR, 1, 15)

    for pid in patients:
        for enc_date, enc_id in [
            (prior_year_date,   f"COHORT_enc_{pid}_py"),
            (current_year_date, f"COHORT_enc_{pid}_cy"),
        ]:
            cur.execute(
                """
                INSERT IGNORE INTO normalized_encounters
                    (encounter_id, patient_id, tenant_id,
                     provider_npi, encounter_date, encounter_type,
                     facility_name, is_demo)
                VALUES (%s, %s, %s, %s, %s, 'office_visit', 'OpenEMR Clinic', 1)
                """,
                (enc_id, pid, TENANT_ID, DEMO_PROVIDER_NPI, enc_date),
            )


# ---------------------------------------------------------------------------
# Main orchestration
# ---------------------------------------------------------------------------


def _check_column_exists(cur: Any, table: str, column: str) -> bool:
    """Return True if the given column exists on the table in current DB."""
    cur.execute(
        """
        SELECT COUNT(*) AS cnt
        FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE()
          AND TABLE_NAME = %s
          AND COLUMN_NAME = %s
        """,
        (table, column),
    )
    row = cur.fetchone()
    return bool(row and row.get("cnt", 0))


def main() -> None:
    _ensure_demo_environment()

    rng = random.Random(_RNG_SEED)

    with raf_cursor() as cur:
        patients = _fetch_all_openemr_patients(cur)

    if not patients:
        raise SystemExit("No patients found in openemr.patient_data. Is the OpenEMR DB seeded?")

    n = len(patients)
    pids = list(patients.keys())
    print(f"Found {n} patients in openemr.patient_data")

    # ---------------------------------------------------------------------------
    # Schema migrations — add missing columns to raf_scores so dashboard queries work
    # ---------------------------------------------------------------------------
    with raf_cursor() as cur:
        _ensure_raf_scores_tenant_id(cur)
        _ensure_raf_scores_model_version(cur)

    # Detect whether columns now exist (they may have existed before)
    with raf_cursor() as cur:
        has_tenant_id = _check_column_exists(cur, "raf_scores", "tenant_id")
        has_model_version = _check_column_exists(cur, "raf_scores", "model_version")

    print(f"  raf_scores.tenant_id    : {'present' if has_tenant_id else 'MISSING'}")
    print(f"  raf_scores.model_version: {'present' if has_model_version else 'MISSING'}")

    # If tenant_id was just added, backfill existing rows with default '1'
    if has_tenant_id:
        with raf_cursor() as cur:
            cur.execute(
                "UPDATE raf_scores SET tenant_id = '1' WHERE tenant_id IS NULL OR tenant_id = ''"
            )

    # ---------------------------------------------------------------------------
    # Assign risk tiers to achieve target distribution:
    #   high (~6), medium (~12), low (~9), unscored (~3)
    # We assign deterministically by index so re-runs produce identical buckets.
    # ---------------------------------------------------------------------------
    tier_sequence: list[str] = []
    # ~20% high, ~40% medium, ~30% low, ~10% unscored
    for i in range(n):
        r = i % 10
        if r < 2:
            tier_sequence.append("high")
        elif r < 6:
            tier_sequence.append("medium")
        elif r < 9:
            tier_sequence.append("low")
        else:
            tier_sequence.append("unscored")

    # Shuffle tier order slightly so high-risk patients aren't all at top of list
    rng_tier = random.Random(99)
    rng_tier.shuffle(tier_sequence)

    tier_counts: dict[str, int] = {"high": 0, "medium": 0, "low": 0, "unscored": 0}
    scored_finals: list[float] = []

    # Seed demographics, HCCs, scores in a single transaction per patient
    age_band_cycle = AGE_BANDS * (n // len(AGE_BANDS) + 1)

    with raf_cursor() as cur:
        _ensure_normalized_encounters_table(cur)

    with raf_cursor() as cur:
        _seed_demographics(cur, patients)

    with raf_cursor() as cur:
        _seed_normalized_encounters(cur, patients)

    for idx, pid in enumerate(pids):
        tier = tier_sequence[idx]
        age_band = age_band_cycle[idx]

        if tier == "unscored":
            tier_counts["unscored"] += 1
            print(f"  pid={pid:4d}  [{tier:8s}]  — no RAF score (intentional gap)")
            continue

        prior_hccs = _compute_prior_hcc_budget(tier, rng)
        current_hccs = _compute_current_hcc_budget(tier, prior_hccs, rng)

        with raf_cursor() as cur:
            _seed_hccs_for_patient(cur, pid, prior_hccs, current_hccs)

        with raf_cursor() as cur:
            final_raf = _seed_raf_score(
                cur, pid, prior_hccs, current_hccs, age_band, rng,
                has_tenant_id=has_tenant_id,
                has_model_version=has_model_version,
            )

        tier_counts[tier] += 1
        scored_finals.append(final_raf)
        print(
            f"  pid={pid:4d}  [{tier:8s}]  final_raf={final_raf:.4f}  "
            f"prior_hccs={len(prior_hccs)}  cy_hccs={len(current_hccs)}"
        )

    # ---------------------------------------------------------------------------
    # Summary
    # ---------------------------------------------------------------------------
    avg_raf = round(sum(scored_finals) / len(scored_finals), 4) if scored_finals else 0.0
    print()
    print("=" * 60)
    print(f"Cohort scoring complete — {n} patients")
    print(f"  High   (>=2.0) : {tier_counts['high']}")
    print(f"  Medium (1.0-1.99): {tier_counts['medium']}")
    print(f"  Low    (<1.0)  : {tier_counts['low']}")
    print(f"  Unscored       : {tier_counts['unscored']}")
    print(f"  Average RAF (scored patients): {avg_raf}")
    print()
    print("Verify via API:")
    print("  curl -s http://localhost:8000/api/dashboard/stats | python3 -m json.tool")
    print("  curl -s 'http://localhost:8000/api/patients?limit=30' | python3 -m json.tool")
    print()
    print("Purge with:")
    print(f"  DELETE FROM raf_patient_hcc    WHERE source_encounter_ids LIKE '%{COHORT_TAG}%';")
    print(f"  DELETE FROM raf_scores         WHERE model_version = 'V28_COHORT_SEED';")
    print(f"  DELETE FROM normalized_encounters WHERE encounter_id LIKE 'COHORT_enc_%';")


if __name__ == "__main__":
    main()
