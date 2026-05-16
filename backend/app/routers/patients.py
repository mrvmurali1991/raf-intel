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
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel

from app.auth import get_current_user, get_tenant_id, require_permission
from app.rate_limit import limiter
from app.schemas.patient import PatientSummary
from app.services import openemr_connector as emr
from app.services import patient_service as svc
from app.services.audit_logger import log_phi_access

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/patients", tags=["patients"])

# Maximum upload size: 10 MB
_MAX_CSV_BYTES = 10 * 1024 * 1024


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------


class PatientListResponse(BaseModel):
    patients: list[PatientSummary]
    total: int
    limit: int
    offset: int


def _to_patient_summary(row: dict[str, Any]) -> PatientSummary:
    """
    Convert a service-layer patient dict into a typed PatientSummary.

    The service emits dicts with keys like ``pid``/``fname``/``lname``/
    ``DOB`` (the casing comes straight from the SELECT aliases that the
    legacy OpenEMR-style frontend expects). We map them onto the typed
    PatientSummary fields here so the API contract stays clean without
    forcing the service or the frontend to migrate in lockstep.
    """
    first = row.get("fname") or row.get("first_name") or ""
    last = row.get("lname") or row.get("last_name") or ""
    name = (f"{first} {last}").strip() or row.get("name") or ""

    raf = row.get("raf_score")
    try:
        raf_val = float(raf) if raf is not None and raf != "" else None
    except (TypeError, ValueError):
        raf_val = None

    emr_pid_raw = row.get("emr_pid") or row.get("pid")
    try:
        emr_pid_val = int(emr_pid_raw) if emr_pid_raw not in (None, "") else None
    except (TypeError, ValueError):
        emr_pid_val = None

    return PatientSummary(
        id=int(row.get("id") or row.get("pid") or 0),
        name=name,
        dob=(row.get("dob") or row.get("DOB") or None) or None,
        emr_pid=emr_pid_val,
        raf_score=raf_val,
        tenant_id=str(row["tenant_id"]) if row.get("tenant_id") is not None else None,
        mrn=row.get("mrn") or None,
    )


class ImportSummaryResponse(BaseModel):
    total_rows: int
    imported: int
    duplicates_skipped: int
    errors: int
    error_details: list[Any] = []


class EncounterListResponse(BaseModel):
    pid: int
    count: int
    encounters: list[dict[str, Any]]


class MedicationListResponse(BaseModel):
    pid: int
    count: int
    medications: list[dict[str, Any]]


class MedicationGapsResponse(BaseModel):
    gaps: list[dict[str, Any]]
    year: int
    gap_count: int


class DiagnosisListResponse(BaseModel):
    pid: int
    count: int
    diagnoses: list[dict[str, Any]]


class ProcedureListResponse(BaseModel):
    pid: int
    count: int
    procedures: list[dict[str, Any]]
    source: str | None = None


class ClinicalNotesResponse(BaseModel):
    pid: int
    encounter_id: int
    count: int
    notes: list[dict[str, Any]]


class ProblemListResponse(BaseModel):
    pid: int
    count: int
    problems: list[dict[str, Any]]


class RecaptureGapsResponse(BaseModel):
    pid: int
    year: int
    gap_count: int
    recapture_gaps: list[dict[str, Any]]
    prior_year: int | None = None
    source: str | None = None
    note: str | None = None


class VitalsSuspectsResponse(BaseModel):
    pid: int
    count: int
    suspects: list[dict[str, Any]]
    note: str | None = None


class LabSuspectsResponse(BaseModel):
    pid: int
    count: int
    suspects: list[dict[str, Any]]
    labs: dict[str, Any] | None = None
    note: str | None = None


class AllergyListResponse(BaseModel):
    pid: int
    count: int
    allergies: list[dict[str, Any]]


class ReferralListResponse(BaseModel):
    pid: int
    count: int
    referrals: list[dict[str, Any]]


class ImmunizationListResponse(BaseModel):
    pid: int
    count: int
    immunizations: list[dict[str, Any]]
    source: str | None = None
    note: str | None = None


class FamilyHistoryResponse(BaseModel):
    pid: int
    family_history: dict[str, Any]
    source: str | None = None
    note: str | None = None


class SdohResponse(BaseModel):
    pid: int
    sdoh_form: dict[str, Any]
    billed_z_codes: list[Any]
    billable_highlights: dict[str, Any]


class HedisResponse(BaseModel):
    pid: int
    year: int
    summary: dict[str, Any]
    measures: dict[str, Any]
    source: str | None = None


class EnrollmentResponse(BaseModel):
    pid: int
    enrollment: dict[str, Any]


class PatientsWithEncountersResponse(BaseModel):
    patients: list[dict[str, Any]]
    total: int


# ---------------------------------------------------------------------------
# Internal guards — reused by many endpoints
# ---------------------------------------------------------------------------

def _require_patient_access(pid: int, tenant_id: str) -> None:
    """Raise 404 when *pid* is not accessible for *tenant_id*."""
    if not svc.patient_is_accessible(pid, tenant_id):
        raise HTTPException(status_code=404, detail=f"Patient {pid} not found")


def _assert_encounter_belongs(encounter_id: int, patient_id: int, tenant_id: str) -> None:
    """Raise 404 when *encounter_id* does not belong to *patient_id* / *tenant_id*.

    Checks both the OpenEMR form_encounter table (for direct-DB patients) and
    the raf_intelligence encounters table (for uploaded/FHIR patients).  If
    neither table has a matching row the encounter is considered inaccessible.

    This prevents IDOR — a caller with a valid patient token for patient A
    cannot probe data belonging to patient B by supplying patient B's
    encounter_id in the URL path.
    """
    from app.db import openemr_cursor, raf_cursor

    # Check raf_intelligence.encounters first (covers FHIR / uploaded patients).
    try:
        with raf_cursor() as cur:
            cur.execute(
                """
                SELECT 1 FROM encounters e
                JOIN patients p ON p.id = e.patient_id
                WHERE e.id = %s AND e.patient_id = %s AND p.tenant_id = %s
                LIMIT 1
                """,
                (encounter_id, patient_id, tenant_id),
            )
            if cur.fetchone():
                return  # found — access is valid
    except Exception as exc:
        logger.debug("_assert_encounter_belongs: raf encounters check failed: %s", exc)

    # Fall back to OpenEMR form_encounter (direct-DB patients).
    # form_encounter.pid maps to openemr patient pid; we need the emr pid.
    emr_pid = svc._get_emr_pid(patient_id, tenant_id=tenant_id) or patient_id
    try:
        with openemr_cursor() as cur:
            cur.execute(
                "SELECT 1 FROM form_encounter WHERE id = %s AND pid = %s LIMIT 1",
                (encounter_id, emr_pid),
            )
            if cur.fetchone():
                return  # found — access is valid
    except Exception as exc:
        logger.debug("_assert_encounter_belongs: openemr check failed: %s", exc)

    raise HTTPException(
        status_code=404,
        detail=f"Encounter {encounter_id} not found for patient {patient_id}",
    )


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


@router.get("", summary="List all patients", response_model=PatientListResponse)
@limiter.limit("60/minute")
def list_patients(
    request: Request,
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    search: str = Query("", description="Search by name or PID"),
    year: int | None = Query(
        default=None,
        description="Measurement year for RAF score enrichment (defaults to current year)",
    ),
    current_user: dict = Depends(get_current_user),
    _perm: None = Depends(require_permission("patients", "read")),
) -> PatientListResponse:
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
        user=str(current_user.get("id") or current_user.get("sub") or "system"),
        details=f"limit={limit} offset={offset} search={search!r} returned={len(result['patients'])}",
    )
    summaries = [_to_patient_summary(row) for row in result["patients"]]
    return PatientListResponse(
        patients=summaries,
        total=result["total"],
        limit=result["limit"],
        offset=result["offset"],
    )


# ---------------------------------------------------------------------------
# Patients with encounters (for pipeline demo)
# ---------------------------------------------------------------------------


@router.get("/with-encounters", summary="Patients that have encounter data", response_model=PatientsWithEncountersResponse)
def patients_with_encounters(
    limit: int = Query(200, ge=1, le=500),
    current_user: dict = Depends(get_current_user),
    _perm: None = Depends(require_permission("patients", "read")),
    tenant_id: str = Depends(get_tenant_id),
) -> PatientsWithEncountersResponse:
    """Return only patients that have at least one encounter."""
    try:
        result = svc.svc_patients_with_encounters(limit=limit, tenant_id=tenant_id)
        return PatientsWithEncountersResponse(**result)
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


@router.post("/import", summary="Bulk import patients from a CSV or Excel file", response_model=ImportSummaryResponse)
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
) -> ImportSummaryResponse:
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
    )
    from app.services.patient_import_service import (
        parse_patient_csv as _parse_csv,
    )
    from app.services.patient_import_service import (
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
        user=str(current_user.get("id") or current_user.get("sub") or "system"),
        details=(
            f"filename={file.filename!r} on_duplicate={on_duplicate} total_rows={summary['total_rows']} "
            f"imported={summary['imported']} duplicates={summary['duplicates_skipped']} "
            f"errors={summary['errors']}"
        ),
    )

    return ImportSummaryResponse(**summary)


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


@router.post("/import/fhir", summary="Bulk import patients from a FHIR JSON file", response_model=ImportSummaryResponse)
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
) -> ImportSummaryResponse:
    """
    Parse *file* as a FHIR R4 Patient Bundle, validate each entry, deduplicate
    against existing OpenEMR patients, and insert new patients.

    The file must be a valid FHIR R4 Bundle of type 'collection' or
    'transaction' containing Patient resources.

    Download the template via GET /api/patients/import/template/fhir.
    """
    from app.services.patient_import_service import (
        import_patients as _import,
    )
    from app.services.patient_import_service import (
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
        user=str(current_user.get("id") or current_user.get("sub") or "system"),
        details=(
            f"filename={file.filename!r} on_duplicate={on_duplicate} total_rows={summary['total_rows']} "
            f"imported={summary['imported']} duplicates={summary['duplicates_skipped']} "
            f"errors={summary['errors']}"
        ),
    )

    return ImportSummaryResponse(**summary)


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

    log_phi_access(action="view", resource="patient", patient_id=pid,
                   user=str(current_user.get("id") or current_user.get("sub") or "system"))
    return patient


# ---------------------------------------------------------------------------
# Clinical Notes
# ---------------------------------------------------------------------------


@router.get(
    "/{pid}/clinical-notes/{encounter_id}",
    summary="Get clinical notes for encounter",
    response_model=ClinicalNotesResponse,
)
def get_clinical_notes_for_encounter(
    pid: int,
    encounter_id: int,
    current_user: dict = Depends(get_current_user),
    _perm: None = Depends(require_permission("patients", "read")),
) -> ClinicalNotesResponse:
    """Return clinical notes text for a specific encounter."""
    _tid = svc._tenant_of(current_user)
    _require_patient_access(pid, _tid)
    _assert_encounter_belongs(encounter_id, pid, _tid)

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
    return ClinicalNotesResponse(
        pid=pid,
        encounter_id=encounter_id,
        count=len(notes),
        notes=notes,
    )


# ---------------------------------------------------------------------------
# Encounters
# ---------------------------------------------------------------------------


@router.get("/{pid}/encounters", summary="Get patient encounters", response_model=EncounterListResponse)
def get_encounters(
    pid: int,
    year: int | None = Query(
        default=None, description="Filter encounters by year (e.g. 2024)"
    ),
    current_user: dict = Depends(get_current_user),
    _perm: None = Depends(require_permission("patients", "read")),
) -> EncounterListResponse:
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
    return EncounterListResponse(**result)


# ---------------------------------------------------------------------------
# Medications
# ---------------------------------------------------------------------------


@router.get("/{pid}/medications", summary="Get patient medications", response_model=MedicationListResponse)
def get_medications(
    pid: int,
    year: int | None = Query(
        default=None,
        description=(
            "Filter to medications active during this calendar year. "
            "A prescription is included when YEAR(start_date) <= year AND active = 1. "
            "Omit to return all prescriptions regardless of year or active status."
        ),
    ),
    current_user: dict = Depends(get_current_user),
    _perm: None = Depends(require_permission("patients", "read")),
) -> MedicationListResponse:
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

    return MedicationListResponse(**svc.svc_get_medications(pid=pid, year=year, tenant_id=_tid))


# ---------------------------------------------------------------------------
# Medication-diagnosis gaps
# ---------------------------------------------------------------------------


@router.get(
    "/{pid}/medication-gaps",
    summary="Medication-linked diagnoses not billed this year",
    response_model=MedicationGapsResponse,
)
def get_medication_gaps(
    pid: int,
    year: int = Query(
        0, ge=0, description="Calendar year to check (defaults to current year)"
    ),
    current_user: dict = Depends(get_current_user),
    _perm: None = Depends(require_permission("patients", "read")),
) -> MedicationGapsResponse:
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
        return MedicationGapsResponse(**svc.svc_get_medication_gaps(pid=pid, year=year, tenant_id=_tid))
    except Exception as exc:
        logger.error("get_medication_gaps error pid=%s year=%s: %s", pid, year, exc)
        raise HTTPException(status_code=500, detail="Internal server error")


# ---------------------------------------------------------------------------
# Diagnoses (billing ICD-10 codes)
# ---------------------------------------------------------------------------


@router.get("/{pid}/diagnoses", summary="Get patient billing ICD-10 codes", response_model=DiagnosisListResponse)
def get_diagnoses(
    pid: int,
    current_user: dict = Depends(get_current_user),
    _perm: None = Depends(require_permission("patients", "read")),
) -> DiagnosisListResponse:
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
    return DiagnosisListResponse(**result)


# ---------------------------------------------------------------------------
# Procedures (CPT codes with condition hints)
# ---------------------------------------------------------------------------


@router.get(
    "/{pid}/procedures",
    summary="Get patient CPT procedure codes with condition hints",
    response_model=ProcedureListResponse,
)
def get_procedures(
    pid: int,
    current_user: dict = Depends(get_current_user),
    _perm: None = Depends(require_permission("patients", "read")),
) -> ProcedureListResponse:
    """
    Return all active CPT4 procedure codes for *pid* from the billing table.

    Each row is enriched with a ``condition_hint`` block when the CPT code
    appears in CPT_CONDITION_HINTS.  Codes without a hint entry are returned
    as-is with ``condition_hint: null``.
    """
    _tid = svc._tenant_of(current_user)
    _require_patient_access(pid, _tid)

    if not _require_emr_patient(pid, _tid):
        # FHIR fallback: return encounter-based procedure info from fhir_encounters
        try:
            from app.db import raf_cursor
            fhir_ext_id = svc._get_fhir_resource_id(pid, _tid)
            if fhir_ext_id:
                with raf_cursor() as _pc:
                    _pc.execute(
                        """SELECT encounter_type, encounter_date, reason_display,
                                  provider_display
                           FROM fhir_encounters
                           WHERE fhir_patient_id = %s
                           ORDER BY encounter_date DESC""",
                        (fhir_ext_id,),
                    )
                    rows = _pc.fetchall()
                    if rows:
                        procs = [
                            {
                                "code": "",
                                "code_type": "encounter",
                                "description": r.get("reason_display") or r.get("encounter_type") or "Office Visit",
                                "date": str(r["encounter_date"]) if r.get("encounter_date") else None,
                                "provider": r.get("provider_display"),
                                "condition_hint": None,
                                "source": "fhir",
                            }
                            for r in rows
                        ]
                        return ProcedureListResponse(pid=pid, count=len(procs), procedures=procs, source="fhir")
        except Exception as exc:
            logger.debug("procedures FHIR fallback failed pid=%s: %s", pid, exc)
        return ProcedureListResponse(pid=pid, count=0, procedures=[])

    try:
        return ProcedureListResponse(**svc.svc_get_procedures(pid=pid, tenant_id=_tid))
    except Exception as exc:
        logger.error("get_procedures error pid=%s: %s", pid, exc)
        raise HTTPException(status_code=500, detail="Internal server error")


# ---------------------------------------------------------------------------
# Problem List
# ---------------------------------------------------------------------------


@router.get("/{pid}/problem-list", summary="Get patient active problem list", response_model=ProblemListResponse)
def get_problem_list(
    pid: int,
    year: int | None = Query(
        default=None, description="Filter problems by begdate year, e.g. 2024"
    ),
    current_user: dict = Depends(get_current_user),
    _perm: None = Depends(require_permission("patients", "read")),
) -> ProblemListResponse:
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

    return ProblemListResponse(**svc.svc_get_problem_list(pid=pid, year=year, tenant_id=_tid))


# ---------------------------------------------------------------------------
# Recapture Gaps
# ---------------------------------------------------------------------------


@router.get(
    "/{pid}/recapture-gaps",
    summary="Active problems not billed this year",
    response_model=RecaptureGapsResponse,
    response_model_exclude_none=True,
)
def get_recapture_gaps(
    pid: int,
    year: int | None = Query(
        default=None,
        ge=2000,
        le=2100,
        description="Calendar year to check billing against. Defaults to current year.",
    ),
    current_user: dict = Depends(get_current_user),
    _perm: None = Depends(require_permission("patients", "read")),
) -> RecaptureGapsResponse:
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
        # FHIR fallback: CMS recapture logic — HCCs captured in PRIOR year not yet billed THIS year
        from datetime import date as _date
        from datetime import datetime as _datetime
        _year = year or _date.today().year
        _prior_year = _year - 1
        try:
            import json as _json

            from app.db import raf_cursor
            with raf_cursor() as _gc:
                # Check if patient is deceased — no recapture needed
                _gc.execute("SELECT deceased_date FROM patients WHERE id = %s LIMIT 1", (pid,))
                p_row = _gc.fetchone()
                if p_row and p_row.get("deceased_date"):
                    return RecaptureGapsResponse(pid=pid, year=_year, gap_count=0, recapture_gaps=[], note="deceased")

                # Step 1: get HCCs captured in the prior measurement year
                # updated_at is used to compute days since last documentation per CMS 365-day rule
                _gc.execute(
                    """SELECT hcc_code, icd10_codes, description,
                              COALESCE(updated_at, created_at) AS last_documented_at
                       FROM raf_patient_hcc
                       WHERE patient_id = %s AND measurement_year = %s""",
                    (pid, _prior_year),
                )
                prior_rows = _gc.fetchall()

                # Only chronic HCCs need annual recapture per CMS rules
                from hccinfhir.defaults import is_chronic_default
                chronic_prior = [
                    r for r in prior_rows
                    if is_chronic_default.get((str(r.get("hcc_code", "")), "CMS-HCC Model V28"), True)
                ]

                # Step 2: get HCC codes already captured in the current year
                _gc.execute(
                    """SELECT hcc_code
                       FROM raf_patient_hcc
                       WHERE patient_id = %s AND measurement_year = %s""",
                    (pid, _year),
                )
                current_hcc_codes = {r["hcc_code"] for r in _gc.fetchall()}

                # Step 3: gap = chronic prior-year HCCs not present in current year
                # For each gap, compute days since last documentation per CMS 365-day recapture rule.
                _today = _date.today()
                gaps = []
                for row in chronic_prior:
                    hcc = row.get("hcc_code")
                    if hcc and hcc not in current_hcc_codes:
                        try:
                            icd10_codes = _json.loads(row.get("icd10_codes") or "[]")
                        except (ValueError, TypeError):
                            icd10_codes = []

                        # Resolve last_documented from updated_at / created_at
                        raw_ts = row.get("last_documented_at")
                        if raw_ts is None:
                            last_doc_date = None
                            days_since = None
                        elif isinstance(raw_ts, _datetime):
                            last_doc_date = raw_ts.date()
                            days_since = (_today - last_doc_date).days
                        elif isinstance(raw_ts, _date):
                            last_doc_date = raw_ts
                            days_since = (_today - last_doc_date).days
                        else:
                            # String fallback — strip time component if present
                            try:
                                last_doc_date = _date.fromisoformat(str(raw_ts)[:10])
                                days_since = (_today - last_doc_date).days
                            except (ValueError, TypeError):
                                last_doc_date = None
                                days_since = None

                        gaps.append({
                            "hcc_code": hcc,
                            "icd10_codes": icd10_codes,
                            "description": row.get("description") or "",
                            "last_documented": last_doc_date.isoformat() if last_doc_date else None,
                            "days_since_documented": days_since,
                            # CMS requires recapture within 365 days of last documentation
                            "overdue": (days_since > 365) if days_since is not None else None,
                            "source": "fhir",
                        })

                # Sort most-overdue first so callers can surface the highest-risk gaps immediately
                gaps.sort(key=lambda g: g["days_since_documented"] if g["days_since_documented"] is not None else -1, reverse=True)

                return RecaptureGapsResponse(pid=pid, year=_year, prior_year=_prior_year, gap_count=len(gaps), recapture_gaps=gaps, source="fhir")
        except Exception as exc:
            logger.debug("recapture-gaps FHIR fallback failed pid=%s: %s", pid, exc)
        return RecaptureGapsResponse(pid=pid, recapture_gaps=[], year=_year, gap_count=0)

    try:
        return RecaptureGapsResponse(**svc.svc_get_recapture_gaps(pid=pid, year=year, tenant_id=_tid))
    except Exception as exc:
        logger.error("get_recapture_gaps error pid=%s year=%s: %s", pid, year, exc)
        raise HTTPException(status_code=500, detail="Internal server error")


# ---------------------------------------------------------------------------
# Vitals Suspects
# ---------------------------------------------------------------------------


@router.get(
    "/{pid}/vitals-suspects",
    summary="Vitals-based suspect conditions",
    response_model=VitalsSuspectsResponse,
    response_model_exclude_none=True,
)
def get_vitals_suspects(
    pid: int,
    year: int | None = Query(
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
) -> VitalsSuspectsResponse:
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
        return VitalsSuspectsResponse(pid=pid, suspects=[], count=0, note="Vitals data not yet synced for FHIR patients")

    try:
        return VitalsSuspectsResponse(**svc.svc_get_vitals_suspects(pid=pid, year=year, tenant_id=_tid, patient=patient))
    except Exception as exc:
        logger.error("get_vitals_suspects error pid=%s: %s", pid, exc)
        raise HTTPException(status_code=500, detail="Internal server error")


# ---------------------------------------------------------------------------
# Lab & Vitals Suspects
# ---------------------------------------------------------------------------


@router.get(
    "/{pid}/lab-suspects",
    summary="Rule-based lab/vitals suspect conditions",
    response_model=LabSuspectsResponse,
    response_model_exclude_none=True,
)
def get_lab_suspects(
    pid: int,
    year: int | None = Query(
        default=None,
        description="Filter notes and vitals by calendar year (e.g. 2025). Omit to include all available records.",
    ),
    current_user: dict = Depends(get_current_user),
    _perm: None = Depends(require_permission("patients", "read")),
) -> LabSuspectsResponse:
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
        # FHIR fallback: return lab results from fhir_observations
        try:
            from app.db import raf_cursor
            from app.services.patient_service import _get_fhir_resource_id
            fhir_id = _get_fhir_resource_id(pid, _tid)
            if fhir_id:
                with raf_cursor() as cur:
                    cur.execute(
                        """SELECT code_display, value_numeric, value_string, unit, effective_date
                           FROM fhir_observations
                           WHERE fhir_patient_id = %s AND category = 'laboratory'
                           ORDER BY effective_date DESC""",
                        (fhir_id,),
                    )
                    rows = cur.fetchall()
                    if rows:
                        lab_results = [
                            {
                                "result_text": f"{r.get('code_display', '')}: {r.get('value_numeric') or r.get('value_string', '')} {r.get('unit', '')}".strip(),
                                "date": str(r["effective_date"]) if r.get("effective_date") else None,
                            }
                            for r in rows
                        ]
                        return LabSuspectsResponse(pid=pid, suspects=[], count=0, labs={"results": lab_results, "source": "fhir"})
        except Exception:
            pass
        return LabSuspectsResponse(pid=pid, suspects=[], count=0, note="Lab data not yet synced for FHIR patients")

    try:
        return LabSuspectsResponse(**svc.svc_get_lab_suspects(pid=pid, year=year, tenant_id=_tid, patient=patient))
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


@router.get("/{pid}/family-history", summary="Get patient family history", response_model=FamilyHistoryResponse, response_model_exclude_none=True)
def get_family_history(
    pid: int,
    current_user: dict = Depends(get_current_user),
    _perm: None = Depends(require_permission("patients", "read")),
) -> FamilyHistoryResponse:
    """
    Return the most recent family-history record for *pid* from
    OpenEMR's history_data table.

    An empty ``family_history`` dict is returned when the table does not
    exist in this OpenEMR deployment or the patient has no record.
    """
    _tid = svc._tenant_of(current_user)
    _require_patient_access(pid, _tid)

    if not _require_emr_patient(pid, _tid):
        # FHIR fallback: query patient_family_history table
        try:
            from app.db import raf_cursor
            with raf_cursor() as cur:
                cur.execute(
                    "SELECT relation, condition_name, onset_age, notes, status "
                    "FROM patient_family_history WHERE patient_id = %s ORDER BY id",
                    (pid,),
                )
                rows = cur.fetchall()
                if rows:
                    fh: dict = {}
                    for r in rows:
                        rel = r.get("relation", "unknown").lower().replace(" ", "_")
                        fh[f"history_{rel}"] = r.get("condition_name", "")
                    return FamilyHistoryResponse(pid=pid, family_history=fh, source="raf_db")
        except Exception:
            pass
        return FamilyHistoryResponse(pid=pid, family_history={}, note="Family history not yet synced for FHIR patients")

    return FamilyHistoryResponse(**svc.svc_get_family_history(pid=pid, tenant_id=_tid))


# ---------------------------------------------------------------------------
# SDOH
# ---------------------------------------------------------------------------


@router.get("/{pid}/sdoh", summary="Get Social Determinants of Health data", response_model=SdohResponse)
def get_sdoh(
    pid: int,
    current_user: dict = Depends(get_current_user),
    _perm: None = Depends(require_permission("patients", "read")),
) -> SdohResponse:
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
        return SdohResponse(pid=pid, sdoh_form={}, billed_z_codes=[], billable_highlights={})

    return SdohResponse(**svc.svc_get_sdoh(pid=pid, tenant_id=_tid))


# ---------------------------------------------------------------------------
# Allergies
# ---------------------------------------------------------------------------


@router.get("/{pid}/allergies", summary="Get patient active allergies", response_model=AllergyListResponse)
def get_allergies(
    pid: int,
    current_user: dict = Depends(get_current_user),
    _perm: None = Depends(require_permission("patients", "read")),
) -> AllergyListResponse:
    """
    Return all active allergy records for *pid* from OpenEMR's lists table.

    Each record includes title (allergen name), diagnosis (reaction code),
    and begdate.  An empty list is returned when no active allergies exist.
    """
    _tid = svc._tenant_of(current_user)
    _require_patient_access(pid, _tid)

    return AllergyListResponse(**svc.svc_get_allergies(pid=pid, tenant_id=_tid))


# ---------------------------------------------------------------------------
# Referrals
# ---------------------------------------------------------------------------


@router.get("/{pid}/referrals", summary="Get patient referral transactions", response_model=ReferralListResponse)
def get_referrals(
    pid: int,
    current_user: dict = Depends(get_current_user),
    _perm: None = Depends(require_permission("patients", "read")),
) -> ReferralListResponse:
    """
    Return all referral transactions for *pid* from OpenEMR's transactions
    table (rows with title='Referral'), ordered newest first.

    An empty list is returned when the transactions table is absent or no
    referrals exist for the patient.
    """
    _tid = svc._tenant_of(current_user)
    _require_patient_access(pid, _tid)

    if not _require_emr_patient(pid, _tid):
        return ReferralListResponse(pid=pid, count=0, referrals=[])

    return ReferralListResponse(**svc.svc_get_referrals(pid=pid, tenant_id=_tid))


# ---------------------------------------------------------------------------
# Immunizations
# ---------------------------------------------------------------------------


@router.get("/{pid}/immunizations", summary="Get patient immunization history", response_model=ImmunizationListResponse, response_model_exclude_none=True)
def get_immunizations(
    pid: int,
    current_user: dict = Depends(get_current_user),
    _perm: None = Depends(require_permission("patients", "read")),
) -> ImmunizationListResponse:
    """
    Return the complete immunization history for *pid* from the OpenEMR
    immunizations table.

    Records flagged as added_erroneously in OpenEMR are excluded.
    CVX codes are the CDC standard vaccine identifiers.
    """
    _tid = svc._tenant_of(current_user)
    _require_patient_access(pid, _tid)

    if not _require_emr_patient(pid, _tid):
        # FHIR fallback: query patient_immunizations table
        try:
            from app.db import raf_cursor
            with raf_cursor() as cur:
                cur.execute(
                    "SELECT vaccine_name, administered_date, lot_number, site, status "
                    "FROM patient_immunizations WHERE patient_id = %s ORDER BY administered_date DESC",
                    (pid,),
                )
                rows = cur.fetchall()
                if rows:
                    imms = [
                        {
                            "title": r.get("vaccine_name", ""),
                            "vaccine": r.get("vaccine_name", ""),
                            "administered_date": str(r["administered_date"]) if r.get("administered_date") else None,
                            "status": r.get("status", "completed"),
                        }
                        for r in rows
                    ]
                    return ImmunizationListResponse(pid=pid, count=len(imms), immunizations=imms, source="raf_db")
        except Exception:
            pass
        return ImmunizationListResponse(pid=pid, count=0, immunizations=[], note="Immunization data not yet synced for FHIR patients")

    try:
        return ImmunizationListResponse(**svc.svc_get_immunizations(pid=pid, tenant_id=_tid))
    except Exception as exc:
        logger.error("get_immunizations error pid=%s: %s", pid, exc)
        raise HTTPException(status_code=500, detail="Internal server error")


# ---------------------------------------------------------------------------
# HEDIS / Stars quality measures
# ---------------------------------------------------------------------------


@router.get(
    "/{pid}/hedis",
    summary="HEDIS/Stars quality measure compliance",
    response_model=HedisResponse,
    response_model_exclude_none=True,
)
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
) -> HedisResponse:
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
        # FHIR fallback: check patient_immunizations for vaccine compliance
        from datetime import date as _hdate
        _hyear = year or _hdate.today().year
        try:
            from app.db import raf_cursor
            with raf_cursor() as _hc:
                _hc.execute(
                    "SELECT vaccine_name, administered_date FROM patient_immunizations WHERE patient_id = %s",
                    (pid,),
                )
                imm_rows = _hc.fetchall()

                # Also get DOB for age-based measures
                _hc.execute("SELECT dob FROM patients WHERE id = %s LIMIT 1", (pid,))
                p = _hc.fetchone()
                age = None
                if p and p.get("dob"):
                    try:
                        from datetime import date as _d2
                        dob = p["dob"] if isinstance(p["dob"], _d2) else _d2.fromisoformat(str(p["dob"])[:10])
                        today = _d2.today()
                        age = today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))
                    except Exception:
                        pass

                vaccines_lower = [(r.get("vaccine_name", "").lower(), r.get("administered_date")) for r in imm_rows]

                measures = {}
                # Flu vaccine — all ages
                flu_given = any(
                    ("influenza" in v or "flu" in v) and d and (
                        (hasattr(d, 'year') and d.year >= _hyear - 1) or
                        (isinstance(d, str) and len(d) >= 4 and int(d[:4]) >= _hyear - 1)
                    )
                    for v, d in vaccines_lower
                )
                measures["flu_vaccine"] = {"due": True, "compliant": flu_given, "description": "Annual influenza vaccination"}
                # Pneumococcal — age >= 65
                if age and age >= 65:
                    pneu_given = any("pneumo" in v for v, _ in vaccines_lower)
                    measures["pneumococcal"] = {"due": True, "compliant": pneu_given, "description": "Pneumococcal vaccination series"}
                # Zoster — age >= 50
                if age and age >= 50:
                    zoster_given = any("zoster" in v or "shingles" in v for v, _ in vaccines_lower)
                    measures["zoster"] = {"due": True, "compliant": zoster_given, "description": "Shingles vaccination series"}

                due_count = sum(1 for m in measures.values() if m.get("due"))
                compliant_count = sum(1 for m in measures.values() if m.get("due") and m.get("compliant"))
                return HedisResponse(
                    pid=pid, year=_hyear,
                    summary={"measures_due": due_count, "measures_compliant": compliant_count,
                             "compliance_rate": round(compliant_count / due_count, 2) if due_count else None},
                    measures=measures, source="fhir",
                )
        except Exception as exc:
            logger.debug("HEDIS FHIR fallback failed pid=%s: %s", pid, exc)
        return HedisResponse(pid=pid, year=_hyear, summary={"measures_due": 0, "measures_compliant": 0, "compliance_rate": None}, measures={})

    try:
        return HedisResponse(**svc.svc_get_hedis_compliance(pid=pid, year=year, tenant_id=_tid))
    except Exception as exc:
        logger.error("get_hedis_compliance error pid=%s year=%s: %s", pid, year, exc)
        raise HTTPException(status_code=500, detail="Internal server error")


# ---------------------------------------------------------------------------
# Enrollment / Insurance Info
# ---------------------------------------------------------------------------


@router.get(
    "/{pid}/enrollment",
    summary="Get patient enrollment and insurance/dual status",
    response_model=EnrollmentResponse,
)
def get_patient_enrollment(
    pid: int,
    current_user: dict = Depends(get_current_user),
    _perm: None = Depends(require_permission("patients", "read")),
) -> EnrollmentResponse:
    """
    Return enrollment and insurance metadata for *pid* derived from OpenEMR
    insurance_data, insurance_companies, and form_encounter tables.

    This endpoint never returns a 500 — if data is unavailable it falls back
    gracefully to CNA defaults (non_dual, aged, not institutional).
    """
    _tid = svc._tenant_of(current_user)
    _require_patient_access(pid, _tid)

    if not _require_emr_patient(pid, _tid):
        # Estimate OREC from DOB for FHIR-only patients (no CMS enrollment data available)
        from datetime import date as _date

        from app.db import raf_cursor
        orec = "aged"  # safe fallback if DOB lookup fails
        try:
            with raf_cursor() as cur:
                cur.execute("SELECT dob FROM patients WHERE id = %s LIMIT 1", (pid,))
                row = cur.fetchone()
            if row and row[0]:
                dob = row[0]
                if isinstance(dob, str):
                    dob = _date.fromisoformat(dob)
                today = _date.today()
                age = today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))
                orec = "aged" if age >= 65 else "disabled"
        except Exception as _exc:
            logger.debug("enrollment: DOB lookup failed for pid=%s: %s", pid, _exc)
        return EnrollmentResponse(pid=pid, enrollment={
            "dual_status": "non_dual",
            "orec": orec,
            "institutional": False,
            "source": "estimated",
            "enrollment_unverified": True,
        })

    return EnrollmentResponse(**svc.svc_get_patient_enrollment(pid=pid, tenant_id=_tid))
