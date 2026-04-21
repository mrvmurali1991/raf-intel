"""
Recapture Gap Analysis router.

HCC recapture gaps are conditions documented in a prior measurement year that
have NOT yet been re-documented in the current year.  Each open gap represents
revenue at risk because CMS will not pay for that HCC unless it is supported by
a face-to-face encounter in the current payment year.

Endpoints
---------
GET    /api/recapture/gaps              – list gaps with optional filters
GET    /api/recapture/gaps/summary      – aggregate stats for the tenant
POST   /api/recapture/gaps/detect       – trigger gap detection engine
PUT    /api/recapture/gaps/{gap_id}/close – close / recapture a gap

All endpoints require a valid JWT.  Write operations require "recapture" write
permission; read operations require "recapture" read permission.
"""
# Do NOT add 'from __future__ import annotations' — it breaks FastAPI/Pydantic
# schema generation (ForwardRef errors in /openapi.json).

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.auth import get_current_user, get_tenant_id, require_permission
from app.services.recapture_gap_service import (
    close_gap,
    detect_gaps,
    get_gap_summary,
    get_patient_gaps,
    list_gaps,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/recapture", tags=["recapture_gaps"])


# ---------------------------------------------------------------------------
# Pydantic request / response models
# ---------------------------------------------------------------------------


class DetectGapsRequest(BaseModel):
    """Payload for triggering gap detection."""

    measurement_year: int = Field(
        ...,
        ge=2020,
        le=2030,
        description="Current measurement year. Prior year is derived as measurement_year - 1.",
        examples=[2026],
    )


class GapSummaryResponse(BaseModel):
    total_open_gaps: int
    total_raf_at_risk: float
    gaps_by_hcc: list[dict[str, Any]]
    top_patients_by_impact: list[dict[str, Any]]


class DetectGapsResponse(BaseModel):
    new_gaps: int
    total_open: int
    prior_year: int
    current_year: int


class GapListResponse(BaseModel):
    total: int
    limit: int
    offset: int
    gaps: list[dict[str, Any]]


class CloseGapResponse(BaseModel):
    gap_id: int
    status: str
    detail: str


# ---------------------------------------------------------------------------
# Static-path routes — declared BEFORE /{gap_id} to avoid path shadowing
# ---------------------------------------------------------------------------


@router.get("/gaps/summary", summary="Aggregate recapture gap statistics", response_model=GapSummaryResponse)
def gap_summary(
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
    _perm: None = Depends(require_permission("recapture", "read")),
) -> GapSummaryResponse:
    """
    Return tenant-level aggregate statistics for recapture gaps.

    Response::

        {
            "total_open_gaps": 42,
            "total_raf_at_risk": 126000.00,
            "gaps_by_hcc": [
                {"hcc_code": "85", "description": "Congestive Heart Failure",
                 "count": 8, "raf_at_risk": 24000.00},
                ...
            ],
            "top_patients_by_impact": [
                {"patient_id": 101, "patient_name": "Jane Doe",
                 "open_gaps": 3, "raf_at_risk": 9000.00},
                ...
            ]
        }
    """
    try:
        return GapSummaryResponse(**get_gap_summary(tenant_id=tenant_id))
    except Exception as exc:
        logger.error("gap_summary error tenant=%s: %s", tenant_id, exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post(
    "/gaps/detect",
    summary="Trigger recapture gap detection",
    status_code=200,
    response_model=DetectGapsResponse,
)
def trigger_detect(
    body: DetectGapsRequest,
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
    _perm: None = Depends(require_permission("recapture", "write")),
) -> DetectGapsResponse:
    """
    Run the recapture gap detection engine for the given measurement year.

    Compares ``raf_patient_hcc`` rows for ``(measurement_year - 1)`` against
    ``measurement_year`` per patient and inserts new ``recapture_gaps`` rows for
    any HCC present in the prior year but absent in the current year.

    The operation is idempotent — duplicate rows are silently skipped via
    ``INSERT IGNORE`` on the unique constraint.

    Body::

        { "measurement_year": 2026 }

    Response::

        {
            "new_gaps": 12,
            "total_open": 42,
            "prior_year": 2025,
            "current_year": 2026
        }
    """
    try:
        return DetectGapsResponse(**detect_gaps(
            tenant_id=tenant_id,
            measurement_year=body.measurement_year,
        ))
    except Exception as exc:
        logger.error(
            "detect_gaps error tenant=%s year=%s: %s",
            tenant_id,
            body.measurement_year,
            exc,
            exc_info=True,
        )
        raise HTTPException(status_code=500, detail="Internal server error")


# ---------------------------------------------------------------------------
# Collection route — GET /api/recapture/gaps
# ---------------------------------------------------------------------------


@router.get("/gaps", summary="List recapture gaps", response_model=GapListResponse)
def list_recapture_gaps(
    patient_id: int | None = Query(
        default=None,
        description="Filter gaps to a single patient (returns all statuses)",
    ),
    status: str | None = Query(
        default=None,
        description="Filter by status: open | recaptured | dismissed",
    ),
    hcc_code: str | None = Query(
        default=None,
        description="Filter by HCC code (exact match, e.g. '85')",
    ),
    limit: int = Query(default=50, ge=1, le=500, description="Page size"),
    offset: int = Query(default=0, ge=0, description="Rows to skip"),
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
    _perm: None = Depends(require_permission("recapture", "read")),
) -> GapListResponse:
    """
    Return a paginated list of recapture gaps for the authenticated tenant.

    When ``patient_id`` is supplied the response includes all gap statuses for
    that patient (open + recaptured + dismissed) so the UI can show the full
    recapture history.

    When ``patient_id`` is **not** supplied, only ``status``-filtered results
    are returned (defaults to all statuses).
    """
    try:
        if patient_id is not None:
            gaps = get_patient_gaps(patient_id=patient_id, tenant_id=tenant_id)
            # Optionally post-filter by hcc_code
            if hcc_code is not None:
                gaps = [g for g in gaps if str(g.get("hcc_code", "")) == hcc_code]
            # Manual pagination for the patient-scoped path
            total = len(gaps)
            gaps = gaps[offset : offset + limit]
        else:
            all_gaps = list_gaps(
                tenant_id=tenant_id,
                status=status,
                limit=limit + offset,  # over-fetch so we can slice
                offset=0,
            )
            # Post-filter by hcc_code if requested
            if hcc_code is not None:
                all_gaps = [g for g in all_gaps if str(g.get("hcc_code", "")) == hcc_code]
            total = len(all_gaps)
            gaps = all_gaps[offset : offset + limit]
    except Exception as exc:
        logger.error(
            "list_recapture_gaps error tenant=%s: %s", tenant_id, exc, exc_info=True
        )
        raise HTTPException(status_code=500, detail="Internal server error")

    return GapListResponse(
        total=total,
        limit=limit,
        offset=offset,
        gaps=gaps,
    )


# ---------------------------------------------------------------------------
# Instance route — PUT /api/recapture/gaps/{gap_id}/close
# ---------------------------------------------------------------------------


@router.put("/gaps/{gap_id}/close", summary="Close (recapture) a gap", response_model=CloseGapResponse)
def close_recapture_gap(
    gap_id: int,
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
    _perm: None = Depends(require_permission("recapture", "write")),
) -> CloseGapResponse:
    """
    Mark a recapture gap as closed / recaptured.

    This should be called when the HCC has been re-documented in the current
    measurement year (e.g. after a qualifying encounter is added to the chart).

    Returns the updated gap status on success.
    """
    try:
        close_gap(gap_id=gap_id, tenant_id=tenant_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        logger.error(
            "close_gap error gap_id=%d tenant=%s: %s",
            gap_id,
            tenant_id,
            exc,
            exc_info=True,
        )
        raise HTTPException(status_code=500, detail="Internal server error")

    return CloseGapResponse(gap_id=gap_id, status="recaptured", detail="Gap closed successfully")
