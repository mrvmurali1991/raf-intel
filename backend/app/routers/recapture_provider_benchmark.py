"""
Provider Peer Benchmarking on Recapture Rate — HTTP router.

Endpoints
---------
GET /api/recapture/provider-leaderboard?year=2026
GET /api/recapture/provider/{provider_id}/percentile?year=2026
GET /api/recapture/provider/{provider_id}/trend?years=3

Auth: read-permission on the ``recapture`` resource (matches existing
``recapture_gaps`` router).
"""
# Do NOT add 'from __future__ import annotations' — it breaks FastAPI/Pydantic
# schema generation (ForwardRef errors in /openapi.json).

import logging
from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from app.auth import get_current_user, get_tenant_id, require_permission
from app.services.recapture_provider_benchmark import (
    compute_provider_rates,
    compute_specialty_cohorts,
    provider_decay,
    provider_percentile,
    provider_unrecaptured_top_hccs,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/recapture", tags=["recapture_benchmark"])


# ---------------------------------------------------------------------------
# /api/recapture/provider-leaderboard
# ---------------------------------------------------------------------------


@router.get(
    "/provider-leaderboard",
    summary="Per-provider recapture rate leaderboard with cohort context",
)
def provider_leaderboard(
    year: int = Query(default=None, ge=2020, le=2035, description="Measurement year (default: current)"),
    current_user: dict = Depends(get_current_user),  # noqa: ARG001  (auth side-effect)
    tenant_id: str = Depends(get_tenant_id),
    _perm: None = Depends(require_permission("recapture", "read")),
) -> dict[str, Any]:
    """Ranked list of providers with their recapture metrics, plus per-specialty
    cohort statistics so the frontend can highlight quartile membership.

    Response::

        {
            "year":      2026,
            "providers": [
                {provider_id, provider_name, npi, specialty, panel_size,
                 total_gaps, gaps_open, gaps_closed, recapture_rate,
                 $_recaptured, $_at_risk},
                ...
            ],
            "specialty_cohorts": {
                "<specialty>": {n, median_rate, q1_rate, q3_rate, top_provider},
                ...
            },
            "network": {
                "n":           int,
                "median_rate": float,
                "q1_rate":     float,
                "q3_rate":     float,
            }
        }
    """
    yr = year or date.today().year
    try:
        rows = compute_provider_rates(tenant_id=tenant_id, year=yr)
        cohorts = compute_specialty_cohorts(tenant_id=tenant_id, year=yr)

        # Network-wide quartile summary (active providers with at least 1 gap)
        from app.services.recapture_provider_benchmark import _quartiles  # local import — keeps the public surface tight
        active = [r for r in rows if r["total_gaps"] > 0]
        rates = [r["recapture_rate"] for r in active]
        q1, med, q3 = _quartiles(rates)
        network = {
            "n":           len(active),
            "median_rate": round(med, 4),
            "q1_rate":     round(q1, 4),
            "q3_rate":     round(q3, 4),
        }

        return {
            "year":              yr,
            "providers":         rows,
            "specialty_cohorts": cohorts,
            "network":           network,
        }
    except Exception as exc:
        logger.error("provider_leaderboard year=%s: %s", yr, exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


# ---------------------------------------------------------------------------
# /api/recapture/provider/{id}/percentile
# ---------------------------------------------------------------------------


@router.get(
    "/provider/{provider_id}/percentile",
    summary="Provider percentile rank vs specialty + network",
)
def get_provider_percentile(
    provider_id: int,
    year: int = Query(default=None, ge=2020, le=2035),
    current_user: dict = Depends(get_current_user),  # noqa: ARG001
    tenant_id: str = Depends(get_tenant_id),
    _perm: None = Depends(require_permission("recapture", "read")),
) -> dict[str, Any]:
    """Percentile context for a single provider plus the top 3 unrecaptured
    HCCs (so the side-card can render the "next best action" panel)."""
    yr = year or date.today().year
    try:
        result = provider_percentile(provider_id=provider_id, tenant_id=tenant_id, year=yr)
        result["year"] = yr
        result["top_unrecaptured_hccs"] = provider_unrecaptured_top_hccs(
            provider_id=provider_id, tenant_id=tenant_id, year=yr, limit=3,
        )
        return result
    except Exception as exc:
        logger.error(
            "get_provider_percentile provider=%s year=%s: %s",
            provider_id, yr, exc, exc_info=True,
        )
        raise HTTPException(status_code=500, detail="Internal server error")


# ---------------------------------------------------------------------------
# /api/recapture/provider/{id}/trend
# ---------------------------------------------------------------------------


@router.get(
    "/provider/{provider_id}/trend",
    summary="Provider recapture rate trend (sparkline data)",
)
def get_provider_trend(
    provider_id: int,
    years: int = Query(default=3, ge=1, le=10, description="Lookback window in years"),
    current_user: dict = Depends(get_current_user),  # noqa: ARG001
    tenant_id: str = Depends(get_tenant_id),
    _perm: None = Depends(require_permission("recapture", "read")),
) -> dict[str, Any]:
    """Per-year recapture rate for a single provider (used for sparkline)."""
    try:
        return provider_decay(
            provider_id=provider_id,
            year=date.today().year,
            lookback=int(years),
            tenant_id=tenant_id,
        )
    except Exception as exc:
        logger.error(
            "get_provider_trend provider=%s years=%s: %s",
            provider_id, years, exc, exc_info=True,
        )
        raise HTTPException(status_code=500, detail="Internal server error")
