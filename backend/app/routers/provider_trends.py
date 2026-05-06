"""
Provider Year-over-Year (YoY) Trend router.

Surfaces per-provider RAF / recapture / capture / revenue history so the
frontend can render sparklines next to each provider on the leaderboard
and a stacked detail card in the drawer.

Endpoints
---------
GET /api/providers/{provider_id}/trend           — all metrics (default 4y)
GET /api/providers/{provider_id}/trend?metric=X  — single metric only
GET /api/providers/trend-aggregate?metric=raf    — tenant-wide average

Auth contract matches the existing providers router: read permission on the
``providers`` resource, current user's ``tenant_id`` flows into the service
layer for tenant scoping where applicable.
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from app.auth import get_current_user, require_permission
from app.services.provider_trends import (
    DEFAULT_METRICS,
    DEFAULT_YEARS,
    METRIC_COLUMNS,
    get_provider_trend,
    get_tenant_aggregate_trend,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/providers", tags=["providers", "trends"])


# ---------------------------------------------------------------------------
# /api/providers/trend-aggregate
# (Declared BEFORE the {provider_id}/trend route so FastAPI's static-path
# matcher resolves the literal segment first — otherwise the integer cast
# on `provider_id` swallows the request and 422s.)
# ---------------------------------------------------------------------------

@router.get(
    "/trend-aggregate",
    summary="Tenant-wide average YoY trend for a single metric",
)
def tenant_trend_aggregate(
    metric: str = Query(default="raf", description="One of: raf, recapture, capture, revenue"),
    years: int = Query(default=DEFAULT_YEARS, ge=1, le=10),
    current_user: dict = Depends(get_current_user),
    _perm: None = Depends(require_permission("providers", "read")),
) -> dict[str, Any]:
    """
    Average the chosen metric across all active providers in the caller's
    tenant, one value per measurement year.  Used by the dashboard header
    strip ("Tenant RAF: 1.18 → 1.34 over 4 years").
    """
    if metric not in METRIC_COLUMNS:
        raise HTTPException(
            status_code=400,
            detail=f"metric must be one of {sorted(METRIC_COLUMNS)}",
        )
    try:
        return get_tenant_aggregate_trend(
            metric=metric,
            years=years,
            tenant_id=current_user.get("tenant_id"),
        )
    except Exception as exc:
        logger.error("tenant_trend_aggregate metric=%s: %s", metric, exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))


# ---------------------------------------------------------------------------
# /api/providers/{provider_id}/trend
# ---------------------------------------------------------------------------

@router.get(
    "/{provider_id}/trend",
    summary="Year-over-year trend(s) for one provider",
)
def provider_trend(
    provider_id: int,
    metric: str | None = Query(
        default=None,
        description="Restrict the response to a single metric (raf|recapture|capture|revenue). "
                    "Omit to receive all four.",
    ),
    years: int = Query(default=DEFAULT_YEARS, ge=1, le=10),
    current_user: dict = Depends(get_current_user),
    _perm: None = Depends(require_permission("providers", "read")),
) -> dict[str, Any]:
    """
    Return historical RAF / recapture / capture / revenue series for the
    requested provider.  When the DB has only a single measurement year the
    response still returns 200 with that single point and ``single_year_only:
    true`` so the UI can show a "Need more history" badge instead of an
    empty chart.
    """
    if metric is not None and metric not in METRIC_COLUMNS:
        raise HTTPException(
            status_code=400,
            detail=f"metric must be one of {sorted(METRIC_COLUMNS)}",
        )

    metrics = [metric] if metric else DEFAULT_METRICS
    try:
        # current_user is acknowledged so future tenant scoping (e.g. cross-
        # tenant access guard) has the hook in place; the service itself is
        # provider-scoped via primary key today.
        _ = current_user
        return get_provider_trend(
            provider_id=provider_id,
            metrics=metrics,
            years=years,
        )
    except Exception as exc:
        logger.error(
            "provider_trend provider=%s years=%s: %s",
            provider_id, years, exc, exc_info=True,
        )
        raise HTTPException(status_code=500, detail=str(exc))
