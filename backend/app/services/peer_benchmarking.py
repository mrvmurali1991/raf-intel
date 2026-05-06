"""
Peer benchmarking service.

Computes percentile rank of a single provider's KPIs against the cohort of
providers sharing the same `specialty`.  Also returns cohort-level summary
statistics (n, min, median, max) so the UI can render benchmarking tables.

KPIs tracked (all higher-is-better):
    - average_raf
    - hcc_capture_rate
    - recapture_rate
    - meat_completeness_avg
    - revenue_opportunity
    - documentation_quality_score

Source of truth is `provider_scorecard_snapshots` (one row per
provider/measurement_year, freshest snapshot wins).  Cohort membership is
derived by joining to `providers.specialty`.

Small-cohort handling
---------------------
If a provider's specialty cohort contains fewer than `MIN_COHORT_SIZE`
peers (default 3, including the provider themselves), percentile values
are returned as ``None`` and the response is flagged with
``"insufficient_peers": True``.  This avoids the misleading "100th
percentile because n=1" failure mode.

All math is deterministic — no LLM call, no caching beyond the per-request
DB read.
"""
from __future__ import annotations

import logging
from datetime import date
from typing import Any, Iterable

from app.db import raf_cursor

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# KPI column names — must match `provider_scorecard_snapshots` schema.
KPI_FIELDS: tuple[str, ...] = (
    "average_raf",
    "hcc_capture_rate",
    "recapture_rate",
    "meat_completeness_avg",
    "revenue_opportunity",
    "documentation_quality_score",
)

# Minimum cohort size (incl. provider) before percentile is meaningful.
MIN_COHORT_SIZE: int = 3


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _current_year() -> int:
    return date.today().year


def _percentile_rank(value: float, peers: Iterable[float]) -> float:
    """
    Standard percentile rank: percent of cohort scoring **at or below** `value`.
    Returns 0..100.  All higher-is-better (caller must ensure value/peers
    are oriented that way).

    If `peers` is empty, returns 0.0 — caller is expected to gate this with
    cohort-size check first.
    """
    peers_list = [p for p in peers if p is not None]
    if not peers_list:
        return 0.0
    n = len(peers_list)
    at_or_below = sum(1 for p in peers_list if p <= value)
    return round(100.0 * at_or_below / n, 1)


def _summary_stats(values: list[float]) -> dict[str, float | None]:
    """min / median / max — None when no data."""
    if not values:
        return {"min": None, "median": None, "max": None}
    sorted_vals = sorted(values)
    n = len(sorted_vals)
    if n % 2 == 1:
        median = sorted_vals[n // 2]
    else:
        median = (sorted_vals[n // 2 - 1] + sorted_vals[n // 2]) / 2.0
    return {
        "min": round(float(sorted_vals[0]), 4),
        "median": round(float(median), 4),
        "max": round(float(sorted_vals[-1]), 4),
    }


# ---------------------------------------------------------------------------
# DB access
# ---------------------------------------------------------------------------

def _provider_specialty(provider_id: int) -> str | None:
    """Look up a provider's specialty string.  Returns None if unknown."""
    try:
        with raf_cursor() as cur:
            cur.execute(
                "SELECT specialty FROM providers WHERE id = %s LIMIT 1",
                (provider_id,),
            )
            row = cur.fetchone()
        if row and row.get("specialty"):
            return str(row["specialty"]).strip() or None
    except Exception as exc:
        logger.warning("_provider_specialty pid=%s: %s", provider_id, exc)
    return None


def _cohort_snapshots(
    specialty: str, measurement_year: int
) -> list[dict[str, Any]]:
    """
    Return the freshest snapshot per provider in the given specialty cohort
    for `measurement_year`.

    Uses a window-function-free query (MySQL 5.7-compatible): correlated
    subquery picks the latest `calculated_at` row per provider.
    """
    sql = """
        SELECT s.provider_id,
               p.first_name, p.last_name, p.full_name, p.specialty,
               s.average_raf, s.hcc_capture_rate, s.recapture_rate,
               s.meat_completeness_avg, s.revenue_opportunity,
               s.documentation_quality_score, s.percentile_rank,
               s.total_patients, s.patients_with_scores,
               s.calculated_at
        FROM provider_scorecard_snapshots s
        JOIN providers p ON p.id = s.provider_id
        WHERE s.measurement_year = %s
          AND p.specialty = %s
          AND s.calculated_at = (
              SELECT MAX(s2.calculated_at)
              FROM provider_scorecard_snapshots s2
              WHERE s2.provider_id = s.provider_id
                AND s2.measurement_year = s.measurement_year
          )
        ORDER BY s.average_raf DESC
    """
    try:
        with raf_cursor() as cur:
            cur.execute(sql, (measurement_year, specialty))
            return list(cur.fetchall() or [])
    except Exception as exc:
        logger.warning(
            "_cohort_snapshots specialty=%s year=%s: %s",
            specialty, measurement_year, exc,
        )
        return []


def _all_specialties(measurement_year: int) -> list[str]:
    """Distinct specialties that have at least one snapshot for the year."""
    sql = """
        SELECT DISTINCT p.specialty
        FROM provider_scorecard_snapshots s
        JOIN providers p ON p.id = s.provider_id
        WHERE s.measurement_year = %s
          AND p.specialty IS NOT NULL
          AND p.specialty <> ''
        ORDER BY p.specialty
    """
    try:
        with raf_cursor() as cur:
            cur.execute(sql, (measurement_year,))
            rows = cur.fetchall() or []
        return [str(r["specialty"]).strip() for r in rows if r.get("specialty")]
    except Exception as exc:
        logger.warning("_all_specialties year=%s: %s", measurement_year, exc)
        return []


# ---------------------------------------------------------------------------
# Public: percentiles for one provider
# ---------------------------------------------------------------------------

def compute_percentiles(
    provider_id: int,
    measurement_year: int | None = None,
) -> dict[str, Any]:
    """
    Compute the provider's percentile rank vs their specialty cohort for
    each KPI in :data:`KPI_FIELDS`.

    Returns a dict shaped::

        {
          "provider_id": 7,
          "specialty": "Internal Medicine",
          "measurement_year": 2026,
          "cohort_size": 5,                  # incl. this provider
          "insufficient_peers": False,
          "provider_kpis":   {kpi: float | None, ...},
          "percentiles":     {kpi: float (0..100) | None, ...},
          "cohort_summary":  {kpi: {"min":..,"median":..,"max":..}, ...},
        }

    When the cohort has fewer than :data:`MIN_COHORT_SIZE` providers the
    percentile values are all ``None`` and ``insufficient_peers`` is ``True``.
    """
    year = measurement_year or _current_year()
    specialty = _provider_specialty(provider_id)

    base = {
        "provider_id": provider_id,
        "specialty": specialty,
        "measurement_year": year,
        "cohort_size": 0,
        "insufficient_peers": True,
        "provider_kpis": {k: None for k in KPI_FIELDS},
        "percentiles": {k: None for k in KPI_FIELDS},
        "cohort_summary": {
            k: {"min": None, "median": None, "max": None} for k in KPI_FIELDS
        },
    }

    if not specialty:
        return base

    cohort = _cohort_snapshots(specialty, year)
    base["cohort_size"] = len(cohort)

    # Find this provider's row inside the cohort.
    self_row = next(
        (r for r in cohort if int(r["provider_id"]) == int(provider_id)),
        None,
    )
    if self_row:
        base["provider_kpis"] = {
            k: (float(self_row[k]) if self_row.get(k) is not None else None)
            for k in KPI_FIELDS
        }

    # Cohort summary (always computed when ≥1 row)
    for kpi in KPI_FIELDS:
        vals = [
            float(r[kpi]) for r in cohort
            if r.get(kpi) is not None
        ]
        base["cohort_summary"][kpi] = _summary_stats(vals)

    # Percentile only meaningful with enough peers
    if len(cohort) < MIN_COHORT_SIZE or self_row is None:
        return base

    base["insufficient_peers"] = False
    for kpi in KPI_FIELDS:
        my_val = base["provider_kpis"][kpi]
        if my_val is None:
            base["percentiles"][kpi] = None
            continue
        peer_vals = [
            float(r[kpi]) for r in cohort
            if r.get(kpi) is not None
        ]
        base["percentiles"][kpi] = _percentile_rank(my_val, peer_vals)

    return base


# ---------------------------------------------------------------------------
# Public: cohort summary for a single specialty
# ---------------------------------------------------------------------------

def specialty_cohort_summary(
    specialty: str,
    measurement_year: int | None = None,
) -> dict[str, Any]:
    """
    Return cohort size + per-KPI summary for a specialty.

    Useful for the specialty-benchmarking dashboard tab.
    """
    year = measurement_year or _current_year()
    cohort = _cohort_snapshots(specialty, year)
    summary: dict[str, dict[str, float | None]] = {}
    for kpi in KPI_FIELDS:
        vals = [float(r[kpi]) for r in cohort if r.get(kpi) is not None]
        summary[kpi] = _summary_stats(vals)

    return {
        "specialty": specialty,
        "measurement_year": year,
        "cohort_size": len(cohort),
        "insufficient_peers": len(cohort) < MIN_COHORT_SIZE,
        "cohort_summary": summary,
    }


# ---------------------------------------------------------------------------
# Public: org-wide specialty benchmarking
# ---------------------------------------------------------------------------

def specialty_benchmarks(
    measurement_year: int | None = None,
) -> dict[str, Any]:
    """
    Return a list of specialty cohorts, each with the provider rows + their
    per-KPI percentile inside the cohort.

    Shape::

        {
          "measurement_year": 2026,
          "specialties": [
            {
              "specialty": "Internal Medicine",
              "cohort_size": 4,
              "insufficient_peers": False,
              "cohort_summary": {kpi: {min,median,max}, ...},
              "providers": [
                {
                  "provider_id": 7, "first_name": "...", "last_name": "...",
                  "kpis": {kpi: value | None, ...},
                  "percentiles": {kpi: 0..100 | None, ...},
                },
                ...
              ],
            },
            ...
          ],
        }
    """
    year = measurement_year or _current_year()
    specialties = _all_specialties(year)

    out: list[dict[str, Any]] = []
    for specialty in specialties:
        cohort = _cohort_snapshots(specialty, year)
        n = len(cohort)
        insufficient = n < MIN_COHORT_SIZE

        # Pre-compute peer value lists once per KPI for percentile reuse.
        peer_vals: dict[str, list[float]] = {}
        for kpi in KPI_FIELDS:
            peer_vals[kpi] = [
                float(r[kpi]) for r in cohort if r.get(kpi) is not None
            ]

        summary = {kpi: _summary_stats(peer_vals[kpi]) for kpi in KPI_FIELDS}

        providers_out: list[dict[str, Any]] = []
        for r in cohort:
            kpi_values = {
                k: (float(r[k]) if r.get(k) is not None else None)
                for k in KPI_FIELDS
            }
            pct = {k: None for k in KPI_FIELDS}
            if not insufficient:
                for k in KPI_FIELDS:
                    v = kpi_values[k]
                    if v is None or not peer_vals[k]:
                        continue
                    pct[k] = _percentile_rank(v, peer_vals[k])

            providers_out.append({
                "provider_id": int(r["provider_id"]),
                "first_name": r.get("first_name") or "",
                "last_name": r.get("last_name") or "",
                "full_name": r.get("full_name") or "",
                "specialty": specialty,
                "kpis": kpi_values,
                "percentiles": pct,
            })

        out.append({
            "specialty": specialty,
            "cohort_size": n,
            "insufficient_peers": insufficient,
            "cohort_summary": summary,
            "providers": providers_out,
        })

    return {"measurement_year": year, "specialties": out}
