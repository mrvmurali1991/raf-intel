"""EHR Problem List write-back queue endpoints.

POST /api/ehr/problem-list-write-back/{patient_id}
    Enqueues an intent to write a Condition resource to the patient EHR
    Problem List.  Returns 202 Accepted — the actual FHIR POST happens
    asynchronously once a SMART-on-FHIR worker processes the queue.

GET  /api/ehr/problem-list-write-back
    Admin view of the full queue (status, timestamps).
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.auth import get_current_user, get_tenant_id, require_permission
from app.db import raf_cursor

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/ehr",
    tags=["ehr-writeback"],
    dependencies=[Depends(get_current_user)],
)


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class WriteBackRequest(BaseModel):
    icd10: str
    hcc_code: Optional[str] = None
    evidence_text: Optional[str] = None
    attested_by: Optional[str] = None
    attested_at: Optional[datetime] = None


class WriteBackQueueItem(BaseModel):
    id: int
    tenant_id: str
    patient_id: int
    icd10: str
    hcc_code: Optional[str]
    evidence_text: Optional[str]
    attested_by: Optional[str]
    attested_at: Optional[datetime]
    status: str
    last_attempt_at: Optional[datetime]
    error_detail: Optional[str]
    created_at: datetime


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post(
    "/problem-list-write-back/{patient_id}",
    status_code=202,
    summary="Queue a Problem List write-back for a patient",
    response_description="Accepted — entry queued for async FHIR Condition POST",
)
def enqueue_writeback(
    patient_id: int,
    body: WriteBackRequest,
    tenant_id: str = Depends(get_tenant_id),
    current_user: dict = Depends(get_current_user),
    _perm: None = Depends(require_permission("suspects", "write")),
):
    """Persist write-back intent to ``ehr_writeback_queue`` and return 202."""
    attested_by = body.attested_by or current_user.get("email") or current_user.get("sub")
    attested_at = body.attested_at or datetime.now(timezone.utc)

    sql = """
        INSERT INTO ehr_writeback_queue
            (tenant_id, patient_id, icd10, hcc_code, evidence_text,
             attested_by, attested_at, status)
        VALUES
            (%s, %s, %s, %s, %s, %s, %s, 'queued')
    """
    params = (
        tenant_id,
        patient_id,
        body.icd10,
        body.hcc_code,
        body.evidence_text,
        attested_by,
        attested_at,
    )
    try:
        with raf_cursor() as cur:
            cur.execute(sql, params)
            queue_id = cur.lastrowid
    except Exception as exc:
        logger.exception("ehr_writeback_queue insert failed: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to queue write-back") from exc

    logger.info(
        "ehr_writeback queued id=%s patient=%s icd10=%s tenant=%s",
        queue_id,
        patient_id,
        body.icd10,
        tenant_id,
    )
    return {
        "status": "queued",
        "queue_id": queue_id,
        "message": "Problem List write-back queued for async EHR delivery.",
    }


@router.get(
    "/problem-list-write-back",
    summary="List EHR write-back queue (admin)",
    response_model=List[WriteBackQueueItem],
)
def list_writeback_queue(
    status: Optional[str] = None,
    limit: int = 100,
    tenant_id: str = Depends(get_tenant_id),
    current_user: dict = Depends(get_current_user),
    _perm: None = Depends(require_permission("fhir", "write")),
):
    where = "WHERE tenant_id = %s"
    args: list = [tenant_id]
    if status:
        where += " AND status = %s"
        args.append(status)
    args.append(int(limit))

    sql = f"""
        SELECT id, tenant_id, patient_id, icd10, hcc_code, evidence_text,
               attested_by, attested_at, status, last_attempt_at,
               error_detail, created_at
        FROM   ehr_writeback_queue
        {where}
        ORDER BY created_at DESC
        LIMIT %s
    """
    try:
        with raf_cursor() as cur:
            cur.execute(sql, tuple(args))
            rows = cur.fetchall() or []
    except Exception as exc:
        logger.exception("ehr_writeback_queue list failed: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to load queue") from exc

    return rows
