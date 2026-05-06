"""Polypharmacy + brand-to-generic knowledge-graph API.

Surfaces:
  - ``brand_generic_service`` — brand <-> generic ingredient mapping.
  - ``polypharmacy_service``  — curated drug-combination patterns that imply
    specific HCCs.

These endpoints sit alongside ``/api/kg/atc`` so the frontend can issue a
single coherent set of KG queries without touching any tenant-specific
medication tables.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, Query

from app.auth import get_current_user
from app.services.knowledge_graph import (
    brand_generic_service,
    polypharmacy_service,
)

router = APIRouter(prefix="/api/kg", tags=["knowledge-graph"])


# ---------------------------------------------------------------------------
# Brand -> generic
# ---------------------------------------------------------------------------

@router.get(
    "/brand-generic/lookup",
    summary="Resolve a brand name to its generic ingredient",
)
def brand_lookup(
    brand: str = Query(..., min_length=1, description="Brand name (Ozempic, Eliquis, ...)"),
    current_user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    hit = brand_generic_service.brand_to_generic(brand)
    return {"input": brand, "match": hit}


@router.get(
    "/brand-generic/reverse",
    summary="Reverse-lookup brand variants for a generic ingredient",
)
def brand_reverse(
    generic: str = Query(..., min_length=1, description="Generic ingredient name"),
    current_user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    brands = brand_generic_service.generic_to_brands(generic)
    return {"input": generic, "count": len(brands), "brands": brands}


@router.post(
    "/brand-generic/bulk-resolve",
    summary="Resolve a mixed list of brand / generic / unknown drug names",
)
def brand_bulk_resolve(
    payload: dict[str, Any] = Body(..., examples=[{"drug_names": ["Ozempic", "metformin", "Foobarol"]}]),
    current_user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    drug_names = (payload or {}).get("drug_names")
    if not isinstance(drug_names, list):
        raise HTTPException(
            status_code=422,
            detail="drug_names must be a list of strings",
        )
    results = brand_generic_service.bulk_resolve(drug_names)
    return {
        "count": len(results),
        "resolved": sum(1 for r in results if r.get("input_kind") != "unknown"),
        "results": results,
    }


# ---------------------------------------------------------------------------
# Polypharmacy
# ---------------------------------------------------------------------------

@router.post(
    "/polypharmacy/evaluate",
    summary="Evaluate a med list against curated polypharmacy patterns",
)
def polypharmacy_evaluate(
    payload: dict[str, Any] = Body(
        ...,
        examples=[{
            "drugs": ["furosemide", "lisinopril", "metoprolol", "spironolactone"],
            "patient_context": {"ejection_fraction": 32},
        }],
    ),
    current_user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    drugs = (payload or {}).get("drugs")
    if not isinstance(drugs, list):
        raise HTTPException(
            status_code=422,
            detail="drugs must be a list of strings",
        )
    patient_context = (payload or {}).get("patient_context") or {}
    if patient_context and not isinstance(patient_context, dict):
        raise HTTPException(
            status_code=422,
            detail="patient_context must be an object",
        )
    triggered = polypharmacy_service.evaluate_drug_combination(drugs, patient_context)
    return {
        "drugs": drugs,
        "patient_context": patient_context,
        "count": len(triggered),
        "triggered": triggered,
    }


@router.get(
    "/polypharmacy/patterns",
    summary="List the curated polypharmacy pattern catalogue",
)
def polypharmacy_patterns(
    current_user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    patterns = polypharmacy_service.list_patterns()
    return {"count": len(patterns), "patterns": patterns}
