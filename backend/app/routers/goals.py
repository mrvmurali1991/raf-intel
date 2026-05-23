"""
Quarterly RAF Capture Goals router.

Endpoints
---------
GET  /api/v1/goals              – list all goals for the tenant (current quarter first)
POST /api/v1/goals              – create a new goal
GET  /api/v1/goals/{id}/progress – actual vs target for one goal
"""
from __future__ import annotations

import logging
import re
from datetime import date, datetime
from math import floor
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, field_validator

from app.auth import get_current_user, get_tenant_id, require_permission
from app.db import raf_cursor

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/goals", tags=["goals"])

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_PERIOD_RE = re.compile(r"^\d{4}-Q[1-4]$")


def _current_period() -> str:
    d = date.today()
    q = (d.month - 1) // 3 + 1
    return f"{d.year}-Q{q}"


def _quarter_bounds(period: str) -> tuple[date, date]:
    """Return (start, end) dates for a YYYY-QN period string."""
    year, qpart = period.split("-")
    q = int(qpart[1])
    start_month = (q - 1) * 3 + 1
    end_month = start_month + 2
    start = date(int(year), start_month, 1)
    # last day of end_month
    next_m = end_month % 12 + 1
    next_y = int(year) if end_month < 12 else int(year) + 1
    end = date(next_y, next_m, 1)
    from datetime import timedelta
    end = end - timedelta(days=1)
    return start, end


def _days_remaining(period: str) -> int:
    _, end = _quarter_bounds(period)
    delta = end - date.today()
    return max(0, delta.days)


# ---------------------------------------------------------------------------
# SQL helpers (plain DB, no ORM to match project conventions)
# ---------------------------------------------------------------------------

def _fetch_goals(tenant_id: str, cur) -> list[dict]:
    cur.execute(
        """
        SELECT id, tenant_id, period, metric, CAST(target_value AS CHAR) AS target_value,
               owner_user_id, created_at
        FROM raf_goals
        WHERE tenant_id = %s
        ORDER BY period DESC, id DESC
        """,
        (tenant_id,),
    )
    return cur.fetchall() or []


def _fetch_goal(goal_id: int, tenant_id: str, cur) -> dict | None:
    cur.execute(
        """
        SELECT id, tenant_id, period, metric, CAST(target_value AS CHAR) AS target_value,
               owner_user_id, created_at
        FROM raf_goals
        WHERE id = %s AND tenant_id = %s
        """,
        (goal_id, tenant_id),
    )
    return cur.fetchone()


def _compute_actual(metric: str, period: str, tenant_id: str, cur) -> float:
    start, end = _quarter_bounds(period)

    if metric == "raf_capture_count":
        cur.execute(
            """
            SELECT COUNT(*) AS cnt
            FROM hcc_suspects
            WHERE tenant_id = %s
              AND status = 'captured'
              AND DATE(updated_at) BETWEEN %s AND %s
            """,
            (tenant_id, start.isoformat(), end.isoformat()),
        )
        row = cur.fetchone()
        return float(row["cnt"] if row else 0)

    if metric == "gaps_closed":
        cur.execute(
            """
            SELECT COUNT(*) AS cnt
            FROM care_gaps
            WHERE tenant_id = %s
              AND status = 'closed'
              AND DATE(closed_at) BETWEEN %s AND %s
            """,
            (tenant_id, start.isoformat(), end.isoformat()),
        )
        row = cur.fetchone()
        return float(row["cnt"] if row else 0)

    if metric == "revenue":
        cur.execute(
            """
            SELECT COALESCE(SUM(revenue_impact), 0) AS total
            FROM hcc_suspects
            WHERE tenant_id = %s
              AND status = 'captured'
              AND DATE(updated_at) BETWEEN %s AND %s
            """,
            (tenant_id, start.isoformat(), end.isoformat()),
        )
        row = cur.fetchone()
        return float(row["total"] if row else 0)

    return 0.0


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class GoalCreate(BaseModel):
    period: str
    metric: str
    target_value: float
    owner_user_id: int | None = None

    @field_validator("period")
    @classmethod
    def validate_period(cls, v: str) -> str:
        if not _PERIOD_RE.match(v):
            raise ValueError("period must be YYYY-QN (e.g. 2026-Q2)")
        return v

    @field_validator("metric")
    @classmethod
    def validate_metric(cls, v: str) -> str:
        allowed = {"raf_capture_count", "revenue", "gaps_closed"}
        if v not in allowed:
            raise ValueError(f"metric must be one of {allowed}")
        return v

    @field_validator("target_value")
    @classmethod
    def validate_target(cls, v: float) -> float:
        if v <= 0:
            raise ValueError("target_value must be positive")
        return v


def _pace_expected(period: str) -> float:
    """% of target we should have hit by today given linear burn."""
    start, end = _quarter_bounds(period)
    total_days = (end - start).days or 1
    elapsed = (date.today() - start).days
    return round(min(max(elapsed / total_days * 100, 0), 100), 1)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get("", summary="List quarterly goals", response_model=None)
def list_goals(
    period: str | None = Query(None, description="Filter by YYYY-QN period"),
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
    _perm: None = Depends(require_permission("goals", "read")),
) -> list[dict[str, Any]]:
    with raf_cursor() as cur:
        goals = _fetch_goals(tenant_id, cur)
        if period:
            goals = [g for g in goals if g["period"] == period]
        result = []
        for g in goals:
            actual = _compute_actual(g["metric"], g["period"], tenant_id, cur)
            target = float(g["target_value"])
            pct = round(min(actual / target * 100, 100), 1) if target else 0
            pace = _pace_expected(g["period"])
            on_track = pct >= pace * 0.8  # within 80% of expected pace = on track
            result.append(
                {
                    **g,
                    "target_value": target,
                    "actual_value": actual,
                    "percent_complete": pct,
                    "days_remaining": _days_remaining(g["period"]),
                    "on_track": on_track,
                    "pace_expected": pace,
                }
            )
        return result


@router.post("", summary="Create a quarterly goal", status_code=201, response_model=None)
def create_goal(
    body: GoalCreate,
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
    _perm: None = Depends(require_permission("goals", "write")),
) -> dict[str, Any]:
    with raf_cursor() as cur:
        cur.execute(
            """
            INSERT INTO raf_goals (tenant_id, period, metric, target_value, owner_user_id, created_at)
            VALUES (%s, %s, %s, %s, %s, NOW())
            """,
            (
                tenant_id,
                body.period,
                body.metric,
                body.target_value,
                body.owner_user_id,
            ),
        )
        new_id = cur.lastrowid
        goal = _fetch_goal(new_id, tenant_id, cur)
        if not goal:
            raise HTTPException(status_code=500, detail="Goal creation failed")
        actual = _compute_actual(goal["metric"], goal["period"], tenant_id, cur)
        target = float(goal["target_value"])
        pct = round(min(actual / target * 100, 100), 1) if target else 0
        return {
            **goal,
            "target_value": target,
            "actual_value": actual,
            "percent_complete": pct,
            "days_remaining": _days_remaining(goal["period"]),
        }


@router.get("/{goal_id}/progress", summary="Goal actual vs target", response_model=None)
def goal_progress(
    goal_id: int,
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
    _perm: None = Depends(require_permission("goals", "read")),
) -> dict[str, Any]:
    with raf_cursor() as cur:
        goal = _fetch_goal(goal_id, tenant_id, cur)
        if not goal:
            raise HTTPException(status_code=404, detail="Goal not found")
        actual = _compute_actual(goal["metric"], goal["period"], tenant_id, cur)
        target = float(goal["target_value"])
        pct = round(min(actual / target * 100, 100), 1) if target else 0
        _, end = _quarter_bounds(goal["period"])
        return {
            **goal,
            "target_value": target,
            "actual_value": actual,
            "percent_complete": pct,
            "days_remaining": _days_remaining(goal["period"]),
            "quarter_end": end.isoformat(),
            "on_track": pct >= _pace_expected(goal["period"]),
        }
