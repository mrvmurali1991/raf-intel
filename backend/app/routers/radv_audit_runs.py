"""
RADV Audit-Run Router (Gap #3 — Audit Defense Workflow)
=======================================================

CMS RADV mock-audit run lifecycle:
  - POST   /api/radv/audit-runs                 — create, sample N patients
  - GET    /api/radv/audit-runs                 — list runs for the tenant
  - GET    /api/radv/audit-runs/{id}            — run header + records
  - PUT    /api/radv/audit-runs/{id}/records/{rid}
                                                — coder updates decision/notes
  - POST   /api/radv/audit-runs/{id}/resubmit-rejected
                                                — MAO-004 re-submission batch
  - POST   /api/radv/audit-runs/{id}/simulate   — exposure $ simulator
  - POST   /api/radv/audit-runs/{id}/export     — package + flag exported

Permissions: `radv:read` for GET, `radv:write` for the others.

Audit events:
  RADV_AUDIT_RUN_CREATED, RADV_RECORD_DECIDED, RADV_AUDIT_EXPORTED
"""
# Do NOT add 'from __future__ import annotations' — breaks FastAPI schema gen.

import logging
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from app.auth import get_current_user, get_tenant_id, require_permission
from app.services import radv_audit_run_service as svc
from app.services.redis_cache import invalidate_audit_runs

logger = logging.getLogger(__name__)

# Distinct tag so the new endpoints don't blur with the existing
# /api/radv audit-trail / MEAT-compliance endpoints in radv_audit.py.
router = APIRouter(prefix="/api/radv", tags=["radv-audit-runs"])

SampleMethodLit = Literal["random", "stratified_hcc", "stratified_raf_decile", "high_risk_first"]
EvidenceStatusLit = Literal["pending", "complete", "missing_meat", "chart_requested"]
DecisionLit = Literal["pending", "defensible", "undefensible", "needs_remediation"]


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class CreateRunIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    payment_year: int = Field(..., ge=2015, le=2099)
    sample_size: int = Field(201, ge=1, le=5000)
    sample_method: SampleMethodLit = "stratified_raf_decile"
    notes: Optional[str] = Field(None, max_length=4000)
    # FFS Adjuster extrapolation fields (CMS 2023 Final Rule).
    # When members_enrolled is supplied, exposure uses ffs_adjuster_v1 methodology.
    # Without it, the run falls back to legacy 55x (methodology: legacy_v1).
    members_enrolled: Optional[int] = Field(None, gt=0, description="Contract enrollment for FFS Adjuster extrapolation")
    ffs_adjuster: Optional[float] = Field(None, gt=0.0, le=1.0, description="CMS FFS Adjuster (default 0.97)")


class UpdateRecordIn(BaseModel):
    evidence_status: Optional[EvidenceStatusLit] = None
    final_decision: Optional[DecisionLit] = None
    reviewer_notes: Optional[str] = Field(None, max_length=10_000)


class SimulateIn(BaseModel):
    assumed_fail_rate: float = Field(..., ge=0.0, le=1.0)
    # Per Sept 2025 N.D. Tex. ruling, CMS extrapolation is currently vacated.
    # Default is False (disabled) — plans can stress-test the enforced scenario.
    extrapolation_enforced: bool = Field(
        False,
        description=(
            "When False (default), returns sample-based direct exposure only "
            "(extrapolation multiplier = 1). When True, applies the full "
            "CMS extrapolation formula. Per Sept 2025 N.D. Tex. ruling, "
            "extrapolation is currently unenforceable (HHS appeal pending)."
        ),
    )


# ---------------------------------------------------------------------------
# Audit emission helper
# ---------------------------------------------------------------------------


def _emit(event_type: str, *, tenant_id: str, actor_user_id: int,
          subject_id: str, payload: dict) -> None:
    try:
        from app.services.immutable_audit import emit_audit_event

        emit_audit_event(
            event_type,
            tenant_id=tenant_id,
            actor_user_id=actor_user_id,
            subject_type="radv_audit_run",
            subject_id=str(subject_id),
            payload=payload,
        )
    except Exception as exc:  # never fail the request on audit-log error
        logger.warning("radv: immutable audit emit failed (%s): %s", event_type, exc)


# ---------------------------------------------------------------------------
# Endpoints — runs
# ---------------------------------------------------------------------------


@router.post(
    "/audit-runs",
    status_code=status.HTTP_201_CREATED,
    summary="Create a RADV audit run + sample N patients",
)
def create_run(
    body: CreateRunIn,
    current_user: dict = Depends(require_permission("radv", "write")),
    tenant_id: str = Depends(get_tenant_id),
) -> dict:
    try:
        run = svc.create_audit_run(
            tenant_id=tenant_id,
            name=body.name,
            payment_year=body.payment_year,
            sample_size=body.sample_size,
            sample_method=body.sample_method,
            created_by_user_id=int(current_user["id"]),
            notes=body.notes,
            members_enrolled=body.members_enrolled,
            ffs_adjuster=body.ffs_adjuster,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        logger.error("radv.create_run failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to create audit run")

    _emit(
        "RADV_AUDIT_RUN_CREATED",
        tenant_id=tenant_id,
        actor_user_id=int(current_user["id"]),
        subject_id=str(run["id"]),
        payload={
            "name": body.name,
            "payment_year": body.payment_year,
            "sample_size": body.sample_size,
            "sample_method": body.sample_method,
            "sampled_count": len(run.get("records") or []),
        },
    )
    return run


@router.get(
    "/audit-runs",
    summary="List RADV audit runs for the tenant",
)
def list_runs(
    extrapolation_enforced: bool = Query(
        False,
        description=(
            "When False (default), exposure dollars reflect direct sample-based "
            "figures only (extrapolation disabled per Sept 2025 court ruling). "
            "When True, full CMS extrapolation applies."
        ),
    ),
    current_user: dict = Depends(require_permission("radv", "read")),
    tenant_id: str = Depends(get_tenant_id),
) -> dict:
    return {
        "runs": svc.list_audit_runs(tenant_id=tenant_id),
        "extrapolation_enforced": extrapolation_enforced,
        "extrapolation_note": (
            None
            if extrapolation_enforced
            else "Disabled per Sept 2025 N.D. Tex. court ruling (HHS appeal pending). "
                 "Exposure shown is direct sample-based only."
        ),
    }


@router.get(
    "/audit-runs/{run_id}",
    summary="Get a RADV audit run with all sampled records",
)
def get_run(
    run_id: int,
    current_user: dict = Depends(require_permission("radv", "read")),
    tenant_id: str = Depends(get_tenant_id),
) -> dict:
    try:
        return svc.get_audit_run(run_id, tenant_id=tenant_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


# ---------------------------------------------------------------------------
# Endpoints — records
# ---------------------------------------------------------------------------


@router.put(
    "/audit-runs/{run_id}/records/{record_id}",
    summary="Update evidence_status / final_decision / notes for one record",
)
def update_record(
    run_id: int,
    record_id: int,
    body: UpdateRecordIn,
    current_user: dict = Depends(require_permission("radv", "write")),
    tenant_id: str = Depends(get_tenant_id),
) -> dict:
    try:
        rec = svc.update_record(
            run_id=run_id,
            record_id=record_id,
            tenant_id=tenant_id,
            reviewer_user_id=int(current_user["id"]),
            evidence_status=body.evidence_status,
            final_decision=body.final_decision,
            reviewer_notes=body.reviewer_notes,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    _emit(
        "RADV_RECORD_DECIDED",
        tenant_id=tenant_id,
        actor_user_id=int(current_user["id"]),
        subject_id=f"{run_id}:{record_id}",
        payload={
            "run_id": run_id,
            "record_id": record_id,
            "evidence_status": body.evidence_status,
            "final_decision": body.final_decision,
        },
    )
    return rec


# ---------------------------------------------------------------------------
# Endpoints — workflow actions
# ---------------------------------------------------------------------------


@router.post(
    "/audit-runs/{run_id}/simulate",
    summary="Simulate exposure $ given an assumed fail rate",
)
def simulate(
    run_id: int,
    body: SimulateIn,
    current_user: dict = Depends(require_permission("radv", "read")),
    tenant_id: str = Depends(get_tenant_id),
) -> dict:
    try:
        result = svc.simulate_exposure(
            run_id=run_id,
            tenant_id=tenant_id,
            assumed_fail_rate=body.assumed_fail_rate,
            extrapolation_enforced=body.extrapolation_enforced,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    # Simulation re-projects the audit-run exposure $.  Any cached
    # audit-runs view for this tenant is now stale — evict.
    try:
        invalidate_audit_runs(tenant_id)
    except Exception as exc:
        logger.debug("radv simulate: cache invalidation failed: %s", exc)
    return result


@router.post(
    "/audit-runs/{run_id}/resubmit-rejected",
    summary="Generate an MAO-004 re-submission batch for EDPS-rejected HCCs",
)
def resubmit_rejected(
    run_id: int,
    current_user: dict = Depends(require_permission("radv", "write")),
    tenant_id: str = Depends(get_tenant_id),
) -> dict:
    try:
        return svc.build_resubmission_batch(run_id=run_id, tenant_id=tenant_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.post(
    "/audit-runs/{run_id}/export",
    summary="Package evidence + mark run as exported",
)
def export(
    run_id: int,
    current_user: dict = Depends(require_permission("radv", "write")),
    tenant_id: str = Depends(get_tenant_id),
) -> dict:
    try:
        manifest = svc.export_run(run_id=run_id, tenant_id=tenant_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    _emit(
        "RADV_AUDIT_EXPORTED",
        tenant_id=tenant_id,
        actor_user_id=int(current_user["id"]),
        subject_id=str(run_id),
        payload={
            "record_count": manifest.get("record_count"),
            "evidence_package_url": manifest.get("evidence_package_url"),
        },
    )
    return manifest
