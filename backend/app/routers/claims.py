"""
Claims Data Ingestion Router.

Endpoints:
  POST   /api/claims/upload                          - Upload a claims file (CSV / 837P / 837I)
  GET    /api/claims/batches                         - List all uploaded batches
  GET    /api/claims/batches/{id}                    - Batch detail with processing stats
  DELETE /api/claims/batches/{id}                    - Delete a batch and its claims
  POST   /api/claims/batches/{id}/process            - Run patient matching + HCC mapping
  GET    /api/claims/batches/{id}/claims             - Paginated claim records in a batch
  GET    /api/claims/batches/{id}/diagnoses          - ICD-10 codes with HCC mapping
  GET    /api/claims/batches/{id}/hcc-summary        - HCC distribution for the batch
  GET    /api/claims/batches/{id}/unmapped-patients  - Patients not matched to OpenEMR
  POST   /api/claims/batches/{id}/calculate-raf      - RAF calculation for matched patients
  GET    /api/claims/stats                           - Overall claims statistics
"""
# Note: do NOT use 'from __future__ import annotations' here —
# it breaks FastAPI's UploadFile parameter resolution.

import logging
from typing import Any

from fastapi import (
    Depends,
    APIRouter,
    BackgroundTasks,
    HTTPException,
    Query,
    Request,
    UploadFile,
    File,
)

from app.services import claims_service as svc
from app.services.audit_logger import log_phi_access
from app.auth import get_current_user, require_permission
from app.rate_limit import limiter

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/claims", tags=["claims"])

# Maximum upload size: 100 MB
_MAX_UPLOAD_BYTES = 100 * 1024 * 1024


# ---------------------------------------------------------------------------
# Upload
# ---------------------------------------------------------------------------


@router.post(
    "/upload", summary="Upload a claims file (CSV, 837P, or 837I)", response_model=None
)
@limiter.limit("10/minute")
async def upload_claims_file(
    request: Request,
    file: UploadFile = File(..., description="Claims file — CSV, .837, .edi, or .x12"),
    current_user: dict = Depends(get_current_user),
    _perm: None = Depends(require_permission("claims", "write")),
) -> dict[str, Any]:
    """
    Upload a claims file and parse it into a new batch.

    The uploader identity is derived from the authenticated JWT — the client
    cannot spoof the ``uploaded_by`` field.
    """
    uploaded_by = f"user:{current_user.get('id', 'unknown')} ({current_user.get('email', 'unknown')})"
    filename = file.filename or "upload.csv"

    content = await file.read()
    if len(content) > _MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"File too large. Maximum allowed size is {_MAX_UPLOAD_BYTES // (1024 * 1024)} MB.",
        )
    if len(content) == 0:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")

    try:
        file_format, claims = svc.parse_claims_file(filename, content)
    except Exception as exc:
        logger.error("Failed to parse uploaded file '%s': %s", filename, exc)
        raise HTTPException(status_code=422, detail="Invalid input")

    if not claims:
        raise HTTPException(
            status_code=422,
            detail="No claims could be parsed from the file. Check the format and content.",
        )

    try:
        tenant_id = str(current_user.get("tenant_id") or "")
        batch_id = svc.create_batch(filename, file_format, len(content), uploaded_by, tenant_id=tenant_id)
        stored_count = svc.store_parsed_claims(batch_id, claims)
        svc.update_batch_status(batch_id, svc.STATUS_PARSED)
    except Exception as exc:
        logger.error("Failed to store claims for file '%s': %s", filename, exc)
        raise HTTPException(status_code=500, detail="Internal server error")

    log_phi_access(
        action="upload",
        resource="claims_batch",
        details=f"batch_id={batch_id} filename='{filename}' format={file_format} claims={stored_count}",
    )

    return {
        "batch_id": batch_id,
        "filename": filename,
        "file_format": file_format,
        "file_size_bytes": len(content),
        "claims_parsed": len(claims),
        "claims_stored": stored_count,
        "status": svc.STATUS_PARSED,
        "message": (
            f"Successfully parsed {stored_count} claims. "
            "Call POST /api/claims/batches/{batch_id}/process to run patient matching and HCC mapping."
        ),
    }


# ---------------------------------------------------------------------------
# Batch listing and detail
# ---------------------------------------------------------------------------


@router.get("/batches", summary="List all uploaded claims batches")
def list_batches(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    current_user: dict = Depends(get_current_user),
    _perm: None = Depends(require_permission("claims", "read")),
) -> dict[str, Any]:
    """Return all claims batches ordered by most recent upload."""
    tenant_id = str(current_user.get("tenant_id") or "")
    try:
        batches = svc.list_batches(limit=limit, offset=offset, tenant_id=tenant_id)
    except Exception as exc:
        logger.error("list_batches error: %s", exc)
        raise HTTPException(status_code=500, detail="Internal server error")

    return {
        "limit": limit,
        "offset": offset,
        "count": len(batches),
        "batches": batches,
    }


@router.get("/batches/{batch_id}", summary="Get batch details with processing stats")
def get_batch(
    batch_id: int,
    current_user: dict = Depends(get_current_user),
    _perm: None = Depends(require_permission("claims", "read")),
) -> dict[str, Any]:
    """
    Return full batch metadata including status, claim counts, match counts,
    and computed statistics if the batch has been processed.
    """
    tenant_id = str(current_user.get("tenant_id") or "")
    batch = svc.get_batch(batch_id, tenant_id=tenant_id)
    if not batch:
        raise HTTPException(status_code=404, detail=f"Batch {batch_id} not found.")

    stats: dict[str, Any] = {}
    if batch.get("status") in (svc.STATUS_COMPLETED, svc.STATUS_PROCESSING):
        try:
            stats = svc.compute_batch_stats(batch_id)
        except Exception as exc:
            logger.warning(
                "compute_batch_stats error for batch_id=%d: %s", batch_id, exc
            )

    log_phi_access(
        action="read",
        resource="claims_batch",
        details=f"batch_id={batch_id}",
    )

    return {**batch, "stats": stats}


@router.delete("/batches/{batch_id}", summary="Delete a batch and all its claims")
def delete_batch(
    batch_id: int,
    current_user: dict = Depends(get_current_user),
    _perm: None = Depends(require_permission("claims", "delete")),
) -> dict[str, Any]:
    """
    Permanently delete a batch and all associated claim records, diagnosis
    mappings, and processing results. This action cannot be undone.
    """
    tenant_id = str(current_user.get("tenant_id") or "")
    batch = svc.get_batch(batch_id, tenant_id=tenant_id)
    if not batch:
        raise HTTPException(status_code=404, detail=f"Batch {batch_id} not found.")

    try:
        deleted_claims = svc.delete_batch(batch_id, tenant_id=tenant_id)
    except Exception as exc:
        logger.error("delete_batch error for batch_id=%d: %s", batch_id, exc)
        raise HTTPException(status_code=500, detail="Internal server error")

    log_phi_access(
        action="delete",
        resource="claims_batch",
        details=f"batch_id={batch_id} deleted_claims={deleted_claims}",
    )

    return {
        "batch_id": batch_id,
        "deleted": True,
        "claims_deleted": deleted_claims,
    }


# ---------------------------------------------------------------------------
# Batch processing
# ---------------------------------------------------------------------------


@router.post(
    "/batches/{batch_id}/process",
    summary="Process a batch: patient matching + HCC mapping",
)
def process_batch(
    batch_id: int,
    background_tasks: BackgroundTasks,
    run_async: bool = Query(
        False,
        description="If true, start processing in the background and return immediately.",
    ),
    current_user: dict = Depends(get_current_user),
    _perm: None = Depends(require_permission("claims", "write")),
) -> dict[str, Any]:
    """
    Run the full processing pipeline for a parsed batch:

    1. Patient matching — match each claim patient to an OpenEMR pid using
       member ID, exact name+DOB, and fuzzy name+DOB-year matching.
    2. HCC mapping — look up HCC categories for each ICD-10 code via the
       hcc_icd10_crosswalk table or hccinfhir library.

    Set ?run_async=true to process in the background (returns 202 immediately).
    """
    tenant_id = str(current_user.get("tenant_id") or "")
    batch = svc.get_batch(batch_id, tenant_id=tenant_id)
    if not batch:
        raise HTTPException(status_code=404, detail=f"Batch {batch_id} not found.")

    if batch.get("status") == svc.STATUS_PROCESSING:
        raise HTTPException(status_code=409, detail="Batch is already being processed.")

    if run_async:
        background_tasks.add_task(_run_process_batch, batch_id)
        return {
            "batch_id": batch_id,
            "status": "processing_started",
            "message": "Batch processing started in background. Poll GET /api/claims/batches/{id} for status.",
        }

    try:
        result = svc.process_batch(batch_id)
    except Exception as exc:
        logger.error("process_batch failed for batch_id=%d: %s", batch_id, exc)
        raise HTTPException(status_code=500, detail="Internal server error")

    log_phi_access(
        action="process",
        resource="claims_batch",
        details=f"batch_id={batch_id} matched={result.get('patient_matching', {}).get('matched')}",
    )

    return result


def _run_process_batch(batch_id: int) -> None:
    """Background task wrapper for process_batch."""
    try:
        svc.process_batch(batch_id)
    except Exception as exc:
        logger.error(
            "Background process_batch failed for batch_id=%d: %s", batch_id, exc
        )


# ---------------------------------------------------------------------------
# Claim records
# ---------------------------------------------------------------------------


@router.get("/batches/{batch_id}/claims", summary="List claims in a batch")
def list_batch_claims(
    batch_id: int,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    current_user: dict = Depends(get_current_user),
    _perm: None = Depends(require_permission("claims", "read")),
) -> dict[str, Any]:
    """
    Return paginated claim records for a batch.

    Each record includes parsed demographics, ICD-10 codes, CPT codes,
    charges, and the matched OpenEMR pid (if any).
    """
    tenant_id = str(current_user.get("tenant_id") or "")
    batch = svc.get_batch(batch_id, tenant_id=tenant_id)
    if not batch:
        raise HTTPException(status_code=404, detail=f"Batch {batch_id} not found.")

    try:
        claims, total = svc.get_batch_claims(batch_id, limit=limit, offset=offset)
    except Exception as exc:
        logger.error("get_batch_claims error batch_id=%d: %s", batch_id, exc)
        raise HTTPException(status_code=500, detail="Internal server error")

    log_phi_access(
        action="list",
        resource="claims_records",
        details=f"batch_id={batch_id} limit={limit} offset={offset} returned={len(claims)}",
    )

    return {
        "batch_id": batch_id,
        "total": total,
        "limit": limit,
        "offset": offset,
        "claims": claims,
    }


# ---------------------------------------------------------------------------
# Diagnoses and HCC mapping
# ---------------------------------------------------------------------------


@router.get(
    "/batches/{batch_id}/diagnoses",
    summary="All ICD-10 codes from batch with HCC mapping",
)
def get_batch_diagnoses(
    batch_id: int,
    limit: int = Query(200, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    current_user: dict = Depends(get_current_user),
    _perm: None = Depends(require_permission("claims", "read")),
) -> dict[str, Any]:
    """
    Return all unique ICD-10 codes found in this batch, each annotated with
    its HCC category (if mapped) and occurrence counts.
    """
    tenant_id = str(current_user.get("tenant_id") or "")
    batch = svc.get_batch(batch_id, tenant_id=tenant_id)
    if not batch:
        raise HTTPException(status_code=404, detail=f"Batch {batch_id} not found.")

    try:
        diagnoses = svc.get_batch_diagnoses(batch_id, limit=limit, offset=offset)
    except Exception as exc:
        logger.error("get_batch_diagnoses error batch_id=%d: %s", batch_id, exc)
        raise HTTPException(status_code=500, detail="Internal server error")

    return {
        "batch_id": batch_id,
        "limit": limit,
        "offset": offset,
        "total_codes": len(diagnoses),
        "diagnoses": diagnoses,
    }


@router.get(
    "/batches/{batch_id}/hcc-summary", summary="HCC distribution from the batch"
)
def get_hcc_summary(
    batch_id: int,
    limit: int = Query(200, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    current_user: dict = Depends(get_current_user),
    _perm: None = Depends(require_permission("claims", "read")),
) -> dict[str, Any]:
    """
    Return a ranked summary of HCC categories found across all claims in the batch,
    with patient and claim occurrence counts per HCC.
    """
    tenant_id = str(current_user.get("tenant_id") or "")
    batch = svc.get_batch(batch_id, tenant_id=tenant_id)
    if not batch:
        raise HTTPException(status_code=404, detail=f"Batch {batch_id} not found.")

    try:
        hcc_summary = svc.get_hcc_summary(batch_id, limit=limit, offset=offset)
    except Exception as exc:
        logger.error("get_hcc_summary error batch_id=%d: %s", batch_id, exc)
        raise HTTPException(status_code=500, detail="Internal server error")

    return {
        "batch_id": batch_id,
        "limit": limit,
        "offset": offset,
        "unique_hccs": len(hcc_summary),
        "hcc_summary": hcc_summary,
    }


# ---------------------------------------------------------------------------
# Unmatched patients
# ---------------------------------------------------------------------------


@router.get(
    "/batches/{batch_id}/unmapped-patients", summary="Patients not matched to OpenEMR"
)
def get_unmapped_patients(
    batch_id: int,
    limit: int = Query(200, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    current_user: dict = Depends(get_current_user),
    _perm: None = Depends(require_permission("claims", "read")),
) -> dict[str, Any]:
    """
    Return distinct patients in this batch that could not be matched to an
    OpenEMR patient record. Useful for manual reconciliation workflows.
    """
    tenant_id = str(current_user.get("tenant_id") or "")
    batch = svc.get_batch(batch_id, tenant_id=tenant_id)
    if not batch:
        raise HTTPException(status_code=404, detail=f"Batch {batch_id} not found.")

    try:
        patients = svc.get_unmapped_patients(batch_id, limit=limit, offset=offset)
    except Exception as exc:
        logger.error("get_unmapped_patients error batch_id=%d: %s", batch_id, exc)
        raise HTTPException(status_code=500, detail="Internal server error")

    log_phi_access(
        action="list",
        resource="unmapped_patients",
        details=f"batch_id={batch_id} count={len(patients)}",
    )

    return {
        "batch_id": batch_id,
        "limit": limit,
        "offset": offset,
        "unmapped_count": len(patients),
        "patients": patients,
    }


# ---------------------------------------------------------------------------
# RAF calculation
# ---------------------------------------------------------------------------


@router.post(
    "/batches/{batch_id}/calculate-raf",
    summary="Trigger RAF calculation for matched patients",
)
def calculate_raf_for_batch(
    batch_id: int,
    background_tasks: BackgroundTasks,
    measurement_year: int = Query(2026, ge=2020, le=2030),
    run_async: bool = Query(
        False,
        description="If true, run in the background and return immediately.",
    ),
    current_user: dict = Depends(get_current_user),
    _perm: None = Depends(require_permission("claims", "write")),
) -> dict[str, Any]:
    """
    Calculate CMS-HCC V28 RAF scores for all patients in this batch that have
    been successfully matched to an OpenEMR pid.

    Uses ICD-10 codes from OpenEMR billing (not just from the claims file) to
    ensure the most complete code set is used for RAF scoring.

    RAF scores are estimates based on hccinfhir (third-party open-source
    implementation of CMS-HCC V28). Not CMS-validated. Verify against official
    CMS SAS software before use in payment determinations.
    """
    tenant_id = str(current_user.get("tenant_id") or "")
    batch = svc.get_batch(batch_id, tenant_id=tenant_id)
    if not batch:
        raise HTTPException(status_code=404, detail=f"Batch {batch_id} not found.")

    if batch.get("status") not in (
        svc.STATUS_COMPLETED,
        svc.STATUS_PARSED,
        svc.STATUS_PROCESSING,
    ):
        raise HTTPException(
            status_code=409,
            detail=f"Batch must be in 'completed' or 'parsed' status to calculate RAF. Current: {batch.get('status')}",
        )

    if run_async and background_tasks is not None:
        background_tasks.add_task(_run_calculate_raf, batch_id, measurement_year)
        return {
            "batch_id": batch_id,
            "measurement_year": measurement_year,
            "status": "raf_calculation_started",
            "message": "RAF calculation started in background.",
        }

    try:
        result = svc.calculate_raf_for_batch(batch_id, measurement_year)
    except Exception as exc:
        logger.error("calculate_raf_for_batch failed batch_id=%d: %s", batch_id, exc)
        raise HTTPException(status_code=500, detail="Internal server error")

    log_phi_access(
        action="raf_calculate",
        resource="claims_batch",
        details=(
            f"batch_id={batch_id} year={measurement_year} "
            f"patients={result.get('patients_processed')} errors={result.get('errors')}"
        ),
    )

    return result


def _run_calculate_raf(batch_id: int, measurement_year: int) -> None:
    """Background task wrapper for calculate_raf_for_batch."""
    try:
        svc.calculate_raf_for_batch(batch_id, measurement_year)
    except Exception as exc:
        logger.error(
            "Background calculate_raf_for_batch failed batch_id=%d: %s", batch_id, exc
        )


# ---------------------------------------------------------------------------
# Overall stats
# ---------------------------------------------------------------------------


@router.get("/stats", summary="Overall claims ingestion statistics")
def get_claims_stats(
    current_user: dict = Depends(get_current_user),
    _perm: None = Depends(require_permission("claims", "read")),
) -> dict[str, Any]:
    """
    Return aggregate statistics across all claims batches: total batches,
    total claims, matched patient counts, unique diagnoses, unique HCCs,
    and a breakdown of batches by status.
    """
    try:
        stats = svc.get_overall_stats()
    except Exception as exc:
        logger.error("get_claims_stats error: %s", exc)
        raise HTTPException(status_code=500, detail="Internal server error")

    return stats
