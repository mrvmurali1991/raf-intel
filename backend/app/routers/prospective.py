"""
Prospective RAF Management router.

Endpoints
---------
GET  /api/prospective/worklist                       - Priority-ranked patient worklist
GET  /api/prospective/worklist/{pid}/pre-visit-summary - Pre-visit RAF summary for a patient
GET  /api/prospective/awv-eligible                   - AWV-eligible patients
POST /api/prospective/awv/{pid}/mark-scheduled       - Mark patient AWV as scheduled
GET  /api/prospective/chase-list                     - Export chase list for outreach
GET  /api/prospective/summary                        - Population prospective summary stats

All endpoints require JWT authentication.
Read endpoints require permission("patients", "read").
Write endpoints require permission("patients", "write").
"""
# Removed: from __future__ import annotations (breaks FastAPI schema generation)

import csv
import io
import logging
from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse

from app.auth import get_current_user, get_tenant_id, require_permission
from app.services import prospective_service as svc

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/prospective", tags=["prospective"])

# _DEFAULT_YEAR removed — use date.today().year inline at each call site
# so the value is always current rather than frozen at import time.


# ---------------------------------------------------------------------------
# GET /worklist
# ---------------------------------------------------------------------------

@router.get(
    "/worklist",
    summary="Priority-ranked patient worklist for prospective RAF management",
)
def get_worklist(
    year: int = Query(default=None, description="Measurement year (defaults to current year)"),
    provider_id: int | None = Query(default=None, description="Filter by provider ID"),
    min_priority: float | None = Query(default=None, ge=0.0, le=100.0, description="Minimum priority score (0-100)"),
    limit: int = Query(default=100, ge=1, le=500, description="Page size"),
    offset: int = Query(default=0, ge=0, description="Page offset"),
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
    _perm: None = Depends(require_permission("patients", "read")),
) -> dict[str, Any]:
    """
    Return a paginated, priority-ranked list of patients for prospective RAF management.

    Each patient record includes:
    - Priority score (0-100) based on days since visit, suspect count, RAF gap, and recapture gaps
    - Current RAF score and potential RAF if all open suspects are addressed
    - Revenue opportunity in dollars
    - Open suspect count and recapture gap count
    - Last encounter date and assigned provider

    Priority score weighting:
    - Days since last visit: 30%
    - Open suspect count: 30%
    - RAF gap (potential vs current): 25%
    - Recapture gaps: 15%
    """
    calc_year = year or date.today().year
    try:
        result = svc.get_prospective_worklist(
            tenant_id=tenant_id,
            year=calc_year,
            provider_id=provider_id,
            min_priority=min_priority,
            limit=limit,
            offset=offset,
        )
    except Exception as exc:
        logger.error("get_worklist error: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")
    return result


# ---------------------------------------------------------------------------
# GET /worklist/{pid}/pre-visit-summary
# ---------------------------------------------------------------------------

@router.get(
    "/worklist/{pid}/pre-visit-summary",
    summary="Pre-visit RAF summary for a specific patient",
)
def get_pre_visit_summary(
    pid: int,
    year: int = Query(default=None, description="Measurement year (defaults to current year)"),
    current_user: dict = Depends(get_current_user),
    _perm: None = Depends(require_permission("patients", "read")),
) -> dict[str, Any]:
    """
    Generate a comprehensive pre-visit RAF summary for the given patient.

    Aggregates:
    - Patient demographics and last encounter date
    - Current RAF score with full HCC breakdown
    - All open AI-detected / rule-based suspect conditions with confidence and rationale
    - Chronic HCCs from the prior year not yet recaptured in the current year
    - HCCs with incomplete or missing MEAT documentation
    - Deduplicated list of recommended ICD-10 codes to evaluate at the visit
    - Estimated revenue impact if all identified gaps are closed

    Designed to be printed or displayed in the EHR workflow immediately before
    the patient encounter.
    """
    calc_year = year or date.today().year
    try:
        result = svc.generate_pre_visit_summary(patient_id=pid, year=calc_year)
    except Exception as exc:
        logger.error("get_pre_visit_summary error pid=%s: %s", pid, exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")

    if result.get("error") == "Patient not found":
        raise HTTPException(status_code=404, detail=f"Patient {pid} not found")

    return result


# ---------------------------------------------------------------------------
# GET /awv-eligible
# ---------------------------------------------------------------------------

@router.get(
    "/awv-eligible",
    summary="Patients eligible for an Annual Wellness Visit",
)
def get_awv_eligible(
    year: int = Query(default=None, description="Benefit year (defaults to current year)"),
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
    _perm: None = Depends(require_permission("patients", "read")),
) -> dict[str, Any]:
    """
    Return all patients who have not received an Annual Wellness Visit (AWV) in
    the specified year.

    AWV CPT codes checked: G0438, G0439, 99381-99387, 99391-99397.

    Each result includes:
    - Patient demographics and contact info
    - Last encounter date and days since last visit
    - Assigned provider
    - Per-patient AWV revenue opportunity (estimated $250)

    The response envelope includes:
    - total_eligible: number of patients without a completed AWV
    - total_awv_completed: patients who already had an AWV this year
    - estimated_awv_revenue: total revenue opportunity for eligible patients
    """
    calc_year = year or date.today().year
    try:
        result = svc.get_awv_eligible(tenant_id=tenant_id, year=calc_year)
    except Exception as exc:
        logger.error("get_awv_eligible error: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")
    return result


# ---------------------------------------------------------------------------
# POST /awv/{pid}/mark-scheduled
# ---------------------------------------------------------------------------

@router.post(
    "/awv/{pid}/mark-scheduled",
    summary="Mark a patient's Annual Wellness Visit as scheduled",
    status_code=200,
)
def mark_awv_scheduled(
    pid: int,
    year: int = Query(default=None, description="Benefit year (defaults to current year)"),
    current_user: dict = Depends(get_current_user),
    _perm: None = Depends(require_permission("patients", "write")),
) -> dict[str, Any]:
    """
    Record that the AWV for a patient has been scheduled.

    Persists a record in `raf_awv_tracking` (created automatically on first call).
    If the patient already has a scheduled AWV for the year, the record is updated
    with the current timestamp and the calling user's ID.

    Used by care coordinators and front desk staff during outreach workflows.
    """
    calc_year = year or date.today().year
    scheduled_by = current_user.get("id")
    try:
        result = svc.mark_awv_scheduled(
            patient_id=pid,
            year=calc_year,
            scheduled_by=scheduled_by,
        )
    except Exception as exc:
        logger.error("mark_awv_scheduled error pid=%s: %s", pid, exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")
    return result


# ---------------------------------------------------------------------------
# GET /chase-list
# ---------------------------------------------------------------------------

@router.get(
    "/chase-list",
    summary="Export chase list for patient outreach",
)
def get_chase_list(
    year: int = Query(default=None, description="Measurement year (defaults to current year)"),
    provider_id: int | None = Query(default=None, description="Filter by provider ID"),
    min_suspects: int | None = Query(default=None, ge=0, description="Minimum open suspect count"),
    min_priority: float | None = Query(default=None, ge=0.0, le=100.0, description="Minimum priority score"),
    not_seen_since_days: int | None = Query(default=None, ge=0, description="Only include patients not seen in the past N days"),
    format: str = Query(default="json", description="Response format: json or csv"),
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
    _perm: None = Depends(require_permission("patients", "read")),
):
    """
    Generate a chase list of patients for outreach campaigns.

    Filters are additive (all applied simultaneously):
    - provider_id: restrict to a specific provider's panel
    - min_suspects: only patients with at least N open suspects
    - min_priority: only patients with priority score >= threshold
    - not_seen_since_days: only patients whose last visit was more than N days ago

    Use `format=csv` to receive a downloadable CSV file suitable for mail merge
    or outreach platform import.  The CSV includes name, phone, address, last
    visit, priority score, suspect count, and assigned provider.
    """
    calc_year = year or date.today().year
    try:
        rows = svc.generate_chase_list(
            tenant_id=tenant_id,
            year=calc_year,
            provider_id=provider_id,
            min_suspects=min_suspects,
            min_priority=min_priority,
            not_seen_since_days=not_seen_since_days,
        )
    except Exception as exc:
        logger.error("get_chase_list error: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")

    if format.lower() == "csv":
        return _build_csv_response(rows, filename=f"chase_list_{calc_year}.csv")

    return {
        "year": calc_year,
        "total": len(rows),
        "rows": rows,
    }


def _build_csv_response(rows: list[dict[str, Any]], filename: str) -> StreamingResponse:
    """Build a streaming CSV response from a list of dicts."""
    if not rows:
        content = "No data"
        return StreamingResponse(
            iter([content]),
            media_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    output = io.StringIO()
    fieldnames = list(rows[0].keys())
    writer = csv.DictWriter(output, fieldnames=fieldnames, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    output.seek(0)

    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ---------------------------------------------------------------------------
# GET /summary
# ---------------------------------------------------------------------------

@router.get(
    "/summary",
    summary="Population-level prospective RAF management statistics",
)
def get_prospective_summary(
    year: int = Query(default=None, description="Measurement year (defaults to current year)"),
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
    _perm: None = Depends(require_permission("patients", "read")),
) -> dict[str, Any]:
    """
    Return a dashboard-ready population prospective summary for the given year.

    Metrics returned:
    - total_patients: total active patients in the panel
    - patients_seen_this_year / patients_not_seen_this_year
    - total_open_suspects: sum of all open AI/rule suspect conditions
    - total_raf_at_risk: aggregate RAF points from open suspects
    - total_revenue_at_risk: estimated revenue if suspects go unaddressed ($12,000/RAF point)
    - awv_completed_this_year / awv_opportunities / awv_revenue_opportunity
    - recapture_patients_affected: patients with prior-year HCCs not yet billed this year
    - total_recapture_gaps: total number of recapture gap HCC events
    - high_priority_patients: count of patients in the top 20% priority tier
    """
    calc_year = year or date.today().year
    try:
        result = svc.get_prospective_summary(tenant_id=tenant_id, year=calc_year)
    except Exception as exc:
        logger.error("get_prospective_summary error: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")
    return result
