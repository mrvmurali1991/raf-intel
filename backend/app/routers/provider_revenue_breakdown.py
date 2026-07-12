"""
Provider revenue opportunity breakdown router.

Decomposes ``provider_scorecard_snapshots.revenue_opportunity`` into three
buckets (Recapture / MEAT improvement / New suspects) so the UI can render
a pie chart and "top contributors" list.

Endpoint
--------
GET /api/providers/{provider_id}/revenue-breakdown?year=2026
"""
from __future__ import annotations

import logging
from datetime import date
from typing import Any

from fastapi import Depends, APIRouter, HTTPException, Query

from app.services.provider_revenue_breakdown import compute_breakdown
from app.auth import get_current_user, get_tenant_id

logger = logging.getLogger(__name__)

# Note: shares the /api/providers prefix with routers/providers.py.  FastAPI
# allows multiple routers under the same prefix as long as the full paths
# are distinct, so we mount this one alongside (router_registry).
router = APIRouter(prefix="/api/providers", tags=["providers"], dependencies=[Depends(get_current_user)])


@router.get(
    "/{provider_id}/revenue-breakdown",
    summary="Decompose a provider's revenue opportunity into 3 buckets",
)
def provider_revenue_breakdown(
    provider_id: int,
    year: int = Query(default=None, description="Measurement year (defaults to current)"),
    tenant_id: str = Depends(get_tenant_id),
) -> dict[str, Any]:
    """
    Returns a 3-bucket decomposition: Recapture / MEAT improvement /
    New suspects.  See ``compute_breakdown`` docstring for response schema.
    """
    yr = year or date.today().year
    try:
        return compute_breakdown(provider_id, yr, tenant_id=tenant_id)
    except Exception as exc:
        logger.error(
            "provider_revenue_breakdown provider=%s year=%s: %s",
            provider_id, yr, exc, exc_info=True,
        )
        raise HTTPException(status_code=500, detail="Internal server error")
