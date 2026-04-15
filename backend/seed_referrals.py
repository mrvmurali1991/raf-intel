"""
Seed referral data into OpenEMR for demo patients pid 28–42.

Inserts 1–3 referral rows per patient into the ``transactions`` table
(title='Referral').  Existing rows for the same (pid, refer_to, date)
are skipped so the script is safe to run more than once.

Usage (from the backend/ directory with the app virtualenv active):

    python seed_referrals.py

The script resolves the OpenEMR connection through the same
``openemr_cursor()`` context manager used by the API, so it honours
the tenant's UI-configured EMR connection (or falls back to the
OPENEMR_DB_* environment variables).
"""

from __future__ import annotations

import os
import random
import sys
from datetime import date, timedelta

# Allow ``from app.db import openemr_cursor`` regardless of CWD.
sys.path.insert(0, os.path.dirname(__file__))

from app.db import openemr_cursor  # noqa: E402

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# Patient IDs to seed.
PATIENT_IDS: list[int] = list(range(28, 43))  # 28 … 42 inclusive

# Referral catalogue: (specialty_label, specialist_name, reason)
REFERRAL_CATALOGUE: list[tuple[str, str, str]] = [
    (
        "Cardiology",
        "Dr. Anita Shah, MD",
        "Evaluation of heart failure with reduced ejection fraction (HFrEF); "
        "echocardiogram and stress test recommended.",
    ),
    (
        "Nephrology",
        "Dr. James Okonkwo, MD",
        "Chronic kidney disease stage 3b with worsening eGFR trend; "
        "nephrology co-management and dietary counselling requested.",
    ),
    (
        "Endocrinology",
        "Dr. Maria Reyes, MD",
        "Poorly controlled Type 2 diabetes mellitus (HbA1c > 9.5%); "
        "insulin optimisation and CGM assessment.",
    ),
    (
        "Pulmonology",
        "Dr. David Kim, MD",
        "COPD exacerbation with FEV1 decline; pulmonary function testing "
        "and inhaler therapy review.",
    ),
    (
        "Rheumatology",
        "Dr. Sandra Lee, MD",
        "Rheumatoid arthritis with inadequate DMARD response; "
        "biologic therapy consideration.",
    ),
    (
        "Neurology",
        "Dr. Eric Mensah, MD",
        "Peripheral neuropathy secondary to diabetes; EMG/NCS and pain "
        "management evaluation.",
    ),
    (
        "Gastroenterology",
        "Dr. Priya Nair, MD",
        "Elevated liver enzymes and fatty liver disease; hepatology "
        "assessment and lifestyle counselling.",
    ),
    (
        "Ophthalmology",
        "Dr. Thomas Berger, OD",
        "Diabetic retinopathy screening; annual dilated fundus examination.",
    ),
    (
        "Vascular Surgery",
        "Dr. Lena Hoffman, MD",
        "Peripheral arterial disease with ankle-brachial index < 0.9; "
        "vascular imaging and revascularisation assessment.",
    ),
    (
        "Hematology",
        "Dr. Carlos Ruiz, MD",
        "Unexplained anaemia with haemoglobin < 10 g/dL; bone marrow "
        "evaluation and iron-deficiency workup.",
    ),
]

REFERRING_PROVIDER = "Dr. Primary Care"
AUTHORIZED = 1  # 1 = authorised in OpenEMR


def _random_date(start_year: int = 2024, end_year: int = 2026) -> date:
    """Return a uniformly random date between Jan 1 *start_year* and today."""
    start = date(start_year, 1, 1)
    end = min(date.today(), date(end_year, 12, 31))
    delta_days = (end - start).days
    return start + timedelta(days=random.randint(0, delta_days))


def _ensure_transactions_table(cur) -> None:
    """Create the transactions table if it does not exist.

    Standard OpenEMR installations ship this table, but some test or
    minimal deployments omit it.  The DDL mirrors the schema used by the
    rest of the codebase (see seed_clinical_data.py).
    """
    cur.execute("SHOW TABLES LIKE 'transactions'")
    if cur.fetchone():
        return  # table already present

    print("  transactions table not found — creating it...")
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS transactions (
            id          BIGINT       AUTO_INCREMENT PRIMARY KEY,
            date        DATETIME     DEFAULT CURRENT_TIMESTAMP,
            title       VARCHAR(255),
            pid         BIGINT,
            body        TEXT,
            refer_to    VARCHAR(255),
            refer_from  VARCHAR(255),
            reason      TEXT,
            reply_date  DATE,
            user        VARCHAR(100),
            groupname   VARCHAR(100),
            authorized  TINYINT      DEFAULT 1,
            INDEX idx_pid (pid)
        )
        """
    )
    print("  transactions table created.")


def seed_referrals() -> None:
    """Insert 1–3 referral rows per patient for pids 28–42."""
    total_inserted = 0
    total_skipped = 0

    with openemr_cursor(tenant_id="1") as cur:
        _ensure_transactions_table(cur)

        for pid in PATIENT_IDS:
            # Choose 1–3 distinct specialties for this patient.
            count = random.randint(1, 3)
            chosen = random.sample(REFERRAL_CATALOGUE, count)

            pid_inserted = 0
            for specialty, specialist, reason in chosen:
                referral_date = _random_date()
                body = (
                    f"Referral to {specialty} – {specialist}. "
                    f"Reason: {reason} "
                    f"Patient has relevant diagnoses requiring specialist evaluation."
                )

                # Idempotency guard: skip if an identical row already exists.
                cur.execute(
                    "SELECT id FROM transactions "
                    "WHERE pid = %s AND refer_to = %s AND date = %s LIMIT 1",
                    (pid, specialist, referral_date.isoformat()),
                )
                if cur.fetchone():
                    total_skipped += 1
                    continue

                cur.execute(
                    "INSERT INTO transactions "
                    "  (date, title, pid, body, refer_to, refer_from, reason, "
                    "   user, groupname, authorized) "
                    "VALUES (%s, 'Referral', %s, %s, %s, %s, %s, "
                    "        'admin', 'Default', %s)",
                    (
                        referral_date.isoformat(),
                        pid,
                        body,
                        specialist,
                        REFERRING_PROVIDER,
                        reason,
                        AUTHORIZED,
                    ),
                )
                pid_inserted += 1
                total_inserted += 1

            print(
                f"  PID {pid}: inserted {pid_inserted} referral(s)"
                + (f" (skipped {count - pid_inserted} duplicate(s))" if pid_inserted < count else "")
            )

    print(
        f"\nDone.  Inserted {total_inserted} referral row(s), "
        f"skipped {total_skipped} duplicate(s)."
    )


if __name__ == "__main__":
    print("Seeding referral transactions for PIDs 28–42 …\n")
    seed_referrals()
