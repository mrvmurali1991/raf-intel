"""
Patient Pydantic schemas.

Canonical request/response shapes for the patient domain.
Routers should use these for response_model declarations to ensure
consistent field naming across all patient-related endpoints.
"""
from __future__ import annotations

from pydantic import BaseModel, Field


class PatientSummary(BaseModel):
    """
    Lightweight patient row used in list responses.

    Captures the minimum fields a worklist / dashboard needs without
    pulling the full PatientResponse payload. Service-layer dicts are
    converted to this model at the router boundary, which gives us a
    typed OpenAPI contract instead of an opaque ``list[dict[str, Any]]``.
    """

    id: int = Field(..., description="Internal patient_id (raf_intelligence.patients.id)")
    # pid mirrors id — the frontend worklist uses p.pid as the row key
    pid: int = Field(..., description="Alias for id used by the worklist frontend")
    name: str = Field(..., description="Display name, typically '<first> <last>'")
    # Individual name parts retained for legacy frontend display
    fname: str | None = Field(None, description="First name")
    lname: str | None = Field(None, description="Last name")
    dob: str | None = Field(None, description="Date of birth in ISO-8601 (YYYY-MM-DD)")
    # DOB is the legacy capitalised alias the frontend reads
    DOB: str | None = Field(None, description="Date of birth — capitalised alias for legacy frontend")
    sex: str | None = Field(None, description="Sex/gender")
    city: str | None = Field(None)
    state: str | None = Field(None)
    postal_code: str | None = Field(None)
    data_source: str | None = Field(None, description="'upload' | 'emr' | 'fhir'")
    emr_pid: int | None = Field(
        None,
        description="Source-EMR patient identifier (OpenEMR pid, or numeric FHIR id when available)",
    )
    raf_score: float | None = Field(None, description="Most recent final RAF score")
    hcc_count: int | None = Field(None, description="Number of active HCCs")
    # RAF score breakdown — populated from raf_scores table when available
    demographic_score: float | None = Field(None, description="Demographic component of RAF score")
    disease_score: float | None = Field(None, description="Disease component of RAF score")
    interaction_score: float | None = Field(None, description="Interaction component of RAF score")
    tenant_id: str | None = Field(None, description="Tenant the patient belongs to")
    mrn: str | None = Field(None, description="Medical Record Number")

    model_config = {"from_attributes": True}


class PatientResponse(BaseModel):
    """Single patient record returned by patient endpoints."""

    id: int
    pid: int | None = None
    first_name: str | None = None
    last_name: str | None = None
    date_of_birth: str | None = None
    sex: str | None = None
    age: int | None = None
    mbi: str | None = None
    tenant_id: str | None = None
    data_source: str | None = None
    is_active: bool = True
    raf_score: float | None = None
    hcc_count: int | None = None

    class Config:
        from_attributes = True


class PatientListResponse(BaseModel):
    """Paginated list of patient records."""

    patients: list[PatientResponse]
    total: int
    page: int = 1
    page_size: int = 25
