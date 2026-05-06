"""WHO ATC drug-classification API.

Surfaces the ``app.services.knowledge_graph.atc_service`` helpers as REST
endpoints so the frontend (and downstream services like rx_suspect_engine)
can resolve drug -> ATC -> indication -> HCC at query time.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, Query

from app.auth import get_current_user
from app.services.knowledge_graph import atc_service

router = APIRouter(prefix="/api/kg/atc", tags=["knowledge-graph"])


@router.get("/resolve", summary="Fuzzy-resolve a drug name / NDC / RxCUI to ATC")
def resolve_drug(
    drug: str = Query(..., min_length=1, description="Drug name, RxCUI, or NDC"),
    current_user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    matches = atc_service.resolve_drug_to_atc(drug)
    return {"input": drug, "count": len(matches), "matches": matches}


@router.post("/drug-to-hcc-chain", summary="Drug -> RxNorm -> ATC -> indication -> HCC chain")
def drug_to_hcc_chain(
    payload: dict[str, Any] = Body(..., examples=[{"drug_name": "metformin"}]),
    current_user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    drug_name = (payload or {}).get("drug_name")
    if not drug_name or not isinstance(drug_name, str):
        raise HTTPException(status_code=422, detail="drug_name is required")
    return atc_service.drug_to_hcc_chain(drug_name)


@router.post("/unseen-drug-inference", summary="Infer ATC for an unfamiliar drug")
def unseen_drug_inference(
    payload: dict[str, Any] = Body(..., examples=[{"drug_name": "tirzepatide"}]),
    current_user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    drug_name = (payload or {}).get("drug_name")
    if not drug_name or not isinstance(drug_name, str):
        raise HTTPException(status_code=422, detail="drug_name is required")
    return atc_service.unseen_drug_inference(drug_name)


# NOTE: this catch-all route MUST be declared LAST among the GETs on this prefix
# so the more specific paths (``/resolve``, etc.) take priority during route
# resolution.
@router.get("/{atc_code}", summary="ATC class detail + indications")
def get_atc_class(
    atc_code: str,
    current_user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    hierarchy = atc_service.get_atc_hierarchy(atc_code)
    if not hierarchy:
        raise HTTPException(status_code=404, detail=f"ATC code {atc_code} not found")
    leaf = hierarchy[-1]
    indications = atc_service.get_indications_for_atc(atc_code)
    return {
        "atc_code": leaf.get("atc_code"),
        "name": leaf.get("name"),
        "level": leaf.get("level"),
        "parent_atc_code": leaf.get("parent_atc_code"),
        "concept_id": leaf.get("concept_id"),
        "hierarchy": hierarchy,
        "indications": indications,
    }


@router.get("/{atc_code}/drugs", summary="Drugs mapped to an ATC class")
def get_drugs_in_class(
    atc_code: str,
    include_subclasses: bool = Query(default=True),
    current_user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    drugs = atc_service.get_drugs_in_class(atc_code, include_subclasses=include_subclasses)
    return {
        "atc_code": atc_code,
        "include_subclasses": include_subclasses,
        "count": len(drugs),
        "drugs": drugs,
    }
