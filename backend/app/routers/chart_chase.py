"""
Chart Chase router — track and manage requests for missing medical records.

Tables: chart_chase_requests, chart_chase_attempts, chart_chase_templates

Endpoints
---------
GET    /api/chart-chase                  – list requests with filters
POST   /api/chart-chase                  – create a new request
GET    /api/chart-chase/dashboard        – aggregated stats / aging report
GET    /api/chart-chase/templates        – list outreach templates
POST   /api/chart-chase/templates        – create outreach template
POST   /api/chart-chase/bulk             – bulk create from suspect list
GET    /api/chart-chase/{id}             – detail with attempt history
PUT    /api/chart-chase/{id}             – update mutable fields
POST   /api/chart-chase/{id}/attempt     – log an outreach attempt
PUT    /api/chart-chase/{id}/receive     – mark received, optionally link document
PUT    /api/chart-chase/{id}/cancel      – cancel the request

Note: static-path routes (/dashboard, /templates, /bulk) are registered
before the parameterised /{id} routes to prevent routing ambiguity.
"""

import logging
from datetime import date
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.auth import get_current_user, get_tenant_id, require_permission
from app.services import chart_chase_service as svc

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/chart-chase", tags=["chart-chase"])


# ---------------------------------------------------------------------------
# Pydantic request models
# ---------------------------------------------------------------------------

class ChaseCreateRequest(BaseModel):
    patient_id: int = Field(..., description="OpenEMR patient ID")
    provider_npi: str | None = Field(None, max_length=10)
    chase_type: Literal["initial", "follow_up", "escalation"] = "initial"
    reason: Literal[
        "suspect_hcc",
        "audit_response",
        "missing_encounter",
        "incomplete_documentation",
    ]
    hcc_codes: list[int] | None = Field(None, description="HCC codes driving this request")
    dos_from: date | None = None
    dos_to: date | None = None
    status: Literal[
        "pending", "sent", "acknowledged", "received", "partial", "completed", "cancelled"
    ] = "pending"
    priority: Literal["critical", "high", "medium", "low"] = "medium"
    facility_name: str | None = Field(None, max_length=255)
    facility_fax: str | None = Field(None, max_length=30)
    facility_email: str | None = Field(None, max_length=255)
    facility_phone: str | None = Field(None, max_length=30)
    request_date: date | None = None
    due_date: date | None = None
    notes: str | None = None


class ChaseUpdateRequest(BaseModel):
    provider_npi: str | None = Field(None, max_length=10)
    chase_type: Literal["initial", "follow_up", "escalation"] | None = None
    reason: Literal[
        "suspect_hcc",
        "audit_response",
        "missing_encounter",
        "incomplete_documentation",
    ] | None = None
    hcc_codes: list[int] | None = None
    dos_from: date | None = None
    dos_to: date | None = None
    status: Literal[
        "pending", "sent", "acknowledged", "received", "partial", "completed", "cancelled"
    ] | None = None
    priority: Literal["critical", "high", "medium", "low"] | None = None
    facility_name: str | None = Field(None, max_length=255)
    facility_fax: str | None = Field(None, max_length=30)
    facility_email: str | None = Field(None, max_length=255)
    facility_phone: str | None = Field(None, max_length=30)
    due_date: date | None = None
    notes: str | None = None


class AttemptRequest(BaseModel):
    method: Literal["fax", "email", "phone", "portal", "mail"]
    response: str | None = None
    responded_at: str | None = Field(
        None, description="ISO 8601 datetime when the facility responded"
    )
    notes: str | None = None


class ReceiveRequest(BaseModel):
    document_id: int | None = Field(None, description="documents.id to link to this chase")
    partial: bool = Field(
        False, description="True when only partial records were received"
    )
    received_date: date | None = None
    notes: str | None = None


class CancelRequest(BaseModel):
    notes: str | None = None


class TemplateCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    type: Literal["fax_cover", "email", "letter"]
    subject: str | None = Field(None, max_length=500, description="Required for email templates")
    body: str = Field(..., min_length=1)


class BulkChaseItem(BaseModel):
    patient_id: int
    reason: Literal[
        "suspect_hcc",
        "audit_response",
        "missing_encounter",
        "incomplete_documentation",
    ]
    provider_npi: str | None = None
    hcc_codes: list[int] | None = None
    dos_from: date | None = None
    dos_to: date | None = None
    priority: Literal["critical", "high", "medium", "low"] = "medium"
    facility_name: str | None = None
    facility_fax: str | None = None
    facility_email: str | None = None
    facility_phone: str | None = None
    due_date: date | None = None
    notes: str | None = None


class BulkChaseRequest(BaseModel):
    items: list[BulkChaseItem] = Field(..., min_length=1, description="Chase requests to create")
    default_priority: Literal["critical", "high", "medium", "low"] = "medium"
    default_due_days: int = Field(
        default=30, ge=1, le=365,
        description="Days from today to set due_date when not explicitly provided",
    )


# ---------------------------------------------------------------------------
# GET /api/chart-chase  —  list with filters
# ---------------------------------------------------------------------------

@router.get("", summary="List chart chase requests")
def list_chases(
    status: str | None = Query(None, description="pending|sent|acknowledged|received|partial|completed|cancelled"),
    priority: str | None = Query(None, description="critical|high|medium|low"),
    patient_id: int | None = Query(None),
    provider_npi: str | None = Query(None),
    reason: str | None = Query(None),
    due_before: date | None = Query(None, description="ISO date — return chases due on or before this date"),
    limit: int = Query(default=200, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
    _perm: None = Depends(require_permission("chart_chase", "read")),
) -> dict[str, Any]:
    """
    Return chart chase requests filtered by any combination of status,
    priority, patient, provider, reason, or due date.

    Results are ordered by priority (critical first) then due_date ascending.
    """
    try:
        chases = svc.list_chases(
            tenant_id=tenant_id,
            status=status,
            priority=priority,
            patient_id=patient_id,
            provider_npi=provider_npi,
            reason=reason,
            due_before=due_before,
            limit=limit,
            offset=offset,
        )
    except Exception as exc:
        logger.error("list_chases failed: %s", exc)
        raise HTTPException(status_code=500, detail="Internal server error")

    return {"count": len(chases), "chases": chases}


# ---------------------------------------------------------------------------
# GET /api/chart-chase/dashboard  —  must appear BEFORE /{id}
# ---------------------------------------------------------------------------

@router.get("/dashboard", summary="Chart chase dashboard — aging report and stats")
def dashboard(
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
    _perm: None = Depends(require_permission("chart_chase", "read")),
) -> dict[str, Any]:
    """
    Return aggregate chart chase statistics for the ops dashboard:

    - Open / overdue counts
    - Breakdown by status and priority
    - Aging buckets (0-7, 8-14, 15-30, 30+ days)
    - 30-day completion rate
    - Average days from request to receipt
    """
    try:
        return svc.get_dashboard(tenant_id=tenant_id)
    except Exception as exc:
        logger.error("dashboard failed: %s", exc)
        raise HTTPException(status_code=500, detail="Internal server error")


# ---------------------------------------------------------------------------
# GET /api/chart-chase/templates
# ---------------------------------------------------------------------------

@router.get("/templates", summary="List outreach templates")
def list_templates(
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
    _perm: None = Depends(require_permission("chart_chase", "read")),
) -> dict[str, Any]:
    """Return all fax / email / letter templates for the tenant."""
    try:
        templates = svc.list_templates(tenant_id=tenant_id)
    except Exception as exc:
        logger.error("list_templates failed: %s", exc)
        raise HTTPException(status_code=500, detail="Internal server error")

    return {"count": len(templates), "templates": templates}


# ---------------------------------------------------------------------------
# POST /api/chart-chase/templates
# ---------------------------------------------------------------------------

@router.post("/templates", summary="Create an outreach template")
def create_template(
    body: TemplateCreateRequest,
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
    _perm: None = Depends(require_permission("chart_chase", "write")),
) -> dict[str, Any]:
    """
    Create a new fax cover sheet, email, or letter template.

    Body::

        {
          "name": "Initial HCC Request",
          "type": "fax_cover",
          "body": "Dear {{facility_name}}, we are requesting records for ..."
        }
    """
    try:
        template = svc.create_template({**body.model_dump(), "tenant_id": tenant_id})
    except Exception as exc:
        logger.error("create_template failed: %s", exc)
        raise HTTPException(status_code=500, detail="Internal server error")

    return {"status": "created", "template": template}


# ---------------------------------------------------------------------------
# POST /api/chart-chase/bulk  —  must appear BEFORE /{id}
# ---------------------------------------------------------------------------

@router.post("/bulk", summary="Bulk create chart chase requests")
def bulk_create(
    body: BulkChaseRequest,
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
    _perm: None = Depends(require_permission("chart_chase", "write")),
) -> dict[str, Any]:
    """
    Create multiple chase requests in a single call.  Designed for bulk
    generation from a suspect conditions export or audit worklist.

    Items that fail validation or DB insertion are captured in the ``errors``
    array; the remaining items are still created.

    Body::

        {
          "items": [
            { "patient_id": 42, "reason": "suspect_hcc", "hcc_codes": [18, 85] },
            { "patient_id": 99, "reason": "missing_encounter", "priority": "high" }
          ],
          "default_due_days": 30
        }
    """
    try:
        result = svc.bulk_create_chases(
            [item.model_dump() for item in body.items],
            requesting_user_id=int(current_user.get("user_id") or current_user.get("id") or 0),
            tenant_id=tenant_id,
            default_priority=body.default_priority,
            default_due_days=body.default_due_days,
        )
    except Exception as exc:
        logger.error("bulk_create failed: %s", exc)
        raise HTTPException(status_code=500, detail="Internal server error")

    return result


# ---------------------------------------------------------------------------
# POST /api/chart-chase  —  create single request
# ---------------------------------------------------------------------------

@router.post("", summary="Create a chart chase request")
def create_chase(
    body: ChaseCreateRequest,
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
    _perm: None = Depends(require_permission("chart_chase", "write")),
) -> dict[str, Any]:
    """
    Create a new chart chase request for a patient.

    Body::

        {
          "patient_id": 42,
          "reason": "suspect_hcc",
          "hcc_codes": [18, 85],
          "priority": "high",
          "facility_name": "Acme Medical Group",
          "facility_fax": "555-000-1234",
          "due_date": "2026-05-01"
        }
    """
    data = body.model_dump()
    data["requesting_user_id"] = int(
        current_user.get("user_id") or current_user.get("id") or 0
    )
    data["tenant_id"] = tenant_id
    try:
        chase = svc.create_chase(data)
    except Exception as exc:
        logger.error("create_chase failed: %s", exc)
        raise HTTPException(status_code=500, detail="Internal server error")

    return {"status": "created", "chase": chase}


# ---------------------------------------------------------------------------
# GET /api/chart-chase/{id}
# ---------------------------------------------------------------------------

@router.get("/{chase_id}", summary="Get chart chase request detail")
def get_chase(
    chase_id: int,
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
    _perm: None = Depends(require_permission("chart_chase", "read")),
) -> dict[str, Any]:
    """Return a single chase request including its full attempt history."""
    try:
        chase = svc.get_chase(chase_id, tenant_id=tenant_id)
    except ValueError as exc:
        logger.warning("get_chase id=%s not found: %s", chase_id, exc)
        raise HTTPException(status_code=404, detail="Resource not found")
    except Exception as exc:
        logger.error("get_chase id=%s: %s", chase_id, exc)
        raise HTTPException(status_code=500, detail="Internal server error")

    return {"chase": chase}


# ---------------------------------------------------------------------------
# PUT /api/chart-chase/{id}
# ---------------------------------------------------------------------------

@router.put("/{chase_id}", summary="Update a chart chase request")
def update_chase(
    chase_id: int,
    body: ChaseUpdateRequest,
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
    _perm: None = Depends(require_permission("chart_chase", "write")),
) -> dict[str, Any]:
    """
    Update mutable fields on an existing chase request.  Only fields that
    are explicitly provided in the request body are changed.

    Body::

        {
          "priority": "critical",
          "due_date": "2026-04-15",
          "notes": "Patient flagged for CMS audit — expedite"
        }
    """
    updates = {k: v for k, v in body.model_dump().items() if v is not None}
    try:
        chase = svc.update_chase(chase_id, updates, tenant_id=tenant_id)
    except ValueError as exc:
        logger.warning("update_chase id=%s not found: %s", chase_id, exc)
        raise HTTPException(status_code=404, detail="Resource not found")
    except Exception as exc:
        logger.error("update_chase id=%s: %s", chase_id, exc)
        raise HTTPException(status_code=500, detail="Internal server error")

    return {"status": "updated", "chase": chase}


# ---------------------------------------------------------------------------
# POST /api/chart-chase/{id}/attempt
# ---------------------------------------------------------------------------

@router.post("/{chase_id}/attempt", summary="Log an outreach attempt")
def log_attempt(
    chase_id: int,
    body: AttemptRequest,
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
    _perm: None = Depends(require_permission("chart_chase", "write")),
) -> dict[str, Any]:
    """
    Record one outreach attempt against a chase request.

    After 3 attempts without a terminal status the chase type is automatically
    promoted to ``'escalation'``.  The first attempt on a ``'pending'`` chase
    also flips its status to ``'sent'``.

    Body::

        {
          "method": "fax",
          "notes": "Sent to 555-000-1234 at 9 am"
        }
    """
    sent_by = str(
        current_user.get("username")
        or current_user.get("email")
        or current_user.get("user_id")
        or "unknown"
    )
    try:
        chase = svc.log_attempt(
            chase_id,
            tenant_id=tenant_id,
            method=body.method,
            sent_by=sent_by,
            response=body.response,
            responded_at=body.responded_at,
            notes=body.notes,
        )
    except ValueError as exc:
        logger.warning("log_attempt chase_id=%s validation error: %s", chase_id, exc)
        raise HTTPException(status_code=422, detail=str(exc))
    except Exception as exc:
        logger.error("log_attempt chase_id=%s: %s", chase_id, exc)
        raise HTTPException(status_code=500, detail="Internal server error")

    return {"status": "attempt_logged", "chase": chase}


# ---------------------------------------------------------------------------
# PUT /api/chart-chase/{id}/receive
# ---------------------------------------------------------------------------

@router.put("/{chase_id}/receive", summary="Mark chase as received, optionally link a document")
def receive_chase(
    chase_id: int,
    body: ReceiveRequest,
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
    _perm: None = Depends(require_permission("chart_chase", "write")),
) -> dict[str, Any]:
    """
    Mark a chase as received (or partially received) and optionally link
    the uploaded document record.

    Body::

        {
          "document_id": 17,
          "partial": false,
          "received_date": "2026-04-02",
          "notes": "Complete records received via fax"
        }
    """
    try:
        chase = svc.receive_chase(
            chase_id,
            tenant_id=tenant_id,
            document_id=body.document_id,
            partial=body.partial,
            received_date=body.received_date,
            notes=body.notes,
        )
    except ValueError as exc:
        logger.warning("receive_chase id=%s validation error: %s", chase_id, exc)
        raise HTTPException(status_code=422, detail=str(exc))
    except Exception as exc:
        logger.error("receive_chase id=%s: %s", chase_id, exc)
        raise HTTPException(status_code=500, detail="Internal server error")

    return {"status": "received", "chase": chase}


# ---------------------------------------------------------------------------
# PUT /api/chart-chase/{id}/cancel
# ---------------------------------------------------------------------------

@router.put("/{chase_id}/cancel", summary="Cancel a chart chase request")
def cancel_chase(
    chase_id: int,
    body: CancelRequest,
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
    _perm: None = Depends(require_permission("chart_chase", "write")),
) -> dict[str, Any]:
    """
    Cancel a chase request.  A cancelled chase is immutable; no further
    attempts can be logged against it.

    Body::

        { "notes": "Patient disenrolled" }
    """
    try:
        chase = svc.cancel_chase(chase_id, tenant_id=tenant_id, notes=body.notes)
    except ValueError as exc:
        logger.warning("cancel_chase id=%s not found: %s", chase_id, exc)
        raise HTTPException(status_code=404, detail="Resource not found")
    except Exception as exc:
        logger.error("cancel_chase id=%s: %s", chase_id, exc)
        raise HTTPException(status_code=500, detail="Internal server error")

    return {"status": "cancelled", "chase": chase}
