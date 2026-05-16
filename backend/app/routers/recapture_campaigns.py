"""
Recapture Campaign router — bulk-campaign workflow + coder queue.

Endpoints
---------
POST   /api/recapture/campaigns                    – create
POST   /api/recapture/campaigns/preview-filter     – count gaps matching a filter
GET    /api/recapture/campaigns?status=            – list (with rolled-up stats)
GET    /api/recapture/campaigns/{id}               – detail
PUT    /api/recapture/campaigns/{id}               – update (e.g. change status)
POST   /api/recapture/campaigns/{id}/assign        – bulk-assign gaps to coders
GET    /api/recapture/campaigns/{id}/kanban        – 4-bucket kanban view
POST   /api/recapture/assignments/{id}/mark        – coder updates assignment state
GET    /api/recapture/coder/{coder_id}/dashboard   – my queue + velocity

All endpoints require a JWT.  Reads need ``recapture:read`` and writes need
``recapture:write``.
"""
# Do NOT add 'from __future__ import annotations' — breaks FastAPI/Pydantic
# schema generation.

import logging
from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.auth import get_current_user, get_tenant_id, require_permission
from app.services.recapture_campaign_service import (
    ASSIGNMENT_STATUSES,
    CAMPAIGN_STATUSES,
    DISTRIBUTION_STRATEGIES,
    assign_gaps_to_coders,
    create_campaign,
    get_campaign,
    get_campaign_kanban,
    get_coder_dashboard,
    list_campaigns,
    list_coders,
    mark_assignment,
    preview_filter,
    update_campaign,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/recapture", tags=["recapture_campaigns"])


# ---------------------------------------------------------------------------
# Pydantic request / response models
# ---------------------------------------------------------------------------


class CreateCampaignRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    description: str | None = None
    filter_criteria: dict[str, Any] | None = None
    target_close_date: date | None = None
    status: str = Field(default="draft")


class PreviewFilterRequest(BaseModel):
    filter_criteria: dict[str, Any] | None = None


class AssignRequest(BaseModel):
    coder_ids: list[int] = Field(..., min_length=1)
    distribution: str = Field(default="round_robin")


class UpdateCampaignRequest(BaseModel):
    name: str | None = None
    description: str | None = None
    status: str | None = None
    filter_criteria: dict[str, Any] | None = None
    target_close_date: date | None = None


class MarkAssignmentRequest(BaseModel):
    status: str
    notes: str | None = None


# ---------------------------------------------------------------------------
# Static-path routes — declared before /{id} catch-alls
# ---------------------------------------------------------------------------


@router.post("/campaigns/preview-filter", summary="Preview how many gaps match a filter")
def post_preview_filter(
    body: PreviewFilterRequest,
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
    _perm: None = Depends(require_permission("recapture", "read")),
) -> dict[str, Any]:
    try:
        return preview_filter(tenant_id=tenant_id, filter_criteria=body.filter_criteria)
    except Exception as exc:
        logger.exception("preview_filter error tenant=%s: %s", tenant_id, exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/coders", summary="Active users eligible for campaign assignment")
def get_eligible_coders(
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
    _perm: None = Depends(require_permission("recapture", "read")),
) -> dict[str, Any]:
    try:
        coders = list_coders(tenant_id=tenant_id)
    except Exception as exc:
        logger.exception("list_coders error tenant=%s: %s", tenant_id, exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")
    return {"coders": coders, "total": len(coders)}


# ---------------------------------------------------------------------------
# Coder dashboard — declared before /campaigns/{id} so the path is unambiguous
# ---------------------------------------------------------------------------


@router.get("/coder/{coder_id}/dashboard", summary="Coder queue + closure velocity")
def coder_dashboard(
    coder_id: int,
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
    _perm: None = Depends(require_permission("recapture", "read")),
) -> dict[str, Any]:
    try:
        return get_coder_dashboard(coder_id=coder_id, tenant_id=tenant_id)
    except Exception as exc:
        logger.exception(
            "coder_dashboard error coder=%s tenant=%s: %s",
            coder_id, tenant_id, exc, exc_info=True,
        )
        raise HTTPException(status_code=500, detail="Internal server error")


# ---------------------------------------------------------------------------
# Assignment routes
# ---------------------------------------------------------------------------


@router.post("/assignments/{assignment_id}/mark", summary="Update an assignment's kanban state")
def post_mark_assignment(
    assignment_id: int,
    body: MarkAssignmentRequest,
    current_user: dict = Depends(get_current_user),
    _tenant_id: str = Depends(get_tenant_id),
    _perm: None = Depends(require_permission("recapture", "write")),
) -> dict[str, Any]:
    if body.status not in ASSIGNMENT_STATUSES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid status. Allowed: {sorted(ASSIGNMENT_STATUSES)}",
        )
    try:
        return mark_assignment(
            assignment_id=assignment_id,
            status=body.status,
            notes=body.notes,
            coder_id=current_user.get("id") if current_user else None,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        logger.exception(
            "mark_assignment error id=%s: %s", assignment_id, exc, exc_info=True
        )
        raise HTTPException(status_code=500, detail="Internal server error")


# ---------------------------------------------------------------------------
# Campaigns — collection + create
# ---------------------------------------------------------------------------


@router.post("/campaigns", summary="Create a campaign", status_code=201)
def post_create_campaign(
    body: CreateCampaignRequest,
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
    _perm: None = Depends(require_permission("recapture", "write")),
) -> dict[str, Any]:
    if body.status not in CAMPAIGN_STATUSES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid status. Allowed: {sorted(CAMPAIGN_STATUSES)}",
        )
    try:
        creator = (current_user or {}).get("email") or str((current_user or {}).get("id") or "")
        return create_campaign(
            tenant_id=tenant_id,
            name=body.name,
            description=body.description,
            filter_criteria=body.filter_criteria,
            target_close_date=body.target_close_date,
            created_by=creator,
            status=body.status,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        logger.exception("create_campaign error tenant=%s: %s", tenant_id, exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/campaigns", summary="List campaigns")
def get_list_campaigns(
    status: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
    _perm: None = Depends(require_permission("recapture", "read")),
) -> dict[str, Any]:
    try:
        items = list_campaigns(
            tenant_id=tenant_id, status=status, limit=limit, offset=offset
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        logger.exception("list_campaigns error tenant=%s: %s", tenant_id, exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")
    return {"campaigns": items, "total": len(items), "limit": limit, "offset": offset}


# ---------------------------------------------------------------------------
# Campaigns — instance routes
# ---------------------------------------------------------------------------


@router.get("/campaigns/{campaign_id}", summary="Campaign detail + rolled-up stats")
def get_campaign_detail(
    campaign_id: int,
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
    _perm: None = Depends(require_permission("recapture", "read")),
) -> dict[str, Any]:
    item = get_campaign(campaign_id=campaign_id, tenant_id=tenant_id)
    if item is None:
        raise HTTPException(status_code=404, detail=f"Campaign {campaign_id} not found")
    return item


@router.put("/campaigns/{campaign_id}", summary="Patch campaign fields")
def put_update_campaign(
    campaign_id: int,
    body: UpdateCampaignRequest,
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
    _perm: None = Depends(require_permission("recapture", "write")),
) -> dict[str, Any]:
    try:
        item = update_campaign(
            campaign_id=campaign_id,
            tenant_id=tenant_id,
            name=body.name,
            description=body.description,
            status=body.status,
            filter_criteria=body.filter_criteria,
            target_close_date=body.target_close_date,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        logger.exception(
            "update_campaign error id=%s tenant=%s: %s",
            campaign_id, tenant_id, exc, exc_info=True,
        )
        raise HTTPException(status_code=500, detail="Internal server error")

    if item is None:
        raise HTTPException(status_code=404, detail=f"Campaign {campaign_id} not found")
    return item


@router.post("/campaigns/{campaign_id}/assign", summary="Bulk-assign matching gaps to coders")
def post_assign(
    campaign_id: int,
    body: AssignRequest,
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
    _perm: None = Depends(require_permission("recapture", "write")),
) -> dict[str, Any]:
    if body.distribution not in DISTRIBUTION_STRATEGIES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid distribution. Allowed: {sorted(DISTRIBUTION_STRATEGIES)}",
        )
    try:
        return assign_gaps_to_coders(
            campaign_id=campaign_id,
            coder_ids=body.coder_ids,
            distribution=body.distribution,
            tenant_id=tenant_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        logger.exception(
            "assign_gaps_to_coders error id=%s tenant=%s: %s",
            campaign_id, tenant_id, exc, exc_info=True,
        )
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/campaigns/{campaign_id}/kanban", summary="Kanban-bucketed assignments")
def get_kanban(
    campaign_id: int,
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
    _perm: None = Depends(require_permission("recapture", "read")),
) -> dict[str, Any]:
    try:
        return get_campaign_kanban(campaign_id=campaign_id, tenant_id=tenant_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        logger.exception(
            "get_kanban error id=%s tenant=%s: %s",
            campaign_id, tenant_id, exc, exc_info=True,
        )
        raise HTTPException(status_code=500, detail="Internal server error")
