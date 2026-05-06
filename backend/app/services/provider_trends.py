"""
Provider Year-over-Year (YoY) trend service.

Returns historical RAF / recapture / capture / revenue series for a single
provider (sparkline) or aggregated across the tenant (header strip).  Data
is sourced from `provider_scorecard_snapshots` — the latest snapshot per
calendar (measurement) year is taken as that year's authoritative datapoint.

Schema gotchas
--------------
- `provider_scorecard_snapshots` has NO `tenant_id` column.  Tenant scoping
  is achieved by joining on `providers.tenant_id`.
- The DB may contain only a single measurement_year (e.g. 2026 only) — all
  delta calculations gracefully degrade to ``None`` in that case.
- ``calculated_at`` is a naive MySQL DATETIME; we serialize via ``str()``.

Output shape (per metric)
-------------------------
::

    {
      "values":          [{year, value, calculated_at}, ...],   # ascending
      "current":         <float | None>,
      "delta_vs_prior_year": <float | None>,
      "delta_vs_4y":     <float | None>,
    }

The wrapper response includes::

    {
      "provider_id":      123,
      "metrics":          {"raf": {...}, "recapture": {...}, ...},
      "years_available":  [2023, 2024, 2025, 2026],
      "single_year_only": false,
    }
"""

from __future__ import annotations

import logging
from typing import Any, Iterable

from app.db import raf_cursor

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Metric → DB column registry
# ---------------------------------------------------------------------------

#: Mapping of public metric keys → physical column on
#: provider_scorecard_snapshots.  Centralised so callers never spell-check
#: column names by hand and so adding a metric is a one-line change.
METRIC_COLUMNS: dict[str, str] = {
    "raf": "average_raf",
    "recapture": "recapture_rate",
    "capture": "hcc_capture_rate",
    "revenue": "revenue_opportunity",
}

DEFAULT_METRICS: list[str] = ["raf", "recapture", "capture", "revenue"]
DEFAULT_YEARS: int = 4
MAX_YEARS: int = 10


def _validate_metrics(metrics: Iterable[str] | None) -> list[str]:
    """Filter to known metric keys; fall back to DEFAULT_METRICS if empty."""
    if not metrics:
        return list(DEFAULT_METRICS)
    cleaned = [m for m in metrics if m in METRIC_COLUMNS]
    return cleaned or list(DEFAULT_METRICS)


def _clamp_years(years: int | None) -> int:
    if not years or years < 1:
        return DEFAULT_YEARS
    return min(int(years), MAX_YEARS)


# ---------------------------------------------------------------------------
# Single-provider trend
# ---------------------------------------------------------------------------

def _fetch_provider_yearly_rows(
    provider_id: int,
    columns: list[str],
    years: int,
) -> list[dict[str, Any]]:
    """
    Return one row per measurement_year for the requested provider, choosing
    the most recently `calculated_at` snapshot when multiple exist for the
    same year.  Result is ordered DESCENDING by year and limited to `years`.

    The latest-per-year selection is implemented via a correlated subquery so
    we don't depend on MySQL window functions (still common to be off on
    older 5.7-era replicas in test envs).
    """
    if not columns:
        return []

    select_cols = ", ".join(f"s.{c}" for c in columns)
    sql = f"""
        SELECT s.measurement_year,
               s.calculated_at,
               {select_cols}
        FROM provider_scorecard_snapshots s
        WHERE s.provider_id = %s
          AND s.calculated_at = (
                SELECT MAX(s2.calculated_at)
                FROM provider_scorecard_snapshots s2
                WHERE s2.provider_id      = s.provider_id
                  AND s2.measurement_year = s.measurement_year
          )
        ORDER BY s.measurement_year DESC
        LIMIT %s
    """
    try:
        with raf_cursor() as cur:
            cur.execute(sql, (provider_id, int(years)))
            return list(cur.fetchall() or [])
    except Exception as exc:
        logger.warning(
            "_fetch_provider_yearly_rows pid=%s years=%s: %s",
            provider_id, years, exc,
        )
        return []


def _build_metric_block(
    rows: list[dict[str, Any]],
    column: str,
) -> dict[str, Any]:
    """
    Convert raw DB rows into the public `{values, current, delta_*}` shape
    for a single metric column.
    """
    # Rows arrived DESC by year; we need ASC for the sparkline.
    asc = sorted(rows, key=lambda r: int(r["measurement_year"]))

    values: list[dict[str, Any]] = []
    for r in asc:
        raw = r.get(column)
        if raw is None:
            value: float | None = None
        else:
            try:
                value = float(raw)
            except (TypeError, ValueError):
                value = None
        values.append({
            "year": int(r["measurement_year"]),
            "value": value,
            "calculated_at": str(r.get("calculated_at") or ""),
        })

    numeric = [v for v in values if v["value"] is not None]
    current = numeric[-1]["value"] if numeric else None

    # Delta vs prior year — last two distinct numeric points.
    delta_prior: float | None = None
    if len(numeric) >= 2:
        delta_prior = round(numeric[-1]["value"] - numeric[-2]["value"], 6)

    # Delta vs ~4-year-ago (i.e. the earliest point in this window).
    delta_4y: float | None = None
    if len(numeric) >= 2:
        delta_4y = round(numeric[-1]["value"] - numeric[0]["value"], 6)

    return {
        "values": values,
        "current": current,
        "delta_vs_prior_year": delta_prior,
        "delta_vs_4y": delta_4y,
    }


def get_provider_trend(
    provider_id: int,
    metrics: Iterable[str] | None = None,
    years: int = DEFAULT_YEARS,
) -> dict[str, Any]:
    """
    Build a multi-metric YoY trend payload for one provider.

    See module docstring for response shape.  Always returns a valid payload
    even if the provider has no snapshots (`values` will be empty lists).
    """
    metric_keys = _validate_metrics(metrics)
    year_limit = _clamp_years(years)
    columns = [METRIC_COLUMNS[m] for m in metric_keys]

    rows = _fetch_provider_yearly_rows(int(provider_id), columns, year_limit)

    blocks: dict[str, Any] = {}
    for key in metric_keys:
        blocks[key] = _build_metric_block(rows, METRIC_COLUMNS[key])

    years_available = sorted({int(r["measurement_year"]) for r in rows})
    return {
        "provider_id": int(provider_id),
        "metrics": blocks,
        "years_available": years_available,
        "single_year_only": len(years_available) <= 1,
        "years_requested": year_limit,
    }


# ---------------------------------------------------------------------------
# Tenant-aggregate trend
# ---------------------------------------------------------------------------

def _fetch_tenant_yearly_rows(
    tenant_id: int | str | None,
    column: str,
    years: int,
) -> list[dict[str, Any]]:
    """
    For each (provider, measurement_year), pick the latest snapshot, then
    average the requested column across all active providers in the tenant.
    Returns rows of {measurement_year, value} ordered DESC.

    Single-tenant deployments may pass `tenant_id=None` — we then aggregate
    across every provider the join produces.
    """
    tid = int(tenant_id) if tenant_id is not None and str(tenant_id).isdigit() else None

    where_extra = ""
    params: list[Any] = []
    if tid is not None:
        # providers.tenant_id is VARCHAR(50) — compare both as strings to
        # avoid implicit-cast surprises.
        where_extra = " AND CAST(p.tenant_id AS CHAR) = %s"
        params.append(str(tid))

    sql = f"""
        SELECT s.measurement_year,
               AVG(s.{column}) AS value
        FROM provider_scorecard_snapshots s
        JOIN providers p ON p.id = s.provider_id
        WHERE s.calculated_at = (
                SELECT MAX(s2.calculated_at)
                FROM provider_scorecard_snapshots s2
                WHERE s2.provider_id      = s.provider_id
                  AND s2.measurement_year = s.measurement_year
          )
          AND COALESCE(p.status, 'active') = 'active'
          {where_extra}
        GROUP BY s.measurement_year
        ORDER BY s.measurement_year DESC
        LIMIT %s
    """
    params.append(int(years))

    try:
        with raf_cursor() as cur:
            cur.execute(sql, tuple(params))
            return list(cur.fetchall() or [])
    except Exception as exc:
        logger.warning(
            "_fetch_tenant_yearly_rows tenant=%s col=%s: %s",
            tenant_id, column, exc,
        )
        return []


def get_tenant_aggregate_trend(
    metric: str = "raf",
    years: int = DEFAULT_YEARS,
    tenant_id: int | str | None = None,
) -> dict[str, Any]:
    """
    Tenant-wide average for a single metric across the last N years.  Useful
    for dashboard headers ("Org-wide RAF over time").
    """
    if metric not in METRIC_COLUMNS:
        metric = "raf"
    year_limit = _clamp_years(years)
    column = METRIC_COLUMNS[metric]

    rows = _fetch_tenant_yearly_rows(tenant_id, column, year_limit)

    asc = sorted(rows, key=lambda r: int(r["measurement_year"]))
    values: list[dict[str, Any]] = []
    for r in asc:
        raw = r.get("value")
        try:
            value = float(raw) if raw is not None else None
        except (TypeError, ValueError):
            value = None
        values.append({
            "year": int(r["measurement_year"]),
            "value": value,
            # No calculated_at on aggregates — averaged across many rows.
            "calculated_at": None,
        })

    numeric = [v for v in values if v["value"] is not None]
    current = numeric[-1]["value"] if numeric else None
    delta_prior = (
        round(numeric[-1]["value"] - numeric[-2]["value"], 6)
        if len(numeric) >= 2 else None
    )
    delta_4y = (
        round(numeric[-1]["value"] - numeric[0]["value"], 6)
        if len(numeric) >= 2 else None
    )

    return {
        "tenant_id": tenant_id if tenant_id is not None else "default",
        "metric": metric,
        "values": values,
        "current": current,
        "delta_vs_prior_year": delta_prior,
        "delta_vs_4y": delta_4y,
        "years_available": [v["year"] for v in values],
        "single_year_only": len(values) <= 1,
    }
