"""
Coder Worklist router — HTTP interface for the coder review queue.

Endpoints
---------
GET  /api/worklist                — coder's queue (paginated, filterable)
GET  /api/worklist/next           — claim the next available item
GET  /api/worklist/stats          — coder productivity metrics
GET  /api/worklist/{id}           — single item detail
PUT  /api/worklist/{id}/start     — move item to in_progress
PUT  /api/worklist/{id}/complete  — complete with coding decisions
PUT  /api/worklist/{id}/escalate  — escalate to supervisor
PUT  /api/worklist/{id}/return    — return for additional clinical info
POST /api/worklist/assign         — manual assignment (manager role)
POST /api/worklist/auto-queue     — trigger auto-assignment from source data

All endpoints require a valid JWT bearer token.
`/assign` and `/auto-queue` additionally require the `worklist:manage` permission
(manager / admin roles).
"""
# Note: do NOT use 'from __future__ import annotations' here —
# it breaks FastAPI/Pydantic schema generation.

import logging
from datetime import date
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.auth import get_current_user, get_tenant_id, require_permission
from app.services.coder_worklist_service import (
    _fetch_item,
    assign_item,
    auto_queue_from_claims,
    auto_queue_from_nlp,
    claim_next,
    complete_review,
    escalate_item,
    get_productivity_stats,
    get_worklist,
    return_item,
    start_review,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/worklist", tags=["worklist"])


# ---------------------------------------------------------------------------
# Pydantic request / response models
# ---------------------------------------------------------------------------

class StartRequest(BaseModel):
    """No body fields required — action is implicit."""
    pass


class CodingDecision(BaseModel):
    hcc: int = Field(..., description="HCC code number being decided on, e.g. 85")
    icd10: str = Field(..., description="ICD-10-CM code supporting this HCC")
    action: Literal["confirm", "reject", "add", "query"] = Field(
        ..., description="Coding decision for this HCC"
    )
    rationale: str = Field(default="", description="Free-text clinical rationale")


class CompleteRequest(BaseModel):
    coding_decisions: list[CodingDecision] = Field(
        ..., min_length=1, description="Coder's decisions for each HCC under review"
    )
    notes: str | None = Field(default=None, description="Optional free-text coder notes")


class EscalateRequest(BaseModel):
    reason: str = Field(
        ..., min_length=5, description="Reason the item requires supervisor attention"
    )


class ReturnRequest(BaseModel):
    reason: str = Field(
        ..., min_length=5, description="Description of the additional information needed"
    )


class AssignRequest(BaseModel):
    patient_id: int = Field(..., description="OpenEMR patient PID")
    coder_user_id: int = Field(..., description="ID of the coder to assign this item to")
    review_type: Literal[
        "initial_coding", "suspect_review", "audit_response", "recapture"
    ] = Field(default="suspect_review")
    encounter_id: int | None = Field(default=None, description="OpenEMR encounter ID")
    priority: int = Field(default=3, ge=1, le=5, description="1 = highest, 5 = lowest")
    due_date: date | None = Field(default=None, description="ISO-8601 deadline date")
    hcc_codes: list[int] | None = Field(
        default=None, description="HCC codes to include in this review"
    )
    notes: str | None = Field(default=None, description="Assignment notes for the coder")


class NlpEntry(BaseModel):
    patient_id: int
    encounter_id: int | None = None
    hcc_codes: list[int] = Field(default_factory=list)
    priority: int = Field(default=3, ge=1, le=5)
    due_date: date | None = None


class ClaimsEntry(BaseModel):
    patient_id: int
    encounter_id: int | None = None
    hcc_codes: list[int] = Field(default_factory=list)
    priority: int = Field(default=2, ge=1, le=5)
    due_date: date | None = None


class AutoQueueRequest(BaseModel):
    source: Literal["nlp", "claims"] = Field(
        ..., description="Source of the items to enqueue"
    )
    items: list[NlpEntry | ClaimsEntry] = Field(
        ..., min_length=1, description="List of items to auto-queue"
    )


# ---------------------------------------------------------------------------
# GET /api/worklist  —  coder's queue
# ---------------------------------------------------------------------------

@router.get("", summary="Get the current coder's review queue")
def list_worklist(
    status: str | None = Query(
        default=None,
        description="Filter by status: queued | in_progress | completed | returned | escalated. "
                    "Defaults to queued + in_progress.",
    ),
    review_type: str | None = Query(
        default=None,
        description="Filter by review type: initial_coding | suspect_review | audit_response | recapture",
    ),
    limit: int = Query(default=50, ge=1, le=200, description="Page size"),
    offset: int = Query(default=0, ge=0, description="Pagination offset"),
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
    _perm: None = Depends(require_permission("worklist", "read")),
) -> dict[str, Any]:
    """
    Returns the authenticated coder's work queue sorted by priority then due
    date.  Coders only see their own items; managers call the reports endpoints
    for cross-coder views.
    """
    coder_id: int = int(current_user["id"])

    try:
        return get_worklist(
            coder_user_id=coder_id,
            tenant_id=tenant_id,
            status=status,
            review_type=review_type,
            limit=limit,
            offset=offset,
        )
    except Exception as exc:
        logger.error("list_worklist coder=%s: %s", coder_id, exc)
        raise HTTPException(status_code=500, detail="Internal server error")


# ---------------------------------------------------------------------------
# GET /api/worklist/next  —  claim next item (must come before /{id})
# ---------------------------------------------------------------------------

@router.get("/next", summary="Claim the next queued item from the coder's queue")
def get_next_item(
    review_type: str | None = Query(
        default=None,
        description="Optionally restrict to a specific review type",
    ),
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
    _perm: None = Depends(require_permission("worklist", "write")),
) -> dict[str, Any]:
    """
    Atomically claims the highest-priority queued item assigned to the calling
    coder and transitions it to *in_progress*.

    Returns the claimed item, or a 204-equivalent JSON response when the queue
    is empty (`{"message": "Queue is empty", "item": null}`).
    """
    coder_id: int = int(current_user["id"])

    try:
        item = claim_next(
            coder_user_id=coder_id,
            tenant_id=tenant_id,
            review_type=review_type,
        )
    except Exception as exc:
        logger.error("get_next_item coder=%s: %s", coder_id, exc)
        raise HTTPException(status_code=500, detail="Internal server error")

    if item is None:
        return {"message": "Queue is empty", "item": None}

    return {"message": "Item claimed", "item": item}


# ---------------------------------------------------------------------------
# GET /api/worklist/stats  —  productivity (must come before /{id})
# ---------------------------------------------------------------------------

@router.get("/stats", summary="Get coder productivity metrics")
def worklist_stats(
    days: int = Query(default=30, ge=1, le=365, description="Rolling window in calendar days"),
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
    _perm: None = Depends(require_permission("worklist", "read")),
) -> dict[str, Any]:
    """
    Returns productivity metrics for the authenticated coder:
    total completed, average cycle time, accuracy rate, and daily history.
    """
    coder_id: int = int(current_user["id"])

    try:
        return get_productivity_stats(
            coder_user_id=coder_id,
            tenant_id=tenant_id,
            days=days,
        )
    except Exception as exc:
        logger.error("worklist_stats coder=%s: %s", coder_id, exc)
        raise HTTPException(status_code=500, detail="Internal server error")


# ---------------------------------------------------------------------------
# GET /api/worklist/{id}  —  item detail
# ---------------------------------------------------------------------------

@router.get("/{item_id}", summary="Get a single worklist item")
def get_item(
    item_id: int,
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
    _perm: None = Depends(require_permission("worklist", "read")),
) -> dict[str, Any]:
    """
    Returns full detail for the requested worklist item.

    Coders may only read items assigned to them.  Managers and admins may
    read any item in their tenant.
    """
    item = _fetch_item(item_id)
    if not item:
        raise HTTPException(status_code=404, detail=f"Worklist item {item_id} not found")

    coder_id: int = int(current_user["id"])
    role: str = current_user.get("role", "coder")

    # Coders can only see their own items
    if role == "coder" and item["coder_user_id"] != coder_id:
        raise HTTPException(status_code=403, detail="Access denied to this worklist item")

    # Tenant boundary check
    if item.get("tenant_id") != tenant_id and role not in ("admin", "super_admin"):
        raise HTTPException(status_code=403, detail="Access denied to this worklist item")

    return item


# ---------------------------------------------------------------------------
# PUT /api/worklist/{id}/start
# ---------------------------------------------------------------------------

@router.put("/{item_id}/start", summary="Start a worklist review")
def start_item(
    item_id: int,
    current_user: dict = Depends(get_current_user),
    _perm: None = Depends(require_permission("worklist", "write")),
) -> dict[str, Any]:
    """
    Transitions the worklist item from *queued* (or *returned*) to
    *in_progress* and stamps ``started_at``.
    """
    coder_id: int = int(current_user["id"])
    try:
        updated = start_review(item_id, coder_user_id=coder_id)
    except ValueError as exc:
        logger.warning("start_item id=%s validation error: %s", item_id, exc)
        raise HTTPException(status_code=422, detail=str(exc))
    except Exception as exc:
        logger.error("start_item id=%s coder=%s: %s", item_id, coder_id, exc)
        raise HTTPException(status_code=500, detail="Internal server error")

    return {"item_id": item_id, "action": "started", "item": updated}


# ---------------------------------------------------------------------------
# PUT /api/worklist/{id}/complete
# ---------------------------------------------------------------------------

@router.put("/{item_id}/complete", summary="Complete a worklist review with coding decisions")
def complete_item(
    item_id: int,
    body: CompleteRequest,
    current_user: dict = Depends(get_current_user),
    _perm: None = Depends(require_permission("worklist", "write")),
) -> dict[str, Any]:
    """
    Marks the worklist item as *completed* and persists the coder's coding
    decisions.

    Body example::

        {
          "coding_decisions": [
            {"hcc": 85, "icd10": "I50.9", "action": "confirm", "rationale": "CHF noted in H&P"},
            {"hcc": 18, "icd10": "E11.9",  "action": "add",     "rationale": "A1c 9.2 supports T2DM"}
          ],
          "notes": "Awaiting next visit for HCC 111 documentation"
        }
    """
    coder_id: int = int(current_user["id"])
    decisions_raw = [d.model_dump() for d in body.coding_decisions]

    try:
        updated = complete_review(
            item_id,
            coder_user_id=coder_id,
            coding_decisions=decisions_raw,
            notes=body.notes,
        )
    except ValueError as exc:
        logger.warning("complete_item id=%s validation error: %s", item_id, exc)
        raise HTTPException(status_code=422, detail=str(exc))
    except Exception as exc:
        logger.error("complete_item id=%s coder=%s: %s", item_id, coder_id, exc)
        raise HTTPException(status_code=500, detail="Internal server error")

    return {
        "item_id": item_id,
        "action": "completed",
        "decisions_recorded": len(decisions_raw),
        "item": updated,
    }


# ---------------------------------------------------------------------------
# PUT /api/worklist/{id}/escalate
# ---------------------------------------------------------------------------

@router.put("/{item_id}/escalate", summary="Escalate a worklist item to supervisor")
def escalate(
    item_id: int,
    body: EscalateRequest,
    current_user: dict = Depends(get_current_user),
    _perm: None = Depends(require_permission("worklist", "write")),
) -> dict[str, Any]:
    """
    Escalates the item so a supervisor can review and re-route it.

    Body::

        {"reason": "Patient has conflicting diagnoses across two facilities"}
    """
    coder_id: int = int(current_user["id"])
    try:
        updated = escalate_item(item_id, coder_user_id=coder_id, reason=body.reason)
    except ValueError as exc:
        logger.warning("escalate id=%s validation error: %s", item_id, exc)
        raise HTTPException(status_code=422, detail=str(exc))
    except Exception as exc:
        logger.error("escalate id=%s coder=%s: %s", item_id, coder_id, exc)
        raise HTTPException(status_code=500, detail="Internal server error")

    return {"item_id": item_id, "action": "escalated", "reason": body.reason, "item": updated}


# ---------------------------------------------------------------------------
# PUT /api/worklist/{id}/return
# ---------------------------------------------------------------------------

@router.put("/{item_id}/return", summary="Return a worklist item for additional information")
def return_for_info(
    item_id: int,
    body: ReturnRequest,
    current_user: dict = Depends(get_current_user),
    _perm: None = Depends(require_permission("worklist", "write")),
) -> dict[str, Any]:
    """
    Returns the item to a *returned* state when the coder needs more clinical
    information before completing the review.

    Body::

        {"reason": "No encounter notes available for DOS 2026-03-15"}
    """
    coder_id: int = int(current_user["id"])
    try:
        updated = return_item(item_id, coder_user_id=coder_id, reason=body.reason)
    except ValueError as exc:
        logger.warning("return_for_info id=%s validation error: %s", item_id, exc)
        raise HTTPException(status_code=422, detail=str(exc))
    except Exception as exc:
        logger.error("return_for_info id=%s coder=%s: %s", item_id, coder_id, exc)
        raise HTTPException(status_code=500, detail="Internal server error")

    return {"item_id": item_id, "action": "returned", "reason": body.reason, "item": updated}


# ---------------------------------------------------------------------------
# POST /api/worklist/assign  —  manual assignment (manager)
# ---------------------------------------------------------------------------

@router.post("/assign", summary="Manually assign a new worklist item to a coder")
def manual_assign(
    body: AssignRequest,
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
    _perm: None = Depends(require_permission("worklist", "manage")),
) -> dict[str, Any]:
    """
    Creates a new worklist item and assigns it directly to a specific coder.
    Requires the `worklist:manage` permission (manager / admin roles).

    Body example::

        {
          "patient_id": 1042,
          "coder_user_id": 7,
          "review_type": "audit_response",
          "priority": 1,
          "due_date": "2026-04-10",
          "hcc_codes": [85, 111],
          "notes": "RADV audit — please review DOS 2025-11-15"
        }
    """
    assigning_user_id: int = int(current_user["id"])

    try:
        item = assign_item(
            patient_id=body.patient_id,
            coder_user_id=body.coder_user_id,
            assigning_user_id=assigning_user_id,
            review_type=body.review_type,
            encounter_id=body.encounter_id,
            priority=body.priority,
            due_date=body.due_date,
            hcc_codes=body.hcc_codes,
            notes=body.notes,
            tenant_id=tenant_id,
            source="manual",
        )
    except Exception as exc:
        logger.error("manual_assign user=%s: %s", assigning_user_id, exc)
        raise HTTPException(status_code=500, detail="Internal server error")

    return {"action": "assigned", "item": item}


# ---------------------------------------------------------------------------
# POST /api/worklist/auto-queue  —  auto-assignment trigger
# ---------------------------------------------------------------------------

@router.post("/auto-queue", summary="Trigger auto-assignment from NLP or claims results")
def auto_queue(
    body: AutoQueueRequest,
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
    _perm: None = Depends(require_permission("worklist", "manage")),
) -> dict[str, Any]:
    """
    Feeds a batch of items from NLP analysis or claims processing into the
    worklist using load-balanced round-robin coder assignment.
    Requires the `worklist:manage` permission.

    Body example (NLP source)::

        {
          "source": "nlp",
          "tenant_id": "default",
          "items": [
            {"patient_id": 1042, "encounter_id": 9901, "hcc_codes": [85, 18], "priority": 2},
            {"patient_id": 1055, "hcc_codes": [111], "due_date": "2026-04-15"}
          ]
        }
    """
    assigning_user_id: int = int(current_user["id"])
    items_raw: list[dict] = [i.model_dump() for i in body.items]

    try:
        if body.source == "nlp":
            result = auto_queue_from_nlp(
                nlp_results=items_raw,
                assigning_user_id=assigning_user_id,
                tenant_id=tenant_id,
            )
        else:
            result = auto_queue_from_claims(
                claims_results=items_raw,
                assigning_user_id=assigning_user_id,
                tenant_id=tenant_id,
            )
    except Exception as exc:
        logger.error("auto_queue user=%s source=%s: %s", assigning_user_id, body.source, exc)
        raise HTTPException(status_code=500, detail="Internal server error")

    return {"source": body.source, **result}
