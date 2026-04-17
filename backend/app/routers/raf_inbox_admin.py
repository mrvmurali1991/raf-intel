"""
RAF Inbox Admin router — observability and control endpoints for the RAF recompute inbox.

Provides visibility into queue depth, failure rates, and manual requeue/dirty-marking
operations for the async RAF score computation pipeline.

Route prefix: /api/admin/raf-inbox
Tags: admin, raf-inbox
"""
# Note: do NOT use 'from __future__ import annotations' here —
# it breaks FastAPI/Pydantic schema generation (ForwardRef errors in /openapi.json).

import logging
from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from app.auth import get_current_user, get_tenant_id, require_permission
from app.services import raf_inbox

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin/raf-inbox", tags=["admin", "raf-inbox"])

# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------


class RequeueRequest(BaseModel):
    tenant_id: str | None = Field(default=None, description="Tenant to requeue; None = all tenants")
    max_rows: int = Field(default=100, ge=1, le=10000, description="Maximum number of failed rows to requeue")


class MarkDirtyRequest(BaseModel):
    pid: int = Field(..., description="Patient ID to mark dirty")
    tenant_id: str = Field(..., description="Tenant that owns the patient")
    reason: str = Field(default="manual", description="Reason tag recorded in the inbox row")


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/status")
async def get_inbox_status(
    tenant_id: str | None = Query(default=None, description="Filter stats to a single tenant (admin cross-tenant view)"),
    current_user: dict = Depends(get_current_user),
    _perm: None = Depends(require_permission("raf_scores", "read")),
) -> dict[str, Any]:
    """
    Return queue depth and age statistics for the RAF recompute inbox.

    Admin users may supply *tenant_id* to inspect a specific tenant.
    Non-admin users have their own tenant silently enforced regardless of the
    query parameter.

    Response shape::

        {
            "pending": int,
            "processing": int,
            "done": int,
            "failed": int,
            "oldest_pending_age_seconds": int | None
        }
    """
    # For non-admin users, ignore the supplied tenant_id and use their own.
    role = (current_user.get("role") or "").lower()
    if role != "admin":
        tenant_id = current_user.get("tenant_id")

    return raf_inbox.get_stats(tenant_id=tenant_id)


@router.post("/requeue")
async def requeue_failed(
    body: RequeueRequest,
    current_user: dict = Depends(get_current_user),
    _perm_read: None = Depends(require_permission("raf_scores", "read")),
    _perm_write: None = Depends(require_permission("raf_scores", "write")),
) -> dict[str, int]:
    """
    Move failed inbox rows back to *pending* so the worker retries them.

    Non-admin users are restricted to their own tenant regardless of the
    *tenant_id* field in the request body.

    Response shape::

        {"requeued": int}
    """
    tenant_id = body.tenant_id
    role = (current_user.get("role") or "").lower()
    if role != "admin":
        tenant_id = current_user.get("tenant_id")

    requeued = raf_inbox.requeue_failed(tenant_id=tenant_id, max_rows=body.max_rows)
    return {"requeued": requeued}


@router.post("/mark-dirty")
async def mark_patient_dirty(
    body: MarkDirtyRequest,
    current_user: dict = Depends(get_current_user),
    _perm_read: None = Depends(require_permission("raf_scores", "read")),
    _perm_write: None = Depends(require_permission("raf_scores", "write")),
) -> dict[str, bool]:
    """
    Insert or update an inbox row for *pid*, forcing the RAF pipeline to
    recompute that patient's score on the next worker poll.

    Response shape::

        {"enqueued": bool}
    """
    enqueued = raf_inbox.mark_dirty(
        pid=body.pid,
        tenant_id=body.tenant_id,
        reason=body.reason,
    )
    return {"enqueued": enqueued}
