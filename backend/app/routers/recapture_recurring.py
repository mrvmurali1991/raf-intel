"""
Recapture Recurring Gap router.

Endpoints
---------
POST /api/recapture/recurring/detect             - Run detection + flag rows
GET  /api/recapture/recurring                    - List flagged recurring gaps
POST /api/recapture/gaps/{id}/suggest-awv        - READ-ONLY AWV recommendation
POST /api/recapture/gaps/{id}/mark-awv-scheduled - Metadata-only marker

All endpoints require JWT auth.  Read endpoints require permission
("recapture", "read"); write endpoints require ("recapture", "write").
"""
# Do NOT add 'from __future__ import annotations' — it breaks FastAPI/Pydantic
# schema generation.

import logging
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from app.auth import get_current_user, get_tenant_id, require_permission
from app.services.recapture_recurring_service import (
    detect_recurring_gaps,
    get_recurring_gaps,
    mark_awv_scheduled,
    suggest_awv_for_gap,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/recapture", tags=["recapture_gaps"])


# ---------------------------------------------------------------------------
# Pydantic request / response models
# ---------------------------------------------------------------------------


class DetectRecurringRequest(BaseModel):
    current_year: int = Field(
        ...,
        ge=2020,
        le=2030,
        description="The model year being evaluated for recurrence.",
        examples=[2026],
    )
    lookback_years: int = Field(
        default=3,
        ge=1,
        le=10,
        description="How many prior years to scan when looking for recurrence.",
    )


class DetectRecurringResponse(BaseModel):
    model_config = ConfigDict(extra="allow")
    current_year: int
    lookback_years: int
    matches: int
    items: list[dict[str, Any]]


class RecurringListResponse(BaseModel):
    year: int
    total: int
    items: list[dict[str, Any]]


class SuggestAWVResponse(BaseModel):
    model_config = ConfigDict(extra="allow")
    gap_id: int
    patient_id: int
    eligible: bool
    suggested_visit_date: str


class MarkAWVScheduledRequest(BaseModel):
    visit_date: str = Field(..., description="ISO date the AWV is booked for, e.g. '2026-06-15'")
    encounter_id: Optional[str] = Field(
        default=None,
        description="Optional EHR encounter / appointment ID",
    )


class MarkAWVScheduledResponse(BaseModel):
    gap_id: int
    awv_suggested: bool
    awv_visit_date: str
    awv_encounter_id: Optional[str] = None


# ---------------------------------------------------------------------------
# POST /api/recapture/recurring/detect
# ---------------------------------------------------------------------------


@router.post(
    "/recurring/detect",
    summary="Detect recurring (multi-year) recapture gaps and flag them",
    response_model=DetectRecurringResponse,
)
def detect_recurring(
    body: DetectRecurringRequest,
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
    _perm: None = Depends(require_permission("recapture", "write")),
) -> DetectRecurringResponse:
    """
    Find (patient_id, hcc_code) pairs that have been an open recapture gap in
    *current_year* AND in at least one prior year inside the lookback window.
    Sets ``is_recurring=1`` and ``years_recurring=N`` on matching rows.
    """
    try:
        items = detect_recurring_gaps(
            tenant_id=tenant_id,
            current_year=body.current_year,
            lookback_years=body.lookback_years,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except Exception as exc:
        logger.error("detect_recurring error: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")

    return DetectRecurringResponse(
        current_year=body.current_year,
        lookback_years=body.lookback_years,
        matches=len(items),
        items=items,
    )


# ---------------------------------------------------------------------------
# GET /api/recapture/recurring
# ---------------------------------------------------------------------------


@router.get(
    "/recurring",
    summary="List recurring recapture gaps for a year (with patient context)",
    response_model=RecurringListResponse,
)
def list_recurring(
    year: int = 2026,
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
    _perm: None = Depends(require_permission("recapture", "read")),
) -> RecurringListResponse:
    """List recurring recapture gaps for *year* with joined patient context."""
    try:
        items = get_recurring_gaps(tenant_id=tenant_id, year=year)
    except Exception as exc:
        logger.error("list_recurring error: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")

    return RecurringListResponse(year=year, total=len(items), items=items)


# ---------------------------------------------------------------------------
# POST /api/recapture/gaps/{gap_id}/suggest-awv
# ---------------------------------------------------------------------------


@router.post(
    "/gaps/{gap_id}/suggest-awv",
    summary="READ-ONLY AWV recommendation for a recurring gap",
    response_model=SuggestAWVResponse,
)
def suggest_awv(
    gap_id: int,
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
    _perm: None = Depends(require_permission("recapture", "read")),
) -> SuggestAWVResponse:
    """
    Return an AWV recommendation for the patient who owns *gap_id*.  This
    endpoint never schedules an AWV — it only inspects existing eligibility.
    """
    try:
        return SuggestAWVResponse(**suggest_awv_for_gap(gap_id))
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        logger.error("suggest_awv error gap_id=%s: %s", gap_id, exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


# ---------------------------------------------------------------------------
# POST /api/recapture/gaps/{gap_id}/mark-awv-scheduled
# ---------------------------------------------------------------------------


@router.post(
    "/gaps/{gap_id}/mark-awv-scheduled",
    summary="Record that an AWV has been booked for this gap (metadata only)",
    response_model=MarkAWVScheduledResponse,
)
def mark_awv_scheduled_endpoint(
    gap_id: int,
    body: MarkAWVScheduledRequest,
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
    _perm: None = Depends(require_permission("recapture", "write")),
) -> MarkAWVScheduledResponse:
    """
    Mark a recurring gap as 'AWV scheduled' — sets ``awv_suggested=1`` and
    stores the visit date + optional EHR encounter ID.  Does NOT call any AWV
    scheduling endpoint.
    """
    try:
        result = mark_awv_scheduled(
            gap_id=gap_id,
            visit_date=body.visit_date,
            encounter_id=body.encounter_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        logger.error("mark_awv_scheduled error: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")

    return MarkAWVScheduledResponse(**result)
