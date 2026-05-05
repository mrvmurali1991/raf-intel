"""
Disputes & Appeals router.

REST surface
------------
POST  /api/disputes                          create a new dispute
GET   /api/disputes                          list (filter by status / assignee / tenant)
GET   /api/disputes/{id}                     full dispute (evidence + appeals)
PUT   /api/disputes/{id}/assign              reassign owner
POST  /api/disputes/{id}/gather-evidence     auto-pull MEAT evidence
POST  /api/disputes/{id}/draft-appeal        Gemini-drafted appeal letter
POST  /api/disputes/{id}/submit-appeal       persist a submitted appeal
POST  /api/appeals/{appeal_id}/record-outcome record the appeal outcome
GET   /api/disputes/metrics                  win-rate / $ / cycle time

All workflow endpoints accept an optional ?tenant_id= query parameter so the
existing RBAC / tenant scoping at the router_registry level can pass it through.
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.services import dispute_service as svc

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["disputes"])


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class CreateDisputePayload(BaseModel):
    patient_id: int
    hcc_code: int
    icd10: str
    disputed_by: str = Field(..., description="cms | payer | internal_audit")
    denial_received_at: str = Field(..., description="ISO datetime")
    financial_impact: float = 0.0

    tenant_id: int | None = None
    measurement_year: int | None = None
    original_submission_id: str | None = None
    payer_name: str | None = None
    denial_reason_code: str | None = None
    denial_reason_text: str | None = None
    assigned_to: str | None = None
    notes: str | None = None
    created_by: str | None = None


class AssignPayload(BaseModel):
    user_id: str


class DraftAppealPayload(BaseModel):
    appeal_round: int = 1


class SubmitAppealPayload(BaseModel):
    appeal_round: int = 1
    appeal_letter_text: str
    appeal_letter_model: str | None = None
    evidence_attached_json: list[dict[str, Any]] | dict[str, Any] | None = None
    submitted_by: str | None = None
    submitted_at: str | None = None


class RecordOutcomePayload(BaseModel):
    outcome: str = Field(..., description="overturned | upheld | partial | withdrawn | pending")
    recovered_amount: float = 0.0
    response_received_at: str | None = None
    outcome_notes: str | None = None


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.post("/disputes", summary="Create a new dispute")
def create_dispute_endpoint(payload: CreateDisputePayload) -> dict[str, Any]:
    try:
        return svc.create_dispute(payload.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/disputes", summary="List disputes (filterable)")
def list_disputes_endpoint(
    status: str | None = Query(None, description="open|in_review|appealing|won|lost|abandoned"),
    assigned_to: str | None = Query(None),
    tenant_id: int | None = Query(None),
    patient_id: int | None = Query(None),
    limit: int = Query(200, ge=1, le=1000),
) -> dict[str, Any]:
    try:
        rows = svc.list_disputes(
            status=status, assigned_to=assigned_to,
            tenant_id=tenant_id, patient_id=patient_id, limit=limit,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"count": len(rows), "disputes": rows}


@router.get("/disputes/metrics", summary="Win-rate, $ recovered, cycle time")
def metrics_endpoint(tenant_id: int | None = Query(None)) -> dict[str, Any]:
    return svc.get_metrics(tenant_id=tenant_id)


@router.get("/disputes/{dispute_id}", summary="Get dispute detail")
def get_dispute_endpoint(dispute_id: int) -> dict[str, Any]:
    try:
        return svc.get_dispute(dispute_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.put("/disputes/{dispute_id}/assign", summary="Assign dispute to a user")
def assign_dispute_endpoint(dispute_id: int, payload: AssignPayload) -> dict[str, Any]:
    try:
        return svc.assign_dispute(dispute_id, payload.user_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/disputes/{dispute_id}/gather-evidence", summary="Auto-pull MEAT evidence")
def gather_evidence_endpoint(dispute_id: int) -> dict[str, Any]:
    try:
        evidence = svc.gather_evidence(dispute_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return {"dispute_id": dispute_id, "count": len(evidence), "evidence": evidence}


@router.post("/disputes/{dispute_id}/draft-appeal", summary="Generate appeal letter draft")
def draft_appeal_endpoint(dispute_id: int, payload: DraftAppealPayload | None = None) -> dict[str, Any]:
    try:
        appeal_round = (payload.appeal_round if payload else 1)
        return svc.compose_appeal_draft(dispute_id, appeal_round=appeal_round)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/disputes/{dispute_id}/submit-appeal", summary="Persist a submitted appeal")
def submit_appeal_endpoint(dispute_id: int, payload: SubmitAppealPayload) -> dict[str, Any]:
    try:
        return svc.submit_appeal(dispute_id, payload.model_dump(exclude_none=False))
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/appeals/{appeal_id}/record-outcome", summary="Record the appeal outcome")
def record_outcome_endpoint(appeal_id: int, payload: RecordOutcomePayload) -> dict[str, Any]:
    try:
        return svc.record_outcome(
            appeal_id=appeal_id,
            outcome=payload.outcome,
            recovered_amount=payload.recovered_amount,
            response_received_at=payload.response_received_at,
            outcome_notes=payload.outcome_notes,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
