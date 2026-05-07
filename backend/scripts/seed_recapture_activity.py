"""Seed realistic recapture activity so the /recapture demo page shows non-zero values.

What this inserts (all idempotent — safe to re-run)
----------------------------------------------------
1. DDL — adds missing columns (resolved_at, resolved_by, provider_npi,
   last_encounter_date, reopened_at, reopened_by, reopen_reason) and expands
   the status enum to include 'recaptured'.
2. 45 closed recapture gaps spread across Q1-2025 through Q1-2026, tagged
   audit_notes='RECAPTURE_ACTIVITY_SEED', so they can be purged cleanly.
3. ~15 open gaps for the same cohort years (pipeline / at-risk view).

Endpoints served:
  GET /api/recapture/cfo/summary   — quarter_breakdown shows $X per quarter
  GET /api/recapture/cfo/yoy       — series has recaptured_dollars for 2024/25/26
  GET /api/recapture/bonus/leaderboard — coders ranked by resolved_by = user id
  GET /api/recapture/velocity      — avg/median days-to-close, YTD $, close rate
"""
from __future__ import annotations

import random
import sys
from datetime import date, datetime, timedelta, timezone

sys.path.insert(0, "/app")
from app.db import raf_cursor  # noqa: E402

SEED_TAG = "RECAPTURE_ACTIVITY_SEED"
TENANT_ID = "1"
TODAY = date.today()

# Patients confirmed to exist in DB
PATIENT_IDS = [8, 16, 22, 23, 24, 25]

# Providers: (npi, resolved_by) — resolved_by uses user id or email
PROVIDERS = [
    ("1234567890", "1"),   # Dr. Sarah Mitchell → admin user
    ("1234567891", "2"),   # Dr. David Park → demo user
    ("1234567894", "1"),
    ("1234567892", "2"),
    ("1234567893", "1"),
    ("1234567895", "2"),
]

# HCC / ICD-10 pairs with realistic revenue_impact values
HCC_POOL = [
    ("E11.65",  "19",  "Diabetes with hyperglycemia",           3200.00),
    ("J44.9",   "111", "COPD, unspecified",                     4100.00),
    ("I50.9",   "85",  "Heart failure, unspecified",            4800.00),
    ("N18.4",   "138", "CKD stage 4",                           5200.00),
    ("F03.90",  "52",  "Dementia, unspecified",                 3600.00),
    ("D63.8",   "48",  "Anemia in chronic disease",             2900.00),
    ("Z99.81",  "84",  "Dependence on supplemental O2",         3400.00),
    ("M06.9",   "40",  "Rheumatoid arthritis",                  3100.00),
    ("E11.40",  "18",  "Diabetes with diabetic nephropathy",    4400.00),
    ("I48.91",  "96",  "Unspecified atrial fibrillation",       3700.00),
]


def _rand_date_in_quarter(year: int, quarter: int) -> date:
    """Return a random date within the given calendar quarter."""
    q_start_month = (quarter - 1) * 3 + 1
    q_end_month = q_start_month + 2
    start = date(year, q_start_month, 1)
    # last day of end month
    if q_end_month == 12:
        end = date(year, 12, 31)
    else:
        end = date(year, q_end_month + 1, 1) - timedelta(days=1)
    # clamp to today
    if end > TODAY:
        end = TODAY
    if start > TODAY:
        start = TODAY
    delta = (end - start).days
    return start + timedelta(days=random.randint(0, max(0, delta)))


def _column_exists(cursor, column: str) -> bool:
    cursor.execute(
        """SELECT COUNT(*) AS c FROM INFORMATION_SCHEMA.COLUMNS
           WHERE TABLE_SCHEMA = DATABASE()
             AND TABLE_NAME   = 'recapture_gaps'
             AND COLUMN_NAME  = %s""",
        (column,),
    )
    return int((cursor.fetchone() or {}).get("c") or 0) > 0


def apply_schema_changes() -> None:
    """Add missing columns and expand status enum — idempotent."""
    # Columns to add: (name, definition)
    new_columns = [
        ("resolved_at",       "DATETIME DEFAULT NULL"),
        ("resolved_by",       "VARCHAR(255) DEFAULT NULL"),
        ("provider_npi",      "VARCHAR(20) DEFAULT NULL"),
        ("last_encounter_date", "DATE DEFAULT NULL"),
        ("reopened_at",       "DATETIME DEFAULT NULL"),
        ("reopened_by",       "VARCHAR(255) DEFAULT NULL"),
        ("reopen_reason",     "TEXT DEFAULT NULL"),
    ]

    with raf_cursor() as cursor:
        # Always attempt enum expand (MODIFY is idempotent)
        try:
            cursor.execute(
                """ALTER TABLE recapture_gaps
                   MODIFY COLUMN status
                   ENUM('open','closed','dismissed','recaptured') NOT NULL DEFAULT 'open'"""
            )
            print("  DDL OK: status enum expanded to include 'recaptured'")
        except Exception as exc:
            print(f"  DDL WARN (enum): {exc}")

        for col, defn in new_columns:
            if _column_exists(cursor, col):
                print(f"  DDL SKIP: {col} already exists")
                continue
            try:
                cursor.execute(
                    f"ALTER TABLE recapture_gaps ADD COLUMN {col} {defn}"
                )
                print(f"  DDL OK: added {col}")
            except Exception as exc:
                if "1060" in str(exc) or "Duplicate column" in str(exc):
                    print(f"  DDL SKIP: {col} already exists (race)")
                else:
                    print(f"  DDL WARN ({col}): {exc}")


def _existing_seed_ids() -> set[int]:
    """Return IDs of gap rows already tagged with the seed tag."""
    with raf_cursor() as cursor:
        cursor.execute(
            "SELECT id FROM recapture_gaps WHERE audit_notes = %s",
            (SEED_TAG,),
        )
        return {row["id"] for row in (cursor.fetchall() or [])}


def seed_closed_gaps() -> int:
    """Insert 45 closed recapture gaps spread across last 4 quarters + current year."""
    existing = _existing_seed_ids()
    if len(existing) >= 45:
        print(f"  Already have {len(existing)} seed rows — skipping closed gap inserts.")
        return len(existing)

    # Distribution: Q1 2025 → 8, Q2 2025 → 10, Q3 2025 → 12, Q4 2025 → 10, Q1 2026 → 5
    schedule = [
        (2025, 1,  8),
        (2025, 2, 10),
        (2025, 3, 12),
        (2025, 4, 10),
        (2026, 1,  5),
    ]

    insert_sql = """
        INSERT INTO recapture_gaps
            (tenant_id, patient_id, icd10_code, hcc_code, condition_label,
             payment_year, status, evidence_phrase, meat_element,
             revenue_impact, current_year, prior_year,
             provider_npi, resolved_at, resolved_by,
             last_encounter_date, audit_status, audit_notes,
             created_at, updated_at)
        VALUES
            (%s, %s, %s, %s, %s,
             %s, 'recaptured', %s, %s,
             %s, %s, %s,
             %s, %s, %s,
             %s, 'approved', %s,
             %s, %s)
    """

    total = 0
    with raf_cursor() as cursor:
        for (year, quarter, count) in schedule:
            for _ in range(count):
                hcc = random.choice(HCC_POOL)
                icd, hcc_code, label, impact = hcc
                patient_id = random.choice(PATIENT_IDS)
                npi, resolved_by = random.choice(PROVIDERS)

                created_dt = datetime.combine(
                    _rand_date_in_quarter(year, quarter), datetime.min.time()
                ).replace(tzinfo=timezone.utc)
                # Close 5–45 days after creation
                close_offset = timedelta(days=random.randint(5, 45))
                resolved_dt = created_dt + close_offset
                # Clamp to today
                now_utc = datetime.now(timezone.utc)
                if resolved_dt > now_utc:
                    resolved_dt = now_utc

                last_enc = (created_dt - timedelta(days=random.randint(7, 30))).date()

                evidence_phrases = [
                    "Annual visit note confirms active management per MEAT criteria",
                    "Lab results reviewed; condition actively monitored with treatment adjustment",
                    "Physician attestation — condition evaluated, treatment plan documented",
                    "Specialist consult confirming ongoing management and assessment",
                    "Chart review: medication reconciliation confirms chronic condition status",
                ]

                meat_elements = ["M", "E", "A", "T"]

                cursor.execute(
                    insert_sql,
                    (
                        TENANT_ID, patient_id, icd, hcc_code, label,
                        year, random.choice(evidence_phrases), random.choice(meat_elements),
                        impact, year, year - 1,
                        npi, resolved_dt, resolved_by,
                        last_enc, SEED_TAG,
                        created_dt, resolved_dt,
                    ),
                )
                total += 1

    print(f"  Inserted {total} closed recapture gaps.")
    return total


def seed_open_gaps() -> int:
    """Insert 15 open gaps for the current year (pipeline / at-risk)."""
    with raf_cursor() as cursor:
        cursor.execute(
            "SELECT COUNT(*) AS c FROM recapture_gaps WHERE audit_notes = %s AND status = 'open'",
            (SEED_TAG,),
        )
        existing_open = int((cursor.fetchone() or {}).get("c") or 0)

    if existing_open >= 15:
        print(f"  Already have {existing_open} open seed rows — skipping.")
        return existing_open

    insert_sql = """
        INSERT INTO recapture_gaps
            (tenant_id, patient_id, icd10_code, hcc_code, condition_label,
             payment_year, status, revenue_impact,
             current_year, prior_year,
             provider_npi, last_encounter_date,
             audit_status, audit_notes, created_at, updated_at)
        VALUES
            (%s, %s, %s, %s, %s,
             %s, 'open', %s,
             %s, %s,
             %s, %s,
             'draft', %s, %s, %s)
    """

    year = TODAY.year
    total = 0
    with raf_cursor() as cursor:
        for _ in range(15):
            icd, hcc_code, label, impact = random.choice(HCC_POOL)
            patient_id = random.choice(PATIENT_IDS)
            npi, _ = random.choice(PROVIDERS)
            created_dt = datetime.now(timezone.utc) - timedelta(days=random.randint(10, 90))
            last_enc = (created_dt - timedelta(days=random.randint(7, 30))).date()

            cursor.execute(
                insert_sql,
                (
                    TENANT_ID, patient_id, icd, hcc_code, label,
                    year, impact,
                    year, year - 1,
                    npi, last_enc,
                    SEED_TAG, created_dt, created_dt,
                ),
            )
            total += 1

    print(f"  Inserted {total} open recapture gaps.")
    return total


def verify() -> None:
    """Print a quick sanity check against the seeded data."""
    with raf_cursor() as cursor:
        cursor.execute(
            """
            SELECT
                current_year,
                QUARTER(resolved_at) AS q,
                COUNT(*) AS gaps,
                ROUND(SUM(revenue_impact), 0) AS dollars
            FROM recapture_gaps
            WHERE tenant_id = %s
              AND status = 'recaptured'
              AND audit_notes = %s
            GROUP BY current_year, QUARTER(resolved_at)
            ORDER BY current_year, q
            """,
            (TENANT_ID, SEED_TAG),
        )
        rows = cursor.fetchall()

    print("\n  Seed verification — closed gaps by year/quarter:")
    total_dollars = 0.0
    for r in rows:
        d = float(r["dollars"] or 0)
        total_dollars += d
        print(f"    {r['current_year']} Q{r['q']}: {r['gaps']} gaps  ${d:,.0f}")

    print(f"\n  Total seeded uplift: ${total_dollars:,.0f}")

    with raf_cursor() as cursor:
        cursor.execute(
            """
            SELECT resolved_by, COUNT(*) AS closures
            FROM recapture_gaps
            WHERE tenant_id=%s AND status='recaptured' AND audit_notes=%s
            GROUP BY resolved_by
            """,
            (TENANT_ID, SEED_TAG),
        )
        lb = cursor.fetchall()

    print("\n  Leaderboard seed (resolved_by → closures):")
    for r in lb:
        print(f"    {r['resolved_by']}: {r['closures']} closures")


def main() -> None:
    print("=== seed_recapture_activity ===")
    print("\n[1/4] Applying schema changes...")
    apply_schema_changes()

    print("\n[2/4] Seeding closed gaps (45 rows across 5 quarters)...")
    closed = seed_closed_gaps()

    print("\n[3/4] Seeding open gaps (15 rows, current year)...")
    opened = seed_open_gaps()

    print("\n[4/4] Verification:")
    verify()

    print(f"\nDone. closed={closed} open={opened}")


if __name__ == "__main__":
    main()
