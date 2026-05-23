"""
Recapture decay-curve & velocity KPI service.

Built directly on top of the ``recapture_gaps`` table populated by
``app.services.recapture_gap_service``. All calculations are deterministic
SQL aggregations — no LLM, no probabilistic models — so results are stable
and auditable for CFOs.

Three primary entry points are exposed:

* :func:`get_decay_curve`    — multi-year monthly cumulative-closure trajectory
                               (the chart that exposes "are we slipping?").
* :func:`get_velocity_kpis`  — current-year scorecard: avg/median days-to-close,
                               YTD recaptured revenue, year-end projection,
                               early/late recapture proportions.
* :func:`get_top_slow_movers` — HCCs with the worst time-to-close, ranked by
                                avg ``days_to_close`` and surfaced for a
                                "assign to campaign" workflow.

A "cohort" here is the *current_year* attribute of a recapture gap (i.e. the
measurement year in which the gap was open). The closure month is
``MONTH(resolved_at)`` clamped to 1..12. We do *not* require the gap to be
resolved within its own year — late-year recaptures still count, they just
land in month 12 (or even later, in which case the cumulative curve plateaus
above 100%).
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from typing import Any

from app.db import raf_cursor

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Public: get_decay_curve
# ---------------------------------------------------------------------------

def get_decay_curve(
    tenant_id: str | int,
    current_year: int,
    lookback_years: int = 3,
) -> dict[str, Any]:
    """Return monthly closure trajectory grouped by gap cohort year.

    Args:
        tenant_id: Tenant scope (string or int — coerced to string for SQL).
        current_year: The "anchor" year. The cohorts returned are
            ``[current_year - lookback_years + 1 ... current_year]``.
        lookback_years: How many cohort years to include (default 3).
            Clamped to ``[1, 10]``.

    Returns:
        ``{"current_year": int, "lookback_years": int,
           "cohorts": [{"cohort_year": int, "total_gaps": int,
                        "closed_gaps": int,
                        "points": [{"month_of_year": 1..12,
                                    "closure_rate": float,   # closed in this month / total
                                    "cumulative_closed_pct": float,
                                    "$_recaptured": float,
                                    "closed_count": int}, ...]}]}``

    Notes:
        * ``closure_rate`` and ``cumulative_closed_pct`` are returned as
          fractions in [0, 1] for easy chart rendering — the frontend can
          multiply by 100 for display.
        * Months with zero closures are still emitted so the line chart has
          a complete x-axis (Jan-Dec).
        * If a cohort has zero gaps the cohort is still returned so the
          consumer can show "no data" badges next to that year.
    """
    lookback = max(1, min(int(lookback_years), 10))
    earliest_year = int(current_year) - lookback + 1
    tid = str(tenant_id) if tenant_id is not None else "1"

    # One query per request — pull all rows for cohorts in range, group in Python.
    # DEFENSIVE: current_year / revenue_impact / resolved_at may not exist if the
    # schema was created from the legacy migration (add_recapture_ai_suggestions.sql)
    # before the service-layer DDL columns were added.  On any DB error we log and
    # return an empty payload so the frontend renders the empty-state chart instead
    # of a red error banner.
    sql = """
        SELECT
            current_year,
            status,
            resolved_at,
            revenue_impact
        FROM recapture_gaps
        WHERE tenant_id    = %s
          AND current_year BETWEEN %s AND %s
    """
    try:
        with raf_cursor() as cursor:
            cursor.execute(sql, (tid, earliest_year, int(current_year)))
            rows = cursor.fetchall()
    except Exception as _db_exc:
        logger.error(
            "get_decay_curve: DB error tenant=%s year=%s lookback=%s — returning empty; %s",
            tid, current_year, lookback, _db_exc, exc_info=True,
        )
        return {
            "current_year": int(current_year),
            "lookback_years": lookback,
            "cohorts": [],
            "degraded": True,
        }

    # cohort_year -> {"total": int, "by_month": {1..12: {"closed": int, "$": float}}}
    buckets: dict[int, dict[str, Any]] = {
        y: {
            "total": 0,
            "closed": 0,
            "by_month": {m: {"closed": 0, "dollars": 0.0} for m in range(1, 13)},
        }
        for y in range(earliest_year, int(current_year) + 1)
    }

    for row in rows:
        cy = int(row["current_year"])
        if cy not in buckets:
            continue
        buckets[cy]["total"] += 1

        if row["status"] == "recaptured" and row["resolved_at"] is not None:
            month = _safe_month(row["resolved_at"])
            buckets[cy]["closed"] += 1
            buckets[cy]["by_month"][month]["closed"] += 1
            buckets[cy]["by_month"][month]["dollars"] += float(row["revenue_impact"] or 0.0)

    cohorts: list[dict[str, Any]] = []
    for year in sorted(buckets.keys()):
        b = buckets[year]
        total = b["total"]
        cumulative = 0
        cumulative_dollars = 0.0
        points: list[dict[str, Any]] = []
        for m in range(1, 13):
            mb = b["by_month"][m]
            cumulative += mb["closed"]
            cumulative_dollars += mb["dollars"]
            closure_rate = (mb["closed"] / total) if total > 0 else 0.0
            cumulative_pct = (cumulative / total) if total > 0 else 0.0
            points.append({
                "month_of_year": m,
                "closed_count": mb["closed"],
                "closure_rate": round(closure_rate, 4),
                "cumulative_closed_pct": round(cumulative_pct, 4),
                "$_recaptured": round(mb["dollars"], 2),
                "cumulative_$_recaptured": round(cumulative_dollars, 2),
            })
        cohorts.append({
            "cohort_year": year,
            "total_gaps": total,
            "closed_gaps": b["closed"],
            "points": points,
        })

    return {
        "current_year": int(current_year),
        "lookback_years": lookback,
        "cohorts": cohorts,
    }


# ---------------------------------------------------------------------------
# Public: get_velocity_kpis
# ---------------------------------------------------------------------------

def get_velocity_kpis(
    tenant_id: str | int,
    year: int,
    today: date | None = None,
) -> dict[str, Any]:
    """Return CFO-grade velocity scorecard for the given measurement year.

    Args:
        tenant_id: Tenant scope.
        year: Measurement (current) year.
        today: Override "today" — used by tests to make computations
            deterministic. Defaults to ``date.today()``.

    Returns:
        Dict with keys:
            avg_days_to_close              float — mean days from created → resolved
            median_days_to_close           float — median (linear interpolation if even)
            ytd_$_recaptured               float — $ of gaps recaptured year-to-date
            ye_projected_$                 float — linear YTD extrapolation to year-end
            days_remaining_in_year         int
            days_to_close_target_30        float — % of cohort closed within 30 days [0..1]
            early_recapture_rate           float — % of cohort closures landing in Q1 [0..1]
            late_recapture_rate            float — % of cohort closures landing in Q4 [0..1]
            total_cohort_gaps              int
            closed_cohort_gaps             int
            open_cohort_gaps               int
    """
    tid = str(tenant_id) if tenant_id is not None else "1"
    today = today or datetime.now(timezone.utc).date()

    sql = """
        SELECT
            status,
            created_at,
            resolved_at,
            revenue_impact
        FROM recapture_gaps
        WHERE tenant_id    = %s
          AND current_year = %s
    """
    try:
        with raf_cursor() as cursor:
            cursor.execute(sql, (tid, int(year)))
            rows = cursor.fetchall()
    except Exception as _db_exc:
        logger.error(
            "get_velocity_kpis: DB error tenant=%s year=%s — returning empty; %s",
            tid, year, _db_exc, exc_info=True,
        )
        return {
            "year": int(year),
            "avg_days_to_close": 0.0,
            "median_days_to_close": 0.0,
            "ytd_$_recaptured": 0.0,
            "ye_projected_$": 0.0,
            "days_remaining_in_year": 0,
            "days_to_close_target_30": 0.0,
            "early_recapture_rate": 0.0,
            "late_recapture_rate": 0.0,
            "total_cohort_gaps": 0,
            "closed_cohort_gaps": 0,
            "open_cohort_gaps": 0,
            "degraded": True,
        }

    days_to_close: list[float] = []
    ytd_dollars = 0.0
    closed_count = 0
    closed_within_30 = 0
    q1_closed = 0
    q4_closed = 0
    closed_with_resolved_at = 0
    open_count = 0
    total = len(rows)

    for r in rows:
        status = r["status"]
        if status == "recaptured" and r["resolved_at"] is not None:
            closed_count += 1
            ytd_dollars += float(r["revenue_impact"] or 0.0)
            created = _coerce_dt(r["created_at"])
            resolved = _coerce_dt(r["resolved_at"])
            if created and resolved:
                delta_days = (resolved - created).total_seconds() / 86400.0
                if delta_days < 0:
                    delta_days = 0.0
                days_to_close.append(delta_days)
                if delta_days <= 30:
                    closed_within_30 += 1
                closed_with_resolved_at += 1
                month = _safe_month(resolved)
                if month <= 3:
                    q1_closed += 1
                elif month >= 10:
                    q4_closed += 1
        elif status == "open":
            open_count += 1

    avg_days = sum(days_to_close) / len(days_to_close) if days_to_close else 0.0
    median_days = _median(days_to_close) if days_to_close else 0.0

    # Linear YTD → year-end projection (proportional to days elapsed)
    days_into_year = (today - date(year, 1, 1)).days + 1
    days_into_year = max(1, days_into_year)
    days_in_year = 366 if _is_leap(year) else 365
    days_remaining = max(0, days_in_year - days_into_year)

    if today.year == year:
        # Current calendar year — YTD trend is the only signal we have
        ye_projected = ytd_dollars * (days_in_year / days_into_year)
    elif today.year > year:
        # Year is fully elapsed; final number is simply the YTD figure
        ye_projected = ytd_dollars
    else:
        # Year is in the future — no signal yet
        ye_projected = 0.0

    return {
        "year": int(year),
        "avg_days_to_close": round(avg_days, 1),
        "median_days_to_close": round(median_days, 1),
        "ytd_$_recaptured": round(ytd_dollars, 2),
        "ye_projected_$": round(ye_projected, 2),
        "days_remaining_in_year": int(days_remaining),
        "days_to_close_target_30": round(
            (closed_within_30 / closed_with_resolved_at) if closed_with_resolved_at else 0.0,
            4,
        ),
        "early_recapture_rate": round(
            (q1_closed / closed_count) if closed_count else 0.0, 4,
        ),
        "late_recapture_rate": round(
            (q4_closed / closed_count) if closed_count else 0.0, 4,
        ),
        "total_cohort_gaps": int(total),
        "closed_cohort_gaps": int(closed_count),
        "open_cohort_gaps": int(open_count),
    }


# ---------------------------------------------------------------------------
# Public: get_top_slow_movers
# ---------------------------------------------------------------------------

def get_top_slow_movers(
    tenant_id: str | int,
    year: int,
    limit: int = 10,
) -> list[dict[str, Any]]:
    """Return HCCs with the slowest closure velocity (longest avg days-to-close).

    For each HCC code in the cohort:
        avg_days_to_close — mean over closed gaps with resolved_at
        open_count        — number of still-open gaps in this cohort
        $_at_risk         — sum(revenue_impact) of still-open gaps

    HCCs without any closed gaps still surface — they're sorted to the top
    using ``inf`` because "we have no idea how slow they are AND nothing has
    closed" is the worst possible signal.

    Args:
        tenant_id: Tenant scope.
        year: Cohort year.
        limit: Max rows returned (default 10, clamped to [1, 100]).
    """
    tid = str(tenant_id) if tenant_id is not None else "1"
    cap = max(1, min(int(limit), 100))

    sql = """
        SELECT
            hcc_code,
            status,
            created_at,
            resolved_at,
            revenue_impact
        FROM recapture_gaps
        WHERE tenant_id    = %s
          AND current_year = %s
    """
    try:
        with raf_cursor() as cursor:
            cursor.execute(sql, (tid, int(year)))
            rows = cursor.fetchall()
    except Exception as _db_exc:
        logger.error(
            "get_top_slow_movers: DB error tenant=%s year=%s — returning empty; %s",
            tid, year, _db_exc, exc_info=True,
        )
        return []

    # hcc_code -> {"days":[..], "open":int, "at_risk":float, "total":int, "closed":int}
    buckets: dict[str, dict[str, Any]] = {}
    for r in rows:
        code = str(r["hcc_code"])
        b = buckets.setdefault(code, {
            "days": [], "open": 0, "at_risk": 0.0, "total": 0, "closed": 0,
        })
        b["total"] += 1
        if r["status"] == "open":
            b["open"] += 1
            b["at_risk"] += float(r["revenue_impact"] or 0.0)
        elif r["status"] == "recaptured" and r["resolved_at"] is not None:
            b["closed"] += 1
            created = _coerce_dt(r["created_at"])
            resolved = _coerce_dt(r["resolved_at"])
            if created and resolved:
                delta = (resolved - created).total_seconds() / 86400.0
                b["days"].append(max(delta, 0.0))

    # Lazy import to avoid a hard dep cycle on description lookup
    try:
        from app.services.recapture_gap_service import _hcc_description
    except Exception:  # pragma: no cover — defensive
        logger.debug("swallowed exception", exc_info=True)
        def _hcc_description(c: str) -> str:
            return f"HCC {c}"

    enriched: list[dict[str, Any]] = []
    for code, b in buckets.items():
        avg_days = (sum(b["days"]) / len(b["days"])) if b["days"] else None
        enriched.append({
            "hcc_code": code,
            "description": _hcc_description(code),
            "avg_days_to_close": round(avg_days, 1) if avg_days is not None else None,
            "open_count": int(b["open"]),
            "$_at_risk": round(b["at_risk"], 2),
            "total_gaps": int(b["total"]),
            "closed_count": int(b["closed"]),
        })

    # Slowest first: HCCs with no closed gaps go first (avg_days=None → inf),
    # then highest avg_days, tie-break by $_at_risk desc.
    def _sort_key(item: dict[str, Any]) -> tuple[float, float]:
        avg = item["avg_days_to_close"]
        return (
            -(float("inf") if avg is None else avg),
            -item["$_at_risk"],
        )

    enriched.sort(key=_sort_key)
    return enriched[:cap]


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _safe_month(value: Any) -> int:
    """Coerce date/datetime/string → month-of-year (1..12).

    Returns 12 if the value cannot be parsed (so the closure still counts —
    we'd rather assign it to December than drop it on the floor).
    """
    if isinstance(value, datetime):
        return value.month
    if isinstance(value, date):
        return value.month
    if isinstance(value, str):
        try:
            # Accept both "2026-03-15" and full ISO timestamps
            return datetime.fromisoformat(value.replace("Z", "+00:00")).month
        except ValueError:
            return 12
    return 12


def _coerce_dt(value: Any) -> datetime | None:
    """Best-effort conversion to a naive datetime for arithmetic."""
    if value is None:
        return None
    if isinstance(value, datetime):
        # Strip tzinfo so we can subtract two values uniformly
        return value.replace(tzinfo=None)
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day)
    if isinstance(value, str):
        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return dt.replace(tzinfo=None)
        except ValueError:
            return None
    return None


def _median(values: list[float]) -> float:
    n = len(values)
    if n == 0:
        return 0.0
    s = sorted(values)
    mid = n // 2
    if n % 2 == 1:
        return s[mid]
    return (s[mid - 1] + s[mid]) / 2.0


def _is_leap(year: int) -> bool:
    return (year % 4 == 0 and year % 100 != 0) or (year % 400 == 0)
