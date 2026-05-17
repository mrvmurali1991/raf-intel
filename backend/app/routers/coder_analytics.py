"""
Coder Productivity Analytics — HTTP API.

Endpoints
---------
GET /api/coder-analytics/me           — current user's metrics
GET /api/coder-analytics/team         — per-coder breakdown (manager view)
GET /api/coder-analytics/leaderboard  — anonymized ranking for friendly comp.

The ``/team`` and ``/leaderboard`` views require the ``reports:write``
permission (admin/manager) since they expose other coders' productivity
numbers.  ``/me`` requires only ``reports:read`` so individual coders can
inspect their own dashboard.
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, Query

from app.auth import get_current_user, get_tenant_id, require_permission
from app.services.coder_analytics import (
    compute_coder_metrics,
    compute_leaderboard,
    compute_team_metrics,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/coder-analytics", tags=["coder-analytics"])


# ---------------------------------------------------------------------------
# GET /api/coder-analytics/me
# ---------------------------------------------------------------------------

@router.get(
    "/me",
    summary="Personal coder productivity metrics",
    response_model=None,
)
def my_coder_metrics(
    date_from: str | None = Query(default=None, alias="from",
                                  description="Window start YYYY-MM-DD"),
    date_to: str | None = Query(default=None, alias="to",
                                description="Window end YYYY-MM-DD"),
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
    _perm: None = Depends(require_permission("reports", "read")),
) -> dict[str, Any]:
    """
    Return productivity metrics for *the authenticated user* over the
    inclusive ``[from, to]`` window.  Defaults to the trailing 30 days.
    """
    user_id = current_user.get("id")
    if not user_id:
        # Should never hit — get_current_user already enforces this.
        return {"error": "no user id on token"}
    return compute_coder_metrics(int(user_id), tenant_id, date_from, date_to)


# ---------------------------------------------------------------------------
# GET /api/coder-analytics/team
# ---------------------------------------------------------------------------

@router.get(
    "/team",
    summary="Team-wide coder productivity (manager view)",
    response_model=None,
)
def team_coder_metrics(
    date_from: str | None = Query(default=None, alias="from"),
    date_to: str | None = Query(default=None, alias="to"),
    tenant_id: str = Depends(get_tenant_id),
    # Re-use the existing reports:write permission as the "team analytics"
    # gate — admin and manager have it; viewer/coder/auditor do not.
    _perm: None = Depends(require_permission("reports", "write")),
) -> dict[str, Any]:
    return compute_team_metrics(tenant_id, date_from, date_to)


# ---------------------------------------------------------------------------
# GET /api/coder-analytics/leaderboard
# ---------------------------------------------------------------------------

@router.get(
    "/leaderboard",
    summary="Anonymized coder leaderboard",
    response_model=None,
)
def coder_leaderboard(
    date_from: str | None = Query(default=None, alias="from"),
    date_to: str | None = Query(default=None, alias="to"),
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
    _perm: None = Depends(require_permission("reports", "read")),
) -> dict[str, Any]:
    return compute_leaderboard(
        tenant_id, date_from, date_to,
        requesting_user_id=int(current_user.get("id") or 0) or None,
    )
