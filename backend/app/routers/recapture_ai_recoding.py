"""
Recapture AI-recoding router.

POST /api/recapture/gaps/{gap_id}/ai-suggest
GET  /api/recapture/gaps/{gap_id}/ai-suggestions
POST /api/recapture/ai-suggestions/{suggestion_id}/accept
POST /api/recapture/ai-suggestions/{suggestion_id}/reject
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import Depends, APIRouter, Header, HTTPException, Query

from app.services import recapture_ai_recoding as svc
from app.auth import get_current_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/recapture", tags=["recapture-ai"], dependencies=[Depends(get_current_user)])


# ---------------------------------------------------------------------------
# Scan a gap for AI evidence suggestions
# ---------------------------------------------------------------------------

@router.post(
    "/gaps/{gap_id}/ai-suggest",
    summary="Scan recent notes for AI-suggested evidence supporting this gap",
)
def ai_suggest(
    gap_id: int,
    months: int = Query(
        default=12,
        ge=1,
        le=36,
        description="Lookback window in months for clinical-note retrieval.",
    ),
) -> dict[str, Any]:
    """
    Run a Gemini scan over the patient's last *months* months of clinical notes
    and persist any verbatim evidence the model finds for the gap's chronic
    condition. Suggestions are returned in the response and stored as
    ``pending`` rows in ``recapture_ai_suggestions``.
    """
    result = svc.suggest_recoding(gap_id, months=months)
    if result.get("error") and "not found" in str(result["error"]).lower():
        raise HTTPException(status_code=404, detail=result["error"])
    return result


# ---------------------------------------------------------------------------
# List pending suggestions for a gap
# ---------------------------------------------------------------------------

@router.get(
    "/gaps/{gap_id}/ai-suggestions",
    summary="List pending AI suggestions for a recapture gap",
)
def list_ai_suggestions(gap_id: int) -> dict[str, Any]:
    suggestions = svc.list_pending_suggestions(gap_id)
    return {
        "gap_id": gap_id,
        "count": len(suggestions),
        "suggestions": suggestions,
    }


# ---------------------------------------------------------------------------
# Accept / Reject
# ---------------------------------------------------------------------------

@router.post(
    "/ai-suggestions/{suggestion_id}/accept",
    summary="Accept an AI suggestion and promote its evidence to the gap",
)
def accept_ai_suggestion(
    suggestion_id: int,
    x_user: str | None = Header(default=None, alias="X-User"),
) -> dict[str, Any]:
    result = svc.accept_suggestion(suggestion_id, reviewer=x_user)
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("error", "accept failed"))
    return result


@router.post(
    "/ai-suggestions/{suggestion_id}/reject",
    summary="Reject an AI suggestion",
)
def reject_ai_suggestion(
    suggestion_id: int,
    x_user: str | None = Header(default=None, alias="X-User"),
) -> dict[str, Any]:
    result = svc.reject_suggestion(suggestion_id, reviewer=x_user)
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("error", "reject failed"))
    return result
