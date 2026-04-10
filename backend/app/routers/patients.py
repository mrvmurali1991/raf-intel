"""
Patient router.

GET  /api/patients                              - paginated patient list from raf_intelligence.patients
POST /api/patients/import                       - bulk import patients from CSV upload
GET  /api/patients/import/template              - download blank CSV import template
GET  /api/patients/{pid}                        - single patient with latest RAF score
GET  /api/patients/{pid}/encounters             - encounter history
GET  /api/patients/{pid}/medications            - active prescriptions (includes diagnosis field)
GET  /api/patients/{pid}/medication-gaps        - medication-linked diagnoses not billed this year
GET  /api/patients/{pid}/diagnoses              - ICD-10 billing codes
GET  /api/patients/{pid}/procedures             - CPT procedure codes with condition hints
GET  /api/patients/{pid}/lab-suspects           - rule-based lab/vitals suspect conditions
GET  /api/patients/{pid}/comprehensive-profile  - aggregated full patient picture for RAF analysis
"""
# Removed: from __future__ import annotations (breaks FastAPI schema generation)

import logging
from datetime import date as _date
from datetime import datetime as _datetime
from typing import Any, Optional

from fastapi import Depends, APIRouter, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import Response

from app.services import openemr_connector as emr
from app.services.audit_logger import log_phi_access
from app.services.raf_calculator import get_raf_breakdown
from app.services.emr_manager import ACTIVE_PATIENTS_SUBQUERY
from app.auth import get_current_user, get_tenant_id, require_permission
from app.rate_limit import limiter
from app.db import raf_cursor

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/patients", tags=["patients"])


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


def _list_fhir_patients(
    limit: int, offset: int, search: str = "", tenant_id: str | None = None
) -> tuple[list[dict], int]:
    """List patients from emr_patient_matches for FHIR/REST connections.

    When *tenant_id* is provided, results are restricted to EMR connections
    owned by that tenant to enforce multi-tenant isolation.
    """
    with raf_cursor() as cur:
        where = "WHERE ec.is_active = 1"
        params: list = []
        if tenant_id is not None:
            where += " AND ec.tenant_id = %s"
            params.append(tenant_id)
        if search:
            where += " AND (epm.first_name LIKE %s OR epm.last_name LIKE %s OR CAST(epm.id AS CHAR) LIKE %s)"
            like = f"%{search}%"
            params.extend([like, like, like])

        cur.execute(
            f"SELECT COUNT(DISTINCT epm.id) AS cnt FROM emr_patient_matches epm "
            f"JOIN emr_connections ec ON ec.id = epm.connection_id {where}",
            params,
        )
        total = cur.fetchone()["cnt"]

        cur.execute(
            f"""SELECT epm.id AS pid, epm.external_id, epm.first_name AS fname,
                       epm.last_name AS lname, epm.date_of_birth AS DOB,
                       epm.sex, epm.mrn, epm.raf_patient_id
                FROM emr_patient_matches epm
                JOIN emr_connections ec ON ec.id = epm.connection_id
                {where}
                ORDER BY epm.last_name, epm.first_name
                LIMIT %s OFFSET %s""",
            (*params, limit, offset),
        )
        rows = cur.fetchall()

    patients = []
    for r in rows:
        patients.append({
            "pid": r["raf_patient_id"] or r["pid"],
            "fname": r["fname"] or "",
            "lname": r["lname"] or "",
            "DOB": str(r["DOB"]) if r["DOB"] else "",
            "sex": r["sex"] or "",
            "mrn": r.get("mrn") or "",
            "external_id": r["external_id"],
        })
    return patients, total


def _list_raf_patients(
    limit: int, offset: int, search: str = "", tenant_id: str | None = None,
    only_uploaded: bool = False,
) -> tuple[list[dict], int]:
    """List patients from the raf_intelligence.patients table.

    Returns field names that match what the frontend Patient type expects
    (pid, fname, lname, DOB, sex, race, ethnicity, language, street, city,
    state, postal_code, phone_home, phone_cell, email, mname).

    When *tenant_id* is provided, results are restricted to rows belonging
    to that tenant (multi-tenant isolation).
    """
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

        cur.execute(
            f"SELECT COUNT(*) AS cnt FROM patients {where}",
            params,
        )
        total = cur.fetchone()["cnt"]

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

    patients = []
    for r in rows:
        p: dict[str, Any] = {}
        for k, v in r.items():
            if hasattr(v, "isoformat"):
                p[k] = v.isoformat()
            elif hasattr(v, "__float__"):
                p[k] = float(v)
            else:
                p[k] = v if v is not None else ""
        patients.append(p)
    return patients, total


def _get_emr_pid(pid: int, tenant_id: str | None = None) -> int | None:
    """Look up the emr_pid for a patient in raf_intelligence.patients.

    Returns the emr_pid if populated, otherwise None.  Clinical/encounter
    queries against OpenEMR should use the returned emr_pid so that the URL
    ``pid`` (which maps to ``patients.id``) is correctly translated to the
    OpenEMR ``patient_data.pid``.

    When *tenant_id* is provided, the lookup is scoped to that tenant so
    IDs from another tenant cannot be resolved.
    """
    try:
        with raf_cursor() as cur:
            if tenant_id is not None:
                cur.execute(
                    "SELECT emr_pid FROM patients WHERE id = %s AND tenant_id = %s",
                    (pid, tenant_id),
                )
            else:
                cur.execute("SELECT emr_pid FROM patients WHERE id = %s", (pid,))
            row = cur.fetchone()
            if row and row.get("emr_pid"):
                return int(row["emr_pid"])
    except Exception:
        pass
    return None


def _tenant_of(current_user: dict) -> str:
    """Extract tenant_id from current_user, with a safe fallback.

    Fallback to ``"1"`` keeps legacy deployments working during the
    multi-tenant rollout, but logs a warning so the gap is visible.
    """
    tid = current_user.get("tenant_id") if current_user else None
    if tid is None:
        logger.warning(
            "current_user has no tenant_id; defaulting to '1' for query scoping"
        )
        return "1"
    return str(tid)


def _patient_belongs_to_tenant(pid: int, tenant_id: str) -> bool:
    """Return True if *pid* exists in raf_intelligence.patients for this tenant.

    Used to enforce per-tenant IDOR protection on {pid} path params.
    """
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
    """Return True if *pid* is linked to an active EMR connection.

    For direct_db connections the patient exists directly in OpenEMR
    (queried via openemr_connector), so we also accept the patient if
    an active direct_db connection exists and OpenEMR knows the pid.
    """
    try:
        with raf_cursor() as cur:
            # Check emr_patient_matches first (FHIR / REST adapters)
            cur.execute(
                "SELECT 1 FROM emr_patient_matches pm "
                "JOIN emr_connections ec ON ec.id = pm.connection_id "
                "WHERE ec.is_active = 1 AND pm.raf_patient_id = %s LIMIT 1",
                (pid,),
            )
            if cur.fetchone() is not None:
                return True
            # For direct_db connections, check if an active connection exists
            # and the patient exists in the raf_intelligence.patients table.
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
                    cur.execute("SELECT 1 FROM patients WHERE id = %s", (pid,))
                return cur.fetchone() is not None
        return False
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Patient list
# ---------------------------------------------------------------------------


@router.get("", summary="List all patients")
@limiter.limit("60/minute")
def list_patients(
    request: Request,
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    search: str = Query("", description="Search by name or PID"),
    year: Optional[int] = Query(
        default=None,
        description="Measurement year for RAF score enrichment (defaults to current year)",
    ),
    current_user: dict = Depends(get_current_user),
    _perm: None = Depends(require_permission("patients", "read")),
) -> dict[str, Any]:
    """
    Return a paginated list of patients from the raf_intelligence.patients table.
    Falls back to FHIR patient matches for fhir_r4/rest_api connections.
    Supports server-side search by name, PID, or MRN.
    """
    # Serve the active cohort from raf_intelligence.patients. If no EMR
    # connection is active we fall back to the local registry — this covers
    # CSV/Excel imports where the user has deactivated their EMR connection
    # but still expects to see the uploaded patients.
    try:
        conn_type = _active_connection_type()
        if conn_type in ("fhir_r4", "rest_api"):
            patients, total = _list_fhir_patients(
                limit, offset, search.strip(), tenant_id=get_tenant_id(current_user)
            )
        else:
            # When EMR is deactivated, only surface uploaded (CSV/Excel) rows.
            only_uploaded = not _has_active_emr_connection()
            patients, total = _list_raf_patients(
                limit, offset, search.strip(),
                tenant_id=get_tenant_id(current_user),
                only_uploaded=only_uploaded,
            )
    except Exception as exc:
        logger.error("list_patients error: %s", exc)
        raise HTTPException(status_code=500, detail="Internal server error")

    # Enrich with RAF scores from raf_scores table.
    # Only include scores for patients linked to active EMR connections so that
    # deactivating a connection immediately hides its patients' data.
    try:
        pids = [p["pid"] for p in patients if p.get("pid")]
        if pids:
            placeholders = ",".join(["%s"] * len(pids))
            with raf_cursor() as cur:
                _tid = int(get_tenant_id(current_user))
                cur.execute(
                    f"""
                    SELECT patient_id, final_raf, hcc_count,
                           demographic_score, disease_score, interaction_score
                    FROM raf_scores
                    WHERE patient_id IN ({placeholders})
                      AND measurement_year = %s
                      AND {ACTIVE_PATIENTS_SUBQUERY}
                      AND raf_scores.tenant_id = %s
                    ORDER BY calculated_at DESC
                    """,
                    (*pids, year or _date.today().year, _tid),
                )
                raf_map: dict[int, dict] = {}
                for row in cur.fetchall():
                    pid = int(row["patient_id"])
                    if pid not in raf_map:
                        raf_map[pid] = row
            for p in patients:
                r = raf_map.get(p["pid"])
                if r:
                    p["raf_score"] = float(r["final_raf"]) if r.get("final_raf") else None
                    p["hcc_count"] = int(r["hcc_count"]) if r.get("hcc_count") else 0
                    p["demographic_score"] = float(r["demographic_score"]) if r.get("demographic_score") else None
                    p["disease_score"] = float(r["disease_score"]) if r.get("disease_score") else None
                    p["interaction_score"] = float(r["interaction_score"]) if r.get("interaction_score") else None
    except Exception as exc:
        logger.warning("list_patients: RAF enrichment failed: %s", exc)

    log_phi_access(
        action="list",
        resource="patient",
        details=f"limit={limit} offset={offset} search={search!r} returned={len(patients)}",
    )
    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "search": search,
        "patients": patients,
    }


# ---------------------------------------------------------------------------
# Patients with encounters (for pipeline demo)
# ---------------------------------------------------------------------------


@router.get("/with-encounters", summary="Patients that have encounter data")
def patients_with_encounters(
    limit: int = Query(200, ge=1, le=500),
    current_user: dict = Depends(get_current_user),
    _perm: None = Depends(require_permission("patients", "read")),
) -> dict[str, Any]:
    """Return only patients that have at least one encounter."""
    if _has_active_emr_connection():
        try:
            patients = emr.get_patients_with_encounters(limit=limit)
            return {"total": len(patients), "patients": patients}
        except Exception as exc:
            logger.error("patients_with_encounters error: %s", exc)
            raise HTTPException(status_code=500, detail="Internal server error")

    # No active EMR — return uploaded patients that have encounter analysis data
    try:
        with raf_cursor() as cur:
            cur.execute(
                """
                SELECT DISTINCT p.id AS pid, p.first_name AS fname, p.last_name AS lname,
                       p.dob AS DOB, p.sex
                FROM patients p
                JOIN raf_encounter_analysis ea ON ea.pid = p.id
                WHERE p.is_active = 1 AND p.data_source = 'upload'
                LIMIT %s
                """,
                (limit,),
            )
            patients = [dict(r) for r in cur.fetchall()]
        return {"total": len(patients), "patients": patients}
    except Exception as exc:
        logger.error("patients_with_encounters (upload fallback) error: %s", exc)
        return {"total": 0, "patients": []}


# ---------------------------------------------------------------------------
# Bulk CSV / Excel Import
# ---------------------------------------------------------------------------

# Maximum upload size: 10 MB — generous for both CSV and xlsx files.
_MAX_CSV_BYTES = 10 * 1024 * 1024


@router.get(
    "/import/template",
    summary="Download CSV import template",
    response_class=Response,
)
def get_import_template(
    current_user: dict = Depends(get_current_user),
    _perm: None = Depends(require_permission("patients", "write")),
) -> Response:
    """
    Return a CSV file with the correct column headers and one example row.

    Download this template, fill in patient data, then upload via
    POST /api/patients/import.  An Excel version is available at
    GET /api/patients/import/template/excel.
    """
    from app.services.patient_import_service import get_import_template as _template

    csv_content = _template()
    return Response(
        content=csv_content,
        media_type="text/csv",
        headers={
            "Content-Disposition": "attachment; filename=patient_import_template.csv"
        },
    )


@router.get(
    "/import/template/excel",
    summary="Download Excel (.xlsx) import template",
    response_class=Response,
)
def get_import_template_excel(
    current_user: dict = Depends(get_current_user),
    _perm: None = Depends(require_permission("patients", "write")),
) -> Response:
    """
    Return an Excel (.xlsx) file with the correct column headers and one
    example row.

    Download this template, fill in patient data, then upload via
    POST /api/patients/import.  A CSV version is available at
    GET /api/patients/import/template.
    """
    from app.services.patient_import_service import get_import_template_xlsx as _xlsx_tpl

    xlsx_content = _xlsx_tpl()
    return Response(
        content=xlsx_content,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": "attachment; filename=patient_import_template.xlsx"
        },
    )


@router.post("/import", summary="Bulk import patients from a CSV or Excel file")
@limiter.limit("5/minute")
async def import_patients_csv(
    request: Request,
    file: UploadFile = File(..., description="CSV or Excel (.xlsx) file with patient records"),
    on_duplicate: str = Query("skip", description="Duplicate handling: 'skip' keeps existing records, 'update' overwrites existing with new data", regex="^(skip|update|replace)$"),
    current_user: dict = Depends(get_current_user),
    _perm: None = Depends(require_permission("patients", "write")),
) -> dict[str, Any]:
    """
    Parse *file* as a patient CSV or Excel spreadsheet, validate each row,
    deduplicate against existing OpenEMR patients, and insert new patients.

    Accepted formats: **.csv** and **.xlsx**.

    The file must contain the following **required** columns (order does not
    matter, extra columns are ignored):

    - first_name, last_name, dob, sex

    Optional columns: ssn, phone, email, address, city, state, zip,
    insurance_type, mrn.

    Download the CSV template via GET /api/patients/import/template or the
    Excel template via GET /api/patients/import/template/excel.

    The uploader identity is derived from the authenticated JWT.

    The ``on_duplicate`` query parameter controls how existing patients are
    handled: ``skip`` (default) leaves existing records unchanged, ``update``
    overwrites them with data from the uploaded file.
    """
    from app.services.patient_import_service import (
        import_patients as _import,
        parse_patient_csv as _parse_csv,
        parse_patient_xlsx as _parse_xlsx,
    )

    fname = file.filename or ""
    fname_lower = fname.lower()
    if not fname or not (fname_lower.endswith(".csv") or fname_lower.endswith(".xlsx")):
        raise HTTPException(
            status_code=422,
            detail=(
                "Only .csv and .xlsx files are accepted. "
                "Download the template via GET /api/patients/import/template "
                "or GET /api/patients/import/template/excel."
            ),
        )

    content = await file.read()

    if len(content) == 0:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")

    if len(content) > _MAX_CSV_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"File too large. Maximum allowed size is {_MAX_CSV_BYTES // (1024 * 1024)} MB.",
        )

    if fname_lower.endswith(".xlsx"):
        rows, parse_errors = _parse_xlsx(content)
    else:
        rows, parse_errors = _parse_csv(content)

    if parse_errors and not rows:
        # Fatal parse error — no rows could be extracted at all.
        raise HTTPException(
            status_code=422,
            detail={"message": "Could not parse uploaded file.", "errors": parse_errors},
        )

    # Always derive uploader from JWT — never from client input.
    actual_uploader = (
        current_user.get("username")
        or current_user.get("sub")
        or current_user.get("email", "unknown")
    )

    try:
        summary = _import(rows, uploaded_by=actual_uploader, on_duplicate=on_duplicate)
    except Exception as exc:
        logger.error("import_patients_csv error: %s", exc)
        raise HTTPException(status_code=500, detail="Internal server error")

    # Merge any parse-level errors into the summary so the caller sees everything.
    if parse_errors:
        summary["errors"] += len(parse_errors)
        summary["error_details"] = parse_errors + summary.get("error_details", [])

    log_phi_access(
        action="bulk_import",
        resource="patient",
        details=(
            f"filename={file.filename!r} on_duplicate={on_duplicate} total_rows={summary['total_rows']} "
            f"imported={summary['imported']} duplicates={summary['duplicates_skipped']} "
            f"errors={summary['errors']}"
        ),
    )

    return summary


# ---------------------------------------------------------------------------
# Bulk FHIR Import
# ---------------------------------------------------------------------------


@router.get(
    "/import/template/fhir",
    summary="Download FHIR JSON import template",
    response_class=Response,
)
def get_fhir_import_template(
    current_user: dict = Depends(get_current_user),
    _perm: None = Depends(require_permission("patients", "write")),
) -> Response:
    """
    Return a FHIR R4 Patient Bundle JSON file with example entries.

    Download this template, populate it with patient data, then upload via
    POST /api/patients/import/fhir.
    """
    from app.services.patient_import_service import get_fhir_template as _fhir_tpl

    json_content = _fhir_tpl()
    return Response(
        content=json_content,
        media_type="application/fhir+json",
        headers={
            "Content-Disposition": "attachment; filename=patient_import_fhir_template.json"
        },
    )


@router.post("/import/fhir", summary="Bulk import patients from a FHIR JSON file")
@limiter.limit("5/minute")
async def import_patients_fhir(
    request: Request,
    file: UploadFile = File(..., description="FHIR R4 Bundle JSON file with Patient entries"),
    on_duplicate: str = Query("skip", description="Duplicate handling: 'skip' keeps existing records, 'update' overwrites existing with new data", regex="^(skip|update|replace)$"),
    current_user: dict = Depends(get_current_user),
    _perm: None = Depends(require_permission("patients", "write")),
) -> dict[str, Any]:
    """
    Parse *file* as a FHIR R4 Patient Bundle, validate each entry, deduplicate
    against existing OpenEMR patients, and insert new patients.

    The file must be a valid FHIR R4 Bundle of type 'collection' or
    'transaction' containing Patient resources.

    Download the template via GET /api/patients/import/template/fhir.

    The uploader identity is derived from the authenticated JWT.

    The ``on_duplicate`` query parameter controls how existing patients are
    handled: ``skip`` (default) leaves existing records unchanged, ``update``
    overwrites them with data from the uploaded file.
    """
    from app.services.patient_import_service import (
        import_patients as _import,
        parse_fhir_patients as _parse_fhir,
    )

    if not file.filename or not file.filename.lower().endswith(".json"):
        raise HTTPException(
            status_code=422,
            detail="Only .json files are accepted. Download the template via GET /api/patients/import/template/fhir.",
        )

    content = await file.read()

    if len(content) == 0:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")

    if len(content) > _MAX_CSV_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"File too large. Maximum allowed size is {_MAX_CSV_BYTES // (1024 * 1024)} MB.",
        )

    rows, parse_errors = _parse_fhir(content)

    if parse_errors and not rows:
        # Fatal parse error — no Patient entries could be extracted at all.
        raise HTTPException(
            status_code=422,
            detail={"message": "Could not parse FHIR JSON file.", "errors": parse_errors},
        )

    # Always derive uploader from JWT — never from client input.
    actual_uploader = (
        current_user.get("username")
        or current_user.get("sub")
        or current_user.get("email", "unknown")
    )

    try:
        summary = _import(rows, uploaded_by=actual_uploader, on_duplicate=on_duplicate)
    except Exception as exc:
        logger.error("import_patients_fhir error: %s", exc)
        raise HTTPException(status_code=500, detail="Internal server error")

    # Merge any parse-level errors into the summary so the caller sees everything.
    if parse_errors:
        summary["errors"] += len(parse_errors)
        summary["error_details"] = parse_errors + summary.get("error_details", [])

    log_phi_access(
        action="bulk_import_fhir",
        resource="patient",
        details=(
            f"filename={file.filename!r} on_duplicate={on_duplicate} total_rows={summary['total_rows']} "
            f"imported={summary['imported']} duplicates={summary['duplicates_skipped']} "
            f"errors={summary['errors']}"
        ),
    )

    return summary


# ---------------------------------------------------------------------------
# Single patient
# ---------------------------------------------------------------------------


@router.get("/{pid}", summary="Get patient details with RAF score")
def get_patient(
    pid: int,
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
    _perm: None = Depends(require_permission("patients", "read")),
) -> dict[str, Any]:
    """
    Return demographic data for *pid* plus their most recent RAF score.
    """
    # Per-tenant IDOR protection: patient must belong to caller's tenant.
    if not _patient_belongs_to_tenant(pid, tenant_id) and not _patient_in_active_connection(pid, tenant_id=tenant_id):
        raise HTTPException(status_code=404, detail=f"Patient {pid} not found")

    patient = emr.get_patient(pid)
    if not patient:
        raise HTTPException(status_code=404, detail=f"Patient {pid} not found")

    # Attach latest RAF score if available (check current year first, then prior)
    raf_data: dict = {}
    for yr in [_date.today().year, _date.today().year - 1]:
        raf_data = get_raf_breakdown(pid, yr, tenant_id=tenant_id)
        if raf_data:
            break
    patient["raf_score"] = raf_data.get("raf_score")
    patient["raf_score_date"] = raf_data.get("calculated_at")
    patient["raf_score_year"] = raf_data.get("measurement_year")

    log_phi_access(action="view", resource="patient", patient_id=pid)
    return patient


# ---------------------------------------------------------------------------
# Clinical Notes
# ---------------------------------------------------------------------------


@router.get(
    "/{pid}/clinical-notes/{encounter_id}", summary="Get clinical notes for encounter"
)
def get_clinical_notes_for_encounter(
    pid: int,
    encounter_id: int,
    current_user: dict = Depends(get_current_user),
    _perm: None = Depends(require_permission("patients", "read")),
) -> dict[str, Any]:
    """Return clinical notes text for a specific encounter."""
    _tid = _tenant_of(current_user)
    if not _patient_belongs_to_tenant(pid, _tid) and not _patient_in_active_connection(pid, tenant_id=_tid):
        raise HTTPException(status_code=404, detail=f"Patient {pid} not found")

    try:
        notes = emr.get_clinical_notes(encounter_id)
    except Exception as exc:
        logger.error("get_clinical_notes error enc=%s: %s", encounter_id, exc)
        raise HTTPException(status_code=500, detail="Internal server error")

    log_phi_access(
        action="view",
        resource="clinical_note",
        patient_id=pid,
        encounter_id=encounter_id,
        details=f"notes_returned={len(notes)}",
    )
    return {
        "pid": pid,
        "encounter_id": encounter_id,
        "count": len(notes),
        "notes": notes,
    }


# ---------------------------------------------------------------------------
# Encounters
# ---------------------------------------------------------------------------


@router.get("/{pid}/encounters", summary="Get patient encounters")
def get_encounters(
    pid: int,
    year: Optional[int] = Query(default=None, description="Filter encounters by year (e.g. 2024)"),
    current_user: dict = Depends(get_current_user),
    _perm: None = Depends(require_permission("patients", "read")),
) -> dict[str, Any]:
    """
    Return all encounters for *pid* from form_encounter.

    Query parameter:
    - **year**: optional integer — when provided, only encounters whose date
      starts with that year are returned.
    """
    _tid = _tenant_of(current_user)
    if not _patient_belongs_to_tenant(pid, _tid) and not _patient_in_active_connection(pid, tenant_id=_tid):
        raise HTTPException(status_code=404, detail=f"Patient {pid} not found")

    patient = emr.get_patient(pid)
    if not patient:
        raise HTTPException(status_code=404, detail=f"Patient {pid} not found")

    # Resolve emr_pid for OpenEMR clinical queries
    emr_pid = _get_emr_pid(pid, tenant_id=_tid) or pid

    try:
        encounters = emr.get_encounters(emr_pid)
    except Exception as exc:
        logger.error("get_encounters error pid=%s: %s", pid, exc)
        raise HTTPException(status_code=500, detail="Internal server error")

    if year is not None:
        encounters = [e for e in encounters if str(e.get("date", ""))[:4] == str(year)]

    # Enrich encounters with cached analysis results and has_notes flag
    try:
        import json as _json

        # Get cached analysis for all encounters of this patient
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
                            analysis_data = _json.loads(row["analysis_json"]) if isinstance(row["analysis_json"], str) else row["analysis_json"]
                        except Exception:
                            pass
                    analysis_map[eid] = {
                        "diagnoses": analysis_data.get("diagnoses", []),
                        "pipeline": analysis_data.get("pipeline", {}),
                        "_meta": analysis_data.get("_meta", {}),
                        "overall_score": float(row["overall_score"]) if row.get("overall_score") else None,
                        "dx_count": row.get("dx_count", 0),
                        "suspect_count": row.get("suspect_count", 0),
                        "hcc_opportunity_count": row.get("hcc_opportunity_count", 0),
                        "analyzed_at": row["created_at"].isoformat() if hasattr(row.get("created_at"), "isoformat") else str(row.get("created_at", "")),
                    }
        except Exception as ae:
            logger.debug("Could not load cached analysis for pid=%s: %s", pid, ae)

        # Fetch actual SOAP note text per encounter
        notes_map: dict[int, str] = {}
        try:
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
        except Exception:
            pass

        # Attach to encounters
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

    log_phi_access(
        action="view",
        resource="encounter",
        patient_id=pid,
        details=f"encounters_returned={len(encounters)}",
    )
    return {
        "pid": pid,
        "count": len(encounters),
        "encounters": encounters,
    }


# ---------------------------------------------------------------------------
# Medications
# ---------------------------------------------------------------------------


@router.get("/{pid}/medications", summary="Get patient medications")
def get_medications(
    pid: int,
    year: Optional[int] = Query(
        default=None,
        description=(
            "Filter to medications active during this calendar year. "
            "A prescription is included when YEAR(start_date) <= year AND active = 1. "
            "Omit to return all prescriptions regardless of year or active status."
        ),
    ),
    current_user: dict = Depends(get_current_user),
    _perm: None = Depends(require_permission("patients", "read")),
) -> dict[str, Any]:
    """
    Return all prescriptions for *pid* from the prescriptions table.

    Query parameter:
    - **year** (optional): when supplied, only prescriptions whose
      ``start_date`` year is <= the given year and that are still marked
      ``active = 1`` are returned.  Omitting ``year`` preserves the
      original behaviour — all prescriptions are returned.
    """
    _tid = _tenant_of(current_user)
    if not _patient_belongs_to_tenant(pid, _tid) and not _patient_in_active_connection(pid, tenant_id=_tid):
        raise HTTPException(status_code=404, detail=f"Patient {pid} not found")

    patient = emr.get_patient(pid)
    if not patient:
        raise HTTPException(status_code=404, detail=f"Patient {pid} not found")

    # Resolve emr_pid for OpenEMR clinical queries
    emr_pid = _get_emr_pid(pid, tenant_id=_tid) or pid

    try:
        medications = emr.get_medications(emr_pid, year=year)
    except Exception as exc:
        logger.error("get_medications error pid=%s: %s", pid, exc)
        raise HTTPException(status_code=500, detail="Internal server error")

    response: dict[str, Any] = {
        "pid": pid,
        "count": len(medications),
        "medications": medications,
    }
    if year is not None:
        response["year"] = year
    return response


# ---------------------------------------------------------------------------
# Medication-diagnosis gaps
# ---------------------------------------------------------------------------


@router.get(
    "/{pid}/medication-gaps", summary="Medication-linked diagnoses not billed this year"
)
def get_medication_gaps(
    pid: int,
    year: int = Query(
        0, ge=0, description="Calendar year to check (defaults to current year)"
    ),
    current_user: dict = Depends(get_current_user),
    _perm: None = Depends(require_permission("patients", "read")),
) -> dict[str, Any]:
    """
    Return active medications whose linked ICD-10 diagnosis has not been
    billed in *year* (defaults to the current calendar year).

    Each prescription in OpenEMR carries a ``diagnosis`` field containing the
    ICD-10 code(s) the medication was prescribed for.  This endpoint surfaces
    cases where an active medication implies an ongoing condition that has not
    yet been substantiated by a claim in the target year — a direct RAF
    recapture opportunity.

    The ``diagnosis`` field is parsed robustly: single codes, semicolon-
    separated lists, codes embedded in free text, and prefixed values (e.g.
    ``ICD10:E11.9``) are all handled.

    Response shape
    --------------
    ``gaps``     - list of gap items, each with:
                     icd_code   - the ICD-10 code from the prescription
                     drug       - the medication name
                     active     - always 1 (only active Rx are considered)
                     description - human-readable ICD-10 description (if known)
                     valid_icd10 - whether the code passes ICD-10-CM validation
    ``year``     - the calendar year checked
    ``gap_count``- number of distinct (icd_code, drug) pairs returned
    """
    from datetime import date as _date

    from app.services.icd_validator import get_description, validate_code

    if year is None:
        year = _date.today().year

    _tid = _tenant_of(current_user)
    if not _patient_belongs_to_tenant(pid, _tid) and not _patient_in_active_connection(pid, tenant_id=_tid):
        raise HTTPException(status_code=404, detail=f"Patient {pid} not found")

    patient = emr.get_patient(pid)
    if not patient:
        raise HTTPException(status_code=404, detail=f"Patient {pid} not found")

    # Resolve emr_pid for OpenEMR clinical queries
    emr_pid = _get_emr_pid(pid, tenant_id=_tid) or pid

    try:
        gaps = emr.get_medication_diagnosis_gaps(emr_pid, year)
    except Exception as exc:
        logger.error("get_medication_gaps error pid=%s year=%s: %s", pid, year, exc)
        raise HTTPException(status_code=500, detail="Internal server error")

    # Enrich each gap with a human-readable ICD-10 description.
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
# Diagnoses (billing ICD-10 codes)
# ---------------------------------------------------------------------------


@router.get("/{pid}/diagnoses", summary="Get patient billing ICD-10 codes")
def get_diagnoses(
    pid: int,
    current_user: dict = Depends(get_current_user),
    _perm: None = Depends(require_permission("patients", "read")),
) -> dict[str, Any]:
    """
    Return all ICD-10 billing codes for *pid* from the billing table,
    enriched with code descriptions via the ICD-10-CM index.
    """
    from app.services.icd_validator import get_description, validate_code

    _tid = _tenant_of(current_user)
    if not _patient_belongs_to_tenant(pid, _tid) and not _patient_in_active_connection(pid, tenant_id=_tid):
        raise HTTPException(status_code=404, detail=f"Patient {pid} not found")

    patient = emr.get_patient(pid)
    if not patient:
        raise HTTPException(status_code=404, detail=f"Patient {pid} not found")

    # Resolve emr_pid for OpenEMR clinical queries
    emr_pid = _get_emr_pid(pid, tenant_id=_tid) or pid

    try:
        codes = emr.get_billing_codes(emr_pid)
    except Exception as exc:
        logger.error("get_diagnoses error pid=%s: %s", pid, exc)
        raise HTTPException(status_code=500, detail="Internal server error")

    # Enrich with ICD-10-CM descriptions
    for row in codes:
        code = row.get("code", "")
        if code:
            row["description"] = get_description(code) or row.get("code_text", "")
            row["valid_icd10"] = validate_code(code)

    log_phi_access(
        action="view",
        resource="diagnosis",
        patient_id=pid,
        details=f"codes_returned={len(codes)}",
    )
    return {
        "pid": pid,
        "count": len(codes),
        "diagnoses": codes,
    }


# ---------------------------------------------------------------------------
# Procedures (CPT codes with condition hints)
# ---------------------------------------------------------------------------


@router.get(
    "/{pid}/procedures", summary="Get patient CPT procedure codes with condition hints"
)
def get_procedures(
    pid: int,
    current_user: dict = Depends(get_current_user),
    _perm: None = Depends(require_permission("patients", "read")),
) -> dict[str, Any]:
    """
    Return all active CPT4 procedure codes for *pid* from the billing table.

    Each row is enriched with a ``condition_hint`` block when the CPT code
    appears in CPT_CONDITION_HINTS.  The hint carries:
      - condition  : plain-English condition name
      - icd10      : representative ICD-10 code (None when ambiguous)
      - hcc        : primary HCC category (None when ambiguous)

    Codes without a hint entry are returned as-is with ``condition_hint: null``
    so callers can distinguish known-hint vs unknown without filtering.

    Example response
    ----------------
    {
      "pid": 42,
      "count": 3,
      "procedures": [
        {
          "code": "93306",
          "code_text": "Echo transthorcic",
          "date": "2025-11-01",
          "encounter": "1001",
          "modifier": null,
          "units": 1,
          "fee": 250.0,
          "condition_hint": {
            "condition": "Heart Disease",
            "icd10": "I50.9",
            "hcc": "HCC226"
          }
        },
        ...
      ]
    }
    """
    _tid = _tenant_of(current_user)
    if not _patient_belongs_to_tenant(pid, _tid) and not _patient_in_active_connection(pid, tenant_id=_tid):
        raise HTTPException(status_code=404, detail=f"Patient {pid} not found")

    patient = emr.get_patient(pid)
    if not patient:
        raise HTTPException(status_code=404, detail=f"Patient {pid} not found")

    # Resolve emr_pid for OpenEMR clinical queries
    emr_pid = _get_emr_pid(pid, tenant_id=_tid) or pid

    try:
        cpt_rows = emr.get_cpt_codes(emr_pid)
    except Exception as exc:
        logger.error("get_procedures error pid=%s: %s", pid, exc)
        raise HTTPException(status_code=500, detail="Internal server error")

    hints = emr.CPT_CONDITION_HINTS
    for row in cpt_rows:
        code = str(row.get("code") or "").strip()
        row["condition_hint"] = hints.get(code)  # None when not in dict

    return {
        "pid": pid,
        "count": len(cpt_rows),
        "procedures": cpt_rows,
    }


# ---------------------------------------------------------------------------
# Problem List
# ---------------------------------------------------------------------------


@router.get("/{pid}/problem-list", summary="Get patient active problem list")
def get_problem_list(
    pid: int,
    year: Optional[int] = Query(default=None, description="Filter problems by begdate year, e.g. 2024"),
    current_user: dict = Depends(get_current_user),
    _perm: None = Depends(require_permission("patients", "read")),
) -> dict[str, Any]:
    """
    Return all active medical problems for *pid* from OpenEMR's lists table.

    Each problem includes:
    - id, title        — row PK and free-text problem name entered by clinician
    - diagnosis        — raw ICD code (may be NULL/empty for title-only entries)
    - begdate/enddate  — onset and resolution dates
    - occurrence       — how often the condition recurs (OpenEMR lookup value)
    - outcome          — clinical outcome code
    - activity         — always 1 (active) for records returned here

    Entries where diagnosis is empty are still returned; the caller should
    treat them as unstructured problems that cannot be matched to HCC codes
    without manual review.

    When *year* is provided, only problems whose begdate falls in that
    calendar year are returned.  Omitting *year* returns all active problems.
    """
    _tid = _tenant_of(current_user)
    if not _patient_belongs_to_tenant(pid, _tid) and not _patient_in_active_connection(pid, tenant_id=_tid):
        raise HTTPException(status_code=404, detail=f"Patient {pid} not found")

    patient = emr.get_patient(pid)
    if not patient:
        raise HTTPException(status_code=404, detail=f"Patient {pid} not found")

    # Resolve emr_pid for OpenEMR clinical queries
    emr_pid = _get_emr_pid(pid, tenant_id=_tid) or pid

    try:
        problems = emr.get_problem_list(emr_pid, year=year)
    except Exception as exc:
        logger.error("get_problem_list error pid=%s: %s", pid, exc)
        raise HTTPException(status_code=500, detail="Internal server error")

    # Annotate each problem with extracted ICD-10 code
    for p in problems:
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
# Recapture Gaps
# ---------------------------------------------------------------------------


@router.get("/{pid}/recapture-gaps", summary="Active problems not billed this year")
def get_recapture_gaps(
    pid: int,
    year: Optional[int] = Query(
        default=None,
        ge=2000,
        le=2100,
        description="Calendar year to check billing against. Defaults to current year.",
    ),
    current_user: dict = Depends(get_current_user),
    _perm: None = Depends(require_permission("patients", "read")),
) -> dict[str, Any]:
    """
    Return active medical problems from the problem list that have NOT been
    substantiated by an ICD-10 billing claim in *year*.

    These represent RAF recapture opportunities: chronic conditions already
    documented in OpenEMR but not re-coded in the current payment year.
    CMS requires annual documentation of HCC-mapped diagnoses for them to
    contribute to the patient's risk score.

    Only problems with a populated diagnosis code are evaluated; title-only
    entries are excluded because they cannot be matched to billing rows.

    Query parameter:
    - year (int, optional): defaults to the current calendar year.
    """
    from datetime import date as _date

    if year is None:
        year = _date.today().year

    _tid = _tenant_of(current_user)
    if not _patient_belongs_to_tenant(pid, _tid) and not _patient_in_active_connection(pid, tenant_id=_tid):
        raise HTTPException(status_code=404, detail=f"Patient {pid} not found")

    patient = emr.get_patient(pid)
    if not patient:
        raise HTTPException(status_code=404, detail=f"Patient {pid} not found")

    # Resolve emr_pid for OpenEMR clinical queries
    emr_pid = _get_emr_pid(pid, tenant_id=_tid) or pid

    try:
        gaps = emr.get_recapture_gaps(emr_pid, year)
    except Exception as exc:
        logger.error("get_recapture_gaps error pid=%s year=%s: %s", pid, year, exc)
        raise HTTPException(status_code=500, detail="Internal server error")

    return {
        "pid": pid,
        "year": year,
        "count": len(gaps),
        "recapture_gaps": gaps,
    }


# ---------------------------------------------------------------------------
# Vitals Suspects — rule-based suspect conditions derived from form_vitals
# ---------------------------------------------------------------------------


@router.get("/{pid}/vitals-suspects", summary="Vitals-based suspect conditions")
def get_vitals_suspects(
    pid: int,
    year: Optional[int] = Query(
        None,
        ge=2000,
        le=2100,
        description=(
            "Filter vitals by measurement year (e.g. 2024). "
            "When omitted the most recent vitals across all years are used."
        ),
    ),
    current_user: dict = Depends(get_current_user),
    _perm: None = Depends(require_permission("patients", "read")),
) -> dict[str, Any]:
    """
    Evaluate the most recent vitals recorded in form_vitals for *pid* against
    a set of clinical threshold rules and return conditions that appear suspect
    but are not already present in the patient's billing or problem-list records.

    Rules applied
    -------------
    - BMI >= 40                  → Morbid Obesity (E66.01 / HCC48)
    - BMI 35-39.9                → Severe Obesity (E66.01 / HCC48)
    - Oxygen saturation < 88 %   → Chronic Respiratory Failure (J96.11 / HCC213)
    - Systolic BP >= 180 mmHg    → Hypertensive Crisis (I16.0)
    - Weight loss >= 10 % trend  → Malnutrition/Cachexia (R63.4)

    Existing diagnoses are sourced from ``get_all_patient_diagnoses``, which
    unions the billing table and active problem list.  A suspect is suppressed
    when its ICD-10 code (dot-stripped) already appears in that union.

    Each returned suspect includes:
        field           — vital field that triggered the rule
        measured_value  — the numeric value observed
        condition       — human-readable condition name
        icd10           — suggested ICD-10 code
        hcc             — HCC category or null
        confidence      — float 0-1
        evidence        — short narrative for display
        vitals_date     — date of the vitals reading used

    Query Parameters
    ----------------
    year (optional):
        Restrict vitals used for evaluation to those recorded in this
        calendar year.  Omit to use the most recent vitals regardless of year.
    """
    _tid = _tenant_of(current_user)
    if not _patient_belongs_to_tenant(pid, _tid) and not _patient_in_active_connection(pid, tenant_id=_tid):
        raise HTTPException(status_code=404, detail=f"Patient {pid} not found")

    patient = emr.get_patient(pid)
    if not patient:
        raise HTTPException(status_code=404, detail=f"Patient {pid} not found")

    # Resolve emr_pid for OpenEMR clinical queries
    emr_pid = _get_emr_pid(pid, tenant_id=_tid) or pid

    try:
        all_diagnoses = emr.get_all_patient_diagnoses(emr_pid)
        existing_codes = [d.get("icd_code", "") for d in all_diagnoses]
    except Exception as exc:
        logger.warning(
            "get_vitals_suspects: could not fetch diagnoses pid=%s: %s", pid, exc
        )
        existing_codes = []

    try:
        suspects = emr.detect_vitals_suspects(
            emr_pid, existing_diagnoses=existing_codes, year=year
        )
    except Exception as exc:
        logger.error("get_vitals_suspects error pid=%s: %s", pid, exc)
        raise HTTPException(status_code=500, detail="Internal server error")

    # Fetch the year-filtered latest vitals so the frontend can display the
    # raw readings alongside the suspects without falling back to the
    # all-time profile endpoint.
    try:
        trends = emr.get_vitals_trends(emr_pid, year=year)  # type: ignore[attr-defined]
        latest_vitals: dict[str, Any] = trends.get("latest_vitals") or {}
    except Exception as exc:  # pragma: no cover
        logger.warning("get_vitals_suspects: could not fetch trends pid=%s: %s", pid, exc)
        latest_vitals = {}

    patient_name = (
        f"{patient.get('fname', '')} {patient.get('lname', '')}".strip()
        or f"Patient {pid}"
    )

    # Sort by confidence descending so highest-confidence suspects appear first
    suspects.sort(key=lambda s: s.get("confidence", 0), reverse=True)

    return {
        "pid": pid,
        "patient_name": patient_name,
        "count": len(suspects),
        "vitals_suspects": suspects,
        "latest_vitals": latest_vitals,
    }


# ---------------------------------------------------------------------------
# Lab & Vitals Suspects — rule-based, no LLM required
# ---------------------------------------------------------------------------


@router.get("/{pid}/lab-suspects", summary="Rule-based lab/vitals suspect conditions")
def get_lab_suspects(
    pid: int,
    year: Optional[int] = Query(
        default=None,
        description="Filter notes and vitals by calendar year (e.g. 2025). Omit to include all available records.",
    ),
    current_user: dict = Depends(get_current_user),
    _perm: None = Depends(require_permission("patients", "read")),
) -> dict[str, Any]:
    """
    Return suspect HCC conditions derived purely from lab values and vitals
    embedded in clinical notes and structured form_vitals rows.

    This endpoint is SUPPLEMENTARY to the Gemini pipeline.  It runs a
    deterministic regex + threshold engine (``lab_suspect_engine``) and
    returns results immediately without any LLM call, making it fast and
    available even when the full pipeline has not been run for this patient.

    Each suspect includes:
    - ``lab``               – the measurement that triggered the rule (e.g. "HbA1c")
    - ``value``             – extracted numeric value
    - ``threshold``         – the clinical threshold that was breached
    - ``operator``          – comparison direction (">=", "<", etc.)
    - ``condition``         – plain-English condition name
    - ``icd10``             – suggested ICD-10-CM code
    - ``hcc``               – HCC category label (null if not HCC-relevant)
    - ``source``            – "clinical_note" | "vitals"
    - ``confidence_score``  – heuristic 0.0–1.0 score
    - ``evidence_detail``   – dict with raw match context

    Suspects already present in the patient's billing record (matched by
    ICD-10 category prefix) are automatically excluded.

    Example response
    ----------------
    ::

        {
          "pid": 42,
          "notes_scanned": 7,
          "vitals_rows_checked": 3,
          "existing_diagnosis_count": 12,
          "note_suspects_count": 2,
          "vitals_suspects_count": 1,
          "total_suspects": 3,
          "suspects": [
            {
              "lab": "HbA1c",
              "value": 7.2,
              "threshold": 6.5,
              "operator": ">=",
              "condition": "Type 2 Diabetes",
              "icd10": "E11.65",
              "hcc": "HCC37",
              "source": "clinical_note",
              "confidence_score": 0.8212,
              "evidence_detail": { ... }
            },
            ...
          ]
        }
    """
    _tid = _tenant_of(current_user)
    if not _patient_belongs_to_tenant(pid, _tid) and not _patient_in_active_connection(pid, tenant_id=_tid):
        raise HTTPException(status_code=404, detail=f"Patient {pid} not found")

    patient = emr.get_patient(pid)
    if not patient:
        raise HTTPException(status_code=404, detail=f"Patient {pid} not found")

    # Resolve emr_pid for OpenEMR clinical queries
    emr_pid = _get_emr_pid(pid, tenant_id=_tid) or pid

    from app.services.lab_suspect_engine import run_lab_suspect_scan

    try:
        result = run_lab_suspect_scan(emr_pid, year=year)
    except Exception as exc:
        logger.error("get_lab_suspects error pid=%s: %s", pid, exc)
        raise HTTPException(status_code=500, detail="Internal server error")

    patient_name = (
        f"{patient.get('fname', '')} {patient.get('lname', '')}".strip()
        or f"Patient {pid}"
    )

    return {
        "pid": pid,
        "patient_name": patient_name,
        "year_filter": year,
        "notes_scanned": result["notes_scanned"],
        "vitals_rows_checked": result["vitals_rows_checked"],
        "existing_diagnosis_count": result["existing_diagnosis_count"],
        "note_suspects_count": len(result["note_suspects"]),
        "vitals_suspects_count": len(result["vitals_suspects"]),
        "total_suspects": len(result["all_suspects"]),
        "suspects": result["all_suspects"],
    }


# ---------------------------------------------------------------------------
# Comprehensive Profile — aggregated multi-source patient view for RAF analysis
# ---------------------------------------------------------------------------


def _calculate_age(dob_raw: str | None) -> int | None:
    """
    Return the patient's current age in years, or None when DOB is absent/unparseable.

    Age is computed relative to today's calendar date, NOT the CMS Feb-1 convention
    used by the RAF calculator.  This value is purely for display purposes in the
    profile view.
    """
    if not dob_raw:
        return None
    try:
        dob = _datetime.strptime(str(dob_raw)[:10], "%Y-%m-%d").date()
        today = _date.today()
        return today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))
    except (ValueError, TypeError):
        return None


def _safe_call(label: str, fn, *args, default=None, **kwargs):
    """
    Call *fn* with *args*/*kwargs* and return the result.

    On any exception, log a warning and return *default* so a single broken
    data source never aborts the whole profile assembly.
    """
    try:
        return fn(*args, **kwargs)
    except Exception as exc:
        logger.warning("comprehensive-profile [%s] failed: %s", label, exc)
        return default


@router.get(
    "/{pid}/comprehensive-profile",
    summary="Complete patient profile for RAF analysis",
)
def get_comprehensive_profile(
    pid: int,
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
    _perm: None = Depends(require_permission("patients", "read")),
) -> dict[str, Any]:
    """
    Aggregate ALL available OpenEMR data sources into a single response.

    Used by the frontend to show the complete patient picture before and after
    RAF analysis.  Every sub-call is individually wrapped so that a failure in
    one data source (e.g. a table that does not exist yet in the target database,
    or a service being developed by another agent) never breaks the response.
    Missing data sources return empty lists / None and are reflected in the
    ``data_completeness`` block so the UI can surface meaningful warnings.

    Data sources aggregated
    -----------------------
    - Patient demographics (DOB, sex, race, ethnicity)
    - Billing: ICD-10 codes + CPT procedure codes
    - Problem list (OpenEMR lists table, ~990 K rows)
    - Recapture gaps: active problems not yet billed in the current year
    - Medications (active prescriptions) + medication-diagnosis gaps
    - Encounters (full history with provider info)
    - Vitals: latest structured reading + rule-based vitals suspects
    - Labs: rule-based lab suspects from clinical notes and procedure_result
    - Immunizations (``immunizations`` table)
    - Enrollment info (OREC + dual-eligibility derived from insurance_data)
    - HEDIS compliance indicators
    - Family history (``lists`` type=family_history)
    - Allergies (``lists`` type=allergy)
    - Referrals (``referrals`` table)
    - RAF: current score + HCC breakdown from raf_scores / raf_patient_hcc

    All timestamps / Decimal values are pre-serialised to JSON-safe types by the
    individual service functions before reaching this layer.
    """
    # ------------------------------------------------------------------
    # 1. Resolve patient — hard 404 if not found; no fallback.
    # ------------------------------------------------------------------
    _tid = _tenant_of(current_user)
    if not _patient_belongs_to_tenant(pid, _tid) and not _patient_in_active_connection(pid, tenant_id=_tid):
        raise HTTPException(status_code=404, detail=f"Patient {pid} not found")

    patient = emr.get_patient(pid)
    if not patient:
        raise HTTPException(status_code=404, detail=f"Patient {pid} not found")

    # Resolve emr_pid for OpenEMR clinical queries
    emr_pid = _get_emr_pid(pid, tenant_id=_tid) or pid

    current_year = _date.today().year

    # ------------------------------------------------------------------
    # 2. Collect every data source independently.
    # ------------------------------------------------------------------

    # --- Billing -------------------------------------------------------
    icd10_codes = _safe_call("billing.icd10", emr.get_billing_codes, emr_pid, default=[])
    cpt_codes = _safe_call("billing.cpt", emr.get_cpt_codes, emr_pid, default=[])

    # Attach condition hints to CPT codes (local dict, never fails)
    hints = emr.CPT_CONDITION_HINTS
    for row in cpt_codes:
        code = str(row.get("code") or "").strip()
        row.setdefault("condition_hint", hints.get(code))

    # --- Problem list --------------------------------------------------
    problem_list = _safe_call("problem_list", emr.get_problem_list, emr_pid, default=[])
    for p in problem_list:
        raw_dx = p.get("diagnosis") or ""
        # Extract ICD-10 code from "ICD10:E11.22" format
        icd10 = raw_dx.split(":")[-1].strip() if ":" in raw_dx else raw_dx.strip()
        p["icd10_code"] = icd10 or None
        p["diagnosis_code"] = icd10 or None
        p["has_icd_code"] = bool(icd10)

    # --- Recapture gaps ------------------------------------------------
    recapture_gaps = _safe_call(
        "recapture_gaps", emr.get_recapture_gaps, emr_pid, current_year, default=[]
    )

    # --- Medications ---------------------------------------------------
    medications = _safe_call("medications", emr.get_medications, emr_pid, default=[])

    # get_medication_diagnosis_gaps may not exist yet (added by another agent)
    medication_diagnosis_gaps = _safe_call(
        "medication_diagnosis_gaps",
        emr.get_medication_diagnosis_gaps,  # type: ignore[attr-defined]
        emr_pid,
        current_year,
        default=[],
    )

    # --- Encounters ----------------------------------------------------
    encounters = _safe_call("encounters", emr.get_encounters, emr_pid, default=[])

    # --- Vitals --------------------------------------------------------
    # get_latest_vitals may not exist yet; fall back to get_vitals and take first row
    latest_vitals = _safe_call(
        "vitals.latest",
        emr.get_latest_vitals,  # type: ignore[attr-defined]
        emr_pid,
        default=None,
    )
    if latest_vitals is None:
        all_vitals = _safe_call("vitals.all", emr.get_vitals, emr_pid, default=[])
        latest_vitals = all_vitals[0] if all_vitals else None

    # Vitals-based suspects from the rule-based lab suspect engine
    vitals_suspects: list[dict[str, Any]] = []
    try:
        from app.services.lab_suspect_engine import run_lab_suspect_scan  # type: ignore

        lab_scan = run_lab_suspect_scan(emr_pid)
        vitals_suspects = lab_scan.get("vitals_suspects", [])
        lab_suspects_list = lab_scan.get("all_suspects", [])
    except Exception as exc:
        logger.warning("comprehensive-profile [lab_suspect_engine] failed: %s", exc)
        lab_suspects_list = []

    # --- Immunizations -------------------------------------------------
    immunizations = _safe_call(
        "immunizations",
        emr.get_immunizations,  # type: ignore[attr-defined]
        emr_pid,
        default=[],
    )

    # --- Enrollment info -----------------------------------------------
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

    # --- HEDIS compliance ----------------------------------------------
    # get_hedis_compliance may not exist yet (added by another agent)
    hedis: dict[str, Any] = _safe_call(
        "hedis",
        emr.get_hedis_compliance,  # type: ignore[attr-defined]
        emr_pid,
        current_year,
        default={},
    )

    # --- Family history ------------------------------------------------
    family_history = _safe_call(
        "family_history",
        emr.get_family_history,  # type: ignore[attr-defined]
        emr_pid,
        default=[],
    )

    # --- Allergies -----------------------------------------------------
    allergies = _safe_call(
        "allergies",
        emr.get_allergies,  # type: ignore[attr-defined]
        emr_pid,
        default=[],
    )

    # --- Referrals -----------------------------------------------------
    referrals = _safe_call(
        "referrals",
        emr.get_referrals,  # type: ignore[attr-defined]
        emr_pid,
        default=[],
    )

    # --- RAF score + breakdown ----------------------------------------
    raf_current_score: float | None = None
    raf_breakdown: dict[str, Any] | None = None

    for yr in [current_year, current_year - 1]:
        raf_data = _safe_call("raf_breakdown", get_raf_breakdown, pid, yr, tenant_id=tenant_id, default={})
        if raf_data:
            raf_current_score = raf_data.get("raf_score")
            raf_breakdown = raf_data
            break

    # --- Clinical notes existence check (for completeness only) --------
    # We check encounter-level has_notes flags rather than fetching all note text.
    has_clinical_notes = any(bool(enc.get("has_notes")) for enc in encounters)

    # --- Insurance / coverage existence check --------------------------
    has_insurance = enrollment.get("source") not in (None, "default", "unavailable")

    # ------------------------------------------------------------------
    # 3. Compute data completeness score (0–100 %).
    # ------------------------------------------------------------------
    # Check actual lab results (not just suspects)
    actual_labs = _safe_call("labs", emr.get_labs, emr_pid, default=[])

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
    completeness_pct = round(
        sum(completeness_flags.values()) / len(completeness_flags) * 100
    )

    # ------------------------------------------------------------------
    # 4. Assemble final response.
    # ------------------------------------------------------------------
    log_phi_access(
        action="view",
        resource="profile",
        patient_id=pid,
        details=f"completeness_pct={completeness_pct}",
    )
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
# Family History
# ---------------------------------------------------------------------------


@router.get("/{pid}/family-history", summary="Get patient family history")
def get_family_history(
    pid: int,
    current_user: dict = Depends(get_current_user),
    _perm: None = Depends(require_permission("patients", "read")),
) -> dict[str, Any]:
    """
    Return the most recent family-history record for *pid* from
    OpenEMR's history_data table.

    The response includes only columns that describe relatives' diagnoses
    (relatives_cancer, relatives_diabetes, relatives_heart_disease, etc.).
    An empty ``family_history`` dict is returned when the table does not
    exist in this OpenEMR deployment or the patient has no record.

    This data enriches the risk-stratification pipeline: a positive family
    history of diabetes or cardiovascular disease, for example, can support
    suspect-condition recommendations when the patient's own diagnoses are
    incomplete.
    """
    _tid = _tenant_of(current_user)
    if not _patient_belongs_to_tenant(pid, _tid) and not _patient_in_active_connection(pid, tenant_id=_tid):
        raise HTTPException(status_code=404, detail=f"Patient {pid} not found")

    patient = emr.get_patient(pid)
    if not patient:
        raise HTTPException(status_code=404, detail=f"Patient {pid} not found")

    # Resolve emr_pid for OpenEMR clinical queries
    emr_pid = _get_emr_pid(pid, tenant_id=_tid) or pid

    family_history = emr.get_family_history(emr_pid)

    return {
        "pid": pid,
        "family_history": family_history,
    }


# ---------------------------------------------------------------------------
# SDOH
# ---------------------------------------------------------------------------


@router.get("/{pid}/sdoh", summary="Get Social Determinants of Health data")
def get_sdoh(
    pid: int,
    current_user: dict = Depends(get_current_user),
    _perm: None = Depends(require_permission("patients", "read")),
) -> dict[str, Any]:
    """
    Return Social Determinants of Health (SDOH) data for *pid*.

    The response combines two sources:

    1. ``sdoh_form`` — the raw row from form_history_sdoh (OpenEMR >= 6.x).
       ``null`` when the table is absent or no record exists.

    2. ``billed_z_codes`` — ICD-10 Z-codes already present on the patient's
       claims (Z5x through Z9x range), each with the most recent billing date.
       Empty list when none exist.

    3. ``billable_highlights`` — reference map of the six highest-value SDOH
       Z-codes that CMS accepts for risk adjustment:
           Z59.0  Homelessness
           Z59.1  Inadequate housing
           Z56.0  Unemployment
           Z63.0  Relationship problems
           Z60.2  Living alone
           Z91.120 Food insecurity

    These codes are billable and can contribute to quality measures and
    Enhanced Medication Adherence scores.  Practices that document SDOH but
    do not bill the corresponding Z-codes leave value on the table.
    """
    _tid = _tenant_of(current_user)
    if not _patient_belongs_to_tenant(pid, _tid) and not _patient_in_active_connection(pid, tenant_id=_tid):
        raise HTTPException(status_code=404, detail=f"Patient {pid} not found")

    patient = emr.get_patient(pid)
    if not patient:
        raise HTTPException(status_code=404, detail=f"Patient {pid} not found")

    # Resolve emr_pid for OpenEMR clinical queries
    emr_pid = _get_emr_pid(pid, tenant_id=_tid) or pid

    sdoh = emr.get_sdoh_data(emr_pid)

    return sdoh


# ---------------------------------------------------------------------------
# Allergies
# ---------------------------------------------------------------------------


@router.get("/{pid}/allergies", summary="Get patient active allergies")
def get_allergies(
    pid: int,
    current_user: dict = Depends(get_current_user),
    _perm: None = Depends(require_permission("patients", "read")),
) -> dict[str, Any]:
    """
    Return all active allergy records for *pid* from OpenEMR's lists table.

    Each record includes:
    - ``title``     — free-text allergen name (e.g. "Penicillin", "Peanuts")
    - ``diagnosis`` — structured reaction code (ICD/SNOMED) when available;
                      may be empty for free-text-only entries
    - ``begdate``   — date the allergy was first recorded

    Allergies are relevant to the RAF pipeline because certain drug allergies
    constrain medication options for chronic conditions (e.g. ACE inhibitor
    allergy in a CHF patient) and may indicate underlying diagnoses.

    An empty list is returned when no active allergies exist or the table is
    inaccessible.
    """
    _tid = _tenant_of(current_user)
    if not _patient_belongs_to_tenant(pid, _tid) and not _patient_in_active_connection(pid, tenant_id=_tid):
        raise HTTPException(status_code=404, detail=f"Patient {pid} not found")

    patient = emr.get_patient(pid)
    if not patient:
        raise HTTPException(status_code=404, detail=f"Patient {pid} not found")

    # Resolve emr_pid for OpenEMR clinical queries
    emr_pid = _get_emr_pid(pid, tenant_id=_tid) or pid

    allergies = emr.get_allergies(emr_pid)

    return {
        "pid": pid,
        "count": len(allergies),
        "allergies": allergies,
    }


# ---------------------------------------------------------------------------
# Referrals
# ---------------------------------------------------------------------------


@router.get("/{pid}/referrals", summary="Get patient referral transactions")
def get_referrals(
    pid: int,
    current_user: dict = Depends(get_current_user),
    _perm: None = Depends(require_permission("patients", "read")),
) -> dict[str, Any]:
    """
    Return all referral transactions for *pid* from OpenEMR's transactions
    table (rows with title='Referral'), ordered newest first.

    Each record includes:
    - ``id``          — transaction PK
    - ``date``        — date referral was created
    - ``body``        — free-text referral notes / clinical summary
    - ``refer_to``    — specialist or facility being referred to
    - ``refer_from``  — referring provider
    - ``reason``      — structured reason for referral
    - ``reply_date``  — date consultation reply was received (null if pending)

    Referrals surface care-coordination context useful for identifying
    specialty conditions (e.g. referral to cardiology may indicate undiagnosed
    HF) and for closing care gaps when a reply has not been received.

    An empty list is returned when the transactions table is absent or no
    referrals exist for the patient.
    """
    _tid = _tenant_of(current_user)
    if not _patient_belongs_to_tenant(pid, _tid) and not _patient_in_active_connection(pid, tenant_id=_tid):
        raise HTTPException(status_code=404, detail=f"Patient {pid} not found")

    patient = emr.get_patient(pid)
    if not patient:
        raise HTTPException(status_code=404, detail=f"Patient {pid} not found")

    # Resolve emr_pid for OpenEMR clinical queries
    emr_pid = _get_emr_pid(pid, tenant_id=_tid) or pid

    referrals = emr.get_referrals(emr_pid)

    return {
        "pid": pid,
        "count": len(referrals),
        "referrals": referrals,
    }


# ---------------------------------------------------------------------------
# Immunizations
# ---------------------------------------------------------------------------


@router.get("/{pid}/immunizations", summary="Get patient immunization history")
def get_immunizations(
    pid: int,
    current_user: dict = Depends(get_current_user),
    _perm: None = Depends(require_permission("patients", "read")),
) -> dict[str, Any]:
    """
    Return the complete immunization history for *pid* from the OpenEMR
    immunizations table.

    Each record includes:
    - id, administered_date, cvx_code, manufacturer, lot_number
    - administered_by, education_date, note

    Records flagged as added_erroneously in OpenEMR are excluded.
    CVX codes are the CDC standard vaccine identifiers -- use them for any
    downstream matching, not free-text descriptions.
    """
    _tid = _tenant_of(current_user)
    if not _patient_belongs_to_tenant(pid, _tid) and not _patient_in_active_connection(pid, tenant_id=_tid):
        raise HTTPException(status_code=404, detail=f"Patient {pid} not found")

    patient = emr.get_patient(pid)
    if not patient:
        raise HTTPException(status_code=404, detail=f"Patient {pid} not found")

    # Resolve emr_pid for OpenEMR clinical queries
    emr_pid = _get_emr_pid(pid, tenant_id=_tid) or pid

    try:
        immunizations = emr.get_immunizations(emr_pid)
    except Exception as exc:
        logger.error("get_immunizations error pid=%s: %s", pid, exc)
        raise HTTPException(status_code=500, detail="Internal server error")

    return {
        "pid": pid,
        "count": len(immunizations),
        "immunizations": immunizations,
    }


# ---------------------------------------------------------------------------
# HEDIS / Stars quality measures
# ---------------------------------------------------------------------------


@router.get("/{pid}/hedis", summary="HEDIS/Stars quality measure compliance")
def get_hedis_compliance(
    pid: int,
    year: int = Query(
        default=0,
        ge=2000,
        le=2100,
        description="Measurement year.  Defaults to the current calendar year.",
    ),
    current_user: dict = Depends(get_current_user),
    _perm: None = Depends(require_permission("patients", "read")),
) -> dict[str, Any]:
    """
    Return HEDIS/Stars quality measure compliance for *pid*.

    Each measure in the response contains:
    - measure      : human-readable measure name
    - due          : whether the measure applies to this patient (age/sex-gated)
    - compliant    : whether the patient currently meets the measure
    - last_date    : ISO date of the most recent qualifying event, or null

    Measures currently evaluated
    ----------------------------
    flu_vaccine     -- Annual influenza vaccination (all ages)
    pneumococcal    -- Pneumococcal vaccination series (age >= 65)
    zoster          -- Shingles vaccination series (age >= 50)

    Compliance is determined using CDC CVX vaccine codes sourced from the
    OpenEMR immunizations table.  Free-text note matching is used only as a
    secondary fallback for influenza when no CVX code is recorded.
    """
    from datetime import date as _date

    if year is None:
        year = _date.today().year

    _tid = _tenant_of(current_user)
    if not _patient_belongs_to_tenant(pid, _tid) and not _patient_in_active_connection(pid, tenant_id=_tid):
        raise HTTPException(status_code=404, detail=f"Patient {pid} not found")

    patient = emr.get_patient(pid)
    if not patient:
        raise HTTPException(status_code=404, detail=f"Patient {pid} not found")

    # Resolve emr_pid for OpenEMR clinical queries
    emr_pid = _get_emr_pid(pid, tenant_id=_tid) or pid

    try:
        measures = emr.get_hedis_compliance(emr_pid, year)
    except Exception as exc:
        logger.error("get_hedis_compliance error pid=%s year=%s: %s", pid, year, exc)
        raise HTTPException(status_code=500, detail="Internal server error")

    due_count = sum(1 for m in measures.values() if m.get("due"))
    compliant_count = sum(
        1 for m in measures.values() if m.get("due") and m.get("compliant")
    )

    return {
        "pid": pid,
        "year": year,
        "summary": {
            "measures_due": due_count,
            "measures_compliant": compliant_count,
            "compliance_rate": round(compliant_count / due_count, 2)
            if due_count
            else None,
        },
        "measures": measures,
    }


# ---------------------------------------------------------------------------
# Enrollment / Insurance Info
# ---------------------------------------------------------------------------


@router.get(
    "/{pid}/enrollment", summary="Get patient enrollment and insurance/dual status"
)
def get_patient_enrollment(
    pid: int,
    current_user: dict = Depends(get_current_user),
    _perm: None = Depends(require_permission("patients", "read")),
) -> dict[str, Any]:
    """
    Return enrollment and insurance metadata for *pid* derived from OpenEMR
    insurance_data, insurance_companies, and form_encounter tables.

    Response fields
    ---------------
    dual_status         -- "non_dual" | "partial_dual" | "full_dual"
    primary_insurance   -- display name of the primary insurer, or null
    secondary_insurance -- display name of the secondary insurer, or null
    orec                -- "0" (aged) | "1" (disabled).  CMS Original Reason
                           for Entitlement Code derived from patient age.
                           ESRD (OREC 2/3) cannot be detected from OpenEMR.
    institutional       -- true when any recent encounter has a facility-based
                           POS code (SNF=31, Nursing Facility=32, etc.)
    pos_codes           -- list of distinct POS codes from recent encounters
    source              -- how the data was derived:
                             "openemr_insurance"   -- matched insurance records
                             "openemr_age_heuristic" -- age only, no insurance data
                             "default"              -- no usable data; CNA assumed
    confidence          -- "high" | "medium" | "low"

    This endpoint never returns a 500 — if data is unavailable it falls back
    gracefully to CNA defaults (non_dual, aged, not institutional).
    """
    _tid = _tenant_of(current_user)
    if not _patient_belongs_to_tenant(pid, _tid) and not _patient_in_active_connection(pid, tenant_id=_tid):
        raise HTTPException(status_code=404, detail=f"Patient {pid} not found")

    patient = emr.get_patient(pid)
    if not patient:
        raise HTTPException(status_code=404, detail=f"Patient {pid} not found")

    # Resolve emr_pid for OpenEMR clinical queries
    emr_pid = _get_emr_pid(pid, tenant_id=_tid) or pid

    enrollment = emr.get_patient_enrollment_info(emr_pid)

    return {
        "pid": pid,
        "enrollment": enrollment,
    }
