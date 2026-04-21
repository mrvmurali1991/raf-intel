"""RADV packet export router.

Exposes a single authenticated endpoint:

    GET /api/radv/{patient_id}/packet?payment_year=YYYY -> application/pdf

The endpoint streams a per-patient, per-payment-year CMS RADV
(Risk Adjustment Data Validation) audit packet PDF. See
``app.services.radv.packet_builder`` for the assembly logic.

Guards
------
- Auth required (JWT via ``get_current_user``).
- Tenant IDOR check reuses ``app.services.patient_service.patient_is_accessible``
  — identical pattern to every other ``/api/patients/{pid}/...`` route.
- Rate-limited to prevent PDF-generation abuse.
- PHI-access audit logged (``log_phi_access(action="export", resource="radv_packet")``).
- Never logs patient name — only the integer ``patient_id``.
"""
# Do NOT add 'from __future__ import annotations' — breaks FastAPI schema gen.

import logging
from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import Response

from app.auth import get_current_user, get_tenant_id
from app.rate_limit import limiter
from app.services import patient_service as patient_svc
from app.services.audit_logger import log_phi_access
from app.services.radv.packet_builder import build_packet

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/radv", tags=["radv"])

_CURRENT_YEAR = date.today().year


def _require_patient_access(pid: int, tenant_id: str) -> None:
    """Raise 404 when *pid* is not accessible for *tenant_id* (IDOR guard)."""
    if not patient_svc.patient_is_accessible(pid, tenant_id):
        # Keep the response opaque — 404 not 403 — so a caller cannot probe
        # other tenants' patient_ids by status-code differencing.
        raise HTTPException(status_code=404, detail=f"Patient {pid} not found")


@router.get(
    "/{patient_id}/packet",
    summary="Download the RADV audit packet PDF for a patient and payment year",
    response_class=Response,
    responses={
        200: {
            "content": {"application/pdf": {}},
            "description": "Rendered PDF audit packet.",
        },
        404: {"description": "Patient not found in caller's tenant."},
        500: {"description": "Packet build or PDF render failed."},
    },
)
@limiter.limit("10/minute")
def download_radv_packet(
    request: Request,
    patient_id: int,
    payment_year: int = Query(
        default=_CURRENT_YEAR,
        ge=2015,
        le=_CURRENT_YEAR + 1,
        description="CMS payment year (maps to raf_patient_hcc.measurement_year)",
    ),
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
) -> Response:
    """Return the RADV audit packet PDF for a patient/payment-year.

    The caller must belong to the same tenant as the patient; otherwise a
    404 is returned (tenant isolation / IDOR prevention — same pattern as
    ``/api/patients/{pid}``). Rate-limited to 10 PDFs/min/IP.
    """
    # 1. IDOR guard — must run before any PHI is read.
    _require_patient_access(patient_id, tenant_id)

    # 2. Build the PDF. Wrap in a broad try so we never leak SQL errors.
    try:
        pdf_bytes: bytes = build_packet(
            patient_id=patient_id,
            payment_year=payment_year,
            db=None,
            tenant_id=tenant_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:  # noqa: BLE001
        # Log with patient_id as int only — never names.
        logger.error(
            "radv.packet build failed patient_id=%d payment_year=%d tenant=%s: %s",
            patient_id,
            payment_year,
            tenant_id,
            exc,
            exc_info=True,
        )
        raise HTTPException(
            status_code=500,
            detail="Failed to build RADV packet. See server logs.",
        )

    # 3. PHI-access audit log (HIPAA 164.312(b)).
    try:
        user_identifier: Any = (
            current_user.get("email")
            or current_user.get("username")
            or current_user.get("id")
            or "unknown"
        )
        log_phi_access(
            action="export",
            resource="radv_packet",
            patient_id=patient_id,
            user=str(user_identifier),
            tenant_id=tenant_id,
            details=f"payment_year={payment_year};size={len(pdf_bytes)}",
        )
    except Exception as exc:  # noqa: BLE001 — never block delivery on audit write
        logger.warning("radv.packet audit log failed patient_id=%d: %s", patient_id, exc)

    filename = f"radv_packet_patient_{patient_id}_py{payment_year}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )
