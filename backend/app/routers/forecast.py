"""
RAF Financial Forecast router.

Translates pending RAF clinical signals (open suspects + missing chronic
re-captures) into forward-looking $ revenue impact.

Endpoints
---------
GET /api/forecast/patient/{patient_id}
GET /api/forecast/provider/{provider_id}
GET /api/forecast/tenant
"""
from __future__ import annotations

import logging
from datetime import date
from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.services.openemr_connector import get_patient
from app.services.raf_forecast import (
    calculate_patient_forecast,
    calculate_provider_forecast,
    calculate_tenant_forecast,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/forecast", tags=["forecast"])


# ---------------------------------------------------------------------------
# GET /api/forecast/patient/{patient_id}
# ---------------------------------------------------------------------------

@router.get(
    "/patient/{patient_id}",
    summary="RAF financial forecast for a single patient",
)
def patient_forecast(
    patient_id: int,
    year: int = Query(default=None, description="Measurement year (defaults to current)"),
) -> dict[str, Any]:
    """
    Project the $ revenue impact if this patient's open suspects are accepted
    and last year's chronic HCCs are re-captured.

    Response shape – see ``raf_forecast.calculate_patient_forecast`` docstring.
    """
    try:
        patient = get_patient(patient_id)
    except Exception as exc:
        logger.warning("patient lookup failed pid=%s: %s", patient_id, exc)
        patient = None

    measurement_year = year or date.today().year
    try:
        forecast = calculate_patient_forecast(patient_id, measurement_year)
    except Exception as exc:
        logger.error(
            "patient_forecast pid=%s year=%s: %s",
            patient_id, measurement_year, exc, exc_info=True,
        )
        raise HTTPException(status_code=500, detail=str(exc))

    if patient:
        forecast["patient_name"] = (
            f"{patient.get('fname', '')} {patient.get('lname', '')}".strip()
            or f"Patient {patient_id}"
        )
    else:
        forecast["patient_name"] = f"Patient {patient_id}"
    return forecast


# ---------------------------------------------------------------------------
# GET /api/forecast/provider/{provider_id}
# ---------------------------------------------------------------------------

@router.get(
    "/provider/{provider_id}",
    summary="RAF financial forecast aggregated for a provider's panel",
)
def provider_forecast(
    provider_id: int,
    year: int = Query(default=None, description="Measurement year (defaults to current)"),
) -> dict[str, Any]:
    """
    Aggregate forecast for the panel of patients assigned to *provider_id*.

    Panel is derived from OpenEMR ``form_encounter.provider_id``.  If the
    derived panel is empty the response still returns 200 with zeros so the
    UI can render an empty-state card.
    """
    measurement_year = year or date.today().year
    try:
        return calculate_provider_forecast(provider_id, measurement_year=measurement_year)
    except Exception as exc:
        logger.error(
            "provider_forecast provider=%s year=%s: %s",
            provider_id, measurement_year, exc, exc_info=True,
        )
        raise HTTPException(status_code=500, detail=str(exc))


# ---------------------------------------------------------------------------
# GET /api/forecast/tenant
# ---------------------------------------------------------------------------

@router.get(
    "",
    include_in_schema=False,  # alias path /api/forecast → tenant
)
@router.get(
    "/tenant",
    summary="RAF financial forecast for the entire tenant population",
)
def tenant_forecast(
    year: int = Query(default=None, description="Measurement year (defaults to current)"),
    tenant_id: str = Query(default=None, description="Tenant identifier (single-tenant deployments may omit)"),
    patient_limit: int = Query(
        default=None, ge=1, le=10_000,
        description="Cap the number of patients aggregated (sample mode)",
    ),
) -> dict[str, Any]:
    """
    Population-wide RAF financial forecast.  Use this on the Reports / CFO
    dashboard to surface the org's total $ opportunity from open suspects.
    """
    measurement_year = year or date.today().year
    try:
        return calculate_tenant_forecast(
            tenant_id=tenant_id,
            measurement_year=measurement_year,
            patient_limit=patient_limit,
        )
    except Exception as exc:
        logger.error(
            "tenant_forecast year=%s tenant=%s: %s",
            measurement_year, tenant_id, exc, exc_info=True,
        )
        raise HTTPException(status_code=500, detail=str(exc))
