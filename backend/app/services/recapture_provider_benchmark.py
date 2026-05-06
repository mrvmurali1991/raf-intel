"""
Provider Peer Benchmarking on Recapture Rate.

Computes per-provider recapture performance and ranks each provider against
peers in the same specialty as well as the network-wide cohort.  Behavioral
levers — providers respond strongly to peer comparison, which is the same
mechanism Inovalon's leaderboards exploit.

Math
----
For each provider P with attributed gaps:

    panel_size      = COUNT(DISTINCT patient_id) on provider_patient_panel
    total_gaps      = COUNT(*) of recapture_gaps where patient_id ∈ panel
    gaps_open       = total_gaps where status = 'open'
    gaps_closed     = total_gaps where status = 'recaptured'
    recapture_rate  = gaps_closed / (gaps_open + gaps_closed)
    $_recaptured    = SUM(revenue_impact) where status = 'recaptured'
    $_at_risk       = SUM(revenue_impact) where status = 'open'

Cohort statistics (per specialty) and percentile ranks fall back gracefully
when n<3 by returning ``insufficient_peers=True`` rather than emitting a
misleading 100th-percentile reading off a single peer.

NOTE
----
We deliberately do NOT modify recapture_gap_service.py or provider_service.py
(per task constraints).  The aggregation re-derives recapture math from the
``recapture_gaps`` and ``provider_patient_panel`` tables.
"""

from __future__ import annotations

import logging
import statistics
from datetime import date
from typing import Any

from app.db import raf_cursor

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Minimum cohort size (incl. the provider) before percentile is meaningful.
# n=2 would give either 0% or 100% which is misleading.
MIN_COHORT_SIZE: int = 3


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _current_year() -> int:
    return date.today().year


def _resolve_tid(tenant_id: int | str | None) -> int:
    """Match the project-wide convention: fall back to tenant 1 when omitted."""
    return int(tenant_id) if tenant_id is not None else 1


def _percentile_rank(value: float, peers: list[float]) -> float:
    """Standard percentile-rank: % of peers scoring at-or-below ``value``."""
    if not peers:
        return 0.0
    at_or_below = sum(1 for p in peers if p <= value)
    return round(100.0 * at_or_below / len(peers), 1)


def _quartiles(values: list[float]) -> tuple[float, float, float]:
    """Return (q1, median, q3).  Falls back to 0.0 on empty input."""
    if not values:
        return 0.0, 0.0, 0.0
    if len(values) == 1:
        v = values[0]
        return v, v, v
    sorted_vals = sorted(values)
    median = statistics.median(sorted_vals)
    # statistics.quantiles requires n>=2.
    try:
        q1, _, q3 = statistics.quantiles(sorted_vals, n=4)
    except statistics.StatisticsError:
        q1, q3 = sorted_vals[0], sorted_vals[-1]
    return float(q1), float(median), float(q3)


# ---------------------------------------------------------------------------
# 1. compute_provider_rates
# ---------------------------------------------------------------------------


def compute_provider_rates(
    tenant_id: int | str | None,
    year: int | None = None,
) -> list[dict[str, Any]]:
    """Per-provider recapture performance for the given measurement year.

    A gap is attributed to a provider if the gap's patient is on that
    provider's panel (``provider_patient_panel``).  A patient assigned to
    multiple providers will have the gap counted under each — peer
    benchmarking compares effort, not exclusivity.

    Args:
        tenant_id: Tenant scope.  Used for the ``recapture_gaps.tenant_id``
                   filter (stored as VARCHAR).
        year:      Measurement year.  Defaults to the current calendar year.

    Returns:
        List of dicts ordered by recapture_rate DESC, $_at_risk DESC::

            {
                "provider_id":   int,
                "provider_name": str,
                "npi":           str | None,
                "specialty":     str | None,
                "panel_size":    int,
                "total_gaps":    int,
                "gaps_open":     int,
                "gaps_closed":   int,
                "recapture_rate": float,    # 0..1
                "$_recaptured":  float,
                "$_at_risk":     float,
            }
    """
    tid = _resolve_tid(tenant_id)
    yr = year or _current_year()

    # Pull every active provider so providers with zero attributed gaps still
    # appear (panel_size>0 with no prior-year HCCs == 100% capture, not 0%).
    providers_sql = """
        SELECT id, npi, full_name, specialty
        FROM providers
        WHERE status = 'active'
        ORDER BY id
    """

    panel_sql = """
        SELECT provider_id, COUNT(DISTINCT patient_id) AS panel_size
        FROM provider_patient_panel
        GROUP BY provider_id
    """

    # Aggregate gaps per provider via the panel.  We INNER JOIN
    # provider_patient_panel on patient_id and tally by status.  Filter on
    # current_year so the leaderboard reflects the requested measurement
    # year.  recapture_gaps.tenant_id is VARCHAR — cast to str for safety.
    gaps_sql = """
        SELECT
            ppp.provider_id                                              AS provider_id,
            COUNT(*)                                                     AS total_gaps,
            SUM(CASE WHEN rg.status = 'open'        THEN 1 ELSE 0 END)   AS gaps_open,
            SUM(CASE WHEN rg.status = 'recaptured'  THEN 1 ELSE 0 END)   AS gaps_closed,
            COALESCE(SUM(CASE WHEN rg.status = 'recaptured'
                              THEN rg.revenue_impact END), 0)            AS dollars_recaptured,
            COALESCE(SUM(CASE WHEN rg.status = 'open'
                              THEN rg.revenue_impact END), 0)            AS dollars_at_risk
        FROM recapture_gaps rg
        INNER JOIN provider_patient_panel ppp
                ON ppp.patient_id = rg.patient_id
        WHERE rg.tenant_id   = %s
          AND rg.current_year = %s
        GROUP BY ppp.provider_id
    """

    with raf_cursor() as cur:
        cur.execute(providers_sql)
        providers = cur.fetchall() or []

        cur.execute(panel_sql)
        panels = {int(r["provider_id"]): int(r["panel_size"]) for r in (cur.fetchall() or [])}

        cur.execute(gaps_sql, (str(tid), int(yr)))
        gaps_by_provider = {
            int(r["provider_id"]): {
                "total_gaps":         int(r["total_gaps"] or 0),
                "gaps_open":          int(r["gaps_open"] or 0),
                "gaps_closed":        int(r["gaps_closed"] or 0),
                "dollars_recaptured": float(r["dollars_recaptured"] or 0.0),
                "dollars_at_risk":    float(r["dollars_at_risk"] or 0.0),
            }
            for r in (cur.fetchall() or [])
        }

    rows: list[dict[str, Any]] = []
    for p in providers:
        pid = int(p["id"])
        g = gaps_by_provider.get(pid, {
            "total_gaps": 0, "gaps_open": 0, "gaps_closed": 0,
            "dollars_recaptured": 0.0, "dollars_at_risk": 0.0,
        })
        denom = g["gaps_open"] + g["gaps_closed"]
        rate = round(g["gaps_closed"] / denom, 4) if denom > 0 else 0.0
        rows.append({
            "provider_id":      pid,
            "provider_name":    p.get("full_name") or "",
            "npi":              p.get("npi"),
            "specialty":        p.get("specialty"),
            "panel_size":       int(panels.get(pid, 0)),
            "total_gaps":       g["total_gaps"],
            "gaps_open":        g["gaps_open"],
            "gaps_closed":      g["gaps_closed"],
            "recapture_rate":   rate,
            "$_recaptured":     g["dollars_recaptured"],
            "$_at_risk":        g["dollars_at_risk"],
        })

    # Order: best recapture_rate first, then biggest dollars-at-risk to break
    # ties (so a 0% provider with $30k risk surfaces above a 0% provider with
    # $0 risk — the leaderboard's job is to drive action).
    rows.sort(key=lambda r: (-r["recapture_rate"], -r["$_at_risk"]))
    return rows


# ---------------------------------------------------------------------------
# 2. compute_specialty_cohorts
# ---------------------------------------------------------------------------


def compute_specialty_cohorts(
    tenant_id: int | str | None,
    year: int | None = None,
) -> dict[str, dict[str, Any]]:
    """Per-specialty cohort statistics for the given measurement year.

    Specialties with fewer than ``MIN_COHORT_SIZE`` providers still get a
    record but quartile values reflect the small sample (callers should
    cross-check ``n`` before drawing conclusions).

    Returns:
        ``{specialty: {n, median_rate, q1_rate, q3_rate, top_provider}}``
        where ``top_provider`` is the highest-rate provider's name within
        that specialty.
    """
    rows = compute_provider_rates(tenant_id=tenant_id, year=year)
    by_specialty: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        # Only include providers with at least 1 attributable gap so the
        # cohort reflects active recapture work, not "no patients had prior
        # HCCs to recapture in the first place".
        if r["total_gaps"] == 0:
            continue
        spec = (r.get("specialty") or "Unknown").strip() or "Unknown"
        by_specialty.setdefault(spec, []).append(r)

    cohorts: dict[str, dict[str, Any]] = {}
    for spec, members in by_specialty.items():
        rates = [m["recapture_rate"] for m in members]
        q1, med, q3 = _quartiles(rates)
        top = max(members, key=lambda m: m["recapture_rate"])
        cohorts[spec] = {
            "n":           len(members),
            "median_rate": round(med, 4),
            "q1_rate":     round(q1, 4),
            "q3_rate":     round(q3, 4),
            "top_provider": {
                "provider_id":    top["provider_id"],
                "provider_name":  top["provider_name"],
                "recapture_rate": top["recapture_rate"],
            },
        }
    return cohorts


# ---------------------------------------------------------------------------
# 3. provider_percentile
# ---------------------------------------------------------------------------


def provider_percentile(
    provider_id: int,
    tenant_id: int | str | None,
    year: int | None = None,
) -> dict[str, Any]:
    """Provider's percentile rank within specialty and across the network.

    Returns:
        {
            "provider_id":              int,
            "provider_name":            str,
            "specialty":                str | None,
            "recapture_rate":           float,
            "percentile_in_specialty":  float | None,
            "percentile_in_network":    float | None,
            "specialty_median":         float | None,
            "network_median":           float,
            "ranks_among_n":            int,    # specialty cohort size
            "insufficient_peers":       bool,
        }
    """
    rows = compute_provider_rates(tenant_id=tenant_id, year=year)
    me = next((r for r in rows if r["provider_id"] == int(provider_id)), None)
    if me is None:
        return {
            "provider_id":             int(provider_id),
            "provider_name":           None,
            "specialty":               None,
            "recapture_rate":          0.0,
            "percentile_in_specialty": None,
            "percentile_in_network":   None,
            "specialty_median":        None,
            "network_median":          0.0,
            "ranks_among_n":           0,
            "insufficient_peers":      True,
        }

    # Network cohort: every provider with at least 1 attributable gap.
    # (Excluding zero-gap providers prevents diluting the median with
    # providers who simply have no recapturable population.)
    network_members = [r for r in rows if r["total_gaps"] > 0]
    network_rates = [r["recapture_rate"] for r in network_members]

    # Specialty cohort: same restriction, plus same specialty.
    spec = (me.get("specialty") or "Unknown").strip() or "Unknown"
    specialty_members = [r for r in network_members if (r.get("specialty") or "Unknown").strip() == spec]
    specialty_rates = [r["recapture_rate"] for r in specialty_members]

    insufficient = len(specialty_members) < MIN_COHORT_SIZE
    pct_specialty: float | None
    pct_network: float | None
    spec_median: float | None

    if insufficient:
        pct_specialty = None
        spec_median = None
    else:
        pct_specialty = _percentile_rank(me["recapture_rate"], specialty_rates)
        spec_median = round(statistics.median(specialty_rates), 4)

    if len(network_members) < MIN_COHORT_SIZE:
        pct_network = None
        net_median = 0.0
    else:
        pct_network = _percentile_rank(me["recapture_rate"], network_rates)
        net_median = round(statistics.median(network_rates), 4)

    return {
        "provider_id":             me["provider_id"],
        "provider_name":           me["provider_name"],
        "specialty":               me.get("specialty"),
        "recapture_rate":          me["recapture_rate"],
        "percentile_in_specialty": pct_specialty,
        "percentile_in_network":   pct_network,
        "specialty_median":        spec_median,
        "network_median":          net_median,
        "ranks_among_n":           len(specialty_members),
        "insufficient_peers":      insufficient,
    }


# ---------------------------------------------------------------------------
# 4. provider_decay
# ---------------------------------------------------------------------------


def provider_decay(
    provider_id: int,
    year: int | None = None,
    lookback: int = 3,
    tenant_id: int | str | None = None,
) -> dict[str, Any]:
    """Per-year recapture rate for ``provider_id`` over the last ``lookback``
    measurement years.

    Used by the side-card sparkline ("trending up?  trending down?").

    Returns:
        {
            "provider_id":  int,
            "years":        [int, ...],          # ascending
            "rates":        [float, ...],        # 0..1, paired with years
            "deltas":       [float | None, ...], # year-over-year delta
        }
    """
    end_year = year or _current_year()
    start_year = end_year - max(0, int(lookback) - 1)
    tid = _resolve_tid(tenant_id)

    sql = """
        SELECT
            rg.current_year                                              AS yr,
            SUM(CASE WHEN rg.status = 'recaptured' THEN 1 ELSE 0 END)    AS gaps_closed,
            SUM(CASE WHEN rg.status IN ('open','recaptured') THEN 1 ELSE 0 END) AS gaps_total
        FROM recapture_gaps rg
        INNER JOIN provider_patient_panel ppp
                ON ppp.patient_id = rg.patient_id
        WHERE ppp.provider_id   = %s
          AND rg.tenant_id      = %s
          AND rg.current_year BETWEEN %s AND %s
        GROUP BY rg.current_year
        ORDER BY rg.current_year ASC
    """

    with raf_cursor() as cur:
        cur.execute(sql, (int(provider_id), str(tid), int(start_year), int(end_year)))
        rows = cur.fetchall() or []

    by_year = {int(r["yr"]): r for r in rows}
    years: list[int] = []
    rates: list[float] = []
    for y in range(start_year, end_year + 1):
        rec = by_year.get(y)
        if rec is None:
            rate = 0.0
        else:
            total = int(rec["gaps_total"] or 0)
            closed = int(rec["gaps_closed"] or 0)
            rate = round(closed / total, 4) if total > 0 else 0.0
        years.append(y)
        rates.append(rate)

    deltas: list[float | None] = []
    for i, r in enumerate(rates):
        if i == 0:
            deltas.append(None)
        else:
            deltas.append(round(r - rates[i - 1], 4))

    return {
        "provider_id": int(provider_id),
        "years":       years,
        "rates":       rates,
        "deltas":      deltas,
    }


# ---------------------------------------------------------------------------
# 5. provider_unrecaptured_top_hccs
# ---------------------------------------------------------------------------


def provider_unrecaptured_top_hccs(
    provider_id: int,
    tenant_id: int | str | None,
    year: int | None = None,
    limit: int = 3,
) -> list[dict[str, Any]]:
    """Top ``limit`` HCCs the provider hasn't recaptured (status='open').

    Used by the side-card "actionable next-best" list.  Ordered by total
    revenue at risk DESC, then by patient count DESC.

    Returns:
        ``[{hcc_code, count, $_at_risk}]``
    """
    tid = _resolve_tid(tenant_id)
    yr = year or _current_year()
    sql = """
        SELECT
            rg.hcc_code                                              AS hcc_code,
            COUNT(DISTINCT rg.patient_id)                            AS patient_count,
            COALESCE(SUM(rg.revenue_impact), 0)                      AS dollars_at_risk
        FROM recapture_gaps rg
        INNER JOIN provider_patient_panel ppp
                ON ppp.patient_id = rg.patient_id
        WHERE ppp.provider_id  = %s
          AND rg.tenant_id     = %s
          AND rg.current_year  = %s
          AND rg.status        = 'open'
          AND rg.hcc_code IS NOT NULL
          AND rg.hcc_code <> ''
        GROUP BY rg.hcc_code
        ORDER BY dollars_at_risk DESC, patient_count DESC
        LIMIT %s
    """
    with raf_cursor() as cur:
        cur.execute(sql, (int(provider_id), str(tid), int(yr), int(limit)))
        rows = cur.fetchall() or []
    return [
        {
            "hcc_code":   r["hcc_code"],
            "count":      int(r["patient_count"] or 0),
            "$_at_risk":  float(r["dollars_at_risk"] or 0.0),
        }
        for r in rows
    ]
