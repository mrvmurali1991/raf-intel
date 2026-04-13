"""
Enrollment Service.

Manages CMS Medicare Advantage enrollment records linked to patients.
Covers the full lifecycle of enrollment data:

  - CRUD operations on the enrollment table
  - Bulk population from existing patients and raf_patient_demographics
  - CMS Bundle 1 export formatting (Patient_ID, MBI, demographics, plan, PCP)

All writes target the raf_intelligence database via the shared raf_cursor pool.
Soft deletes are used — records are never physically removed.
"""
from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Any

from app.db import raf_cursor

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_ENROLLMENT_SELECT = """
    SELECT
        e.enrollment_id,
        e.patient_id,
        e.tenant_id,
        e.mbi,
        e.plan_id,
        e.coverage_start,
        e.coverage_end,
        e.dual_status,
        e.orec,
        e.institutional_status,
        e.esrd_status,
        e.raf_demographic_score,
        e.age_band,
        e.disability_status,
        e.created_at,
        e.updated_at
    FROM enrollment e
    WHERE e.deleted_at IS NULL
"""


def _serialize_dates(row: dict[str, Any]) -> dict[str, Any]:
    """Convert date/datetime objects in a row dict to ISO strings for JSON safety."""
    for key, value in row.items():
        if isinstance(value, (date, datetime)):
            row[key] = value.isoformat()
    return row


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def get_enrollment(patient_id: int) -> dict | None:
    """Return the active enrollment record for a patient, or None if not found.

    Args:
        patient_id: The patients.id primary key.

    Returns:
        Enrollment row as a dict, or None when no active record exists.
    """
    sql = _ENROLLMENT_SELECT + " AND e.patient_id = %s LIMIT 1"
    with raf_cursor() as cursor:
        cursor.execute(sql, (patient_id,))
        row = cursor.fetchone()

    if row is None:
        return None
    return _serialize_dates(row)


def list_enrollments(
    tenant_id: str, limit: int = 50, offset: int = 0
) -> list[dict]:
    """Return a paginated list of active enrollment records for a tenant.

    Args:
        tenant_id: Tenant identifier used to scope the query.
        limit: Maximum number of rows to return (default 50, capped at 1000).
        offset: Number of rows to skip for pagination.

    Returns:
        List of enrollment row dicts ordered by enrollment_id descending.
    """
    limit = min(limit, 1000)
    sql = (
        _ENROLLMENT_SELECT
        + " AND e.tenant_id = %s ORDER BY e.enrollment_id DESC LIMIT %s OFFSET %s"
    )
    with raf_cursor() as cursor:
        cursor.execute(sql, (tenant_id, limit, offset))
        rows = cursor.fetchall()

    return [_serialize_dates(row) for row in rows]


def create_enrollment(data: dict) -> int:
    """Insert a new enrollment record and return the generated enrollment_id.

    Required keys in data:
        patient_id (int), tenant_id (str)

    Optional keys (all default to None/False when absent):
        mbi, plan_id, coverage_start, coverage_end, dual_status, orec,
        institutional_status, esrd_status, raf_demographic_score, age_band,
        disability_status

    Args:
        data: Dict of field values for the new enrollment row.

    Returns:
        The auto-generated enrollment_id (int).

    Raises:
        ValueError: When required fields are missing.
        mysql.connector.Error: On database constraint violations.
    """
    required = {"patient_id", "tenant_id"}
    missing = required - data.keys()
    if missing:
        raise ValueError(f"create_enrollment: missing required fields: {missing}")

    sql = """
        INSERT INTO enrollment (
            patient_id, tenant_id, mbi, plan_id,
            coverage_start, coverage_end, dual_status, orec,
            institutional_status, esrd_status, raf_demographic_score,
            age_band, disability_status,
            created_at, updated_at
        ) VALUES (
            %s, %s, %s, %s,
            %s, %s, %s, %s,
            %s, %s, %s,
            %s, %s,
            NOW(), NOW()
        )
    """
    params = (
        data["patient_id"],
        data["tenant_id"],
        data.get("mbi"),
        data.get("plan_id"),
        data.get("coverage_start"),
        data.get("coverage_end"),
        data.get("dual_status"),
        data.get("orec"),
        bool(data.get("institutional_status", False)),
        bool(data.get("esrd_status", False)),
        data.get("raf_demographic_score"),
        data.get("age_band"),
        bool(data.get("disability_status", False)),
    )

    with raf_cursor() as cursor:
        cursor.execute(sql, params)
        enrollment_id = cursor.lastrowid

    logger.info(
        "Created enrollment enrollment_id=%s patient_id=%s tenant_id=%s",
        enrollment_id,
        data["patient_id"],
        data["tenant_id"],
    )
    return enrollment_id


def update_enrollment(enrollment_id: int, data: dict) -> bool:
    """Update mutable fields on an existing enrollment record.

    Only keys present in *data* are updated; omitted keys are left unchanged.
    The updated_at timestamp is always refreshed.

    Args:
        enrollment_id: Primary key of the enrollment row to update.
        data: Dict of field names -> new values. Unknown keys are silently
              ignored to prevent SQL injection via dynamic column names.

    Returns:
        True when exactly one row was updated, False when the record was not
        found or already soft-deleted.
    """
    allowed_columns = {
        "mbi", "plan_id", "coverage_start", "coverage_end",
        "dual_status", "orec", "institutional_status", "esrd_status",
        "raf_demographic_score", "age_band", "disability_status",
    }

    updates = {k: v for k, v in data.items() if k in allowed_columns}
    if not updates:
        logger.warning(
            "update_enrollment called with no valid fields for enrollment_id=%s",
            enrollment_id,
        )
        return False

    set_clauses = ", ".join(f"{col} = %s" for col in updates)
    sql = f"""
        UPDATE enrollment
        SET {set_clauses}, updated_at = NOW()
        WHERE enrollment_id = %s AND deleted_at IS NULL
    """
    params = list(updates.values()) + [enrollment_id]

    with raf_cursor() as cursor:
        cursor.execute(sql, params)
        affected = cursor.rowcount

    if affected == 0:
        logger.warning(
            "update_enrollment: no active row found for enrollment_id=%s", enrollment_id
        )
        return False

    logger.info("Updated enrollment enrollment_id=%s fields=%s", enrollment_id, list(updates))
    return True


def delete_enrollment(enrollment_id: int) -> bool:
    """Soft-delete an enrollment record by setting deleted_at to NOW().

    The row is retained in the database for audit trail purposes.

    Args:
        enrollment_id: Primary key of the enrollment row to soft-delete.

    Returns:
        True when the record was found and marked deleted, False otherwise.
    """
    sql = """
        UPDATE enrollment
        SET deleted_at = NOW(), updated_at = NOW()
        WHERE enrollment_id = %s AND deleted_at IS NULL
    """
    with raf_cursor() as cursor:
        cursor.execute(sql, (enrollment_id,))
        affected = cursor.rowcount

    if affected == 0:
        logger.warning(
            "delete_enrollment: no active row found for enrollment_id=%s", enrollment_id
        )
        return False

    logger.info("Soft-deleted enrollment enrollment_id=%s", enrollment_id)
    return True


def populate_from_demographics(tenant_id: str) -> int:
    if not tenant_id:
        raise ValueError(
            "populate_from_demographics: tenant_id is required — "
            "refusing to operate without tenant scope (HIPAA multi-tenant isolation)"
        )
    """Bulk-populate the enrollment table from patients + raf_patient_demographics.

    Inserts one enrollment row per patient that:
      - Belongs to the given tenant
      - Is active (is_active = 1)
      - Does not already have an active enrollment row

    Demographic fields (age_band, raf_demographic_score, dual_status, orec,
    disability_status, institutional_status, esrd_status) are pulled from
    raf_patient_demographics when a matching row exists; otherwise those fields
    are left NULL/False.

    MBI is taken from patients.mbi when populated.

    Args:
        tenant_id: Tenant to populate. Defaults to "default".

    Returns:
        Number of new enrollment rows created.

    Raises:
        mysql.connector.Error: On any database error.
    """
    # Identify patients without an active enrollment row
    candidates_sql = """
        SELECT
            p.id            AS patient_id,
            p.tenant_id,
            p.mbi,
            d.age_band,
            d.raf_score     AS raf_demographic_score,
            d.dual_status,
            d.orec,
            d.disability_status,
            d.institutional_status,
            d.esrd_status
        FROM patients p
        LEFT JOIN raf_patient_demographics d
            ON d.patient_id = p.id
        LEFT JOIN enrollment e
            ON e.patient_id = p.id
           AND e.deleted_at IS NULL
        WHERE p.tenant_id = %s
          AND p.is_active  = 1
          AND e.enrollment_id IS NULL
    """

    insert_sql = """
        INSERT INTO enrollment (
            patient_id, tenant_id, mbi,
            age_band, raf_demographic_score, dual_status, orec,
            disability_status, institutional_status, esrd_status,
            created_at, updated_at
        ) VALUES (
            %s, %s, %s,
            %s, %s, %s, %s,
            %s, %s, %s,
            NOW(), NOW()
        )
    """

    created = 0

    with raf_cursor() as cursor:
        cursor.execute(candidates_sql, (tenant_id,))
        candidates = cursor.fetchall()

        if not candidates:
            logger.info(
                "populate_from_demographics: no new patients to enroll for tenant=%s",
                tenant_id,
            )
            return 0

        rows = [
            (
                c["patient_id"],
                c["tenant_id"],
                c.get("mbi"),
                c.get("age_band"),
                c.get("raf_demographic_score"),
                c.get("dual_status"),
                c.get("orec"),
                bool(c.get("disability_status", False)),
                bool(c.get("institutional_status", False)),
                bool(c.get("esrd_status", False)),
            )
            for c in candidates
        ]

        cursor.executemany(insert_sql, rows)
        created = cursor.rowcount

    logger.info(
        "populate_from_demographics: created %d enrollment records for tenant=%s",
        created,
        tenant_id,
    )
    return created


def get_enrollment_for_bundle(tenant_id: str) -> list[dict]:
    if not tenant_id:
        raise ValueError(
            "get_enrollment_for_bundle: tenant_id is required — "
            "refusing to operate without tenant scope (HIPAA multi-tenant isolation)"
        )
    """Return enrollment data formatted for CMS Bundle 1 export.

    Each row maps to a single enrollee and contains only the fields required
    by the CMS Risk Adjustment Bundle 1 submission:
      Patient_ID, MBI, First_Name, Last_Name, DOB, Gender,
      Plan_ID, Coverage_Start, Coverage_End, PCP_NPI, Dual_Status

    PCP_NPI is resolved from the providers table via the patient's assigned
    provider relationship when available. Rows without an MBI are included
    but callers should treat them as incomplete for submission purposes.

    Args:
        tenant_id: Tenant to export.

    Returns:
        List of dicts with CMS Bundle 1 field names. Empty list when no
        active enrollments exist for the tenant.
    """
    sql = """
        SELECT
            p.id                        AS Patient_ID,
            COALESCE(e.mbi, p.mbi)      AS MBI,
            p.first_name                AS First_Name,
            p.last_name                 AS Last_Name,
            p.dob                       AS DOB,
            p.sex                       AS Gender,
            e.plan_id                   AS Plan_ID,
            e.coverage_start            AS Coverage_Start,
            e.coverage_end              AS Coverage_End,
            pr.npi                      AS PCP_NPI,
            e.dual_status               AS Dual_Status
        FROM enrollment e
        JOIN patients p
            ON p.id = e.patient_id
        LEFT JOIN patient_providers pp
            ON pp.patient_id = p.id
           AND pp.relationship_type = 'PCP'
           AND pp.is_active = 1
        LEFT JOIN providers pr
            ON pr.id = pp.provider_id
        WHERE e.tenant_id    = %s
          AND e.deleted_at   IS NULL
          AND p.is_active    = 1
        ORDER BY p.last_name ASC, p.first_name ASC
    """

    with raf_cursor() as cursor:
        cursor.execute(sql, (tenant_id,))
        rows = cursor.fetchall()

    result = []
    for row in rows:
        # Serialize date objects to ISO strings for downstream JSON serialization
        serialized = {}
        for key, value in row.items():
            if isinstance(value, (date, datetime)):
                serialized[key] = value.isoformat()
            else:
                serialized[key] = value
        result.append(serialized)

    logger.info(
        "get_enrollment_for_bundle: returned %d records for tenant=%s",
        len(result),
        tenant_id,
    )
    return result
