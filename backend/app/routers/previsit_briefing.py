"""
Pre-Visit HCC Briefing router.

Endpoints
---------
GET /api/providers/{provider_id}/pre-visit-briefings?days=7

Returns a list of huddle cards — one per upcoming visit on this provider's
schedule — each with the patient's identity and the top HCC gaps the
provider should address during the encounter.
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from app.auth import get_current_user, require_permission
from app.rate_limit import limiter
from app.services.previsit_briefing import (
    DEFAULT_DAYS_AHEAD,
    DEFAULT_LIMIT_PER_PATIENT,
    get_upcoming_briefings,
)

logger = logging.getLogger(__name__)

# Mounted under the providers router prefix already used by the rest of the
# provider endpoints.  The path here intentionally matches /api/providers/...
router = APIRouter(prefix="/api/providers", tags=["providers"])


@router.get(
    "/{provider_id}/pre-visit-briefings",
    summary="Top HCC gaps to address during each upcoming visit",
)
@limiter.limit("60/minute")
def pre_visit_briefings(
    request: Request,
    provider_id: int,
    days: int = Query(
        default=DEFAULT_DAYS_AHEAD,
        ge=0,
        le=30,
        description="Days ahead from today (0 = today only, max 30).",
    ),
    limit_per_patient: int = Query(
        default=DEFAULT_LIMIT_PER_PATIENT,
        ge=1,
        le=10,
        description="Top-N HCC gaps to surface per visit.",
    ),
    year: int | None = Query(
        default=None,
        description="Measurement year override (defaults to each visit's year).",
    ),
    current_user: dict = Depends(get_current_user),
    _perm: None = Depends(require_permission("providers", "read")),
) -> dict[str, Any]:
    """Return upcoming visits + top HCC gaps for each.

    Always returns 200 with a ``briefings`` list (possibly empty) plus a
    ``message`` for the empty-state UI.  Errors at the service layer are
    swallowed and reported as an empty list with a warning ``message`` so the
    huddle UI degrades gracefully rather than blocking the provider.
    """
    try:
        briefings = get_upcoming_briefings(
            provider_id=provider_id,
            days_ahead=days,
            limit_per_patient=limit_per_patient,
            measurement_year=year,
        )
    except Exception as exc:
        logger.error(
            "pre_visit_briefings provider=%s days=%s: %s",
            provider_id, days, exc, exc_info=True,
        )
        raise HTTPException(status_code=500, detail="Internal server error")

    if not briefings:
        return {
            "provider_id": provider_id,
            "days_ahead": days,
            "briefings": [],
            "message": (
                f"No upcoming visits in the next {days} day"
                f"{'s' if days != 1 else ''}."
            ),
        }

    return {
        "provider_id": provider_id,
        "days_ahead": days,
        "briefings": briefings,
        "message": (
            f"{len(briefings)} upcoming visit"
            f"{'s' if len(briefings) != 1 else ''} in the next {days} day"
            f"{'s' if days != 1 else ''}."
        ),
    }
