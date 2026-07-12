"""
Recapture MEAT Audit router — dual-coder workflow + RADV PDF export.

Endpoints
---------
POST   /api/recapture/gaps/{gap_id}/evidence       — record primary evidence
POST   /api/recapture/gaps/{gap_id}/submit-review  — submit for dual review
POST   /api/recapture/gaps/{gap_id}/approve        — secondary coder approve
POST   /api/recapture/gaps/{gap_id}/reject         — secondary coder reject
GET    /api/recapture/review-queue                 — list gaps in workflow state
GET    /api/recapture/audit-readiness              — tenant readiness score
GET    /api/recapture/audit-report.pdf             — RADV defense PDF

All endpoints require a valid JWT.  Coder identity is taken from
``current_user["id"]`` server-side so clients cannot spoof ``coder_id``.

NOTE: the prefix overlaps with ``recapture_gaps.router`` (``/api/recapture``)
but the paths are disjoint so registration order does not matter.
"""

# Do NOT add 'from __future__ import annotations' — it breaks FastAPI/Pydantic
# schema generation (ForwardRef errors in /openapi.json).

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel, Field

from app.auth import get_current_user, get_tenant_id, require_permission
from app.services.meat_audit_service import (
    approve_review,
    compute_audit_readiness,
    get_review_queue,
    record_primary_evidence,
    reject_review,
    submit_for_review,
)
from app.services.recapture_audit_pdf import build_audit_pdf

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/recapture", tags=["recapture_audit"])


# ---------------------------------------------------------------------------
# Pydantic request / response models
# ---------------------------------------------------------------------------


class EvidenceRequest(BaseModel):
    phrase: str = Field(..., min_length=1, max_length=4000,
                        description="Quoted MEAT phrase from the chart note.")
    meat_element: str = Field(..., description="One of M / E / A / T / MULTI.")
    source_url: str | None = Field(default=None, max_length=500,
                                   description="Optional deep-link or FHIR ref.")
    notes: str | None = Field(default=None, max_length=4000)


class RejectRequest(BaseModel):
    reason: str = Field(..., min_length=1, max_length=4000)


class ApproveRequest(BaseModel):
    notes: str | None = Field(default=None, max_length=4000)


class GapAuditResponse(BaseModel):
    gap: dict[str, Any]


class ReviewQueueResponse(BaseModel):
    status: str
    total: int
    items: list[dict[str, Any]]


class AuditReadinessResponse(BaseModel):
    total_gaps: int
    with_evidence: int
    dual_signed: int
    audit_ready_pct: float
    missing_meat: list[dict[str, Any]]
    inter_rater_reliability: dict[str, Any] | None = None


# ---------------------------------------------------------------------------
# Static-path routes — declared BEFORE /{gap_id} routes to avoid shadowing.
# ---------------------------------------------------------------------------


@router.get(
    "/review-queue",
    response_model=ReviewQueueResponse,
    summary="List gaps in the dual-coder review workflow",
)
def review_queue(
    status: str = Query(default="review_pending",
                        description="audit_status filter: draft | primary_coded | review_pending | approved | rejected"),
    limit: int = Query(default=100, ge=1, le=500),
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
    _perm: None = Depends(require_permission("recapture", "read")),
) -> ReviewQueueResponse:
    try:
        items = get_review_queue(tenant_id=tenant_id, status=status, limit=limit)
    except Exception as exc:
        logger.error("review_queue error tenant=%s: %s", tenant_id, exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")
    return ReviewQueueResponse(status=status, total=len(items), items=items)


@router.get(
    "/audit-readiness",
    response_model=AuditReadinessResponse,
    summary="Audit-readiness score for the tenant",
)
def audit_readiness(
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
    _perm: None = Depends(require_permission("recapture", "read")),
) -> AuditReadinessResponse:
    try:
        return AuditReadinessResponse(**compute_audit_readiness(tenant_id=tenant_id))
    except Exception as exc:
        logger.error("audit_readiness error tenant=%s: %s", tenant_id, exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get(
    "/audit-report.pdf",
    summary="Download the RADV audit defense PDF",
    responses={
        200: {"content": {"application/pdf": {}}, "description": "PDF bytes"},
        500: {"description": "Render failure"},
    },
)
def audit_report_pdf(
    year: int | None = Query(default=None, ge=2020, le=2030,
                             description="Optional measurement-year filter."),
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
    _perm: None = Depends(require_permission("recapture", "read")),
) -> Response:
    try:
        pdf_bytes = build_audit_pdf(tenant_id=tenant_id, year=year)
    except RuntimeError as exc:
        # WeasyPrint native deps missing — surface a clean 500 with the
        # reason so the operator can fix the deployment.
        logger.error("audit_report_pdf weasyprint missing: %s", exc)
        raise HTTPException(status_code=500, detail="Internal server error")
    except Exception as exc:
        logger.error("audit_report_pdf error tenant=%s: %s", tenant_id, exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")

    suffix = f"-{year}" if year else ""
    filename = f"radv-audit-tenant-{tenant_id}{suffix}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ---------------------------------------------------------------------------
# Per-gap workflow routes
# ---------------------------------------------------------------------------


@router.post(
    "/gaps/{gap_id}/evidence",
    response_model=GapAuditResponse,
    summary="Record primary MEAT evidence for a gap",
)
def post_evidence(
    gap_id: int,
    body: EvidenceRequest,
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
    _perm: None = Depends(require_permission("recapture", "write")),
) -> GapAuditResponse:
    try:
        gap = record_primary_evidence(
            gap_id=gap_id,
            coder_id=int(current_user["id"]),
            phrase=body.phrase,
            meat_element=body.meat_element,
            source_url=body.source_url,
            notes=body.notes,
            tenant_id=tenant_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Internal server error")
    except Exception as exc:
        logger.error(
            "record_primary_evidence error gap_id=%s tenant=%s: %s",
            gap_id, tenant_id, exc, exc_info=True,
        )
        raise HTTPException(status_code=500, detail="Internal server error")
    return GapAuditResponse(gap=gap)


@router.post(
    "/gaps/{gap_id}/submit-review",
    response_model=GapAuditResponse,
    summary="Submit a primary-coded gap for dual-coder review",
)
def post_submit_review(
    gap_id: int,
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
    _perm: None = Depends(require_permission("recapture", "write")),
) -> GapAuditResponse:
    try:
        gap = submit_for_review(
            gap_id=gap_id,
            coder_id=int(current_user["id"]),
            tenant_id=tenant_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Internal server error")
    except Exception as exc:
        logger.error(
            "submit_for_review error gap_id=%s tenant=%s: %s",
            gap_id, tenant_id, exc, exc_info=True,
        )
        raise HTTPException(status_code=500, detail="Internal server error")
    return GapAuditResponse(gap=gap)


@router.post(
    "/gaps/{gap_id}/approve",
    response_model=GapAuditResponse,
    summary="Secondary-coder approve a review_pending gap",
)
def post_approve(
    gap_id: int,
    body: ApproveRequest = ApproveRequest(),
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
    _perm: None = Depends(require_permission("recapture", "write")),
) -> GapAuditResponse:
    try:
        gap = approve_review(
            gap_id=gap_id,
            secondary_coder_id=int(current_user["id"]),
            notes=body.notes,
            tenant_id=tenant_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Internal server error")
    except Exception as exc:
        logger.error(
            "approve_review error gap_id=%s tenant=%s: %s",
            gap_id, tenant_id, exc, exc_info=True,
        )
        raise HTTPException(status_code=500, detail="Internal server error")
    return GapAuditResponse(gap=gap)


@router.post(
    "/gaps/{gap_id}/reject",
    response_model=GapAuditResponse,
    summary="Secondary-coder reject a review_pending gap",
)
def post_reject(
    gap_id: int,
    body: RejectRequest,
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
    _perm: None = Depends(require_permission("recapture", "write")),
) -> GapAuditResponse:
    try:
        gap = reject_review(
            gap_id=gap_id,
            secondary_coder_id=int(current_user["id"]),
            reason=body.reason,
            tenant_id=tenant_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Internal server error")
    except Exception as exc:
        logger.error(
            "reject_review error gap_id=%s tenant=%s: %s",
            gap_id, tenant_id, exc, exc_info=True,
        )
        raise HTTPException(status_code=500, detail="Internal server error")
    return GapAuditResponse(gap=gap)
