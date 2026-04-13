"""
Dashboard Analytics Router.

Endpoints
---------
GET /api/analytics/overview           – RAF population overview (score dist, trends, revenue)
GET /api/analytics/coding             – HCC coding accuracy and MEAT compliance
GET /api/analytics/providers          – Per-provider performance ranking
GET /api/analytics/risk-stratification – Patient risk tiers and rising-risk patients

All endpoints require a valid JWT and the ``reports:read`` permission.
Results are cached for 5 minutes per tenant/year combination.
"""

import logging
from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, Query

from app.auth import get_current_user, require_permission
from app.cache import cache_get, cache_set
from app.services.dashboard_analytics_service import (
    get_coding_accuracy_metrics,
    get_patient_risk_stratification,
    get_provider_performance,
    get_raf_overview,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/analytics", tags=["analytics"])

# Cache TTL in seconds (5 minutes)
_CACHE_TTL = 300


# ---------------------------------------------------------------------------
# GET /api/analytics/overview
# ---------------------------------------------------------------------------


@router.get(
    "/overview",
    summary="RAF population overview",
    response_model=None,
)
def analytics_overview(
    year: int = Query(default=None, description="Measurement year (defaults to current year)"),
    current_user: dict = Depends(get_current_user),
    _perm: None = Depends(require_permission("reports", "read")),
) -> dict[str, Any]:
    """
    Return population-level RAF intelligence summary.

    Includes:
    - total_patients, average_raf_score, total_hccs, total_recapture_gaps
    - raf_score_distribution — patient counts in five RAF buckets
    - month_over_month_trend — avg RAF per month for the last 6 months
    - estimated_annual_revenue — avg_raf × CMS per-member rate × patient count
    """
    measurement_year = year or date.today().year
    tenant_id = str(current_user.get("tenant_id", "1"))

    cache_key = f"analytics:overview:{tenant_id}:{measurement_year}"
    cached = cache_get(cache_key)
    if cached is not None:
        return cached

    result = get_raf_overview(tenant_id, measurement_year)
    cache_set(cache_key, result, ttl=_CACHE_TTL)
    return result


# ---------------------------------------------------------------------------
# GET /api/analytics/coding
# ---------------------------------------------------------------------------


@router.get(
    "/coding",
    summary="HCC coding accuracy metrics",
    response_model=None,
)
def analytics_coding(
    current_user: dict = Depends(get_current_user),
    _perm: None = Depends(require_permission("reports", "read")),
) -> dict[str, Any]:
    """
    Return HCC coding accuracy and MEAT compliance metrics.

    Includes:
    - total_encounters, coded_encounters, uncoded_encounters
    - hcc_capture_rate  — coded encounters / total encounters
    - meat_compliance_rate — encounters with MEAT evidence / HCC-coded encounters
    - top_missed_hccs — top-10 most frequently missed HCC categories (open suspects)
    """
    tenant_id = str(current_user.get("tenant_id", "1"))

    cache_key = f"analytics:coding:{tenant_id}"
    cached = cache_get(cache_key)
    if cached is not None:
        return cached

    result = get_coding_accuracy_metrics(tenant_id)
    cache_set(cache_key, result, ttl=_CACHE_TTL)
    return result


# ---------------------------------------------------------------------------
# GET /api/analytics/providers
# ---------------------------------------------------------------------------


@router.get(
    "/providers",
    summary="Provider performance ranking",
    response_model=None,
)
def analytics_providers(
    current_user: dict = Depends(get_current_user),
    _perm: None = Depends(require_permission("reports", "read")),
) -> list[dict[str, Any]]:
    """
    Return per-provider RAF effectiveness metrics ranked by average RAF score.

    Each entry includes:
    - provider_id, provider_name, specialty
    - patient_count, avg_raf_score
    - hcc_capture_rate — proportion of encounters with ≥1 HCC coded
    - gap_closure_rate — closed recapture gaps / total gaps for this provider's panel
    """
    tenant_id = str(current_user.get("tenant_id", "1"))

    cache_key = f"analytics:providers:{tenant_id}"
    cached = cache_get(cache_key)
    if cached is not None:
        return cached

    result = get_provider_performance(tenant_id)
    cache_set(cache_key, result, ttl=_CACHE_TTL)
    return result


# ---------------------------------------------------------------------------
# GET /api/analytics/risk-stratification
# ---------------------------------------------------------------------------


@router.get(
    "/risk-stratification",
    summary="Patient risk tier stratification",
    response_model=None,
)
def analytics_risk_stratification(
    current_user: dict = Depends(get_current_user),
    _perm: None = Depends(require_permission("reports", "read")),
) -> dict[str, Any]:
    """
    Return patients grouped into risk tiers with rising-risk identification.

    Tiers (based on current-year prospective RAF score):
    - low       < 0.8
    - medium    0.8 – 1.2
    - high      1.2 – 1.8
    - very_high ≥ 1.8

    Also returns rising_risk_patients — patients whose RAF increased ≥ 0.3
    year-over-year, sorted by largest increase.
    """
    tenant_id = str(current_user.get("tenant_id", "1"))

    cache_key = f"analytics:risk:{tenant_id}"
    cached = cache_get(cache_key)
    if cached is not None:
        return cached

    result = get_patient_risk_stratification(tenant_id)
    cache_set(cache_key, result, ttl=_CACHE_TTL)
    return result
