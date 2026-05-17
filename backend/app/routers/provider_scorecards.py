"""
Provider Scorecard v2 — HTTP router.

Endpoints
---------
GET /api/provider-scorecards?year=2026
    List every active provider with per-provider metrics + tenant
    averages so the UI can render a peer-delta column.

GET /api/provider-scorecards/{provider_id}?year=2026
    Single provider variant — same payload, but for one provider only.
    Returns 404 when the provider doesn't exist (or is inactive).

Auth
----
``require_permission("providers", "read")`` — same surface the existing
provider router uses. Tenant-scoped via ``get_tenant_id``.

This is the v2 surface — the existing ``/api/providers/...`` router is
NOT modified.
"""
# Do NOT add 'from __future__ import annotations' — it breaks FastAPI/Pydantic
# schema generation (ForwardRef errors in /openapi.json).

import logging
from datetime import date
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.auth import get_current_user, get_tenant_id, require_permission
from app.services.provider_scorecard_v2 import (
    compute_provider_scorecard,
    list_provider_scorecards,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/provider-scorecards", tags=["provider_scorecards"])


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------


class ProviderScorecardV2(BaseModel):
    """Per-provider scorecard row used by both list + single endpoints."""

    provider_id: int
    provider_npi: Optional[str] = None
    provider_name: str
    specialty: Optional[str] = None
    panel_size: int = Field(..., ge=0)
    avg_raf: float
    recapture_rate_pct: float
    # meat_compliance_pct is None when no HCCs have been MEAT-scored yet —
    # surfaces an em-dash in the UI rather than a misleading 0.0%.
    meat_compliance_pct: Optional[float] = None
    meat_coverage_pct: Optional[float] = None
    # Set when the underlying counts indicate a data-quality anomaly
    # (e.g. leakage rate > 1 because open-gaps query expanded mid-year).
    data_quality_flag: Optional[str] = None

    # Peer (tenant) averages — same for every row in a list response but
    # included on every row so the frontend can render delta-vs-peer
    # without juggling two shapes.
    tenant_avg_raf: float
    tenant_avg_recapture_rate: float
    tenant_avg_meat_compliance: Optional[float] = None

    year: int


class ProviderScorecardListResponse(BaseModel):
    year: int
    providers: List[ProviderScorecardV2]
    tenant_avg_raf: float
    tenant_avg_recapture_rate: float
    tenant_avg_meat_compliance: Optional[float] = None


# ---------------------------------------------------------------------------
# /api/provider-scorecards
# ---------------------------------------------------------------------------


@router.get(
    "",
    response_model=ProviderScorecardListResponse,
    summary="List provider scorecards with peer benchmarks",
)
def get_provider_scorecards(
    year: Optional[int] = Query(default=None, ge=2020, le=2035, description="Measurement year (default: current)"),
    current_user: dict = Depends(get_current_user),  # noqa: ARG001  (auth side-effect)
    tenant_id: str = Depends(get_tenant_id),
    _perm: None = Depends(require_permission("providers", "read")),
) -> dict:
    """Return one row per active provider with metrics + tenant averages.

    Each row carries the tenant averages so the UI can render a per-cell
    delta vs peer without a second API call.
    """
    yr = year or date.today().year
    try:
        payload = list_provider_scorecards(tenant_id=tenant_id, year=yr)
        # Decorate each row with the tenant averages + year so it
        # matches ProviderScorecardV2.
        for row in payload["providers"]:
            row["tenant_avg_raf"] = payload["tenant_avg_raf"]
            row["tenant_avg_recapture_rate"] = payload["tenant_avg_recapture_rate"]
            row["tenant_avg_meat_compliance"] = payload["tenant_avg_meat_compliance"]
            row["year"] = payload["year"]
        return payload
    except Exception as exc:
        logger.error(
            "list_provider_scorecards year=%s tenant=%s: %s",
            yr, tenant_id, exc, exc_info=True,
        )
        raise HTTPException(status_code=500, detail="Internal server error")


# ---------------------------------------------------------------------------
# /api/provider-scorecards/{provider_id}
# ---------------------------------------------------------------------------


@router.get(
    "/{provider_id}",
    response_model=ProviderScorecardV2,
    summary="Single provider scorecard with peer benchmarks",
)
def get_provider_scorecard(
    provider_id: int,
    year: Optional[int] = Query(default=None, ge=2020, le=2035),
    current_user: dict = Depends(get_current_user),  # noqa: ARG001
    tenant_id: str = Depends(get_tenant_id),
    _perm: None = Depends(require_permission("providers", "read")),
) -> dict:
    yr = year or date.today().year
    try:
        return compute_provider_scorecard(
            provider_id=int(provider_id),
            tenant_id=tenant_id,
            year=yr,
        )
    except ValueError as ve:
        raise HTTPException(status_code=404, detail=str(ve))
    except Exception as exc:
        logger.error(
            "get_provider_scorecard provider=%s year=%s tenant=%s: %s",
            provider_id, yr, tenant_id, exc, exc_info=True,
        )
        raise HTTPException(status_code=500, detail="Internal server error")
