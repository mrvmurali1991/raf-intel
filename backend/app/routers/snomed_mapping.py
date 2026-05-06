"""
snomed_mapping.py — REST endpoints for the SNOMED CT mapping service.

Routes
------
GET  /api/kg/snomed/resolve?text=...           text → SNOMED matches
GET  /api/kg/snomed/{snomed_id}/icd10          SNOMED → ICD-10
GET  /api/kg/icd10/{icd10}/hcc?year=2026       ICD-10 → HCC
POST /api/kg/text-to-hcc                       full pipeline (single text)
POST /api/kg/problem-list-to-hcc               full pipeline (list of texts)
"""

import logging
from typing import Any
# NOTE: Do NOT add ``from __future__ import annotations`` to this module.
# That import turns every type annotation into a ForwardRef string, which
# Pydantic 2's TypeAdapter cannot resolve at FastAPI ``/openapi.json``
# generation time for body-bound BaseModel parameters.  When that happens
# the OpenAPI endpoint returns 500 and the entire interactive docs page
# breaks.  See incident notes in commit history (search "TypeAdapter").

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from app.auth import get_current_user
from app.rate_limit import limiter
from app.services.knowledge_graph.snomed_service import (
    bulk_resolve_problem_list,
    icd10_to_hcc,
    resolve_text_to_snomed,
    snomed_to_icd10,
    text_to_hcc,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/kg", tags=["knowledge-graph"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _resolve_tenant_id(current_user: dict[str, Any]) -> int:
    """Tenant fallback per project convention: int(tid) or 1 when missing."""
    tenant_id = current_user.get("tenant_id") if isinstance(current_user, dict) else None
    try:
        return int(tenant_id) if tenant_id is not None else 1
    except (TypeError, ValueError):
        return 1


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class TextToHCCBody(BaseModel):
    text: str = Field(..., min_length=1, max_length=2_000)
    model_year: int = Field(default=2026, ge=2018, le=2030)
    top_k: int = Field(default=10, ge=1, le=50)


class ProblemListBody(BaseModel):
    items: list[str] = Field(..., min_length=1, max_length=200)
    model_year: int = Field(default=2026, ge=2018, le=2030)
    top_k_per_item: int = Field(default=5, ge=1, le=20)




# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/snomed/resolve", summary="Fuzzy-match free text to SNOMED CT concepts")
def resolve(
    text: str = Query(..., min_length=1, max_length=500),
    top_k: int = Query(default=5, ge=1, le=25),
    min_score: float = Query(default=50.0, ge=0.0, le=100.0),
    current_user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    tenant_id = _resolve_tenant_id(current_user)  # noqa: F841 (reserved for tenant filtering)
    matches = resolve_text_to_snomed(text, top_k=top_k, min_score=min_score)
    return {
        "query": text,
        "count": len(matches),
        "results": [m.to_dict() for m in matches],
    }


@router.get("/snomed/{snomed_id}/icd10", summary="ICD-10 codes mapped from a SNOMED concept")
def snomed_to_icd10_route(
    snomed_id: str,
    current_user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    if not snomed_id or not snomed_id.strip():
        raise HTTPException(status_code=400, detail="snomed_id is required")
    codes = snomed_to_icd10(snomed_id)
    return {"snomed_id": snomed_id, "icd10_codes": codes, "count": len(codes)}


@router.get("/icd10/{icd10}/hcc", summary="HCCs mapped from an ICD-10 code")
def icd10_to_hcc_route(
    icd10: str,
    year: int = Query(default=2026, ge=2018, le=2030),
    current_user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    if not icd10 or not icd10.strip():
        raise HTTPException(status_code=400, detail="icd10 is required")
    rows = icd10_to_hcc(icd10, model_year=year)
    return {"icd10": icd10, "model_year": year, "count": len(rows), "results": rows}


@router.post("/text-to-hcc", summary="Full pipeline: clinical text → HCC candidates")
@limiter.limit("60/minute")
def text_to_hcc_route(
    request: Request,
    # Explicit ``Body(...)`` is required because ``from __future__ import
    # annotations`` (top of file) hides the Pydantic-ness of TextToHCCBody
    # at FastAPI's parameter-introspection time, which otherwise falls
    # back to treating the parameter as a Query and breaks /openapi.json.
    body: TextToHCCBody = Body(...),
    current_user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    candidates = text_to_hcc(
        body.text,
        top_k_results=body.top_k,
        model_year=body.model_year,
    )
    return {
        "text": body.text,
        "model_year": body.model_year,
        "count": len(candidates),
        "candidates": candidates,
    }


@router.post("/problem-list-to-hcc", summary="Full pipeline over a problem list")
def problem_list_to_hcc_route(
    body: ProblemListBody = Body(...),
    current_user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    result = bulk_resolve_problem_list(
        body.items,
        model_year=body.model_year,
        top_k_per_item=body.top_k_per_item,
    )
    result["model_year"] = body.model_year
    return result
