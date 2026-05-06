"""
Top HCC Opportunities router.

Surfaces the top N HCC opportunities (ranked by expected $ revenue lift) for
a given provider's panel.

Endpoints
---------
GET /api/providers/{provider_id}/top-opportunities
"""
# Removed: from __future__ import annotations (FastAPI schema generation)

import logging
from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from app.auth import get_current_user, require_permission
from app.rate_limit import limiter
from app.services.provider_service import get_provider
from app.services.top_hcc_opportunities import compute_top_hccs

logger = logging.getLogger(__name__)

# We intentionally reuse the /api/providers prefix so the path is
# /api/providers/{id}/top-opportunities — keeps the resource grouped with the
# rest of provider endpoints in OpenAPI without changing providers.py.
router = APIRouter(prefix="/api/providers", tags=["providers"])


@router.get(
    "/{provider_id}/top-opportunities",
    summary="Top HCC opportunities for a provider, ranked by expected $ lift",
)
@limiter.limit("60/minute")
def top_opportunities(
    request: Request,
    provider_id: int,
    year: int = Query(default=None, description="Measurement year (defaults to current year)"),
    limit: int = Query(default=5, ge=1, le=50, description="Max opportunities returned"),
    current_user: dict = Depends(get_current_user),
    _perm: None = Depends(require_permission("providers", "read")),
) -> dict[str, Any]:
    """
    Return up to *limit* HCC opportunities for the provider, sorted by
    descending expected $ lift.

    Score = open_suspect_count * raf_coefficient * HCC_BASE_RATE * avg_confidence

    Includes peer_capture_rate (avg across same-specialty peers) for context;
    null when no peer data is available.
    """
    provider = get_provider(provider_id)
    if not provider:
        raise HTTPException(status_code=404, detail=f"Provider {provider_id} not found")

    measurement_year = year or date.today().year
    try:
        items = compute_top_hccs(
            provider_id=provider_id,
            year=measurement_year,
            limit=limit,
            tenant_id=current_user.get("tenant_id"),
        )
    except Exception as exc:
        logger.error(
            "top_opportunities provider=%s year=%s: %s",
            provider_id, measurement_year, exc, exc_info=True,
        )
        raise HTTPException(status_code=500, detail="Internal server error")

    return {
        "provider_id": provider_id,
        "provider_name": provider.get("full_name", ""),
        "measurement_year": measurement_year,
        "limit": limit,
        "count": len(items),
        "opportunities": items,
    }
