"""
Demographic risk modulation router.

Endpoints
---------
POST /api/kg/demographic/modulated-prior
    Compute modulated suspect prior for a single HCC + patient demographic
    + optional list of prior HCCs.

GET  /api/kg/demographic/factors?hcc=
    List active risk-factor rows for a given HCC (admin / inspection).

POST /api/kg/demographic/panel-priors/{provider_id}
    Bulk modulated priors for the provider's panel (suspect engine batch).

All endpoints require an authenticated user and DO NOT touch the official
RAF calculation path — the multipliers feed only the suspect/prior layer.
"""

import logging
from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.auth import get_current_user
from app.services.knowledge_graph import demographic_risk_service as drs

logger = logging.getLogger(__name__)

CurrentUser = dict

router = APIRouter(prefix="/api/kg/demographic", tags=["knowledge-graph"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class ModulatedPriorBody(BaseModel):
    hcc_code: str = Field(..., description="Target HCC code, e.g. '138'")
    age: int | None = Field(None, ge=0, le=120)
    sex: str | None = Field(None, description="M / F / U")
    dual_status: str | None = Field(
        None,
        description="dual / non_dual / any (anything else coerces to 'any')",
    )
    disabled: int | None = Field(None, ge=0, le=1)
    institutional: int | None = Field(None, ge=0, le=1)
    prior_hccs: list[str] = Field(
        default_factory=list,
        description="HCCs the patient is already known to carry",
    )
    base_prior_override: float | None = Field(
        None,
        description="Optional override; skips DB lookup of CMS coefficient",
    )
    model_segment: str = Field("CNA", description="CMS model segment for baseline lookup")
    model_year: int = Field(2024, ge=2000, le=2100)


# ---------------------------------------------------------------------------
# POST /api/kg/demographic/modulated-prior
# ---------------------------------------------------------------------------

@router.post(
    "/modulated-prior",
    summary="Compute modulated suspect prior for an HCC + patient demographic",
)
def modulated_prior(
    body: ModulatedPriorBody,
    current_user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    """
    Apply demographic + comorbidity-conditional multipliers on top of the
    baseline CMS coefficient (or caller-provided override) to produce a
    finer-grained suspect-detection prior.
    """
    try:
        return drs.compute_modulated_prior(
            hcc_code=body.hcc_code,
            patient_demo={
                "age": body.age,
                "sex": body.sex,
                "dual_status": body.dual_status,
                "disabled": body.disabled,
                "institutional": body.institutional,
            },
            prior_hccs=body.prior_hccs,
            model_segment=body.model_segment,
            model_year=body.model_year,
            base_prior_override=body.base_prior_override,
        )
    except Exception as exc:  # pragma: no cover — defensive
        logger.error("modulated_prior body=%s: %s", body, exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))


# ---------------------------------------------------------------------------
# GET /api/kg/demographic/factors
# ---------------------------------------------------------------------------

@router.get(
    "/factors",
    summary="List active demographic-risk factor rows for an HCC",
)
def list_factors(
    hcc: str = Query(..., description="HCC code (e.g. '138')"),
    current_user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    """List every active factor row that targets ``hcc`` for inspection."""
    rows = drs.get_risk_factors(hcc)
    return {
        "hcc_code": hcc,
        "count": len(rows),
        "factors": rows,
    }


# ---------------------------------------------------------------------------
# POST /api/kg/demographic/panel-priors/{provider_id}
# ---------------------------------------------------------------------------

class PanelPriorsBody(BaseModel):
    hcc_codes: list[str] = Field(..., min_length=1)
    year: int | None = Field(None, ge=2000, le=2100)


@router.post(
    "/panel-priors/{provider_id}",
    summary="Bulk modulated priors for a provider's panel",
)
def panel_priors(
    provider_id: int,
    body: PanelPriorsBody,
    current_user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    """
    Compute modulated priors for every HCC in ``body.hcc_codes`` against
    every patient on the provider's panel.  Used by the suspect engine to
    rank "what to look at next" across a population.
    """
    year = body.year or date.today().year
    try:
        return drs.compute_panel_priors(
            provider_id=provider_id,
            year=year,
            hcc_codes=body.hcc_codes,
        )
    except Exception as exc:  # pragma: no cover
        logger.error(
            "panel_priors provider=%s year=%s: %s",
            provider_id, year, exc, exc_info=True,
        )
        raise HTTPException(status_code=500, detail=str(exc))
