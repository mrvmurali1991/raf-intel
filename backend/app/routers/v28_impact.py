"""
V28 transition impact router (Gap #14).

Surfaces the per-patient and portfolio-level $ impact of CMS' V24 → V28
CMS-HCC model cutover (PY2026 100% V28).  Backed by
``app.services.v28_transition_calculator``.

Endpoints
---------
    GET  /api/v28-impact/portfolio?year=2026
        Tenant-wide rollup: total V24 / V28 RAF, $ delta, erosion %, top-eroded
        patients, HCC erosion breakdown, $-delta histogram.

    GET  /api/v28-impact/patient/{pid}?year=2026
        Per-patient V24 vs V28 delta with dropped / gained HCC lists.

    POST /api/v28-impact/run-analysis
        Force-refresh the tenant portfolio cache (kicks off the Celery
        ``raf.refresh_v28_portfolio`` task when Celery is available; falls
        back to synchronous recompute otherwise so the endpoint always
        returns a usable payload).

PHI audit: every patient-scoped call writes through ``log_phi_access``.
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request

from app.auth import get_current_user, require_permission
from app.rate_limit import limiter
from app.services.audit_logger import log_phi_access
from app.services.patient_service import patient_is_accessible
from app.services.redis_cache import cached as redis_cached
from app.services.v28_transition_calculator import (
    portfolio_v28_impact,
    refresh_portfolio_cache,
    score_delta_v24_to_v28,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v28-impact", tags=["v28-impact"])


def _resolve_tenant(current_user: dict) -> str:
    tenant_id = (current_user or {}).get("tenant_id")
    if not tenant_id:
        raise HTTPException(status_code=403, detail="No tenant context for this user")
    return str(tenant_id)


# Cached compute layer used by the GET /portfolio endpoint.
# Keyed by tenant + year + top_n so different drill-down depths don't collide.
@redis_cached(
    key_builder=lambda tenant_id, year, top_n: (
        f"raf:v28:portfolio:{tenant_id}:{year}:{top_n}"
    ),
    ttl_seconds=3600,
    tenant_aware=True,
)
def _cached_portfolio_impact(tenant_id: str, year: int, top_n: int) -> dict[str, Any]:
    # ``use_cache=False`` on the inner calculator prevents a double-cache
    # layer fighting over the same key space.
    return portfolio_v28_impact(
        tenant_id=tenant_id,
        year=year,
        use_cache=False,
        top_n=top_n,
    )


# ---------------------------------------------------------------------------
# GET /api/v28-impact/portfolio
# ---------------------------------------------------------------------------


@router.get(
    "/portfolio",
    summary="Tenant-wide V24→V28 transition impact rollup",
)
@limiter.limit("30/minute")
def get_portfolio_impact(
    request: Request,
    year: int | None = Query(default=None, ge=2020, le=2100),
    refresh: bool = Query(
        default=False,
        description="If true, bypass Redis cache and recompute synchronously",
    ),
    force_refresh: bool = Query(
        default=False,
        description="Alias for ?refresh=true (Redis cache bypass).",
    ),
    top_n: int = Query(default=20, ge=1, le=100),
    current_user: dict = Depends(get_current_user),
    _perm: None = Depends(require_permission("raf", "read")),
) -> dict[str, Any]:
    tenant_id = _resolve_tenant(current_user)
    measurement_year = year or date.today().year
    try:
        payload = _cached_portfolio_impact(
            tenant_id,
            measurement_year,
            top_n,
            force_refresh=refresh or force_refresh,
        )
    except Exception as exc:
        logger.exception(
            "v28-impact portfolio failed tenant=%s year=%s: %s",
            tenant_id, measurement_year, exc,
        )
        raise HTTPException(status_code=500, detail="Internal server error")
    return payload


# ---------------------------------------------------------------------------
# GET /api/v28-impact/patient/{pid}
# ---------------------------------------------------------------------------


@router.get(
    "/patient/{pid}",
    summary="Per-patient V24→V28 RAF delta",
)
@limiter.limit("120/minute")
def get_patient_impact(
    request: Request,
    pid: int = Path(..., description="OpenEMR patient id"),
    year: int | None = Query(default=None, ge=2020, le=2100),
    refresh: bool = Query(default=False),
    current_user: dict = Depends(get_current_user),
    _perm: None = Depends(require_permission("raf", "read")),
) -> dict[str, Any]:
    tenant_id = _resolve_tenant(current_user)
    if not patient_is_accessible(pid, tenant_id):
        raise HTTPException(status_code=404, detail=f"Patient {pid} not found")
    measurement_year = year or date.today().year

    # HIPAA §164.312(b) — every patient touch leaves an audit trail
    try:
        log_phi_access(
            action="v28-impact",
            resource="raf",
            patient_id=pid,
            user=current_user.get("email") or current_user.get("sub") or "api",
            tenant_id=tenant_id,
            details=f"year={measurement_year}",
        )
    except Exception:  # noqa: BLE001 — best-effort guard
        logger.warning("best-effort operation failed", exc_info=True)

    try:
        return score_delta_v24_to_v28(
            patient_id=pid,
            year=measurement_year,
            tenant_id=tenant_id,
            use_cache=not refresh,
        )
    except Exception as exc:
        logger.exception("v28-impact patient pid=%s failed: %s", pid, exc)
        raise HTTPException(status_code=500, detail="Internal server error")


# ---------------------------------------------------------------------------
# POST /api/v28-impact/run-analysis
# ---------------------------------------------------------------------------


@router.post(
    "/run-analysis",
    summary="Refresh the tenant V28 portfolio cache (sync fallback, Celery preferred)",
)
@limiter.limit("6/minute")
def run_analysis(
    request: Request,
    year: int | None = Query(default=None, ge=2020, le=2100),
    current_user: dict = Depends(get_current_user),
    _perm: None = Depends(require_permission("raf", "read")),
) -> dict[str, Any]:
    tenant_id = _resolve_tenant(current_user)
    measurement_year = year or date.today().year

    # Prefer Celery when available so the HTTP call returns immediately and
    # the heavy 44-patient scoring runs in the background. Falls back to a
    # synchronous recompute when Celery / Redis are not configured (dev).
    try:
        from app.services.celery_tasks import task_refresh_v28_portfolio
        result = task_refresh_v28_portfolio.delay(tenant_id, measurement_year)
        return {
            "queued":       True,
            "job_id":       getattr(result, "id", None),
            "tenant_id":    tenant_id,
            "year":         measurement_year,
            "status":       "queued",
            "message":      "Portfolio refresh queued; poll /portfolio after ~30s",
        }
    except Exception as celery_exc:
        logger.warning(
            "v28-impact: Celery unavailable, running sync (%s)", celery_exc
        )
        try:
            payload = refresh_portfolio_cache(tenant_id, measurement_year)
        except Exception as exc:
            logger.exception("v28-impact sync refresh failed: %s", exc)
            raise HTTPException(status_code=500, detail="Internal server error")
        return {
            "queued":     False,
            "tenant_id":  tenant_id,
            "year":       measurement_year,
            "status":     "completed",
            "summary": {
                "patient_count":         payload["patient_count"],
                "total_raf_delta":       payload["total_raf_delta"],
                "total_revenue_delta":   payload["total_revenue_delta"],
                "raf_erosion_pct":       payload["raf_erosion_pct"],
            },
        }
