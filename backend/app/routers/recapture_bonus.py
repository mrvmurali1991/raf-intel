"""
Recapture Bonus / Coder Incentive Tracker router.

Endpoints
---------
GET    /api/recapture/bonus/config                – per-tenant config
PUT    /api/recapture/bonus/config                – admin tweak
GET    /api/recapture/bonus/leaderboard           – ranked coder list
GET    /api/recapture/bonus/coder/{id}/earnings   – per-coder summary
GET    /api/recapture/gaps/{id}/bonus-preview     – "close-now" preview

All endpoints require a valid JWT. Read endpoints require ``recapture:read``
permission; the config PUT requires ``recapture:write``.
"""
# Do NOT add 'from __future__ import annotations' — it breaks FastAPI/Pydantic
# schema generation (ForwardRef errors in /openapi.json).

import logging
from datetime import datetime
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.auth import get_current_user, get_tenant_id, require_permission
from app.services.recapture_bonus_service import (
    bonus_for_closing_now,
    compute_coder_earnings,
    compute_leaderboard,
    current_month_multiplier,
    get_or_create_config,
    update_config,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/recapture", tags=["recapture_bonus"])


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


class BonusConfigResponse(BaseModel):
    id: int
    tenant_id: str
    bonus_per_closure_default: float
    month_multipliers: dict[str, float]
    active: bool
    current_month_multiplier: dict[str, Any]
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class BonusConfigUpdate(BaseModel):
    bonus_per_closure_default: Optional[float] = Field(default=None, ge=0)
    month_multipliers: Optional[dict[str, float]] = None
    active: Optional[bool] = None


class LeaderboardEntry(BaseModel):
    rank: int
    coder_id: Optional[int] = None
    resolved_by: str
    name: str
    email: str
    ytd_closures: int
    ytd_dollars_recaptured: float
    bonus_earned: float
    open_gaps: int
    win_rate: float


class LeaderboardResponse(BaseModel):
    tenant_id: str
    year: int
    current_month_multiplier: dict[str, Any]
    leaderboard: list[LeaderboardEntry]


class CoderEarningsResponse(BaseModel):
    coder_id: int
    name: str
    email: str
    role: str
    year: int
    ytd_closures: int
    ytd_dollars_recaptured: float
    bonus_earned: float
    bonus_at_risk: float
    open_gaps: int
    current_month: int
    current_multiplier: float
    next_month: int
    next_multiplier: float
    monthly_breakdown: list[dict[str, Any]]


class BonusPreviewResponse(BaseModel):
    gap_id: int
    bonus: float
    base_bonus: float
    month: int
    multiplier: float
    eligible: bool
    reason: Optional[str] = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _config_to_api(cfg: dict[str, Any], tenant_id: str) -> dict[str, Any]:
    """Convert internal config dict -> API response, with str-keyed multipliers."""
    return {
        "id": cfg["id"],
        "tenant_id": cfg["tenant_id"],
        "bonus_per_closure_default": cfg["bonus_per_closure_default"],
        "month_multipliers": {str(k): float(v) for k, v in cfg["month_multipliers"].items()},
        "active": cfg["active"],
        "current_month_multiplier": current_month_multiplier(tenant_id),
        "created_at": cfg.get("created_at"),
        "updated_at": cfg.get("updated_at"),
    }


# ---------------------------------------------------------------------------
# GET /api/recapture/bonus/config
# ---------------------------------------------------------------------------


@router.get(
    "/bonus/config",
    summary="Per-tenant bonus configuration",
    response_model=BonusConfigResponse,
)
def get_bonus_config(
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
    _perm: None = Depends(require_permission("recapture", "read")),
) -> BonusConfigResponse:
    """Return the bonus config for the calling tenant. Auto-seeds defaults."""
    try:
        cfg = get_or_create_config(tenant_id)
        return BonusConfigResponse(**_config_to_api(cfg, tenant_id))
    except Exception as exc:  # noqa: BLE001
        logger.error("get_bonus_config tenant=%s: %s", tenant_id, exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


# ---------------------------------------------------------------------------
# PUT /api/recapture/bonus/config
# ---------------------------------------------------------------------------


@router.put(
    "/bonus/config",
    summary="Update tenant bonus configuration",
    response_model=BonusConfigResponse,
)
def update_bonus_config(
    body: BonusConfigUpdate,
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
    _perm: None = Depends(require_permission("recapture", "write")),
) -> BonusConfigResponse:
    """Patch the bonus configuration. All fields optional; unsent fields are unchanged."""
    payload = body.model_dump(exclude_unset=True, exclude_none=True)
    try:
        cfg = update_config(tenant_id, **payload)
        return BonusConfigResponse(**_config_to_api(cfg, tenant_id))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:  # noqa: BLE001
        logger.error("update_bonus_config tenant=%s: %s", tenant_id, exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


# ---------------------------------------------------------------------------
# GET /api/recapture/bonus/leaderboard
# ---------------------------------------------------------------------------


@router.get(
    "/bonus/leaderboard",
    summary="Ranked coder leaderboard for a given year",
    response_model=LeaderboardResponse,
)
def get_bonus_leaderboard(
    year: int = Query(default=None, ge=2020, le=2099, description="Defaults to current year"),
    limit: int = Query(default=20, ge=1, le=200),
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
    _perm: None = Depends(require_permission("recapture", "read")),
) -> LeaderboardResponse:
    """Return the top ``limit`` coders for ``year`` (defaults to current year)."""
    try:
        effective_year = int(year) if year else datetime.utcnow().year
        rows = compute_leaderboard(tenant_id, effective_year, limit=limit)
        return LeaderboardResponse(
            tenant_id=str(tenant_id),
            year=effective_year,
            current_month_multiplier=current_month_multiplier(tenant_id),
            leaderboard=[LeaderboardEntry(**r) for r in rows],
        )
    except Exception as exc:  # noqa: BLE001
        logger.error("get_bonus_leaderboard tenant=%s: %s", tenant_id, exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


# ---------------------------------------------------------------------------
# GET /api/recapture/bonus/coder/{id}/earnings
# ---------------------------------------------------------------------------


@router.get(
    "/bonus/coder/{coder_id}/earnings",
    summary="Per-coder year-to-date bonus earnings",
    response_model=CoderEarningsResponse,
)
def get_coder_earnings(
    coder_id: int,
    year: int = Query(default=None, ge=2020, le=2099),
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
    _perm: None = Depends(require_permission("recapture", "read")),
) -> CoderEarningsResponse:
    """
    Return bonus earnings + at-risk preview for a coder.

    Non-admin callers may only request their own earnings; admins may
    inspect any coder in their tenant.
    """
    role = (current_user.get("role") or "").lower()
    own_id = current_user.get("id")
    if role not in {"admin", "manager"} and own_id is not None and int(own_id) != int(coder_id):
        raise HTTPException(status_code=403, detail="May only view your own earnings.")

    try:
        effective_year = int(year) if year else datetime.utcnow().year
        data = compute_coder_earnings(tenant_id, coder_id, effective_year)
        return CoderEarningsResponse(**data)
    except Exception as exc:  # noqa: BLE001
        logger.error(
            "get_coder_earnings tenant=%s coder=%s: %s",
            tenant_id, coder_id, exc, exc_info=True,
        )
        raise HTTPException(status_code=500, detail="Internal server error")


# ---------------------------------------------------------------------------
# GET /api/recapture/gaps/{gap_id}/bonus-preview
# ---------------------------------------------------------------------------


@router.get(
    "/gaps/{gap_id}/bonus-preview",
    summary="Preview the bonus a coder would earn closing this gap right now",
    response_model=BonusPreviewResponse,
)
def get_gap_bonus_preview(
    gap_id: int,
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
    _perm: None = Depends(require_permission("recapture", "read")),
) -> BonusPreviewResponse:
    """Return the dollar bonus a coder would earn for closing ``gap_id`` now."""
    try:
        result = bonus_for_closing_now(tenant_id, gap_id)
        return BonusPreviewResponse(**result)
    except Exception as exc:  # noqa: BLE001
        logger.error(
            "get_gap_bonus_preview tenant=%s gap=%s: %s",
            tenant_id, gap_id, exc, exc_info=True,
        )
        raise HTTPException(status_code=500, detail="Internal server error")
