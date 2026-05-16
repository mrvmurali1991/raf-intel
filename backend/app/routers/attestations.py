"""
Provider Attestation Router.

Endpoints for the full provider sign-off workflow on suspect HCC conditions.

All write endpoints require the authenticated user to have the
"attestations" resource write permission.  Read endpoints require read.

Endpoint summary
----------------
GET  /api/attestations                   — list (filtered by provider, status)
POST /api/attestations                   — create a single attestation request
GET  /api/attestations/dashboard         — KPI stats
POST /api/attestations/remind            — trigger pending-attestation reminders
POST /api/attestations/batch             — create a batch signing session
PUT  /api/attestations/batch/{id}/submit — submit all decisions in a batch
GET  /api/attestations/{id}              — single attestation detail
PUT  /api/attestations/{id}/attest       — provider attests (confirm active/resolved)
PUT  /api/attestations/{id}/reject       — provider rejects as inaccurate
PUT  /api/attestations/{id}/defer        — provider defers (needs more info)
"""
# Note: do NOT use 'from __future__ import annotations' here —
# it breaks FastAPI/Pydantic schema generation (ForwardRef errors).

import logging
from datetime import date
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field

from app.auth import get_current_user, get_tenant_id, require_permission
from app.middleware.idempotency import idempotency_key_dependency, store_idempotent_response
from app.services import attestation_service as svc

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/attestations", tags=["attestations"])


# ---------------------------------------------------------------------------
# Pydantic request models
# ---------------------------------------------------------------------------

class CreateAttestationRequest(BaseModel):
    patient_id: int = Field(..., description="OpenEMR patient ID (pid)")
    provider_npi: str = Field(..., min_length=10, max_length=10, description="10-digit NPI")
    hcc_code: str = Field(..., description="HCC code, e.g. HCC18")
    hcc_description: str = Field(default="", description="Human-readable HCC description")
    icd10_code: str = Field(..., description="ICD-10-CM code supporting this HCC")
    icd10_description: str = Field(default="", description="ICD-10-CM short description")
    source: Literal["suspect", "nlp", "claims", "manual"] = Field(
        default="suspect",
        description="Origin of this condition",
    )
    encounter_id: int | None = Field(default=None, description="OpenEMR encounter ID if known")
    evidence_references: list[dict[str, Any]] | None = Field(
        default=None,
        description="Array of document/note references",
    )


class AttestRequest(BaseModel):
    attestation_type: Literal["confirm_active", "confirm_resolved"] = Field(
        ...,
        description="Whether the condition is currently active or was resolved",
    )
    clinical_justification: str | None = Field(
        default=None,
        description="Provider narrative supporting the attestation",
    )
    evidence_references: list[dict[str, Any]] | None = Field(
        default=None,
        description="Additional supporting document/note references",
    )


class RejectRequest(BaseModel):
    reject_reason: str = Field(
        ...,
        min_length=1,
        description="Structured reason the condition is being rejected",
    )
    clinical_justification: str | None = Field(
        default=None,
        description="Optional additional provider narrative",
    )


class DeferRequest(BaseModel):
    deferred_until: date | None = Field(
        default=None,
        description="Date for follow-up review (defaults to 30 days from today)",
    )
    clinical_justification: str | None = Field(
        default=None,
        description="Reason additional information is needed",
    )


class CreateBatchRequest(BaseModel):
    provider_npi: str = Field(..., min_length=10, max_length=10, description="10-digit NPI")
    attestation_ids: list[int] = Field(
        ...,
        min_length=1,
        description="List of pending attestation IDs to include in this batch",
    )


class BatchDecision(BaseModel):
    attestation_id: int
    action: Literal["attest", "reject", "defer"]
    attestation_type: Literal["confirm_active", "confirm_resolved"] | None = None
    reject_reason: str | None = None
    deferred_until: date | None = None
    clinical_justification: str | None = None


class SubmitBatchRequest(BaseModel):
    decisions: list[BatchDecision] = Field(
        ...,
        min_length=1,
        description="One decision entry per attestation in the batch",
    )


class RemindRequest(BaseModel):
    reminder_type: Literal["email", "in_app"] = Field(
        default="in_app",
        description="Notification channel to use",
    )
    overdue_days: int = Field(
        default=7,
        ge=1,
        le=90,
        description="Remind on attestations pending for at least this many days",
    )


# ---------------------------------------------------------------------------
# Helper — extract client metadata from request
# ---------------------------------------------------------------------------

def _client_meta(request: Request) -> tuple[str | None, str | None]:
    """Return (ip_address, user_agent) from the incoming request."""
    forwarded = request.headers.get("X-Forwarded-For")
    ip = (
        forwarded.split(",")[0].strip()
        if forwarded
        else (request.client.host if request.client else None)
    )
    ua = request.headers.get("User-Agent")
    return ip, ua


# ---------------------------------------------------------------------------
# GET /api/attestations — list
# ---------------------------------------------------------------------------

@router.get("", summary="List attestations")
def list_attestations(
    provider_npi: str | None = Query(default=None, description="Filter by provider NPI"),
    patient_id: int | None = Query(default=None, description="Filter by patient ID"),
    status: str = Query(
        default="all",
        description="Filter by status: pending | attested | rejected | deferred | all",
    ),
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
    _perm: None = Depends(require_permission("attestations", "read")),
) -> dict[str, Any]:
    """
    Return attestations visible to the authenticated provider.

    Non-admin users automatically have results scoped to their own
    provider_user_id.  Admins may supply a provider_npi to view any
    provider's queue.
    """
    user_role: str = current_user.get("role", "")
    provider_user_id: int | None = None

    if user_role not in ("admin", "superadmin"):
        provider_user_id = current_user["id"]

    try:
        rows = svc.list_attestations(
            provider_user_id=provider_user_id,
            provider_npi=provider_npi,
            patient_id=patient_id,
            status=status if status != "all" else None,
            tenant_id=tenant_id,
            limit=limit,
            offset=offset,
        )
    except Exception as exc:
        logger.exception("list_attestations failed: %s", exc)
        raise HTTPException(status_code=500, detail="Internal server error")

    return {"count": len(rows), "offset": offset, "attestations": rows}


# ---------------------------------------------------------------------------
# POST /api/attestations — create  (must be before /{id} routes)
# ---------------------------------------------------------------------------

@router.post("", summary="Create an attestation request", status_code=201)
def create_attestation(
    request: Request,
    response: Response,
    body: CreateAttestationRequest,
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
    _perm: None = Depends(require_permission("attestations", "write")),
    _idem: None = Depends(idempotency_key_dependency()),
) -> dict[str, Any]:
    """
    Create a single pending attestation request for a provider to review.

    The ``provider_user_id`` is always taken from the authenticated session,
    not from the request body, to prevent impersonation.

    Supports Idempotency-Key header (24h replay window).
    """
    provider_user_id: int = current_user["id"]

    try:
        rec = svc.create_attestation(
            patient_id=body.patient_id,
            provider_npi=body.provider_npi,
            provider_user_id=provider_user_id,
            hcc_code=body.hcc_code,
            hcc_description=body.hcc_description,
            icd10_code=body.icd10_code,
            icd10_description=body.icd10_description,
            source=body.source,
            encounter_id=body.encounter_id,
            evidence_references=body.evidence_references,
            tenant_id=tenant_id,
        )
    except Exception as exc:
        logger.exception("create_attestation failed: %s", exc)
        raise HTTPException(status_code=500, detail="Internal server error")

    store_idempotent_response(request, response, rec)
    return rec


# ---------------------------------------------------------------------------
# GET /api/attestations/dashboard — stats (fixed path before /{id})
# ---------------------------------------------------------------------------

@router.get("/dashboard", summary="Attestation dashboard statistics")
def attestation_dashboard(
    days: int = Query(default=30, ge=1, le=365, description="Look-back window in days"),
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
    _perm: None = Depends(require_permission("attestations", "read")),
) -> dict[str, Any]:
    """
    Return attestation KPIs for the requesting provider (or all providers
    for admin users) over the specified look-back window.
    """
    user_role: str = current_user.get("role", "")
    provider_user_id: int | None = (
        None if user_role in ("admin", "superadmin") else current_user["id"]
    )

    try:
        stats = svc.get_dashboard_stats(
            provider_user_id=provider_user_id,
            tenant_id=tenant_id,
            days=days,
        )
    except Exception as exc:
        logger.exception("attestation_dashboard failed: %s", exc)
        raise HTTPException(status_code=500, detail="Internal server error")

    return stats


# ---------------------------------------------------------------------------
# POST /api/attestations/remind — send reminders (fixed path before /{id})
# ---------------------------------------------------------------------------

@router.post("/remind", summary="Send pending attestation reminders")
def send_reminders(
    body: RemindRequest,
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
    _perm: None = Depends(require_permission("attestations", "write")),
) -> dict[str, Any]:
    """
    Generate reminder records for attestations that have been pending longer
    than ``overdue_days``.

    Attestations that already received a reminder of the same type within
    the last 24 hours are skipped automatically.
    """

    try:
        reminders = svc.generate_reminders(
            reminder_type=body.reminder_type,
            overdue_days=body.overdue_days,
            tenant_id=tenant_id,
        )
    except Exception as exc:
        logger.exception("send_reminders failed: %s", exc)
        raise HTTPException(status_code=500, detail="Internal server error")

    return {
        "reminders_created": len(reminders),
        "reminder_type": body.reminder_type,
        "overdue_days": body.overdue_days,
        "reminders": reminders,
    }


# ---------------------------------------------------------------------------
# POST /api/attestations/batch — create batch (fixed path before /{id})
# ---------------------------------------------------------------------------

@router.post("/batch", summary="Create a batch attestation session", status_code=201)
def create_batch(
    body: CreateBatchRequest,
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
    _perm: None = Depends(require_permission("attestations", "write")),
) -> dict[str, Any]:
    """
    Group multiple pending attestations into a batch signing session.

    The provider reviews all conditions and then submits all decisions at
    once via ``PUT /api/attestations/batch/{id}/submit``.
    """
    provider_user_id: int = current_user["id"]

    try:
        batch = svc.create_batch(
            provider_npi=body.provider_npi,
            provider_user_id=provider_user_id,
            attestation_ids=body.attestation_ids,
            tenant_id=tenant_id,
        )
    except ValueError as exc:
        logger.warning("create_batch validation error: %s", exc)
        raise HTTPException(status_code=422, detail=str(exc))
    except Exception as exc:
        logger.exception("create_batch failed: %s", exc)
        raise HTTPException(status_code=500, detail="Internal server error")

    return batch


# ---------------------------------------------------------------------------
# PUT /api/attestations/batch/{batch_id}/submit
# ---------------------------------------------------------------------------

@router.put("/batch/{batch_id}/submit", summary="Submit all decisions in a batch")
def submit_batch(
    batch_id: int,
    body: SubmitBatchRequest,
    request: Request,
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
    _perm: None = Depends(require_permission("attestations", "write")),
) -> dict[str, Any]:
    """
    Process all decisions supplied in the request body and mark the batch
    as completed.

    Each ``decisions`` entry must specify one of:
    - ``action: "attest"``  + ``attestation_type``
    - ``action: "reject"``  + ``reject_reason``
    - ``action: "defer"``   + optional ``deferred_until`` (ISO date)
    """
    provider_user_id: int = current_user["id"]
    ip, ua = _client_meta(request)

    decisions_dicts = [d.model_dump() for d in body.decisions]

    try:
        result = svc.submit_batch(
            batch_id,
            provider_user_id=provider_user_id,
            decisions=decisions_dicts,
            ip_address=ip,
            user_agent=ua,
        )
    except ValueError as exc:
        logger.warning("submit_batch validation error batch_id=%s: %s", batch_id, exc)
        raise HTTPException(status_code=422, detail=str(exc))
    except Exception as exc:
        logger.exception("submit_batch batch_id=%s failed: %s", batch_id, exc)
        raise HTTPException(status_code=500, detail="Internal server error")

    return result


# ---------------------------------------------------------------------------
# GET /api/attestations/{attestation_id} — detail
# ---------------------------------------------------------------------------

@router.get("/{attestation_id}", summary="Get attestation detail")
def get_attestation(
    attestation_id: int,
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
    _perm: None = Depends(require_permission("attestations", "read")),
) -> dict[str, Any]:
    """Return the full detail for a single attestation."""
    try:
        rec = svc.get_attestation(attestation_id)
    except ValueError as exc:
        logger.exception("Unexpected error: %s", exc)
        raise HTTPException(status_code=404, detail="Resource not found")
    except Exception as exc:
        logger.exception("get_attestation id=%s failed: %s", attestation_id, exc)
        raise HTTPException(status_code=500, detail="Internal server error")

    # Non-admin users may only view their own attestations
    user_role: str = current_user.get("role", "")
    if user_role not in ("admin", "superadmin"):
        if rec.get("provider_user_id") != current_user["id"]:
            raise HTTPException(status_code=403, detail="Access denied.")

    return rec


# ---------------------------------------------------------------------------
# PUT /api/attestations/{attestation_id}/attest
# ---------------------------------------------------------------------------

@router.put("/{attestation_id}/attest", summary="Provider attests an HCC condition")
def attest_condition(
    attestation_id: int,
    body: AttestRequest,
    request: Request,
    current_user: dict = Depends(get_current_user),
    _perm: None = Depends(require_permission("attestations", "write")),
) -> dict[str, Any]:
    """
    Record an attestation decision.

    - ``confirm_active``   — condition is clinically present and active today
    - ``confirm_resolved`` — condition was present but has since resolved

    A digital signature (HMAC-SHA256) is computed and stored alongside
    the decision.  When the type is ``confirm_active`` the HCC is
    automatically propagated to ``raf_patient_hcc``.
    """
    provider_user_id: int = current_user["id"]
    ip, ua = _client_meta(request)

    try:
        rec = svc.attest(
            attestation_id,
            provider_user_id=provider_user_id,
            attestation_type=body.attestation_type,
            clinical_justification=body.clinical_justification,
            evidence_references=body.evidence_references,
            ip_address=ip,
            user_agent=ua,
        )
    except ValueError as exc:
        logger.warning("attest id=%s validation error: %s", attestation_id, exc)
        raise HTTPException(status_code=422, detail=str(exc))
    except Exception as exc:
        logger.exception("attest id=%s failed: %s", attestation_id, exc)
        raise HTTPException(status_code=500, detail="Internal server error")

    return rec


# ---------------------------------------------------------------------------
# PUT /api/attestations/{attestation_id}/reject
# ---------------------------------------------------------------------------

@router.put("/{attestation_id}/reject", summary="Provider rejects an HCC condition")
def reject_condition(
    attestation_id: int,
    body: RejectRequest,
    request: Request,
    current_user: dict = Depends(get_current_user),
    _perm: None = Depends(require_permission("attestations", "write")),
) -> dict[str, Any]:
    """
    Record a rejection decision — the condition is clinically inaccurate.

    A ``reject_reason`` is required.
    """
    provider_user_id: int = current_user["id"]
    ip, ua = _client_meta(request)

    try:
        rec = svc.reject(
            attestation_id,
            provider_user_id=provider_user_id,
            reject_reason=body.reject_reason,
            clinical_justification=body.clinical_justification,
            ip_address=ip,
            user_agent=ua,
        )
    except ValueError as exc:
        logger.warning("reject id=%s validation error: %s", attestation_id, exc)
        raise HTTPException(status_code=422, detail=str(exc))
    except Exception as exc:
        logger.exception("reject id=%s failed: %s", attestation_id, exc)
        raise HTTPException(status_code=500, detail="Internal server error")

    return rec


# ---------------------------------------------------------------------------
# PUT /api/attestations/{attestation_id}/defer
# ---------------------------------------------------------------------------

@router.put("/{attestation_id}/defer", summary="Provider defers an HCC condition")
def defer_condition(
    attestation_id: int,
    body: DeferRequest,
    request: Request,
    current_user: dict = Depends(get_current_user),
    _perm: None = Depends(require_permission("attestations", "write")),
) -> dict[str, Any]:
    """
    Defer the attestation decision — more information is needed.

    An optional ``deferred_until`` date can be supplied; defaults to 30 days
    from today.  A reminder will be generated automatically when the
    scheduled date is reached (via the ``/remind`` endpoint).
    """
    provider_user_id: int = current_user["id"]
    ip, ua = _client_meta(request)

    try:
        rec = svc.defer(
            attestation_id,
            provider_user_id=provider_user_id,
            deferred_until=body.deferred_until,
            clinical_justification=body.clinical_justification,
            ip_address=ip,
            user_agent=ua,
        )
    except ValueError as exc:
        logger.warning("defer id=%s validation error: %s", attestation_id, exc)
        raise HTTPException(status_code=422, detail=str(exc))
    except Exception as exc:
        logger.exception("defer id=%s failed: %s", attestation_id, exc)
        raise HTTPException(status_code=500, detail="Internal server error")

    return rec
