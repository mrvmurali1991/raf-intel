"""
HCC Removal Candidates router - Two-Way Coding (RADV defense).

Endpoints (matching the suspect-router pattern)::

    POST /api/raf/{patient_id}/audit-removals
        Run a fresh removal scan for the patient and return the candidates.

    GET  /api/raf/{patient_id}/removal-candidates
        List existing removal candidates for the patient (default status='pending').

    POST /api/raf/removal-candidates/{candidate_id}/dismiss
        Clinician keeps the HCC; removes it from the review queue.

    POST /api/raf/removal-candidates/{candidate_id}/confirm-removal
        Clinician confirms the HCC is unsupported (workflow status only -
        the engine does not delete from raf_patient_hcc).

Tenant scoping
--------------
The system does not (yet) carry tenant_id on the request layer, so every
endpoint accepts an optional ``X-Tenant-ID`` header (default 'default').
This mirrors the way other routers will gain tenancy when the multi-tenant
rollout lands and lets the engine table stay tenant-aware from day one.

PHI auditing
------------
Each call writes to the phi_audit logger via ``log_phi_access`` with the
same shape used by the patients/analysis routers.
"""

import logging
from typing import Any, Optional

from fastapi import Depends, APIRouter, Header, HTTPException, Query
from pydantic import BaseModel, Field

from app.services import hcc_removal_engine
from app.services.audit_logger import log_phi_access
from app.services.openemr_connector import get_patient
from app.auth import get_current_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/raf", tags=["hcc-removal"], dependencies=[Depends(get_current_user)])


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------

class AuditRemovalsRequest(BaseModel):
    measurement_year: int = Field(default=2026, ge=2000, le=2100)
    persist: bool = Field(
        default=True,
        description="If false, run in dry-run / preview mode without writing.",
    )


class DismissRequest(BaseModel):
    reviewed_by: str = Field(..., min_length=1)
    notes: str = Field(default="", description="Optional clinician notes")


class ConfirmRemovalRequest(BaseModel):
    reviewed_by: str = Field(..., min_length=1)
    notes: str = Field(default="", description="Optional clinician notes")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _resolve_tenant(header_value: str | None) -> str:
    return (header_value or "default").strip() or "default"


# ---------------------------------------------------------------------------
# POST /api/raf/{patient_id}/audit-removals
# ---------------------------------------------------------------------------

@router.post(
    "/{patient_id}/audit-removals",
    summary="Run two-way coding removal-candidate audit for a patient",
)
def audit_removals(
    patient_id: int,
    body: AuditRemovalsRequest | None = None,
    x_tenant_id: Optional[str] = Header(default=None, alias="X-Tenant-ID"),
) -> dict[str, Any]:
    """
    Re-evaluate every coded HCC against the chart and return the list of
    HCCs that lack MEAT support.  New / refreshed candidates are upserted
    into ``hcc_removal_candidates`` with status='pending'.
    """
    body = body or AuditRemovalsRequest()
    tenant_id = _resolve_tenant(x_tenant_id)

    try:
        patient = get_patient(patient_id)
    except Exception:
        logger.debug("swallowed exception", exc_info=True)
        patient = None
    # Skip patient existence check (patients table optional in this deployment)

    log_phi_access(
        action="audit-removals",
        resource="hcc",
        patient_id=patient_id,
        user="api",
        details=f"tenant_id={tenant_id} year={body.measurement_year}",
    )

    try:
        candidates = hcc_removal_engine.generate_removal_candidates(
            patient_id,
            year=body.measurement_year,
            tenant_resolver=lambda _pid: tenant_id,
            persist=body.persist,
        )
    except Exception as exc:
        logger.exception("audit-removals failed pid=%s: %s", patient_id, exc)
        raise HTTPException(status_code=500, detail=f"audit-removals failed: {exc}")

    return {
        "patient_id":        patient_id,
        "tenant_id":         tenant_id,
        "measurement_year":  body.measurement_year,
        "persisted":         body.persist,
        "candidate_count":   len(candidates),
        "candidates":        candidates,
    }


# ---------------------------------------------------------------------------
# GET /api/raf/{patient_id}/removal-candidates
# ---------------------------------------------------------------------------

@router.get(
    "/{patient_id}/removal-candidates",
    summary="List removal candidates for a patient",
)
def list_removal_candidates(
    patient_id: int,
    status: str = Query(
        default="pending",
        description="pending | dismissed | removed | all",
    ),
    measurement_year: int | None = Query(default=None, ge=2000, le=2100),
    limit: int = Query(default=200, ge=1, le=1000),
    x_tenant_id: Optional[str] = Header(default=None, alias="X-Tenant-ID"),
) -> dict[str, Any]:
    tenant_id = _resolve_tenant(x_tenant_id)

    try:
        patient = get_patient(patient_id)
    except Exception:
        logger.debug("swallowed exception", exc_info=True)
        patient = None
    # Skip patient existence check (patients table optional in this deployment)

    log_phi_access(
        action="list-removal-candidates",
        resource="hcc",
        patient_id=patient_id,
        user="api",
        details=f"tenant_id={tenant_id} status={status} year={measurement_year}",
    )

    rows = hcc_removal_engine.list_candidates(
        patient_id=patient_id,
        tenant_id=tenant_id,
        status=status,
        year=measurement_year,
        limit=limit,
    )

    return {
        "patient_id":   patient_id,
        "tenant_id":    tenant_id,
        "status":       status,
        "count":        len(rows),
        "candidates":   rows,
    }


# ---------------------------------------------------------------------------
# POST /api/raf/removal-candidates/{candidate_id}/dismiss
# ---------------------------------------------------------------------------

@router.post(
    "/removal-candidates/{candidate_id}/dismiss",
    summary="Dismiss a removal candidate (clinician keeps the HCC)",
)
def dismiss(
    candidate_id: int,
    body: DismissRequest,
    x_tenant_id: Optional[str] = Header(default=None, alias="X-Tenant-ID"),
) -> dict[str, Any]:
    tenant_id = _resolve_tenant(x_tenant_id)

    existing = hcc_removal_engine.get_candidate(candidate_id, tenant_id=tenant_id)
    if not existing:
        raise HTTPException(
            status_code=404,
            detail=f"Removal candidate {candidate_id} not found in tenant '{tenant_id}'",
        )

    log_phi_access(
        action="dismiss-removal-candidate",
        resource="hcc",
        patient_id=int(existing.get("patient_id") or 0),
        user=body.reviewed_by,
        details=f"candidate_id={candidate_id} tenant_id={tenant_id}",
    )

    try:
        record = hcc_removal_engine.dismiss_candidate(
            candidate_id,
            reviewed_by=body.reviewed_by,
            notes=body.notes,
            tenant_id=tenant_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        logger.exception("dismiss failed id=%s: %s", candidate_id, exc)
        raise HTTPException(status_code=500, detail=f"dismiss failed: {exc}")

    return {"candidate_id": candidate_id, "action": "dismissed", "record": record}


# ---------------------------------------------------------------------------
# POST /api/raf/removal-candidates/{candidate_id}/confirm-removal
# ---------------------------------------------------------------------------

@router.post(
    "/removal-candidates/{candidate_id}/confirm-removal",
    summary="Confirm removal of an HCC (workflow status only)",
)
def confirm_removal(
    candidate_id: int,
    body: ConfirmRemovalRequest,
    x_tenant_id: Optional[str] = Header(default=None, alias="X-Tenant-ID"),
) -> dict[str, Any]:
    tenant_id = _resolve_tenant(x_tenant_id)

    existing = hcc_removal_engine.get_candidate(candidate_id, tenant_id=tenant_id)
    if not existing:
        raise HTTPException(
            status_code=404,
            detail=f"Removal candidate {candidate_id} not found in tenant '{tenant_id}'",
        )

    log_phi_access(
        action="confirm-hcc-removal",
        resource="hcc",
        patient_id=int(existing.get("patient_id") or 0),
        user=body.reviewed_by,
        details=f"candidate_id={candidate_id} tenant_id={tenant_id}",
    )

    try:
        record = hcc_removal_engine.confirm_removal(
            candidate_id,
            reviewed_by=body.reviewed_by,
            notes=body.notes,
            tenant_id=tenant_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        logger.exception("confirm-removal failed id=%s: %s", candidate_id, exc)
        raise HTTPException(status_code=500, detail=f"confirm-removal failed: {exc}")

    return {"candidate_id": candidate_id, "action": "removed", "record": record}
