"""
Suspects router — manages suspect conditions (missing / unconfirmed HCC codes).

Table: raf_suspect_conditions
  id, patient_id, measurement_year, suspect_hcc, suspect_icd10,
  evidence_type  ENUM('medication','lab','imaging','referral','historical'),
  evidence_detail JSON, confidence_score DECIMAL(5,4),
  status  ENUM('open','accepted','dismissed','coded'),
  reviewed_by, reviewed_at, created_at, updated_at

Endpoints
---------
GET  /api/suspects                   – all open suspects, sorted by confidence
GET  /api/suspects/{pid}             – suspects for a single patient
POST /api/suspects/scan/{pid}        – run full suspect scan for a patient
POST /api/suspects/scan-all          – run suspect scan for every patient
PUT  /api/suspects/{suspect_id}/accept   – mark accepted / coded
PUT  /api/suspects/{suspect_id}/dismiss  – mark dismissed
POST /api/suspects/bulk-update       – bulk accept or dismiss
"""
# Removed: from __future__ import annotations (breaks FastAPI schema generation)

import logging
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from app.auth import get_current_user, require_permission
from app.rate_limit import limiter
from app.services.openemr_connector import get_all_patients, get_patient
from app.services.suspect_engine import (
    accept_suspect,
    dismiss_suspect,
    get_all_open_suspects,
    get_suspects_for_patient,
    run_full_suspect_scan,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/suspects", tags=["suspects"])


# ---------------------------------------------------------------------------
# Pydantic request / response models
# ---------------------------------------------------------------------------


class AcceptRequest(BaseModel):
    pass


class DismissRequest(BaseModel):
    reason: str = Field(default="dismissed via api", description="Reason for dismissal")


class BulkUpdateRequest(BaseModel):
    ids: list[int] = Field(
        ..., min_length=1, description="List of suspect IDs to update"
    )
    action: Literal["accept", "dismiss"] = Field(..., description="Action to perform")
    reason: str = Field(
        default="bulk update", description="Reason (required when dismissing)"
    )


class SuspectResponse(BaseModel):
    suspect_id: int
    patient_id: int
    status: str
    suspect_hcc: int
    suspect_icd10: str
    evidence_type: str
    confidence_score: float
    # Calibration layer — see services/raf/calibration/__init__.py for the
    # full caveats.  raw_confidence mirrors confidence_score; the new
    # calibrated_confidence is a probability in [0,1] produced by the
    # per-source calibrator artifacts.  When the calibration feature flag
    # is off or no artifact exists, calibrated_confidence == raw_confidence.
    raw_confidence: float | None = None
    calibrated_confidence: float | None = None


class BulkUpdateResult(BaseModel):
    action: str
    requested: int
    succeeded: int
    failed: int
    errors: list[dict[str, Any]]


class SuspectListResponse(BaseModel):
    status_filter: str
    count: int
    limit: int
    offset: int
    suspects: list[dict[str, Any]]


class SuspectPatientResponse(BaseModel):
    pid: int
    patient_name: str
    status_filter: str
    year_filter: int | None
    count: int
    suspects: list[dict[str, Any]]


class ScanPatientResponse(BaseModel):
    pid: int
    patient_name: str
    new_suspects_found: int
    suspects: list[dict[str, Any]]


class ScanAllResponse(BaseModel):
    patients_scanned: int
    patients_with_errors: int
    total_new_suspects: int
    per_patient: list[dict[str, Any]]
    errors: list[dict[str, Any]]


class AcceptActionResponse(BaseModel):
    suspect_id: int
    action: str
    reviewed_by: str
    record: dict[str, Any]


class DismissActionResponse(BaseModel):
    suspect_id: int
    action: str
    reviewed_by: str
    reason: str
    record: dict[str, Any]


# ---------------------------------------------------------------------------
# GET /api/suspects  –  all open suspects across all patients
# ---------------------------------------------------------------------------


@router.get("", summary="List all open suspect conditions across all patients", response_model=SuspectListResponse)
@limiter.limit("60/minute")
def list_suspects(
    request: Request,
    status: str = Query(
        default="open",
        description="Filter by status: open | accepted | dismissed | coded | all",
    ),
    limit: int = Query(
        default=200, ge=1, le=1000, description="Maximum records to return"
    ),
    offset: int = Query(
        default=0, ge=0, description="Pagination offset"
    ),
    current_user: dict = Depends(get_current_user),
    _perm: None = Depends(require_permission("suspects", "read")),
) -> SuspectListResponse:
    """
    Return suspect conditions across every patient.

    Results are joined with OpenEMR ``patient_data`` (via ``get_all_open_suspects``)
    so each record includes ``patient_name``.  Records are sorted by
    ``confidence_score`` descending (highest confidence first).
    """
    tenant_id: str | None = current_user.get("tenant_id") or None
    if not tenant_id:
        raise HTTPException(status_code=403, detail="No tenant context for this user")
    try:
        suspects: list[dict[str, Any]] = get_all_open_suspects(
            limit=limit, offset=offset, tenant_id=tenant_id
        )
    except Exception as exc:
        logger.error("list_suspects – get_all_open_suspects failed: %s", exc)
        raise HTTPException(
            status_code=500, detail="Internal server error"
        )

    # Apply status filter (get_all_open_suspects may already filter to 'open')
    if status != "all":
        suspects = [s for s in suspects if s.get("status") == status]

    # Sort by confidence_score descending (DB already ordered, but defensive)
    suspects.sort(key=lambda s: float(s.get("confidence_score", 0)), reverse=True)

    return SuspectListResponse(
        status_filter=status,
        count=len(suspects),
        limit=limit,
        offset=offset,
        suspects=suspects,
    )


# ---------------------------------------------------------------------------
# POST /api/suspects/scan-all  –  must appear before /{pid} to avoid clash
# ---------------------------------------------------------------------------


@router.post("/scan-all", summary="Run suspect scan for all patients", response_model=ScanAllResponse)
@limiter.limit("2/minute")
def scan_all_patients(
    request: Request,
    year: int | None = Query(default=None),
    current_user: dict = Depends(get_current_user),
    _perm: None = Depends(require_permission("suspects", "write")),
) -> ScanAllResponse:
    """
    Iterate over every patient returned by ``get_all_patients`` and run a
    full suspect scan for each one.  Returns a summary of totals and any
    per-patient errors encountered.
    """
    tenant_id: str | None = current_user.get("tenant_id") or None
    if not tenant_id:
        raise HTTPException(status_code=403, detail="No tenant context for this user")
    try:
        patients: list[dict[str, Any]] = get_all_patients(tenant_id=tenant_id)
    except Exception as exc:
        logger.error("scan_all_patients – get_all_patients failed: %s", exc)
        raise HTTPException(
            status_code=500, detail="Internal server error"
        )

    # Guard: for large populations use the background job endpoint instead
    if len(patients) > 100:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Patient count ({len(patients)}) exceeds the synchronous limit of 100. "
                "Use the background job endpoint (POST /api/jobs/dispatch/suspects-scan) instead."
            ),
        )

    total_new = 0
    errors: list[dict[str, Any]] = []
    per_patient: list[dict[str, Any]] = []

    for patient in patients:
        pid: int = int(patient.get("pid") or patient.get("id") or 0)
        if not pid:
            continue
        try:
            found = run_full_suspect_scan(
                pid, year=year, tenant_id=current_user.get("tenant_id") or None
            )
            new_count = len(found)
            total_new += new_count
            per_patient.append({"pid": pid, "new_suspects": new_count})
            logger.info("scan_all: pid=%s found %s suspects", pid, new_count)
        except Exception as exc:
            logger.warning("scan_all: pid=%s failed: %s", pid, exc)
            errors.append({"pid": pid, "error": str(exc)})

    return ScanAllResponse(
        patients_scanned=len(patients),
        patients_with_errors=len(errors),
        total_new_suspects=total_new,
        per_patient=per_patient,
        errors=errors,
    )


# ---------------------------------------------------------------------------
# POST /api/suspects/bulk-update  –  must appear before /{pid}
# ---------------------------------------------------------------------------


@router.post("/bulk-update", summary="Bulk accept or dismiss multiple suspects")
@limiter.limit("20/minute")
def bulk_update(
    request: Request,
    body: BulkUpdateRequest,
    current_user: dict = Depends(get_current_user),
    _perm: None = Depends(require_permission("suspects", "write")),
) -> BulkUpdateResult:
    """
    Accept or dismiss a list of suspect IDs in a single call.

    Body::

        {
          "ids": [1, 2, 3],
          "action": "accept" | "dismiss",
          "reason": "not clinically relevant"   // used only for dismiss
        }

    The reviewer identity is derived from the authenticated JWT — the client
    cannot spoof the ``reviewed_by`` field.
    """
    reviewed_by = f"user:{current_user.get('id', 'unknown')} ({current_user.get('email', 'unknown')})"
    tenant_id: str | None = current_user.get("tenant_id") or None
    if not tenant_id:
        raise HTTPException(status_code=403, detail="No tenant context for this user")
    succeeded = 0
    failed = 0
    errors: list[dict[str, Any]] = []

    for sid in body.ids:
        try:
            if body.action == "accept":
                accept_suspect(sid, reviewed_by=reviewed_by, tenant_id=tenant_id)
            else:
                dismiss_suspect(sid, reason=body.reason, reviewed_by=reviewed_by, tenant_id=tenant_id)
            succeeded += 1
        except Exception as exc:
            failed += 1
            errors.append({"suspect_id": sid, "error": str(exc)})
            logger.warning(
                "bulk_update: id=%s action=%s failed: %s", sid, body.action, exc
            )

    return BulkUpdateResult(
        action=body.action,
        requested=len(body.ids),
        succeeded=succeeded,
        failed=failed,
        errors=errors,
    )


# ---------------------------------------------------------------------------
# GET /api/suspects/{pid}  –  suspects for a single patient
# ---------------------------------------------------------------------------


@router.get("/{pid}", summary="Get suspect conditions for a specific patient", response_model=SuspectPatientResponse)
@limiter.limit("60/minute")
def get_patient_suspects(
    request: Request,
    pid: int,
    status: str = Query(
        default="open",
        description="Filter by status: open | accepted | dismissed | coded | all",
    ),
    year: int | None = Query(
        default=None,
        description="Filter by measurement_year (e.g. 2025). Omit to return all years.",
    ),
    current_user: dict = Depends(get_current_user),
    _perm: None = Depends(require_permission("suspects", "read")),
) -> SuspectPatientResponse:
    """
    Return all suspect conditions for the patient identified by ``pid``.

    Patient existence is validated against OpenEMR before querying suspects.

    Pass ``?year=2025`` to restrict results to a specific ``measurement_year``.
    When omitted, suspects for all years are returned.
    """
    tenant_id: str = current_user.get("tenant_id") or ""
    from app.services.audit_logger import log_phi_access
    from app.services.patient_service import patient_is_accessible
    if not patient_is_accessible(pid, tenant_id):
        raise HTTPException(
            status_code=404, detail=f"Patient {pid} not found"
        )

    patient = get_patient(pid)
    if not patient:
        raise HTTPException(
            status_code=404, detail=f"Patient {pid} not found in OpenEMR"
        )

    log_phi_access(
        action="view",
        resource="suspect",
        patient_id=pid,
        user=current_user.get("email") or current_user.get("sub") or "unknown",
        details=f"status={status} year={year}",
        tenant_id=tenant_id or "unknown",
    )

    try:
        suspects: list[dict[str, Any]] = get_suspects_for_patient(
            pid, year=year, tenant_id=tenant_id or None
        )
    except Exception as exc:
        logger.error(
            "get_patient_suspects pid=%s tenant=%s user=%s: %s",
            pid, tenant_id, current_user.get("email") or current_user.get("id"), exc,
        )
        raise HTTPException(
            status_code=500,
            detail="Internal server error",
        )

    if status != "all":
        suspects = [s for s in suspects if s.get("status") == status]

    suspects.sort(key=lambda s: float(s.get("confidence_score", 0)), reverse=True)

    patient_name = (
        f"{patient.get('fname', '')} {patient.get('lname', '')}".strip()
        or f"Patient {pid}"
    )

    return SuspectPatientResponse(
        pid=pid,
        patient_name=patient_name,
        status_filter=status,
        year_filter=year,
        count=len(suspects),
        suspects=suspects,
    )


# ---------------------------------------------------------------------------
# POST /api/suspects/scan/{pid}  –  run full suspect scan for one patient
# ---------------------------------------------------------------------------


@router.post("/scan/{pid}", summary="Run full suspect scan for a patient", response_model=ScanPatientResponse)
def scan_patient(
    pid: int,
    year: int | None = Query(default=None),
    current_user: dict = Depends(get_current_user),
    _perm: None = Depends(require_permission("suspects", "write")),
) -> ScanPatientResponse:
    """
    Execute all suspect-detection passes for the given patient:

    * Medication-based suspects (``scan_medications``)
    * Lab-based suspects (``scan_labs``)
    * Historical HCC suspects
    * Note-vs-billing gap suspects

    All passes are orchestrated by ``run_full_suspect_scan``.  New suspects
    are persisted to ``raf_suspect_conditions``.  Already-known suspects are
    deduplicated by the engine and not double-inserted.
    """
    tenant_id: str = current_user.get("tenant_id") or ""
    from app.services.patient_service import patient_is_accessible
    if not patient_is_accessible(pid, tenant_id):
        raise HTTPException(
            status_code=404, detail=f"Patient {pid} not found in OpenEMR"
        )
    patient = get_patient(pid)
    if not patient:
        raise HTTPException(
            status_code=404, detail=f"Patient {pid} not found in OpenEMR"
        )

    try:
        new_suspects: list[dict[str, Any]] = run_full_suspect_scan(
            pid, year=year, tenant_id=tenant_id or None
        )
    except Exception as exc:
        logger.error(
            "scan_patient pid=%s tenant=%s user=%s: %s",
            pid, tenant_id, current_user.get("email") or current_user.get("id"), exc,
        )
        raise HTTPException(
            status_code=500, detail="Internal server error"
        )

    patient_name = (
        f"{patient.get('fname', '')} {patient.get('lname', '')}".strip()
        or f"Patient {pid}"
    )

    logger.info(
        "scan_patient: pid=%s tenant=%s user=%s found %s new suspects",
        pid, tenant_id, current_user.get("email") or current_user.get("id"), len(new_suspects),
    )

    return ScanPatientResponse(
        pid=pid,
        patient_name=patient_name,
        new_suspects_found=len(new_suspects),
        suspects=new_suspects,
    )


# ---------------------------------------------------------------------------
# PUT /api/suspects/{suspect_id}/accept
# ---------------------------------------------------------------------------


@router.put("/{suspect_id}/accept", summary="Accept a suspect condition", response_model=AcceptActionResponse)
def accept_suspect_endpoint(
    suspect_id: int,
    body: AcceptRequest,
    current_user: dict = Depends(get_current_user),
    _perm: None = Depends(require_permission("suspects", "write")),
) -> AcceptActionResponse:
    """
    Mark a suspect condition as **accepted** (the clinician agrees it should
    be coded for this encounter).

    The reviewer identity is derived from the authenticated JWT.
    """
    reviewed_by = f"user:{current_user.get('id', 'unknown')} ({current_user.get('email', 'unknown')})"
    tenant_id: str | None = current_user.get("tenant_id") or None
    if not tenant_id:
        raise HTTPException(status_code=403, detail="No tenant context for this user")
    try:
        updated = accept_suspect(suspect_id, reviewed_by=reviewed_by, tenant_id=tenant_id)
    except ValueError as exc:
        logger.error("Unexpected error: %s", exc)
        raise HTTPException(status_code=404, detail="Resource not found")
    except Exception as exc:
        logger.error("accept_suspect_endpoint id=%s: %s", suspect_id, exc)
        raise HTTPException(
            status_code=500, detail="Internal server error"
        )

    return AcceptActionResponse(
        suspect_id=suspect_id,
        action="accepted",
        reviewed_by=reviewed_by,
        record=updated,
    )


# ---------------------------------------------------------------------------
# PUT /api/suspects/{suspect_id}/dismiss
# ---------------------------------------------------------------------------


@router.put("/{suspect_id}/dismiss", summary="Dismiss a suspect condition", response_model=DismissActionResponse)
def dismiss_suspect_endpoint(
    suspect_id: int,
    body: DismissRequest,
    current_user: dict = Depends(get_current_user),
    _perm: None = Depends(require_permission("suspects", "write")),
) -> DismissActionResponse:
    """
    Mark a suspect condition as **dismissed** (the clinician reviewed and
    determined the condition is not present or not codeable this encounter).

    The reviewer identity is derived from the authenticated JWT.
    """
    reviewed_by = f"user:{current_user.get('id', 'unknown')} ({current_user.get('email', 'unknown')})"
    tenant_id: str | None = current_user.get("tenant_id") or None
    if not tenant_id:
        raise HTTPException(status_code=403, detail="No tenant context for this user")
    try:
        updated = dismiss_suspect(
            suspect_id,
            reason=body.reason,
            reviewed_by=reviewed_by,
            tenant_id=tenant_id,
        )
    except ValueError as exc:
        logger.error("Unexpected error: %s", exc)
        raise HTTPException(status_code=404, detail="Resource not found")
    except Exception as exc:
        logger.error("dismiss_suspect_endpoint id=%s: %s", suspect_id, exc)
        raise HTTPException(
            status_code=500, detail="Internal server error"
        )

    return DismissActionResponse(
        suspect_id=suspect_id,
        action="dismissed",
        reviewed_by=reviewed_by,
        reason=body.reason,
        record=updated,
    )
