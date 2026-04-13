"""
Data Quality Monitoring Service.

Runs a battery of data quality checks across the RAF Intelligence database
to surface suspicious, stale, or inconsistent records. Intended to be run
nightly via cron (e.g. 02:00 local time), with the resulting report stored
and surfaced to the admin dashboard so operators can triage data issues
before they impact RAF calculations or submissions.

Each check returns a structured dict:
    {
        "check":      <str  — check identifier>,
        "severity":   <"info" | "warn" | "error">,
        "count":      <int  — number of offending rows>,
        "sample_ids": <list — up to 10 example ids>,
        "details":    <str  — human-readable description>,
    }

The top-level ``run_all_checks(cursor, tenant_id)`` function executes every
check, isolating failures so a single bad query does not sink the full
report. Typical scheduling:

    # /etc/cron.d/raf-dq
    0 2 * * *  appuser  /usr/local/bin/python -m app.jobs.run_dq_monitor

Results should be persisted (e.g. ``data_quality_reports`` table) and
rendered in the admin dashboard with severity-based filtering.
"""
from __future__ import annotations

import logging
from datetime import date
from typing import Any, Callable

logger = logging.getLogger(__name__)

SAMPLE_LIMIT = 10

# Type alias for a mysql-connector cursor (dictionary=True).
# Using Any here avoids a hard import of mysql.connector types at module level.
Cursor = Any


def _empty_result(check: str, severity: str, details: str) -> dict[str, Any]:
    return {
        "check": check,
        "severity": severity,
        "count": 0,
        "sample_ids": [],
        "details": details,
    }


def _error_result(check: str, exc: Exception) -> dict[str, Any]:
    logger.exception("Data quality check %s failed", check)
    return {
        "check": check,
        "severity": "error",
        "count": 0,
        "sample_ids": [],
        "details": f"Check failed to execute: {exc!s}",
    }


def check_patients_without_icd(cursor: Cursor, tenant_id: int) -> dict[str, Any]:
    """Patients with no HCCs and no diagnoses recorded in the last 365 days."""
    check = "patients_without_icd"
    try:
        cursor.execute(
            """
            SELECT p.id
            FROM patients p
            WHERE p.tenant_id = %(tenant_id)s
              AND NOT EXISTS (
                    SELECT 1 FROM raf_patient_hcc h
                    WHERE h.patient_id = p.id
              )
              AND NOT EXISTS (
                    SELECT 1 FROM diagnoses d
                    WHERE d.patient_id = p.id
                      AND d.diagnosis_date >= (CURRENT_DATE - INTERVAL 365 DAY)
              )
            ORDER BY p.id
            LIMIT 1000
            """,
            {"tenant_id": tenant_id},
        )
        rows = [r["id"] for r in cursor.fetchall()]
        return {
            "check": check,
            "severity": "warn",
            "count": len(rows),
            "sample_ids": rows[:SAMPLE_LIMIT],
            "details": (
                "Patients with zero rows in raf_patient_hcc and no diagnoses "
                "in the last 365 days — likely missing coding or data ingestion gap."
            ),
        }
    except Exception as exc:  # noqa: BLE001
        return _error_result(check, exc)


def check_hccs_missing_meat(cursor: Cursor, tenant_id: int) -> dict[str, Any]:
    """HCC rows with MEAT status missing or NULL — unsupported documentation."""
    check = "hccs_missing_meat"
    try:
        cursor.execute(
            """
            SELECT h.id
            FROM raf_patient_hcc h
            JOIN patients p ON p.id = h.patient_id
            WHERE p.tenant_id = %(tenant_id)s
              AND (h.meat_status IS NULL OR h.meat_status = 'MISSING')
            ORDER BY h.id
            LIMIT 1000
            """,
            {"tenant_id": tenant_id},
        )
        rows = [r["id"] for r in cursor.fetchall()]
        return {
            "check": check,
            "severity": "error",
            "count": len(rows),
            "sample_ids": rows[:SAMPLE_LIMIT],
            "details": (
                "raf_patient_hcc rows with meat_status NULL or 'MISSING'. These "
                "HCCs cannot be defended in a RADV audit and should not be submitted."
            ),
        }
    except Exception as exc:  # noqa: BLE001
        return _error_result(check, exc)


def check_raf_score_outliers(cursor: Cursor, tenant_id: int) -> dict[str, Any]:
    """RAF scores outside plausible clinical range (>5.0 or <0.1)."""
    check = "raf_score_outliers"
    try:
        cursor.execute(
            """
            SELECT p.id
            FROM patients p
            WHERE p.tenant_id = %(tenant_id)s
              AND p.raf_score IS NOT NULL
              AND (p.raf_score > 5.0 OR p.raf_score < 0.1)
            ORDER BY p.id
            LIMIT 1000
            """,
            {"tenant_id": tenant_id},
        )
        rows = [r["id"] for r in cursor.fetchall()]
        return {
            "check": check,
            "severity": "warn",
            "count": len(rows),
            "sample_ids": rows[:SAMPLE_LIMIT],
            "details": (
                "Patients with RAF scores > 5.0 or < 0.1 — suspiciously high/low. "
                "Investigate demographic or coefficient lookup errors."
            ),
        }
    except Exception as exc:  # noqa: BLE001
        return _error_result(check, exc)


def check_future_dob(cursor: Cursor, tenant_id: int) -> dict[str, Any]:
    """Patients with date-of-birth after today — impossible data."""
    check = "future_dob"
    try:
        cursor.execute(
            """
            SELECT id
            FROM patients
            WHERE tenant_id = %(tenant_id)s
              AND dob IS NOT NULL
              AND dob > CURRENT_DATE
            ORDER BY id
            LIMIT 1000
            """,
            {"tenant_id": tenant_id},
        )
        rows = [r["id"] for r in cursor.fetchall()]
        return {
            "check": check,
            "severity": "error",
            "count": len(rows),
            "sample_ids": rows[:SAMPLE_LIMIT],
            "details": "Patients with DOB in the future — data entry / import defect.",
        }
    except Exception as exc:  # noqa: BLE001
        return _error_result(check, exc)


def check_duplicate_patients(cursor: Cursor, tenant_id: int) -> dict[str, Any]:
    """Patients sharing the same (last_name, first_name, dob)."""
    check = "duplicate_patients"
    try:
        cursor.execute(
            """
            SELECT p.id
            FROM patients p
            JOIN (
                SELECT last_name, first_name, dob
                FROM patients
                WHERE tenant_id = %(tenant_id)s
                  AND last_name IS NOT NULL
                  AND first_name IS NOT NULL
                  AND dob IS NOT NULL
                GROUP BY last_name, first_name, dob
                HAVING COUNT(*) > 1
            ) dup
              ON dup.last_name = p.last_name
             AND dup.first_name = p.first_name
             AND dup.dob = p.dob
            WHERE p.tenant_id = %(tenant_id)s
            ORDER BY p.last_name, p.first_name, p.dob, p.id
            LIMIT 1000
            """,
            {"tenant_id": tenant_id},
        )
        rows = [r["id"] for r in cursor.fetchall()]
        return {
            "check": check,
            "severity": "error",
            "count": len(rows),
            "sample_ids": rows[:SAMPLE_LIMIT],
            "details": (
                "Multiple patient rows with identical last_name, first_name and dob. "
                "Likely duplicate enrollment — merge before calculating RAF."
            ),
        }
    except Exception as exc:  # noqa: BLE001
        return _error_result(check, exc)


def check_stale_crosswalk(cursor: Cursor) -> dict[str, Any]:
    """HCC/ICD-10 crosswalk effective_year is more than 1 year behind today."""
    check = "stale_crosswalk"
    try:
        cursor.execute("SELECT MAX(effective_year) AS max_year FROM hcc_icd10_crosswalk")
        row = cursor.fetchone()
        max_year = row["max_year"] if row else None
        current_year = date.today().year  # 2026 at time of writing
        if max_year is None:
            return {
                "check": check,
                "severity": "error",
                "count": 0,
                "sample_ids": [],
                "details": "hcc_icd10_crosswalk is empty — no effective_year found.",
            }
        if max_year < current_year - 1:
            return {
                "check": check,
                "severity": "warn",
                "count": int(current_year - max_year),
                "sample_ids": [int(max_year)],
                "details": (
                    f"hcc_icd10_crosswalk max effective_year is {max_year}, "
                    f"current year is {current_year}. Crosswalk is stale — refresh "
                    "from CMS before next RAF run."
                ),
            }
        return _empty_result(
            check,
            "info",
            f"hcc_icd10_crosswalk effective_year={max_year} is current.",
        )
    except Exception as exc:  # noqa: BLE001
        return _error_result(check, exc)


def check_orphaned_hccs(cursor: Cursor, tenant_id: int) -> dict[str, Any]:
    """raf_patient_hcc rows whose patient_id has no matching patients row."""
    check = "orphaned_hccs"
    try:
        try:
            cursor.execute(
                """
                SELECT h.id
                FROM raf_patient_hcc h
                LEFT JOIN patients p ON p.id = h.patient_id
                WHERE p.id IS NULL
                  AND (h.tenant_id = %(tenant_id)s OR %(tenant_id)s IS NULL)
                ORDER BY h.id
                LIMIT 1000
                """,
                {"tenant_id": tenant_id},
            )
            rows = [r["id"] for r in cursor.fetchall()]
        except Exception:
            # Fallback if raf_patient_hcc has no tenant_id column
            cursor.execute(
                """
                SELECT h.id
                FROM raf_patient_hcc h
                LEFT JOIN patients p ON p.id = h.patient_id
                WHERE p.id IS NULL
                ORDER BY h.id
                LIMIT 1000
                """
            )
            rows = [r["id"] for r in cursor.fetchall()]
        return {
            "check": check,
            "severity": "error",
            "count": len(rows),
            "sample_ids": rows[:SAMPLE_LIMIT],
            "details": (
                "raf_patient_hcc rows pointing at a patient_id that no longer "
                "exists in patients — referential integrity violation."
            ),
        }
    except Exception as exc:  # noqa: BLE001
        return _error_result(check, exc)


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

_TENANT_CHECKS: list[Callable[[Cursor, int], dict[str, Any]]] = [
    check_patients_without_icd,
    check_hccs_missing_meat,
    check_raf_score_outliers,
    check_future_dob,
    check_duplicate_patients,
    check_orphaned_hccs,
]

_GLOBAL_CHECKS: list[Callable[[Cursor], dict[str, Any]]] = [
    check_stale_crosswalk,
]


def run_all_checks(cursor: Cursor, tenant_id: int) -> list[dict[str, Any]]:
    """Execute every data quality check and return a list of result dicts.

    Each check is wrapped so a single failure does not break the report.
    Intended to be invoked from the nightly cron job and persisted to the
    ``data_quality_reports`` table for display on the admin dashboard.

    ``cursor`` must be a mysql-connector dictionary cursor (dictionary=True)
    obtained via ``app.db.raf_cursor()``.
    """
    report: list[dict[str, Any]] = []
    for fn in _TENANT_CHECKS:
        try:
            report.append(fn(cursor, tenant_id))
        except Exception as exc:  # noqa: BLE001
            report.append(_error_result(fn.__name__, exc))
    for gfn in _GLOBAL_CHECKS:
        try:
            report.append(gfn(cursor))
        except Exception as exc:  # noqa: BLE001
            report.append(_error_result(gfn.__name__, exc))
    return report


CHECK_NAMES: list[str] = [fn.__name__ for fn in _TENANT_CHECKS] + [
    fn.__name__ for fn in _GLOBAL_CHECKS
]


if __name__ == "__main__":
    print("Data Quality Monitor — available checks:")
    for name in CHECK_NAMES:
        print(f"  - {name}")
