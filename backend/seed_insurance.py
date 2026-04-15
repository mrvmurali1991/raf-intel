"""
Seed insurance companies and insurance_data for demo patients pid 28-42.

All patients are Medicare Advantage beneficiaries (primary = Medicare Part A/B).
Dual-eligible patients (pids 29, 31, 34, 37, 39, 41) also get Medicaid TX as
secondary coverage.  A small cohort has commercial supplemental (BCBS) as
secondary to reflect realistic MA plan mix.

Usage (from backend/ directory, with .env loaded):
    python seed_insurance.py

The script:
  1. Introspects information_schema to confirm the columns that exist on
     insurance_companies and insurance_data before touching any data.
  2. Upserts the 3 canonical insurance companies.
  3. Inserts primary + optional secondary insurance_data rows, skipping any
     pid/type combination that already has a row so the script is idempotent.
"""

from __future__ import annotations

import os
import sys
import datetime
import random

# ---------------------------------------------------------------------------
# Bootstrap: make sure `app` is importable from the backend/ directory tree
# ---------------------------------------------------------------------------
_BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)

# Load .env so settings (DB creds etc.) resolve before importing app modules
try:
    from dotenv import load_dotenv
    _env_path = os.path.join(os.path.dirname(_BACKEND_DIR), ".env")
    if os.path.exists(_env_path):
        load_dotenv(_env_path)
        print(f"[boot] Loaded .env from {_env_path}")
    else:
        load_dotenv()  # search upward from cwd
        print("[boot] Loaded .env from default search path")
except ImportError:
    print("[boot] python-dotenv not installed — skipping .env load")

from app.db import openemr_cursor  # noqa: E402  (after sys.path fixup)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

DEMO_PIDS: list[int] = list(range(28, 43))  # 28 .. 42 inclusive

# Dual-eligible patients — these get Medicare (primary) + Medicaid (secondary)
DUAL_ELIGIBLE_PIDS: set[int] = {29, 31, 34, 37, 39, 41}

# Patients with commercial supplemental BCBS (secondary) — different subset
BCBS_SECONDARY_PIDS: set[int] = {28, 32, 36, 40, 42}

# Effective date for all new insurance records
EFFECTIVE_DATE = datetime.date(2024, 1, 1)

# Canonical company names
MEDICARE_NAME = "Medicare Part A/B"
MEDICAID_NAME = "Medicaid TX"
BCBS_NAME     = "Blue Cross Blue Shield"

# Per-patient policy number seeds (deterministic but realistic-looking)
random.seed(8675309)

def _medicare_id(pid: int) -> str:
    """Generate a realistic-looking Medicare Beneficiary Identifier (MBI).

    Real MBIs are 11 characters: 1C-2N-1A-1N-1A-1N-2A-2N.
    We approximate that pattern for demo data.
    """
    letters = "ACDEFGHJKMNPQRTUVWXY"
    digits  = "0123456789"
    rng = random.Random(pid * 13 + 42)
    mbi = (
        rng.choice(letters)
        + rng.choice(digits)
        + rng.choice(digits)
        + rng.choice(letters)
        + rng.choice(digits)
        + rng.choice(letters)
        + rng.choice(digits)
        + rng.choice(letters)
        + rng.choice(letters)
        + rng.choice(digits)
        + rng.choice(digits)
    )
    return mbi


def _medicaid_id(pid: int) -> str:
    rng = random.Random(pid * 7 + 99)
    return "TX" + "".join(str(rng.randint(0, 9)) for _ in range(10))


def _bcbs_policy(pid: int) -> str:
    rng = random.Random(pid * 3 + 17)
    return "XOP" + "".join(str(rng.randint(0, 9)) for _ in range(9))


def _bcbs_group(pid: int) -> str:
    rng = random.Random(pid * 5 + 23)
    return "GRP" + "".join(str(rng.randint(0, 9)) for _ in range(6))


# ---------------------------------------------------------------------------
# Schema introspection helpers
# ---------------------------------------------------------------------------

def _get_columns(cur, table: str) -> set[str]:
    """Return the set of column names that exist on *table* in the active DB."""
    cur.execute(
        """
        SELECT COLUMN_NAME
        FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE()
          AND TABLE_NAME   = %s
        """,
        (table,),
    )
    rows = cur.fetchall()
    # Cursor may return dicts or tuples depending on dictionary= setting
    if rows and isinstance(rows[0], dict):
        return {r["COLUMN_NAME"] for r in rows}
    return {r[0] for r in rows}


# ---------------------------------------------------------------------------
# Company upsert
# ---------------------------------------------------------------------------

def _upsert_companies(cur) -> dict[str, int]:
    """Ensure the 3 canonical companies exist; return mapping name -> id."""
    companies = {
        MEDICARE_NAME: {
            "name": MEDICARE_NAME,
            "attn": "Medicare Beneficiary Contact Center",
            "street": "7500 Security Blvd",
            "city": "Baltimore",
            "state": "MD",
            "zip": "21244",
            "phone": "1-800-633-4227",
            "cms_id": "00001",
        },
        MEDICAID_NAME: {
            "name": MEDICAID_NAME,
            "attn": "Texas Medicaid",
            "street": "PO Box 85200",
            "city": "Austin",
            "state": "TX",
            "zip": "78708",
            "phone": "1-800-252-8263",
            "cms_id": "00002",
        },
        BCBS_NAME: {
            "name": BCBS_NAME,
            "attn": "BCBS Member Services",
            "street": "PO Box 660044",
            "city": "Dallas",
            "state": "TX",
            "zip": "75266",
            "phone": "1-888-697-0683",
            "cms_id": "00003",
        },
    }

    # Discover which columns exist on insurance_companies
    ic_cols = _get_columns(cur, "insurance_companies")
    print(f"[schema] insurance_companies columns: {sorted(ic_cols)}")

    name_to_id: dict[str, int] = {}

    for name, info in companies.items():
        # Check existence
        cur.execute(
            "SELECT id FROM insurance_companies WHERE name = %s LIMIT 1",
            (name,),
        )
        row = cur.fetchone()
        if row:
            existing_id = row["id"] if isinstance(row, dict) else row[0]
            name_to_id[name] = existing_id
            print(f"[company] '{name}' already exists (id={existing_id}) — skipping")
            continue

        # Build INSERT using only columns that exist on this OpenEMR version
        insert_data: dict[str, object] = {"name": name}

        col_map = {
            "attn":  info["attn"],
            "street": info["street"],
            "city":   info["city"],
            "state":  info["state"],
            "zip":    info["zip"],
            "phone":  info["phone"],
        }
        # cms_id present in some OpenEMR versions
        if "cms_id" in ic_cols:
            col_map["cms_id"] = info["cms_id"]
        # country column
        if "country" in ic_cols:
            col_map["country"] = "USA"
        # email / fax optionally
        if "email" in ic_cols:
            col_map["email"] = ""
        if "fax" in ic_cols:
            col_map["fax"] = ""

        for col, val in col_map.items():
            if col in ic_cols:
                insert_data[col] = val

        cols_sql   = ", ".join(insert_data.keys())
        placeholders = ", ".join(["%s"] * len(insert_data))
        cur.execute(
            f"INSERT INTO insurance_companies ({cols_sql}) VALUES ({placeholders})",
            tuple(insert_data.values()),
        )
        new_id = cur.lastrowid
        name_to_id[name] = new_id
        print(f"[company] Created '{name}' with id={new_id}")

    return name_to_id


# ---------------------------------------------------------------------------
# insurance_data helpers
# ---------------------------------------------------------------------------

_SUBSCRIBER_RELATIONSHIP = "self"

# Representative subscriber demographics per pid (lname, fname, dob)
# In a real scenario these come from patient demographics; here we use
# placeholders that are consistent with demo patient data.
_SUBSCRIBER_META: dict[int, tuple[str, str, str]] = {
    28: ("Johnson",   "Margaret",  "1942-03-15"),
    29: ("Williams",  "Robert",    "1938-11-22"),
    30: ("Martinez",  "Elena",     "1945-07-04"),
    31: ("Thompson",  "Harold",    "1936-01-30"),
    32: ("Davis",     "Patricia",  "1949-06-18"),
    33: ("Anderson",  "George",    "1940-09-09"),
    34: ("Taylor",    "Dorothy",   "1943-12-01"),
    35: ("Moore",     "James",     "1947-05-27"),
    36: ("Jackson",   "Helen",     "1941-08-14"),
    37: ("White",     "Charles",   "1935-02-19"),
    38: ("Harris",    "Ruth",      "1950-10-31"),
    39: ("Martin",    "Edward",    "1937-04-07"),
    40: ("Garcia",    "Frances",   "1944-07-22"),
    41: ("Robinson",  "Walter",    "1933-03-11"),
    42: ("Clark",     "Louise",    "1948-11-05"),
}


def _row_exists(cur, pid: int, ins_type: str) -> bool:
    """Return True if an insurance_data row already exists for this pid+type."""
    cur.execute(
        "SELECT id FROM insurance_data WHERE pid = %s AND type = %s LIMIT 1",
        (pid, ins_type),
    )
    return cur.fetchone() is not None


def _insert_insurance(
    cur,
    id_cols: set[str],
    pid: int,
    ins_type: str,        # "primary" | "secondary"
    provider_id: int,
    plan_name: str,
    policy_number: str,
    group_number: str,
) -> None:
    """Insert a single insurance_data row using only columns that exist."""
    if _row_exists(cur, pid, ins_type):
        print(f"  [skip] pid={pid} {ins_type} already exists")
        return

    lname, fname, dob = _SUBSCRIBER_META.get(pid, ("Demo", "Patient", "1950-01-01"))

    row: dict[str, object] = {
        "pid":          pid,
        "type":         ins_type,
        "provider":     provider_id,
        "plan_name":    plan_name,
        "policy_number": policy_number,
        "group_number":  group_number,
        "subscriber_lname":        lname,
        "subscriber_fname":        fname,
        "subscriber_relationship": _SUBSCRIBER_RELATIONSHIP,
    }

    # Optional columns — insert only when they exist on this OpenEMR version
    optional: dict[str, object] = {
        "subscriber_DOB":   dob,
        "date":             EFFECTIVE_DATE.strftime("%Y-%m-%d"),
        "subscriber_mname": "",
        "subscriber_street": "",
        "subscriber_city":   "",
        "subscriber_state":  "",
        "subscriber_postal_code": "",
        "subscriber_country": "USA",
        "subscriber_phone":   "",
        "subscriber_employer": "",
        "subscriber_employer_street": "",
        "subscriber_employer_city": "",
        "subscriber_employer_state": "",
        "subscriber_employer_postal_code": "",
        "subscriber_employer_country": "",
        "copay":             "0.00",
        "date_end":          None,
        "accept_assignment": "TRUE",
        "notes":             "",
    }
    for col, val in optional.items():
        if col in id_cols:
            row[col] = val

    cols_sql     = ", ".join(row.keys())
    placeholders = ", ".join(["%s"] * len(row))
    cur.execute(
        f"INSERT INTO insurance_data ({cols_sql}) VALUES ({placeholders})",
        tuple(row.values()),
    )
    print(f"  [insert] pid={pid} {ins_type} provider_id={provider_id} policy={policy_number}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run() -> None:
    print("=" * 60)
    print("Seeding insurance data for demo patients pid 28-42")
    print("=" * 60)

    with openemr_cursor(tenant_id="1") as cur:
        # ---- Introspect schemas ----
        id_cols = _get_columns(cur, "insurance_data")
        print(f"[schema] insurance_data columns: {sorted(id_cols)}")

        # Verify expected columns are present; warn about any that are absent
        required_cols = {"pid", "type", "provider", "plan_name",
                         "policy_number", "group_number",
                         "subscriber_lname", "subscriber_fname",
                         "subscriber_relationship"}
        missing = required_cols - id_cols
        if missing:
            print(
                f"[WARNING] The following expected columns are MISSING from "
                f"insurance_data: {missing}\n"
                f"  The script will skip them and continue.  Verify the "
                f"OpenEMR version / schema before relying on seeded data."
            )

        # ---- Upsert companies ----
        company_ids = _upsert_companies(cur)
        medicare_id  = company_ids[MEDICARE_NAME]
        medicaid_id  = company_ids[MEDICAID_NAME]
        bcbs_id      = company_ids[BCBS_NAME]

        # ---- Seed per-patient insurance ----
        for pid in DEMO_PIDS:
            print(f"\n[pid={pid}]")

            # Primary: Medicare for all demo patients
            _insert_insurance(
                cur,
                id_cols,
                pid=pid,
                ins_type="primary",
                provider_id=medicare_id,
                plan_name="Medicare Part A/B",
                policy_number=_medicare_id(pid),
                group_number="",          # Medicare uses MBI, no group number
            )

            # Secondary: Medicaid for dual-eligible patients
            if pid in DUAL_ELIGIBLE_PIDS:
                _insert_insurance(
                    cur,
                    id_cols,
                    pid=pid,
                    ins_type="secondary",
                    provider_id=medicaid_id,
                    plan_name="Texas Medicaid",
                    policy_number=_medicaid_id(pid),
                    group_number="",
                )

            # Secondary: BCBS supplemental for commercial-plan patients
            # (mutual exclusion: a patient is either dual-eligible or BCBS, not both)
            elif pid in BCBS_SECONDARY_PIDS:
                _insert_insurance(
                    cur,
                    id_cols,
                    pid=pid,
                    ins_type="secondary",
                    provider_id=bcbs_id,
                    plan_name="BCBS Medicare Supplement Plan G",
                    policy_number=_bcbs_policy(pid),
                    group_number=_bcbs_group(pid),
                )

    print("\n" + "=" * 60)
    print("Done.  Insurance seeding complete.")
    print("=" * 60)


if __name__ == "__main__":
    run()
