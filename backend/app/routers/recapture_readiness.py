"""
Recapture Readiness router — IMO Health–style problem-list sync score.

Endpoints
---------
GET /api/recapture/gaps/{gap_id}/readiness     – single-gap readiness payload
GET /api/recapture/readiness/bulk?year=2026    – per-gap payload for every open gap
GET /api/recapture/readiness/summary?year=2026 – aggregate-only summary

All endpoints require a valid JWT and ``recapture:read`` permission.

The router is read-only; it never mutates ``recapture_gaps``.  Scoring lives in
``app.services.recapture_readiness_service``.
"""

# Do NOT add 'from __future__ import annotations' — it breaks FastAPI/Pydantic
# schema generation.

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.auth import get_current_user, get_tenant_id, require_permission
from app.services.recapture_readiness_service import (
    bulk_compute_readiness,
    compute_gap_readiness,
    compute_readiness_summary,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/recapture", tags=["recapture_readiness"])


# ---------------------------------------------------------------------------
# Pydantic response models
# ---------------------------------------------------------------------------


class ReadinessComponents(BaseModel):
    problem_list: bool
    problem_list_recent: bool
    recent_encounter: bool
    meat: dict[str, int] = Field(
        default_factory=dict,
        description="Per-MEAT-element presence flags: m/e/a/t each 0 or 1.",
    )


class ReadinessPayload(BaseModel):
    gap_id: int
    patient_id: Any = Field(description="Patient identifier (str or int).")
    hcc_code: str
    icd10_code: str | None = None
    current_year: int
    score: int = Field(ge=0, le=100)
    components: ReadinessComponents
    score_breakdown: dict[str, int]
    defensibility_tier: str = Field(
        description="One of: strong | moderate | weak",
    )
    recommended_actions: list[str]
    problem_list_matches: list[dict[str, Any]] = Field(default_factory=list)
    last_encounter_in_window: str | None = None
    computed_at: str


class ReadinessSummaryResponse(BaseModel):
    year: int
    total_open_gaps: int
    average_score: float
    defensibility_distribution: dict[str, int]
    actionable_gaps: int


class ReadinessBulkResponse(BaseModel):
    year: int
    total: int
    items: list[ReadinessPayload]


# ---------------------------------------------------------------------------
# Static-path routes — declared BEFORE /{gap_id} to avoid path shadowing
# ---------------------------------------------------------------------------


@router.get(
    "/readiness/summary",
    summary="Aggregate recapture readiness summary",
    response_model=ReadinessSummaryResponse,
)
def readiness_summary(
    year: int = Query(default=2026, ge=2020, le=2030),
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
    _perm: None = Depends(require_permission("recapture", "read")),
) -> ReadinessSummaryResponse:
    """Return the dashboard-card-ready aggregate summary."""
    try:
        return ReadinessSummaryResponse(
            **compute_readiness_summary(tenant_id=tenant_id, year=year)
        )
    except Exception as exc:
        logger.error(
            "readiness_summary error tenant=%s year=%s: %s",
            tenant_id, year, exc, exc_info=True,
        )
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get(
    "/readiness/bulk",
    summary="Per-gap readiness for every open gap in the year",
    response_model=ReadinessBulkResponse,
)
def readiness_bulk(
    year: int = Query(default=2026, ge=2020, le=2030),
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
    _perm: None = Depends(require_permission("recapture", "read")),
) -> ReadinessBulkResponse:
    try:
        items = bulk_compute_readiness(tenant_id=tenant_id, year=year)
    except Exception as exc:
        logger.error(
            "readiness_bulk error tenant=%s year=%s: %s",
            tenant_id, year, exc, exc_info=True,
        )
        raise HTTPException(status_code=500, detail="Internal server error")

    return ReadinessBulkResponse(year=year, total=len(items), items=items)


# ---------------------------------------------------------------------------
# Single-gap route — declared LAST so /readiness/* routes resolve first
# ---------------------------------------------------------------------------


@router.get(
    "/gaps/{gap_id}/readiness",
    summary="Recapture readiness score for one gap",
    response_model=ReadinessPayload,
)
def gap_readiness(
    gap_id: int,
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
    _perm: None = Depends(require_permission("recapture", "read")),
) -> ReadinessPayload:
    try:
        payload = compute_gap_readiness(gap_id=gap_id, tenant_id=tenant_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        logger.error(
            "gap_readiness error gap_id=%s tenant=%s: %s",
            gap_id, tenant_id, exc, exc_info=True,
        )
        raise HTTPException(status_code=500, detail="Internal server error")

    return ReadinessPayload(**payload)
