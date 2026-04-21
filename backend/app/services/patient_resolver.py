"""Unified patient resolver — handles both direct_db and FHIR patient lookups.

This is the single source of truth for resolving a patient ID to a patient
record, regardless of whether the active EMR connection is a FHIR/REST API
or a direct database connection.

Column name reference (verified against patient_service.py):
  - raf_intelligence.patients:        id, tenant_id, first_name, middle_name, last_name, dob, gender, sex, race, ethnicity, zip, mrn, emr_pid, data_source, is_active
  - raf_intelligence.emr_patient_matches: id, external_id, first_name, last_name,
                                          date_of_birth, sex, mrn, raf_patient_id, connection_id
"""

from __future__ import annotations

import logging

from app.db import raf_cursor

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Connection type helpers
# ---------------------------------------------------------------------------


def active_connection_type(tenant_id: str) -> str:
    """Return 'fhir_r4', 'rest_api', or 'direct_db' for the active connection.

    Falls back to 'direct_db' on any error or when no active connection row
    exists, matching the behaviour of the rest of the application.
    """
    try:
        with raf_cursor() as cur:
            cur.execute(
                "SELECT connection_type FROM emr_connections "
                "WHERE is_active = 1 AND tenant_id = %s LIMIT 1",
                (tenant_id,),
            )
            row = cur.fetchone()
            return row["connection_type"] if row else "direct_db"
    except Exception:
        return "direct_db"


def is_fhir_active(tenant_id: str) -> bool:
    """Return True when the active connection for *tenant_id* is FHIR or REST."""
    return active_connection_type(tenant_id) in ("fhir_r4", "rest_api")


# ---------------------------------------------------------------------------
# Single-patient resolver
# ---------------------------------------------------------------------------


def resolve_patient(pid: int, tenant_id: str) -> dict | None:
    """Resolve a patient by ID from the correct table based on the active connection.

    Returns a unified dict with the following keys:
        id              — internal row ID (emr_patient_matches.id OR patients.id)
        first_name      — patient first name
        last_name       — patient last name
        date_of_birth   — ISO date string (YYYY-MM-DD) or raw value
        sex             — patient sex
        mrn             — medical record number
        external_id     — external FHIR/REST patient ID, or None for direct_db
        source          — 'fhir' or 'direct_db'
        patient_id_for_raf — the ID to use when querying RAF scores and conditions
                             (emr_patient_matches.raf_patient_id for FHIR,
                              patients.id for direct_db)

    Returns None when the patient is not found or does not belong to the tenant.
    """
    try:
        with raf_cursor() as cur:
            if is_fhir_active(tenant_id):
                cur.execute(
                    """
                    SELECT epm.id,
                           epm.external_id,
                           epm.first_name,
                           epm.last_name,
                           epm.date_of_birth,
                           epm.sex,
                           epm.mrn,
                           epm.raf_patient_id
                    FROM emr_patient_matches epm
                    JOIN emr_connections ec ON ec.id = epm.connection_id
                    WHERE epm.id = %s
                      AND ec.is_active = 1
                      AND ec.tenant_id = %s
                    LIMIT 1
                    """,
                    (pid, tenant_id),
                )
                row = cur.fetchone()
                if row:
                    dob = row["date_of_birth"]
                    return {
                        "id": row["id"],
                        "first_name": row["first_name"] or "",
                        "last_name": row["last_name"] or "",
                        "date_of_birth": (
                            dob.isoformat()
                            if hasattr(dob, "isoformat")
                            else (str(dob) if dob else None)
                        ),
                        "sex": row["sex"] or "",
                        "mrn": row["mrn"] or "",
                        "external_id": row["external_id"],
                        "source": "fhir",
                        "patient_id_for_raf": row["raf_patient_id"],
                    }
            else:
                # direct_db — patients table uses first_name/last_name/dob/mrn
                cur.execute(
                    """
                    SELECT id,
                           first_name,
                           last_name,
                           dob    AS date_of_birth,
                           sex,
                           mrn,
                           emr_pid
                    FROM patients
                    WHERE id = %s
                      AND tenant_id = %s
                      AND is_active = 1
                    LIMIT 1
                    """,
                    (pid, tenant_id),
                )
                row = cur.fetchone()
                if row:
                    dob = row["date_of_birth"]
                    return {
                        "id": row["id"],
                        "first_name": row["first_name"] or "",
                        "last_name": row["last_name"] or "",
                        "date_of_birth": (
                            dob.isoformat()
                            if hasattr(dob, "isoformat")
                            else (str(dob) if dob else None)
                        ),
                        "sex": row["sex"] or "",
                        "mrn": row["mrn"] or "",
                        "external_id": None,
                        "source": "direct_db",
                        "patient_id_for_raf": row["id"],
                    }
    except Exception:
        logger.exception("resolve_patient failed for pid=%s tenant=%s", pid, tenant_id)
    return None


# ---------------------------------------------------------------------------
# Bulk ID helpers — used by RAF calc, suspect scans, cohort builders, etc.
# ---------------------------------------------------------------------------


def get_all_patient_ids(tenant_id: str) -> list[int]:
    """Return all active patient IDs for *tenant_id*.

    For FHIR connections the ID returned is emr_patient_matches.raf_patient_id
    so that downstream RAF/condition queries use a consistent key.
    For direct_db connections the ID is patients.id.
    """
    try:
        with raf_cursor() as cur:
            if is_fhir_active(tenant_id):
                cur.execute(
                    """
                    SELECT epm.raf_patient_id AS patient_id
                    FROM emr_patient_matches epm
                    JOIN emr_connections ec ON ec.id = epm.connection_id
                    WHERE ec.is_active = 1
                      AND ec.tenant_id = %s
                    """,
                    (tenant_id,),
                )
            else:
                cur.execute(
                    "SELECT id AS patient_id FROM patients "
                    "WHERE is_active = 1 AND tenant_id = %s",
                    (tenant_id,),
                )
            return [r["patient_id"] for r in cur.fetchall()]
    except Exception:
        logger.exception("get_all_patient_ids failed for tenant=%s", tenant_id)
        return []


# ---------------------------------------------------------------------------
# Display list — used by dashboard, dropdowns, search results
# ---------------------------------------------------------------------------


def get_patient_display_list(tenant_id: str) -> list[dict]:
    """Return all active patients for *tenant_id* formatted for display.

    Each dict contains: id, first_name, last_name, date_of_birth, sex, mrn,
    external_id, source, patient_id_for_raf.
    Results are sorted alphabetically by last name then first name.
    """
    try:
        with raf_cursor() as cur:
            if is_fhir_active(tenant_id):
                cur.execute(
                    """
                    SELECT epm.id,
                           epm.external_id,
                           epm.first_name,
                           epm.last_name,
                           epm.date_of_birth,
                           epm.sex,
                           epm.mrn,
                           epm.raf_patient_id
                    FROM emr_patient_matches epm
                    JOIN emr_connections ec ON ec.id = epm.connection_id
                    WHERE ec.is_active = 1
                      AND ec.tenant_id = %s
                    ORDER BY epm.last_name, epm.first_name
                    """,
                    (tenant_id,),
                )
                rows = cur.fetchall()
                result = []
                for row in rows:
                    dob = row["date_of_birth"]
                    result.append({
                        "id": row["id"],
                        "first_name": row["first_name"] or "",
                        "last_name": row["last_name"] or "",
                        "date_of_birth": (
                            dob.isoformat()
                            if hasattr(dob, "isoformat")
                            else (str(dob) if dob else None)
                        ),
                        "sex": row["sex"] or "",
                        "mrn": row["mrn"] or "",
                        "external_id": row["external_id"],
                        "source": "fhir",
                        "patient_id_for_raf": row["raf_patient_id"],
                    })
                return result
            cur.execute(
                """
                    SELECT id,
                           first_name,
                           last_name,
                           dob    AS date_of_birth,
                           sex,
                           mrn,
                           emr_pid
                    FROM patients
                    WHERE is_active = 1
                      AND tenant_id = %s
                    ORDER BY last_name, first_name
                    """,
                (tenant_id,),
            )
            rows = cur.fetchall()
            result = []
            for row in rows:
                dob = row["date_of_birth"]
                result.append({
                    "id": row["id"],
                    "first_name": row["first_name"] or "",
                    "last_name": row["last_name"] or "",
                    "date_of_birth": (
                        dob.isoformat()
                        if hasattr(dob, "isoformat")
                        else (str(dob) if dob else None)
                    ),
                    "sex": row["sex"] or "",
                    "mrn": row["mrn"] or "",
                    "external_id": None,
                    "source": "direct_db",
                    "patient_id_for_raf": row["id"],
                })
            return result
    except Exception:
        logger.exception("get_patient_display_list failed for tenant=%s", tenant_id)
        return []
