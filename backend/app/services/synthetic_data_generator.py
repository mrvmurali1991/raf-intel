"""
Synthetic patient data generator for RAF Intelligence demo mode.

Creates 25 realistic but clearly fake patients tagged with ``is_demo=1`` so
they can be identified and are never confused with real PHI.  All data lives
in the RAF Intelligence database:

  - Shadow OpenEMR tables (patient_data, form_encounter, billing) are created
    inside the RAF DB so that ``openemr_cursor()`` can serve them when the
    active EMR connection is the demo connection.
  - RAF analytics tables (raf_scores, raf_patient_hcc, raf_patient_demographics)
    are populated with pre-computed scores.

The generator is **idempotent**: if a demo EMR connection already exists *and*
synthetic patients already exist it returns the current stats without
re-inserting rows.

Usage
-----
    from app.services.synthetic_data_generator import generate_synthetic_data
    stats = generate_synthetic_data()
    # {"patients_created": 25, "encounters_created": 75, "is_demo": True}
"""
from __future__ import annotations

import json
import logging
import random
from datetime import date, timedelta
from typing import Any

from app.config import settings
from app.db import raf_cursor

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Seed for reproducibility
# ---------------------------------------------------------------------------

_RNG = random.Random(42)

# ---------------------------------------------------------------------------
# Patient pool — names intentionally include "Demo-" prefix
# ---------------------------------------------------------------------------

_FIRST_NAMES_F = [
    "Sarah", "Maria", "Patricia", "Linda", "Barbara",
    "Elizabeth", "Jennifer", "Margaret", "Susan", "Dorothy",
    "Betty", "Sandra", "Ashley", "Kimberly", "Carol",
]
_FIRST_NAMES_M = [
    "James", "Robert", "John", "Michael", "William",
    "David", "Richard", "Joseph", "Thomas", "Charles",
    "Christopher", "Daniel", "Paul", "George", "Kenneth",
]
_LAST_NAMES = [
    "Johnson", "Williams", "Brown", "Jones", "Garcia",
    "Miller", "Davis", "Rodriguez", "Martinez", "Hernandez",
    "Lopez", "Gonzalez", "Wilson", "Anderson", "Thomas",
    "Taylor", "Moore", "Jackson", "Martin", "Lee",
    "Perez", "Thompson", "White", "Harris", "Sanchez",
]

_CITIES = [
    ("Los Angeles", "CA", "90001"),
    ("Chicago", "IL", "60601"),
    ("Houston", "TX", "77001"),
    ("Phoenix", "AZ", "85001"),
    ("Philadelphia", "PA", "19101"),
    ("San Antonio", "TX", "78201"),
    ("San Diego", "CA", "92101"),
    ("Dallas", "TX", "75201"),
    ("Jacksonville", "FL", "32201"),
    ("Austin", "TX", "78701"),
]

_STREETS = [
    "123 Maple St", "456 Oak Ave", "789 Pine Rd", "321 Elm Dr",
    "654 Cedar Blvd", "987 Birch Ln", "111 Walnut Ct", "222 Ash Way",
    "333 Spruce Pl", "444 Willow Terr",
]

# ---------------------------------------------------------------------------
# ICD-10 code pool grouped by HCC category
# ---------------------------------------------------------------------------

_ICD_POOL: list[tuple[str, str]] = [
    # Diabetes
    ("E11.9",  "Type 2 diabetes mellitus without complications"),
    ("E11.65", "Type 2 diabetes mellitus with hyperglycemia"),
    ("E11.22", "Type 2 diabetes mellitus with diabetic CKD stage 2"),
    # CHF
    ("I50.9",  "Heart failure, unspecified"),
    ("I50.22", "Chronic systolic (congestive) heart failure"),
    ("I50.32", "Chronic diastolic (congestive) heart failure"),
    # CKD
    ("N18.3",  "Chronic kidney disease, stage 3"),
    ("N18.4",  "Chronic kidney disease, stage 4"),
    ("N18.5",  "Chronic kidney disease, stage 5"),
    # COPD
    ("J44.1",  "COPD with acute exacerbation"),
    ("J44.0",  "COPD with acute lower respiratory infection"),
    # Depression
    ("F32.1",  "Major depressive disorder, single episode, moderate"),
    ("F33.0",  "Major depressive disorder, recurrent, mild"),
    # Obesity
    ("E66.01", "Morbid (severe) obesity due to excess calories"),
    # Atrial Fibrillation
    ("I48.91", "Unspecified atrial fibrillation"),
    # Vascular Disease
    ("I73.9",  "Peripheral vascular disease, unspecified"),
]

# HCC number approximations (V28 model) for RAF score estimation
_ICD_HCC_MAP: dict[str, int] = {
    "E11.9": 37,  "E11.65": 37,  "E11.22": 37,
    "I50.9": 85,  "I50.22": 85,  "I50.32": 85,
    "N18.3": 138, "N18.4": 137,  "N18.5": 136,
    "J44.1": 112, "J44.0": 112,
    "F32.1": 155, "F33.0": 155,
    "E66.01": 48,
    "I48.91": 96,
    "I73.9": 108,
}

# Rough per-HCC coefficient for estimating RAF
_HCC_COEFF: dict[int, float] = {
    37: 0.302, 85: 0.340, 138: 0.108, 137: 0.290, 136: 0.441,
    112: 0.335, 155: 0.309, 48: 0.272, 96: 0.288, 108: 0.288,
}

# ---------------------------------------------------------------------------
# Encounter type labels
# ---------------------------------------------------------------------------

_ENCOUNTER_TYPES = [
    "Office Visit",
    "Annual Wellness Visit",
    "Follow-up",
    "Telehealth",
    "Specialist Consultation",
]

# ---------------------------------------------------------------------------
# DDL helpers — shadow OpenEMR tables inside the RAF DB
# ---------------------------------------------------------------------------

_SHADOW_TABLE_DDL = [
    """
    CREATE TABLE IF NOT EXISTS patient_data (
        pid           INT AUTO_INCREMENT PRIMARY KEY,
        fname         VARCHAR(100) NOT NULL DEFAULT '',
        lname         VARCHAR(100) NOT NULL DEFAULT '',
        mname         VARCHAR(100) DEFAULT NULL,
        DOB           DATE,
        sex           VARCHAR(25) DEFAULT '',
        race          VARCHAR(100) DEFAULT '',
        ethnicity     VARCHAR(100) DEFAULT '',
        street        VARCHAR(255) DEFAULT '',
        city          VARCHAR(100) DEFAULT '',
        state         VARCHAR(50) DEFAULT '',
        postal_code   VARCHAR(20) DEFAULT '',
        phone_home    VARCHAR(30) DEFAULT '',
        phone_cell    VARCHAR(30) DEFAULT '',
        email         VARCHAR(255) DEFAULT '',
        providerID    INT DEFAULT NULL,
        date          DATETIME DEFAULT CURRENT_TIMESTAMP,
        is_demo       TINYINT(1) NOT NULL DEFAULT 0,
        INDEX idx_lname_fname (lname, fname),
        INDEX idx_is_demo (is_demo)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
    """
    CREATE TABLE IF NOT EXISTS form_encounter (
        encounter    INT AUTO_INCREMENT PRIMARY KEY,
        pid          INT NOT NULL,
        date         DATETIME NOT NULL,
        reason       VARCHAR(255) DEFAULT '',
        facility     VARCHAR(255) DEFAULT 'Demo Clinic',
        pos_code     VARCHAR(10) DEFAULT '11',
        class_code   VARCHAR(20) DEFAULT 'AMB',
        is_demo      TINYINT(1) NOT NULL DEFAULT 0,
        INDEX idx_pid (pid),
        INDEX idx_date (date),
        INDEX idx_is_demo (is_demo)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
    """
    CREATE TABLE IF NOT EXISTS billing (
        id            INT AUTO_INCREMENT PRIMARY KEY,
        pid           INT NOT NULL,
        encounter     INT NOT NULL,
        code_type     VARCHAR(20) NOT NULL DEFAULT 'ICD10',
        code          VARCHAR(20) NOT NULL,
        code_text     VARCHAR(255) DEFAULT '',
        activity      TINYINT(1) NOT NULL DEFAULT 1,
        is_demo       TINYINT(1) NOT NULL DEFAULT 0,
        INDEX idx_pid (pid),
        INDEX idx_encounter (encounter),
        INDEX idx_code_type (code_type),
        INDEX idx_is_demo (is_demo)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
]

# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def generate_synthetic_data() -> dict[str, Any]:
    """Generate 25 synthetic demo patients and register a demo EMR connection.

    Returns
    -------
    dict with keys:
        patients_created  – number of patient rows inserted (0 if already existed)
        encounters_created – number of encounter rows inserted
        is_demo           – always True
    """
    _ensure_shadow_tables()

    if _demo_data_exists():
        logger.info("synthetic_data_generator: demo data already present — skipping")
        stats = _current_stats()
        stats["is_demo"] = True
        return stats

    patients_created = 0
    encounters_created = 0

    patients = _build_patients()
    today = date.today()
    measurement_year = today.year

    for p in patients:
        pid = _insert_patient(p)
        if pid is None:
            continue
        patients_created += 1

        # Insert encounters and billing codes
        n_encounters = _RNG.randint(2, 4)
        encounter_ids: list[int] = []
        for _ in range(n_encounters):
            days_back = _RNG.randint(1, 365)
            enc_date = today - timedelta(days=days_back)
            enc_id = _insert_encounter(pid, enc_date)
            if enc_id is not None:
                encounter_ids.append(enc_id)
                encounters_created += 1

        # Attach ICD codes to encounters (spread across encounters)
        icd_codes = p["icd_codes"]
        for idx, (code, code_text) in enumerate(icd_codes):
            enc_id = encounter_ids[idx % len(encounter_ids)] if encounter_ids else None
            if enc_id:
                _insert_billing(pid, enc_id, code, code_text)

        # Pre-compute and store RAF analytics
        _store_raf_data(pid, icd_codes, p["age"], p["sex"], measurement_year)

    _ensure_demo_emr_connection()

    logger.info(
        "synthetic_data_generator: created %d patients, %d encounters",
        patients_created,
        encounters_created,
    )
    return {
        "patients_created": patients_created,
        "encounters_created": encounters_created,
        "is_demo": True,
    }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _ensure_shadow_tables() -> None:
    """Create shadow OpenEMR tables inside the RAF DB if they don't exist."""
    with raf_cursor() as cur:
        for ddl in _SHADOW_TABLE_DDL:
            cur.execute(ddl)


def _demo_data_exists() -> bool:
    """Return True if demo patients already exist in patient_data."""
    try:
        with raf_cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) AS cnt FROM patient_data WHERE is_demo = 1",
            )
            row = cur.fetchone()
            return (row["cnt"] if row else 0) >= 25
    except Exception:  # noqa: BLE001 — best-effort guard
        logger.debug("swallowed exception", exc_info=True)
        return False


def _current_stats() -> dict[str, Any]:
    """Return row counts for existing demo data."""
    try:
        with raf_cursor() as cur:
            cur.execute("SELECT COUNT(*) AS cnt FROM patient_data WHERE is_demo = 1")
            p_row = cur.fetchone()
            cur.execute("SELECT COUNT(*) AS cnt FROM form_encounter WHERE is_demo = 1")
            e_row = cur.fetchone()
        return {
            "patients_created": p_row["cnt"] if p_row else 0,
            "encounters_created": e_row["cnt"] if e_row else 0,
        }
    except Exception:
        logger.debug("swallowed exception", exc_info=True)
        return {"patients_created": 0, "encounters_created": 0}


def _build_patients() -> list[dict[str, Any]]:
    """Build a list of 25 synthetic patient dicts."""
    patients: list[dict[str, Any]] = []
    used_names: set[str] = set()

    sexes = (["F"] * 13) + (["M"] * 12)
    _RNG.shuffle(sexes)

    for i in range(25):
        sex = sexes[i]
        first_pool = _FIRST_NAMES_F if sex == "F" else _FIRST_NAMES_M

        for attempt in range(100):
            fname = _RNG.choice(first_pool)
            lname = _RNG.choice(_LAST_NAMES)
            key = f"{fname}-{lname}"
            if key not in used_names:
                used_names.add(key)
                break
        else:
            fname = f"Demo{i}"
            lname = _LAST_NAMES[i % len(_LAST_NAMES)]

        age = _RNG.randint(25, 85)
        birth_year = date.today().year - age
        dob = date(birth_year, _RNG.randint(1, 12), _RNG.randint(1, 28))

        city, state, postal = _RNG.choice(_CITIES)
        street = _RNG.choice(_STREETS)

        n_codes = _RNG.randint(2, 5)
        icd_codes = _RNG.sample(_ICD_POOL, n_codes)

        patients.append({
            "fname": f"Demo-{fname}",
            "lname": lname,
            "dob": dob,
            "sex": sex,
            "age": age,
            "street": street,
            "city": city,
            "state": state,
            "postal_code": postal,
            "phone_home": f"555-{_RNG.randint(100, 999)}-{_RNG.randint(1000, 9999)}",
            "phone_cell": f"555-{_RNG.randint(100, 999)}-{_RNG.randint(1000, 9999)}",
            "email": f"demo.{fname.lower()}.{lname.lower()}@demo-health.example",
            "icd_codes": icd_codes,
        })

    return patients


def _insert_patient(p: dict[str, Any]) -> int | None:
    """Insert a patient row and return the new pid."""
    try:
        with raf_cursor() as cur:
            cur.execute(
                """
                INSERT INTO patient_data
                    (fname, lname, DOB, sex, street, city, state, postal_code,
                     phone_home, phone_cell, email, is_demo)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 1)
                """,
                (
                    p["fname"], p["lname"], p["dob"].isoformat(), p["sex"],
                    p["street"], p["city"], p["state"], p["postal_code"],
                    p["phone_home"], p["phone_cell"], p["email"],
                ),
            )
            return cur.lastrowid
    except Exception as exc:
        logger.warning("synthetic_data_generator: insert patient failed: %s", exc)
        return None


def _insert_encounter(pid: int, enc_date: date) -> int | None:
    """Insert an encounter row and return the new encounter id."""
    reason = _RNG.choice(_ENCOUNTER_TYPES)
    try:
        with raf_cursor() as cur:
            cur.execute(
                """
                INSERT INTO form_encounter
                    (pid, date, reason, facility, pos_code, class_code, is_demo)
                VALUES (%s, %s, %s, 'Demo Clinic', '11', 'AMB', 1)
                """,
                (pid, enc_date.isoformat(), reason),
            )
            return cur.lastrowid
    except Exception as exc:
        logger.warning("synthetic_data_generator: insert encounter failed: %s", exc)
        return None


def _insert_billing(pid: int, encounter_id: int, code: str, code_text: str) -> None:
    """Insert a billing/ICD-10 row."""
    try:
        with raf_cursor() as cur:
            cur.execute(
                """
                INSERT INTO billing
                    (pid, encounter, code_type, code, code_text, activity, is_demo)
                VALUES (%s, %s, 'ICD10', %s, %s, 1, 1)
                """,
                (pid, encounter_id, code, code_text),
            )
    except Exception as exc:
        logger.warning("synthetic_data_generator: insert billing failed: %s", exc)


def _store_raf_data(
    pid: int,
    icd_codes: list[tuple[str, str]],
    age: int,
    sex: str,
    measurement_year: int,
) -> None:
    """Store pre-computed RAF score, HCC codes, and demographics in RAF tables."""
    codes = [c for c, _ in icd_codes]
    hcc_set: set[int] = set()
    for code in codes:
        hcc = _ICD_HCC_MAP.get(code)
        if hcc:
            hcc_set.add(hcc)

    # Build RAF score from sum of HCC coefficients + demographic base (0.35)
    demographic_score = 0.35
    disease_score = sum(_HCC_COEFF.get(h, 0.28) for h in hcc_set)
    total_raw = demographic_score + disease_score
    # Clamp to realistic range 0.5 – 3.5
    final_raf = max(0.50, min(3.50, total_raw))
    hcc_count = len(hcc_set)

    model_segment = "CNA" if age >= 65 else "CND"

    try:
        with raf_cursor() as cur:
            # Demographics
            age_band = _age_band(age)
            cur.execute(
                """
                INSERT INTO raf_patient_demographics
                    (patient_id, measurement_year, age_band, sex,
                     dual_status, dual_type, disabled, orec,
                     institutional, enrollment_source, model_segment)
                VALUES (%s, %s, %s, %s, 0, 'non_dual', 0, '0', 0, 'demo', %s)
                ON DUPLICATE KEY UPDATE
                    age_band = VALUES(age_band),
                    sex = VALUES(sex),
                    model_segment = VALUES(model_segment),
                    updated_at = NOW()
                """,
                (pid, measurement_year, age_band, sex, model_segment),
            )

            # HCC codes
            cur.execute(
                "DELETE FROM raf_patient_hcc WHERE patient_id = %s AND measurement_year = %s",
                (pid, measurement_year),
            )
            for hcc in hcc_set:
                related = [c for c in codes if _ICD_HCC_MAP.get(c) == hcc]
                coeff = _HCC_COEFF.get(hcc, 0.28)
                cur.execute(
                    """
                    INSERT INTO raf_patient_hcc
                        (patient_id, measurement_year, hcc_code, icd10_codes,
                         source_encounter_ids, raf_coefficient, meat_status, model_version)
                    VALUES (%s, %s, %s, %s, '[]', %s, 'demo', 'V28')
                    ON DUPLICATE KEY UPDATE
                        icd10_codes = VALUES(icd10_codes),
                        raf_coefficient = VALUES(raf_coefficient),
                        model_version = VALUES(model_version)
                    """,
                    (pid, measurement_year, hcc, json.dumps(related), coeff),
                )

            # RAF score
            cur.execute(
                """
                INSERT INTO raf_scores (
                    patient_id, measurement_year, score_type, model_segment,
                    demographic_score, disease_score, interaction_score,
                    total_raw, normalization_factor, final_raf,
                    hcc_count, calculated_at
                ) VALUES (
                    %s, %s, 'v28', %s,
                    %s, %s, 0.0,
                    %s, 1.0, %s,
                    %s, NOW()
                )
                ON DUPLICATE KEY UPDATE
                    demographic_score  = VALUES(demographic_score),
                    disease_score      = VALUES(disease_score),
                    total_raw          = VALUES(total_raw),
                    final_raf          = VALUES(final_raf),
                    hcc_count          = VALUES(hcc_count),
                    calculated_at      = NOW()
                """,
                (
                    pid, measurement_year, model_segment,
                    demographic_score, disease_score,
                    total_raw, final_raf,
                    hcc_count,
                ),
            )
    except Exception as exc:
        logger.warning(
            "synthetic_data_generator: failed to store RAF data for pid=%s: %s",
            pid, exc,
        )


def _age_band(age: int) -> str:
    if age < 35: return "0-34"
    if age < 45: return "35-44"
    if age < 55: return "45-54"
    if age < 60: return "55-59"
    if age < 65: return "60-64"
    if age < 70: return "65-69"
    if age < 75: return "70-74"
    if age < 80: return "75-79"
    if age < 85: return "80-84"
    return "85+"


def _ensure_demo_emr_connection() -> None:
    """Register a demo EMR connection in emr_connections if not already present.

    The demo connection points at the RAF Intelligence DB itself so that
    ``openemr_cursor()`` can read from the shadow patient_data / form_encounter /
    billing tables created by this generator.
    """
    try:
        with raf_cursor() as cur:
            cur.execute(
                "SELECT id FROM emr_connections WHERE vendor = 'demo' LIMIT 1",
            )
            if cur.fetchone() is not None:
                return  # already registered

        db_host = settings.raf_db_host
        db_port = settings.raf_db_port
        db_name = settings.raf_db_name
        db_user = settings.raf_db_user
        db_password = settings.raf_db_password

        with raf_cursor() as cur:
            cur.execute(
                """
                INSERT INTO emr_connections
                    (tenant_id, display_name, vendor, connection_type,
                     db_type, db_host, db_port, db_name, db_user, db_password,
                     is_active, created_at, updated_at)
                VALUES
                    ('default', 'Demo Data (synthetic)', 'demo', 'direct_db',
                     'mysql', %s, %s, %s, %s, %s,
                     1, NOW(), NOW())
                """,
                (db_host, db_port, db_name, db_user, db_password),
            )
        logger.info("synthetic_data_generator: demo EMR connection registered")
    except Exception as exc:
        logger.warning(
            "synthetic_data_generator: could not register demo EMR connection: %s", exc,
        )
