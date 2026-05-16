"""
Annual Wellness Visit (AWV) Scheduling router.

Endpoints
---------
GET  /api/awv                          - List AWV schedules with filters
POST /api/awv                          - Create a new AWV schedule record
GET  /api/awv/eligible                 - List patients eligible for AWV
GET  /api/awv/dashboard                - Completion rates and revenue impact
POST /api/awv/bulk-outreach            - Generate bulk outreach campaign
GET  /api/awv/{id}                     - Get single AWV schedule detail
PUT  /api/awv/{id}                     - Partial update of an AWV schedule
PUT  /api/awv/{id}/schedule            - Set appointment date/time
PUT  /api/awv/{id}/complete            - Mark completed with clinical results
POST /api/awv/{id}/outreach            - Log an outreach contact attempt
GET  /api/awv/{id}/checklist           - Get the full visit checklist
PUT  /api/awv/{id}/checklist/{item_id} - Mark a checklist item complete or incomplete

All endpoints require JWT authentication.
Read-only endpoints require permission("patients", "read").
Write endpoints require permission("patients", "write").
"""
# Note: do NOT use 'from __future__ import annotations' here —
# it breaks FastAPI/Pydantic schema generation.

import logging
from datetime import date
from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, Path, Query
from pydantic import BaseModel, ConfigDict

from app.auth import get_current_user, get_tenant_id, require_permission
from app.services import awv_prioritization as prio
from app.services import awv_service as svc

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/awv", tags=["awv"])


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------


class _AWVBase(BaseModel):
    """Base with extra='allow' for complex service-layer dicts."""
    model_config = ConfigDict(extra="allow")


class AWVScheduleResponse(_AWVBase):
    id: int
    patient_id: int
    tenant_id: str | None = None
    schedule_year: int
    status: str


class AWVListResponse(BaseModel):
    total: int
    limit: int
    offset: int
    schedules: list[dict[str, Any]]


class AWVEligibleResponse(BaseModel):
    total_eligible: int
    total_already_completed: int
    estimated_awv_revenue: float
    patients: list[dict[str, Any]]


class AWVDashboardResponse(_AWVBase):
    total_schedules: int
    completion_rate_pct: float


class AWVBulkOutreachResponse(BaseModel):
    created: int
    awv_ids: list[int]
    campaign_date: str


class AWVChecklistResponse(_AWVBase):
    awv_id: int
    completion_pct: float


class AWVChecklistItemResponse(_AWVBase):
    id: int
    awv_id: int
    checklist_type: str
    item_name: str
    completed: bool


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _current_year() -> int:
    return date.today().year


def _get_or_404(awv_id: int) -> dict[str, Any]:
    record = svc.get_schedule(awv_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"AWV schedule {awv_id} not found")
    return record


# ---------------------------------------------------------------------------
# GET /api/awv/eligible
# Must be declared BEFORE /{id} to prevent routing collision.
# ---------------------------------------------------------------------------

@router.get(
    "/eligible",
    summary="List patients eligible for an Annual Wellness Visit",
    response_model=AWVEligibleResponse,
    response_model_exclude_none=True,
)
def get_eligible_patients(
    year: int = Query(default=None, description="Benefit year (defaults to current year)"),
    sort: str = Query(
        default="default",
        description="Result ordering: 'default' (alphabetical) or 'priority' "
                    "(ranked by expected RAF/$ lift via the prioritization engine)",
    ),
    limit: int = Query(default=500, ge=1, le=2000, description="Max patients returned when sort=priority"),
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
    _perm: None = Depends(require_permission("patients", "read")),
) -> dict[str, Any]:
    """
    Return all patients who qualify for an AWV in *year* and do not yet have a
    completed AWV schedule record or billed AWV claim for that year.

    Each patient entry includes demographics, last encounter date, open HCC gap
    count, assigned provider, and the per-patient AWV revenue opportunity.

    Response envelope:
    - total_eligible: patients without a completed AWV
    - total_already_completed: patients who have already had their AWV
    - estimated_awv_revenue: total revenue opportunity (eligible * $250)
    - patients[]: patient list

    When ``sort=priority`` is supplied each patient row is enriched with a
    ``priority_score``, ``expected_revenue_lift``, ``score_reasons`` array, and
    the list is sorted highest-score-first (capped to ``limit``). The
    underlying score blend is documented in
    ``backend/app/services/awv_prioritization.py``.
    """
    calc_year = year or _current_year()
    try:
        result = svc.get_eligible_patients(tenant_id=tenant_id, year=calc_year)
    except Exception as exc:
        logger.exception("get_eligible_patients error: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")

    if sort != "priority":
        return result

    patients = result.get("patients") or []
    if not patients:
        return result

    pids = [int(p["patient_id"]) for p in patients if p.get("patient_id") is not None]
    try:
        ranking = prio.rank_panel(
            tenant_id=tenant_id,
            patient_ids=pids,
            limit=max(limit, len(pids)),
        )
    except Exception as exc:
        logger.error("priority sort failed, returning unsorted list: %s", exc, exc_info=True)
        return result

    score_map = {row["patient_id"]: row for row in ranking.get("patients", [])}
    enriched: list[dict[str, Any]] = []
    for p in patients:
        pid = int(p.get("patient_id") or 0)
        score = score_map.get(pid)
        if score:
            p["priority_score"] = score["score"]
            p["expected_revenue_lift"] = score["expected_revenue_lift"]
            p["expected_raf_lift"] = score["expected_raf_lift"]
            p["score_reasons"] = score["reasons"]
            p["score_components"] = score["components"]
            p["high_confidence_suspect_count"] = score["high_confidence_suspect_count"]
        else:
            p["priority_score"] = 0.0
            p["expected_revenue_lift"] = 0.0
            p["expected_raf_lift"] = 0.0
            p["score_reasons"] = []
            p["score_components"] = {}
            p["high_confidence_suspect_count"] = 0
        enriched.append(p)

    enriched.sort(
        key=lambda r: (
            -float(r.get("priority_score") or 0),
            -float(r.get("expected_revenue_lift") or 0),
            int(r.get("patient_id") or 0),
        )
    )
    result["patients"] = enriched[:limit]
    result["sort"] = "priority"
    result["weights"] = ranking.get("weights")
    return result


# ---------------------------------------------------------------------------
# GET /api/awv/priority-list
# Must be declared BEFORE /{id}.
# ---------------------------------------------------------------------------

@router.get(
    "/priority-list",
    summary="Ranked AWV outreach list — highest expected RAF/$ lift first",
)
def get_priority_list(
    provider_id: int | None = Query(default=None, description="Restrict to this provider's panel"),
    limit: int = Query(default=50, ge=1, le=500, description="Max patients returned"),
    weight_revenue: float | None = Query(default=None, ge=0, le=1, description="Override default revenue weight (0.45)"),
    weight_high_conf: float | None = Query(default=None, ge=0, le=1, description="Override high-confidence-suspects weight (0.25)"),
    weight_recency: float | None = Query(default=None, ge=0, le=1, description="Override recency weight (0.15)"),
    weight_no_awv: float | None = Query(default=None, ge=0, le=1, description="Override no-AWV-in-year weight (0.15)"),
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
    _perm: None = Depends(require_permission("patients", "read")),
) -> dict[str, Any]:
    """
    Return the panel ranked by composite priority score (0-100).

    Each entry includes:
      - score, expected_raf_lift, expected_revenue_lift
      - suspect_count, high_confidence_suspect_count
      - last_encounter_days_ago, last_awv_days_ago, open_care_gaps
      - reasons[]: human-readable explanation list (for tooltip rendering)
      - components: per-axis weighted contribution (sums to score / 100)

    Optional weight_* query params override the default 0.45/0.25/0.15/0.15
    blend and are renormalized to sum to 1.0.

    The endpoint is read-only and does NOT mutate any AWV schedule or
    outreach log row.
    """
    overrides: dict[str, float] = {}
    if weight_revenue is not None:
        overrides["revenue"] = weight_revenue
    if weight_high_conf is not None:
        overrides["high_conf_suspects"] = weight_high_conf
    if weight_recency is not None:
        overrides["recency"] = weight_recency
    if weight_no_awv is not None:
        overrides["no_awv"] = weight_no_awv

    try:
        return prio.rank_panel(
            tenant_id=tenant_id,
            provider_id=provider_id,
            limit=limit,
            weights=overrides or None,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except Exception as exc:
        logger.exception("get_priority_list error: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


# ---------------------------------------------------------------------------
# GET /api/awv/dashboard
# Must be declared BEFORE /{id}.
# ---------------------------------------------------------------------------

@router.get(
    "/dashboard",
    summary="AWV programme completion rates and revenue impact",
    response_model=AWVDashboardResponse,
    response_model_exclude_none=True,
)
def get_dashboard(
    year: int = Query(default=None, description="Measurement year (defaults to current year)"),
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
    _perm: None = Depends(require_permission("patients", "read")),
) -> dict[str, Any]:
    """
    Return a dashboard-ready summary of the AWV programme for the given year.

    Metrics returned:
    - total_schedules and breakdown by status
    - completion_rate_pct
    - avg_outreach_attempts per patient
    - awv_revenue_captured (completed visits * $250)
    - total_conditions_reviewed / confirmed / new_identified
    - avg_raf_lift_per_visit and total_raf_revenue_impact
    """
    calc_year = year or _current_year()
    try:
        return svc.get_dashboard(tenant_id=tenant_id, year=calc_year)
    except Exception as exc:
        logger.exception("get_dashboard error: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


# ---------------------------------------------------------------------------
# POST /api/awv/bulk-outreach
# Must be declared BEFORE /{id}.
# ---------------------------------------------------------------------------

@router.post(
    "/bulk-outreach",
    summary="Generate a bulk outreach campaign for eligible/pending AWV patients",
    status_code=201,
    response_model=AWVBulkOutreachResponse,
)
def bulk_outreach(
    year: int = Query(default=None, description="Benefit year (defaults to current year)"),
    method: str = Query(default="phone", description="Outreach method: phone, email, sms, mail"),
    provider_npi: str | None = Query(default=None, description="Restrict to a specific provider NPI"),
    max_patients: int = Query(default=500, ge=1, le=2000, description="Maximum patients to include"),
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
    _perm: None = Depends(require_permission("patients", "write")),
) -> dict[str, Any]:
    """
    Create outreach log entries for all eligible and outreach-pending AWV
    schedules in one operation.

    Each targeted patient receives a single outreach log entry with outcome
    'no_answer' as a placeholder. Outreach staff update the outcome when the
    contact is completed.  The schedule's outreach_attempts counter and
    last_outreach_date are updated automatically.

    Returns:
    - created: number of outreach records inserted
    - awv_ids: list of schedule IDs that were targeted
    - campaign_date: date the campaign was run
    """
    calc_year = year or _current_year()
    contacted_by = current_user.get("id")
    try:
        return svc.create_bulk_outreach(
            tenant_id=tenant_id,
            year=calc_year,
            method=method,
            contacted_by=contacted_by,
            provider_npi=provider_npi,
            max_patients=max_patients,
        )
    except Exception as exc:
        logger.exception("bulk_outreach error: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


# ---------------------------------------------------------------------------
# GET /api/awv
# ---------------------------------------------------------------------------

@router.get(
    "",
    summary="List AWV schedules with optional filters",
    response_model=AWVListResponse,
)
def list_schedules(
    year: int | None = Query(default=None, description="Filter by schedule year"),
    status: str | None = Query(
        default=None,
        description="Filter by status: eligible, outreach_pending, scheduled, completed, declined, no_show",
    ),
    provider_npi: str | None = Query(default=None, description="Filter by provider NPI"),
    patient_id: int | None = Query(default=None, description="Filter by patient ID"),
    limit: int = Query(default=100, ge=1, le=500, description="Page size"),
    offset: int = Query(default=0, ge=0, description="Page offset"),
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
    _perm: None = Depends(require_permission("patients", "read")),
) -> dict[str, Any]:
    """
    Return a paginated list of AWV schedule records.

    All filters are optional and additive. When no year is provided all years
    for the tenant are returned.
    """
    try:
        return svc.list_schedules(
            tenant_id=tenant_id,
            year=year,
            status=status,
            provider_npi=provider_npi,
            patient_id=patient_id,
            limit=limit,
            offset=offset,
        )
    except Exception as exc:
        logger.exception("list_schedules error: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


# ---------------------------------------------------------------------------
# POST /api/awv
# ---------------------------------------------------------------------------

@router.post(
    "",
    summary="Create a new AWV schedule record for a patient",
    status_code=201,
)
def create_schedule(
    body: dict[str, Any] = Body(
        ...,
        example={
            "patient_id": 1042,
            "schedule_year": 2026,
            "provider_npi": "1234567890",
            "visit_type": "subsequent_awv",
            "eligibility_date": "2026-01-01",
            "location": "Main Street Clinic",
            "notes": "Patient prefers morning appointments",
        },
    ),
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
    _perm: None = Depends(require_permission("patients", "write")),
) -> dict[str, Any]:
    """
    Create an AWV schedule record.

    Required body fields:
    - patient_id (int): OpenEMR patient pid
    - schedule_year (int): Calendar year for the AWV

    Optional body fields:
    - provider_npi (str): Rendering provider NPI
    - visit_type (str): initial_awv | subsequent_awv | welcome_to_medicare
    - eligibility_date (str): YYYY-MM-DD
    - location (str): Practice or facility name
    - notes (str): Free-text notes

    The HCC gap list and estimated RAF impact are computed automatically from the
    patient's prior-year HCC data.

    Returns HTTP 409 if a schedule already exists for the patient in the given year.
    """
    patient_id = body.get("patient_id")
    schedule_year = body.get("schedule_year")
    if not patient_id or not schedule_year:
        raise HTTPException(status_code=422, detail="patient_id and schedule_year are required")

    try:
        return svc.create_schedule(
            patient_id=int(patient_id),
            tenant_id=tenant_id,
            schedule_year=int(schedule_year),
            provider_npi=body.get("provider_npi"),
            visit_type=body.get("visit_type"),
            eligibility_date=body.get("eligibility_date"),
            location=body.get("location"),
            notes=body.get("notes"),
        )
    except Exception as exc:
        err_str = str(exc).lower()
        if "duplicate entry" in err_str or "unique" in err_str:
            raise HTTPException(
                status_code=409,
                detail=f"An AWV schedule already exists for patient {patient_id} in {schedule_year}",
            )
        logger.exception("create_schedule error: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


# ---------------------------------------------------------------------------
# GET /api/awv/{id}
# ---------------------------------------------------------------------------

@router.get(
    "/{awv_id}",
    summary="Get AWV schedule detail",
    response_model=AWVScheduleResponse,
    response_model_exclude_none=True,
)
def get_schedule(
    awv_id: int = Path(..., description="AWV schedule ID"),
    current_user: dict = Depends(get_current_user),
    _perm: None = Depends(require_permission("patients", "read")),
) -> dict[str, Any]:
    """Return a single AWV schedule record including all fields."""
    return _get_or_404(awv_id)


# ---------------------------------------------------------------------------
# PUT /api/awv/{id}
# ---------------------------------------------------------------------------

@router.put(
    "/{awv_id}",
    summary="Partial update of an AWV schedule",
    response_model=AWVScheduleResponse,
    response_model_exclude_none=True,
)
def update_schedule(
    awv_id: int = Path(..., description="AWV schedule ID"),
    body: dict[str, Any] = Body(
        ...,
        example={
            "status": "no_show",
            "notes": "Patient did not attend the 9am slot on 2026-03-15",
        },
    ),
    current_user: dict = Depends(get_current_user),
    _perm: None = Depends(require_permission("patients", "write")),
) -> dict[str, Any]:
    """
    Partially update an AWV schedule record.

    Updatable fields: provider_npi, status, visit_type, location, notes,
    decline_reason, outreach_attempts, last_outreach_date,
    hcc_gaps_to_review, estimated_raf_impact.

    For appointment scheduling use PUT /{id}/schedule.
    For visit completion use PUT /{id}/complete.
    """
    _get_or_404(awv_id)
    try:
        result = svc.update_schedule(awv_id, body)
    except Exception as exc:
        logger.exception("update_schedule error awv_id=%s: %s", awv_id, exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")
    return result


# ---------------------------------------------------------------------------
# PUT /api/awv/{id}/schedule
# ---------------------------------------------------------------------------

@router.put(
    "/{awv_id}/schedule",
    summary="Set confirmed appointment date for an AWV",
)
def set_appointment(
    awv_id: int = Path(..., description="AWV schedule ID"),
    body: dict[str, Any] = Body(
        ...,
        example={
            "scheduled_date": "2026-04-20 09:00:00",
            "location": "Main Street Clinic",
            "notes": "Patient requested Dr. Smith",
        },
    ),
    current_user: dict = Depends(get_current_user),
    _perm: None = Depends(require_permission("patients", "write")),
) -> dict[str, Any]:
    """
    Record a confirmed appointment date and advance the schedule status to
    'scheduled'.

    Required body fields:
    - scheduled_date (str): ISO datetime, e.g. "2026-04-20 09:00:00"

    Optional:
    - location (str): Clinic or facility name
    - notes (str): Scheduling notes
    """
    _get_or_404(awv_id)
    scheduled_date = body.get("scheduled_date")
    if not scheduled_date:
        raise HTTPException(status_code=422, detail="scheduled_date is required")
    try:
        return svc.set_appointment(
            awv_id=awv_id,
            scheduled_date=scheduled_date,
            location=body.get("location"),
            notes=body.get("notes"),
        )
    except Exception as exc:
        logger.exception("set_appointment error awv_id=%s: %s", awv_id, exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


# ---------------------------------------------------------------------------
# PUT /api/awv/{id}/complete
# ---------------------------------------------------------------------------

@router.put(
    "/{awv_id}/complete",
    summary="Mark an AWV as completed and capture clinical results",
)
def complete_schedule(
    awv_id: int = Path(..., description="AWV schedule ID"),
    body: dict[str, Any] = Body(
        ...,
        example={
            "completed_date": "2026-04-20",
            "conditions_reviewed": 8,
            "conditions_confirmed": 6,
            "new_conditions_identified": 2,
            "hcc_codes_captured": [19, 85, 111],
            "raf_score_before": 1.2340,
            "raf_score_after": 1.5680,
            "notes": "Patient cooperative. PHQ-9 score 4.",
        },
    ),
    current_user: dict = Depends(get_current_user),
    _perm: None = Depends(require_permission("patients", "write")),
) -> dict[str, Any]:
    """
    Mark the AWV as completed and record clinical outcomes.

    Required body fields:
    - completed_date (str): YYYY-MM-DD

    Optional body fields:
    - conditions_reviewed (int)
    - conditions_confirmed (int)
    - new_conditions_identified (int)
    - hcc_codes_captured (list[int]): HCC codes successfully documented
    - raf_score_before (float): RAF score snapshot before the visit
    - raf_score_after (float): RAF score snapshot after coding is finalised
    - notes (str): Provider notes

    Returns both the updated schedule and the visit results record.
    """
    _get_or_404(awv_id)
    completed_date = body.get("completed_date")
    if not completed_date:
        raise HTTPException(status_code=422, detail="completed_date is required")
    try:
        return svc.complete_schedule(
            awv_id=awv_id,
            completed_date=completed_date,
            conditions_reviewed=int(body.get("conditions_reviewed") or 0),
            conditions_confirmed=int(body.get("conditions_confirmed") or 0),
            new_conditions_identified=int(body.get("new_conditions_identified") or 0),
            hcc_codes_captured=body.get("hcc_codes_captured"),
            raf_score_before=float(body["raf_score_before"]) if body.get("raf_score_before") is not None else None,
            raf_score_after=float(body["raf_score_after"]) if body.get("raf_score_after") is not None else None,
            notes=body.get("notes"),
        )
    except Exception as exc:
        logger.exception("complete_schedule error awv_id=%s: %s", awv_id, exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


# ---------------------------------------------------------------------------
# POST /api/awv/{id}/outreach
# ---------------------------------------------------------------------------

@router.post(
    "/{awv_id}/outreach",
    summary="Log an outreach contact attempt",
    status_code=201,
)
def log_outreach(
    awv_id: int = Path(..., description="AWV schedule ID"),
    body: dict[str, Any] = Body(
        ...,
        example={
            "method": "phone",
            "outcome": "left_message",
            "notes": "Left voicemail at 10:15 AM",
        },
    ),
    current_user: dict = Depends(get_current_user),
    _perm: None = Depends(require_permission("patients", "write")),
) -> dict[str, Any]:
    """
    Record an outreach contact attempt for an AWV.

    Required body fields:
    - method (str): phone | email | sms | mail
    - outcome (str): no_answer | left_message | scheduled | declined | wrong_number

    Optional:
    - notes (str): Contact attempt notes
    - contact_date (str): ISO datetime (defaults to now)

    The schedule's outreach_attempts counter and last_outreach_date are
    updated automatically. When the status is 'eligible' it is advanced to
    'outreach_pending'.
    """
    _get_or_404(awv_id)
    method = body.get("method")
    outcome = body.get("outcome")
    if not method or not outcome:
        raise HTTPException(status_code=422, detail="method and outcome are required")
    try:
        return svc.log_outreach(
            awv_id=awv_id,
            method=method,
            outcome=outcome,
            contacted_by=current_user.get("id"),
            notes=body.get("notes"),
            contact_date=body.get("contact_date"),
        )
    except Exception as exc:
        logger.exception("log_outreach error awv_id=%s: %s", awv_id, exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


# ---------------------------------------------------------------------------
# GET /api/awv/{id}/checklist
# ---------------------------------------------------------------------------

@router.get(
    "/{awv_id}/checklist",
    summary="Get the full visit checklist grouped by phase",
    response_model=AWVChecklistResponse,
    response_model_exclude_none=True,
)
def get_checklist(
    awv_id: int = Path(..., description="AWV schedule ID"),
    current_user: dict = Depends(get_current_user),
    _perm: None = Depends(require_permission("patients", "read")),
) -> dict[str, Any]:
    """
    Return the AWV checklist for all three phases:
    - pre_visit: tasks to complete before the appointment
    - during_visit: protocol items and HCC gap capture tasks at the visit
    - post_visit: billing, coding, and follow-up tasks after the visit

    The checklist is auto-generated from protocol defaults plus per-patient HCC
    gaps when the schedule is created. It is re-generated on first access if
    no items are found.

    Response includes overall completion_pct across all phases.
    """
    _get_or_404(awv_id)
    try:
        return svc.get_checklist(awv_id)
    except Exception as exc:
        logger.exception("get_checklist error awv_id=%s: %s", awv_id, exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


# ---------------------------------------------------------------------------
# PUT /api/awv/{id}/checklist/{item_id}
# ---------------------------------------------------------------------------

@router.put(
    "/{awv_id}/checklist/{item_id}",
    summary="Mark a checklist item complete or incomplete",
    response_model=AWVChecklistItemResponse,
    response_model_exclude_none=True,
)
def mark_checklist_item(
    awv_id: int = Path(..., description="AWV schedule ID"),
    item_id: int = Path(..., description="Checklist item ID"),
    body: dict[str, Any] = Body(
        ...,
        example={"completed": True},
    ),
    current_user: dict = Depends(get_current_user),
    _perm: None = Depends(require_permission("patients", "write")),
) -> dict[str, Any]:
    """
    Toggle the completed state of a single checklist item.

    Required body fields:
    - completed (bool): true to mark complete, false to revert to pending

    When completed=true, completed_by is set to the calling user's ID and
    completed_at is set to the current UTC timestamp.
    """
    _get_or_404(awv_id)
    completed = body.get("completed")
    if completed is None:
        raise HTTPException(status_code=422, detail="completed (bool) is required")
    try:
        result = svc.mark_checklist_item(
            awv_id=awv_id,
            item_id=item_id,
            completed=bool(completed),
            completed_by=current_user.get("id"),
        )
    except Exception as exc:
        logger.exception("mark_checklist_item error awv_id=%s item_id=%s: %s", awv_id, item_id, exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")

    if result is None:
        raise HTTPException(
            status_code=404,
            detail=f"Checklist item {item_id} not found for AWV schedule {awv_id}",
        )
    return result
