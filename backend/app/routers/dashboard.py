"""
dashboard.py — Dashboard-specific API endpoints.

Endpoints that belong to the dashboard domain but were previously scattered
across other routers (e.g. health.py) are consolidated here.
"""
from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Any

from fastapi import APIRouter, Depends, Query

from app.auth import get_current_user, get_tenant_id

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


# ---------------------------------------------------------------------------
# GET /api/v1/dashboard/kpi-trends  — 12-week sparkline series per KPI
# ---------------------------------------------------------------------------


@router.get("/kpi-trends", summary="12-week KPI sparkline series")
def dashboard_kpi_trends(
    weeks: int = Query(default=12, ge=2, le=52, description="Number of weekly buckets to return"),
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
) -> dict[str, Any]:
    """
    Returns per-week series (oldest -> newest) for four dashboard KPIs:

    - open_gaps      - count of open recapture gaps per week
    - suspects       - count of open suspect conditions per week
    - panel_patients - distinct active patients per week
    - avg_raf        - average RAF score per week

    Also returns ``deltas`` -- the WoW % change between the last two buckets
    for each KPI.

    Weeks are ISO-Monday-anchored so the most recent bucket is always the
    current (partial) week.
    """
    from app.db import raf_cursor

    today = date.today()
    start_of_current_week = today - timedelta(days=today.weekday())
    earliest_week = start_of_current_week - timedelta(weeks=weeks - 1)

    empty_series: list[float] = [0.0] * weeks

    def _week_index(week_start: date) -> int:
        return (week_start - earliest_week).days // 7

    try:
        with raf_cursor() as cur:
            # open gaps per week
            cur.execute(
                """
                SELECT
                    DATE_SUB(created_at, INTERVAL WEEKDAY(created_at) DAY) AS week_start,
                    COUNT(*) AS cnt
                FROM recapture_gaps
                WHERE status = 'open'
                  AND tenant_id = %s
                  AND created_at >= %s
                GROUP BY week_start
                """,
                (tenant_id, earliest_week.isoformat()),
            )
            gaps_series: list[float] = list(empty_series)
            for row in cur.fetchall():
                idx = _week_index(date.fromisoformat(str(row["week_start"])[:10]))
                if 0 <= idx < weeks:
                    gaps_series[idx] = float(row["cnt"])

            # suspects per week
            cur.execute(
                """
                SELECT
                    DATE_SUB(created_at, INTERVAL WEEKDAY(created_at) DAY) AS week_start,
                    COUNT(*) AS cnt
                FROM raf_suspect_conditions
                WHERE status = 'open'
                  AND tenant_id = %s
                  AND created_at >= %s
                GROUP BY week_start
                """,
                (tenant_id, earliest_week.isoformat()),
            )
            suspects_series: list[float] = list(empty_series)
            for row in cur.fetchall():
                idx = _week_index(date.fromisoformat(str(row["week_start"])[:10]))
                if 0 <= idx < weeks:
                    suspects_series[idx] = float(row["cnt"])

            # panel patients per week (distinct active)
            cur.execute(
                """
                SELECT
                    DATE_SUB(created_at, INTERVAL WEEKDAY(created_at) DAY) AS week_start,
                    COUNT(DISTINCT id) AS cnt
                FROM patients
                WHERE is_active = 1
                  AND tenant_id = %s
                  AND created_at >= %s
                GROUP BY week_start
                """,
                (tenant_id, earliest_week.isoformat()),
            )
            panel_series: list[float] = list(empty_series)
            for row in cur.fetchall():
                idx = _week_index(date.fromisoformat(str(row["week_start"])[:10]))
                if 0 <= idx < weeks:
                    panel_series[idx] = float(row["cnt"])

            # avg RAF per week
            cur.execute(
                """
                SELECT
                    DATE_SUB(calculated_at, INTERVAL WEEKDAY(calculated_at) DAY) AS week_start,
                    ROUND(AVG(final_raf), 4) AS avg_raf
                FROM raf_scores
                WHERE tenant_id = %s
                  AND calculated_at >= %s
                GROUP BY week_start
                """,
                (tenant_id, earliest_week.isoformat()),
            )
            raf_series: list[float] = list(empty_series)
            for row in cur.fetchall():
                idx = _week_index(date.fromisoformat(str(row["week_start"])[:10]))
                if 0 <= idx < weeks:
                    raf_series[idx] = float(row["avg_raf"] or 0)

    except Exception as exc:
        logger.warning("dashboard_kpi_trends query failed: %s", exc)
        return {
            "weeks": weeks,
            "error": True,
            "open_gaps": empty_series,
            "suspects": empty_series,
            "panel_patients": empty_series,
            "avg_raf": empty_series,
            "deltas": {},
        }

    def _wow_delta(series: list[float]) -> float | None:
        prev = series[-2] if len(series) >= 2 else 0
        curr = series[-1] if series else 0
        if prev == 0:
            return None
        return round(((curr - prev) / prev) * 100, 1)

    return {
        "weeks": weeks,
        "open_gaps": gaps_series,
        "suspects": suspects_series,
        "panel_patients": panel_series,
        "avg_raf": raf_series,
        "deltas": {
            "open_gaps": _wow_delta(gaps_series),
            "suspects": _wow_delta(suspects_series),
            "panel_patients": _wow_delta(panel_series),
            "avg_raf": _wow_delta(raf_series),
        },
    }


# ---------------------------------------------------------------------------
# GET /api/v1/dashboard/top-opportunities
# Returns top 5 patients ranked by (estimated_raf_lift * confidence_score),
# closing within `days` days.
# ---------------------------------------------------------------------------


@router.get(
    "/top-opportunities",
    summary="Top 5 RAF capture opportunities closing soon",
)
def dashboard_top_opportunities(
    days: int = Query(default=14, ge=1, le=90, description="Closing window in days"),
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
) -> dict[str, Any]:
    """
    Returns up to 5 patients ranked by ``estimated_raf_lift * confidence_score``
    whose recapture gap or suspect condition closes within *days* days.

    Fields per row:
    - patient_id, patient_name
    - condition  (HCC label or suspect description)
    - estimated_raf_lift
    - confidence_score  (0–1)
    - revenue_at_risk  (USD, lift × $10 000 per RAF point)
    - days_remaining
    """
    from app.db import raf_cursor

    cutoff = date.today() + timedelta(days=days)

    try:
        with raf_cursor() as cur:
            cur.execute(
                """
                SELECT
                    p.id                                            AS patient_id,
                    CONCAT(p.first_name, ' ', p.last_name)         AS patient_name,
                    COALESCE(h.hcc_label, h.hcc_code, 'Unknown')   AS condition,
                    COALESCE(h.estimated_lift, 0.20)               AS estimated_raf_lift,
                    COALESCE(rs.confidence_score, 0.75)            AS confidence_score,
                    COALESCE(h.gap_close_date, DATE_ADD(NOW(), INTERVAL %s DAY)) AS close_date
                FROM raf_patient_hcc h
                JOIN patients         p  ON p.id = h.patient_id
                LEFT JOIN raf_scores  rs ON rs.patient_id = h.patient_id
                                        AND rs.tenant_id  = h.tenant_id
                WHERE h.tenant_id = %s
                  AND h.status    = 'open'
                  AND (
                        h.gap_close_date IS NULL
                     OR h.gap_close_date <= %s
                  )
                ORDER BY (COALESCE(h.estimated_lift, 0.20) * COALESCE(rs.confidence_score, 0.75)) DESC
                LIMIT 5
                """,
                (days, tenant_id, cutoff.isoformat()),
            )
            rows = cur.fetchall()
    except Exception as exc:
        logger.warning("dashboard_top_opportunities query failed: %s", exc)
        rows = []

    today = date.today()
    opportunities = []
    for row in rows:
        close_dt = row.get("close_date")
        if close_dt is None:
            days_rem = days
        elif hasattr(close_dt, "date"):
            days_rem = max(0, (close_dt.date() - today).days)
        else:
            days_rem = max(0, (close_dt - today).days)

        lift = float(row.get("estimated_raf_lift") or 0.20)
        conf = float(row.get("confidence_score") or 0.75)
        opportunities.append(
            {
                "patient_id": row["patient_id"],
                "patient_name": row["patient_name"],
                "condition": row["condition"],
                "estimated_raf_lift": round(lift, 3),
                "confidence_score": round(conf, 3),
                "revenue_at_risk": round(lift * 10_000),
                "days_remaining": days_rem,
            }
        )

    return {"opportunities": opportunities, "count": len(opportunities)}
