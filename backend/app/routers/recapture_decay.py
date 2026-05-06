"""
Recapture decay-curve & velocity KPI router.

Three read-only endpoints that drive the CFO-facing recapture analytics
pictured on ``/recapture``. Powered by ``app.services.recapture_decay``.

Endpoints
---------
GET /api/recapture/decay-curve?year=YYYY&lookback=N
GET /api/recapture/velocity?year=YYYY
GET /api/recapture/slow-movers?year=YYYY&limit=N

All routes require a valid JWT plus the ``recapture`` read permission, the
same authorisation gate used by ``/api/recapture/gaps``.
"""
# Do NOT add 'from __future__ import annotations' — it breaks FastAPI/Pydantic
# schema generation (ForwardRef errors in /openapi.json).

import logging
from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from app.auth import get_current_user, get_tenant_id, require_permission
from app.services.recapture_decay import (
    get_decay_curve,
    get_top_slow_movers,
    get_velocity_kpis,
)

logger = logging.getLogger(__name__)

# Shared prefix with /api/recapture/gaps; FastAPI tolerates two routers on the
# same prefix as long as the paths don't collide.
router = APIRouter(prefix="/api/recapture", tags=["recapture_decay"])


# ---------------------------------------------------------------------------
# GET /api/recapture/decay-curve
# ---------------------------------------------------------------------------

@router.get(
    "/decay-curve",
    summary="Multi-year recapture decay curve (cohort × month-of-year)",
)
def decay_curve(
    year: int = Query(default=None, ge=2020, le=2030, description="Anchor year (defaults to current calendar year)"),
    lookback: int = Query(default=3, ge=1, le=10, description="Number of cohort years to include"),
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
    _perm: None = Depends(require_permission("recapture", "read")),
) -> dict[str, Any]:
    """Return cohort-grouped monthly closure trajectory.

    Response shape – see ``recapture_decay.get_decay_curve`` docstring.
    """
    anchor = int(year) if year is not None else date.today().year
    try:
        return get_decay_curve(tenant_id=tenant_id, current_year=anchor, lookback_years=lookback)
    except Exception as exc:
        logger.error(
            "decay_curve error tenant=%s year=%s lookback=%s: %s",
            tenant_id, anchor, lookback, exc, exc_info=True,
        )
        raise HTTPException(status_code=500, detail="Internal server error")


# ---------------------------------------------------------------------------
# GET /api/recapture/velocity
# ---------------------------------------------------------------------------

@router.get(
    "/velocity",
    summary="Recapture velocity KPIs for the given measurement year",
)
def velocity(
    year: int = Query(default=None, ge=2020, le=2030, description="Measurement year"),
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
    _perm: None = Depends(require_permission("recapture", "read")),
) -> dict[str, Any]:
    """Return CFO-grade velocity scorecard (avg/median days, YTD $, projected $)."""
    target = int(year) if year is not None else date.today().year
    try:
        return get_velocity_kpis(tenant_id=tenant_id, year=target)
    except Exception as exc:
        logger.error(
            "velocity error tenant=%s year=%s: %s",
            tenant_id, target, exc, exc_info=True,
        )
        raise HTTPException(status_code=500, detail="Internal server error")


# ---------------------------------------------------------------------------
# GET /api/recapture/slow-movers
# ---------------------------------------------------------------------------

@router.get(
    "/slow-movers",
    summary="HCC codes with the slowest closure velocity",
)
def slow_movers(
    year: int = Query(default=None, ge=2020, le=2030, description="Cohort year"),
    limit: int = Query(default=10, ge=1, le=100, description="Max rows returned"),
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
    _perm: None = Depends(require_permission("recapture", "read")),
) -> dict[str, Any]:
    """Return ranked list of HCC codes whose recaptures take the longest."""
    target = int(year) if year is not None else date.today().year
    try:
        rows = get_top_slow_movers(tenant_id=tenant_id, year=target, limit=limit)
    except Exception as exc:
        logger.error(
            "slow_movers error tenant=%s year=%s: %s",
            tenant_id, target, exc, exc_info=True,
        )
        raise HTTPException(status_code=500, detail="Internal server error")
    return {"year": target, "limit": limit, "slow_movers": rows}
