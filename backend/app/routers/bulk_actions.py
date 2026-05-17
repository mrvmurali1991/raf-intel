"""
Bulk-actions router — server-side endpoints for the worklist multi-select
chip bar (``frontend/src/app/patients/page.tsx``).

The frontend builds a ``Set<number>`` of patient ids and POSTs the same
list to one of three actions:

    POST /api/bulk-actions/patients/reassign
        Move ownership of one or more patients to a different user.
        Rows are upserted into ``raf_patient_assignments`` (one row per
        (tenant_id, patient_id)).

    POST /api/bulk-actions/patients/recalculate-raf
        Re-run ``calculate_raf_score`` for every patient and report the
        per-patient success / failure counts.

    POST /api/bulk-actions/patients/mark-reviewed
        Emit one ``PATIENT_BULK_REVIEWED`` audit event per patient via the
        immutable audit log.

Security model
--------------
* Tenant: pulled from ``current_user["tenant_id"]`` — **never** accepted in
  the request body.  Honors the ``feedback_field_names`` and tenant-leak
  guidance baked into the rest of the codebase.
* Permissions: every endpoint requires ``patients:write``.
* Payload size: each endpoint accepts at most ``MAX_BULK_IDS`` patient_ids
  per request; the limit is enforced by a pydantic ``field_validator`` so
  an oversize payload returns 422 from FastAPI before the handler runs,
  and an explicit 400 is raised as a backstop.

The ``raf_patient_assignments`` table is created out-of-band:

    docker exec raf-mysql sh -c 'mysql -uroot -proot raf_intelligence -e \
        "CREATE TABLE IF NOT EXISTS raf_patient_assignments (...)"'

It is not managed by an Alembic migration because the rest of this
codebase uses ad-hoc DDL for new feature tables.
"""

from __future__ import annotations

import logging
import time
from collections import defaultdict
from datetime import datetime
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, field_validator

from app.auth import get_current_user, get_tenant_id, require_permission
from app.db import raf_cursor
from app.services.immutable_audit import emit_audit_event
from app.services.raf.calculator import calculate_raf_score

# Per-actor rate limit — 10 bulk ops / minute / user across all 3 endpoints.
# Use the actor id (not source IP) so a shared kiosk does not get throttled
# by another user's burst.
_BULK_RATE_WINDOW_SEC = 60
_BULK_RATE_LIMIT = 10
_bulk_rate_state: dict[int, list[float]] = defaultdict(list)

# Confirmation token gate for batches > 50 ids. Prevents fat-finger bulk
# mutations on the entire worklist while keeping the typical selection
# (≤ 50) friction-free.
_BULK_CONFIRM_THRESHOLD = 50


def _enforce_actor_rate_limit(actor_id: int) -> None:
    now = time.time()
    cutoff = now - _BULK_RATE_WINDOW_SEC
    history = [t for t in _bulk_rate_state[actor_id] if t > cutoff]
    if len(history) >= _BULK_RATE_LIMIT:
        retry_after = max(1, int(_BULK_RATE_WINDOW_SEC - (now - history[0])))
        _bulk_rate_state[actor_id] = history
        raise HTTPException(
            status_code=429,
            detail=f"bulk-actions rate limit ({_BULK_RATE_LIMIT}/min) exceeded",
            headers={"Retry-After": str(retry_after)},
        )
    history.append(now)
    _bulk_rate_state[actor_id] = history


def _filter_owned_patient_ids(
    candidate_ids: list[int], tenant_id: str
) -> tuple[list[int], list[int]]:
    """Return (accepted_ids_owned_by_tenant, rejected_unknown_or_cross_tenant).

    The accepted list preserves caller order. The rejected list contains
    every id NOT in the active tenant's patient table or not active.
    """
    if not candidate_ids:
        return [], []
    placeholders = ",".join(["%s"] * len(candidate_ids))
    sql = (
        f"SELECT id FROM patients "
        f"WHERE id IN ({placeholders}) AND tenant_id = %s "
        f"AND COALESCE(is_active, 1) = 1"
    )
    params = list(candidate_ids) + [tenant_id]
    with raf_cursor() as cur:
        cur.execute(sql, tuple(params))
        owned = {int(r["id"]) for r in cur.fetchall() or []}
    accepted = [pid for pid in candidate_ids if pid in owned]
    rejected = [pid for pid in candidate_ids if pid not in owned]
    return accepted, rejected


def _check_confirm_token(
    patient_ids: list[int], confirm_token: str | None
) -> None:
    if len(patient_ids) <= _BULK_CONFIRM_THRESHOLD:
        return
    expected = f"BULK-{len(patient_ids)}"
    if confirm_token != expected:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Batch of {len(patient_ids)} requires confirm_token={expected!r}"
                " (anti-fat-finger gate for batches > "
                f"{_BULK_CONFIRM_THRESHOLD})"
            ),
        )

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/bulk-actions", tags=["bulk-actions"])

# ---------------------------------------------------------------------------
# Shared constants
# ---------------------------------------------------------------------------

#: Hard cap on the number of patient_ids accepted per request.  Picked to
#: keep a single bulk action under ~5s end-to-end (RAF recalc averages
#: ~20ms per patient) while still covering realistic worklist selections.
MAX_BULK_IDS: int = 200


# ---------------------------------------------------------------------------
# Pydantic models — request
# ---------------------------------------------------------------------------


def _validate_patient_ids(v: list[int]) -> list[int]:
    """Shared validator: non-empty, deduped, <= MAX_BULK_IDS, all positive."""
    if not v:
        raise ValueError("patient_ids must not be empty")
    if len(v) > MAX_BULK_IDS:
        raise ValueError(
            f"patient_ids accepts at most {MAX_BULK_IDS} ids per request; "
            f"got {len(v)}"
        )
    if any((not isinstance(pid, int)) or pid <= 0 for pid in v):
        raise ValueError("patient_ids must all be positive integers")
    # Dedupe while preserving order so the caller's first occurrence wins.
    seen: set[int] = set()
    deduped: list[int] = []
    for pid in v:
        if pid not in seen:
            seen.add(pid)
            deduped.append(pid)
    return deduped


class ReassignIn(BaseModel):
    patient_ids: list[int] = Field(
        ..., description="Patient ids to reassign (max 200)."
    )
    assignee_user_id: int = Field(
        ..., gt=0, description="User id that will own these patients."
    )
    confirm_token: Optional[str] = Field(
        None,
        description=(
            f"Required when patient_ids count > {_BULK_CONFIRM_THRESHOLD}. "
            "Must equal 'BULK-<n>' where n is the count."
        ),
    )

    @field_validator("patient_ids")
    @classmethod
    def _check_patient_ids(cls, v: list[int]) -> list[int]:
        return _validate_patient_ids(v)


class RecalculateRafIn(BaseModel):
    patient_ids: list[int] = Field(
        ..., description="Patient ids to recompute (max 200)."
    )
    confirm_token: Optional[str] = Field(None)

    @field_validator("patient_ids")
    @classmethod
    def _check_patient_ids(cls, v: list[int]) -> list[int]:
        return _validate_patient_ids(v)


class MarkReviewedIn(BaseModel):
    patient_ids: list[int] = Field(
        ..., description="Patient ids to mark reviewed (max 200)."
    )
    note: Optional[str] = Field(
        None,
        max_length=2000,
        description="Optional free-text note attached to every audit event.",
    )
    confirm_token: Optional[str] = Field(None)

    @field_validator("patient_ids")
    @classmethod
    def _check_patient_ids(cls, v: list[int]) -> list[int]:
        return _validate_patient_ids(v)


# ---------------------------------------------------------------------------
# Pydantic models — response
# ---------------------------------------------------------------------------


class BulkError(BaseModel):
    patient_id: int
    error: str


class ReassignOut(BaseModel):
    requested: int = Field(..., ge=0)
    upserted: int = Field(..., ge=0)
    assignee_user_id: int
    failed: int = Field(..., ge=0)
    errors: list[BulkError] = Field(default_factory=list)

    @field_validator("requested", "upserted", "failed")
    @classmethod
    def _non_negative(cls, v: int) -> int:
        if v < 0:
            raise ValueError("count must be non-negative")
        return v


class RecalculateRafOut(BaseModel):
    requested: int = Field(..., ge=0)
    succeeded: int = Field(..., ge=0)
    failed: int = Field(..., ge=0)
    errors: list[BulkError] = Field(default_factory=list)

    @field_validator("requested", "succeeded", "failed")
    @classmethod
    def _non_negative(cls, v: int) -> int:
        if v < 0:
            raise ValueError("count must be non-negative")
        return v


class MarkReviewedOut(BaseModel):
    requested: int = Field(..., ge=0)
    audited: int = Field(..., ge=0)
    failed: int = Field(..., ge=0)
    errors: list[BulkError] = Field(default_factory=list)

    @field_validator("requested", "audited", "failed")
    @classmethod
    def _non_negative(cls, v: int) -> int:
        if v < 0:
            raise ValueError("count must be non-negative")
        return v


# ---------------------------------------------------------------------------
# Shared backstop guard
# ---------------------------------------------------------------------------


def _enforce_bulk_cap(patient_ids: list[int]) -> None:
    """Backstop check — pydantic should already reject oversize payloads.

    Kept so that any future caller that bypasses the model still gets a
    400 instead of leaking through to the database loop.
    """
    if len(patient_ids) > MAX_BULK_IDS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"patient_ids accepts at most {MAX_BULK_IDS} ids per request; "
                f"got {len(patient_ids)}"
            ),
        )


# ---------------------------------------------------------------------------
# 1. Reassign
# ---------------------------------------------------------------------------


@router.post(
    "/patients/reassign",
    response_model=ReassignOut,
    summary="Reassign a batch of patients to a different user",
)
def reassign_patients(
    body: ReassignIn,
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
    _perm: dict = Depends(require_permission("patients", "write")),
) -> ReassignOut:
    """Upsert one ``raf_patient_assignments`` row per patient_id.

    The unique key ``(tenant_id, patient_id)`` means re-assigning a
    patient overwrites the previous owner — there is no history table
    for this MVP; audit history lives in ``audit_log``.
    """
    _enforce_bulk_cap(body.patient_ids)
    _check_confirm_token(body.patient_ids, body.confirm_token)
    actor_id = int(current_user["id"])
    _enforce_actor_rate_limit(actor_id)
    accepted_ids, rejected_ids = _filter_owned_patient_ids(
        body.patient_ids, tenant_id
    )

    now = datetime.utcnow()
    upserted = 0
    errors: list[BulkError] = [
        BulkError(patient_id=pid, error="not-found-or-cross-tenant")
        for pid in rejected_ids
    ]

    with raf_cursor() as cur:
        for pid in accepted_ids:
            try:
                cur.execute(
                    """
                    INSERT INTO raf_patient_assignments
                        (patient_id, tenant_id, assignee_user_id,
                         assigned_by_user_id, assigned_at)
                    VALUES (%s, %s, %s, %s, %s)
                    ON DUPLICATE KEY UPDATE
                        assignee_user_id    = VALUES(assignee_user_id),
                        assigned_by_user_id = VALUES(assigned_by_user_id),
                        assigned_at         = VALUES(assigned_at)
                    """,
                    (pid, tenant_id, body.assignee_user_id, actor_id, now),
                )
                upserted += 1
            except Exception as exc:  # noqa: BLE001 - best-effort per-row
                logger.warning(
                    "bulk reassign failed pid=%s tenant=%s err=%s",
                    pid, tenant_id, exc,
                )
                errors.append(BulkError(patient_id=pid, error=str(exc)))

    # Single rolled-up audit event for the whole batch — individual rows
    # already live in ``raf_patient_assignments``.
    try:
        emit_audit_event(
            "PATIENT_BULK_REASSIGNED",
            tenant_id=tenant_id,
            actor_user_id=actor_id,
            subject_type="patient",
            payload={
                "patient_ids": body.patient_ids,
                "assignee_user_id": body.assignee_user_id,
                "upserted": upserted,
                "failed": len(errors),
            },
        )
    except Exception as exc:  # noqa: BLE001 — audit failures must not 500
        logger.error("audit emit failed for bulk reassign: %s", exc)

    return ReassignOut(
        requested=len(body.patient_ids),
        upserted=upserted,
        assignee_user_id=body.assignee_user_id,
        failed=len(errors),
        errors=errors,
    )


# ---------------------------------------------------------------------------
# 2. Recalculate RAF
# ---------------------------------------------------------------------------


@router.post(
    "/patients/recalculate-raf",
    response_model=RecalculateRafOut,
    summary="Recalculate the RAF score for a batch of patients",
)
def recalculate_raf_bulk(
    body: RecalculateRafIn,
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
    _perm: dict = Depends(require_permission("patients", "write")),
) -> RecalculateRafOut:
    """Loop ``calculate_raf_score`` per patient_id for the current year.

    The CMS payment year is taken from the host clock (``UTC``).  The
    function is invoked with the standard keyword arguments; we never
    pass plan-specific overrides here.  Errors are caught per-patient
    so a single bad pid does not abort the rest of the batch.
    """
    _enforce_bulk_cap(body.patient_ids)
    _check_confirm_token(body.patient_ids, body.confirm_token)
    actor_id = int(current_user["id"])
    _enforce_actor_rate_limit(actor_id)
    accepted_ids, rejected_ids = _filter_owned_patient_ids(
        body.patient_ids, tenant_id
    )

    current_year = datetime.utcnow().year
    succeeded = 0
    errors: list[BulkError] = [
        BulkError(patient_id=pid, error="not-found-or-cross-tenant")
        for pid in rejected_ids
    ]

    for pid in accepted_ids:
        try:
            calculate_raf_score(
                pid,
                measurement_year=current_year,
                tenant_id=tenant_id,
            )
            succeeded += 1
        except Exception as exc:  # noqa: BLE001 - best-effort per-row
            logger.warning(
                "bulk recalc failed pid=%s tenant=%s err=%s",
                pid, tenant_id, exc,
            )
            errors.append(BulkError(patient_id=pid, error=str(exc)[:500]))

    try:
        emit_audit_event(
            "PATIENT_BULK_RAF_RECALCULATED",
            tenant_id=tenant_id,
            actor_user_id=int(current_user["id"]),
            subject_type="patient",
            payload={
                "patient_ids": body.patient_ids,
                "measurement_year": current_year,
                "succeeded": succeeded,
                "failed": len(errors),
            },
        )
    except Exception as exc:  # noqa: BLE001
        logger.error("audit emit failed for bulk recalc: %s", exc)

    return RecalculateRafOut(
        requested=len(body.patient_ids),
        succeeded=succeeded,
        failed=len(errors),
        errors=errors,
    )


# ---------------------------------------------------------------------------
# 3. Mark reviewed
# ---------------------------------------------------------------------------


@router.post(
    "/patients/mark-reviewed",
    response_model=MarkReviewedOut,
    summary="Emit a PATIENT_BULK_REVIEWED audit event per patient",
)
def mark_reviewed_bulk(
    body: MarkReviewedIn,
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
    _perm: dict = Depends(require_permission("patients", "write")),
) -> MarkReviewedOut:
    """Emit one immutable audit event per patient_id.

    The action is ``PATIENT_BULK_REVIEWED``; the optional caller note is
    attached to every event's payload so the audit reader can render it
    consistently for any pid in the batch.
    """
    _enforce_bulk_cap(body.patient_ids)
    _check_confirm_token(body.patient_ids, body.confirm_token)
    actor_id = int(current_user["id"])
    _enforce_actor_rate_limit(actor_id)
    accepted_ids, rejected_ids = _filter_owned_patient_ids(
        body.patient_ids, tenant_id
    )

    audited = 0
    errors: list[BulkError] = [
        BulkError(patient_id=pid, error="not-found-or-cross-tenant")
        for pid in rejected_ids
    ]

    payload_base: dict[str, Any] = {"bulk": True}
    if body.note:
        payload_base["note"] = body.note

    for pid in accepted_ids:
        try:
            emit_audit_event(
                "PATIENT_BULK_REVIEWED",
                tenant_id=tenant_id,
                actor_user_id=actor_id,
                subject_type="patient",
                subject_id=pid,
                payload=payload_base,
            )
            audited += 1
        except Exception as exc:  # noqa: BLE001 - best-effort per-row
            logger.warning(
                "bulk review audit failed pid=%s tenant=%s err=%s",
                pid, tenant_id, exc,
            )
            errors.append(BulkError(patient_id=pid, error=str(exc)[:500]))

    return MarkReviewedOut(
        requested=len(body.patient_ids),
        audited=audited,
        failed=len(errors),
        errors=errors,
    )
