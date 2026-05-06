"""
Specialty-priors router.

Exposes the read-side of ``services.knowledge_graph.specialty_priors_service``
as a small set of HTTP endpoints used by the AWV / chart-prep UI and by the
suspect-engine integration helper.

Endpoints
---------
GET  /api/kg/specialty/canonical?raw=<str>            - alias resolver
GET  /api/kg/specialty/{specialty}/priors             - all priors for a specialty
POST /api/kg/specialty/apply                          - adjust a base score
GET  /api/kg/specialty/{specialty}/top-likely?n=10    - top-N most likely HCCs
GET  /api/kg/specialty/provider/{id}/calibrated-priors - per-provider calibration

All endpoints are read-only.  Writes happen via the seed script.
"""

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Path, Query
from pydantic import BaseModel, Field

from app.services.knowledge_graph.specialty_priors_service import (
    apply_specialty_prior,
    canonicalize,
    compute_provider_calibrated_priors,
    get_priors_for_specialty,
    top_n_likely_hccs,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/kg/specialty", tags=["knowledge-graph"])


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------

class ApplyRequest(BaseModel):
    """Body for POST /api/kg/specialty/apply."""

    specialty: str = Field(..., min_length=1, description="Raw or canonical specialty")
    hcc_code: str = Field(..., min_length=1, description="HCC code (with or without 'HCC' prefix)")
    base_score: float = Field(..., ge=0.0, description="Baseline score / probability to adjust")


# ---------------------------------------------------------------------------
# GET /canonical
# ---------------------------------------------------------------------------

@router.get("/canonical", summary="Resolve a raw specialty string to its canonical form")
def get_canonical(raw: str = Query(..., min_length=1, description="Raw specialty string from EHR / user")) -> dict[str, Any]:
    """
    Returns the canonical specialty name for *raw*.

    The resolver checks ``kg_specialty_aliases`` first, then falls back to
    a fuzzy match against the curated canonical list.  Always returns a
    non-empty string for non-empty input.
    """
    canonical = canonicalize(raw)
    return {
        "raw": raw,
        "canonical": canonical or None,
        "matched": bool(canonical) and canonical.lower() != raw.strip().lower(),
    }


# ---------------------------------------------------------------------------
# GET /{specialty}/priors
# ---------------------------------------------------------------------------

@router.get("/{specialty}/priors", summary="All HCC priors for a specialty")
def get_specialty_priors(
    specialty: str = Path(..., min_length=1, description="Specialty name (raw or canonical)"),
) -> dict[str, Any]:
    canonical = canonicalize(specialty)
    priors = get_priors_for_specialty(specialty)
    return {
        "specialty_input": specialty,
        "canonical_specialty": canonical or None,
        "count": len(priors),
        "priors": priors,
    }


# ---------------------------------------------------------------------------
# POST /apply
# ---------------------------------------------------------------------------

@router.post("/apply", summary="Apply a specialty prior to a base score")
def apply(body: ApplyRequest) -> dict[str, Any]:
    """
    Multiply *base_score* by the specialty-specific prior weight.

    Missing (specialty, hcc_code) combinations return prior_weight=1.0
    (no adjustment) and ``applied=false`` so callers can detect the
    fall-back.
    """
    try:
        return apply_specialty_prior(body.specialty, body.hcc_code, body.base_score)
    except Exception as exc:
        logger.error("apply_specialty_prior error: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))


# ---------------------------------------------------------------------------
# GET /{specialty}/top-likely
# ---------------------------------------------------------------------------

@router.get("/{specialty}/top-likely", summary="Top-N most likely HCCs for a specialty")
def top_likely(
    specialty: str = Path(..., min_length=1, description="Specialty (raw or canonical)"),
    n: int = Query(default=10, ge=1, le=100, description="Number of top HCCs to return"),
) -> dict[str, Any]:
    """
    Returns the *n* HCCs with the highest prior weight for *specialty*.

    Use this to drive proactive chart-prep — these are the conditions
    the visiting specialist is most likely to confirm or document.
    """
    canonical = canonicalize(specialty)
    rows = top_n_likely_hccs(specialty, n=n)
    return {
        "specialty_input": specialty,
        "canonical_specialty": canonical or None,
        "n": n,
        "count": len(rows),
        "top_likely": rows,
    }


# ---------------------------------------------------------------------------
# GET /provider/{id}/calibrated-priors
# ---------------------------------------------------------------------------

@router.get("/provider/{provider_id}/calibrated-priors", summary="Provider's calibrated HCC priors")
def provider_calibrated(
    provider_id: int = Path(..., ge=1, description="providers.id"),
) -> dict[str, Any]:
    """
    Looks up the provider's specialty in the ``providers`` table and
    returns the full calibrated prior set plus the top-10 most-likely HCCs.

    If the provider does not exist or has no specialty recorded, the
    response is shape-compatible but contains an empty priors list.
    """
    return compute_provider_calibrated_priors(provider_id)
