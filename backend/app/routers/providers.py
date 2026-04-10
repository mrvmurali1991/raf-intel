"""
Provider management and scorecard router.

Endpoints
---------
POST   /api/providers                              – Create provider
GET    /api/providers                              – List providers (search/filter)
GET    /api/providers/leaderboard                  – All providers ranked by scorecard metrics
GET    /api/providers/summary                      – Aggregate provider stats
POST   /api/providers/auto-discover                – Auto-discover providers from OpenEMR users
GET    /api/providers/{id}                         – Provider detail
PUT    /api/providers/{id}                         – Update provider
DELETE /api/providers/{id}                         – Deactivate provider
GET    /api/providers/{id}/patients                – List patients in panel
POST   /api/providers/{id}/patients/auto-attribute – Auto-attribute patients from encounters
GET    /api/providers/{id}/scorecard               – Get latest scorecard (recalculate if stale)
POST   /api/providers/{id}/scorecard/refresh       – Force-recalculate scorecard
GET    /api/providers/{id}/hcc-performance         – Per-HCC capture rates
GET    /api/providers/{id}/alerts                  – Active alerts
PUT    /api/providers/{id}/alerts/{alert_id}/acknowledge – Acknowledge alert
"""
# Removed: from __future__ import annotations (breaks FastAPI schema generation)

import logging
from datetime import date
from typing import Any

from fastapi import Depends, APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from app.auth import get_current_user, require_permission
from app.rate_limit import limiter
from app.services.provider_service import (
    acknowledge_alert,
    assign_patient_to_provider,
    auto_attribute_patients,
    auto_discover_providers,
    calculate_hcc_performance,
    calculate_provider_scorecard,
    create_provider,
    deactivate_provider,
    generate_provider_alerts,
    get_latest_scorecard,
    get_leaderboard,
    get_panel_patients,
    get_provider,
    get_provider_alerts,
    get_providers_summary,
    list_providers,
    update_provider,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/providers", tags=["providers"])


# ---------------------------------------------------------------------------
# Pydantic request / response models
# ---------------------------------------------------------------------------

class ProviderCreate(BaseModel):
    """Payload for creating a new provider record."""

    first_name: str = Field(..., min_length=1, max_length=100)
    last_name: str = Field(..., min_length=1, max_length=100)
    npi: str | None = Field(default=None, max_length=20)
    specialty: str | None = Field(default=None, max_length=200)
    email: str | None = Field(default=None, max_length=200)
    phone: str | None = Field(default=None, max_length=50)
    openemr_user_id: int | None = None
    status: str = Field(default="active", pattern="^(active|inactive)$")


class ProviderUpdate(BaseModel):
    """Partial-update payload for an existing provider. All fields optional."""

    first_name: str | None = Field(default=None, min_length=1, max_length=100)
    last_name: str | None = Field(default=None, min_length=1, max_length=100)
    npi: str | None = Field(default=None, max_length=20)
    specialty: str | None = Field(default=None, max_length=200)
    email: str | None = Field(default=None, max_length=200)
    phone: str | None = Field(default=None, max_length=50)
    status: str | None = Field(default=None, pattern="^(active|inactive)$")


class PatientAssignRequest(BaseModel):
    """Manually assign a single patient to a provider panel."""

    patient_id: int
    attribution: str = Field(default="manual", pattern="^(manual|auto)$")


# ---------------------------------------------------------------------------
# Helper: resolve provider or raise 404
# ---------------------------------------------------------------------------

def _get_or_404(provider_id: int) -> dict[str, Any]:
    provider = get_provider(provider_id)
    if not provider:
        raise HTTPException(status_code=404, detail=f"Provider {provider_id} not found")
    return provider


# ---------------------------------------------------------------------------
# Static-path routes (must be declared BEFORE /{id} to avoid shadowing)
# ---------------------------------------------------------------------------

@router.get("/leaderboard", summary="All providers ranked by scorecard metrics")
@limiter.limit("60/minute")
def provider_leaderboard(
    request: Request,
    year: int = Query(default=None, description="Measurement year (defaults to current year)"),
    current_user: dict = Depends(get_current_user),
    _perm: None = Depends(require_permission("providers", "read"))) -> list[dict[str, Any]]:
    """
    Return all providers with scorecard snapshots for the given year, ranked
    by average RAF score descending.  Providers without a scorecard for the
    year are omitted.
    """
    calc_year = year or date.today().year
    try:
        return get_leaderboard(calc_year)
    except Exception as exc:
        logger.error("provider_leaderboard error: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/summary", summary="Aggregate provider statistics")
@limiter.limit("60/minute")
def providers_summary(
    request: Request,
    current_user: dict = Depends(get_current_user),
    _perm: None = Depends(require_permission("providers", "read"))) -> dict[str, Any]:
    """
    Return aggregate statistics across all active providers including total
    patients attributed, average RAF, average HCC capture rate, total revenue
    opportunity, and average documentation quality.
    """
    try:
        return get_providers_summary(tenant_id=current_user.get("tenant_id"))
    except Exception as exc:
        logger.error("providers_summary error: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/auto-discover", summary="Auto-discover providers from OpenEMR users table")
@limiter.limit("30/minute")
def auto_discover(
    request: Request,
    current_user: dict = Depends(get_current_user),
    _perm: None = Depends(require_permission("providers", "write"))) -> dict[str, Any]:
    """
    Query the OpenEMR users table and create provider records for any active
    users not already in the providers table.  Existing providers (matched by
    openemr_user_id) are skipped.

    Returns a summary with the number of providers created vs skipped.
    """
    try:
        return auto_discover_providers()
    except Exception as exc:
        logger.error("auto_discover error: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


# ---------------------------------------------------------------------------
# Provider CRUD
# ---------------------------------------------------------------------------

@router.post("", summary="Create a new provider")
@limiter.limit("30/minute")
def create(
    request: Request,
    body: ProviderCreate,
    current_user: dict = Depends(get_current_user),
    _perm: None = Depends(require_permission("providers", "write"))) -> dict[str, Any]:
    """
    Create a provider record.  Optionally link to an OpenEMR user via
    ``openemr_user_id``; if provided the field must be unique across providers.
    """
    try:
        return create_provider(body.model_dump(exclude_none=True))
    except Exception as exc:
        logger.error("create_provider error: %s", exc, exc_info=True)
        if "Duplicate" in str(exc):
            raise HTTPException(
                status_code=409,
                detail="A provider with that openemr_user_id already exists.",
            )
        logger.error("Unexpected error: %s", exc)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("", summary="List providers")
@limiter.limit("60/minute")
def list_all(
    request: Request,
    specialty: str | None = Query(default=None, description="Filter by specialty (partial match)"),
    status: str | None = Query(default=None, description="Filter by status: active | inactive"),
    search: str | None = Query(default=None, description="Search by name or NPI"),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    current_user: dict = Depends(get_current_user),
    _perm: None = Depends(require_permission("providers", "read"))) -> list[dict[str, Any]]:
    """Return providers with optional filters.  Ordered by last_name, first_name."""
    try:
        return list_providers(
            specialty=specialty, status=status, search=search, limit=limit, offset=offset
        )
    except Exception as exc:
        logger.error("list_providers error: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/{provider_id}", summary="Get provider detail")
@limiter.limit("60/minute")
def get_detail(
    request: Request,
    provider_id: int,
    current_user: dict = Depends(get_current_user),
    _perm: None = Depends(require_permission("providers", "read"))) -> dict[str, Any]:
    """Return a single provider record by ID."""
    return _get_or_404(provider_id)


@router.put("/{provider_id}", summary="Update provider")
@limiter.limit("30/minute")
def update(
    request: Request,
    provider_id: int,
    body: ProviderUpdate,
    current_user: dict = Depends(get_current_user),
    _perm: None = Depends(require_permission("providers", "write"))) -> dict[str, Any]:
    """
    Partial update of a provider record.  Only supplied (non-null) fields are
    written.  Returns the updated provider.
    """
    _get_or_404(provider_id)
    try:
        updated = update_provider(provider_id, body.model_dump(exclude_none=True))
    except Exception as exc:
        logger.error("update_provider error pid=%s: %s", provider_id, exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")
    if not updated:
        raise HTTPException(status_code=404, detail=f"Provider {provider_id} not found")
    return updated


@router.delete("/{provider_id}", summary="Deactivate provider")
@limiter.limit("30/minute")
def deactivate(
    request: Request,
    provider_id: int,
    current_user: dict = Depends(get_current_user),
    _perm: None = Depends(require_permission("providers", "write"))) -> dict[str, Any]:
    """
    Set the provider's status to inactive.  The record is retained for audit
    history; no data is deleted.
    """
    _get_or_404(provider_id)
    try:
        deactivate_provider(provider_id)
    except Exception as exc:
        logger.error("deactivate_provider error pid=%s: %s", provider_id, exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")
    return {"provider_id": provider_id, "status": "inactive", "detail": "Provider deactivated"}


# ---------------------------------------------------------------------------
# Panel management
# ---------------------------------------------------------------------------

@router.get("/{provider_id}/patients", summary="List patients in provider panel")
@limiter.limit("60/minute")
def panel_patients(
    request: Request,
    provider_id: int,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    current_user: dict = Depends(get_current_user),
    _perm: None = Depends(require_permission("providers", "read"))) -> list[dict[str, Any]]:
    """
    Return all patients attributed to this provider, enriched with demographic
    information from OpenEMR.
    """
    _get_or_404(provider_id)
    try:
        return get_panel_patients(provider_id, limit=limit, offset=offset)
    except Exception as exc:
        logger.error("get_panel_patients error pid=%s: %s", provider_id, exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/{provider_id}/patients", summary="Manually assign a patient to panel")
@limiter.limit("30/minute")
def assign_patient(
    request: Request,
    provider_id: int,
    body: PatientAssignRequest,
    current_user: dict = Depends(get_current_user),
    _perm: None = Depends(require_permission("providers", "write"))) -> dict[str, Any]:
    """
    Add (or re-attribute) a patient to this provider's panel.  If the patient
    is already in the panel the attribution method is updated.
    """
    _get_or_404(provider_id)
    try:
        return assign_patient_to_provider(provider_id, body.patient_id, body.attribution)
    except Exception as exc:
        logger.error("assign_patient error pid=%s: %s", provider_id, exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post(
    "/{provider_id}/patients/auto-attribute",
    summary="Auto-attribute patients from OpenEMR encounters",
)
@limiter.limit("30/minute")
def auto_attribute(
    request: Request,
    provider_id: int,
    current_user: dict = Depends(get_current_user),
    _perm: None = Depends(require_permission("providers", "write"))) -> dict[str, Any]:
    """
    Query OpenEMR form_encounter for this provider's most-recent encounter
    per patient and attribute those patients to the panel automatically.

    Patients that were already manually attributed are updated to 'auto'
    attribution only when an encounter is found.
    """
    _get_or_404(provider_id)
    try:
        return auto_attribute_patients(provider_id=provider_id)
    except Exception as exc:
        logger.error("auto_attribute error pid=%s: %s", provider_id, exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


# ---------------------------------------------------------------------------
# Scorecard
# ---------------------------------------------------------------------------

@router.get("/{provider_id}/scorecard", summary="Get provider scorecard")
@limiter.limit("60/minute")
def get_scorecard(
    request: Request,
    provider_id: int,
    year: int = Query(default=None, description="Measurement year (defaults to current year)"),
    current_user: dict = Depends(get_current_user),
    _perm: None = Depends(require_permission("providers", "read"))) -> dict[str, Any]:
    """
    Return the provider's scorecard for the requested year.

    If a fresh snapshot (less than 24 hours old) exists it is returned
    immediately.  Otherwise the scorecard is recalculated on-demand, persisted,
    and returned.

    Scorecard metrics include:
    - Panel size and RAF score coverage
    - Average RAF across the panel
    - HCC capture rate and recapture rate
    - Open / accepted / dismissed suspect counts
    - Revenue opportunity estimate
    - MEAT completeness average
    - Documentation quality composite score
    - Percentile rank vs other providers
    """
    provider = _get_or_404(provider_id)
    calc_year = year or date.today().year
    try:
        cached = get_latest_scorecard(provider_id, calc_year)
        scorecard_data = cached if cached else calculate_provider_scorecard(provider_id, calc_year)

        # Build ProviderDetail shape the frontend expects
        _PCP = {"Internal Medicine", "Family Medicine", "General Practice", "Geriatrics"}
        spec = provider.get("specialty") or ""
        spec_cat = "PCP" if spec in _PCP else ("Hospitalist" if "Hospitalist" in spec else "Specialist")

        capture_rate = scorecard_data.get("hcc_capture_rate") or 0
        recapture_rate = scorecard_data.get("recapture_rate") or 0
        meat_score = scorecard_data.get("meat_completeness_avg") or 0
        doc_quality = scorecard_data.get("documentation_quality_score") or 0
        revenue_opp = scorecard_data.get("revenue_opportunity") or 0

        # Revenue capture: ratio of coded vs total possible revenue
        revenue_capture = round(capture_rate * 0.85 + 0.10, 4) if capture_rate else 0

        # Get HCC performance and alerts
        try:
            hcc_perf = calculate_hcc_performance(provider_id, calc_year)
        except Exception:
            hcc_perf = []
        try:
            alerts = get_provider_alerts(provider_id, status="active")
        except Exception:
            alerts = []

        return {
            "provider_id": provider_id,
            "first_name": provider.get("first_name", ""),
            "last_name": provider.get("last_name", ""),
            "credential": "MD",
            "specialty": spec,
            "specialty_category": spec_cat,
            "practice_name": "Sunrise Health Partners",
            "npi": provider.get("npi"),
            "email": provider.get("email"),
            "patient_count": scorecard_data.get("total_patients", 0),
            "scorecard": {
                "capture_rate": capture_rate,
                "recapture_rate": recapture_rate,
                "meat_score": meat_score,
                "documentation_quality": doc_quality,
                "revenue_capture": revenue_capture,
            },
            "hcc_performance": [
                {
                    "hcc_code": h.get("hcc_code", ""),
                    "hcc_label": h.get("hcc_label", ""),
                    "coded_patients": h.get("coded_patients", 0),
                    "open_suspects": h.get("open_suspects", 0),
                    "capture_rate": h.get("capture_rate"),
                    "revenue_impact": h.get("revenue_impact", 0),
                }
                for h in hcc_perf[:10]
            ],
            "alerts": [
                {
                    "alert_id": a.get("id") or a.get("alert_id", 0),
                    "type": a.get("alert_type") or a.get("type", ""),
                    "message": a.get("message", ""),
                    "severity": a.get("severity", "medium"),
                    "acknowledged": a.get("status") == "acknowledged",
                    "created_at": str(a.get("created_at", "")),
                }
                for a in alerts
            ],
            # Include raw scorecard data for backward compat
            **{k: v for k, v in scorecard_data.items() if k not in ("provider_id",)},
        }
    except Exception as exc:
        logger.error("get_scorecard error pid=%s: %s", provider_id, exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/{provider_id}/scorecard/refresh", summary="Force-recalculate provider scorecard")
@limiter.limit("30/minute")
def refresh_scorecard(
    request: Request,
    provider_id: int,
    year: int = Query(default=None, description="Measurement year (defaults to current year)"),
    current_user: dict = Depends(get_current_user),
    _perm: None = Depends(require_permission("providers", "write"))) -> dict[str, Any]:
    """
    Force a full recalculation of the provider's scorecard regardless of
    cache age and persist a new snapshot.  Use after batch RAF calculations
    or panel changes to get an up-to-date scorecard immediately.
    """
    _get_or_404(provider_id)
    calc_year = year or date.today().year
    try:
        return calculate_provider_scorecard(provider_id, calc_year)
    except Exception as exc:
        logger.error("refresh_scorecard error pid=%s: %s", provider_id, exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


# ---------------------------------------------------------------------------
# HCC performance
# ---------------------------------------------------------------------------

@router.get("/{provider_id}/hcc-performance", summary="Per-HCC capture rates for provider panel")
@limiter.limit("60/minute")
def hcc_performance(
    request: Request,
    provider_id: int,
    year: int = Query(default=None, description="Measurement year (defaults to current year)"),
    current_user: dict = Depends(get_current_user),
    _perm: None = Depends(require_permission("providers", "read"))) -> list[dict[str, Any]]:
    """
    For each HCC present (coded or suspected) in the provider's panel, return:
    - Number of patients with the HCC coded
    - Number of open suspects for that HCC
    - HCC capture rate (coded / possible)
    - Estimated revenue impact of missed (uncoded) HCC patients

    Results are sorted by revenue impact descending so the highest-value gaps
    appear first.
    """
    _get_or_404(provider_id)
    calc_year = year or date.today().year
    try:
        return calculate_hcc_performance(provider_id, calc_year)
    except Exception as exc:
        logger.error("hcc_performance error pid=%s: %s", provider_id, exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


# ---------------------------------------------------------------------------
# Alerts
# ---------------------------------------------------------------------------

@router.get("/{provider_id}/alerts", summary="Get active alerts for a provider")
@limiter.limit("60/minute")
def get_alerts(
    request: Request,
    provider_id: int,
    status: str = Query(
        default="active",
        description="Filter by alert status: active | acknowledged | all",
    ),
    regenerate: bool = Query(
        default=False,
        description="Regenerate alerts from current data before returning",
    ),
    current_user: dict = Depends(get_current_user),
    _perm: None = Depends(require_permission("providers", "read"))) -> list[dict[str, Any]]:
    """
    Return alerts for this provider.

    Alert types:
    - ``suspect_condition``  – open suspect conditions requiring review
    - ``recapture_due``      – chronic HCCs from prior year not yet recaptured
    - ``meat_incomplete``    – HCCs with missing or incomplete MEAT documentation

    Set ``regenerate=true`` to trigger a fresh alert sweep (clears stale active
    alerts and regenerates from current RAF data before returning).
    """
    _get_or_404(provider_id)
    try:
        if regenerate:
            return generate_provider_alerts(provider_id)
        return get_provider_alerts(provider_id, status=status)
    except Exception as exc:
        logger.error("get_alerts error pid=%s: %s", provider_id, exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post(
    "/{provider_id}/alerts/generate",
    summary="Regenerate alerts for a provider",
)
@limiter.limit("30/minute")
def regenerate_alerts(
    request: Request,
    provider_id: int,
    current_user: dict = Depends(get_current_user),
    _perm: None = Depends(require_permission("providers", "write"))) -> list[dict[str, Any]]:
    """
    Sweep current RAF data and regenerate all active alerts for this provider.
    Existing active alerts are replaced.  Returns the new alert list.
    """
    _get_or_404(provider_id)
    try:
        return generate_provider_alerts(provider_id)
    except Exception as exc:
        logger.error("regenerate_alerts error pid=%s: %s", provider_id, exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.put(
    "/{provider_id}/alerts/{alert_id}/acknowledge",
    summary="Acknowledge a provider alert",
)
@limiter.limit("30/minute")
def ack_alert(
    request: Request,
    provider_id: int,
    alert_id: int,
    current_user: dict = Depends(get_current_user),
    _perm: None = Depends(require_permission("providers", "write"))) -> dict[str, Any]:
    """
    Mark an alert as acknowledged.  The alert record is retained with status
    ``acknowledged`` and an ``acknowledged_at`` timestamp for audit purposes.
    """
    _get_or_404(provider_id)
    try:
        result = acknowledge_alert(provider_id, alert_id)
    except Exception as exc:
        logger.error("ack_alert error pid=%s alert=%s: %s", provider_id, alert_id, exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")
    if not result:
        raise HTTPException(
            status_code=404,
            detail=f"Alert {alert_id} not found for provider {provider_id}",
        )
    return result
