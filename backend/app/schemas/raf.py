"""
RAF (Risk Adjustment Factor) Pydantic schemas.

Canonical response shapes for RAF score calculation and HCC breakdown
endpoints. Keeping these separate from router logic enables consistent
field naming and reuse across tests and downstream consumers.
"""
from __future__ import annotations

from pydantic import BaseModel, Field


class HCCComponent(BaseModel):
    """Individual HCC condition contributing to a RAF score."""

    hcc_code: str
    hcc_label: str | None = None
    coefficient: float
    icd10_codes: list[str] = Field(default_factory=list)
    documented: bool = True


class DemographicComponent(BaseModel):
    """Demographic RAF adjustment (age/sex band, Medicaid, new enrollee, etc.)."""

    factor_name: str
    coefficient: float
    description: str | None = None


class RAFScoreResponse(BaseModel):
    """Complete RAF score result for a single patient."""

    patient_id: int
    measurement_year: int
    model: str = Field(..., description="CMS HCC model version, e.g. 'v28'")
    total_raf: float
    demographic_raf: float
    disease_raf: float
    hcc_count: int
    interaction_raf: float = 0.0


class RAFBreakdownResponse(RAFScoreResponse):
    """RAF score with full HCC and demographic component breakdown."""

    hcc_components: list[HCCComponent] = Field(default_factory=list)
    demographic_components: list[DemographicComponent] = Field(default_factory=list)
    interactions: list[dict] = Field(default_factory=list)
