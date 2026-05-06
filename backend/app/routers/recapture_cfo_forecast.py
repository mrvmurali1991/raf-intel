"""
Recapture CFO Forecast router.

Executive ($) view of the recapture program — designed to mirror what Pareto
and Cotiviti expose to CFO / VP Finance personas:

    GET  /api/recapture/cfo/summary?year=2026
    GET  /api/recapture/cfo/yoy?years=3
    GET  /api/recapture/cfo/export?year=2026&format=csv  (or json)

All endpoints require an authenticated user with read access to the
``recapture`` permission resource.
"""
# Do NOT add 'from __future__ import annotations' — it breaks FastAPI/Pydantic
# schema generation (ForwardRef errors in /openapi.json).

import logging
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.auth import get_current_user, get_tenant_id, require_permission
from app.services.recapture_cfo_forecast import (
    export_for_bi,
    get_executive_summary,
    get_year_over_year_trend,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/recapture/cfo", tags=["recapture_gaps"])


# ---------------------------------------------------------------------------
# Pydantic response models
# ---------------------------------------------------------------------------


class MonthBreakdown(BaseModel):
    month: int
    opened: int
    closed: int
    recaptured_dollars: float
    remaining_dollars: float


class QuarterBreakdown(BaseModel):
    quarter: str
    opened: int
    closed: int
    recaptured_dollars: float
    remaining_dollars: float


class TopCondition(BaseModel):
    hcc_code: str
    description: str
    count: int
    dollars: float


class TopProvider(BaseModel):
    provider_npi: str
    recaptured_count: int
    recaptured_dollars: float


class ExecutiveSummary(BaseModel):
    year: int
    generated_at: str
    total_gaps_open: int
    total_dollars_at_risk: float
    ytd_dollars_recaptured: float
    ytd_closures: int
    ytd_velocity_per_day: float
    budget_dollars: float
    forecast_ye_dollars: float
    variance_to_budget: float
    month_breakdown: list[MonthBreakdown]
    quarter_breakdown: list[QuarterBreakdown]
    top_3_recaptured_conditions: list[TopCondition]
    top_3_at_risk_conditions: list[TopCondition]
    top_3_provider_contributors: list[TopProvider]
    audit_risk_flag: bool
    audit_dual_coded_pct: float
    totals: dict[str, int]
    days_elapsed: int
    days_in_year: int


class YoyRow(BaseModel):
    year: int
    opened: int
    closed: int
    recaptured_dollars: float
    at_risk_dollars: float
    closure_rate_pct: float


class YoyResponse(BaseModel):
    tenant_id: str
    years_back: int
    series: list[YoyRow]


# ---------------------------------------------------------------------------
# /summary
# ---------------------------------------------------------------------------


@router.get(
    "/summary",
    summary="CFO executive summary for a measurement year",
    response_model=ExecutiveSummary,
)
def cfo_summary(
    year: int = Query(
        default=datetime.now(timezone.utc).year,
        ge=2020,
        le=2035,
        description="Measurement year to summarise.",
    ),
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
    _perm: None = Depends(require_permission("recapture", "read")),
) -> Any:
    """Return the full CFO dashboard payload for *year*."""
    try:
        return get_executive_summary(tenant_id=tenant_id, year=year)
    except Exception as exc:  # pragma: no cover — logged before re-raise
        logger.error(
            "cfo_summary error tenant=%s year=%s: %s",
            tenant_id, year, exc, exc_info=True,
        )
        raise HTTPException(status_code=500, detail="Internal server error")


# ---------------------------------------------------------------------------
# /yoy
# ---------------------------------------------------------------------------


@router.get(
    "/yoy",
    summary="Year-over-year recapture trend",
    response_model=YoyResponse,
)
def cfo_yoy(
    years: int = Query(default=3, ge=1, le=10, description="How many trailing years to include."),
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
    _perm: None = Depends(require_permission("recapture", "read")),
) -> Any:
    """Return per-year opened/closed/$ rolled up across the trailing window."""
    try:
        return get_year_over_year_trend(tenant_id=tenant_id, years_back=years)
    except Exception as exc:  # pragma: no cover
        logger.error(
            "cfo_yoy error tenant=%s years=%s: %s",
            tenant_id, years, exc, exc_info=True,
        )
        raise HTTPException(status_code=500, detail="Internal server error")


# ---------------------------------------------------------------------------
# /export
# ---------------------------------------------------------------------------


@router.get(
    "/export",
    summary="Flat CSV/JSON export for BI tools (Looker, Power BI, Tableau)",
)
def cfo_export(
    year: int = Query(
        default=datetime.now(timezone.utc).year,
        ge=2020,
        le=2035,
    ),
    format: str = Query(default="csv", pattern="^(csv|json)$"),
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
    _perm: None = Depends(require_permission("recapture", "read")),
):
    """Stream a tabular row-per-month export suitable for BI ingestion."""
    try:
        content, mime = export_for_bi(tenant_id=tenant_id, year=year, format=format)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:  # pragma: no cover
        logger.error(
            "cfo_export error tenant=%s year=%s fmt=%s: %s",
            tenant_id, year, format, exc, exc_info=True,
        )
        raise HTTPException(status_code=500, detail="Internal server error")

    ext = "csv" if format == "csv" else "json"
    filename = f"recapture_cfo_{year}.{ext}"
    return StreamingResponse(
        iter([content]),
        media_type=mime,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
