"""
RADV Chart-Request Tracking Router — CMS compliance workflow.
=============================================================

CMS RADV mandates that health plans document every chart pull request,
track turnaround time, and maintain status through the audit lifecycle.

Endpoints (all under /api/radv/{run_id}/chart-requests):
  GET    /           — list all chart requests for an audit run
  POST   /           — create a new chart request
  PATCH  /{req_id}   — update status / received_at / notes

Status lifecycle: requested → received → coded → disputed → cleared

Each status change is written to the immutable SHA-256 audit chain.

Permissions: radv:read for GET, radv:write for POST/PATCH.
"""
# Do NOT add 'from __future__ import annotations' — breaks FastAPI schema gen.

import hashlib
import json
import logging
from datetime import date, datetime, timezone
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.auth import require_permission, get_current_user, get_tenant_id
from app.db import raf_cursor

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/radv", tags=["radv-chart-requests"])

ChartStatusLit = Literal["requested", "received", "coded", "disputed", "cleared"]


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class CreateChartRequestIn(BaseModel):
    patient_id: int = Field(..., gt=0)
    provider_id: Optional[int] = None
    due_date: Optional[date] = None
    notes: Optional[str] = Field(None, max_length=4000)


class PatchChartRequestIn(BaseModel):
    status: Optional[ChartStatusLit] = None
    received_at: Optional[datetime] = None
    notes: Optional[str] = Field(None, max_length=4000)
    due_date: Optional[date] = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _chain_hash(tenant_id: str, run_id: int, req_id: int, new_status: str) -> str:
    """Compute SHA-256 linking this status transition into the audit chain."""
    payload = {
        "tenant_id": tenant_id,
        "audit_run_id": run_id,
        "chart_request_id": req_id,
        "status": new_status,
        "ts": datetime.now(timezone.utc).isoformat(),
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def _emit(event_type: str, *, tenant_id: str, actor_user_id: int,
          subject_id: str, payload: dict) -> None:
    try:
        from app.services.immutable_audit import emit_audit_event
        emit_audit_event(
            event_type,
            tenant_id=tenant_id,
            actor_user_id=actor_user_id,
            subject_type="radv_chart_request",
            subject_id=subject_id,
            payload=payload,
        )
    except Exception as exc:
        logger.warning("chart_requests: audit emit failed (%s): %s", event_type, exc)


def _assert_run_owned(run_id: int, tenant_id: str) -> None:
    with raf_cursor() as cur:
        cur.execute(
            "SELECT id FROM raf_radv_audit_runs WHERE id = %s AND tenant_id = %s",
            (run_id, tenant_id),
        )
        if not cur.fetchone():
            raise HTTPException(status_code=404, detail="Audit run not found")


def _row_to_dict(row: dict) -> dict:
    """Normalise datetime/date fields for JSON serialisation."""
    for k in ("requested_at", "received_at", "updated_at"):
        if isinstance(row.get(k), datetime):
            row[k] = row[k].isoformat()
    if isinstance(row.get("due_date"), date):
        row["due_date"] = row["due_date"].isoformat()
    return row


# ---------------------------------------------------------------------------
# GET — list chart requests for a run
# ---------------------------------------------------------------------------


@router.get(
    "/{run_id}/chart-requests",
    summary="List chart requests for a RADV audit run",
)
def list_chart_requests(
    run_id: int,
    current_user: dict = Depends(require_permission("radv", "read")),
    tenant_id: str = Depends(get_tenant_id),
) -> dict:
    _assert_run_owned(run_id, tenant_id)
    with raf_cursor() as cur:
        cur.execute(
            """
            SELECT rcr.id, rcr.audit_run_id, rcr.patient_id, rcr.requested_at,
                   rcr.status, rcr.provider_id, rcr.due_date, rcr.received_at,
                   rcr.notes, rcr.sha256_hash, rcr.created_by, rcr.updated_at,
                   DATEDIFF(COALESCE(rcr.received_at, NOW()), rcr.requested_at)
                       AS days_outstanding
            FROM   radv_chart_requests rcr
            WHERE  rcr.tenant_id = %s AND rcr.audit_run_id = %s
            ORDER  BY rcr.requested_at DESC
            """,
            (tenant_id, run_id),
        )
        rows = [_row_to_dict(dict(r)) for r in cur.fetchall()]

    # Aggregate summary counts for the caller
    open_statuses = {"requested", "received"}
    now = datetime.now(timezone.utc).date()
    overdue = sum(
        1 for r in rows
        if r["status"] in open_statuses
        and r.get("due_date")
        and date.fromisoformat(r["due_date"]) < now
    )
    return {
        "chart_requests": rows,
        "summary": {
            "total": len(rows),
            "open": sum(1 for r in rows if r["status"] in open_statuses),
            "overdue": overdue,
        },
    }


# ---------------------------------------------------------------------------
# POST — create chart request
# ---------------------------------------------------------------------------


@router.post(
    "/{run_id}/chart-requests",
    status_code=status.HTTP_201_CREATED,
    summary="Create a chart request for a RADV audit run",
)
def create_chart_request(
    run_id: int,
    body: CreateChartRequestIn,
    current_user: dict = Depends(require_permission("radv", "write")),
    tenant_id: str = Depends(get_tenant_id),
) -> dict:
    _assert_run_owned(run_id, tenant_id)
    actor_id = int(current_user["id"])
    initial_hash = _chain_hash(tenant_id, run_id, 0, "requested")

    with raf_cursor() as cur:
        cur.execute(
            """
            INSERT INTO radv_chart_requests
                (tenant_id, audit_run_id, patient_id, status,
                 provider_id, due_date, notes, sha256_hash, created_by)
            VALUES (%s, %s, %s, 'requested', %s, %s, %s, %s, %s)
            """,
            (
                tenant_id, run_id, body.patient_id,
                body.provider_id, body.due_date, body.notes,
                initial_hash, actor_id,
            ),
        )
        req_id = cur.lastrowid
        # Update hash now that we have the real row id
        final_hash = _chain_hash(tenant_id, run_id, req_id, "requested")
        cur.execute(
            "UPDATE radv_chart_requests SET sha256_hash = %s WHERE id = %s",
            (final_hash, req_id),
        )
        cur.execute(
            "SELECT * FROM radv_chart_requests WHERE id = %s",
            (req_id,),
        )
        row = _row_to_dict(dict(cur.fetchone()))

    _emit(
        "RADV_CHART_REQUEST_CREATED",
        tenant_id=tenant_id,
        actor_user_id=actor_id,
        subject_id=f"{run_id}:{req_id}",
        payload={"run_id": run_id, "patient_id": body.patient_id, "status": "requested"},
    )
    return row


# ---------------------------------------------------------------------------
# PATCH — update status / fields
# ---------------------------------------------------------------------------


@router.patch(
    "/{run_id}/chart-requests/{req_id}",
    summary="Update status or fields for a chart request",
)
def patch_chart_request(
    run_id: int,
    req_id: int,
    body: PatchChartRequestIn,
    current_user: dict = Depends(require_permission("radv", "write")),
    tenant_id: str = Depends(get_tenant_id),
) -> dict:
    _assert_run_owned(run_id, tenant_id)
    actor_id = int(current_user["id"])

    with raf_cursor() as cur:
        cur.execute(
            "SELECT * FROM radv_chart_requests WHERE id = %s AND tenant_id = %s AND audit_run_id = %s",
            (req_id, tenant_id, run_id),
        )
        existing = cur.fetchone()
        if not existing:
            raise HTTPException(status_code=404, detail="Chart request not found")

        updates: list[str] = []
        params: list = []
        new_status = body.status or existing["status"]

        if body.status and body.status != existing["status"]:
            updates.append("status = %s")
            params.append(body.status)
        if body.received_at is not None:
            updates.append("received_at = %s")
            params.append(body.received_at)
        if body.notes is not None:
            updates.append("notes = %s")
            params.append(body.notes)
        if body.due_date is not None:
            updates.append("due_date = %s")
            params.append(body.due_date)

        # Always recompute hash to chain the update
        new_hash = _chain_hash(tenant_id, run_id, req_id, new_status)
        updates.append("sha256_hash = %s")
        params.append(new_hash)

        if updates:
            params.append(req_id)
            cur.execute(
                f"UPDATE radv_chart_requests SET {', '.join(updates)} WHERE id = %s",
                params,
            )

        cur.execute("SELECT * FROM radv_chart_requests WHERE id = %s", (req_id,))
        row = _row_to_dict(dict(cur.fetchone()))

    if body.status and body.status != existing["status"]:
        _emit(
            "RADV_CHART_REQUEST_STATUS_CHANGED",
            tenant_id=tenant_id,
            actor_user_id=actor_id,
            subject_id=f"{run_id}:{req_id}",
            payload={
                "run_id": run_id,
                "req_id": req_id,
                "from_status": existing["status"],
                "to_status": body.status,
                "sha256_hash": new_hash,
            },
        )
    return row
