"""
Patient router — thin dispatch layer.

All business logic lives in app.services.patient_service.

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
from typing import Any, Optional

from fastapi import Depends, APIRouter, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import Response

from app.services import openemr_connector as emr
from app.services.audit_logger import log_phi_access
from app.services import patient_service as svc
from app.auth import get_current_user, get_tenant_id, require_permission
from app.rate_limit import limiter

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/patients", tags=["patients"])

# Maximum upload size: 10 MB
_MAX_CSV_BYTES = 10 * 1024 * 1024


# ---------------------------------------------------------------------------
# Internal guards — reused by many endpoints
# ---------------------------------------------------------------------------

def _require_patient_access(pid: int, tenant_id: str) -> None:
    """Raise 404 when *pid* is not accessible for *tenant_id*."""
    if not svc.patient_is_accessible(pid, tenant_id):
        raise HTTPException(status_code=404, detail=f"Patient {pid} not found")


def _require_emr_patient(pid: int, tenant_id: str) -> bool:
    """Return True when patient exists in the local OpenEMR DB.

    For FHIR patients (stored in emr_patient_matches), this returns False so
    callers can return empty clinical sub-resources instead of raising 404.
    Never raises — the caller decides how to handle a False result.
    """
    if svc.patient_is_fhir(pid, tenant_id):
        return False
    patient = emr.get_patient(pid)
    return bool(patient)


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
    try:
        result = svc.svc_list_patients(
            limit=limit,
            offset=offset,
            search=search.strip(),
            year=year,
            tenant_id=get_tenant_id(current_user),
        )
    except RuntimeError:
        raise HTTPException(status_code=500, detail="Internal server error")

    log_phi_access(
        action="list",
        resource="patient",
        details=f"limit={limit} offset={offset} search={search!r} returned={len(result['patients'])}",
    )
    return result


# ---------------------------------------------------------------------------
# Patients with encounters (for pipeline demo)
# ---------------------------------------------------------------------------


@router.get("/with-encounters", summary="Patients that have encounter data")
def patients_with_encounters(
    limit: int = Query(200, ge=1, le=500),
    current_user: dict = Depends(get_current_user),
    _perm: None = Depends(require_permission("patients", "read")),
    tenant_id: str = Depends(get_tenant_id),
) -> dict[str, Any]:
    """Return only patients that have at least one encounter."""
    try:
        return svc.svc_patients_with_encounters(limit=limit, tenant_id=tenant_id)
    except Exception as exc:
        logger.error("patients_with_encounters error: %s", exc)
        raise HTTPException(status_code=500, detail="Internal server error")


# ---------------------------------------------------------------------------
# Bulk CSV / Excel Import
# ---------------------------------------------------------------------------


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
    """
    from app.services.patient_import_service import (
        get_import_template_xlsx as _xlsx_tpl,
    )

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
    file: UploadFile = File(
        ..., description="CSV or Excel (.xlsx) file with patient records"
    ),
    on_duplicate: str = Query(
        "skip",
        description="Duplicate handling: 'skip' keeps existing records, 'update' overwrites existing with new data",
        regex="^(skip|update|replace)$",
    ),
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
        raise HTTPException(
            status_code=422,
            detail={
                "message": "Could not parse uploaded file.",
                "errors": parse_errors,
            },
        )

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
    file: UploadFile = File(
        ..., description="FHIR R4 Bundle JSON file with Patient entries"
    ),
    on_duplicate: str = Query(
        "skip",
        description="Duplicate handling: 'skip' keeps existing records, 'update' overwrites existing with new data",
        regex="^(skip|update|replace)$",
    ),
    current_user: dict = Depends(get_current_user),
    _perm: None = Depends(require_permission("patients", "write")),
) -> dict[str, Any]:
    """
    Parse *file* as a FHIR R4 Patient Bundle, validate each entry, deduplicate
    against existing OpenEMR patients, and insert new patients.

    The file must be a valid FHIR R4 Bundle of type 'collection' or
    'transaction' containing Patient resources.

    Download the template via GET /api/patients/import/template/fhir.
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
        raise HTTPException(
            status_code=422,
            detail={
                "message": "Could not parse FHIR JSON file.",
                "errors": parse_errors,
            },
        )

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
    _require_patient_access(pid, tenant_id)

    patient = svc.svc_get_patient(pid, tenant_id)
    if not patient:
        raise HTTPException(status_code=404, detail=f"Patient {pid} not found")

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
    _tid = svc._tenant_of(current_user)
    _require_patient_access(pid, _tid)

    try:
        notes = svc.svc_get_clinical_notes(pid, encounter_id)
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
    year: Optional[int] = Query(
        default=None, description="Filter encounters by year (e.g. 2024)"
    ),
    current_user: dict = Depends(get_current_user),
    _perm: None = Depends(require_permission("patients", "read")),
) -> dict[str, Any]:
    """
    Return all encounters for *pid* from form_encounter.

    Query parameter:
    - **year**: optional integer — when provided, only encounters whose date
      starts with that year are returned.
    """
    _tid = svc._tenant_of(current_user)
    _require_patient_access(pid, _tid)

    result = svc.svc_get_encounters(pid=pid, year=year, tenant_id=_tid)

    log_phi_access(
        action="view",
        resource="encounter",
        patient_id=pid,
        details=f"encounters_returned={result['count']}",
    )
    return result


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
    _tid = svc._tenant_of(current_user)
    _require_patient_access(pid, _tid)

    return svc.svc_get_medications(pid=pid, year=year, tenant_id=_tid)


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
    _tid = svc._tenant_of(current_user)
    _require_patient_access(pid, _tid)

    try:
        return svc.svc_get_medication_gaps(pid=pid, year=year, tenant_id=_tid)
    except Exception as exc:
        logger.error("get_medication_gaps error pid=%s year=%s: %s", pid, year, exc)
        raise HTTPException(status_code=500, detail="Internal server error")


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
    _tid = svc._tenant_of(current_user)
    _require_patient_access(pid, _tid)

    result = svc.svc_get_diagnoses(pid=pid, tenant_id=_tid)

    log_phi_access(
        action="view",
        resource="diagnosis",
        patient_id=pid,
        details=f"codes_returned={result['count']}",
    )
    return result


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
    appears in CPT_CONDITION_HINTS.  Codes without a hint entry are returned
    as-is with ``condition_hint: null``.
    """
    _tid = svc._tenant_of(current_user)
    _require_patient_access(pid, _tid)

    if not _require_emr_patient(pid, _tid):
        return {"pid": pid, "count": 0, "procedures": [], "note": "Procedure data not yet synced for FHIR patients"}

    try:
        return svc.svc_get_procedures(pid=pid, tenant_id=_tid)
    except Exception as exc:
        logger.error("get_procedures error pid=%s: %s", pid, exc)
        raise HTTPException(status_code=500, detail="Internal server error")


# ---------------------------------------------------------------------------
# Problem List
# ---------------------------------------------------------------------------


@router.get("/{pid}/problem-list", summary="Get patient active problem list")
def get_problem_list(
    pid: int,
    year: Optional[int] = Query(
        default=None, description="Filter problems by begdate year, e.g. 2024"
    ),
    current_user: dict = Depends(get_current_user),
    _perm: None = Depends(require_permission("patients", "read")),
) -> dict[str, Any]:
    """
    Return all active medical problems for *pid* from OpenEMR's lists table.

    Each problem includes:
    - id, title        — row PK and free-text problem name entered by clinician
    - diagnosis        — raw ICD code (may be NULL/empty for title-only entries)
    - begdate/enddate  — onset and resolution dates

    When *year* is provided, only problems whose begdate falls in that
    calendar year are returned.  Omitting *year* returns all active problems.
    """
    _tid = svc._tenant_of(current_user)
    _require_patient_access(pid, _tid)

    return svc.svc_get_problem_list(pid=pid, year=year, tenant_id=_tid)


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

    Only problems with a populated diagnosis code are evaluated; title-only
    entries are excluded because they cannot be matched to billing rows.

    Query parameter:
    - year (int, optional): defaults to the current calendar year.
    """
    _tid = svc._tenant_of(current_user)
    _require_patient_access(pid, _tid)

    if not _require_emr_patient(pid, _tid):
        return {"pid": pid, "gaps": [], "year": year, "gap_count": 0, "note": "Recapture gap data not yet synced for FHIR patients"}

    try:
        return svc.svc_get_recapture_gaps(pid=pid, year=year, tenant_id=_tid)
    except Exception as exc:
        logger.error("get_recapture_gaps error pid=%s year=%s: %s", pid, year, exc)
        raise HTTPException(status_code=500, detail="Internal server error")


# ---------------------------------------------------------------------------
# Vitals Suspects
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
    - BMI >= 40                  — Morbid Obesity (E66.01 / HCC48)
    - BMI 35-39.9                — Severe Obesity (E66.01 / HCC48)
    - Oxygen saturation < 88 %   — Chronic Respiratory Failure (J96.11 / HCC213)
    - Systolic BP >= 180 mmHg    — Hypertensive Crisis (I16.0)
    - Weight loss >= 10 % trend  — Malnutrition/Cachexia (R63.4)
    """
    _tid = svc._tenant_of(current_user)
    _require_patient_access(pid, _tid)

    patient = emr.get_patient(pid)
    if not patient:
        if not svc.patient_is_fhir(pid, _tid):
            raise HTTPException(status_code=404, detail=f"Patient {pid} not found")
        return {"pid": pid, "suspects": [], "count": 0, "note": "Vitals data not yet synced for FHIR patients"}

    try:
        return svc.svc_get_vitals_suspects(pid=pid, year=year, tenant_id=_tid, patient=patient)
    except Exception as exc:
        logger.error("get_vitals_suspects error pid=%s: %s", pid, exc)
        raise HTTPException(status_code=500, detail="Internal server error")


# ---------------------------------------------------------------------------
# Lab & Vitals Suspects
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
    returns results immediately without any LLM call.
    """
    _tid = svc._tenant_of(current_user)
    _require_patient_access(pid, _tid)

    patient = emr.get_patient(pid)
    if not patient:
        if not svc.patient_is_fhir(pid, _tid):
            raise HTTPException(status_code=404, detail=f"Patient {pid} not found")
        return {"pid": pid, "suspects": [], "count": 0, "note": "Lab data not yet synced for FHIR patients"}

    try:
        return svc.svc_get_lab_suspects(pid=pid, year=year, tenant_id=_tid, patient=patient)
    except Exception as exc:
        logger.error("get_lab_suspects error pid=%s: %s", pid, exc)
        raise HTTPException(status_code=500, detail="Internal server error")


# ---------------------------------------------------------------------------
# Comprehensive Profile
# ---------------------------------------------------------------------------


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
    one data source never breaks the response.  Missing data sources return
    empty lists / None and are reflected in the ``data_completeness`` block.
    """
    _tid = svc._tenant_of(current_user)
    _require_patient_access(pid, _tid)

    patient = emr.get_patient(pid)
    if not patient:
        if not svc.patient_is_fhir(pid, _tid):
            raise HTTPException(status_code=404, detail=f"Patient {pid} not found")
        # For FHIR patients, build a minimal patient dict from emr_patient_matches
        fhir_row = svc._get_fhir_patient_row(pid, tenant_id=_tid)
        patient = fhir_row or {"pid": pid}

    result = svc.svc_get_comprehensive_profile(pid=pid, tenant_id=tenant_id, patient=patient)

    log_phi_access(
        action="view",
        resource="profile",
        patient_id=pid,
        details=f"completeness_pct={result['data_completeness']['completeness_pct']}",
    )
    return result


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

    An empty ``family_history`` dict is returned when the table does not
    exist in this OpenEMR deployment or the patient has no record.
    """
    _tid = svc._tenant_of(current_user)
    _require_patient_access(pid, _tid)

    if not _require_emr_patient(pid, _tid):
        return {"pid": pid, "family_history": {}, "note": "Family history not yet synced for FHIR patients"}

    return svc.svc_get_family_history(pid=pid, tenant_id=_tid)


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

    The response combines:
    1. ``sdoh_form`` — the raw row from form_history_sdoh (OpenEMR >= 6.x).
    2. ``billed_z_codes`` — ICD-10 Z-codes already present on the patient's claims.
    3. ``billable_highlights`` — reference map of the six highest-value SDOH Z-codes.
    """
    _tid = svc._tenant_of(current_user)
    _require_patient_access(pid, _tid)

    if not _require_emr_patient(pid, _tid):
        return {"pid": pid, "sdoh_form": {}, "billed_z_codes": [], "billable_highlights": {}, "note": "SDOH data not yet synced for FHIR patients"}

    return svc.svc_get_sdoh(pid=pid, tenant_id=_tid)


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

    Each record includes title (allergen name), diagnosis (reaction code),
    and begdate.  An empty list is returned when no active allergies exist.
    """
    _tid = svc._tenant_of(current_user)
    _require_patient_access(pid, _tid)

    return svc.svc_get_allergies(pid=pid, tenant_id=_tid)


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

    An empty list is returned when the transactions table is absent or no
    referrals exist for the patient.
    """
    _tid = svc._tenant_of(current_user)
    _require_patient_access(pid, _tid)

    if not _require_emr_patient(pid, _tid):
        return {"pid": pid, "count": 0, "referrals": [], "note": "Referral data not yet synced for FHIR patients"}

    return svc.svc_get_referrals(pid=pid, tenant_id=_tid)


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

    Records flagged as added_erroneously in OpenEMR are excluded.
    CVX codes are the CDC standard vaccine identifiers.
    """
    _tid = svc._tenant_of(current_user)
    _require_patient_access(pid, _tid)

    if not _require_emr_patient(pid, _tid):
        return {"pid": pid, "count": 0, "immunizations": [], "note": "Immunization data not yet synced for FHIR patients"}

    try:
        return svc.svc_get_immunizations(pid=pid, tenant_id=_tid)
    except Exception as exc:
        logger.error("get_immunizations error pid=%s: %s", pid, exc)
        raise HTTPException(status_code=500, detail="Internal server error")


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

    Measures currently evaluated:
    - flu_vaccine     — Annual influenza vaccination (all ages)
    - pneumococcal    — Pneumococcal vaccination series (age >= 65)
    - zoster          — Shingles vaccination series (age >= 50)
    """
    _tid = svc._tenant_of(current_user)
    _require_patient_access(pid, _tid)

    if not _require_emr_patient(pid, _tid):
        return {"pid": pid, "measures": {}, "note": "HEDIS data not yet synced for FHIR patients"}

    try:
        return svc.svc_get_hedis_compliance(pid=pid, year=year, tenant_id=_tid)
    except Exception as exc:
        logger.error("get_hedis_compliance error pid=%s year=%s: %s", pid, year, exc)
        raise HTTPException(status_code=500, detail="Internal server error")


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

    This endpoint never returns a 500 — if data is unavailable it falls back
    gracefully to CNA defaults (non_dual, aged, not institutional).
    """
    _tid = svc._tenant_of(current_user)
    _require_patient_access(pid, _tid)

    if not _require_emr_patient(pid, _tid):
        return {"pid": pid, "enrollment": {}, "note": "Enrollment data not yet synced for FHIR patients"}

    return svc.svc_get_patient_enrollment(pid=pid, tenant_id=_tid)
