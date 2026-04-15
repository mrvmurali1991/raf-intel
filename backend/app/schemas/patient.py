"""
Patient Pydantic schemas.

Canonical request/response shapes for the patient domain.
Routers should use these for response_model declarations to ensure
consistent field naming across all patient-related endpoints.
"""
from __future__ import annotations

from datetime import date
from typing import Any

from pydantic import BaseModel, Field


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
