"""
Population Geographic Heat-Map Router.

Endpoints
---------
GET /api/population/heatmap?year=YYYY  – aggregated stats by ZIP code

The endpoint identifies clusters of risk and care gaps across the patient
population, grouped by ZIP code (Innovaccer-style heat map).

Response shape
--------------
list of objects, one per ZIP code:
    {
      "zip_code":        str,    # 5-digit (or whatever is stored in patients.zip)
      "patient_count":   int,    # active patients in this ZIP
      "avg_raf":         float,  # mean prospective RAF for the year
      "total_open_gaps": int,    # open recapture gaps for patients in this ZIP
      "high_risk_count": int     # patients whose RAF >= 1.8
    }

Tenant isolation
----------------
Every aggregation is scoped to ``patients.tenant_id`` AND ``is_active = 1``.

Permissions
-----------
Requires the ``reports:read`` permission, consistent with the rest of the
analytics surface.
"""

import logging
from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, Query

from app.auth import get_current_user, get_tenant_id, require_permission
from app.cache import cache_get, cache_set
from app.db import raf_cursor
from app.services.cache_strategy import get_active_connection_id

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/population", tags=["population"])

# Cache TTL — population aggregates change slowly, 5 minutes is plenty.
_CACHE_TTL = 300

# RAF threshold for "high risk" patients.  Matches the "very_high" tier used
# in dashboard_analytics_service.get_patient_risk_stratification (>= 1.8).
_HIGH_RISK_THRESHOLD = 1.8


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _int_tenant(tenant_id: str) -> int:
    """Convert tenant_id string to int, defaulting to 1 for safety."""
    try:
        return int(tenant_id)
    except (TypeError, ValueError):
        return 1


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return round(float(value), 3) if value is not None else default
    except (TypeError, ValueError):
        return default


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value) if value is not None else default
    except (TypeError, ValueError):
        return default


def _aggregate_heatmap(tenant_id: str, measurement_year: int) -> list[dict[str, Any]]:
    """
    Aggregate population stats per ZIP code for a tenant + year.

    Strategy
    --------
    1. Pull (zip, patient_count, avg_raf, high_risk_count) by GROUPing
       ``raf_scores`` joined to ``patients`` (so we only see active, in-tenant
       patients with a prospective RAF row for the requested year).
    2. Pull (zip, open_gap_count) from a separate GROUP on ``recapture_gaps``
       joined to ``patients`` — recapture_gaps has no year column in all
       deployments, so we keep this query separate and tolerant of a missing
       table.
    3. Merge the two dictionaries keyed by zip.

    Patients without a populated ``zip`` are excluded from the heat map (a
    geographic visualization can't place them anyway).
    """
    tid = _int_tenant(tenant_id)

    # --- Per-zip RAF / patient aggregates --------------------------------
    by_zip: dict[str, dict[str, Any]] = {}
    try:
        with raf_cursor() as cur:
            cur.execute(
                """
                SELECT
                    p.zip                                                       AS zip_code,
                    COUNT(DISTINCT p.id)                                        AS patient_count,
                    AVG(rs.raf_score)                                           AS avg_raf,
                    SUM(CASE WHEN rs.raf_score >= %s THEN 1 ELSE 0 END)         AS high_risk_count
                FROM patients p
                JOIN raf_scores rs ON rs.patient_id = p.id
                WHERE p.is_active = 1
                  AND p.tenant_id = %s
                  AND rs.measurement_year = %s
                  AND rs.score_type = 'prospective'
                  AND p.zip IS NOT NULL
                  AND p.zip <> ''
                GROUP BY p.zip
                """,
                (_HIGH_RISK_THRESHOLD, tid, measurement_year),
            )
            for row in cur.fetchall():
                zip_code = (row.get("zip_code") or "").strip()
                if not zip_code:
                    continue
                by_zip[zip_code] = {
                    "zip_code":        zip_code,
                    "patient_count":   _safe_int(row.get("patient_count")),
                    "avg_raf":         _safe_float(row.get("avg_raf")),
                    "total_open_gaps": 0,
                    "high_risk_count": _safe_int(row.get("high_risk_count")),
                }
    except Exception as exc:
        logger.warning("population_heatmap: per-zip RAF query failed: %s", exc)
        return []

    # --- Per-zip open recapture-gap counts -------------------------------
    # recapture_gaps may not exist in every deployment — be tolerant.
    try:
        with raf_cursor() as cur:
            cur.execute(
                """
                SELECT
                    p.zip               AS zip_code,
                    COUNT(*)            AS open_gaps
                FROM recapture_gaps rg
                JOIN patients p ON p.id = rg.patient_id
                WHERE p.is_active = 1
                  AND p.tenant_id = %s
                  AND rg.status = 'open'
                  AND p.zip IS NOT NULL
                  AND p.zip <> ''
                GROUP BY p.zip
                """,
                (tid,),
            )
            for row in cur.fetchall():
                zip_code = (row.get("zip_code") or "").strip()
                if not zip_code:
                    continue
                bucket = by_zip.get(zip_code)
                if bucket is None:
                    # A ZIP can have gaps but no current-year RAF row (e.g. brand-new
                    # patient).  Surface it with patient_count = 0 so the FE still
                    # plots the cluster.
                    bucket = {
                        "zip_code":        zip_code,
                        "patient_count":   0,
                        "avg_raf":         0.0,
                        "total_open_gaps": 0,
                        "high_risk_count": 0,
                    }
                    by_zip[zip_code] = bucket
                bucket["total_open_gaps"] = _safe_int(row.get("open_gaps"))
    except Exception as exc:
        logger.debug("population_heatmap: recapture_gaps query skipped: %s", exc)

    # Sort by patient_count desc so the front-end can take "top N" cheaply.
    return sorted(
        by_zip.values(),
        key=lambda r: (r["patient_count"], r["total_open_gaps"]),
        reverse=True,
    )


# ---------------------------------------------------------------------------
# GET /api/population/heatmap
# ---------------------------------------------------------------------------


@router.get(
    "/heatmap",
    summary="Population geographic heat-map by ZIP code",
    response_model=None,
)
def population_heatmap(
    year: int = Query(default=None, description="Measurement year (defaults to current year)"),
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
    _perm: None = Depends(require_permission("reports", "read")),
) -> list[dict[str, Any]]:
    """
    Return aggregated population stats keyed by ZIP code.

    Each entry includes ``patient_count``, ``avg_raf``, ``total_open_gaps``,
    and ``high_risk_count`` — enough for a front-end to render either a
    geographic choropleth or a ranked bar chart of clusters.
    """
    measurement_year = year or date.today().year

    _acid = get_active_connection_id(tenant_id)
    cache_key = f"population:heatmap:{tenant_id}:{measurement_year}:{_acid}"
    cached = cache_get(cache_key)
    if cached is not None:
        return cached

    result = _aggregate_heatmap(tenant_id, measurement_year)
    cache_set(cache_key, result, ttl=_CACHE_TTL)
    return result
