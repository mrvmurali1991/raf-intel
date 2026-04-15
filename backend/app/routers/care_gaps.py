"""
Care Gap Closure Workflow router.

Endpoints
---------
GET    /api/care-gaps                  – list with filters and pagination
POST   /api/care-gaps                  – create a gap task
GET    /api/care-gaps/dashboard        – summary statistics
POST   /api/care-gaps/bulk-assign      – bulk-assign tasks to a user
POST   /api/care-gaps/generate         – auto-generate tasks from suspect conditions
GET    /api/care-gaps/{id}             – task detail (with comments and history)
PUT    /api/care-gaps/{id}             – partial update
PUT    /api/care-gaps/{id}/assign      – assign to a user
PUT    /api/care-gaps/{id}/status      – transition status
POST   /api/care-gaps/{id}/comments    – add a comment

All endpoints require a valid JWT and the "care_gaps" resource permission.
Write operations require "write" scope; read operations require "read" scope.
"""
# Removed: from __future__ import annotations (breaks FastAPI schema generation)

import logging
from datetime import date
from typing import Any, Literal

from fastapi import Depends, APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.auth import get_current_user, get_tenant_id, require_permission
from app.services.care_gap_service import (
    add_comment,
    assign_gap_task,
    bulk_assign_gap_tasks,
    create_gap_task,
    generate_gaps_from_suspects,
    get_comments,
    get_dashboard_stats,
    get_gap_task,
    get_history,
    list_gap_tasks,
    transition_status,
    update_gap_task,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/care-gaps", tags=["care_gaps"])


# ---------------------------------------------------------------------------
# Pydantic request models
# ---------------------------------------------------------------------------

class GapTaskCreate(BaseModel):
    """Payload for creating a new care gap task."""

    patient_id: int
    provider_id: int
    hcc_code: str = Field(..., min_length=1, max_length=20)
    hcc_description: str = Field(default="", max_length=500)
    gap_type: Literal["suspect", "recapture", "new"] = "suspect"
    priority: Literal["critical", "high", "medium", "low"] = "medium"
    due_date: date | None = None
    notes: str | None = None
    evidence_summary: str | None = None
    assigned_to: int | None = None
    suspect_condition_id: int | None = None


class GapTaskUpdate(BaseModel):
    """Partial update payload — all fields optional."""

    hcc_description: str | None = Field(default=None, max_length=500)
    priority: Literal["critical", "high", "medium", "low"] | None = None
    due_date: date | None = None
    notes: str | None = None
    evidence_summary: str | None = None


class AssignRequest(BaseModel):
    """Assign or re-assign a task to a user."""

    assigned_to: int = Field(..., description="User ID to assign the task to")
    note: str | None = Field(default=None, description="Optional note about the assignment")


class StatusTransitionRequest(BaseModel):
    """Request a status change for a gap task."""

    status: Literal["open", "in_progress", "scheduled", "completed", "rejected"]
    note: str | None = Field(default=None, description="Reason or context for the transition")


class CommentCreate(BaseModel):
    """Add a comment to a gap task."""

    comment: str = Field(..., min_length=1, description="Comment text")


class BulkAssignRequest(BaseModel):
    """Bulk-assign a list of gap tasks to a single user."""

    task_ids: list[int] = Field(..., min_length=1, description="Task IDs to assign")
    assigned_to: int = Field(..., description="User ID to assign all tasks to")


class GenerateGapsRequest(BaseModel):
    """Options for auto-generating gap tasks from suspect conditions."""

    provider_id: int | None = Field(
        default=None,
        description="Restrict generation to a specific provider's patient panel",
    )
    patient_id: int | None = Field(
        default=None,
        description="Restrict generation to a single patient",
    )
    min_confidence: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description="Minimum suspect confidence score to include",
    )
    priority_threshold: float = Field(
        default=0.8,
        ge=0.0,
        le=1.0,
        description="Suspects at or above this confidence score receive 'high' priority",
    )


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _get_or_404(task_id: int) -> dict[str, Any]:
    task = get_gap_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail=f"Care gap task {task_id} not found")
    return task


# ---------------------------------------------------------------------------
# Static-path routes — must be declared BEFORE /{id} to avoid path shadowing
# ---------------------------------------------------------------------------

@router.get("/dashboard", summary="Care gap dashboard statistics")
def dashboard(
    provider_id: int | None = Query(default=None, description="Scope stats to a single provider"),
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
    _perm: None = Depends(require_permission("care_gaps", "read")),
) -> dict[str, Any]:
    """
    Return aggregate care gap counts for the dashboard.

    Statistics include open / in_progress / scheduled / completed / rejected counts,
    overdue count, closure rate, breakdowns by priority and gap type, and
    (when not scoped to a single provider) the top 10 providers by open task count.
    """
    try:
        return get_dashboard_stats(provider_id=provider_id, tenant_id=tenant_id)
    except Exception as exc:
        logger.error("care_gap dashboard error: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/bulk-assign", summary="Bulk-assign multiple gap tasks to a user")
def bulk_assign(
    body: BulkAssignRequest,
    current_user: dict = Depends(get_current_user),
    _perm: None = Depends(require_permission("care_gaps", "write")),
) -> dict[str, Any]:
    """
    Assign all tasks in ``task_ids`` to the user identified by ``assigned_to``
    in a single transaction.

    Body::

        {
          "task_ids": [1, 2, 3],
          "assigned_to": 42
        }
    """
    user_id: int = int(current_user.get("id") or current_user.get("user_id") or 0)
    try:
        return bulk_assign_gap_tasks(
            task_ids=body.task_ids,
            assigned_to=body.assigned_to,
            user_id=user_id,
        )
    except Exception as exc:
        logger.error("bulk_assign error: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/generate", summary="Auto-generate care gap tasks from suspect conditions")
def generate_gaps(
    body: GenerateGapsRequest,
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
    _perm: None = Depends(require_permission("care_gaps", "write")),
) -> dict[str, Any]:
    """
    Scan ``raf_suspect_conditions`` and create gap tasks for all open suspects
    that do not yet have an associated task.

    Optionally scope the scan to a specific provider's patient panel or a single
    patient.  Suspects below ``min_confidence`` are excluded.  Suspects at or
    above ``priority_threshold`` receive *high* priority; others receive *medium*.

    Already-linked suspects are silently skipped — calling this endpoint
    multiple times is safe (idempotent for already-created tasks).
    """
    user_id: int = int(current_user.get("id") or current_user.get("user_id") or 0)
    try:
        return generate_gaps_from_suspects(
            provider_id=body.provider_id,
            patient_id=body.patient_id,
            min_confidence=body.min_confidence,
            priority_threshold=body.priority_threshold,
            created_by=user_id,
            tenant_id=tenant_id,
        )
    except Exception as exc:
        logger.error("generate_gaps error: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


# ---------------------------------------------------------------------------
# Collection routes
# ---------------------------------------------------------------------------

@router.get("", summary="List care gap tasks")
def list_tasks(
    provider_id: int | None = Query(default=None, description="Filter by responsible provider"),
    assigned_to: int | None = Query(default=None, description="Filter by assignee user ID"),
    patient_id: int | None = Query(default=None, description="Filter by patient ID"),
    status: str | None = Query(
        default=None,
        description="Filter by status: open | in_progress | scheduled | completed | rejected",
    ),
    priority: str | None = Query(
        default=None,
        description="Filter by priority: critical | high | medium | low",
    ),
    gap_type: str | None = Query(
        default=None,
        description="Filter by gap type: suspect | recapture | new",
    ),
    due_before: date | None = Query(default=None, description="Tasks due on or before this date (YYYY-MM-DD)"),
    due_after: date | None = Query(default=None, description="Tasks due on or after this date (YYYY-MM-DD)"),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
    _perm: None = Depends(require_permission("care_gaps", "read")),
) -> dict[str, Any]:
    """
    Return a paginated, filtered list of care gap tasks.

    Results are ordered by priority (critical first), then due date ascending,
    then creation date descending so the most urgent actionable tasks appear
    at the top.
    """
    try:
        tasks = list_gap_tasks(
            provider_id=provider_id,
            assigned_to=assigned_to,
            patient_id=patient_id,
            status=status,
            priority=priority,
            gap_type=gap_type,
            due_before=due_before,
            due_after=due_after,
            tenant_id=tenant_id,
            limit=limit,
            offset=offset,
        )
    except Exception as exc:
        logger.error("list_tasks error: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")

    return {
        "count": len(tasks),
        "limit": limit,
        "offset": offset,
        "tasks": tasks,
    }


@router.post("", summary="Create a care gap task", status_code=201)
def create_task(
    body: GapTaskCreate,
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
    _perm: None = Depends(require_permission("care_gaps", "write")),
) -> dict[str, Any]:
    """
    Create a new care gap task.

    Body::

        {
          "patient_id": 101,
          "provider_id": 5,
          "hcc_code": "HCC18",
          "hcc_description": "Diabetes with Chronic Complications",
          "gap_type": "suspect",
          "priority": "high",
          "due_date": "2026-06-30",
          "assigned_to": 42
        }
    """
    user_id: int = int(current_user.get("id") or current_user.get("user_id") or 0)
    try:
        return create_gap_task(
            patient_id=body.patient_id,
            provider_id=body.provider_id,
            hcc_code=body.hcc_code,
            hcc_description=body.hcc_description,
            gap_type=body.gap_type,
            priority=body.priority,
            due_date=body.due_date,
            notes=body.notes,
            evidence_summary=body.evidence_summary,
            assigned_to=body.assigned_to,
            suspect_condition_id=body.suspect_condition_id,
            created_by=user_id,
            tenant_id=tenant_id,
        )
    except Exception as exc:
        logger.error("create_task error: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


# ---------------------------------------------------------------------------
# Instance routes  /{id}  and  /{id}/sub-resources
# ---------------------------------------------------------------------------

@router.get("/{task_id}", summary="Get care gap task detail")
def get_task(
    task_id: int,
    include_comments: bool = Query(default=True, description="Include comment thread"),
    include_history: bool = Query(default=True, description="Include audit history"),
    current_user: dict = Depends(get_current_user),
    _perm: None = Depends(require_permission("care_gaps", "read")),
) -> dict[str, Any]:
    """
    Return a single care gap task by ID, optionally enriched with its comment
    thread and full audit history.
    """
    task = _get_or_404(task_id)
    result: dict[str, Any] = {"task": task}

    if include_comments:
        try:
            result["comments"] = get_comments(task_id)
        except Exception as exc:
            logger.warning("get_task comments error task=%s: %s", task_id, exc)
            result["comments"] = []

    if include_history:
        try:
            result["history"] = get_history(task_id)
        except Exception as exc:
            logger.warning("get_task history error task=%s: %s", task_id, exc)
            result["history"] = []

    return result


@router.put("/{task_id}", summary="Partial update a care gap task")
def update_task(
    task_id: int,
    body: GapTaskUpdate,
    current_user: dict = Depends(get_current_user),
    _perm: None = Depends(require_permission("care_gaps", "write")),
) -> dict[str, Any]:
    """
    Partially update a care gap task.  Only supplied (non-null) fields are
    written.

    Status and assignment changes must use their dedicated endpoints to ensure
    audit trails are maintained correctly.
    """
    _get_or_404(task_id)
    user_id: int = int(current_user.get("id") or current_user.get("user_id") or 0)
    updates = body.model_dump(exclude_none=True)
    try:
        updated = update_gap_task(task_id, updates, user_id=user_id)
    except Exception as exc:
        logger.error("update_task error id=%s: %s", task_id, exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")
    if not updated:
        raise HTTPException(status_code=404, detail=f"Care gap task {task_id} not found")
    return updated


@router.put("/{task_id}/assign", summary="Assign a care gap task to a user")
def assign_task(
    task_id: int,
    body: AssignRequest,
    current_user: dict = Depends(get_current_user),
    _perm: None = Depends(require_permission("care_gaps", "write")),
) -> dict[str, Any]:
    """
    Assign (or re-assign) a care gap task to the user identified by
    ``assigned_to``.  The assignment is recorded in the task history.

    Body::

        {
          "assigned_to": 42,
          "note": "routing to Dr. Smith's coding team"
        }
    """
    _get_or_404(task_id)
    user_id: int = int(current_user.get("id") or current_user.get("user_id") or 0)
    try:
        updated = assign_gap_task(
            task_id, body.assigned_to, user_id=user_id, note=body.note
        )
    except Exception as exc:
        logger.error("assign_task error id=%s: %s", task_id, exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")
    if not updated:
        raise HTTPException(status_code=404, detail=f"Care gap task {task_id} not found")
    return updated


@router.put("/{task_id}/status", summary="Transition a care gap task status")
def update_status(
    task_id: int,
    body: StatusTransitionRequest,
    current_user: dict = Depends(get_current_user),
    _perm: None = Depends(require_permission("care_gaps", "write")),
) -> dict[str, Any]:
    """
    Transition a care gap task to a new lifecycle status.

    Valid transitions::

        open        → in_progress | scheduled | rejected
        in_progress → scheduled | completed | rejected | open
        scheduled   → in_progress | completed | rejected | open
        completed   → (terminal — no further transitions)
        rejected    → open

    Body::

        {
          "status": "completed",
          "note": "condition documented in encounter note 2026-04-01"
        }
    """
    user_id: int = int(current_user.get("id") or current_user.get("user_id") or 0)
    try:
        return transition_status(
            task_id, new_status=body.status, user_id=user_id, note=body.note
        )
    except ValueError as exc:
        logger.warning("update_status validation error id=%s: %s", task_id, exc)
        raise HTTPException(status_code=422, detail=str(exc))
    except Exception as exc:
        logger.error("update_status error id=%s: %s", task_id, exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/{task_id}/comments", summary="Add a comment to a care gap task", status_code=201)
def post_comment(
    task_id: int,
    body: CommentCreate,
    current_user: dict = Depends(get_current_user),
    _perm: None = Depends(require_permission("care_gaps", "write")),
) -> dict[str, Any]:
    """
    Add a comment to a care gap task.  Comments are append-only and preserved
    in the audit trail.

    Body::

        { "comment": "Patient scheduled for follow-up on 2026-05-01." }
    """
    user_id: int = int(current_user.get("id") or current_user.get("user_id") or 0)
    try:
        return add_comment(task_id, user_id=user_id, comment=body.comment)
    except ValueError as exc:
        logger.warning("post_comment not found task=%s: %s", task_id, exc)
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        logger.error("post_comment error task=%s: %s", task_id, exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")
