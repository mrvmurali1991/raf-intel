"""
HEDIS Quality Measure and Value-Based Care analytics router.

Endpoints
---------
GET /api/quality/measures              – List all tracked HEDIS measures
GET /api/quality/measures/{code}       – Measure detail with population stats
GET /api/quality/patients/{pid}        – All measures for a single patient
GET /api/quality/gaps                  – Patients with open care gaps
GET /api/quality/summary               – Population quality dashboard
GET /api/quality/stars-estimate        – Estimated CMS STARS rating
GET /api/quality/overlap               – RAF/HEDIS HCC overlap analysis
"""
# Removed: from __future__ import annotations (breaks FastAPI schema generation)

import logging
from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from app.auth import get_current_user, require_permission
from app.services.quality_service import (
    HEDIS_MEASURES,
    evaluate_measure,
    get_care_gaps,
    get_patient_measures,
    get_quality_summary,
    get_raf_hedis_overlap,
    estimate_stars_rating,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/quality", tags=["quality"])

# _CURRENT_YEAR removed — use date.today().year inline at each call site
# so the value is always current rather than frozen at import time.


# ---------------------------------------------------------------------------
# GET /measures
# ---------------------------------------------------------------------------

@router.get(
    "/measures",
    summary="List all tracked HEDIS measures",
)
def list_measures(
    current_user: dict = Depends(get_current_user),
    _perm: None = Depends(require_permission("reports", "read")),
) -> list[dict[str, Any]]:
    """
    Return the full catalog of HEDIS measures tracked by this system,
    including HCC overlap codes, measure components, and STARS weights.
    """
    return [
        {
            "code": m["code"],
            "name": m["name"],
            "description": m["description"],
            "hcc_overlap": m["hcc_overlap"],
            "hcc_labels": m["hcc_labels"],
            "components": m["components"],
            "stars_weight": m["stars_weight"],
        }
        for m in HEDIS_MEASURES.values()
    ]


# ---------------------------------------------------------------------------
# GET /measures/{code}
# ---------------------------------------------------------------------------

@router.get(
    "/measures/{code}",
    summary="Measure detail with population compliance stats",
)
def measure_detail(
    code: str,
    year: int = Query(default=None, description="Measurement year (defaults to current year)"),
    current_user: dict = Depends(get_current_user),
    _perm: None = Depends(require_permission("reports", "read")),
) -> dict[str, Any]:
    """
    Return measure metadata plus population-level compliance statistics
    (eligible patients, met count, compliance rate) for the given year.
    """
    code = code.upper()
    measure = HEDIS_MEASURES.get(code)
    if not measure:
        raise HTTPException(status_code=404, detail=f"Unknown measure code: {code}")

    calc_year = year or date.today().year

    try:
        summary = get_quality_summary(calc_year)
    except Exception as exc:
        logger.error("measure_detail summary error [%s]: %s", code, exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")

    measure_stats = summary.get("measures", {}).get(code, {})

    return {
        "code": measure["code"],
        "name": measure["name"],
        "description": measure["description"],
        "hcc_overlap": measure["hcc_overlap"],
        "hcc_labels": measure["hcc_labels"],
        "components": measure["components"],
        "stars_weight": measure["stars_weight"],
        "year": calc_year,
        "population_stats": {
            "eligible_count": measure_stats.get("eligible_count", 0),
            "met_count": measure_stats.get("met_count", 0),
            "gap_count": measure_stats.get("gap_count", 0),
            "compliance_rate": measure_stats.get("compliance_rate"),
        },
    }


# ---------------------------------------------------------------------------
# GET /patients/{pid}
# ---------------------------------------------------------------------------

@router.get(
    "/patients/{pid}",
    summary="All HEDIS measures for a single patient",
)
def patient_measures(
    pid: int,
    year: int = Query(default=None, description="Measurement year (defaults to current year)"),
    current_user: dict = Depends(get_current_user),
    _perm: None = Depends(require_permission("patients", "read")),
) -> dict[str, Any]:
    """
    Return met/unmet status for every tracked HEDIS measure for the specified
    patient.  Only measures where the patient is in the denominator are
    evaluated; ineligible measures are still listed with denominator=false.

    Includes per-component evidence and the first open gap description
    for each unmet measure.
    """
    calc_year = year or date.today().year

    try:
        result = get_patient_measures(pid, calc_year)
    except Exception as exc:
        logger.error("patient_measures error [pid=%s]: %s", pid, exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")

    # Detect a patient-not-found error from the service response safely
    try:
        measures = result.get("measures") or {}
        first_key = next(iter(measures))
        patient_not_found = "error" in measures[first_key]
    except StopIteration:
        patient_not_found = False
    if patient_not_found:
        raise HTTPException(status_code=404, detail=f"Patient {pid} not found")

    return result


# ---------------------------------------------------------------------------
# GET /gaps
# ---------------------------------------------------------------------------

@router.get(
    "/gaps",
    summary="Patients with open HEDIS care gaps",
)
def care_gaps(
    year: int = Query(default=None, description="Measurement year (defaults to current year)"),
    measure: str = Query(default=None, description="Filter to a specific measure code (e.g. CDC, CBP)"),
    limit: int = Query(default=200, ge=1, le=1000, description="Maximum number of patients to scan"),
    current_user: dict = Depends(get_current_user),
    _perm: None = Depends(require_permission("reports", "read")),
) -> dict[str, Any]:
    """
    Return all patients that are eligible for a measure but have not yet met
    the numerator criteria — i.e., patients with open care gaps.

    Results include the specific gap description and the associated HCC codes,
    enabling care coordinators to prioritize outreach and close both the quality
    gap and any corresponding RAF recapture opportunity in a single visit.

    Use the ``measure`` parameter to filter to a single HEDIS measure.
    """
    calc_year = year or date.today().year

    if measure:
        measure = measure.upper()
        if measure not in HEDIS_MEASURES:
            raise HTTPException(
                status_code=400,
                detail=f"Unknown measure code: {measure}. Valid codes: {', '.join(HEDIS_MEASURES.keys())}",
            )

    try:
        gaps = get_care_gaps(calc_year, measure, limit=limit)
    except ValueError as exc:
        logger.error("Unexpected error: %s", exc)
        raise HTTPException(status_code=400, detail="Bad request")
    except Exception as exc:
        logger.error("care_gaps error: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")

    # Aggregate gap counts per measure for the summary header
    measure_gap_counts: dict[str, int] = {}
    for g in gaps:
        mc = g["measure_code"]
        measure_gap_counts[mc] = measure_gap_counts.get(mc, 0) + 1

    return {
        "year": calc_year,
        "measure_filter": measure,
        "total_gaps": len(gaps),
        "patients_with_gaps": len({g["patient_id"] for g in gaps}),
        "gaps_by_measure": measure_gap_counts,
        "gaps": gaps,
    }


# ---------------------------------------------------------------------------
# GET /summary
# ---------------------------------------------------------------------------

@router.get(
    "/summary",
    summary="Population quality dashboard",
)
def quality_summary(
    year: int = Query(default=None, description="Measurement year (defaults to current year)"),
    current_user: dict = Depends(get_current_user),
    _perm: None = Depends(require_permission("reports", "read")),
) -> dict[str, Any]:
    """
    Population-level HEDIS compliance dashboard.

    Returns eligible patient counts, met counts, gap counts, and compliance
    rates for every tracked measure.  Includes the overall mean compliance
    rate across all measures with eligible patients.

    This endpoint may take several seconds to respond on large populations
    because it evaluates every patient against every applicable measure.
    """
    calc_year = year or date.today().year

    try:
        summary = get_quality_summary(calc_year)
    except Exception as exc:
        logger.error("quality_summary error: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")

    return summary


# ---------------------------------------------------------------------------
# GET /stars-estimate
# ---------------------------------------------------------------------------

@router.get(
    "/stars-estimate",
    summary="Estimated CMS STARS rating",
)
def stars_estimate(
    year: int = Query(default=None, description="Measurement year (defaults to current year)"),
    current_user: dict = Depends(get_current_user),
    _perm: None = Depends(require_permission("reports", "read")),
) -> dict[str, Any]:
    """
    Estimate the plan's CMS STARS rating based on HEDIS measure performance.

    Maps each measure's compliance rate to a 1-5 star score using approximate
    CMS cut-point benchmarks, then computes a weighted average overall STARS
    estimate.

    IMPORTANT: This is an analytical estimate only.  Actual CMS STARS ratings
    are computed by CMS using HEDIS hybrid/administrative methodology with
    official denominator/numerator specifications.  This estimate is for
    internal performance tracking and improvement planning only.
    """
    calc_year = year or date.today().year

    try:
        result = estimate_stars_rating(calc_year)
    except Exception as exc:
        logger.error("stars_estimate error: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")

    return result


# ---------------------------------------------------------------------------
# GET /overlap
# ---------------------------------------------------------------------------

@router.get(
    "/overlap",
    summary="RAF/HEDIS HCC overlap analysis",
)
def raf_hedis_overlap(
    current_user: dict = Depends(get_current_user),
    _perm: None = Depends(require_permission("reports", "read")),
) -> dict[str, Any]:
    """
    Identify which HCC conditions have associated HEDIS quality measures,
    enabling value-based care strategies that close RAF recapture gaps and
    HEDIS quality gaps simultaneously in a single patient encounter.

    Returns a mapping of HCC code -> list of associated HEDIS measures with
    their components, plus a synergy note explaining the combined opportunity.
    This is the foundation for combined RAF + quality outreach workflows.
    """
    try:
        overlap = get_raf_hedis_overlap()
    except Exception as exc:
        logger.error("raf_hedis_overlap error: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")

    return {
        "total_hcc_codes_with_quality_measures": len(overlap),
        "tracked_measures": len(HEDIS_MEASURES),
        "overlap": overlap,
        "value_based_care_note": (
            "Patients with these HCC conditions are simultaneously eligible for HEDIS quality "
            "measures. Scheduling a comprehensive annual wellness visit for these patients can "
            "close RAF recapture gaps, HEDIS care gaps, and generate revenue — all in one visit."
        ),
    }
