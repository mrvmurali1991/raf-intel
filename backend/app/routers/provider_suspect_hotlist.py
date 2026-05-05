"""
Real-Time Suspect Hot-List router.

Surfaces the provider's hottest open suspects ranked by a blended urgency
score (confidence + expected $ + days_open).  Powers the provider drawer's
"action this week" panel.

Endpoint
--------
GET /api/providers/{provider_id}/suspect-hotlist
    ?year=2026&limit=20&min_confidence=0.5
"""
from __future__ import annotations

import logging
from datetime import date
from typing import Any

from fastapi import APIRouter, HTTPException, Path, Query

from app.services.provider_suspect_hotlist import get_hotlist

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/providers", tags=["providers", "suspects"])


@router.get(
    "/{provider_id}/suspect-hotlist",
    summary="Real-time suspect hot-list for a provider",
)
def provider_suspect_hotlist(
    provider_id: int = Path(..., ge=1, description="Internal provider id"),
    year: int = Query(default=None, description="Measurement year (defaults to current)"),
    limit: int = Query(default=20, ge=1, le=200, description="Max items to return"),
    min_confidence: float = Query(
        default=0.0, ge=0.0, le=1.0,
        description="Drop suspects with confidence < this value (0..1)",
    ),
) -> dict[str, Any]:
    """Return the top-N most urgent open suspects across the provider's panel.

    See ``app.services.provider_suspect_hotlist.get_hotlist`` for the urgency
    formula and item shape.  Always returns 200 — empty `items` if the panel
    is empty or all suspects are filtered out.
    """
    measurement_year = year or date.today().year
    try:
        return get_hotlist(
            provider_id=provider_id,
            year=measurement_year,
            limit=limit,
            min_confidence=min_confidence,
        )
    except Exception as exc:
        logger.error(
            "provider_suspect_hotlist provider=%s year=%s: %s",
            provider_id, measurement_year, exc, exc_info=True,
        )
        raise HTTPException(status_code=500, detail=str(exc))
