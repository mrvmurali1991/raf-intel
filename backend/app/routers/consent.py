# Note: do NOT use 'from __future__ import annotations' here —
# it breaks FastAPI/Pydantic schema generation (ForwardRef errors in /openapi.json).

"""
Consent management router — CRUD for patient consent records.

Route prefix: /api/consent
Tags: compliance
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field

from app.auth import get_current_user, get_tenant_id
from app.middleware.idempotency import idempotency_key_dependency, store_idempotent_response
from app.services.consent_service import (
    CONSENT_TYPES,
    check_consent,
    list_consents,
    record_consent,
    revoke_consent,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/consent", tags=["compliance"])


class RecordConsentRequest(BaseModel):
    patient_id: int
    consent_type: str = Field(..., description=f"One of: {', '.join(sorted(CONSENT_TYPES))}")
    granted: bool = True
    expires_at: str | None = None
    details: str = ""


class RevokeConsentRequest(BaseModel):
    patient_id: int
    consent_type: str


class CheckConsentRequest(BaseModel):
    patient_id: int
    consent_type: str


@router.post("/record")
def api_record_consent(
    request: Request,
    response: Response,
    body: RecordConsentRequest,
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
    _idem: None = Depends(idempotency_key_dependency()),
):
    """Record or update a patient consent decision."""
    try:
        consent = record_consent(
            patient_id=body.patient_id,
            tenant_id=tenant_id,
            consent_type=body.consent_type,
            granted=body.granted,
            expires_at=body.expires_at,
            granted_by=current_user.get("id"),
            details=body.details,
        )
        result = {"status": "ok", "consent": consent}
        store_idempotent_response(request, response, result)
        return result
    except ValueError as exc:
        logger.warning("Consent record error: %s", exc)
        raise HTTPException(status_code=400, detail="Invalid consent data. Please check your input.")


@router.post("/check")
def api_check_consent(
    body: CheckConsentRequest,
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
):
    """Check if a patient has active consent for a given type."""
    allowed = check_consent(
        patient_id=body.patient_id,
        tenant_id=tenant_id,
        consent_type=body.consent_type,
    )
    return {"patient_id": body.patient_id, "consent_type": body.consent_type, "granted": allowed}


@router.post("/revoke")
def api_revoke_consent(
    request: Request,
    response: Response,
    body: RevokeConsentRequest,
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
    _idem: None = Depends(idempotency_key_dependency()),
):
    """Revoke a patient's consent."""
    updated = revoke_consent(
        patient_id=body.patient_id,
        tenant_id=tenant_id,
        consent_type=body.consent_type,
        revoked_by=current_user.get("id"),
    )
    if not updated:
        raise HTTPException(status_code=404, detail="No active consent record found.")
    result = {"status": "ok", "revoked": True}
    store_idempotent_response(request, response, result)
    return result


@router.get("/patient/{patient_id}")
def api_list_consents(
    patient_id: int,
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
):
    """List all consent records for a patient."""
    records = list_consents(patient_id=patient_id, tenant_id=tenant_id)
    return {"patient_id": patient_id, "consents": records}
