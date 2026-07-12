"""
Comorbidity-patterns router.

Exposes the HCC comorbidity-patterns engine — see
``app.services.knowledge_graph.comorbidity_engine`` for the rule-evaluation
logic.

Endpoints
---------
POST /api/kg/comorbidity/evaluate-patient/{pid}   Run all active patterns
                                                  against a real patient.
POST /api/kg/comorbidity/evaluate-evidence        Run patterns against an
                                                  in-memory evidence dict.
GET  /api/kg/comorbidity/patterns                 List patterns
                                                  (optional ?hcc=<code>).
GET  /api/kg/comorbidity/patterns/{id}            Pattern detail with source
                                                  attribution.
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import Depends, APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.services.knowledge_graph import comorbidity_engine as engine
from app.auth import get_current_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/kg/comorbidity", tags=["knowledge-graph"], dependencies=[Depends(get_current_user)])


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------

class EvidencePayload(BaseModel):
    """In-memory evidence set used by ``evaluate-evidence``."""

    hccs: list[str] = Field(default_factory=list, description="HCC codes (V28 numeric)")
    icds: list[str] = Field(default_factory=list, description="ICD-10-CM codes (with or without dot)")
    atc_codes: list[str] = Field(default_factory=list, description="ATC drug-class codes")
    labs: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Lab observations: each item must include `loinc` and `value`",
    )


class EvaluateEvidenceRequest(BaseModel):
    evidence: EvidencePayload


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("/evaluate-patient/{pid}", summary="Evaluate comorbidity patterns for a patient")
def evaluate_patient(pid: int, year: int = Query(2026, ge=2000, le=2100)) -> dict[str, Any]:
    """Run every active pattern against the patient identified by *pid*.

    Returns the matches plus the assembled evidence set so the caller can
    inspect what was used.  Always returns 200 with an empty `matches` list
    when nothing matches; raises 404 only when the patient itself doesn't
    exist.
    """
    try:
        evidence = engine.assemble_patient_evidence(pid, year=year)
        matches = engine.evaluate_evidence_set(evidence)
    except Exception as exc:
        logger.exception("evaluate_patient pid=%s failed", pid)
        raise HTTPException(status_code=500, detail="Internal server error")

    return {
        "patient_id": pid,
        "year": year,
        "evidence": evidence,
        "match_count": len(matches),
        "matches": [{**m, "patient_id": pid, "measurement_year": year} for m in matches],
    }


@router.post("/evaluate-evidence", summary="Evaluate comorbidity patterns against in-memory evidence")
def evaluate_evidence(req: EvaluateEvidenceRequest) -> dict[str, Any]:
    """Stateless evaluation — useful for what-if analysis and from the suspect engine."""
    try:
        matches = engine.evaluate_evidence_set(req.evidence.model_dump())
    except Exception as exc:
        logger.exception("evaluate_evidence failed")
        raise HTTPException(status_code=500, detail="Internal server error")
    return {
        "match_count": len(matches),
        "matches": matches,
    }


@router.get("/patterns", summary="List comorbidity patterns")
def list_patterns(
    hcc: str | None = Query(default=None, description="Filter by output_hcc or upgrades_from_hcc"),
    active_only: bool = Query(default=True),
) -> dict[str, Any]:
    rows = engine.list_patterns(hcc_code=hcc, active_only=active_only)
    return {"count": len(rows), "patterns": rows}


@router.get("/patterns/{pattern_id}", summary="Pattern detail")
def pattern_detail(pattern_id: int) -> dict[str, Any]:
    row = engine.get_pattern(pattern_id)
    if not row:
        raise HTTPException(status_code=404, detail=f"pattern {pattern_id} not found")
    return row
