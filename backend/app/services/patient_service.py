"""
patient_service.py

Business logic extracted from app/routers/patients.py.

The router is responsible for:
  - FastAPI dependency injection (auth, permissions, rate limiting)
  - Raising HTTPException on error codes returned here
  - Calling log_phi_access after successful service calls

This module is responsible for:
  - All database queries against raf_intelligence (via raf_cursor)
  - All calls to openemr_connector (emr.*)
  - All data transformation, enrichment, and fallback logic
  - Tenant-scoping and IDOR checks (returns False / None instead of 404)

Public surface
--------------
Every function beginning with ``svc_`` is called by the router.  The internal
helpers (prefixed ``_``) are module-private implementation details.
"""

from __future__ import annotations

import json as _json
import logging
import time as _time
from datetime import date as _date
from datetime import datetime as _datetime
from typing import Any

from app.db import raf_cursor
from app.services import openemr_connector as emr
from app.services.cache_strategy import (
    TTL_PATIENT_LIST,
    tenant_cached,
)
from app.services.emr_manager import active_patients_subquery
from app.services.raf_calculator import get_raf_breakdown

logger = logging.getLogger(__name__)

# Simple TTL cache for _get_fhir_resource_id to avoid redundant DB lookups
_fhir_id_cache: dict[int, tuple[str | None, float]] = {}
_FHIR_ID_CACHE_TTL = 60  # seconds


# ---------------------------------------------------------------------------
# Internal helpers — tenant / connection guards
# ---------------------------------------------------------------------------


def _has_active_emr_connection() -> bool:
    """Return True if at least one EMR connection with is_active=1 exists."""
    try:
        with raf_cursor() as cur:
            cur.execute("SELECT 1 FROM emr_connections WHERE is_active = 1 LIMIT 1")
            return cur.fetchone() is not None
    except Exception:
        return False


def _active_connection_type() -> str | None:
    """Return the connection_type of the active EMR connection, or None."""
    try:
        with raf_cursor() as cur:
            cur.execute(
                "SELECT connection_type FROM emr_connections WHERE is_active = 1 LIMIT 1"
            )
            row = cur.fetchone()
            return row["connection_type"] if row else None
    except Exception:
        return None


def _tenant_of(current_user: dict) -> str:
    """Extract tenant_id from current_user — raises if not present.

    Raises:
        ValueError: If current_user has no tenant_id (misconfigured account).
    """
    tid = current_user.get("tenant_id") if current_user else None
    if tid is None:
        raise ValueError(
            "_tenant_of: current_user has no tenant_id — user account is misconfigured; "
            "contact administrator (HIPAA multi-tenant isolation)"
        )
    return str(tid)


def _patient_belongs_to_tenant(pid: int, tenant_id: str) -> bool:
    """Return True if *pid* exists in raf_intelligence.patients for this tenant."""
    try:
        with raf_cursor() as cur:
            cur.execute(
                "SELECT 1 FROM patients WHERE id = %s AND tenant_id = %s LIMIT 1",
                (pid, tenant_id),
            )
            return cur.fetchone() is not None
    except Exception:
        return False


def _patient_in_active_connection(pid: int, tenant_id: str | None = None) -> bool:
    """Return True if *pid* is linked to an active EMR connection."""
    try:
        with raf_cursor() as cur:
            cur.execute(
                "SELECT 1 FROM emr_patient_matches pm "
                "JOIN emr_connections ec ON ec.id = pm.connection_id "
                "WHERE ec.is_active = 1 AND pm.raf_patient_id = %s LIMIT 1",
                (pid,),
            )
            if cur.fetchone() is not None:
                return True
            cur.execute(
                "SELECT 1 FROM emr_connections "
                "WHERE is_active = 1 AND connection_type = 'direct_db' LIMIT 1",
            )
            if cur.fetchone() is not None:
                if tenant_id is not None:
                    cur.execute(
                        "SELECT 1 FROM patients WHERE id = %s AND tenant_id = %s",
                        (pid, tenant_id),
                    )
                else:
                    logger.warning("patient_exists called without tenant_id for pid=%s", pid)
                    cur.execute("SELECT 1 FROM patients WHERE id = %s", (pid,))
                return cur.fetchone() is not None
        return False
    except Exception:
        return False


def _get_emr_pid(pid: int, tenant_id: str | None = None) -> int | str | None:
    """Look up the emr_pid for a patient in raf_intelligence.patients.

    Returns an int for direct-DB (OpenEMR) patients or a string UUID for
    FHIR-synced patients.
    """
    try:
        with raf_cursor() as cur:
            if tenant_id is not None:
                cur.execute(
                    "SELECT emr_pid FROM patients WHERE id = %s AND tenant_id = %s",
                    (pid, tenant_id),
                )
            else:
                logger.warning("_get_emr_pid called without tenant_id for pid=%s", pid)
                cur.execute("SELECT emr_pid FROM patients WHERE id = %s", (pid,))
            row = cur.fetchone()
            if row and row.get("emr_pid"):
                raw = row["emr_pid"]
                try:
                    return int(float(raw))
                except (ValueError, TypeError):
                    # FHIR UUID string — return as-is
                    return str(raw)
    except Exception as exc:
        logger.debug("Failed to fetch data: %s", exc)
    return None


def _safe_call(label: str, fn, *args, default=None, **kwargs):
    """Call *fn* and return result; on any exception log and return *default*."""
    try:
        return fn(*args, **kwargs)
    except Exception as exc:
        logger.warning("patient_service [%s] failed: %s", label, exc)
        return default


def _calculate_age(dob_raw: str | None) -> int | None:
    """Return current age in years from a DOB string, or None."""
    if not dob_raw:
        return None
    try:
        dob = _datetime.strptime(str(dob_raw)[:10], "%Y-%m-%d").date()
        today = _date.today()
        return today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))
    except (ValueError, TypeError):
        return None


def _patient_in_fhir_matches(pid: int, tenant_id: str | None = None) -> bool:
    """Return True if *pid* is a FHIR patient.

    Checks three paths:
      1. emr_patient_matches.id = pid  (legacy: pid IS the match row id)
      2. emr_patient_matches.raf_patient_id = pid  (new: pid is patients.id)
      3. patients.data_source = 'fhir'  (most reliable for patients-table rows)
    """
    try:
        with raf_cursor() as cur:
            # Path 3: patients table data_source check (fastest, most reliable)
            if tenant_id is not None:
                cur.execute(
                    "SELECT 1 FROM patients WHERE id = %s AND tenant_id = %s "
                    "AND data_source = 'fhir' LIMIT 1",
                    (pid, tenant_id),
                )
            else:
                cur.execute(
                    "SELECT 1 FROM patients WHERE id = %s AND data_source = 'fhir' LIMIT 1",
                    (pid,),
                )
            if cur.fetchone() is not None:
                return True

            # Path 1 & 2: emr_patient_matches
            if tenant_id is not None:
                cur.execute(
                    "SELECT 1 FROM emr_patient_matches epm "
                    "JOIN emr_connections ec ON ec.id = epm.connection_id "
                    "WHERE ec.is_active = 1 AND ec.connection_type IN ('fhir_r4', 'rest_api') "
                    "AND (epm.id = %s OR epm.raf_patient_id = %s) AND ec.tenant_id = %s LIMIT 1",
                    (pid, pid, tenant_id),
                )
            else:
                cur.execute(
                    "SELECT 1 FROM emr_patient_matches epm "
                    "JOIN emr_connections ec ON ec.id = epm.connection_id "
                    "WHERE ec.is_active = 1 AND ec.connection_type IN ('fhir_r4', 'rest_api') "
                    "AND (epm.id = %s OR epm.raf_patient_id = %s) LIMIT 1",
                    (pid, pid),
                )
            return cur.fetchone() is not None
    except Exception:
        return False


def _get_fhir_patient_row(pid: int, tenant_id: str | None = None) -> dict | None:
    """Return a unified patient dict from emr_patient_matches for a FHIR patient.

    Checks both epm.id = pid (legacy) and epm.raf_patient_id = pid (new path
    for patients that live in the patients table with data_source='fhir').
    """
    try:
        with raf_cursor() as cur:
            if tenant_id is not None:
                cur.execute(
                    "SELECT epm.id, epm.external_id, epm.first_name, epm.last_name, "
                    "epm.date_of_birth, epm.sex, epm.mrn, epm.raf_patient_id, epm.match_status "
                    "FROM emr_patient_matches epm "
                    "JOIN emr_connections ec ON ec.id = epm.connection_id "
                    "WHERE ec.is_active = 1 AND ec.connection_type IN ('fhir_r4', 'rest_api') "
                    "AND (epm.id = %s OR epm.raf_patient_id = %s OR epm.patient_id = %s) AND ec.tenant_id = %s LIMIT 1",
                    (pid, pid, pid, tenant_id),
                )
            else:
                cur.execute(
                    "SELECT epm.id, epm.external_id, epm.first_name, epm.last_name, "
                    "epm.date_of_birth, epm.sex, epm.mrn, epm.raf_patient_id, epm.match_status "
                    "FROM emr_patient_matches epm "
                    "JOIN emr_connections ec ON ec.id = epm.connection_id "
                    "WHERE ec.is_active = 1 AND ec.connection_type IN ('fhir_r4', 'rest_api') "
                    "AND (epm.id = %s OR epm.raf_patient_id = %s OR epm.patient_id = %s) LIMIT 1",
                    (pid, pid, pid),
                )
            row = cur.fetchone()
            if not row:
                return None
            dob_raw = row.get("date_of_birth")
            return {
                "pid": row["id"],
                "fname": row.get("first_name") or "",
                "lname": row.get("last_name") or "",
                "DOB": dob_raw.isoformat() if hasattr(dob_raw, "isoformat") else (str(dob_raw) if dob_raw else ""),
                "sex": row.get("sex") or "",
                "mrn": row.get("mrn") or "",
                "external_id": row.get("external_id"),
                "raf_patient_id": row.get("raf_patient_id"),
                "match_status": row.get("match_status") or "",
                "data_source": "fhir",
            }
    except Exception:
        return None


def _get_fhir_resource_id(pid: int, tenant_id: str | None = None) -> str | None:
    """Resolve the FHIR resource UUID for a patient, used to query fhir_* tables.

    Tries three paths in order:
      1. emr_patient_matches.external_id  (via _get_fhir_patient_row)
      2. fhir_patients.fhir_resource_id   (via patients.emr_pid / emr_connection_id)
      3. fhir_patients.fhir_resource_id   (name+DOB fuzzy match as last resort)

    Returns the UUID string or None.
    """
    # TODO: Check fhir_sync_logs.status for this patient — if sync is in-progress,
    # fallback queries may return partial data. Consider adding sync_status to fhir_patients table.

    # Check module-level TTL cache first to avoid redundant DB lookups
    _cached = _fhir_id_cache.get(pid)
    if _cached and (_time.time() - _cached[1]) < _FHIR_ID_CACHE_TTL:
        return _cached[0]

    # Path 1: emr_patient_matches external_id (the standard FHIR patient UUID)
    fhir_row = _get_fhir_patient_row(pid, tenant_id=tenant_id)
    if fhir_row and fhir_row.get("external_id"):
        _fhir_id_cache[pid] = (fhir_row["external_id"], _time.time())
        return fhir_row["external_id"]

    # Path 2: fhir_patients table via patients.emr_pid + emr_connection_id
    try:
        with raf_cursor() as cur:
            # Get the patient row to find emr_pid and emr_connection_id
            if tenant_id is not None:
                cur.execute(
                    "SELECT emr_pid, emr_connection_id, first_name, last_name, fname, lname, dob "
                    "FROM patients WHERE id = %s AND tenant_id = %s LIMIT 1",
                    (pid, tenant_id),
                )
            else:
                cur.execute(
                    "SELECT emr_pid, emr_connection_id, first_name, last_name, fname, lname, dob "
                    "FROM patients WHERE id = %s LIMIT 1",
                    (pid,),
                )
            p_row = cur.fetchone()
            if not p_row:
                return None

            conn_id = p_row.get("emr_connection_id")

            # emr_pid now stores the FHIR resource UUID directly for
            # FHIR-synced patients; check if it matches a fhir_patients row.
            # Note: patients.emr_connection_id is from emr_connections table,
            # but fhir_patients.connection_id is from fhir_connections table
            # (different IDs for the same connection), so match by UUID only.
            emr_pid_val = str(p_row.get("emr_pid") or "").strip()
            if emr_pid_val:
                cur.execute(
                    "SELECT fhir_resource_id FROM fhir_patients "
                    "WHERE fhir_resource_id = %s LIMIT 1",
                    (emr_pid_val,),
                )
                fp_row = cur.fetchone()
                if fp_row:
                    _fhir_id_cache[pid] = (fp_row["fhir_resource_id"], _time.time())
                    return fp_row["fhir_resource_id"]

            # Path 3: exact match by name + DOB (prefix/fuzzy match is unsafe in healthcare)
            fname = (p_row.get("first_name") or p_row.get("fname") or "").strip().lower()
            lname = (p_row.get("last_name") or p_row.get("lname") or "").strip().lower()
            dob = p_row.get("dob")
            if fname and lname and dob:
                cur.execute(
                    "SELECT fhir_resource_id FROM fhir_patients "
                    "WHERE LOWER(given_name) = %s "
                    "AND LOWER(family_name) = %s AND birth_date = %s",
                    (fname, lname, str(dob)),
                )
                fp_matches = cur.fetchall()
                if len(fp_matches) > 1:
                    logger.warning(
                        "Ambiguous FHIR patient match for pid=%s: %d candidates found, skipping",
                        pid,
                        len(fp_matches),
                    )
                    return None
                if fp_matches:
                    _fhir_id_cache[pid] = (fp_matches[0]["fhir_resource_id"], _time.time())
                    return fp_matches[0]["fhir_resource_id"]
    except Exception as exc:
        logger.warning("_get_fhir_resource_id fallback failed for pid=%s: %s", pid, exc)

    return None


def _get_fhir_encounters_for_patient(fhir_patient_id: str, pid: int) -> list[dict]:
    """Query fhir_encounters table and return formatted encounter dicts.

    Parameters
    ----------
    fhir_patient_id:
        The FHIR resource UUID stored in fhir_encounters.fhir_patient_id.
    pid:
        Internal patient ID, included in each returned dict as "pid".
    """
    results: list[dict] = []
    try:
        with raf_cursor() as cur:
            cur.execute(
                """SELECT fe.id AS encounter_id,
                          fe.period_start AS date,
                          COALESCE(fe.type_display, fe.encounter_type) AS reason,
                          fe.status,
                          fe.fhir_encounter_id,
                          fe.provider_name,
                          fe.reason_codes,
                          fe.service_provider
                   FROM fhir_encounters fe
                   WHERE fe.fhir_patient_id = %s
                   ORDER BY fe.period_start DESC""",
                (fhir_patient_id,),
            )
            for r in cur.fetchall():
                _rc = r.get("reason_codes") or ""
                results.append(
                    {
                        "encounter_id": r["encounter_id"],
                        "pid": pid,
                        "date": str(r["date"]) if r.get("date") else None,
                        "reason": r.get("reason") or "Office Visit",
                        "provider": r.get("provider_name") or "",
                        "provider_id": None,
                        "provider_fname": r.get("provider_name") or "",
                        "provider_lname": "",
                        "facility": r.get("service_provider") or "",
                        "has_notes": 1 if _rc else 0,
                        "notes": _rc,
                        "note_text": _rc,
                        "status": r.get("status") or "finished",
                        "source": "fhir",
                    }
                )
    except Exception as exc:
        logger.error("_get_fhir_encounters_for_patient error fhir_patient_id=%s: %s", fhir_patient_id, exc)
    return results

def patient_is_fhir(pid: int, tenant_id: str) -> bool:
    """Return True when *pid* belongs to an active FHIR/REST connection (emr_patient_matches.id)."""
    return _patient_in_fhir_matches(pid, tenant_id)


def patient_is_accessible(pid: int, tenant_id: str) -> bool:
    """Return True when the router should allow access to *pid*.

    Combines the two tenant/connection guards used throughout the router.
    Includes direct emr_patient_matches.id lookup for FHIR patients.
    """
    return (
        _patient_belongs_to_tenant(pid, tenant_id)
        or _patient_in_active_connection(pid, tenant_id=tenant_id)
        or _patient_in_fhir_matches(pid, tenant_id=tenant_id)
    )


# ---------------------------------------------------------------------------
# Internal list helpers
# ---------------------------------------------------------------------------


def _list_fhir_patients(
    limit: int, offset: int, search: str = "", tenant_id: str | None = None
) -> tuple[list[dict], int]:
    """List patients for FHIR/REST connections from the patients table.

    FHIR patients now have proper rows in the patients table (data_source='fhir',
    emr_connection_id set).  Using the patients table avoids duplicate counting
    that occurs with emr_patient_matches.
    """
    with raf_cursor() as cur:
        where = "WHERE p.is_active = 1 AND p.data_source = 'fhir'"
        params: list = []
        if tenant_id is not None:
            where += " AND p.tenant_id = %s"
            params.append(tenant_id)
        if search:
            where += " AND (p.first_name LIKE %s OR p.last_name LIKE %s OR CAST(p.id AS CHAR) LIKE %s)"
            like = f"%{search}%"
            params.extend([like, like, like])

        cur.execute(
            f"SELECT COUNT(*) AS cnt FROM patients p {where}",
            params,
        )
        total = (cur.fetchone() or {}).get("cnt", 0)

        cur.execute(
            f"""SELECT p.id AS pid, p.first_name AS fname,
                       p.last_name AS lname, p.dob AS DOB,
                       p.sex, p.mrn
                FROM patients p
                {where}
                ORDER BY p.last_name, p.first_name
                LIMIT %s OFFSET %s""",
            (*params, limit, offset),
        )
        rows = cur.fetchall()

    patients = []
    for r in rows:
        patients.append(
            {
                "pid": r["pid"],
                "fname": r["fname"] or "",
                "lname": r["lname"] or "",
                "DOB": str(r["DOB"]) if r["DOB"] else "",
                "sex": r["sex"] or "",
                "mrn": r.get("mrn") or "",
                "external_id": "",
            }
        )
    return patients, total


def _list_raf_patients(
    limit: int,
    offset: int,
    search: str = "",
    tenant_id: str | None = None,
    only_uploaded: bool = False,
) -> tuple[list[dict], int]:
    """List patients from the raf_intelligence.patients table."""
    with raf_cursor() as cur:
        where = "WHERE is_active = 1"
        params: list = []
        if tenant_id is not None:
            where += " AND tenant_id = %s"
            params.append(tenant_id)
        if only_uploaded:
            where += " AND data_source = 'upload'"
        if search:
            if search.isdigit():
                where += " AND id = %s"
                params.append(int(search))
            else:
                like = f"%{search}%"
                where += (
                    " AND (CONCAT(first_name, ' ', last_name) LIKE %s"
                    " OR first_name LIKE %s"
                    " OR last_name LIKE %s"
                    " OR mrn LIKE %s)"
                )
                params.extend([like, like, like, like])

        cur.execute(f"SELECT COUNT(*) AS cnt FROM patients {where}", params)
        total = (cur.fetchone() or {}).get("cnt", 0)

        cur.execute(
            f"""SELECT id AS pid,
                       first_name AS fname,
                       last_name AS lname,
                       middle_name AS mname,
                       dob AS DOB,
                       sex,
                       race,
                       ethnicity,
                       preferred_language AS language,
                       address AS street,
                       city,
                       state,
                       zip AS postal_code,
                       phone AS phone_cell,
                       phone AS phone_home,
                       email,
                       mrn,
                       insurance_type,
                       data_source,
                       created_at AS created_date
                FROM patients
                {where}
                ORDER BY last_name, first_name
                LIMIT %s OFFSET %s""",
            (*params, limit, offset),
        )
        rows = cur.fetchall()

    from decimal import Decimal
    _PHI_EXCLUDED_FIELDS = {"ssn", "social_security_number", "ssn_last4"}
    patients = []
    for r in rows:
        p: dict[str, Any] = {}
        for k, v in r.items():
            if k.lower() in _PHI_EXCLUDED_FIELDS:
                continue
            if hasattr(v, "isoformat"):
                p[k] = v.isoformat()
            elif isinstance(v, Decimal):
                p[k] = float(v)
            elif isinstance(v, int):
                p[k] = v
            else:
                p[k] = v if v is not None else ""
        patients.append(p)
    return patients, total


# ---------------------------------------------------------------------------
# svc_list_patients
# ---------------------------------------------------------------------------


@tenant_cached("patient_list", ttl=TTL_PATIENT_LIST)
def svc_list_patients(
    limit: int,
    offset: int,
    search: str,
    year: int | None,
    tenant_id: str,
) -> dict[str, Any]:
    """Fetch paginated patient list and enrich with RAF scores.

    Raises RuntimeError on unrecoverable database errors (router converts to 500).
    """
    try:
        conn_type = _active_connection_type()
        if conn_type in ("fhir_r4", "rest_api"):
            patients, total = _list_fhir_patients(limit, offset, search, tenant_id=tenant_id)
        elif _has_active_emr_connection():
            # Use raf_intelligence.patients (synced data) — querying OpenEMR
            # directly would miss patients already synced into raf DB.
            patients, total = _list_raf_patients(
                limit, offset, search, tenant_id=tenant_id
            )
        else:
            patients, total = _list_raf_patients(
                limit, offset, search, tenant_id=tenant_id, only_uploaded=True
            )
    except Exception as exc:
        logger.error("svc_list_patients error: %s", exc)
        raise RuntimeError("Internal server error") from exc

    # Enrich with RAF scores
    try:
        pids = [p["pid"] for p in patients if p.get("pid")]
        if pids:
            placeholders = ",".join(["%s"] * len(pids))
            with raf_cursor() as cur:
                _tid = int(tenant_id)
                _sf, _sp = active_patients_subquery(_tid)
                cur.execute(
                    f"""
                    SELECT patient_id, final_raf, hcc_count,
                           demographic_score, disease_score, interaction_score
                    FROM raf_scores
                    WHERE patient_id IN ({placeholders})
                      AND measurement_year = %s
                      AND {_sf}
                      AND raf_scores.tenant_id = %s
                    ORDER BY calculated_at DESC
                    """,
                    (*pids, year or _date.today().year, *_sp, _tid),
                )
                raf_map: dict[int, dict] = {}
                for row in cur.fetchall():
                    pid_val = int(row["patient_id"])
                    if pid_val not in raf_map:
                        raf_map[pid_val] = row
            for p in patients:
                r = raf_map.get(p["pid"])
                if r:
                    p["raf_score"] = float(r["final_raf"]) if r.get("final_raf") else None
                    p["hcc_count"] = int(r["hcc_count"]) if r.get("hcc_count") else 0
                    p["demographic_score"] = (
                        float(r["demographic_score"]) if r.get("demographic_score") else None
                    )
                    p["disease_score"] = (
                        float(r["disease_score"]) if r.get("disease_score") else None
                    )
                    p["interaction_score"] = (
                        float(r["interaction_score"]) if r.get("interaction_score") else None
                    )
    except Exception as exc:
        logger.warning("svc_list_patients: RAF enrichment failed: %s", exc)

    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "search": search,
        "patients": patients,
    }


# ---------------------------------------------------------------------------
# svc_patients_with_encounters
# ---------------------------------------------------------------------------


def svc_patients_with_encounters(limit: int, tenant_id: str | None = None) -> dict[str, Any]:
    """Return patients that have at least one encounter."""
    if _has_active_emr_connection():
        patients = emr.get_patients_with_encounters(limit=limit)
        return {"total": len(patients), "patients": patients}

    try:
        with raf_cursor() as cur:
            cur.execute(
                """
                SELECT DISTINCT p.id AS pid, p.first_name AS fname, p.last_name AS lname,
                       p.dob AS DOB, p.sex
                FROM patients p
                JOIN raf_encounter_analysis ea ON ea.patient_id = p.id
                WHERE p.is_active = 1 AND p.data_source = 'upload'
                  AND p.tenant_id = %s AND ea.tenant_id = %s
                LIMIT %s
                """,
                (tenant_id, tenant_id, limit),
            )
            patients = [dict(r) for r in cur.fetchall()]
        return {"total": len(patients), "patients": patients}
    except Exception as exc:
        logger.error("svc_patients_with_encounters (upload fallback) error: %s", exc)
        return {"total": 0, "patients": []}


# ---------------------------------------------------------------------------
# svc_get_patient
# ---------------------------------------------------------------------------


def svc_get_patient(pid: int, tenant_id: str) -> dict[str, Any] | None:
    """Return patient demographics enriched with the latest RAF score.

    Returns None when the patient is not found.
    """
    patient = emr.get_patient(pid)
    if not patient:
        # Fallback: look up in raf_intelligence.patients (synced data)
        try:
            with raf_cursor() as cur:
                cur.execute(
                    """SELECT id AS pid, first_name AS fname, last_name AS lname,
                              middle_name AS mname, dob AS DOB,
                              COALESCE(sex, gender) AS sex, race, ethnicity,
                              preferred_language AS language, address AS street,
                              city, state, zip AS postal_code, phone AS phone_cell,
                              phone AS phone_home, email, mrn, insurance_type,
                              gender, data_source, created_at AS created_date
                       FROM patients WHERE id = %s AND is_active = 1 AND tenant_id = %s""",
                    (pid, tenant_id),
                )
                row = cur.fetchone()
                if row:
                    patient = {}
                    for k, v in row.items():
                        if hasattr(v, "isoformat"):
                            patient[k] = v.isoformat()
                        elif hasattr(v, "__float__"):
                            patient[k] = float(v)
                        else:
                            patient[k] = v if v is not None else ""
        except Exception as exc:
            logger.debug("Failed to fetch data: %s", exc)
    if not patient:
        # Third fallback: FHIR patient from emr_patient_matches
        fhir_row = _get_fhir_patient_row(pid, tenant_id=tenant_id)
        if fhir_row:
            patient = fhir_row

    if not patient:
        return None

    # Ensure mrn is always a non-empty string.  The patients VIEW exposes
    # pubpid AS mrn but pubpid is often blank for demo/imported patients.
    # Fall back to a synthetic "PID{pid}" so the UI never shows an empty MRN.
    if not patient.get("mrn"):
        emr_pid_val = patient.get("emr_pid") or patient.get("providerID") or ""
        patient["mrn"] = str(emr_pid_val).strip() if emr_pid_val else f"PID{pid}"

    raf_data: dict = {}
    for yr in [_date.today().year, _date.today().year - 1]:
        raf_data = get_raf_breakdown(pid, yr, tenant_id=tenant_id)
        if raf_data:
            break
    patient["raf_score"] = raf_data.get("raf_score")
    patient["raf_score_date"] = raf_data.get("calculated_at")
    patient["raf_score_year"] = raf_data.get("measurement_year")
    return patient


# ---------------------------------------------------------------------------
# svc_get_clinical_notes
# ---------------------------------------------------------------------------


def svc_get_clinical_notes(pid: int, encounter_id: int) -> list[dict]:
    """Return clinical notes for a specific encounter."""
    return emr.get_clinical_notes(encounter_id)


# ---------------------------------------------------------------------------
# svc_get_encounters
# ---------------------------------------------------------------------------


def svc_get_encounters(pid: int, year: int | None, tenant_id: str) -> dict[str, Any]:
    """Return all encounters for *pid*, with enrichment from cached analysis."""
    emr_pid = _get_emr_pid(pid, tenant_id=tenant_id) or pid

    # For FHIR patients, skip the direct OpenEMR DB query and go straight to
    # the FHIR-specific tables (fhir_encounters + raf_encounter_analysis).
    is_fhir = _patient_in_fhir_matches(pid, tenant_id=tenant_id)

    encounters: list[dict] = []
    if is_fhir:
        external_id = _get_fhir_resource_id(pid, tenant_id=tenant_id)
        if external_id:
            encounters = _get_fhir_encounters_for_patient(external_id, pid)
    else:
        try:
            encounters = emr.get_encounters(emr_pid)
        except Exception as exc:
            logger.error("svc_get_encounters error pid=%s: %s", pid, exc)
            encounters = []

    # Fallback: load from raf_intelligence.encounters
    if not encounters and not is_fhir:
        try:
            with raf_cursor() as cur:
                cur.execute(
                    """SELECT e.id AS encounter_id, e.patient_id AS pid,
                              e.encounter_date AS date, e.encounter_type AS reason,
                              e.facility, e.provider_id, e.notes, e.status,
                              pr.first_name AS provider_fname, pr.last_name AS provider_lname
                       FROM encounters e
                       LEFT JOIN providers pr ON pr.id = e.provider_id
                       WHERE e.patient_id = %s
                       ORDER BY e.encounter_date DESC""",
                    (pid,),
                )
                raf_rows = cur.fetchall()
            encounters = []
            for r in raf_rows:
                encounters.append(
                    {
                        "encounter_id": r["encounter_id"],
                        "pid": r["pid"],
                        "date": str(r["date"]) if r["date"] else None,
                        "reason": r["reason"],
                        "facility": r["facility"],
                        "provider_id": r["provider_id"],
                        "provider_fname": r.get("provider_fname", ""),
                        "provider_lname": r.get("provider_lname", ""),
                        "has_notes": 1 if r.get("notes") else 0,
                        "notes": r.get("notes", ""),
                        "note_text": r.get("notes", ""),
                        "status": r.get("status", "completed"),
                    }
                )
        except Exception as exc2:
            logger.error("svc_get_encounters fallback error pid=%s: %s", pid, exc2)

    if year is not None:
        encounters = [e for e in encounters if str(e.get("date", ""))[:4] == str(year)]

    # Enrich encounters with cached analysis results and SOAP note text
    try:
        analysis_map: dict[int, dict] = {}
        try:
            with raf_cursor() as cur:
                cur.execute(
                    "SELECT encounter_id, analysis_json, overall_score, dx_count, "
                    "suspect_count, hcc_opportunity_count, created_at "
                    "FROM raf_encounter_analysis WHERE patient_id = %s",
                    (pid,),
                )
                for row in cur.fetchall():
                    eid = row["encounter_id"]
                    analysis_data = {}
                    if row.get("analysis_json"):
                        try:
                            analysis_data = (
                                _json.loads(row["analysis_json"])
                                if isinstance(row["analysis_json"], str)
                                else row["analysis_json"]
                            )
                        except Exception as exc:
                            logger.debug("Failed to fetch data: %s", exc)
                    analysis_map[eid] = {
                        "diagnoses": analysis_data.get("diagnoses", []),
                        "pipeline": analysis_data.get("pipeline", {}),
                        "_meta": analysis_data.get("_meta", {}),
                        "overall_score": float(row["overall_score"])
                        if row.get("overall_score")
                        else None,
                        "dx_count": row.get("dx_count", 0),
                        "suspect_count": row.get("suspect_count", 0),
                        "hcc_opportunity_count": row.get("hcc_opportunity_count", 0),
                        "analyzed_at": row["created_at"].isoformat()
                        if hasattr(row.get("created_at"), "isoformat")
                        else str(row.get("created_at", "")),
                    }
        except Exception as ae:
            logger.debug("Could not load cached analysis for pid=%s: %s", pid, ae)

        # Fetch actual SOAP note text per encounter
        notes_map: dict[int, str] = {}
        try:
            from app.db import openemr_cursor

            with openemr_cursor() as cur:
                cur.execute(
                    """
                    SELECT f.encounter,
                           CONCAT_WS('\\n\\n',
                               IF(fs.subjective <> '', CONCAT('S: ', fs.subjective), NULL),
                               IF(fs.objective  <> '', CONCAT('O: ', fs.objective),  NULL),
                               IF(fs.assessment <> '', CONCAT('A: ', fs.assessment), NULL),
                               IF(fs.plan       <> '', CONCAT('P: ', fs.plan),       NULL)
                           ) AS note_text
                    FROM form_soap fs
                    JOIN forms f ON f.form_id = fs.id AND f.formdir = 'soap'
                    WHERE fs.pid = %s AND fs.activity = 1
                    ORDER BY f.date DESC
                    """,
                    (emr_pid,),
                )
                for row in cur.fetchall():
                    eid = row["encounter"]
                    if eid not in notes_map:
                        notes_map[eid] = row.get("note_text") or ""
        except Exception as exc:
            logger.debug("Failed to fetch data: %s", exc)

        for enc in encounters:
            eid = enc.get("encounter_id") or enc.get("encounter")
            if eid and eid in analysis_map:
                enc["cached_analysis"] = analysis_map[eid]
                enc["analysis"] = analysis_map[eid]
            if eid and eid in notes_map:
                enc["has_notes"] = True
                enc["notes"] = notes_map[eid]
            else:
                enc["has_notes"] = enc.get("has_notes", False)
    except Exception as enrich_exc:
        logger.debug("Encounter enrichment failed pid=%s: %s", pid, enrich_exc)

    return {
        "pid": pid,
        "count": len(encounters),
        "encounters": encounters,
    }


# ---------------------------------------------------------------------------
# svc_get_medications
# ---------------------------------------------------------------------------


def svc_get_medications(pid: int, year: int | None, tenant_id: str) -> dict[str, Any]:
    """Return all prescriptions for *pid*, with RAF DB fallback."""
    emr_pid = _get_emr_pid(pid, tenant_id=tenant_id) or pid
    is_fhir = _patient_in_fhir_matches(pid, tenant_id=tenant_id)
    medications: list[dict] = []

    if is_fhir:
        # FHIR patients: try patient_medications by pid first, then raf_patient_id
        fhir_row = _get_fhir_patient_row(pid, tenant_id=tenant_id)
        raf_patient_id = fhir_row.get("raf_patient_id") if fhir_row else None
        lookup_ids = [pid]
        if raf_patient_id and raf_patient_id != pid:
            lookup_ids.append(raf_patient_id)
        for _med_pid in lookup_ids:
            if medications:
                break
            try:
                with raf_cursor() as cur:
                    cur.execute(
                        "SELECT medication_name AS drug, dosage, frequency, "
                        "purpose AS note, start_date, status "
                        "FROM patient_medications "
                        "WHERE patient_id = %s AND status = 'active' ORDER BY medication_name",
                        (_med_pid,),
                    )
                    for r in cur.fetchall():
                        medications.append(
                            {
                                "drug": r.get("drug") or "",
                                "dosage": r.get("dosage") or "",
                                "form": "",
                                "frequency": r.get("frequency") or "",
                                "note": r.get("note") or "",
                                "start_date": str(r["start_date"]) if r.get("start_date") else None,
                                "active": 1,
                                "source": "fhir",
                            }
                        )
            except Exception as exc:
                logger.error("svc_get_medications FHIR error pid=%s: %s", pid, exc)
        # FHIR fallback: pull from fhir_medications table
        if not medications:
            fhir_rid = _get_fhir_resource_id(pid, tenant_id=tenant_id)
            if fhir_rid:
                try:
                    with raf_cursor() as cur:
                        cur.execute(
                            "SELECT medication_display AS drug, dosage_text AS dosage, "
                            "status, authored_on AS start_date "
                            "FROM fhir_medications WHERE fhir_patient_id = %s "
                            "ORDER BY authored_on DESC",
                            (fhir_rid,),
                        )
                        for r in cur.fetchall():
                            medications.append(
                                {
                                    "drug": r.get("drug") or "",
                                    "dosage": r.get("dosage") or "",
                                    "form": "",
                                    "frequency": "",
                                    "note": "",
                                    "start_date": str(r["start_date"]) if r.get("start_date") else None,
                                    "active": 1,
                                    "source": "fhir",
                                }
                            )
                except Exception as exc:
                    logger.warning("svc_get_medications fhir_medications fallback failed: %s", exc)
    else:
        try:
            medications = emr.get_medications(emr_pid, year=year)
        except Exception as exc:
            logger.error("svc_get_medications error pid=%s: %s", pid, exc)
            medications = []

    if not medications and not is_fhir:
        try:
            with raf_cursor() as cur:
                cur.execute(
                    "SELECT medication_name AS drug, dosage, form, frequency, "
                    "purpose AS note, start_date, status, "
                    "prescriber_id FROM patient_medications "
                    "WHERE patient_id = %s AND status = 'active' ORDER BY medication_name",
                    (pid,),
                )
                for r in cur.fetchall():
                    medications.append(
                        {
                            "drug": r["drug"],
                            "dosage": r.get("dosage", ""),
                            "form": r.get("form", ""),
                            "frequency": r.get("frequency", ""),
                            "note": r.get("note", ""),
                            "start_date": str(r["start_date"]) if r.get("start_date") else None,
                            "active": 1,
                        }
                    )
        except Exception as exc:
            logger.debug("Failed to fetch data: %s", exc)

    response: dict[str, Any] = {
        "pid": pid,
        "count": len(medications),
        "medications": medications,
    }
    if year is not None:
        response["year"] = year
    return response


# ---------------------------------------------------------------------------
# svc_get_medication_gaps
# ---------------------------------------------------------------------------


def svc_get_medication_gaps(pid: int, year: int, tenant_id: str) -> dict[str, Any]:
    """Return medication-linked diagnoses not billed in *year*."""
    from app.services.icd_validator import get_description, validate_code

    if not year:
        year = _date.today().year

    emr_pid = _get_emr_pid(pid, tenant_id=tenant_id) or pid

    gaps = emr.get_medication_diagnosis_gaps(emr_pid, year)

    # FHIR fallback: if no gaps from EMR, check patient_medications + patient_conditions
    if not gaps and _patient_in_fhir_matches(pid, tenant_id=tenant_id):
        try:
            with raf_cursor() as _mc:
                _mc.execute(
                    "SELECT medication_name, reason_code, reason_display FROM patient_medications WHERE patient_id = %s AND status = 'active'",
                    (pid,),
                )
                meds = _mc.fetchall()
                if meds:
                    # Get billed ICD codes relevant to the target year.
                    # Include conditions with no onset date (unknown onset) and
                    # those whose onset is on or before the end of the target year.
                    _mc.execute(
                        "SELECT DISTINCT icd10_code FROM patient_conditions"
                        " WHERE patient_id = %s"
                        " AND (onset_date IS NULL OR YEAR(onset_date) <= %s) LIMIT 500",
                        (pid, year),
                    )
                    billed = {r["icd10_code"] for r in _mc.fetchall() if r.get("icd10_code")}

                    for med in meds:
                        reason_code = (med.get("reason_code") or "").strip()
                        if reason_code and reason_code not in billed:
                            gaps.append({
                                "icd_code": reason_code,
                                "drug": med.get("medication_name") or "",
                                "active": 1,
                            })
        except Exception as exc:
            logger.warning("svc_get_medication_gaps FHIR fallback failed pid=%s: %s", pid, exc)

    for gap in gaps:
        code = gap.get("icd_code", "")
        if code:
            gap["description"] = get_description(code) or ""
            gap["valid_icd10"] = validate_code(code)

    return {
        "pid": pid,
        "year": year,
        "gap_count": len(gaps),
        "gaps": gaps,
    }


# ---------------------------------------------------------------------------
# svc_get_diagnoses
# ---------------------------------------------------------------------------


def svc_get_diagnoses(pid: int, tenant_id: str) -> dict[str, Any]:
    """Return all ICD-10 billing codes for *pid*, enriched with descriptions."""
    from app.services.icd_validator import get_description, validate_code

    emr_pid = _get_emr_pid(pid, tenant_id=tenant_id) or pid
    is_fhir = _patient_in_fhir_matches(pid, tenant_id=tenant_id)
    codes: list[dict] = []

    if is_fhir:
        # FHIR patients: pull ICD-10 codes from raf_patient_hcc via pid (or raf_patient_id)
        fhir_row = _get_fhir_patient_row(pid, tenant_id=tenant_id)
        raf_patient_id = fhir_row.get("raf_patient_id") if fhir_row else None
        lookup_ids = [pid]
        if raf_patient_id and raf_patient_id != pid:
            lookup_ids.append(raf_patient_id)
        for _dx_pid in lookup_ids:
            if codes:
                break
            try:
                import json as _json
                with raf_cursor() as cur:
                    cur.execute(
                        """SELECT hcc_code, icd10_codes, measurement_year, updated_at
                           FROM raf_patient_hcc
                           WHERE patient_id = %s
                           ORDER BY measurement_year DESC""",
                        (_dx_pid,),
                    )
                    for r in cur.fetchall():
                        icd_list: list[str] = []
                        raw = r.get("icd10_codes")
                        if raw:
                            try:
                                icd_list = _json.loads(raw) if isinstance(raw, str) else raw
                            except Exception as exc:
                                logger.debug("Failed to fetch data: %s", exc)
                        for code in icd_list:
                            codes.append(
                                {
                                    "code": code,
                                    "code_text": "",
                                    "code_type": "ICD10",
                                    "hcc_code": r.get("hcc_code"),
                                    "encounter_date": str(r["updated_at"])[:10]
                                    if r.get("updated_at")
                                    else None,
                                    "source": "fhir",
                                }
                            )
            except Exception as exc:
                logger.error("svc_get_diagnoses FHIR error pid=%s: %s", pid, exc)
        # Fallback: pull from fhir_conditions if raf_patient_hcc had nothing
        if not codes:
            fhir_rid = _get_fhir_resource_id(pid, tenant_id=tenant_id)
            if fhir_rid:
                try:
                    with raf_cursor() as cur:
                        cur.execute(
                            "SELECT DISTINCT fc.icd10_codes AS code, fc.display AS code_text, "
                            "fc.onset_date AS encounter_date "
                            "FROM fhir_conditions fc "
                            "WHERE fc.fhir_patient_id = %s "
                            "AND fc.clinical_status IN ('active', 'recurrence', 'relapse', '') "
                            "ORDER BY fc.onset_date DESC LIMIT 500",
                            (fhir_rid,),
                        )
                        for r in cur.fetchall():
                            codes.append(
                                {
                                    "code": r["code"],
                                    "code_text": r["code_text"],
                                    "code_type": "ICD10",
                                    "hcc_code": None,
                                    "encounter_date": str(r["encounter_date"])
                                    if r.get("encounter_date")
                                    else None,
                                    "source": "fhir",
                                }
                            )
                except Exception as exc:
                    logger.warning("svc_get_diagnoses fhir_conditions fallback failed: %s", exc)
    else:
        try:
            codes = emr.get_billing_codes(emr_pid)
        except Exception as exc:
            logger.error("svc_get_diagnoses error pid=%s: %s", pid, exc)
            codes = []

    if not codes and not is_fhir:
        try:
            with raf_cursor() as cur:
                cur.execute(
                    "SELECT DISTINCT ed.icd10_code AS code, ed.description AS code_text, "
                    "ed.hcc_code, ed.is_primary, e.encounter_date "
                    "FROM encounter_diagnoses ed "
                    "JOIN encounters e ON e.id = ed.encounter_id "
                    "WHERE ed.patient_id = %s ORDER BY e.encounter_date DESC, ed.is_primary DESC",
                    (pid,),
                )
                for r in cur.fetchall():
                    codes.append(
                        {
                            "code": r["code"],
                            "code_text": r["code_text"],
                            "code_type": "ICD10",
                            "hcc_code": r.get("hcc_code"),
                            "encounter_date": str(r["encounter_date"])
                            if r.get("encounter_date")
                            else None,
                        }
                    )
        except Exception as exc:
            logger.debug("Failed to fetch data: %s", exc)

    for row in codes:
        code = row.get("code", "")
        if code:
            row["description"] = get_description(code) or row.get("code_text", "")
            row["valid_icd10"] = validate_code(code)

    return {
        "pid": pid,
        "count": len(codes),
        "diagnoses": codes,
    }


# ---------------------------------------------------------------------------
# svc_get_procedures
# ---------------------------------------------------------------------------


def svc_get_procedures(pid: int, tenant_id: str) -> dict[str, Any]:
    """Return CPT procedure codes with condition hints for *pid*."""
    emr_pid = _get_emr_pid(pid, tenant_id=tenant_id) or pid

    cpt_rows = emr.get_cpt_codes(emr_pid)

    hints = emr.CPT_CONDITION_HINTS
    for row in cpt_rows:
        code = str(row.get("code") or "").strip()
        row["condition_hint"] = hints.get(code)

    return {
        "pid": pid,
        "count": len(cpt_rows),
        "procedures": cpt_rows,
    }


# ---------------------------------------------------------------------------
# svc_get_problem_list
# ---------------------------------------------------------------------------


def svc_get_problem_list(pid: int, year: int | None, tenant_id: str) -> dict[str, Any]:
    """Return active medical problems for *pid*, with RAF DB fallback."""
    emr_pid = _get_emr_pid(pid, tenant_id=tenant_id) or pid

    try:
        problems = emr.get_problem_list(emr_pid, year=year)
    except Exception as exc:
        logger.error("svc_get_problem_list error pid=%s: %s", pid, exc)
        problems = []

    if not problems:
        try:
            with raf_cursor() as cur:
                cur.execute(
                    "SELECT icd10_code AS diagnosis, description AS title, "
                    "hcc_code, onset_date AS begdate, status, severity "
                    "FROM patient_conditions WHERE patient_id = %s ORDER BY onset_date DESC LIMIT 500",
                    (pid,),
                )
                for r in cur.fetchall():
                    problems.append(
                        {
                            "title": r["title"],
                            "diagnosis": f"ICD10:{r['diagnosis']}" if r.get("diagnosis") else "",
                            "begdate": str(r["begdate"]) if r.get("begdate") else None,
                            "activity": "1",
                            "icd10_code": r.get("diagnosis"),
                            "diagnosis_code": r.get("diagnosis"),
                            "has_icd_code": bool(r.get("diagnosis")),
                            "hcc_code": r.get("hcc_code"),
                            "severity": r.get("severity"),
                        }
                    )
        except Exception as exc:
            logger.debug("Failed to fetch patient_conditions: %s", exc)

    # Third fallback: derive from raf_patient_hcc (always populated by RAF calc)
    if not problems:
        try:
            with raf_cursor() as cur:
                cur.execute(
                    "SELECT h.hcc_code, h.hcc_description, h.icd10_code "
                    "FROM raf_patient_hcc h WHERE h.patient_id = %s AND h.is_trumped = 0 "
                    "ORDER BY h.hcc_code",
                    (pid,),
                )
                for r in cur.fetchall():
                    problems.append(
                        {
                            "title": r.get("hcc_description") or f"HCC {r['hcc_code']}",
                            "diagnosis": f"ICD10:{r['icd10_code']}" if r.get("icd10_code") else "",
                            "begdate": None,
                            "activity": "1",
                            "icd10_code": r.get("icd10_code"),
                            "diagnosis_code": r.get("icd10_code"),
                            "has_icd_code": bool(r.get("icd10_code")),
                            "hcc_code": r.get("hcc_code"),
                        }
                    )
        except Exception as exc:
            logger.debug("Failed to fetch raf_patient_hcc: %s", exc)

    for p in problems:
        if "icd10_code" not in p:
            raw_dx = p.get("diagnosis") or ""
            icd10 = raw_dx.split(":")[-1].strip() if ":" in raw_dx else raw_dx.strip()
            p["icd10_code"] = icd10 or None
            p["diagnosis_code"] = icd10 or None
            p["has_icd_code"] = bool(icd10)

    return {
        "pid": pid,
        "count": len(problems),
        "problems": problems,
    }


# ---------------------------------------------------------------------------
# svc_get_recapture_gaps
# ---------------------------------------------------------------------------


def svc_get_recapture_gaps(pid: int, year: int | None, tenant_id: str) -> dict[str, Any]:
    """Return active problems not billed in *year*."""
    if year is None:
        year = _date.today().year

    emr_pid = _get_emr_pid(pid, tenant_id=tenant_id) or pid

    gaps = emr.get_recapture_gaps(emr_pid, year)

    return {
        "pid": pid,
        "year": year,
        "gap_count": len(gaps),
        "recapture_gaps": gaps,
    }


# ---------------------------------------------------------------------------
# svc_get_vitals_suspects
# ---------------------------------------------------------------------------


def svc_get_vitals_suspects(
    pid: int, year: int | None, tenant_id: str, patient: dict
) -> dict[str, Any]:
    """Return vitals-based suspect conditions for *pid*."""
    emr_pid = _get_emr_pid(pid, tenant_id=tenant_id) or pid

    try:
        all_diagnoses = emr.get_all_patient_diagnoses(emr_pid)
        existing_codes = [d.get("icd_code", "") for d in all_diagnoses]
    except Exception as exc:
        logger.warning("svc_get_vitals_suspects: could not fetch diagnoses pid=%s: %s", pid, exc)
        existing_codes = []

    suspects = emr.detect_vitals_suspects(emr_pid, existing_diagnoses=existing_codes, year=year)

    try:
        trends = emr.get_vitals_trends(emr_pid, year=year)  # type: ignore[attr-defined]
        latest_vitals: dict[str, Any] = trends.get("latest_vitals") or {}
    except Exception as exc:
        logger.warning("svc_get_vitals_suspects: could not fetch trends pid=%s: %s", pid, exc)
        latest_vitals = {}

    # FHIR fallback for vitals
    if not latest_vitals:
        try:
            fhir_ext_id = _get_fhir_resource_id(pid, tenant_id)
            if fhir_ext_id:
                with raf_cursor() as _vc:
                    _vc.execute(
                        """SELECT code_display, value_numeric, value_string, unit, effective_date
                           FROM fhir_observations
                           WHERE fhir_patient_id = %s AND category = 'vital-signs'
                           ORDER BY effective_date DESC LIMIT 20""",
                        (fhir_ext_id,),
                    )
                    vrows = _vc.fetchall()
                    if vrows:
                        for vr in vrows:
                            name = (vr.get("code_display") or "").lower().replace(" ", "_")
                            val = vr.get("value_numeric") or vr.get("value_string") or ""
                            if name and name not in latest_vitals:
                                try:
                                    latest_vitals[name] = float(val) if val else None
                                except (ValueError, TypeError):
                                    latest_vitals[name] = val
                        if latest_vitals:
                            latest_vitals["date"] = str(vrows[0]["effective_date"]) if vrows[0].get("effective_date") else None
                            latest_vitals["source"] = "fhir"
        except Exception as exc:
            logger.warning("svc_get_vitals_suspects FHIR fallback failed: %s", exc)

    patient_name = (
        f"{patient.get('fname', '')} {patient.get('lname', '')}".strip()
        or f"Patient {pid}"
    )

    suspects.sort(key=lambda s: s.get("confidence", 0), reverse=True)

    return {
        "pid": pid,
        "patient_name": patient_name,
        "count": len(suspects),
        "suspects": suspects,
        "vitals_suspects": suspects,
        "latest_vitals": latest_vitals,
    }


# ---------------------------------------------------------------------------
# svc_get_lab_suspects
# ---------------------------------------------------------------------------


def svc_get_lab_suspects(
    pid: int, year: int | None, tenant_id: str, patient: dict
) -> dict[str, Any]:
    """Return rule-based lab/vitals suspect conditions for *pid*."""
    from app.services.lab_suspect_engine import run_lab_suspect_scan

    emr_pid = _get_emr_pid(pid, tenant_id=tenant_id) or pid

    result = run_lab_suspect_scan(emr_pid, year=year)

    patient_name = (
        f"{patient.get('fname', '')} {patient.get('lname', '')}".strip()
        or f"Patient {pid}"
    )

    resp: dict[str, Any] = {
        "pid": pid,
        "patient_name": patient_name,
        "year_filter": year,
        "notes_scanned": result["notes_scanned"],
        "lab_results_scanned": result.get("lab_results_scanned", 0),
        "vitals_rows_checked": result["vitals_rows_checked"],
        "existing_diagnosis_count": result["existing_diagnosis_count"],
        "note_suspects_count": len(result["note_suspects"]),
        "vitals_suspects_count": len(result["vitals_suspects"]),
        "total_suspects": len(result["all_suspects"]),
        "count": len(result["all_suspects"]),
        "suspects": result["all_suspects"],
    }

    # FHIR fallback: include lab results from fhir_observations
    if result.get("lab_results_scanned", 0) == 0:
        try:
            fhir_id = _get_fhir_resource_id(pid, tenant_id)
            if fhir_id:
                with raf_cursor() as _lc:
                    _lc.execute(
                        """SELECT code_display, value_numeric, value_string, unit, effective_date
                           FROM fhir_observations
                           WHERE fhir_patient_id = %s AND category = 'laboratory'
                           ORDER BY effective_date DESC LIMIT 200""",
                        (fhir_id,),
                    )
                    rows = _lc.fetchall()
                    if rows:
                        lab_results = [
                            {
                                "result_text": f"{r.get('code_display', '')}: {r.get('value_numeric') or r.get('value_string', '')} {r.get('unit', '')}".strip(),
                                "date": str(r["effective_date"]) if r.get("effective_date") else None,
                            }
                            for r in rows
                        ]
                        resp["labs"] = {"results": lab_results, "source": "fhir"}
                        resp["lab_results_scanned"] = len(lab_results)
        except Exception as exc:
            logger.warning("svc_get_lab_suspects FHIR lab fallback failed: %s", exc)

    return resp


# ---------------------------------------------------------------------------
# svc_get_comprehensive_profile
# ---------------------------------------------------------------------------


def svc_get_comprehensive_profile(
    pid: int, tenant_id: str, patient: dict
) -> dict[str, Any]:
    """Aggregate all available data sources into a single profile response."""
    emr_pid = _get_emr_pid(pid, tenant_id=tenant_id) or pid
    current_year = _date.today().year

    # Determine if this patient is a FHIR patient once, reuse throughout
    is_fhir = _patient_in_fhir_matches(pid, tenant_id=tenant_id)
    # Also check data_source from the patient dict (more reliable for patients table)
    if not is_fhir and patient.get("data_source") == "fhir":
        is_fhir = True
    fhir_external_id: str | None = None
    if is_fhir:
        fhir_external_id = _get_fhir_resource_id(pid, tenant_id=tenant_id)

    # --- Billing ----------------------------------------------------------
    icd10_codes = _safe_call("billing.icd10", emr.get_billing_codes, emr_pid, default=[])
    if not icd10_codes:
        try:
            with raf_cursor() as _bl_cur:
                if is_fhir and fhir_external_id:
                    # For FHIR patients: pull diagnoses from fhir_conditions
                    # Columns: icd10_codes (CSV string), display (description), onset_date
                    _bl_cur.execute(
                        "SELECT DISTINCT fc.icd10_codes AS code, fc.display AS code_text, "
                        "fc.onset_date AS encounter_date "
                        "FROM fhir_conditions fc "
                        "WHERE fc.fhir_patient_id = %s "
                        "AND fc.clinical_status IN ('active', 'recurrence', 'relapse', '') "
                        "ORDER BY fc.onset_date DESC LIMIT 500",
                        (fhir_external_id,),
                    )
                else:
                    _bl_cur.execute(
                        "SELECT DISTINCT ed.icd10_code AS code, ed.description AS code_text, "
                        "ed.hcc_code, e.encounter_date "
                        "FROM encounter_diagnoses ed "
                        "JOIN encounters e ON e.id = ed.encounter_id "
                        "WHERE ed.patient_id = %s ORDER BY e.encounter_date DESC",
                        (pid,),
                    )
                for r in _bl_cur.fetchall():
                    icd10_codes.append(
                        {
                            "code": r["code"],
                            "code_text": r["code_text"],
                            "code_type": "ICD10",
                            "hcc_code": r.get("hcc_code"),
                            "encounter_date": str(r["encounter_date"])
                            if r.get("encounter_date")
                            else None,
                        }
                    )
        except Exception as exc:
            logger.debug("Failed to fetch data: %s", exc)

    cpt_codes = _safe_call("billing.cpt", emr.get_cpt_codes, emr_pid, default=[])
    hints = emr.CPT_CONDITION_HINTS
    for row in cpt_codes:
        code = str(row.get("code") or "").strip()
        row.setdefault("condition_hint", hints.get(code))

    # --- Problem list -----------------------------------------------------
    problem_list = _safe_call("problem_list", emr.get_problem_list, emr_pid, default=[])
    if not problem_list:
        try:
            with raf_cursor() as _pl_cur:
                _pl_cur.execute(
                    """SELECT description AS title, icd10_code AS diagnosis,
                              hcc_code, severity, onset_date, status
                       FROM patient_conditions
                       WHERE patient_id = %s AND status = 'active'
                       ORDER BY description LIMIT 500""",
                    (pid,),
                )
                for r in _pl_cur.fetchall():
                    icd = r.get("diagnosis") or ""
                    problem_list.append(
                        {
                            "title": r.get("title") or "",
                            "diagnosis": icd,
                            "icd10_code": icd,
                            "diagnosis_code": icd,
                            "has_icd_code": bool(icd),
                            "hcc_code": r.get("hcc_code"),
                            "severity": r.get("severity") or "",
                            "begdate": str(r["onset_date"]) if r.get("onset_date") else None,
                            "activity": "1",
                            "source": "raf_db",
                        }
                    )
        except Exception as exc:
            logger.debug("Failed to fetch data: %s", exc)
    # FHIR fallback: pull from fhir_conditions if still empty
    if not problem_list and is_fhir and fhir_external_id:
        try:
            with raf_cursor() as _fc_cur:
                _fc_cur.execute(
                    """SELECT fc.display AS title, fc.icd10_codes,
                              fc.clinical_status AS status, fc.onset_date,
                              fc.hcc_codes
                       FROM fhir_conditions fc
                       WHERE fc.fhir_patient_id = %s
                       ORDER BY fc.onset_date DESC LIMIT 500""",
                    (fhir_external_id,),
                )
                for r in _fc_cur.fetchall():
                    import json as _json
                    codes = []
                    try:
                        codes = _json.loads(r.get("icd10_codes") or "[]")
                    except Exception:
                        pass
                    icd = codes[0] if codes else ""
                    hcc_codes = []
                    try:
                        hcc_codes = _json.loads(r.get("hcc_codes") or "[]")
                    except Exception:
                        pass
                    problem_list.append(
                        {
                            "title": r.get("title") or "",
                            "diagnosis": icd,
                            "icd10_code": icd,
                            "diagnosis_code": icd,
                            "has_icd_code": bool(icd),
                            "hcc_code": hcc_codes[0] if hcc_codes else None,
                            "severity": "",
                            "begdate": str(r["onset_date"]) if r.get("onset_date") else None,
                            "activity": "1",
                            "source": "fhir",
                        }
                    )
        except Exception as exc:
            logger.warning("FHIR problem_list fallback failed: %s", exc)
    for p in problem_list:
        raw_dx = p.get("diagnosis") or ""
        icd10 = raw_dx.split(":")[-1].strip() if ":" in raw_dx else raw_dx.strip()
        p["icd10_code"] = icd10 or None
        p["diagnosis_code"] = icd10 or None
        p["has_icd_code"] = bool(icd10)

    # --- Recapture gaps --------------------------------------------------
    recapture_gaps = _safe_call(
        "recapture_gaps", emr.get_recapture_gaps, emr_pid, current_year, default=[]
    )

    # --- Medications -----------------------------------------------------
    medications = _safe_call("medications", emr.get_medications, emr_pid, default=[])
    if not medications:
        try:
            with raf_cursor() as _med_cur:
                _med_cur.execute(
                    """SELECT medication_name AS drug, dosage, frequency, purpose,
                              start_date, prescriber AS provider
                       FROM patient_medications
                       WHERE patient_id = %s AND is_active = 1
                       ORDER BY medication_name""",
                    (pid,),
                )
                for r in _med_cur.fetchall():
                    medications.append(
                        {
                            "drug": r.get("drug") or "",
                            "dosage": r.get("dosage") or "",
                            "frequency": r.get("frequency") or "",
                            "purpose": r.get("purpose") or "",
                            "start_date": str(r["start_date"]) if r.get("start_date") else None,
                            "provider": r.get("provider") or "",
                            "source": "raf_db",
                        }
                    )
        except Exception as exc:
            logger.debug("Failed to fetch data: %s", exc)
    # FHIR fallback: pull from fhir_medications if still empty
    if not medications and is_fhir and fhir_external_id:
        try:
            with raf_cursor() as _fm_cur:
                _fm_cur.execute(
                    """SELECT medication_display AS drug, dosage_text AS dosage,
                              status, authored_on AS start_date
                       FROM fhir_medications
                       WHERE fhir_patient_id = %s
                       ORDER BY authored_on DESC""",
                    (fhir_external_id,),
                )
                for r in _fm_cur.fetchall():
                    medications.append(
                        {
                            "drug": r.get("drug") or "",
                            "dosage": r.get("dosage") or "",
                            "frequency": "",
                            "purpose": "",
                            "start_date": str(r["start_date"]) if r.get("start_date") else None,
                            "provider": "",
                            "source": "fhir",
                        }
                    )
        except Exception as exc:
            logger.warning("FHIR medications fallback failed: %s", exc)

    medication_diagnosis_gaps = _safe_call(
        "medication_diagnosis_gaps",
        emr.get_medication_diagnosis_gaps,  # type: ignore[attr-defined]
        emr_pid,
        current_year,
        default=[],
    )

    # --- Encounters ------------------------------------------------------
    encounters: list[dict] = []
    if is_fhir and fhir_external_id:
        # FHIR patients: query fhir_encounters by the external FHIR patient ID
        encounters = _get_fhir_encounters_for_patient(fhir_external_id, pid)
    else:
        # Non-FHIR patients: query raf_intelligence.encounters table
        try:
            with raf_cursor() as _enc_cur:
                _enc_cur.execute(
                    """SELECT e.id AS encounter_id, e.patient_id AS pid,
                              e.encounter_date AS date, e.encounter_type AS reason,
                              e.facility, e.provider_id, e.notes, e.status,
                              pr.first_name AS provider_fname, pr.last_name AS provider_lname
                       FROM encounters e
                       LEFT JOIN providers pr ON pr.id = e.provider_id
                       WHERE e.patient_id = %s
                       ORDER BY e.encounter_date DESC""",
                    (pid,),
                )
                for r in _enc_cur.fetchall():
                    pname = ""
                    if r.get("provider_fname") or r.get("provider_lname"):
                        pname = f"{r.get('provider_fname', '')} {r.get('provider_lname', '')}".strip()
                    encounters.append(
                        {
                            "encounter_id": r["encounter_id"],
                            "pid": r["pid"],
                            "date": str(r["date"]) if r.get("date") else None,
                            "reason": r.get("reason") or "Office Visit",
                            "provider": pname,
                            "provider_id": r.get("provider_id"),
                            "provider_fname": r.get("provider_fname", ""),
                            "provider_lname": r.get("provider_lname", ""),
                            "facility": r.get("facility") or "",
                            "has_notes": 1 if r.get("notes") else 0,
                            "notes": r.get("notes") or "",
                            "note_text": r.get("notes") or "",
                            "source": "raf_db",
                        }
                    )
        except Exception as _enc_exc2:
            logger.error(
                "svc_get_comprehensive_profile RAF DB encounters error pid=%s: %s",
                pid, _enc_exc2, exc_info=True,
            )
        if not encounters:
            encounters = _safe_call("encounters", emr.get_encounters, emr_pid, default=[])

    # --- Vitals ----------------------------------------------------------
    latest_vitals = _safe_call("vitals.latest", emr.get_latest_vitals, emr_pid, default=None)  # type: ignore[attr-defined]
    if not latest_vitals:
        all_vitals = _safe_call("vitals.all", emr.get_vitals, emr_pid, default=[])
        latest_vitals = all_vitals[0] if all_vitals else None
    # FHIR fallback: pull vitals from fhir_observations
    if not latest_vitals and is_fhir and fhir_external_id:
        try:
            with raf_cursor() as _fv_cur:
                _fv_cur.execute(
                    """SELECT code_display, value_numeric, value_string, unit, effective_date
                       FROM fhir_observations
                       WHERE fhir_patient_id = %s AND category = 'vital-signs'
                       ORDER BY effective_date DESC LIMIT 20""",
                    (fhir_external_id,),
                )
                vitals_rows = _fv_cur.fetchall()
                if vitals_rows:
                    vitals_dict: dict[str, Any] = {}
                    for vr in vitals_rows:
                        name = (vr.get("code_display") or "").lower().replace(" ", "_")
                        val = vr.get("value_numeric") or vr.get("value_string") or ""
                        if name and name not in vitals_dict:
                            # Return numeric values so frontend can do math (BMI, unit conversion)
                            try:
                                vitals_dict[name] = float(val) if val else None
                            except (ValueError, TypeError):
                                vitals_dict[name] = val
                    if vitals_dict:
                        vitals_dict["date"] = str(vitals_rows[0]["effective_date"]) if vitals_rows[0].get("effective_date") else None
                        vitals_dict["source"] = "fhir"
                        latest_vitals = vitals_dict
        except Exception as exc:
            logger.warning("FHIR vitals fallback failed: %s", exc)

    vitals_suspects: list[dict[str, Any]] = []
    lab_suspects_list: list[dict[str, Any]] = []
    try:
        from app.services.lab_suspect_engine import run_lab_suspect_scan  # type: ignore

        lab_scan = run_lab_suspect_scan(emr_pid)
        vitals_suspects = lab_scan.get("vitals_suspects", [])
        lab_suspects_list = lab_scan.get("all_suspects", [])
    except Exception as exc:
        logger.warning("svc_get_comprehensive_profile [lab_suspect_engine] failed: %s", exc)

    # --- Immunizations ---------------------------------------------------
    immunizations = _safe_call("immunizations", emr.get_immunizations, emr_pid, default=[])  # type: ignore[attr-defined]
    # FHIR fallback: pull immunizations from patient_immunizations table
    if not immunizations:
        try:
            with raf_cursor() as _imm_cur:
                _imm_cur.execute(
                    """SELECT vaccine_name AS title, administered_date,
                              cvx_code, lot_number, site, status
                       FROM patient_immunizations
                       WHERE patient_id = %s
                       ORDER BY administered_date DESC""",
                    (pid,),
                )
                for r in _imm_cur.fetchall():
                    immunizations.append({
                        "title": r.get("title") or "",
                        "administered_date": str(r["administered_date"]) if r.get("administered_date") else None,
                        "cvx_code": r.get("cvx_code") or "",
                        "id": r.get("id"),
                        "source": "raf_db",
                    })
        except Exception as exc:
            logger.debug("patient_immunizations fallback failed: %s", exc)

    # --- Enrollment info -------------------------------------------------
    enrollment = _safe_call(
        "enrollment",
        emr.get_patient_enrollment_info,
        emr_pid,
        default={
            "dual_status": "non_dual",
            "orec": "0",
            "institutional": False,
            "source": "unavailable",
        },
    )
    try:
        with raf_cursor() as _enr_cur:
            _enr_cur.execute(
                "SELECT insurance_plan, insurance_type, enrollment_months, dob FROM patients WHERE id = %s AND tenant_id = %s",
                (pid, tenant_id),
            )
            _enr_row = _enr_cur.fetchone()
            if _enr_row:
                # Use raf.patients.insurance_plan / insurance_type as a display fallback
                # for primary_insurance when OpenEMR insurance_data is unavailable.
                # This covers non-seeded patients whose insurance fields only live in
                # raf.patients (e.g. imported via FHIR / CSV / manual entry).
                if not enrollment.get("primary_insurance"):
                    fallback_name = (
                        _enr_row.get("insurance_plan")
                        or _enr_row.get("insurance_type")
                    )
                    if fallback_name:
                        enrollment["primary_insurance"] = fallback_name
                if not enrollment.get("plan_type") and _enr_row.get("insurance_plan"):
                    enrollment["plan_type"] = _enr_row["insurance_plan"]
                if not enrollment.get("plan_type") and _enr_row.get("insurance_type"):
                    enrollment["plan_type"] = _enr_row["insurance_type"]
                if not enrollment.get("enrolled_since") and _enr_row.get("enrollment_months"):
                    from datetime import datetime, timedelta

                    months = int(_enr_row["enrollment_months"])
                    enrolled_date = datetime.now() - timedelta(days=months * 30)
                    enrollment["enrolled_since"] = enrolled_date.strftime("%Y-%m-%d")
    except Exception as exc:
        logger.debug("Failed to fetch data: %s", exc)

    # --- HEDIS -----------------------------------------------------------
    hedis: dict[str, Any] = _safe_call(
        "hedis",
        emr.get_hedis_compliance,  # type: ignore[attr-defined]
        emr_pid,
        current_year,
        default={},
    )

    # --- Family history --------------------------------------------------
    family_history = _safe_call("family_history", emr.get_family_history, emr_pid, default=[])  # type: ignore[attr-defined]
    # FHIR fallback: pull from patient_family_history table
    if not family_history:
        try:
            with raf_cursor() as _fh_cur:
                _fh_cur.execute(
                    """SELECT relation, condition_name, onset_age, notes, status
                       FROM patient_family_history
                       WHERE patient_id = %s
                       ORDER BY relation""",
                    (pid,),
                )
                fh_rows = _fh_cur.fetchall()
                if fh_rows:
                    family_history = [
                        {
                            "relation": r.get("relation") or "",
                            "condition": r.get("condition_name") or "",
                            "onset_age": r.get("onset_age") or "",
                            "notes": r.get("notes") or "",
                            "source": "raf_db",
                        }
                        for r in fh_rows
                    ]
        except Exception as exc:
            logger.debug("patient_family_history fallback failed: %s", exc)

    # --- Allergies -------------------------------------------------------
    allergies = _safe_call("allergies", emr.get_allergies, emr_pid, default=[])  # type: ignore[attr-defined]
    # FHIR fallback: pull from fhir_allergies if still empty
    if not allergies and is_fhir and fhir_external_id:
        try:
            with raf_cursor() as _fa_cur:
                _fa_cur.execute(
                    """SELECT allergy_display AS title, category, criticality AS severity,
                              clinical_status AS status, onset_date, recorded_date
                       FROM fhir_allergies
                       WHERE fhir_patient_id = %s
                       ORDER BY recorded_date DESC""",
                    (fhir_external_id,),
                )
                for row in _fa_cur.fetchall():
                    allergies.append({
                        "title": row.get("title") or "Unknown allergy",
                        "category": row.get("category") or "",
                        "severity": row.get("severity") or "",
                        "status": row.get("status") or "active",
                        "begdate": str(row["onset_date"]) if row.get("onset_date") else "",
                    })
        except Exception as exc:
            logger.warning("FHIR allergy fallback failed: %s", exc)

    # --- Referrals -------------------------------------------------------
    referrals = _safe_call("referrals", emr.get_referrals, emr_pid, default=[])  # type: ignore[attr-defined]
    # FHIR fallback: pull from patient_referrals table
    if not referrals:
        try:
            with raf_cursor() as _ref_cur:
                _ref_cur.execute(
                    """SELECT referral_date, referred_to, referred_by, reason,
                              specialty, status, notes
                       FROM patient_referrals
                       WHERE patient_id = %s
                       ORDER BY referral_date DESC""",
                    (pid,),
                )
                for r in _ref_cur.fetchall():
                    referrals.append({
                        "date": str(r["referral_date"]) if r.get("referral_date") else None,
                        "referred_to": r.get("referred_to") or "",
                        "referred_by": r.get("referred_by") or "",
                        "reason": r.get("reason") or "",
                        "specialty": r.get("specialty") or "",
                        "status": r.get("status") or "",
                        "notes": r.get("notes") or "",
                        "source": "raf_db",
                    })
        except Exception as exc:
            logger.debug("patient_referrals fallback failed: %s", exc)

    # --- RAF score + breakdown ------------------------------------------
    raf_current_score: float | None = None
    raf_breakdown: dict[str, Any] | None = None
    for yr in [current_year, current_year - 1]:
        raf_data = _safe_call(
            "raf_breakdown", get_raf_breakdown, pid, yr, tenant_id=tenant_id, default={}
        )
        if raf_data:
            raf_current_score = raf_data.get("raf_score")
            raf_breakdown = raf_data
            break

    # --- Actual labs -----------------------------------------------------
    actual_labs = _safe_call("labs", emr.get_labs, emr_pid, default=[])
    # FHIR fallback: pull labs from fhir_observations
    if not actual_labs and is_fhir and fhir_external_id:
        try:
            with raf_cursor() as _fl_cur:
                _fl_cur.execute(
                    """SELECT code, code_display, value_numeric, value_string,
                              unit, effective_date, status
                       FROM fhir_observations
                       WHERE fhir_patient_id = %s AND category = 'laboratory'
                       ORDER BY effective_date DESC LIMIT 50""",
                    (fhir_external_id,),
                )
                for r in _fl_cur.fetchall():
                    actual_labs.append(
                        {
                            "test_name": r.get("code_display") or r.get("code") or "",
                            "result": str(r.get("value_numeric") or r.get("value_string") or ""),
                            "units": r.get("unit") or "",
                            "date": str(r["effective_date"]) if r.get("effective_date") else None,
                            "status": r.get("status") or "",
                            "source": "fhir",
                        }
                    )
        except Exception as exc:
            logger.warning("FHIR labs fallback failed: %s", exc)

    # --- Data completeness -----------------------------------------------
    has_clinical_notes = any(bool(enc.get("has_notes")) for enc in encounters)
    has_insurance = enrollment.get("source") not in (None, "default", "unavailable")

    completeness_flags: dict[str, bool] = {
        "has_billing": bool(icd10_codes),
        "has_problems": bool(problem_list),
        "has_clinical_notes": has_clinical_notes,
        "has_vitals": latest_vitals is not None,
        "has_labs": bool(actual_labs),
        "has_immunizations": bool(immunizations),
        "has_insurance": has_insurance,
        "has_medications": bool(medications),
        "has_encounters": bool(encounters),
        "has_allergies": bool(allergies),
        "has_family_history": bool(family_history) and family_history != {},
        "has_referrals": bool(referrals),
        "has_demographics": bool(patient.get("race")) and bool(patient.get("language")),
    }
    completeness_pct = round(sum(completeness_flags.values()) / len(completeness_flags) * 100)

    return {
        "pid": pid,
        "patient": patient,
        "demographics": {
            "age": _calculate_age(patient.get("DOB")),
            "sex": patient.get("sex"),
            "race": patient.get("race"),
            "ethnicity": patient.get("ethnicity"),
            "language": patient.get("language"),
        },
        "billing": {
            "icd10_codes": icd10_codes,
            "cpt_codes": cpt_codes,
        },
        "problem_list": problem_list,
        "recapture_gaps": recapture_gaps,
        "medications": {
            "active": medications,
            "diagnosis_gaps": medication_diagnosis_gaps,
        },
        "encounters": encounters,
        "vitals": {
            "latest": latest_vitals,
            "suspects": vitals_suspects,
        },
        "labs": {
            "results": actual_labs,
            "suspects": lab_suspects_list,
        },
        "immunizations": immunizations,
        "enrollment": enrollment,
        "hedis": hedis,
        "family_history": family_history,
        "allergies": allergies,
        "referrals": referrals,
        "raf": {
            "current_score": raf_current_score,
            "breakdown": raf_breakdown,
        },
        "data_completeness": {
            **completeness_flags,
            "completeness_pct": completeness_pct,
        },
    }


# ---------------------------------------------------------------------------
# svc_get_family_history
# ---------------------------------------------------------------------------


def svc_get_family_history(pid: int, tenant_id: str) -> dict[str, Any]:
    """Return family history for *pid*."""
    emr_pid = _get_emr_pid(pid, tenant_id=tenant_id) or pid
    family_history = emr.get_family_history(emr_pid) or {}
    return {"pid": pid, "family_history": family_history}


# ---------------------------------------------------------------------------
# svc_get_sdoh
# ---------------------------------------------------------------------------


def svc_get_sdoh(pid: int, tenant_id: str) -> dict[str, Any]:
    """Return SDOH data for *pid*."""
    emr_pid = _get_emr_pid(pid, tenant_id=tenant_id) or pid
    data = emr.get_sdoh_data(emr_pid) or {}
    data.setdefault("pid", pid)
    data.setdefault("sdoh_form", {})
    data.setdefault("billed_z_codes", [])
    data.setdefault("billable_highlights", {})
    if data.get("sdoh_form") is None:
        data["sdoh_form"] = {}
    return data


# ---------------------------------------------------------------------------
# svc_get_allergies
# ---------------------------------------------------------------------------


def svc_get_allergies(pid: int, tenant_id: str) -> dict[str, Any]:
    """Return active allergies for *pid*."""
    emr_pid = _get_emr_pid(pid, tenant_id=tenant_id) or pid
    allergies = emr.get_allergies(emr_pid)
    # FHIR fallback
    if not allergies:
        fhir_external_id = _get_fhir_resource_id(pid, tenant_id=tenant_id)
        if fhir_external_id:
            try:
                with raf_cursor() as cur:
                    cur.execute(
                        """SELECT allergy_display AS title, category,
                                  criticality AS severity, clinical_status AS status,
                                  onset_date
                           FROM fhir_allergies
                           WHERE fhir_patient_id = %s""",
                        (fhir_external_id,),
                    )
                    for row in cur.fetchall():
                        allergies.append({
                            "title": row.get("title") or "Unknown",
                            "category": row.get("category") or "",
                            "severity": row.get("severity") or "",
                            "status": row.get("status") or "active",
                            "begdate": str(row["onset_date"]) if row.get("onset_date") else "",
                        })
            except Exception:
                pass
    return {"pid": pid, "count": len(allergies), "allergies": allergies}


# ---------------------------------------------------------------------------
# svc_get_referrals
# ---------------------------------------------------------------------------


def svc_get_referrals(pid: int, tenant_id: str) -> dict[str, Any]:
    """Return referral transactions for *pid*."""
    emr_pid = _get_emr_pid(pid, tenant_id=tenant_id) or pid
    referrals = emr.get_referrals(emr_pid)
    return {"pid": pid, "count": len(referrals), "referrals": referrals}


# ---------------------------------------------------------------------------
# svc_get_immunizations
# ---------------------------------------------------------------------------


def svc_get_immunizations(pid: int, tenant_id: str) -> dict[str, Any]:
    """Return immunization history for *pid*."""
    emr_pid = _get_emr_pid(pid, tenant_id=tenant_id) or pid
    immunizations = emr.get_immunizations(emr_pid)
    return {"pid": pid, "count": len(immunizations), "immunizations": immunizations}


# ---------------------------------------------------------------------------
# svc_get_hedis_compliance
# ---------------------------------------------------------------------------


def svc_get_hedis_compliance(pid: int, year: int, tenant_id: str) -> dict[str, Any]:
    """Return HEDIS/Stars quality measure compliance for *pid*."""
    if not year:
        year = _date.today().year

    emr_pid = _get_emr_pid(pid, tenant_id=tenant_id) or pid
    measures = emr.get_hedis_compliance(emr_pid, year) or {}

    due_count = sum(1 for m in measures.values() if m.get("due"))
    compliant_count = sum(1 for m in measures.values() if m.get("due") and m.get("compliant"))

    return {
        "pid": pid,
        "year": year,
        "summary": {
            "measures_due": due_count,
            "measures_compliant": compliant_count,
            "compliance_rate": round(compliant_count / due_count, 2) if due_count else None,
        },
        "measures": measures,
    }


# ---------------------------------------------------------------------------
# svc_get_patient_enrollment
# ---------------------------------------------------------------------------


def svc_get_patient_enrollment(pid: int, tenant_id: str) -> dict[str, Any]:
    """Return enrollment and insurance metadata for *pid*."""
    emr_pid = _get_emr_pid(pid, tenant_id=tenant_id) or pid
    enrollment = emr.get_patient_enrollment_info(emr_pid) or {}
    return {"pid": pid, "enrollment": enrollment}
