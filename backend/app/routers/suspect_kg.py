"""
Suspect-KG router — KG-first suspect detection endpoints.

Endpoints
---------
POST /api/suspects/kg-detect/{patient_id}
    Run the full KG-first pipeline for *patient_id* and return the
    detected suspects + audit chain.  Optional body ``{ "year": 2026 }``.

GET  /api/suspects/{suspect_id}/evidence-chain
    Return the full KG attribution chain for a single persisted suspect
    (used by the frontend "why" panel).

GET  /api/suspects/kg-detect/distribution
    Sample distribution of evidence_type across raf_suspect_conditions.
    Useful for ops dashboards to confirm KG dominance after a run.
"""

import logging
from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.auth import get_current_user, require_permission
from app.services.knowledge_graph.suspect_kg_orchestrator import (
    get_evidence_chain,
    get_evidence_type_distribution,
    run_kg_first_detection,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/suspects", tags=["suspects-kg"])


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------

class KgDetectRequest(BaseModel):
    year: int = Field(default=2026, ge=2020, le=2100)
    tenant_id: int = Field(default=1, ge=1)
    chart_text: str | None = Field(default=None, description="Optional chart text for LLM augmentation phase")
    provider_specialty: str | None = Field(default=None)


# ---------------------------------------------------------------------------
# POST /api/suspects/kg-detect/{patient_id}
# ---------------------------------------------------------------------------

@router.post(
    "/kg-detect/{patient_id}",
    summary="Run KG-first suspect detection for a patient",
)
def kg_detect(
    patient_id: int,
    body: KgDetectRequest | None = Body(default=None),
    current_user: dict = Depends(get_current_user),
    _perm: None = Depends(require_permission("patients", "write")),
) -> dict[str, Any]:
    """
    Execute the KG-first → LLM-augmented suspect pipeline for *patient_id*.

    Returns the persisted suspects with their full ``evidence_detail``
    audit chain (kg_rule_id, citations, trigger evidence, comorbidity
    upgrades, demographic / specialty multipliers, final confidence,
    optional LLM corroboration).
    """
    body = body or KgDetectRequest()
    try:
        suspects = run_kg_first_detection(
            patient_id=patient_id,
            year=body.year,
            tenant_id=body.tenant_id,
            chart_text=body.chart_text,
            provider_specialty=body.provider_specialty,
        )
    except Exception as exc:
        logger.error("kg_detect failed pid=%s: %s", patient_id, exc)
        raise HTTPException(status_code=500, detail=f"KG detection failed: {exc}")

    by_type: dict[str, int] = {}
    for s in suspects:
        et = s.get("evidence_type") or "unknown"
        by_type[et] = by_type.get(et, 0) + 1

    return {
        "patient_id": patient_id,
        "year": body.year,
        "tenant_id": body.tenant_id,
        "suspects_found": len(suspects),
        "by_evidence_type": by_type,
        "suspects": suspects,
    }


# ---------------------------------------------------------------------------
# GET /api/suspects/kg-detect/distribution
# ---------------------------------------------------------------------------

@router.get(
    "/kg-detect/distribution",
    summary="Distribution of suspects by evidence_type",
)
def kg_evidence_distribution(
    patient_id: int | None = Query(default=None),
    year: int | None = Query(default=None),
    current_user: dict = Depends(get_current_user),
    _perm: None = Depends(require_permission("patients", "read")),
) -> dict[str, Any]:
    """
    Return a count of raf_suspect_conditions rows grouped by
    evidence_type.  Useful to verify KG dominance after a detection run.
    """
    try:
        dist = get_evidence_type_distribution(patient_id=patient_id, year=year)
    except Exception as exc:
        logger.error("kg_evidence_distribution failed: %s", exc)
        raise HTTPException(status_code=500, detail=f"Distribution query failed: {exc}")

    total = sum(dist.values()) or 1
    pct = {k: round(100.0 * v / total, 2) for k, v in dist.items()}
    return {
        "patient_id": patient_id,
        "year": year,
        "total": sum(dist.values()),
        "by_evidence_type": dist,
        "by_evidence_type_pct": pct,
    }


# ---------------------------------------------------------------------------
# GET /api/suspects/{suspect_id}/evidence-chain
# ---------------------------------------------------------------------------

@router.get(
    "/{suspect_id}/evidence-chain",
    summary="Full KG attribution chain for one suspect",
)
def evidence_chain(
    suspect_id: int,
    current_user: dict = Depends(get_current_user),
    _perm: None = Depends(require_permission("patients", "read")),
) -> dict[str, Any]:
    """
    Return the persisted suspect plus its parsed ``evidence_detail`` JSON.

    The evidence chain contains the KG rule id, the rule citation, the
    trigger evidence (ICD codes, LOINCs + values, drug names), any
    comorbidity upgrades that fired, the calibration multipliers and the
    final confidence — everything a clinician needs to answer "why is
    this suspect on my list?".
    """
    try:
        chain = get_evidence_chain(suspect_id)
    except ValueError:
        raise HTTPException(status_code=404, detail=f"Suspect {suspect_id} not found")
    except Exception as exc:
        logger.error("evidence_chain id=%s: %s", suspect_id, exc)
        raise HTTPException(status_code=500, detail=f"Evidence chain lookup failed: {exc}")

    return chain
