"""
Clinical-query workflow router.

Surfaces a documentation-query workflow modeled on Apixio HCC-Complete:
when a coder reviews a suspect and the chart documentation is thin, they
can fire a structured question to the PCP without rejecting the suspect.
The query lives in `raf_clinical_queries` and progresses through
``pending → replied → closed`` (or ``cancelled`` if withdrawn).

Endpoints
---------
POST  /api/clinical-queries
    Create a new query against a patient (optionally tied to a suspect).
GET   /api/clinical-queries?patient_id=...&status=...
    List queries for the active tenant, optionally filtered.
PUT   /api/clinical-queries/{id}/reply
    Record a clinician's reply, flip to ``replied``.
PUT   /api/clinical-queries/{id}/close
    Close as resolved (whether replied or not).

All endpoints are tenant-scoped via the JWT. Mutations require the
``patients:write`` permission so a read-only auditor cannot fabricate
queries on a tenant's behalf.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator

from app.auth import get_current_user, require_permission
from app.db import raf_cursor

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/clinical-queries", tags=["clinical-queries"])


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------


class ClinicalQueryCreate(BaseModel):
    patient_id: int = Field(..., ge=1)
    suspect_id: int | None = Field(default=None, ge=1)
    hcc_code: str | None = Field(default=None, max_length=16)
    icd10_code: str | None = Field(default=None, max_length=10)
    query_text: str = Field(..., min_length=10, max_length=4000)

    @field_validator("query_text")
    @classmethod
    def _strip_whitespace(cls, v: str) -> str:
        s = v.strip()
        if len(s) < 10:
            raise ValueError("query_text must contain at least 10 non-whitespace characters")
        return s


class ClinicalQueryReply(BaseModel):
    reply_text: str = Field(..., min_length=5, max_length=4000)


class ClinicalQuery(BaseModel):
    id: int
    tenant_id: str
    patient_id: int
    suspect_id: int | None = None
    hcc_code: str | None = None
    icd10_code: str | None = None
    query_text: str
    status: Literal["pending", "replied", "closed", "cancelled"]
    reply_text: str | None = None
    replied_by_user_id: int | None = None
    replied_at: str | None = None
    closed_at: str | None = None
    asker_user_id: int
    asker_email: str | None = None
    created_at: str
    updated_at: str


class ClinicalQueryListResponse(BaseModel):
    total: int
    items: list[ClinicalQuery]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _row_to_query(row: dict[str, Any]) -> ClinicalQuery:
    """Coerce a MySQL row to the typed ClinicalQuery response model.
    Datetimes are stringified so JSON serialisation is stable across
    runtimes (mysql.connector returns datetime objects on some versions
    and ISO strings on others)."""
    def _ts(v: Any) -> str | None:
        if v is None:
            return None
        if isinstance(v, datetime):
            return v.isoformat(timespec="seconds")
        return str(v)

    return ClinicalQuery(
        id=int(row["id"]),
        tenant_id=str(row["tenant_id"]),
        patient_id=int(row["patient_id"]),
        suspect_id=int(row["suspect_id"]) if row.get("suspect_id") is not None else None,
        hcc_code=row.get("hcc_code"),
        icd10_code=row.get("icd10_code"),
        query_text=row["query_text"],
        status=row["status"],
        reply_text=row.get("reply_text"),
        replied_by_user_id=int(row["replied_by_user_id"]) if row.get("replied_by_user_id") is not None else None,
        replied_at=_ts(row.get("replied_at")),
        closed_at=_ts(row.get("closed_at")),
        asker_user_id=int(row["asker_user_id"]),
        asker_email=row.get("asker_email"),
        created_at=_ts(row["created_at"]) or "",
        updated_at=_ts(row["updated_at"]) or "",
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post(
    "",
    response_model=ClinicalQuery,
    status_code=201,
    summary="Open a new clinical-documentation query",
)
def create_query(
    body: ClinicalQueryCreate,
    current_user: dict = Depends(get_current_user),
    _perm: None = Depends(require_permission("patients", "write")),
) -> ClinicalQuery:
    tenant_id = str(current_user.get("tenant_id") or "")
    if not tenant_id:
        raise HTTPException(status_code=403, detail="No tenant context for this user")
    user_id = current_user.get("id")
    if user_id is None:
        raise HTTPException(status_code=403, detail="User id missing from token")

    with raf_cursor() as cur:
        cur.execute(
            """
            INSERT INTO raf_clinical_queries
                (tenant_id, patient_id, suspect_id, hcc_code, icd10_code,
                 query_text, status, asker_user_id, asker_email)
            VALUES (%s, %s, %s, %s, %s, %s, 'pending', %s, %s)
            """,
            (
                tenant_id,
                body.patient_id,
                body.suspect_id,
                body.hcc_code,
                body.icd10_code,
                body.query_text,
                int(user_id),
                current_user.get("email"),
            ),
        )
        new_id = cur.lastrowid
        cur.execute(
            "SELECT * FROM raf_clinical_queries WHERE id = %s AND tenant_id = %s",
            (new_id, tenant_id),
        )
        row = cur.fetchone()
    if not row:
        # Defensive: the row was just inserted under our cursor; if it
        # vanished the database is mid-failover.
        raise HTTPException(status_code=500, detail="Failed to read back created query")
    return _row_to_query(row)


@router.get(
    "",
    response_model=ClinicalQueryListResponse,
    summary="List clinical queries for the active tenant",
)
def list_queries(
    patient_id: int | None = Query(default=None, ge=1),
    status: Literal["pending", "replied", "closed", "cancelled"] | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    current_user: dict = Depends(get_current_user),
    _perm: None = Depends(require_permission("patients", "read")),
) -> ClinicalQueryListResponse:
    tenant_id = str(current_user.get("tenant_id") or "")
    if not tenant_id:
        raise HTTPException(status_code=403, detail="No tenant context for this user")

    where = ["tenant_id = %s"]
    params: list[Any] = [tenant_id]
    if patient_id is not None:
        where.append("patient_id = %s")
        params.append(patient_id)
    if status is not None:
        where.append("status = %s")
        params.append(status)
    where_sql = " AND ".join(where)

    with raf_cursor() as cur:
        cur.execute(
            f"SELECT COUNT(*) AS c FROM raf_clinical_queries WHERE {where_sql}",
            tuple(params),
        )
        total_row = cur.fetchone() or {"c": 0}
        cur.execute(
            f"""SELECT * FROM raf_clinical_queries
                 WHERE {where_sql}
                 ORDER BY id DESC
                 LIMIT %s OFFSET %s""",
            tuple(params) + (limit, offset),
        )
        rows = cur.fetchall() or []
    return ClinicalQueryListResponse(
        total=int(total_row.get("c") or 0),
        items=[_row_to_query(r) for r in rows],
    )


@router.put(
    "/{query_id}/reply",
    response_model=ClinicalQuery,
    summary="Record a clinician's reply to a clinical query",
)
def reply_query(
    query_id: int,
    body: ClinicalQueryReply,
    current_user: dict = Depends(get_current_user),
    _perm: None = Depends(require_permission("patients", "write")),
) -> ClinicalQuery:
    tenant_id = str(current_user.get("tenant_id") or "")
    if not tenant_id:
        raise HTTPException(status_code=403, detail="No tenant context for this user")

    with raf_cursor() as cur:
        cur.execute(
            """
            UPDATE raf_clinical_queries
               SET reply_text = %s,
                   replied_by_user_id = %s,
                   replied_at = NOW(),
                   status = 'replied'
             WHERE id = %s
               AND tenant_id = %s
               AND status IN ('pending', 'replied')
            """,
            (body.reply_text.strip(), int(current_user.get("id") or 0), query_id, tenant_id),
        )
        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail="Query not found or already closed")
        cur.execute(
            "SELECT * FROM raf_clinical_queries WHERE id = %s AND tenant_id = %s",
            (query_id, tenant_id),
        )
        row = cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Query disappeared after update")
    return _row_to_query(row)


@router.put(
    "/{query_id}/close",
    response_model=ClinicalQuery,
    summary="Close a clinical query (resolved or withdrawn)",
)
def close_query(
    query_id: int,
    cancelled: bool = Query(default=False, description="Pass true to mark as withdrawn rather than resolved"),
    current_user: dict = Depends(get_current_user),
    _perm: None = Depends(require_permission("patients", "write")),
) -> ClinicalQuery:
    tenant_id = str(current_user.get("tenant_id") or "")
    if not tenant_id:
        raise HTTPException(status_code=403, detail="No tenant context for this user")
    final_status = "cancelled" if cancelled else "closed"

    with raf_cursor() as cur:
        cur.execute(
            """
            UPDATE raf_clinical_queries
               SET status = %s,
                   closed_at = NOW()
             WHERE id = %s
               AND tenant_id = %s
            """,
            (final_status, query_id, tenant_id),
        )
        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail="Query not found")
        cur.execute(
            "SELECT * FROM raf_clinical_queries WHERE id = %s AND tenant_id = %s",
            (query_id, tenant_id),
        )
        row = cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Query disappeared after update")
    return _row_to_query(row)
