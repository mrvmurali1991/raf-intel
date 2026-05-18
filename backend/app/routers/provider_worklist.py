"""
Provider Worklist router — HTTP interface for the provider-facing RAF worklist.

Endpoints
---------
GET  /api/worklist/provider/{provider_id}          — provider's prioritized patient list
GET  /api/worklist/patient/{patient_id}/actions    — action items for a patient visit
GET  /api/worklist/summary                         — tenant-level aggregate stats

All endpoints require a valid JWT bearer token and the ``worklist:read``
permission.  The summary endpoint additionally requires ``worklist:manage``
(manager / admin roles) to prevent providers from viewing cross-provider data.
"""
# Note: do NOT use 'from __future__ import annotations' here —
# it breaks FastAPI/Pydantic schema generation.

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from app.auth import get_current_user, get_tenant_id, require_permission
from app.services.provider_worklist_service import (
    get_patient_action_items,
    get_provider_worklist,
    get_provider_workload,
    get_worklist_summary,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/worklist", tags=["provider-worklist"])


# ---------------------------------------------------------------------------
# GET /api/worklist/provider/{provider_id}
# ---------------------------------------------------------------------------


@router.get(
    "/provider/{provider_id}",
    summary="Get the prioritized patient worklist for a provider",
)
def provider_worklist(
    provider_id: int,
    measurement_year: int = Query(
        default=2026,
        ge=2020,
        le=2030,
        description="RAF measurement year to evaluate (default: current programme year 2026)",
    ),
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
    _perm: None = Depends(require_permission("worklist", "read")),
) -> dict[str, Any]:
    """
    Returns a prioritized list of patients the provider should see, sorted by
    ``priority_score`` descending.

    Each patient entry includes:
    - ``patient_name``, ``dob``, ``last_visit_date``
    - ``open_recapture_gaps`` — HCCs from the prior year not yet documented
    - ``suspect_conditions`` — conditions flagged by NLP / lab analysis
    - ``estimated_raf_impact`` — sum of RAF coefficients for open gaps
    - ``estimated_revenue_at_risk`` — estimated revenue if gaps stay unclosed
    - ``priority_score`` — 0–100, higher is more urgent

    Providers may only query their own worklist unless they have the
    ``worklist:manage`` permission (manager / admin roles).
    """
    caller_id: int = int(current_user["id"])
    role: str = current_user.get("role", "provider")

    # Providers can only see their own worklist; admins/managers can see any.
    if role not in ("admin", "super_admin", "manager") and caller_id != provider_id:
        raise HTTPException(
            status_code=403,
            detail="Providers may only view their own worklist. "
                   "Request the 'worklist:manage' permission to view other providers.",
        )

    try:
        items = get_provider_worklist(
            provider_id=provider_id,
            tenant_id=tenant_id,
            measurement_year=measurement_year,
        )
    except ValueError as exc:
        logger.warning("provider_worklist validation error provider=%s: %s", provider_id, exc)
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        logger.error("provider_worklist provider=%s tenant=%s: %s", provider_id, tenant_id, exc)
        raise HTTPException(status_code=500, detail="Internal server error")

    return {
        "provider_id": provider_id,
        "measurement_year": measurement_year,
        "total": len(items),
        "items": items,
    }


# ---------------------------------------------------------------------------
# GET /api/worklist/patient/{patient_id}/actions
# ---------------------------------------------------------------------------


@router.get(
    "/patient/{patient_id}/actions",
    summary="Get action items for a specific patient visit",
)
def patient_action_items(
    patient_id: int,
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
    _perm: None = Depends(require_permission("worklist", "read")),
) -> dict[str, Any]:
    """
    Returns the specific actions a provider or coder should take during or
    before a patient visit.

    Action types returned:
    - ``recapture_hcc`` — HCC present in a prior year but not yet documented
      this year; includes ICD-10 codes to document.
    - ``incomplete_meat`` — HCC has incomplete MEAT (Monitoring, Evaluation,
      Assessment, Treatment) documentation.
    - ``missing_encounter`` — Patient has no encounter recorded in the current
      calendar year.
    - ``suggested_diagnosis`` — Condition suspected by NLP / lab analysis or
      found in historical encounter data.

    Results are ordered by priority (1 = most urgent) then HCC code.
    """
    try:
        actions = get_patient_action_items(
            patient_id=patient_id,
            tenant_id=tenant_id,
        )
    except ValueError as exc:
        logger.warning("patient_action_items validation error patient=%s: %s", patient_id, exc)
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        logger.error(
            "patient_action_items patient=%s tenant=%s: %s",
            patient_id, tenant_id, exc,
        )
        raise HTTPException(status_code=500, detail="Internal server error")

    return {
        "patient_id": patient_id,
        "total": len(actions),
        "action_items": actions,
    }


# ---------------------------------------------------------------------------
# GET /api/worklist/summary
# ---------------------------------------------------------------------------


@router.get(
    "/summary",
    summary="Get tenant-level worklist aggregate statistics",
)
def worklist_summary(
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
    _perm: None = Depends(require_permission("worklist", "manage")),
) -> dict[str, Any]:
    """
    Returns aggregate RAF worklist statistics for the calling user's tenant.

    Requires the ``worklist:manage`` permission (manager / admin roles).

    Response includes:
    - ``total_patients_needing_attention`` — patients with at least one open gap
    - ``total_raf_impact_at_risk`` — sum of RAF coefficients across open gaps
    - ``total_revenue_at_risk`` — estimated revenue at risk from unclosed gaps
    - ``top_conditions`` — top 10 HCC codes by frequency, with gap counts and
      average revenue impact
    - ``provider_performance`` — per-provider summary: patients seen YTD,
      open gap count, recapture rate
    - ``generated_at`` — UTC timestamp
    """
    try:
        result = get_worklist_summary(tenant_id=tenant_id)
    except ValueError as exc:
        logger.warning("worklist_summary validation error tenant=%s: %s", tenant_id, exc)
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        logger.error("worklist_summary tenant=%s: %s", tenant_id, exc)
        raise HTTPException(status_code=500, detail="Internal server error")

    return result


# ---------------------------------------------------------------------------
# GET /api/worklist/provider-workload
# ---------------------------------------------------------------------------


@router.get(
    "/provider-workload",
    summary="Per-provider workload heatmap data (admin/manager only)",
)
def provider_workload(
    measurement_year: int = Query(
        default=2026,
        ge=2020,
        le=2030,
        description="RAF measurement year (default: current programme year 2026)",
    ),
    target_capacity: int = Query(
        default=30,
        ge=1,
        le=500,
        description="Target gaps per provider used to compute capacity_pct (default: 30)",
    ),
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
    _perm: None = Depends(require_permission("worklist", "manage")),
) -> dict[str, Any]:
    """
    Returns per-provider workload for the heatmap widget.

    Requires ``worklist:manage`` (admin / manager roles).

    Each item in ``providers`` includes:
    - ``provider_id``, ``provider_name``
    - ``open_gaps``, ``awv_due``, ``suspect_count``, ``total_workload``
    - ``capacity_pct`` — 0–100; green <70, amber 70–90, red >90
    """
    try:
        rows = get_provider_workload(
            tenant_id=tenant_id,
            measurement_year=measurement_year,
            target_capacity=target_capacity,
        )
    except ValueError as exc:
        logger.warning("provider_workload validation error tenant=%s: %s", tenant_id, exc)
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        logger.error("provider_workload tenant=%s: %s", tenant_id, exc)
        raise HTTPException(status_code=500, detail="Internal server error")

    total_open = sum(r["open_gaps"] for r in rows)
    return {
        "providers": rows,
        "total_open_gaps": total_open,
        "target_capacity": target_capacity,
        "measurement_year": measurement_year,
    }
