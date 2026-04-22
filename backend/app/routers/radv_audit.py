"""
RADV Audit Router
=================
HTTP endpoints for CMS Risk Adjustment Data Validation (RADV) audit support.

RADV is CMS's process for verifying that submitted HCC codes are supported
by medical records. Every HCC must trace back to:
  encounter → provider → diagnosis → supporting documentation

Routes
------
GET /api/radv/audit-trail/{patient_id}/{hcc_code}
    Complete RADV evidence chain for a single patient/HCC combination.
    Query params: year (int, defaults to current year)

GET /api/radv/report
    Population-level RADV readiness report for the authenticated tenant.
    Query params: year (int, defaults to current year)

GET /api/radv/meat/{patient_id}/{hcc_code}
    MEAT compliance check (Monitor / Evaluate / Assess / Treat) for one HCC.
    Query params: year (int, defaults to current year)

Implementation note: follows the project's raw-SQL / raf_cursor() convention
established in routers/audit.py and routers/meat.py.  No SQLAlchemy Session.
"""
# Do NOT add 'from __future__ import annotations' — breaks FastAPI schema gen.

import logging
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query

from app.auth import get_current_user, get_tenant_id
from app.services.radv_audit_service import (
    check_meat_compliance,
    generate_radv_report,
    get_hcc_audit_trail,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/radv", tags=["radv"])

_CURRENT_YEAR = date.today().year


# ---------------------------------------------------------------------------
# GET /api/radv/audit-trail/{patient_id}/{hcc_code}
# ---------------------------------------------------------------------------


@router.get(
    "/audit-trail/{patient_id}/{hcc_code}",
    summary="RADV audit trail for a single patient/HCC",
    response_model=None,
)
def get_audit_trail(
    patient_id: int,
    hcc_code: int,
    year: int = Query(default=_CURRENT_YEAR, description="Measurement year (e.g. 2026)"),
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
) -> dict:
    """Return the complete RADV evidence chain for one patient/HCC.

    The response includes patient demographics, HCC description, supporting
    ICD-10 codes with hccinfhir enrichment, source encounters, normalized
    diagnoses, MEAT criteria status, document count, overall audit status,
    and a list of any gaps that would fail a RADV audit.
    """
    try:
        return get_hcc_audit_trail(
            patient_id=patient_id,
            hcc_code=hcc_code,
            measurement_year=year,
            tenant_id=tenant_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        logger.error(
            "radv.audit_trail failed patient_id=%s hcc_code=%s: %s",
            patient_id,
            hcc_code,
            exc,
            exc_info=True,
        )
        raise HTTPException(
            status_code=500,
            detail="Failed to generate RADV audit trail",
        )


# ---------------------------------------------------------------------------
# GET /api/radv/report
# ---------------------------------------------------------------------------


@router.get(
    "/report",
    summary="Population-level RADV readiness report",
    response_model=None,
)
def get_radv_report(
    year: int = Query(default=_CURRENT_YEAR, description="Measurement year (e.g. 2026)"),
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
) -> dict:
    """Return a full RADV readiness report for all patients in a tenant/year.

    The report includes total HCC counts, documentation completeness rates
    broken down by MEAT status, RAF score grouped by completeness tier, and
    a ranked list of patients needing attention (those with partial or missing
    MEAT documentation).
    """
    try:
        return generate_radv_report(
            tenant_id=tenant_id,
            measurement_year=year,
        )
    except Exception as exc:
        logger.error(
            "radv.report failed tenant_id=%s year=%s: %s",
            tenant_id,
            year,
            exc,
            exc_info=True,
        )
        raise HTTPException(
            status_code=500,
            detail="Failed to generate RADV report",
        )


# ---------------------------------------------------------------------------
# GET /api/radv/meat/{patient_id}/{hcc_code}
# ---------------------------------------------------------------------------


@router.get(
    "/meat/{patient_id}/{hcc_code}",
    summary="MEAT compliance check for a single patient/HCC",
    response_model=None,
)
def get_meat_compliance(
    patient_id: int,
    hcc_code: int,
    year: int = Query(default=_CURRENT_YEAR, description="Measurement year (e.g. 2026)"),
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
) -> dict:
    """Check whether the four MEAT criteria are satisfied for an HCC.

    MEAT stands for: Monitor, Evaluate, Assess, Treat.  Each element must be
    evidenced in a clinical note for the HCC to be considered RADV-defensible.

    Returns per-criterion status (met/not met), supporting text excerpts,
    the encounter IDs where evidence was found, an overall status
    (COMPLETE / PARTIAL / MISSING), and a plain-language recommendation.
    """
    try:
        return check_meat_compliance(
            patient_id=patient_id,
            hcc_code=hcc_code,
            tenant_id=tenant_id,
            measurement_year=year,
        )
    except Exception as exc:
        logger.error(
            "radv.meat_compliance failed patient_id=%s hcc_code=%s: %s",
            patient_id,
            hcc_code,
            exc,
            exc_info=True,
        )
        raise HTTPException(
            status_code=500,
            detail="Failed to check MEAT compliance",
        )
