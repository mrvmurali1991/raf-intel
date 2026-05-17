"""NLP extraction router — Gemini suspect mining over unstructured notes.

Exposes a single POST endpoint that takes a clinical note and returns a
ranked list of HCC suspects with verbatim evidence offsets.  The endpoint
is tenant-scoped (the caller's tenant_id is used to verify patient access
and to load the patient's already-coded ICDs for filtering) and rate-limited
to 30 requests/minute/user via the shared slowapi limiter.

This is the synchronous, on-demand surface.  Bulk / nightly extraction is
driven by :mod:`app.services.suspect_engine` which calls the same underlying
:func:`extract_hcc_suspects_from_note` function during a full patient scan.
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from app.auth import get_current_user, require_permission
from app.rate_limit import limiter
from app.services.nlp_suspect_extractor import (
    NLPSuspect,
    extract_hcc_suspects_from_note,
)
from app.services.openemr_connector import get_billing_codes
from app.services.patient_service import patient_is_accessible

logger = logging.getLogger(__name__)


router = APIRouter(prefix="/api/nlp", tags=["nlp"])


class ExtractSuspectsRequest(BaseModel):
    """Inbound payload for ``POST /api/nlp/extract-suspects``."""

    patient_id: int = Field(..., description="OpenEMR patient PID")
    note_text: str = Field(..., min_length=1, description="Free-text clinical note")
    measurement_year: int | None = Field(
        default=None,
        description="Measurement year for filter/context. Defaults to today's year.",
    )


class NLPSuspectModel(BaseModel):
    """JSON-serialisable mirror of :class:`NLPSuspect`."""

    hcc_code: str
    icd10: str
    confidence: float
    evidence_sentence: str
    evidence_start: int
    evidence_end: int
    model_version: str


class ExtractSuspectsResponse(BaseModel):
    patient_id: int
    measurement_year: int
    suspects: list[NLPSuspectModel]
    note_chars: int


def _suspect_to_model(s: NLPSuspect) -> NLPSuspectModel:
    return NLPSuspectModel(**s.to_dict())


@router.post(
    "/extract-suspects",
    response_model=ExtractSuspectsResponse,
    summary="Extract HCC suspects from a clinical note (Gemini NLP)",
)
@limiter.limit("30/minute")
def extract_suspects(
    request: Request,
    body: ExtractSuspectsRequest,
    current_user: dict = Depends(get_current_user),
    _perm: Any = Depends(require_permission("raf", "read")),
) -> ExtractSuspectsResponse:
    """Run Gemini-powered HCC suspect extraction on *note_text*.

    The patient_id is verified to belong to the caller's tenant before any
    LLM call is made; the patient's existing billing ICD-10 set is loaded
    and passed to the extractor so already-coded HCCs are filtered out.
    """
    tenant_id: str | None = current_user.get("tenant_id")
    if not tenant_id:
        raise HTTPException(status_code=403, detail="No tenant context for this user")

    pid = int(body.patient_id)
    if not patient_is_accessible(pid, tenant_id):
        # 404 (not 403) so we don't leak the existence of patients in
        # other tenants.
        raise HTTPException(status_code=404, detail=f"Patient {pid} not found")

    measurement_year = body.measurement_year or date.today().year

    # Build the already-coded ICD set so the LLM (and our post-filter) can
    # skip HCCs that are already on the chart for this year.
    try:
        coded = get_billing_codes(pid)
        existing_codes = sorted({
            (r.get("code") or "").strip()
            for r in coded or []
            if r.get("code")
        })
    except Exception as exc:  # noqa: BLE001 — degrade gracefully
        logger.warning(
            "nlp_extract: billing-code fetch failed pid=%s — extracting "
            "without coded-ICD filter: %s",
            pid, exc,
        )
        existing_codes = []

    try:
        suspects = extract_hcc_suspects_from_note(
            note_text=body.note_text,
            existing_codes=existing_codes,
            measurement_year=measurement_year,
        )
    except Exception as exc:
        logger.exception(
            "nlp_extract: extractor raised for pid=%s tenant=%s",
            pid, tenant_id,
        )
        raise HTTPException(
            status_code=502,
            detail=f"NLP extraction failed: {type(exc).__name__}",
        ) from exc

    logger.info(
        "nlp_extract pid=%s tenant=%s year=%s → %d suspect(s)",
        pid, tenant_id, measurement_year, len(suspects),
    )

    return ExtractSuspectsResponse(
        patient_id=pid,
        measurement_year=measurement_year,
        suspects=[_suspect_to_model(s) for s in suspects],
        note_chars=len(body.note_text),
    )
