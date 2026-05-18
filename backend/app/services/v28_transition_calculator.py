# DISCLAIMER: This module computes V24→V28 CMS-HCC transition impact using the
# existing hccinfhir-backed RAF engine. It is NOT validated or endorsed by CMS.
# Numbers should be cross-checked against official CMS HCC Software output before
# any financial planning.

"""
V28 Transition Impact Calculator (Gap #14).

Surfaces the per-patient and portfolio-level $ impact of CMS' V24 → V28
CMS-HCC model cutover.  Every MA plan is budgeting for the PY2026 cutover
(Jan 1 2026, 100% V28) — CMS projects roughly a -3.12 % aggregate RAF erosion
relative to the V24 baseline.  Plans need to see who erodes and by how much.

This module is a thin orchestrator on top of the existing engine:

  - `calculate_raf_score_multi_model` (calculator.py) already runs BOTH the
    V24 and V28 processors back-to-back and emits a side-by-side comparison
    payload.  We re-use it as the single source of truth for both scores —
    no duplicated coefficient tables, no parallel scoring code path.

  - The V24 / V28 coefficient tables themselves live in `hccinfhir`, the
    third-party CMS-HCC implementation.  Source: the bundled
    `risk_adjustment_model v0.5.3` weights CSVs:
        * CMS V24 2024 weights.csv  (V24 community/institutional + ESRD)
        * CMS V28 2024 weights.csv  (V28 community/institutional)
    Norm + MACI factors are pulled from `blend_weights.py` which cites the
    CMS 2026 Rate Announcement.

Public API
----------
    calculate_v24_score(patient_id, year)           -> float
    calculate_v28_score(patient_id, year)           -> float
    calculate_blended_score(patient_id, year, v24_pct, v28_pct) -> float
    score_delta_v24_to_v28(patient_id, year)        -> dict
    portfolio_v28_impact(tenant_id, year)           -> dict
    refresh_portfolio_cache(tenant_id, year)        -> dict  (used by Celery)

Caching
-------
Per-patient deltas are cached for 60s on `v28:patient:{tenant}:{pid}:{year}`.
Portfolio rollups are cached for 24h on `v28:portfolio:{tenant}:{year}` and
are refreshed by a Celery task (see `celery_tasks.py`:
`task_refresh_v28_portfolio`).
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Any

from app.cache import cache_delete_pattern, cache_get, cache_set
from app.config import settings
from app.db import raf_cursor
from app.services.hcc_hierarchy import V24_HIERARCHY_CHAINS, V28_HIERARCHY_CHAINS, _build_lookup
from app.services.raf.calculator import calculate_raf_score_multi_model
from app.services.raf.revenue_constants import revenue_per_raf_point as _revenue_lookup

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Revenue conversion: $/RAF point/year.
# Sourced from revenue_constants.py (year-aware table) and falls back to the
# settings override so operators can pin a custom rate without a code deploy.
def _revenue_per_raf_point(year: int | None = None) -> float:
    override = getattr(settings, "cms_revenue_per_raf_point", None)
    if override is not None:
        return float(override)
    return _revenue_lookup(year)


# ---------------------------------------------------------------------------
# HCC hierarchy helpers — applied per model-version before set-diff
# ---------------------------------------------------------------------------

_V24_TRUMPED_BY = _build_lookup(V24_HIERARCHY_CHAINS)
_V28_TRUMPED_BY = _build_lookup(V28_HIERARCHY_CHAINS)


def _filter_hierarchy(hcc_codes: list[str], model_version: str) -> list[str]:
    """Return *hcc_codes* with model-version-appropriate trumped HCCs removed.

    A trumped HCC (e.g. HCC 18 when HCC 17 is present under V24 diabetes rules)
    is excluded from the resulting list so that set-diffs between the V24 and
    V28 sides reflect genuine code-mapping changes, not phantom drops caused
    by a more-severe HCC suppressing a less-severe one on only one side.

    Parameters
    ----------
    hcc_codes:
        Raw HCC list from the multi-model engine (strings like "18", "HCC18").
    model_version:
        "V24" or "V28".
    """
    trumped_by = _V24_TRUMPED_BY if model_version.upper() == "V24" else _V28_TRUMPED_BY
    # Normalise to ints for lookup; keep originals for output.
    present_ints: set[int] = set()
    for code in hcc_codes:
        try:
            present_ints.add(int(str(code).replace("HCC", "").strip()))
        except (TypeError, ValueError):
            pass

    filtered: list[str] = []
    for code in hcc_codes:
        try:
            hcc_int = int(str(code).replace("HCC", "").strip())
        except (TypeError, ValueError):
            filtered.append(code)
            continue
        trumpers = trumped_by.get(hcc_int, [])
        if any(t in present_ints for t in trumpers):
            # This HCC is dominated by a more-severe sibling on this model side.
            continue
        filtered.append(code)
    return filtered


_PATIENT_CACHE_TTL = 60          # 1 minute — per-patient deltas refresh fast
_PORTFOLIO_CACHE_TTL = 24 * 3600  # 24 hours — refreshed daily by Celery


def _patient_cache_key(tenant_id: str, pid: int, year: int) -> str:
    return f"v28:patient:{tenant_id}:{pid}:{year}"


def _portfolio_cache_key(tenant_id: str, year: int) -> str:
    return f"v28:portfolio:{tenant_id}:{year}"


# ---------------------------------------------------------------------------
# Single-patient helpers
# ---------------------------------------------------------------------------


def _run_multi_model(
    patient_id: int,
    year: int,
    tenant_id: str,
) -> dict[str, Any]:
    """Run the existing multi-model engine and return its dict."""
    if not tenant_id:
        raise ValueError(
            "v28_transition_calculator: tenant_id is required "
            "(HIPAA multi-tenant isolation)"
        )
    return calculate_raf_score_multi_model(
        patient_id=patient_id,
        measurement_year=year,
        tenant_id=tenant_id,
    )


def calculate_v24_score(
    patient_id: int,
    year: int | None = None,
    *,
    tenant_id: str = "",
) -> float:
    """Return the patient's V24 payment RAF score for *year*.

    Uses the engine's V24 single-model output (raw RAF, then normalized with
    V24 norm factor and reduced by MACI).
    """
    year = year or date.today().year
    res = _run_multi_model(patient_id, year, tenant_id)
    v24 = res.get("v24") or {}
    # Prefer the engine's already-normalized payment RAF if present; otherwise
    # fall back to raw_raf (single-model runs return raw_raf only).
    score = v24.get("payment_raf")
    if score is None:
        score = v24.get("raw_raf", 0.0)
    return round(float(score), 4)


def calculate_v28_score(
    patient_id: int,
    year: int | None = None,
    *,
    tenant_id: str = "",
) -> float:
    """Return the patient's V28 payment RAF score for *year*."""
    year = year or date.today().year
    res = _run_multi_model(patient_id, year, tenant_id)
    v28 = res.get("v28") or {}
    score = v28.get("payment_raf")
    if score is None:
        score = v28.get("raw_raf", 0.0)
    return round(float(score), 4)


def calculate_blended_score(
    patient_id: int,
    year: int | None = None,
    v24_pct: float = 0.0,
    v28_pct: float = 1.0,
    *,
    tenant_id: str = "",
) -> float:
    """Return the blended RAF score for arbitrary V24/V28 weights.

    PY2024 official blend is 0.67 V24 + 0.33 V28; PY2025 is 0.33 / 0.67;
    PY2026+ is 0.0 / 1.0.  This helper lets callers pass non-standard weights
    (e.g. scenario analysis) without re-running the model.
    """
    if abs((v24_pct + v28_pct) - 1.0) > 0.001:
        raise ValueError(
            f"calculate_blended_score: v24_pct ({v24_pct}) + v28_pct ({v28_pct}) "
            "must sum to 1.0"
        )
    v24 = calculate_v24_score(patient_id, year, tenant_id=tenant_id)
    v28 = calculate_v28_score(patient_id, year, tenant_id=tenant_id)
    return round(v24_pct * v24 + v28_pct * v28, 4)


def score_delta_v24_to_v28(
    patient_id: int,
    year: int | None = None,
    *,
    tenant_id: str = "",
    use_cache: bool = True,
) -> dict[str, Any]:
    """Return the per-patient V24→V28 delta.

    Output shape::

        {
            "patient_id":          int,
            "measurement_year":    int,
            "v24_raf":             float,
            "v28_raf":             float,
            "raf_delta":           float,        # v28 - v24 (negative == erosion)
            "raf_delta_pct":       float,        # raf_delta / v24 * 100
            "revenue_delta_annual": float,       # raf_delta * $/RAF
            "dropped_hccs":        list[str],    # in V24 only (lost in V28)
            "gained_hccs":         list[str],    # in V28 only (gained vs V24)
            "common_hccs":         list[str],    # in both
        }
    """
    year = year or date.today().year
    if use_cache:
        cached = cache_get(_patient_cache_key(tenant_id, patient_id, year))
        if cached is not None:
            return cached

    res = _run_multi_model(patient_id, year, tenant_id)
    v24 = res.get("v24") or {}
    v28 = res.get("v28") or {}

    v24_raf = float(v24.get("payment_raf") or v24.get("raw_raf") or 0.0)
    v28_raf = float(v28.get("payment_raf") or v28.get("raw_raf") or 0.0)
    raf_delta = round(v28_raf - v24_raf, 4)
    raf_delta_pct = round((raf_delta / v24_raf * 100.0), 2) if v24_raf else 0.0
    revenue_delta = round(raf_delta * _revenue_per_raf_point(year), 2)

    comp = res.get("hcc_comparison") or {}

    # Apply model-version-appropriate hierarchy trump before set-diff.
    # Without this pass, an HCC that is trumped on ONE side (e.g. HCC 18
    # suppressed by HCC 17 in V24 diabetes hierarchy) would appear in the
    # v24_only set even though it was never genuinely "lost" in V28 — it was
    # simply superseded on the V24 side.
    raw_v24_only = list(comp.get("v24_only") or [])
    raw_v28_only = list(comp.get("v28_only") or [])
    raw_in_both  = list(comp.get("in_both")  or [])

    # Reconstruct each model's full HCC set, apply hierarchy, then re-diff.
    v24_all_hccs = raw_v24_only + raw_in_both
    v28_all_hccs = raw_v28_only + raw_in_both

    v24_active = set(_filter_hierarchy(v24_all_hccs, "V24"))
    v28_active = set(_filter_hierarchy(v28_all_hccs, "V28"))

    dropped_hccs = sorted(v24_active - v28_active)
    gained_hccs  = sorted(v28_active - v24_active)
    common_hccs  = sorted(v24_active & v28_active)

    out = {
        "patient_id":           int(patient_id),
        "measurement_year":     int(year),
        "v24_raf":              round(v24_raf, 4),
        "v28_raf":              round(v28_raf, 4),
        "raf_delta":            raf_delta,
        "raf_delta_pct":        raf_delta_pct,
        "revenue_delta_annual": revenue_delta,
        "dropped_hccs":         dropped_hccs,
        "gained_hccs":          gained_hccs,
        "common_hccs":          common_hccs,
        "icd_count":            len(res.get("icd_codes") or []),
        "model_segment":        res.get("model_segment"),
        "_disclaimer":          (
            "V24→V28 delta estimated via hccinfhir; not CMS-validated. "
            "Cross-check against official CMS HCC Software before contract use."
        ),
    }
    if use_cache:
        cache_set(_patient_cache_key(tenant_id, patient_id, year), out, _PATIENT_CACHE_TTL)
    return out


# ---------------------------------------------------------------------------
# Portfolio (tenant-wide) impact
# ---------------------------------------------------------------------------


def _list_tenant_patient_ids(tenant_id: str) -> list[int]:
    """Return every active patient id in the tenant (native + FHIR)."""
    seen: set[int] = set()
    pids: list[int] = []

    def _add(pid: int) -> None:
        if pid not in seen:
            seen.add(pid)
            pids.append(pid)

    with raf_cursor() as cur:
        # Native rows in patients table
        cur.execute(
            "SELECT id FROM patients "
            "WHERE is_active = 1 AND tenant_id = %s "
            "ORDER BY id",
            (tenant_id,),
        )
        for r in (cur.fetchall() or []):
            _add(int(r["id"]))

        # FHIR-only rows (mirror of calculate_raf_for_all_patients)
        try:
            cur.execute(
                """
                SELECT DISTINCT epm.id
                FROM emr_patient_matches epm
                JOIN emr_connections ec ON ec.id = epm.connection_id
                WHERE ec.is_active = 1
                  AND ec.connection_type IN ('fhir_r4', 'rest_api')
                  AND ec.tenant_id = %s
                  AND epm.id NOT IN (
                      SELECT id FROM patients
                      WHERE is_active = 1 AND tenant_id = %s
                  )
                ORDER BY epm.id
                """,
                (tenant_id, tenant_id),
            )
            for r in (cur.fetchall() or []):
                _add(int(r["id"]))
        except Exception as exc:
            # FHIR side is best-effort; some deployments don't have the tables.
            logger.debug("FHIR patient enumeration skipped: %s", exc)
    return pids


def portfolio_v28_impact(
    tenant_id: str,
    year: int | None = None,
    *,
    use_cache: bool = True,
    top_n: int = 20,
) -> dict[str, Any]:
    """Compute tenant-wide V24 vs V28 rollup for *year*.

    Output shape::

        {
            "tenant_id":            str,
            "measurement_year":     int,
            "patient_count":        int,
            "computed_patient_count": int,
            "total_v24_raf":        float,
            "total_v28_raf":        float,
            "avg_v24_raf":          float,
            "avg_v28_raf":          float,
            "total_raf_delta":      float,
            "raf_erosion_pct":      float,     # signed; CMS projects ~-3.12%
            "total_revenue_delta":  float,
            "top_eroded_patients":  list[{"pid","v24","v28","delta","revenue","dropped_hccs"}],
            "top_gained_patients":  list[{...}],
            "hcc_erosion_breakdown": {hcc_code: count_affected},  # most-dropped HCCs
            "delta_histogram":      list[{"bucket_label","lo","hi","count"}],
            "errors":               int,
            "generated_at":         iso8601 timestamp,
        }
    """
    year = year or date.today().year
    if not tenant_id:
        raise ValueError("portfolio_v28_impact: tenant_id is required")

    if use_cache:
        cached = cache_get(_portfolio_cache_key(tenant_id, year))
        if cached is not None:
            return cached

    pids = _list_tenant_patient_ids(tenant_id)
    per_patient: list[dict[str, Any]] = []
    errors = 0
    for pid in pids:
        try:
            row = score_delta_v24_to_v28(
                pid, year, tenant_id=tenant_id, use_cache=False
            )
            per_patient.append(row)
        except Exception as exc:
            errors += 1
            logger.warning(
                "v28 portfolio: skipping pid=%s tenant=%s: %s",
                pid, tenant_id, exc,
            )

    total_v24 = round(sum(r["v24_raf"] for r in per_patient), 4)
    total_v28 = round(sum(r["v28_raf"] for r in per_patient), 4)
    total_delta = round(total_v28 - total_v24, 4)
    erosion_pct = round((total_delta / total_v24 * 100.0), 2) if total_v24 else 0.0
    revenue_delta = round(total_delta * _revenue_per_raf_point(), 2)
    n = len(per_patient)
    avg_v24 = round(total_v24 / n, 4) if n else 0.0
    avg_v28 = round(total_v28 / n, 4) if n else 0.0

    # Sort by raf_delta (most-negative first) for "top eroded"
    sorted_asc = sorted(per_patient, key=lambda r: r["raf_delta"])
    top_eroded = [
        {
            "pid":          r["patient_id"],
            "v24":          r["v24_raf"],
            "v28":          r["v28_raf"],
            "delta":        r["raf_delta"],
            "delta_pct":    r["raf_delta_pct"],
            "revenue":      r["revenue_delta_annual"],
            "dropped_hccs": r["dropped_hccs"][:5],
        }
        for r in sorted_asc[:top_n]
        if r["raf_delta"] < 0
    ]
    top_gained = [
        {
            "pid":         r["patient_id"],
            "v24":         r["v24_raf"],
            "v28":         r["v28_raf"],
            "delta":       r["raf_delta"],
            "delta_pct":   r["raf_delta_pct"],
            "revenue":     r["revenue_delta_annual"],
            "gained_hccs": r["gained_hccs"][:5],
        }
        for r in reversed(sorted_asc[-top_n:])
        if r["raf_delta"] > 0
    ]

    # HCC erosion breakdown: how often does each dropped HCC show up?
    erosion_counts: dict[str, int] = {}
    for r in per_patient:
        for h in r["dropped_hccs"]:
            erosion_counts[h] = erosion_counts.get(h, 0) + 1
    # Sort by frequency, keep top 30
    hcc_erosion_breakdown = dict(
        sorted(erosion_counts.items(), key=lambda kv: kv[1], reverse=True)[:30]
    )

    # Histogram of revenue_delta_annual ($) — fixed buckets covering the
    # observed CMS-projected range. Bucket boundaries chosen so that a
    # mid-erosion patient (-$1k to -$3k) is the modal bin.
    histogram = _build_revenue_histogram(per_patient)

    out = {
        "tenant_id":              tenant_id,
        "measurement_year":       int(year),
        "patient_count":          len(pids),
        "computed_patient_count": n,
        "total_v24_raf":          total_v24,
        "total_v28_raf":          total_v28,
        "avg_v24_raf":            avg_v24,
        "avg_v28_raf":            avg_v28,
        "total_raf_delta":        total_delta,
        "raf_erosion_pct":        erosion_pct,
        "total_revenue_delta":    revenue_delta,
        "top_eroded_patients":    top_eroded,
        "top_gained_patients":    top_gained,
        "hcc_erosion_breakdown":  hcc_erosion_breakdown,
        "delta_histogram":        histogram,
        "errors":                 errors,
        "revenue_per_raf_point":  _revenue_per_raf_point(),
        "generated_at":           date.today().isoformat(),
        "_disclaimer":            (
            "Portfolio totals estimated via hccinfhir; not CMS-validated. "
            "CMS projects ~-3.12% aggregate RAF erosion at full V28 cutover."
        ),
    }
    if use_cache:
        cache_set(_portfolio_cache_key(tenant_id, year), out, _PORTFOLIO_CACHE_TTL)
    return out


def _build_revenue_histogram(
    rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Bucket per-patient revenue_delta_annual into a fixed grid."""
    # Bucket boundaries in $; lo inclusive, hi exclusive
    boundaries: list[tuple[float, float, str]] = [
        (float("-inf"), -5000.0,   "<-$5k"),
        (-5000.0,       -3000.0,   "-$5k to -$3k"),
        (-3000.0,       -1500.0,   "-$3k to -$1.5k"),
        (-1500.0,         -500.0,  "-$1.5k to -$500"),
        ( -500.0,           0.0,   "-$500 to $0"),
        (    0.0,         500.0,   "$0 to $500"),
        (  500.0,        1500.0,   "$500 to $1.5k"),
        ( 1500.0,        3000.0,   "$1.5k to $3k"),
        ( 3000.0,        5000.0,   "$3k to $5k"),
        ( 5000.0,    float("inf"), ">$5k"),
    ]
    buckets = [
        {"bucket_label": lbl, "lo": lo, "hi": hi, "count": 0}
        for (lo, hi, lbl) in boundaries
    ]
    for r in rows:
        v = r.get("revenue_delta_annual", 0.0)
        for b in buckets:
            if b["lo"] <= v < b["hi"]:
                b["count"] += 1
                break
    return buckets


def refresh_portfolio_cache(
    tenant_id: str,
    year: int | None = None,
) -> dict[str, Any]:
    """Force-recompute the portfolio rollup and store it in Redis.

    Called by the Celery task `task_refresh_v28_portfolio`; also exposed via
    `POST /api/v28-impact/run-analysis` so users can kick off a manual
    refresh from the UI.
    """
    year = year or date.today().year
    # Invalidate per-patient caches so the recompute uses fresh data
    cache_delete_pattern(f"v28:patient:{tenant_id}:*:{year}")
    cache_delete_pattern(_portfolio_cache_key(tenant_id, year))
    return portfolio_v28_impact(tenant_id, year, use_cache=True)
