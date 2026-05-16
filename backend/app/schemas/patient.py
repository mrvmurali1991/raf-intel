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
    name: str = Field(..., description="Display name, typically '<first> <last>'")
    dob: str | None = Field(None, description="Date of birth in ISO-8601 (YYYY-MM-DD)")
    emr_pid: int | None = Field(
        None,
        description="Source-EMR patient identifier (OpenEMR pid, or numeric FHIR id when available)",
    )
    raf_score: float | None = Field(None, description="Most recent final RAF score")
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
