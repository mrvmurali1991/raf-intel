"""Admin router — FHIR DocumentReference + Binary ingest.

POST /api/admin/fhir-docs/ingest-patient/{raf_patient_id}
POST /api/admin/fhir-docs/ingest-tenant

Role required: coder | manager | admin
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.auth import get_current_user, get_tenant_id, require_permission

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin/fhir-docs", tags=["fhir-document-ingest"])


# ---------------------------------------------------------------------------
# Request bodies
# ---------------------------------------------------------------------------

class IngestPatientRequest(BaseModel):
    since: str | None = Field(
        None,
        description="ISO-8601 date string. Only fetch DocumentReferences on or after this date. "
                    "e.g. '2025-01-01'",
    )
    measurement_year: int | None = Field(
        None,
        description="Measurement year for HCC scoring. Defaults to current year.",
    )


class IngestTenantRequest(BaseModel):
    since: str | None = Field(
        None,
        description="ISO-8601 date string filter (same as per-patient).",
    )
    measurement_year: int | None = Field(
        None,
        description="Measurement year. Defaults to current year.",
    )
    rate_limit_sec: float = Field(
        1.0,
        ge=0.0,
        le=10.0,
        description="Seconds to wait between patients (EHR-polite throttle). Default 1.0.",
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("/ingest-patient/{raf_patient_id}", summary="Ingest FHIR docs for one patient")
async def ingest_patient(
    raf_patient_id: int,
    body: IngestPatientRequest = IngestPatientRequest(),
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
    _perm=Depends(require_permission("coder")),
) -> dict[str, Any]:
    """List DocumentReferences for ``raf_patient_id``, fetch each Binary,
    run Gemini vision, persist HCC suspects + MEAT.

    Returns an ingest summary with per-document results.
    """
    from app.services.fhir_document_ingest import ingest_patient_documents

    try:
        result = ingest_patient_documents(
            tenant_id,
            raf_patient_id,
            since=body.since,
            measurement_year=body.measurement_year,
        )
    except Exception as exc:
        logger.exception(
            "ingest_patient raf_patient_id=%s tenant=%s: %s",
            raf_patient_id, tenant_id, exc,
        )
        raise HTTPException(status_code=500, detail="Internal server error")

    if result.get("status") == "error":
        raise HTTPException(status_code=422, detail=result.get("error", "ingest_error"))

    return result


@router.post("/ingest-tenant", summary="Ingest FHIR docs for all active patients in tenant")
async def ingest_tenant(
    body: IngestTenantRequest = IngestTenantRequest(),
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
    _perm=Depends(require_permission("manager")),
) -> dict[str, Any]:
    """Iterate all active patients and ingest their FHIR documents.

    Rate-limited at ``body.rate_limit_sec`` per patient to avoid overwhelming
    the EHR FHIR endpoint.  Returns an aggregate summary.
    """
    from app.services.fhir_document_ingest import ingest_tenant_documents

    try:
        result = ingest_tenant_documents(
            tenant_id,
            since=body.since,
            measurement_year=body.measurement_year,
            rate_limit_sec=body.rate_limit_sec,
        )
    except Exception as exc:
        logger.exception(
            "ingest_tenant tenant=%s: %s", tenant_id, exc,
        )
        raise HTTPException(status_code=500, detail="Internal server error")

    return result
