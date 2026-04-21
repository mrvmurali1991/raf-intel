"""
Cohort Analysis router.

Endpoints
---------
POST   /api/cohorts                        – create cohort from criteria
GET    /api/cohorts                        – list cohorts
GET    /api/cohorts/population-health      – global population metrics (static path, before /{id})
GET    /api/cohorts/{id}                   – cohort detail with summary stats
PUT    /api/cohorts/{id}                   – update criteria / metadata
DELETE /api/cohorts/{id}                   – archive cohort
GET    /api/cohorts/{id}/members           – paginated member list
POST   /api/cohorts/{id}/refresh           – refresh dynamic membership
POST   /api/cohorts/{id}/snapshot          – take point-in-time snapshot
GET    /api/cohorts/{id}/trends            – historical snapshots
POST   /api/cohorts/compare                – compare two cohorts (static path, before /{id})
GET    /api/cohorts/comparisons/{id}       – comparison result detail
GET    /api/cohorts/{id}/export            – export cohort as CSV

All endpoints require a valid JWT.
Write operations require the "cohorts" write permission.
Read operations require the "cohorts" read permission.
"""
# Note: do NOT use 'from __future__ import annotations' — breaks FastAPI schema gen.

import logging
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.auth import get_current_user, get_tenant_id, require_permission
from app.rate_limit import limiter
from app.services.cohort_service import (
    archive_cohort,
    compare_cohorts,
    create_cohort,
    export_cohort_csv,
    get_cohort,
    get_cohort_members,
    get_cohort_trends,
    get_comparison,
    get_population_health_metrics,
    list_cohorts,
    refresh_cohort_membership,
    take_snapshot,
    update_cohort,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/cohorts", tags=["cohorts"])


# ---------------------------------------------------------------------------
# Pydantic request models
# ---------------------------------------------------------------------------

class CohortCreate(BaseModel):
    """Payload for creating a new cohort."""

    name: str = Field(..., min_length=1, max_length=255, description="Human-readable cohort name")
    description: str | None = Field(default=None, description="Optional longer description")
    cohort_type: Literal[
        "custom",
        "chronic_condition",
        "risk_tier",
        "provider_panel",
        "payer",
        "geographic",
        "age_group",
    ] = Field(default="custom", description="Category that drives criteria interpretation")
    criteria: dict[str, Any] = Field(
        ...,
        description=(
            "Membership filter definition. Supported keys: "
            "hcc_codes (list[str]), raf_min (float), raf_max (float), "
            "age_min (int), age_max (int), gender (str), "
            "provider_ids (list[int]), payer_names (list[str]), "
            "icd_codes (list[str]), risk_tiers (list[str]), "
            "zip_codes (list[str]), states (list[str])"
        ),
    )
class CohortUpdate(BaseModel):
    """Partial update payload — all fields optional."""

    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    cohort_type: Literal[
        "custom",
        "chronic_condition",
        "risk_tier",
        "provider_panel",
        "payer",
        "geographic",
        "age_group",
    ] | None = None
    criteria: dict[str, Any] | None = None
    refresh_membership: bool = Field(
        default=True,
        description="When True and criteria changed, re-evaluate membership immediately",
    )


class CompareRequest(BaseModel):
    """Request a side-by-side comparison of two cohorts."""

    cohort_a_id: int = Field(..., description="Reference cohort ID")
    cohort_b_id: int = Field(..., description="Comparison cohort ID")
    name: str | None = Field(default=None, max_length=255, description="Optional label")


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _get_or_404(cohort_id: int) -> dict[str, Any]:
    cohort = get_cohort(cohort_id)
    if not cohort:
        raise HTTPException(status_code=404, detail=f"Cohort {cohort_id} not found")
    return cohort


# ---------------------------------------------------------------------------
# Static-path routes — declared BEFORE /{id} to avoid path-shadowing
# ---------------------------------------------------------------------------

@router.get("/population-health", summary="Global population health metrics")
@limiter.limit("60/minute")
def population_health(
    request: Request,
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
    _perm: None = Depends(require_permission("cohorts", "read")),
) -> dict[str, Any]:
    """
    Return population-wide health metrics aggregated across all active cohorts
    in the specified tenant.

    Includes:
    - Total unique patients
    - Average RAF score
    - Risk tier distribution
    - Top 10 HCC codes by prevalence
    - Estimated total RAF revenue
    - Active and archived cohort counts
    """
    try:
        return get_population_health_metrics(tenant_id=tenant_id)
    except Exception as exc:
        logger.error("population_health error: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/compare", summary="Compare two cohorts", status_code=201)
@limiter.limit("30/minute")
def compare(
    request: Request,
    body: CompareRequest,
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
    _perm: None = Depends(require_permission("cohorts", "read")),
) -> dict[str, Any]:
    """
    Run a side-by-side statistical comparison between two cohorts and persist
    the result.

    Statistical tests applied:
    - **Welch's t-test** on RAF scores and ages (continuous metrics).
    - **Chi-square test** on gender and risk tier distributions (categorical).

    Results are stored in ``cohort_comparisons`` and returned with p-values
    and significance flags.

    Body::

        {
          "cohort_a_id": 1,
          "cohort_b_id": 2,
          "name": "Diabetics vs. Non-Diabetics Q1 2026"
        }
    """
    user_id: int = int(current_user.get("id") or current_user.get("user_id") or 0)
    try:
        return compare_cohorts(
            cohort_a_id=body.cohort_a_id,
            cohort_b_id=body.cohort_b_id,
            name=body.name,
            created_by=user_id,
            tenant_id=tenant_id,
        )
    except ValueError as exc:
        logger.warning("compare_cohorts not found: %s", exc)
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        logger.error("compare_cohorts error: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/comparisons/{comparison_id}", summary="Get comparison result detail")
@limiter.limit("60/minute")
def get_comparison_detail(
    request: Request,
    comparison_id: int,
    current_user: dict = Depends(get_current_user),
    _perm: None = Depends(require_permission("cohorts", "read")),
) -> dict[str, Any]:
    """Return a previously persisted cohort comparison result by ID."""
    result = get_comparison(comparison_id)
    if not result:
        raise HTTPException(status_code=404, detail=f"Comparison {comparison_id} not found")
    return result


# ---------------------------------------------------------------------------
# Collection routes
# ---------------------------------------------------------------------------

@router.get("", summary="List cohorts")
@limiter.limit("60/minute")
def list_cohorts_endpoint(
    request: Request,
    cohort_type: str | None = Query(
        default=None,
        description="Filter by type: custom | chronic_condition | risk_tier | provider_panel | payer | geographic | age_group",
    ),
    status: str = Query(default="active", description="Filter by status: active | archived"),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
    _perm: None = Depends(require_permission("cohorts", "read")),
) -> dict[str, Any]:
    """
    Return a paginated list of cohorts ordered by most recently updated.

    Each row includes the cached ``patient_count``, ``avg_raf_score``, and
    ``total_raf_revenue`` summary statistics computed at last membership refresh.
    """
    try:
        cohorts = list_cohorts(
            cohort_type=cohort_type,
            status=status,
            tenant_id=tenant_id,
            limit=limit,
            offset=offset,
        )
    except Exception as exc:
        logger.error("list_cohorts error: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")

    return {
        "count": len(cohorts),
        "limit": limit,
        "offset": offset,
        "cohorts": cohorts,
    }


@router.post("", summary="Create a cohort from criteria", status_code=201)
@limiter.limit("30/minute")
def create_cohort_endpoint(
    request: Request,
    body: CohortCreate,
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
    _perm: None = Depends(require_permission("cohorts", "write")),
) -> dict[str, Any]:
    """
    Create a new cohort definition and immediately populate its membership by
    evaluating the supplied criteria against current patient data.

    The response includes the freshly computed ``patient_count``,
    ``avg_raf_score``, and ``total_raf_revenue`` fields.

    Example body::

        {
          "name": "High-risk Diabetics",
          "cohort_type": "chronic_condition",
          "criteria": {
            "hcc_codes": ["HCC18", "HCC19"],
            "risk_tiers": ["very_high", "high"]
          }
        }
    """
    user_id: int = int(current_user.get("id") or current_user.get("user_id") or 0)
    try:
        return create_cohort(
            name=body.name,
            description=body.description,
            cohort_type=body.cohort_type,
            criteria=body.criteria,
            created_by=user_id,
            tenant_id=tenant_id,
        )
    except Exception as exc:
        logger.error("create_cohort error: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


# ---------------------------------------------------------------------------
# Instance routes  /{id}  and  /{id}/sub-resources
# ---------------------------------------------------------------------------

@router.get("/{cohort_id}", summary="Get cohort detail with summary stats")
@limiter.limit("60/minute")
def get_cohort_endpoint(
    request: Request,
    cohort_id: int,
    current_user: dict = Depends(get_current_user),
    _perm: None = Depends(require_permission("cohorts", "read")),
) -> dict[str, Any]:
    """
    Return a single cohort by ID, including its criteria, membership counts,
    average RAF score, and estimated revenue.
    """
    return _get_or_404(cohort_id)


@router.put("/{cohort_id}", summary="Update cohort criteria or metadata")
@limiter.limit("30/minute")
def update_cohort_endpoint(
    request: Request,
    cohort_id: int,
    body: CohortUpdate,
    current_user: dict = Depends(get_current_user),
    _perm: None = Depends(require_permission("cohorts", "write")),
) -> dict[str, Any]:
    """
    Partially update a cohort.  Only supplied (non-null) fields are written.

    When ``criteria`` is updated and ``refresh_membership`` is ``true``
    (the default), membership is immediately re-evaluated so summary stats
    reflect the new criteria.
    """
    _get_or_404(cohort_id)
    updates = body.model_dump(exclude_none=True)
    refresh = updates.pop("refresh_membership", True)
    if not updates:
        return _get_or_404(cohort_id)
    try:
        updated = update_cohort(cohort_id, updates, refresh_membership=refresh)
    except Exception as exc:
        logger.error("update_cohort error id=%s: %s", cohort_id, exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")
    if not updated:
        raise HTTPException(status_code=404, detail=f"Cohort {cohort_id} not found")
    return updated


@router.delete("/{cohort_id}", summary="Archive a cohort")
@limiter.limit("30/minute")
def delete_cohort_endpoint(
    request: Request,
    cohort_id: int,
    current_user: dict = Depends(get_current_user),
    _perm: None = Depends(require_permission("cohorts", "write")),
) -> dict[str, Any]:
    """
    Soft-delete a cohort by setting its status to ``archived``.

    Archived cohorts are read-only — their membership and snapshot history
    is retained for audit and trend analysis purposes.
    """
    _get_or_404(cohort_id)
    try:
        result = archive_cohort(cohort_id)
    except Exception as exc:
        logger.error("archive_cohort error id=%s: %s", cohort_id, exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")
    return result


@router.get("/{cohort_id}/members", summary="List cohort members with pagination")
@limiter.limit("60/minute")
def list_members(
    request: Request,
    cohort_id: int,
    include_inactive: bool = Query(default=False, description="Include previously removed members"),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    current_user: dict = Depends(get_current_user),
    _perm: None = Depends(require_permission("cohorts", "read")),
) -> dict[str, Any]:
    """
    Return a paginated list of cohort member records.

    Each row includes ``patient_id``, ``added_at``, ``removed_at``, and
    ``is_active`` flag.  Set ``include_inactive=true`` to also see patients
    who have been removed from the cohort by a previous refresh.
    """
    _get_or_404(cohort_id)
    try:
        members = get_cohort_members(
            cohort_id,
            include_inactive=include_inactive,
            limit=limit,
            offset=offset,
        )
    except Exception as exc:
        logger.error("list_members error id=%s: %s", cohort_id, exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")

    return {
        "cohort_id": cohort_id,
        "count": len(members),
        "limit": limit,
        "offset": offset,
        "members": members,
    }


@router.post("/{cohort_id}/refresh", summary="Refresh cohort membership")
@limiter.limit("30/minute")
def refresh_membership(
    request: Request,
    cohort_id: int,
    current_user: dict = Depends(get_current_user),
    _perm: None = Depends(require_permission("cohorts", "write")),
) -> dict[str, Any]:
    """
    Re-evaluate the cohort criteria against current patient data and update
    membership accordingly.

    - New qualifying patients are added.
    - Patients no longer matching criteria are soft-removed (``is_active=0``).
    - Summary statistics (``patient_count``, ``avg_raf_score``, ``total_raf_revenue``)
      on the parent ``cohorts`` row are updated.

    Returns added/removed/unchanged counts.
    """
    _get_or_404(cohort_id)
    try:
        return refresh_cohort_membership(cohort_id)
    except ValueError as exc:
        logger.warning("refresh_membership error id=%s: %s", cohort_id, exc)
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        logger.error("refresh_membership error id=%s: %s", cohort_id, exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/{cohort_id}/snapshot", summary="Take a point-in-time snapshot", status_code=201)
@limiter.limit("30/minute")
def snapshot(
    request: Request,
    cohort_id: int,
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
    _perm: None = Depends(require_permission("cohorts", "write")),
) -> dict[str, Any]:
    """
    Compute and persist a point-in-time snapshot of cohort aggregate metrics.

    Snapshot includes:
    - Patient count
    - Average RAF score
    - Average age
    - Gender distribution
    - Top 10 HCC codes with prevalence rates
    - Risk tier distribution
    - Total projected RAF revenue

    Snapshots are the foundation for trend analysis via ``GET /{id}/trends``.
    """
    _get_or_404(cohort_id)
    try:
        return take_snapshot(cohort_id, tenant_id=tenant_id)
    except ValueError as exc:
        logger.warning("snapshot error id=%s: %s", cohort_id, exc)
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        logger.error("snapshot error id=%s: %s", cohort_id, exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/{cohort_id}/trends", summary="Get historical snapshot trends")
@limiter.limit("60/minute")
def trends(
    request: Request,
    cohort_id: int,
    limit: int = Query(default=24, ge=1, le=120, description="Maximum number of snapshots to return"),
    current_user: dict = Depends(get_current_user),
    _perm: None = Depends(require_permission("cohorts", "read")),
) -> dict[str, Any]:
    """
    Return historical snapshots for the cohort ordered by snapshot date descending.

    Each snapshot entry contains the full set of population health metrics
    recorded at the time of the snapshot.  Use this to track changes in
    average RAF score, risk tier mix, HCC prevalence, and revenue over time.
    """
    _get_or_404(cohort_id)
    try:
        snapshots = get_cohort_trends(cohort_id, limit=limit)
    except Exception as exc:
        logger.error("trends error id=%s: %s", cohort_id, exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")

    return {
        "cohort_id": cohort_id,
        "count": len(snapshots),
        "snapshots": snapshots,
    }


@router.get("/{cohort_id}/export", summary="Export cohort members as CSV")
@limiter.limit("60/minute")
def export_csv(
    request: Request,
    cohort_id: int,
    current_user: dict = Depends(get_current_user),
    _perm: None = Depends(require_permission("cohorts", "read")),
) -> StreamingResponse:
    """
    Export all active cohort members as a CSV file.

    Columns: ``patient_id``, ``added_at``, ``final_raf``, ``risk_tier``,
    ``hcc_codes``, ``age``, ``gender``.

    The file is streamed as ``text/csv`` with a ``Content-Disposition``
    attachment header suitable for direct browser download.
    """
    _get_or_404(cohort_id)
    try:
        csv_content = export_cohort_csv(cohort_id)
    except ValueError as exc:
        logger.warning("export_csv not found id=%s: %s", cohort_id, exc)
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        logger.error("export_csv error id=%s: %s", cohort_id, exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")

    filename = f"cohort_{cohort_id}_members.csv"
    return StreamingResponse(
        iter([csv_content]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
