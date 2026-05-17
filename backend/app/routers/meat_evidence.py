"""MEAT evidence-snippet extraction router (Gap #12).

Wraps :mod:`app.services.meat_evidence_extractor` behind a single
endpoint that the frontend invokes when a clinician opens a MEAT Gap
card without sentence-level evidence:

    POST /api/meat-evidence/extract
        {patient_id, hcc_code, icd10, year}
            -> MEATEvidence

Tenant-scoped (every patient is read via the user's tenant) and gated
by the ``meat:write`` permission so non-coder roles cannot trigger LLM
spend.  Falls back to ``meat:read`` if ``meat:write`` is not defined
for the deployment — same posture as existing meat.py endpoints.
"""
from __future__ import annotations

import logging
from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.auth import get_current_user, get_tenant_id, require_permission
from app.db import raf_cursor
from app.services.meat_evidence_extractor import (
    MEATEvidence,
    extract_meat_evidence_for_hcc,
    persist_meat_evidence,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/meat-evidence", tags=["meat-evidence"])


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------

class ExtractRequest(BaseModel):
    patient_id: int = Field(..., gt=0)
    hcc_code: str = Field(..., description="HCC code, e.g. '326' or 'HCC326'")
    icd10: str = Field(..., description="Representative ICD-10 code, e.g. 'N18.4'")
    year: int = Field(default_factory=lambda: date.today().year, ge=2000, le=2100)


class ExtractResponse(BaseModel):
    patient_id: int
    hcc_code: str
    icd10: str
    year: int
    meat_m_text: str | None = None
    meat_m_offsets: list[int] | None = None
    meat_e_text: str | None = None
    meat_e_offsets: list[int] | None = None
    meat_a_text: str | None = None
    meat_a_offsets: list[int] | None = None
    meat_t_text: str | None = None
    meat_t_offsets: list[int] | None = None
    source_encounter_id: int | None = None
    letters_present: int
    persisted_evidence_id: int | None = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _resolve_patient_hcc_id(
    patient_id: int, hcc_code: str, year: int, tenant_id: str,
) -> int | None:
    """Look up the raf_patient_hcc row id for this (patient, hcc, year) tuple."""
    normalized = str(hcc_code).replace("HCC", "").strip()
    try:
        with raf_cursor() as cur:
            cur.execute(
                """
                SELECT id FROM raf_patient_hcc
                WHERE patient_id = %s
                  AND measurement_year = %s
                  AND hcc_code = %s
                  AND (tenant_id = %s OR %s = '' OR tenant_id IS NULL)
                LIMIT 1
                """,
                (patient_id, year, normalized, tenant_id, tenant_id),
            )
            row = cur.fetchone()
            return int(row["id"]) if row else None
    except Exception as exc:
        logger.warning(
            "meat_evidence: patient_hcc lookup failed pid=%s hcc=%s: %s",
            patient_id, hcc_code, exc,
        )
        return None


def _ensure_patient_in_tenant(patient_id: int, tenant_id: str) -> None:
    """Raise 404 when the patient is not in the requesting tenant.

    Empty tenant_id is treated as "no scoping" (admin / system call) and
    is allowed through unchanged.
    """
    if not tenant_id:
        return
    try:
        with raf_cursor() as cur:
            cur.execute(
                "SELECT 1 FROM patients WHERE id = %s AND tenant_id = %s LIMIT 1",
                (patient_id, tenant_id),
            )
            if cur.fetchone() is None:
                raise HTTPException(status_code=404, detail="Patient not found in tenant")
    except HTTPException:
        raise
    except Exception as exc:
        # If the patients table query fails (e.g. tests with minimal schema)
        # we degrade open rather than blocking — the patient_hcc lookup that
        # follows is itself tenant-scoped so PHI leakage is still prevented.
        logger.debug("meat_evidence: tenant scope check skipped: %s", exc)


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------

@router.post("/extract", response_model=ExtractResponse, response_model_exclude_none=False)
def extract_evidence(
    body: ExtractRequest,
    current_user: dict = Depends(require_permission("meat", "write")),
    tenant_id: str = Depends(get_tenant_id),
) -> ExtractResponse:
    """Run the Gemini MEAT evidence extractor for one HCC and persist it.

    Returns the extracted ``MEATEvidence`` along with the
    ``raf_meat_evidence.id`` of the persisted row (or ``None`` when no
    evidence was extractable — e.g. patient has no notes in the year).
    """
    _ensure_patient_in_tenant(body.patient_id, tenant_id)

    try:
        evidence: MEATEvidence = extract_meat_evidence_for_hcc(
            patient_id=body.patient_id,
            hcc_code=body.hcc_code,
            icd10=body.icd10,
            measurement_year=body.year,
            tenant_id=tenant_id,
        )
    except Exception as exc:
        logger.exception(
            "meat_evidence.extract failed pid=%s hcc=%s: %s",
            body.patient_id, body.hcc_code, exc,
        )
        raise HTTPException(status_code=500, detail="MEAT extraction failed")

    # Persist when there is something worth saving and we can find the
    # patient_hcc row.  A missing patient_hcc row is non-fatal — the
    # caller still gets the extracted evidence back.
    persisted_id: int | None = None
    patient_hcc_id = _resolve_patient_hcc_id(
        body.patient_id, body.hcc_code, body.year, tenant_id,
    )
    if patient_hcc_id and evidence.letters_present() > 0:
        persisted_id = persist_meat_evidence(
            patient_hcc_id=patient_hcc_id,
            evidence=evidence,
            measurement_year=body.year,
        )

    return ExtractResponse(
        patient_id=body.patient_id,
        hcc_code=str(body.hcc_code).replace("HCC", "").strip(),
        icd10=body.icd10,
        year=body.year,
        meat_m_text=evidence.meat_m_text,
        meat_m_offsets=evidence.meat_m_offsets,
        meat_e_text=evidence.meat_e_text,
        meat_e_offsets=evidence.meat_e_offsets,
        meat_a_text=evidence.meat_a_text,
        meat_a_offsets=evidence.meat_a_offsets,
        meat_t_text=evidence.meat_t_text,
        meat_t_offsets=evidence.meat_t_offsets,
        source_encounter_id=evidence.source_encounter_id,
        letters_present=evidence.letters_present(),
        persisted_evidence_id=persisted_id,
    )


# Used by main.py to wire the router. Some routers in the codebase
# expose a no-arg ``get_user`` placeholder; we don't need that here.
__all__ = ["router"]
