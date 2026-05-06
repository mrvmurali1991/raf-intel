"""
Recapture member-outreach automation tracker router.

Endpoints
---------
GET    /api/recapture/outreach/templates                    – list templates
POST   /api/recapture/outreach/templates                    – create template
POST   /api/recapture/outreach/templates/seed-defaults      – seed 3 defaults
POST   /api/recapture/gaps/{gap_id}/queue-outreach          – queue an event
POST   /api/recapture/outreach/events/{id}/mark             – transition event
GET    /api/recapture/outreach/summary?year=2026            – aggregate metrics
GET    /api/recapture/gaps/{gap_id}/outreach-history        – per-gap timeline

All endpoints require a valid JWT.  Reads require ``recapture:read`` and
mutations require ``recapture:write`` permission, matching the recapture_gaps
router.
"""
# Do NOT add 'from __future__ import annotations' — it breaks FastAPI/Pydantic
# schema generation (ForwardRef errors in /openapi.json).

import logging
from datetime import datetime
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.auth import get_current_user, get_tenant_id, require_permission
from app.services.recapture_outreach_service import (
    VALID_CHANNELS,
    create_template,
    get_outreach_history,
    list_templates,
    mark_event,
    outreach_summary,
    queue_outreach,
    seed_default_templates,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/recapture", tags=["recapture_outreach"])


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class TemplateCreate(BaseModel):
    channel: str = Field(..., description="sms | portal | phone | email | letter")
    name: str = Field(..., min_length=1, max_length=200)
    message_text: str = Field(..., min_length=1)
    subject: Optional[str] = None
    trigger_rules: Optional[dict] = None
    is_active: bool = True


class TemplateResponse(BaseModel):
    id: int
    tenant_id: str
    channel: str
    name: str
    subject: Optional[str] = None
    message_text: str
    trigger_rules: Optional[Any] = None
    is_active: bool
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class TemplateListResponse(BaseModel):
    total: int
    templates: list[TemplateResponse]


class SeedDefaultsResponse(BaseModel):
    created: list[TemplateResponse]
    total_created: int


class QueueOutreachRequest(BaseModel):
    template_id: Optional[int] = None
    channel: Optional[str] = None
    scheduled_for: Optional[datetime] = None
    metadata: Optional[dict] = None


class OutreachEventResponse(BaseModel):
    id: int
    tenant_id: str
    gap_id: int
    patient_id: str
    template_id: Optional[int] = None
    template_name: Optional[str] = None
    channel: str
    status: str
    scheduled_for: Optional[str] = None
    sent_at: Optional[str] = None
    delivered_at: Optional[str] = None
    responded_at: Optional[str] = None
    response_text: Optional[str] = None
    resulted_in_visit: bool
    resulted_in_closure: bool
    metadata: Optional[Any] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class MarkEventRequest(BaseModel):
    status: str = Field(
        ...,
        description="sent | delivered | responded | failed | opted_out",
    )
    response_text: Optional[str] = None
    resulted_in_visit: bool = False
    resulted_in_closure: bool = False


class ChannelMetrics(BaseModel):
    queued: int
    sent: int
    delivered: int
    responded: int
    visits: int
    closed: int
    response_rate: float
    visit_rate: float
    closure_rate: float


class OutreachSummaryResponse(BaseModel):
    year: Optional[int] = None
    total_sent: int
    total_responded: int
    total_closed: int
    conversion_rate: float
    avg_days_to_response: Optional[float] = None
    estimated_revenue: float
    by_channel: dict[str, ChannelMetrics]


class OutreachHistoryResponse(BaseModel):
    gap_id: int
    total: int
    events: list[OutreachEventResponse]


# ---------------------------------------------------------------------------
# Templates
# ---------------------------------------------------------------------------

@router.get(
    "/outreach/templates",
    summary="List outreach templates",
    response_model=TemplateListResponse,
)
def list_outreach_templates(
    channel: Optional[str] = Query(default=None),
    is_active: Optional[bool] = Query(default=None),
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
    _perm: None = Depends(require_permission("recapture", "read")),
) -> TemplateListResponse:
    try:
        rows = list_templates(tenant_id=tenant_id, channel=channel, is_active=is_active)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        logger.error("list_outreach_templates error: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")
    return TemplateListResponse(total=len(rows), templates=rows)  # type: ignore[arg-type]


@router.post(
    "/outreach/templates",
    summary="Create an outreach template",
    response_model=TemplateResponse,
    status_code=201,
)
def create_outreach_template(
    body: TemplateCreate,
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
    _perm: None = Depends(require_permission("recapture", "write")),
) -> TemplateResponse:
    try:
        tpl = create_template(
            tenant_id=tenant_id,
            channel=body.channel,
            name=body.name,
            message_text=body.message_text,
            subject=body.subject,
            trigger_rules=body.trigger_rules,
            is_active=body.is_active,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        logger.error("create_outreach_template error: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")
    return tpl  # type: ignore[return-value]


@router.post(
    "/outreach/templates/seed-defaults",
    summary="Insert SMS/portal/phone defaults if missing",
    response_model=SeedDefaultsResponse,
)
def seed_defaults(
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
    _perm: None = Depends(require_permission("recapture", "write")),
) -> SeedDefaultsResponse:
    try:
        created = seed_default_templates(tenant_id=tenant_id)
    except Exception as exc:
        logger.error("seed_defaults error: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")
    return SeedDefaultsResponse(created=created, total_created=len(created))  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Events
# ---------------------------------------------------------------------------

@router.post(
    "/gaps/{gap_id}/queue-outreach",
    summary="Queue an outreach event for a gap",
    response_model=OutreachEventResponse,
    status_code=201,
)
def queue_outreach_for_gap(
    gap_id: int,
    body: QueueOutreachRequest,
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
    _perm: None = Depends(require_permission("recapture", "write")),
) -> OutreachEventResponse:
    try:
        evt = queue_outreach(
            tenant_id=tenant_id,
            gap_id=gap_id,
            template_id=body.template_id,
            channel=body.channel,
            scheduled_for=body.scheduled_for,
            metadata=body.metadata,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        logger.error("queue_outreach error gap=%s: %s", gap_id, exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")
    return evt  # type: ignore[return-value]


@router.post(
    "/outreach/events/{event_id}/mark",
    summary="Transition an outreach event status",
    response_model=OutreachEventResponse,
)
def mark_outreach_event(
    event_id: int,
    body: MarkEventRequest,
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
    _perm: None = Depends(require_permission("recapture", "write")),
) -> OutreachEventResponse:
    try:
        evt = mark_event(
            event_id=event_id,
            status=body.status,
            response_text=body.response_text,
            resulted_in_visit=body.resulted_in_visit,
            resulted_in_closure=body.resulted_in_closure,
        )
    except ValueError as exc:
        # Distinguish "bad input" (400) from "not found" (404) by message.
        msg = str(exc)
        if "not found" in msg.lower():
            raise HTTPException(status_code=404, detail=msg)
        raise HTTPException(status_code=400, detail=msg)
    except Exception as exc:
        logger.error("mark_outreach_event error id=%s: %s", event_id, exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")
    return evt  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# Analytics
# ---------------------------------------------------------------------------

@router.get(
    "/outreach/summary",
    summary="Aggregate outreach metrics",
    response_model=OutreachSummaryResponse,
)
def get_outreach_summary(
    year: Optional[int] = Query(default=None, ge=2020, le=2030),
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
    _perm: None = Depends(require_permission("recapture", "read")),
) -> OutreachSummaryResponse:
    try:
        data = outreach_summary(tenant_id=tenant_id, year=year)
    except Exception as exc:
        logger.error("outreach_summary error: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")
    return data  # type: ignore[return-value]


@router.get(
    "/gaps/{gap_id}/outreach-history",
    summary="Chronological outreach events for a gap",
    response_model=OutreachHistoryResponse,
)
def gap_outreach_history(
    gap_id: int,
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
    _perm: None = Depends(require_permission("recapture", "read")),
) -> OutreachHistoryResponse:
    try:
        events = get_outreach_history(gap_id=gap_id, tenant_id=tenant_id)
    except Exception as exc:
        logger.error("gap_outreach_history error gap=%s: %s", gap_id, exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")
    return OutreachHistoryResponse(  # type: ignore[arg-type]
        gap_id=gap_id, total=len(events), events=events,
    )


# Sanity check — registry imports VALID_CHANNELS for type hints in some paths.
_ = VALID_CHANNELS
