# Note: do NOT use 'from __future__ import annotations' here —
# it breaks FastAPI/Pydantic schema generation (ForwardRef errors in /openapi.json).

"""
Reveleer admin endpoints — manual pull/push triggers and sync status.

Route prefix: /api/admin/reveleer
Tags: reveleer-admin
"""

import logging
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Path, Query, status
from pydantic import BaseModel

from app.auth import get_current_user, get_tenant_id, require_role
from app.db import raf_cursor

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/admin/reveleer",
    tags=["reveleer-admin"],
    dependencies=[Depends(get_current_user)],
)


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------


class PullSummary(BaseModel):
    charts_found: int
    charts_skipped: int
    charts_processed: int
    suspects_extracted: int


class PushResult(BaseModel):
    suspects_found: int
    pushed: int
    failed: int
    skipped: int


class SyncStatus(BaseModel):
    last_pull_at: Optional[str]
    last_push_at: Optional[str]
    total_charts_pulled: int
    total_suspects_pushed: int
    pending_suspects: int


# ---------------------------------------------------------------------------
# POST /api/admin/reveleer/pull-now
# ---------------------------------------------------------------------------


@router.post(
    "/pull-now",
    response_model=PullSummary,
    summary="Trigger immediate Reveleer chart pull",
)
def pull_now(
    tenant_id: str = Depends(get_tenant_id),
    since: Optional[str] = Query(None, description="ISO-8601 lower bound for chart timestamps"),
    _user=Depends(require_role("admin")),
) -> Any:
    """Pull ready charts from Reveleer immediately (synchronous, admin only).

    Returns a summary of charts found, processed and suspects extracted.
    """
    try:
        from app.services.partners.reveleer_sync import pull_charts_from_reveleer

        return pull_charts_from_reveleer(tenant_id=tenant_id, since=since)
    except Exception as exc:
        logger.error("pull_now failed tenant=%s: %s", tenant_id, exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Internal server error",
        )


# ---------------------------------------------------------------------------
# POST /api/admin/reveleer/push-patient/{raf_patient_id}
# ---------------------------------------------------------------------------


@router.post(
    "/push-patient/{raf_patient_id}",
    response_model=PushResult,
    summary="Push HCC suspects to Reveleer for one patient",
)
def push_patient(
    raf_patient_id: int = Path(..., description="RAF patients.id"),
    tenant_id: str = Depends(get_tenant_id),
    _user=Depends(require_role("admin")),
) -> Any:
    """Push all open gemini_vision suspects for a patient to Reveleer immediately."""
    try:
        from app.services.partners.reveleer_sync import push_suspects_to_reveleer

        return push_suspects_to_reveleer(
            tenant_id=tenant_id, raf_patient_id=raf_patient_id
        )
    except Exception as exc:
        logger.error(
            "push_patient failed tenant=%s patient=%s: %s", tenant_id, raf_patient_id, exc
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Internal server error",
        )


# ---------------------------------------------------------------------------
# GET /api/admin/reveleer/sync-status
# ---------------------------------------------------------------------------


@router.get(
    "/sync-status",
    response_model=SyncStatus,
    summary="Reveleer sync status — last timestamps and counts",
)
def sync_status(
    tenant_id: str = Depends(get_tenant_id),
    _user=Depends(require_role("admin")),
) -> Any:
    """Return last pull/push timestamps and aggregate counts for a tenant."""
    try:
        with raf_cursor() as cur:
            cur.execute(
                """SELECT
                     MAX(pulled_at)        AS last_pull_at,
                     COUNT(*)              AS total_charts
                   FROM reveleer_charts_pulled
                   WHERE tenant_id=%s""",
                (tenant_id,),
            )
            pull_row = cur.fetchone()

            cur.execute(
                """SELECT
                     MAX(pushed_at)        AS last_push_at,
                     SUM(status='success') AS total_pushed
                   FROM reveleer_suspects_pushed
                   WHERE tenant_id=%s""",
                (tenant_id,),
            )
            push_row = cur.fetchone()

            cur.execute(
                """SELECT COUNT(*) AS pending
                   FROM reveleer_suspects_pushed
                   WHERE tenant_id=%s AND status='pending'""",
                (tenant_id,),
            )
            pending_row = cur.fetchone()

        def _val(row, key):
            if row is None:
                return None
            return row[key] if isinstance(row, dict) else None

        def _int(row, key, default=0):
            v = _val(row, key)
            return int(v) if v is not None else default

        last_pull_at = _val(pull_row, "last_pull_at")
        last_push_at = _val(push_row, "last_push_at")

        return SyncStatus(
            last_pull_at=last_pull_at.isoformat() if hasattr(last_pull_at, "isoformat") else (str(last_pull_at) if last_pull_at else None),
            last_push_at=last_push_at.isoformat() if hasattr(last_push_at, "isoformat") else (str(last_push_at) if last_push_at else None),
            total_charts_pulled=_int(pull_row, "total_charts"),
            total_suspects_pushed=_int(push_row, "total_pushed"),
            pending_suspects=_int(pending_row, "pending"),
        )
    except Exception as exc:
        logger.error("sync_status failed tenant=%s: %s", tenant_id, exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error",
        )
