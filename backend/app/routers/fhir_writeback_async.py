"""Endpoints for the async FHIR writeback lifecycle."""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from app.auth import get_current_user, get_tenant_id, require_permission
from app.services import fhir_writeback_async as svc

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api",
    tags=["fhir-async"],
    dependencies=[Depends(get_current_user)],
)


@router.get(
    "/suspects/{suspect_id}/writeback-status",
    summary="Async FHIR write-back status for a suspect",
)
def writeback_status(
    suspect_id: int,
    tenant_id: str = Depends(get_tenant_id),
    _perm: None = Depends(require_permission("suspects", "read")),
):
    row = svc.get_writeback_status(tenant_id, suspect_id)
    if not row:
        raise HTTPException(status_code=404, detail="suspect not found")
    return row


@router.post(
    "/admin/fhir/replay-failed-writes",
    summary="Re-enqueue every suspect with fhir_writeback_status='failed'",
)
def replay_failed(
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
):
    role = (current_user.get("role") or "").lower()
    if role not in {"admin", "manager"}:
        raise HTTPException(status_code=403, detail="Admin/manager only")

    failed = svc.list_failed_writebacks(tenant_id, limit=1000)
    replayed = 0
    skipped = 0
    # Lazy-import the celery task so importing this router doesn't pull celery
    try:
        from app.services.celery_tasks import task_fhir_writeback_async
    except Exception:
        logger.debug("swallowed exception", exc_info=True)
        task_fhir_writeback_async = None  # type: ignore

    user_id = int(current_user.get("id") or current_user.get("user_id") or 0)
    for r in failed:
        svc.mark_writeback_pending(tenant_id=tenant_id, suspect_id=int(r["id"]))
        if task_fhir_writeback_async is not None:
            try:
                task_fhir_writeback_async.delay(
                    suspect_id=int(r["id"]),
                    tenant_id=str(tenant_id),
                    meat_signed=False,
                    user_role=role,
                    user_id=user_id,
                )
                replayed += 1
            except Exception:
                logger.debug("swallowed exception", exc_info=True)
                skipped += 1
        else:
            skipped += 1
    return {"replayed_count": replayed, "skipped_count": skipped,
            "failed_total": len(failed)}
