"""
Unified Knowledge-Graph query router.

Endpoints
---------
POST  /api/kg/query/related-hccs
GET   /api/kg/query/evidence-chain/{hcc_code}/patient/{pid}?year=2026
GET   /api/kg/query/traverse?from=&to=&max_depth=5
GET   /api/kg/query/explain/{hcc_code}
POST  /api/kg/query/patient-full-inference/{pid}
GET   /api/kg/query/stats?since_hours=24
GET   /api/kg/query/sub-services         (availability dashboard)
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.services.knowledge_graph import kg_lookup_service as kg

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/kg/query", tags=["knowledge-graph"])


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------

class RelatedHccsRequest(BaseModel):
    concept_uri_or_text: str = Field(..., description="Concept URI, text, or ICD-10 code")
    patient_context: dict[str, Any] | None = Field(
        default=None,
        description="Optional patient features: age, sex, dual, specialty, "
                    "prior_hccs, drugs, labs",
    )
    limit: int = Field(default=10, ge=1, le=100)


class FullInferenceRequest(BaseModel):
    year: int = Field(default=2026, ge=2020, le=2099)
    include_modulation: bool = Field(default=True)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("/related-hccs", summary="HCCs related to a concept (with patient context)")
def related_hccs(req: RelatedHccsRequest) -> dict[str, Any]:
    try:
        results = kg.get_related_hccs(
            concept_uri_or_text=req.concept_uri_or_text,
            patient_context=req.patient_context,
            limit=req.limit,
        )
        return {"count": len(results), "results": results}
    except Exception as exc:
        logger.exception("related_hccs failed")
        raise HTTPException(status_code=500, detail=str(exc))


@router.get(
    "/evidence-chain/{hcc_code}/patient/{pid}",
    summary="Full evidence chain for a single (patient, HCC, year)",
)
def evidence_chain(
    hcc_code: str,
    pid: int,
    year: int = Query(default=2026, ge=2020, le=2099),
) -> dict[str, Any]:
    try:
        return kg.get_evidence_chain(hcc_code=hcc_code, patient_id=pid, year=year)
    except Exception as exc:
        logger.exception("evidence_chain failed")
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/traverse", summary="BFS shortest path between two concept URIs")
def traverse(
    start_uri: str = Query(..., alias="from", description="Source concept URI"),
    end_uri: str = Query(..., alias="to", description="Target concept URI"),
    max_depth: int = Query(default=5, ge=1, le=10),
) -> dict[str, Any]:
    try:
        path = kg.traverse_path(start_uri=start_uri, end_uri=end_uri, max_depth=max_depth)
        return {"from": start_uri, "to": end_uri, "depth": max(0, len(path) - 1),
                "path": path, "found": bool(path)}
    except Exception as exc:
        logger.exception("traverse failed")
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/explain/{hcc_code}", summary="Static explainer for an HCC")
def explain(hcc_code: str) -> dict[str, Any]:
    try:
        return kg.explain_hcc(hcc_code)
    except Exception as exc:
        logger.exception("explain_hcc failed")
        raise HTTPException(status_code=500, detail=str(exc))


@router.post(
    "/patient-full-inference/{pid}",
    summary="Run all sub-services for one patient and return ranked candidates",
)
def patient_full_inference(
    pid: int,
    req: FullInferenceRequest | None = None,
) -> dict[str, Any]:
    req = req or FullInferenceRequest()
    try:
        return kg.patient_full_inference(
            patient_id=pid,
            year=req.year,
            include_modulation=req.include_modulation,
        )
    except Exception as exc:
        logger.exception("patient_full_inference failed pid=%s", pid)
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/stats", summary="kg_query_log aggregates")
def stats(since_hours: int = Query(default=24, ge=1, le=720)) -> dict[str, Any]:
    return kg.get_query_stats(since_hours=since_hours)


@router.get("/sub-services", summary="Availability of every KG sub-service")
def sub_service_status() -> dict[str, Any]:
    """Useful for ops: shows which sibling agents have shipped their service."""
    return {"available": kg.sub_service_status()}
