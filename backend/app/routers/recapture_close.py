"""
Recapture Close router — smart-close, bulk-close, reopen, attribution backfill.

Lives alongside the existing ``recapture_gaps`` router and intentionally does
NOT modify the legacy ``PUT /api/recapture/gaps/{id}/close`` endpoint.

Endpoints
---------
POST  /api/recapture/orphan-gaps/attribute     – backfill provider_npi
POST  /api/recapture/gaps/{gap_id}/smart-close – close with evidence + MEAT
POST  /api/recapture/gaps/bulk-close           – close many with shared evidence
POST  /api/recapture/gaps/{gap_id}/reopen      – reopen a recaptured gap
GET   /api/recapture/close-history             – recent closures timeline
"""
# Do NOT add 'from __future__ import annotations' — breaks FastAPI/Pydantic schema gen.

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.auth import get_current_user, get_tenant_id, require_permission
from app.services.recapture_close_service import (
    attribute_orphan_gaps,
    bulk_close,
    get_close_history,
    reopen_gap,
    smart_close,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/recapture", tags=["recapture_close"])


# ---------------------------------------------------------------------------
# Request / response schemas
# ---------------------------------------------------------------------------


class AttributeOrphansResponse(BaseModel):
    checked: int
    updated: int
    still_orphan: int


class SmartCloseRequest(BaseModel):
    evidence_phrase: str = Field(
        ...,
        min_length=1,
        max_length=4000,
        description="Free-text quote from the chart that supports recapture",
    )
    meat_element: str | None = Field(
        default=None,
        description="One of M (Monitor), E (Evaluate), A (Assess), T (Treat)",
    )
    write_to_raf_hcc: bool = Field(
        default=True,
        description="When true, INSERT IGNORE the HCC into raf_patient_hcc for the current measurement year",
    )
    measurement_year: int | None = Field(
        default=None,
        ge=2020,
        le=2030,
        description="Override the measurement year (defaults to current calendar year)",
    )


class SmartCloseResponse(BaseModel):
    gap_id: int
    status: str
    raf_hcc_inserted: bool
    raf_hcc_already_present: bool
    measurement_year: int


class BulkCloseRequest(BaseModel):
    gap_ids: list[int] = Field(..., min_length=1, max_length=500)
    evidence_phrase: str = Field(..., min_length=1, max_length=4000)
    meat_element: str | None = None
    write_to_raf_hcc: bool = True
    measurement_year: int | None = Field(default=None, ge=2020, le=2030)


class BulkCloseResponse(BaseModel):
    closed: int
    raf_hcc_inserted: int
    errors: list[dict[str, Any]]
    results: list[dict[str, Any]]


class ReopenRequest(BaseModel):
    reason: str = Field(..., min_length=1, max_length=2000)


class ReopenResponse(BaseModel):
    gap_id: int
    status: str


class CloseHistoryResponse(BaseModel):
    items: list[dict[str, Any]]
    count: int


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


def _closer_identity(current_user: dict) -> str:
    """Pick a stable string identifier for the user closing a gap."""
    return (
        current_user.get("email")
        or current_user.get("username")
        or str(current_user.get("id") or "system")
    )


@router.post(
    "/orphan-gaps/attribute",
    summary="Attribute orphan recapture gaps to a provider via the patient panel",
    response_model=AttributeOrphansResponse,
)
def attribute_orphans(
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
    _perm: None = Depends(require_permission("recapture", "write")),
) -> AttributeOrphansResponse:
    """Backfill ``provider_npi`` on every recapture_gaps row that is missing one."""
    try:
        result = attribute_orphan_gaps(tenant_id=tenant_id)
    except Exception as exc:
        logger.error(
            "attribute_orphans error tenant=%s: %s", tenant_id, exc, exc_info=True,
        )
        raise HTTPException(status_code=500, detail="Internal server error")
    return AttributeOrphansResponse(**result)


@router.post(
    "/gaps/{gap_id}/smart-close",
    summary="Close a recapture gap with documentation evidence + MEAT element",
    response_model=SmartCloseResponse,
)
def smart_close_endpoint(
    gap_id: int,
    body: SmartCloseRequest,
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
    _perm: None = Depends(require_permission("recapture", "write")),
) -> SmartCloseResponse:
    closer = _closer_identity(current_user)
    try:
        result = smart_close(
            gap_id=gap_id,
            closed_by=closer,
            evidence_phrase=body.evidence_phrase,
            meat_element=body.meat_element,
            write_to_raf_hcc=body.write_to_raf_hcc,
            tenant_id=tenant_id,
            measurement_year=body.measurement_year,
        )
    except ValueError as exc:
        # 404 for missing gap, 400 for invalid input
        msg = str(exc)
        if "not found" in msg.lower():
            raise HTTPException(status_code=404, detail=msg)
        raise HTTPException(status_code=400, detail=msg)
    except Exception as exc:
        logger.error(
            "smart_close error gap_id=%s tenant=%s: %s",
            gap_id, tenant_id, exc, exc_info=True,
        )
        raise HTTPException(status_code=500, detail="Internal server error")
    return SmartCloseResponse(**result)


@router.post(
    "/gaps/bulk-close",
    summary="Bulk-close recapture gaps with shared evidence",
    response_model=BulkCloseResponse,
)
def bulk_close_endpoint(
    body: BulkCloseRequest,
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
    _perm: None = Depends(require_permission("recapture", "write")),
) -> BulkCloseResponse:
    closer = _closer_identity(current_user)
    try:
        result = bulk_close(
            gap_ids=body.gap_ids,
            closed_by=closer,
            evidence_phrase=body.evidence_phrase,
            meat_element=body.meat_element,
            write_to_raf_hcc=body.write_to_raf_hcc,
            tenant_id=tenant_id,
            measurement_year=body.measurement_year,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        logger.error(
            "bulk_close error tenant=%s: %s", tenant_id, exc, exc_info=True,
        )
        raise HTTPException(status_code=500, detail="Internal server error")
    return BulkCloseResponse(**result)


@router.post(
    "/gaps/{gap_id}/reopen",
    summary="Reopen a previously recaptured gap",
    response_model=ReopenResponse,
)
def reopen_endpoint(
    gap_id: int,
    body: ReopenRequest,
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
    _perm: None = Depends(require_permission("recapture", "write")),
) -> ReopenResponse:
    reopener = _closer_identity(current_user)
    try:
        result = reopen_gap(
            gap_id=gap_id,
            reopened_by=reopener,
            reason=body.reason,
            tenant_id=tenant_id,
        )
    except ValueError as exc:
        msg = str(exc)
        if "not found" in msg.lower():
            raise HTTPException(status_code=404, detail=msg)
        raise HTTPException(status_code=400, detail=msg)
    except Exception as exc:
        logger.error(
            "reopen error gap_id=%s tenant=%s: %s",
            gap_id, tenant_id, exc, exc_info=True,
        )
        raise HTTPException(status_code=500, detail="Internal server error")
    return ReopenResponse(**result)


@router.get(
    "/close-history",
    summary="Recent recapture-gap closures with evidence",
    response_model=CloseHistoryResponse,
)
def close_history_endpoint(
    year: int | None = Query(default=None, ge=2020, le=2030),
    limit: int = Query(default=50, ge=1, le=500),
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
    _perm: None = Depends(require_permission("recapture", "read")),
) -> CloseHistoryResponse:
    try:
        items = get_close_history(tenant_id=tenant_id, year=year, limit=limit)
    except Exception as exc:
        logger.error(
            "close_history error tenant=%s: %s", tenant_id, exc, exc_info=True,
        )
        raise HTTPException(status_code=500, detail="Internal server error")
    return CloseHistoryResponse(items=items, count=len(items))
