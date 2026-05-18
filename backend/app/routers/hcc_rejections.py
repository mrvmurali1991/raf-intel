"""
HCC Rejections router — DOJ-compliant two-way HCC review.

Reveleer 2026: "add-only = DOJ red flag."  Coders must be able to reject
prior-year HCC gaps after retrospective chart review.  Every rejection is
SHA-256-chained into the immutable audit log so the audit trail is tamper-
evident and RADV-defensible.

Endpoints
---------
POST /api/v1/hcc-rejections
    Create a rejection record.  Reason code is REQUIRED.  Writes to both
    the raf_hcc_rejections table and the immutable_audit_log chain.

GET  /api/v1/hcc-rejections
    List rejections for the authenticated tenant (paginated).

Business rules
--------------
* A rejected gap is excluded from the recapture queue for the payment year.
* Re-accepting a rejected gap requires a second POST (rejection-of-rejection)
  — the original record is never mutated; the audit trail is append-only.
"""
from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field, field_validator

from app.auth import get_current_user, get_tenant_id
from app.db import raf_cursor
from app.services.immutable_audit import emit_audit_event

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/hcc-rejections",
    tags=["hcc-rejections"],
    dependencies=[Depends(get_current_user)],
)

# ---------------------------------------------------------------------------
# Reason code constants (mirror the DB ENUM)
# ---------------------------------------------------------------------------

REASON_CODES = {
    "not_supported_in_chart",
    "incorrect_specificity",
    "resolved_condition",
    "documentation_insufficient",
    "coder_error",
    "provider_dispute",
}

REASON_LABELS: dict[str, str] = {
    "not_supported_in_chart":      "Not supported in chart",
    "incorrect_specificity":       "Incorrect specificity",
    "resolved_condition":          "Resolved / inactive condition",
    "documentation_insufficient":  "Documentation insufficient",
    "coder_error":                 "Coder error",
    "provider_dispute":            "Provider dispute",
}


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------

class CreateRejectionIn(BaseModel):
    patient_id: int = Field(..., ge=1)
    hcc_code: str = Field(..., min_length=1, max_length=16)
    payment_year: int = Field(..., ge=2000, le=2100)
    reason_code: str = Field(
        ...,
        description=f"Required. One of: {', '.join(sorted(REASON_CODES))}",
    )
    reason_text: Optional[str] = Field(
        default=None,
        max_length=500,
        description="Optional free-form context (max 500 chars)",
    )
    prior_year_documented: bool = Field(
        default=False,
        description="Was the condition documented in the prior year?",
    )

    @field_validator("reason_code")
    @classmethod
    def _validate_reason_code(cls, v: str) -> str:
        if v not in REASON_CODES:
            raise ValueError(
                f"reason_code must be one of: {', '.join(sorted(REASON_CODES))}"
            )
        return v


# ---------------------------------------------------------------------------
# SHA-256 chain helper
# ---------------------------------------------------------------------------

def _compute_rejection_hash(
    tenant_id: str,
    patient_id: int,
    hcc_code: str,
    payment_year: int,
    reason_code: str,
    rejected_at_iso: str,
    prev_hash: str,
) -> str:
    payload = "|".join([
        prev_hash,
        tenant_id,
        str(patient_id),
        hcc_code,
        str(payment_year),
        reason_code,
        rejected_at_iso,
    ])
    return hashlib.sha256(payload.encode()).hexdigest()


def _get_prev_hash(tenant_id: str) -> str:
    """Return the sha256_hash of the most recent rejection for this tenant,
    or the genesis hash if none exists yet."""
    genesis = "0" * 64
    with raf_cursor() as cur:
        cur.execute(
            "SELECT sha256_hash FROM raf_hcc_rejections "
            "WHERE tenant_id = %s ORDER BY id DESC LIMIT 1",
            (tenant_id,),
        )
        row = cur.fetchone()
    return (row["sha256_hash"] if row else genesis)


# ---------------------------------------------------------------------------
# POST /api/hcc-rejections
# ---------------------------------------------------------------------------

@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    summary="Reject an HCC gap (DOJ-compliant, immutable audit chain)",
)
def create_rejection(
    body: CreateRejectionIn,
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
) -> dict[str, Any]:
    actor_id = int(current_user["id"])
    now_iso = datetime.now(timezone.utc).isoformat()

    prev_hash = _get_prev_hash(tenant_id)
    sha256 = _compute_rejection_hash(
        tenant_id=tenant_id,
        patient_id=body.patient_id,
        hcc_code=body.hcc_code,
        payment_year=body.payment_year,
        reason_code=body.reason_code,
        rejected_at_iso=now_iso,
        prev_hash=prev_hash,
    )

    try:
        with raf_cursor() as cur:
            cur.execute(
                """
                INSERT INTO raf_hcc_rejections
                    (tenant_id, patient_id, hcc_code, payment_year,
                     rejected_by, rejected_at, reason_code, reason_text,
                     prior_year_documented, sha256_hash)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    tenant_id,
                    body.patient_id,
                    body.hcc_code,
                    body.payment_year,
                    actor_id,
                    now_iso,
                    body.reason_code,
                    body.reason_text,
                    int(body.prior_year_documented),
                    sha256,
                ),
            )
            rejection_id = cur.lastrowid
    except Exception as exc:
        logger.exception("hcc_rejection insert failed: %s", exc)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to record rejection: {exc}",
        )

    # Write to immutable audit chain
    try:
        emit_audit_event(
            "hcc_gap_rejected",
            tenant_id=tenant_id,
            actor_user_id=actor_id,
            subject_type="hcc_gap",
            subject_id=f"{body.patient_id}:{body.hcc_code}:{body.payment_year}",
            payload={
                "rejection_id": rejection_id,
                "reason_code": body.reason_code,
                "reason_text": body.reason_text,
                "prior_year_documented": body.prior_year_documented,
                "sha256_hash": sha256,
                "prev_hash": prev_hash,
            },
        )
    except Exception:
        # Audit write failure is logged but does not roll back the rejection
        logger.exception("immutable_audit write failed for rejection_id=%s", rejection_id)

    return {
        "id": rejection_id,
        "tenant_id": tenant_id,
        "patient_id": body.patient_id,
        "hcc_code": body.hcc_code,
        "payment_year": body.payment_year,
        "reason_code": body.reason_code,
        "reason_text": body.reason_text,
        "prior_year_documented": body.prior_year_documented,
        "rejected_by": actor_id,
        "rejected_at": now_iso,
        "sha256_hash": sha256,
    }


# ---------------------------------------------------------------------------
# GET /api/hcc-rejections
# ---------------------------------------------------------------------------

@router.get(
    "",
    summary="List HCC rejections for the tenant (paginated)",
)
def list_rejections(
    patient_id: Optional[int] = Query(default=None, ge=1),
    hcc_code: Optional[str] = Query(default=None),
    payment_year: Optional[int] = Query(default=None, ge=2000, le=2100),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    tenant_id: str = Depends(get_tenant_id),
) -> dict[str, Any]:
    offset = (page - 1) * page_size
    clauses: list[str] = ["tenant_id = %s"]
    params: list[Any] = [tenant_id]

    if patient_id is not None:
        clauses.append("patient_id = %s")
        params.append(patient_id)
    if hcc_code is not None:
        clauses.append("hcc_code = %s")
        params.append(hcc_code)
    if payment_year is not None:
        clauses.append("payment_year = %s")
        params.append(payment_year)

    where = " AND ".join(clauses)

    with raf_cursor() as cur:
        cur.execute(
            f"SELECT COUNT(*) AS total FROM raf_hcc_rejections WHERE {where}",
            params,
        )
        total = (cur.fetchone() or {}).get("total", 0)

        cur.execute(
            f"""
            SELECT id, patient_id, hcc_code, payment_year,
                   rejected_by, rejected_at, reason_code, reason_text,
                   prior_year_documented, sha256_hash
            FROM   raf_hcc_rejections
            WHERE  {where}
            ORDER  BY id DESC
            LIMIT  %s OFFSET %s
            """,
            [*params, page_size, offset],
        )
        rows = [dict(r) for r in cur.fetchall()]

    # Annotate with human-readable label
    for r in rows:
        r["reason_label"] = REASON_LABELS.get(r.get("reason_code", ""), r.get("reason_code", ""))
        if isinstance(r.get("rejected_at"), datetime):
            r["rejected_at"] = r["rejected_at"].isoformat()

    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": rows,
    }


# ---------------------------------------------------------------------------
# GET /api/hcc-rejections/reason-codes  (lookup for UI dropdowns)
# ---------------------------------------------------------------------------

@router.get(
    "/reason-codes",
    summary="Return the valid rejection reason codes and their labels",
)
def get_reason_codes() -> list[dict[str, str]]:
    return [
        {"code": code, "label": label}
        for code, label in REASON_LABELS.items()
    ]
