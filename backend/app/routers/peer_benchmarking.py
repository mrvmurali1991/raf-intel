"""
Peer benchmarking router.

Surfaces percentile-rank-vs-cohort data for the provider leaderboard ribbon
and the specialty benchmarking dashboard tab.

Endpoints
---------
GET /api/providers/{provider_id}/peer-percentile   – single-provider percentiles
GET /api/providers/specialty-benchmarks            – every specialty cohort

The single-provider endpoint shares the `/api/providers` prefix with the
existing providers router.  Because the existing router declares
``provider_id: int`` on its dynamic paths, the literal sub-path
``/specialty-benchmarks`` does not collide with ``/{provider_id}`` route
matching — FastAPI / Starlette will only match the int-typed segment when
the URL component is parseable as int.
"""
from __future__ import annotations

import logging
from datetime import date
from typing import Any

from fastapi import Depends, APIRouter, HTTPException, Query

from app.auth import get_current_user
from app.services.peer_benchmarking import (
    compute_percentiles,
    specialty_benchmarks,
    specialty_cohort_summary,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/providers", tags=["providers", "benchmarking"], dependencies=[Depends(get_current_user)])


# ---------------------------------------------------------------------------
# GET /api/providers/specialty-benchmarks
# ---------------------------------------------------------------------------

@router.get(
    "/specialty-benchmarks",
    summary="Per-specialty cohort benchmarks for every provider",
)
def get_specialty_benchmarks(
    year: int = Query(default=None, description="Measurement year (defaults to current)"),
    specialty: str | None = Query(
        default=None,
        description="Optional: only return this specialty cohort",
    ),
) -> dict[str, Any]:
    """
    Org-wide view: each specialty cohort with cohort summary stats and the
    provider rows containing per-KPI percentile rank inside that cohort.

    Used by the SpecialtyBenchmarkTab in the provider detail drawer.
    """
    measurement_year = year or date.today().year
    try:
        if specialty:
            return {
                "measurement_year": measurement_year,
                "specialties": [
                    {
                        **specialty_cohort_summary(specialty, measurement_year),
                        # `compute_percentiles` is per-provider so we still
                        # emit the cohort row without provider-level pct.
                    }
                ],
            }
        return specialty_benchmarks(measurement_year=measurement_year)
    except Exception as exc:
        logger.error(
            "specialty_benchmarks year=%s specialty=%s: %s",
            measurement_year, specialty, exc, exc_info=True,
        )
        raise HTTPException(status_code=500, detail="Internal server error")


# ---------------------------------------------------------------------------
# GET /api/providers/{provider_id}/peer-percentile
# ---------------------------------------------------------------------------

@router.get(
    "/{provider_id}/peer-percentile",
    summary="Percentile rank of provider's KPIs vs their specialty cohort",
)
def get_peer_percentile(
    provider_id: int,
    year: int = Query(default=None, description="Measurement year (defaults to current)"),
) -> dict[str, Any]:
    """
    Returns per-KPI percentile rank (0..100) plus cohort summary stats for
    the provider's specialty.  When the cohort has fewer than 3 providers
    the response carries ``insufficient_peers: true`` and percentile values
    are ``null``.
    """
    measurement_year = year or date.today().year
    try:
        return compute_percentiles(provider_id, measurement_year)
    except Exception as exc:
        logger.error(
            "peer_percentile provider=%s year=%s: %s",
            provider_id, measurement_year, exc, exc_info=True,
        )
        raise HTTPException(status_code=500, detail="Internal server error")
