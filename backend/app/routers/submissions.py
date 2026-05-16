"""
CMS RAPS / EDPS Submission Router.

Provides the full CMS risk-adjustment data submission lifecycle for MA plans:

  POST   /api/submissions/generate                    - Generate RAPS or EDPS file
  GET    /api/submissions/batches                     - List submission batches
  GET    /api/submissions/batches/{id}                - Batch detail
  GET    /api/submissions/batches/{id}/records        - Records in a batch
  POST   /api/submissions/batches/{id}/validate       - Run validation rules
  GET    /api/submissions/batches/{id}/validation-report - Validation summary
  POST   /api/submissions/batches/{id}/submit         - Mark as submitted + download
  GET    /api/submissions/batches/{id}/download       - Download submission file
  POST   /api/submissions/batches/{id}/upload-response - Upload MAO-002/004 reply
  GET    /api/submissions/batches/{id}/responses      - List response files
  GET    /api/submissions/batches/{id}/reconciliation - Payment reconciliation data
  GET    /api/submissions/schedule                    - CMS submission deadlines
  POST   /api/submissions/schedule                    - Add / update custom deadline
  GET    /api/submissions/stats                       - Overall submission statistics
  GET    /api/submissions/batches/{id}/errors         - Error records for correction

All endpoints require JWT authentication via `get_current_user` and enforce
resource-level permissions via `require_permission`.
"""
# Removed: from __future__ import annotations (breaks FastAPI schema generation)

import logging
import os
from pathlib import Path
from typing import Any, Literal

from fastapi import (
    APIRouter,
    Depends,
    File,
    HTTPException,
    Query,
    Request,
    Response,
    UploadFile,
    status,
)
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, field_validator

from app.auth import get_current_user, get_tenant_id, require_permission
from app.middleware.idempotency import idempotency_key_dependency, store_idempotent_response
from app.rate_limit import limiter
from app.services import submission_service as svc

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/submissions", tags=["submissions"])


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------


class GenerateRequest(BaseModel):
    """
    Request body for generating a RAPS or EDPS submission file.

    Fields:
        file_type:    'RAPS' or 'EDPS'
        payment_year: CMS payment year (e.g. 2025)
        sweep_type:   'Initial', 'Midyear', or 'Final'
        plan_id:      CMS H-number for the plan (used in RAPS header / EDPS ISA)
        sender_id:    EDI sender ID (EDPS only; ignored for RAPS)
        receiver_id:  EDI receiver ID (EDPS only; ignored for RAPS)
    """
    file_type:   Literal["RAPS", "EDPS"] = Field(..., description="Submission file format")
    payment_year: int = Field(..., ge=2020, le=2030, description="CMS payment year")
    sweep_type:  Literal["Initial", "Midyear", "Final"] = Field(
        default="Initial",
        description="CMS sweep type",
    )
    plan_id:     str = Field(default="H9999", description="CMS H-number for the plan")
    sender_id:   str = Field(default="MASENDER",  description="EDI sender ID (EDPS only)")
    receiver_id: str = Field(default="CMSEDPS00", description="EDI receiver ID (EDPS only)")

    @field_validator("plan_id")
    @classmethod
    def validate_plan_id(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("plan_id must not be empty")
        return v


class ScheduleUpsertRequest(BaseModel):
    """Request body for adding or updating a custom CMS deadline."""
    payment_year:  int  = Field(..., ge=2020, le=2030)
    sweep_type:    str  = Field(..., min_length=1, max_length=20)
    deadline_date: str  = Field(..., description="ISO date YYYY-MM-DD")
    description:   str  = Field(default="")

    @field_validator("deadline_date")
    @classmethod
    def validate_date(cls, v: str) -> str:
        import re
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", v):
            raise ValueError("deadline_date must be YYYY-MM-DD")
        return v


def _require_batch(batch_id: str, tenant_id: str) -> dict[str, Any]:
    """Load a batch and enforce tenant ownership; raise 404 if missing."""
    try:
        batch = svc.get_batch(batch_id)
    except RuntimeError as exc:
        logger.error("Unexpected error: %s", exc)
        raise HTTPException(status_code=500, detail="Internal server error")
    if not batch:
        raise HTTPException(status_code=404, detail=f"Batch {batch_id} not found")
    if str(batch.get("tenant_id", "")) != str(tenant_id):
        raise HTTPException(status_code=404, detail=f"Batch {batch_id} not found")
    return batch


# ---------------------------------------------------------------------------
# POST /generate
# ---------------------------------------------------------------------------


@router.post(
    "/generate",
    status_code=status.HTTP_201_CREATED,
    summary="Generate a RAPS or EDPS CMS submission file",
)
@limiter.limit("10/minute")
def generate_submission(
    request: Request,
    response: Response,
    body: GenerateRequest,
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
    _perm: None = Depends(require_permission("submissions", "write")),
    _idem: None = Depends(idempotency_key_dependency()),
) -> dict[str, Any]:
    """
    Generate a CMS RAPS (fixed-width) or EDPS (837P EDI) submission file from
    the current confirmed RAF / HCC data for the authenticated tenant.

    Supports Idempotency-Key header (24h replay window).

    - Queries all confirmed HCC records for `payment_year`.
    - Builds one submission record per (patient, ICD-10 code).
    - Writes the formatted file to the configured output directory.
    - Creates a `submission_batches` row and `submission_records` rows.
    - Returns batch metadata including `batch_id` and `file_path`.

    Run POST /api/submissions/batches/{id}/validate before submitting.
    """
    from fastapi.responses import JSONResponse
    try:
        if body.file_type == "RAPS":
            result = svc.generate_raps_file(
                tenant_id=tenant_id,
                payment_year=body.payment_year,
                sweep_type=body.sweep_type,
                plan_id=body.plan_id,
            )
        else:
            result = svc.generate_edps_file(
                tenant_id=tenant_id,
                payment_year=body.payment_year,
                sweep_type=body.sweep_type,
                sender_id=body.sender_id,
                receiver_id=body.receiver_id,
                plan_id=body.plan_id,
            )
    except RuntimeError as exc:
        logger.error("generate_submission error: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")

    if result.get("duplicate"):
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={
                **{k: (str(v) if not isinstance(v, (str, int, float, bool, type(None))) else v) for k, v in result.items()},
                "message": "Submission already exists for this data set",
            },
        )

    store_idempotent_response(request, response, result)
    return result


# ---------------------------------------------------------------------------
# GET /batches
# ---------------------------------------------------------------------------


@router.get("/batches", summary="List CMS submission batches")
def list_batches(
    payment_year: int | None = Query(default=None, description="Filter by payment year"),
    file_type:    str | None = Query(default=None, description="RAPS or EDPS"),
    batch_status: str | None = Query(default=None, alias="status", description="pending|validated|submitted|accepted|rejected|partial"),
    limit:  int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0,  ge=0),
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
    _perm: None = Depends(require_permission("submissions", "read")),
) -> dict[str, Any]:
    """
    Return a paginated list of all submission batches for the authenticated tenant.

    Optional filters: `payment_year`, `file_type` (RAPS/EDPS), `status`.
    """
    try:
        return svc.list_batches(
            tenant_id=tenant_id,
            payment_year=payment_year,
            file_type=file_type,
            status=batch_status,
            limit=limit,
            offset=offset,
        )
    except RuntimeError as exc:
        logger.error("Unexpected error: %s", exc)
        raise HTTPException(status_code=500, detail="Internal server error")


# ---------------------------------------------------------------------------
# GET /batches/{id}
# ---------------------------------------------------------------------------


@router.get("/batches/{batch_id}", summary="Get submission batch detail")
def get_batch(
    batch_id: str,
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
    _perm: None = Depends(require_permission("submissions", "read")),
) -> dict[str, Any]:
    """
    Return full detail for a single submission batch including record counts,
    validation summary, file hash, and current status.
    """
    return _require_batch(batch_id, tenant_id)


# ---------------------------------------------------------------------------
# GET /batches/{id}/records
# ---------------------------------------------------------------------------


@router.get("/batches/{batch_id}/records", summary="List records in a submission batch")
def list_records(
    batch_id: str,
    validation_status: str | None = Query(default=None, description="pending|valid|invalid|warning"),
    cms_status:        str | None = Query(default=None, description="accepted|rejected|duplicate"),
    limit:  int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0,   ge=0),
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
    _perm: None = Depends(require_permission("submissions", "read")),
) -> dict[str, Any]:
    """
    Return a paginated list of submission records for the given batch.

    Use `validation_status` to filter to valid/invalid/warning records.
    Use `cms_status` to filter by CMS response status after MAO-002 parsing.
    """
    _require_batch(batch_id, tenant_id)
    try:
        return svc.list_records(
            batch_id=batch_id,
            validation_status=validation_status,
            cms_status=cms_status,
            limit=limit,
            offset=offset,
        )
    except RuntimeError as exc:
        logger.error("Unexpected error: %s", exc)
        raise HTTPException(status_code=500, detail="Internal server error")


# ---------------------------------------------------------------------------
# POST /batches/{id}/validate
# ---------------------------------------------------------------------------


@router.post("/batches/{batch_id}/validate", summary="Run validation rules on a batch")
@limiter.limit("10/minute")
def validate_batch(
    request: Request,
    batch_id: str,
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
    _perm: None = Depends(require_permission("submissions", "write")),
) -> dict[str, Any]:
    """
    Execute all pre-submission validation rules against every record in the batch.

    Checks performed:
    - ICD-10-CM code format and reference validity
    - Service date range (dos_from <= dos_through, not future, within payment year)
    - NPI format (10-digit numeric)
    - HICN/MBI presence
    - Duplicate (patient + ICD-10 + DOS) detection within the batch

    Updates each record's `validation_status` and `validation_errors`.
    Updates batch `valid_count`, `invalid_count`, `warning_count`, and status.

    Returns a full validation report including per-rule error counts and
    a record-level result list.
    """
    _require_batch(batch_id, tenant_id)
    try:
        return svc.validate_submission(batch_id)
    except RuntimeError as exc:
        logger.error("validate_batch error batch=%s: %s", batch_id, exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


# ---------------------------------------------------------------------------
# GET /batches/{id}/validation-report
# ---------------------------------------------------------------------------


@router.get("/batches/{batch_id}/validation-report", summary="Get validation report for a batch")
def get_validation_report(
    batch_id: str,
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
    _perm: None = Depends(require_permission("submissions", "read")),
) -> dict[str, Any]:
    """
    Return the latest validation results for the batch without re-running validation.

    Returns batch-level counts (valid, invalid, warning) and a list of all
    records with their individual validation status and error messages.

    Run POST /api/submissions/batches/{id}/validate first to populate results.
    """
    batch = _require_batch(batch_id, tenant_id)

    try:
        records_result = svc.list_records(
            batch_id=batch_id,
            limit=10000,
            offset=0,
        )
    except RuntimeError as exc:
        logger.error("Unexpected error: %s", exc)
        raise HTTPException(status_code=500, detail="Internal server error")

    total = records_result["total"]
    valid_count   = int(batch.get("valid_count")   or 0)
    invalid_count = int(batch.get("invalid_count") or 0)
    warning_count = int(batch.get("warning_count") or 0)

    return {
        "batch_id":    batch_id,
        "status":      batch.get("status"),
        "total":       total,
        "valid":       valid_count,
        "invalid":     invalid_count,
        "warnings":    warning_count,
        "pass_rate":   round(valid_count / total * 100, 1) if total else 0.0,
        "records":     records_result["items"],
    }


# ---------------------------------------------------------------------------
# POST /batches/{id}/submit
# ---------------------------------------------------------------------------


@router.post("/batches/{batch_id}/submit", summary="Mark batch as submitted and download file")
@limiter.limit("10/minute")
def submit_batch(
    request: Request,
    batch_id: str,
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
    _perm: None = Depends(require_permission("submissions", "write")),
) -> Any:
    """
    Mark the batch as submitted (sets status to 'submitted', records timestamp),
    then serve the generated file as a download response.

    Plans should:
    1. Run POST /validate first and confirm invalid_count == 0 (or acceptable).
    2. Call this endpoint to lock the batch status and retrieve the file.
    3. Transmit the downloaded file to CMS via the appropriate channel.

    Returns the submission file as an attachment download.
    """
    batch = _require_batch(batch_id, tenant_id)

    # Validate state — must be pending or validated
    current_status = batch.get("status", "")
    if current_status in ("submitted", "accepted", "rejected", "partial"):
        raise HTTPException(
            status_code=409,
            detail=f"Batch is already in '{current_status}' state. "
                   "Create a new batch to re-submit.",
        )

    try:
        updated_batch = svc.mark_submitted(batch_id)
    except (RuntimeError, ValueError) as exc:
        logger.error("Unexpected error: %s", exc)
        raise HTTPException(status_code=500, detail="Internal server error")

    file_path = updated_batch.get("file_path") or ""
    if not file_path or not os.path.isfile(file_path):
        # File missing — return metadata only
        return {
            "batch_id":     batch_id,
            "status":       "submitted",
            "submitted_at": updated_batch.get("submitted_at"),
            "warning":      "Submission file not found on disk. Check server file storage.",
        }

    # Path-traversal guard: resolved path must be inside the submissions output directory
    from app.services.submission_service import _output_dir as _get_output_dir
    _submissions_root = _get_output_dir().resolve()
    _resolved = Path(file_path).resolve()
    try:
        _resolved.relative_to(_submissions_root)
    except ValueError:
        raise HTTPException(status_code=400, detail="File path is outside the submissions output directory.")

    file_name = os.path.basename(file_path)
    return FileResponse(
        path=file_path,
        media_type="application/octet-stream",
        filename=file_name,
        headers={
            "X-Batch-Id":    batch_id,
            "X-File-Type":   str(updated_batch.get("file_type", "")),
            "X-Record-Count": str(updated_batch.get("record_count", 0)),
        },
    )


# ---------------------------------------------------------------------------
# GET /batches/{id}/download
# ---------------------------------------------------------------------------


@router.get("/batches/{batch_id}/download", summary="Download submission file for a batch")
def download_batch_file(
    batch_id: str,
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
    _perm: None = Depends(require_permission("submissions", "read")),
) -> Any:
    """
    Download the generated submission file for the given batch at any time.

    Unlike POST /submit, this endpoint does NOT change the batch status.
    Use it to retrieve a previously generated file for review or re-transmission.
    """
    batch = _require_batch(batch_id, tenant_id)

    file_path = batch.get("file_path") or ""
    if not file_path or not os.path.isfile(file_path):
        raise HTTPException(
            status_code=404,
            detail="Submission file not found on disk. The file may have been moved or deleted.",
        )

    # Path-traversal guard: resolved path must be inside the submissions output directory
    from app.services.submission_service import _output_dir as _get_output_dir
    _submissions_root = _get_output_dir().resolve()
    _resolved = Path(file_path).resolve()
    try:
        _resolved.relative_to(_submissions_root)
    except ValueError:
        raise HTTPException(status_code=400, detail="File path is outside the submissions output directory.")

    file_name = os.path.basename(file_path)
    return FileResponse(
        path=file_path,
        media_type="application/octet-stream",
        filename=file_name,
    )


# ---------------------------------------------------------------------------
# POST /batches/{id}/upload-response
# ---------------------------------------------------------------------------


@router.post(
    "/batches/{batch_id}/upload-response",
    summary="Upload a CMS MAO-002 or MAO-004 response file",
)
@limiter.limit("10/minute")
async def upload_response(
    request: Request,
    batch_id: str,
    response_type: Literal["MAO-002", "MAO-004"] = Query(
        ...,
        description="CMS response file type: MAO-002 (transaction reply) or MAO-004 (payment reconciliation)",
    ),
    file: UploadFile = File(..., description="CMS response file"),
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
    _perm: None = Depends(require_permission("submissions", "write")),
) -> dict[str, Any]:
    """
    Upload and parse a CMS response file for a submitted batch.

    **MAO-002** — Transaction Reply:
    - Contains accepted / rejected / duplicate status per record.
    - Updates `cms_status`, `cms_error_code`, `cms_error_desc` on each matched record.
    - Updates batch status to 'accepted', 'rejected', or 'partial'.

    **MAO-004** — Payment Reconciliation:
    - Contains payment amounts and risk score adjustments per record.
    - Updates `payment_amount` and `risk_score_adj` on each matched record.

    File is read as UTF-8 text; binary files will raise a 422 error.
    """
    _require_batch(batch_id, tenant_id)

    # Read and decode file content
    try:
        raw_bytes = await file.read()
        content = raw_bytes.decode("utf-8", errors="replace")
    except Exception as exc:
        logger.error("upload_response file read error: %s", exc)
        raise HTTPException(
            status_code=422,
            detail="Could not read uploaded file. Ensure it is a valid UTF-8 text file.",
        )

    if not content.strip():
        raise HTTPException(status_code=422, detail="Uploaded file is empty")

    file_name = file.filename or f"{response_type}_{batch_id}.txt"
    try:
        if response_type == "MAO-002":
            result = svc.parse_mao002_response(batch_id, content, file_name)
        else:
            result = svc.parse_mao004_response(batch_id, content, file_name)
    except RuntimeError as exc:
        logger.error(
            "upload_response error batch=%s type=%s: %s",
            batch_id, response_type, exc, exc_info=True,
        )
        logger.error("Unexpected error: %s", exc)
        raise HTTPException(status_code=500, detail="Internal server error")

    return result


# ---------------------------------------------------------------------------
# GET /batches/{id}/responses
# ---------------------------------------------------------------------------


@router.get("/batches/{batch_id}/responses", summary="List CMS response files for a batch")
def list_responses(
    batch_id: str,
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
    _perm: None = Depends(require_permission("submissions", "read")),
) -> dict[str, Any]:
    """
    Return all parsed CMS response files (MAO-002 and MAO-004) associated
    with the given batch, including accepted/rejected counts and total payment.
    """
    _require_batch(batch_id, tenant_id)
    try:
        responses = svc.list_responses(batch_id)
    except RuntimeError as exc:
        logger.error("Unexpected error: %s", exc)
        raise HTTPException(status_code=500, detail="Internal server error")
    return {"batch_id": batch_id, "count": len(responses), "responses": responses}


# ---------------------------------------------------------------------------
# GET /batches/{id}/reconciliation
# ---------------------------------------------------------------------------


@router.get("/batches/{batch_id}/reconciliation", summary="Payment reconciliation data for a batch")
def get_reconciliation(
    batch_id: str,
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
    _perm: None = Depends(require_permission("submissions", "read")),
) -> dict[str, Any]:
    """
    Return payment reconciliation summary and per-record detail for a batch
    after a MAO-004 response has been uploaded.

    Includes:
    - Total payment amount across all accepted records
    - Total risk score adjustment
    - Per-record line items with payment amounts
    - Accepted / rejected / duplicate counts
    """
    _require_batch(batch_id, tenant_id)
    try:
        return svc.get_reconciliation(batch_id)
    except RuntimeError as exc:
        logger.error("Unexpected error: %s", exc)
        raise HTTPException(status_code=500, detail="Internal server error")


# ---------------------------------------------------------------------------
# GET /schedule
# ---------------------------------------------------------------------------


@router.get("/schedule", summary="Get CMS submission deadline schedule")
def get_schedule(
    payment_year: int | None = Query(default=None, description="Filter by payment year"),
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
    _perm: None = Depends(require_permission("submissions", "read")),
) -> dict[str, Any]:
    """
    Return the CMS submission deadline schedule for the authenticated tenant.

    Merges standard CMS deadlines with any tenant-custom overrides.
    Each entry includes `days_until` and `is_overdue` for dashboard display.
    """
    try:
        schedule = svc.get_submission_schedule(tenant_id, payment_year)
    except Exception as exc:
        logger.error("Unexpected error: %s", exc)
        raise HTTPException(status_code=500, detail="Internal server error")
    return {
        "tenant_id":    tenant_id,
        "payment_year": payment_year,
        "count":        len(schedule),
        "schedule":     schedule,
    }


# ---------------------------------------------------------------------------
# POST /schedule
# ---------------------------------------------------------------------------


@router.post(
    "/schedule",
    status_code=status.HTTP_201_CREATED,
    summary="Add or update a custom CMS submission deadline",
)
@limiter.limit("10/minute")
def upsert_schedule(
    request: Request,
    body: ScheduleUpsertRequest,
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
    _perm: None = Depends(require_permission("submissions", "write")),
) -> dict[str, Any]:
    """
    Add a new custom deadline or update an existing one for the tenant.

    Custom deadlines override the standard CMS schedule for the given
    (payment_year, sweep_type) combination.  Use this to track internal
    deadlines that differ from the CMS-published dates.
    """
    try:
        return svc.upsert_submission_schedule(
            tenant_id=tenant_id,
            payment_year=body.payment_year,
            sweep_type=body.sweep_type,
            deadline_date=body.deadline_date,
            description=body.description,
        )
    except RuntimeError as exc:
        logger.error("Unexpected error: %s", exc)
        raise HTTPException(status_code=500, detail="Internal server error")


# ---------------------------------------------------------------------------
# GET /stats
# ---------------------------------------------------------------------------


@router.get("/stats", summary="Overall submission statistics for the tenant")
def get_stats(
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
    _perm: None = Depends(require_permission("submissions", "read")),
) -> dict[str, Any]:
    """
    Return aggregate CMS submission statistics for the authenticated tenant.

    Includes:
    - Total batches generated
    - Total records submitted and overall acceptance rate
    - Per-payment-year / per-file-type breakdown
    - Upcoming CMS deadlines within the next 90 days
    """
    try:
        return svc.get_submission_stats(tenant_id)
    except RuntimeError as exc:
        logger.error("Unexpected error: %s", exc)
        raise HTTPException(status_code=500, detail="Internal server error")


# ---------------------------------------------------------------------------
# GET /batches/{id}/errors
# ---------------------------------------------------------------------------


@router.get("/batches/{batch_id}/errors", summary="Records with errors for correction")
def get_error_records(
    batch_id: str,
    limit:  int = Query(default=200, ge=1, le=1000),
    offset: int = Query(default=0,   ge=0),
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
    _perm: None = Depends(require_permission("submissions", "read")),
) -> dict[str, Any]:
    """
    Return all records that have validation errors, validation warnings, or
    CMS rejections for a given batch.

    Use this endpoint to identify records requiring correction before
    re-generating the submission file.

    Records are ordered: invalid first (must-fix), then warnings, then rejections.
    Each record includes `validation_errors` (list of rule/message objects),
    `cms_error_code`, and `cms_error_desc` when available.
    """
    _require_batch(batch_id, tenant_id)
    try:
        return svc.list_error_records(batch_id, limit=limit, offset=offset)
    except RuntimeError as exc:
        logger.error("Unexpected error: %s", exc)
        raise HTTPException(status_code=500, detail="Internal server error")
