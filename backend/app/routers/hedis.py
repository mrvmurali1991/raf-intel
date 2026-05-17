"""HEDIS / Star Ratings + Health Equity Index (HEI) router.

Endpoints
---------
GET /api/hedis/measures                           List available measures + metadata
GET /api/hedis/scores                             Tenant-wide rate per measure
GET /api/hedis/scores/by-segment                  Rates broken down by HEI segment
GET /api/hedis/patients-failing/{measure_id}      Gap list — denominator AND NOT numerator

All endpoints require JWT auth and the "reports" resource permission.
Each call to the gap list emits a ``HEDIS_GAP_LIST_VIEWED`` PHI audit record.
"""
# Do NOT use `from __future__ import annotations` — breaks FastAPI schemas.

import logging
from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Path, Query

from app.auth import get_current_user, get_tenant_id, require_permission
from app.db import raf_cursor
from app.services.audit_logger import log_phi_access
from app.services.hedis import (
    MEASURES,
    NCQA_STAR_CUTOFFS,
    get_measure,
    list_measures,
)
from app.services.hedis.measures import stars_for_rate
from app.services.hei import SEGMENTS, classify_patients_bulk

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/hedis", tags=["hedis"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _measurement_year(year: int | None) -> int:
    return year or date.today().year


def _load_tenant_patients(tenant_id: int) -> list[dict[str, Any]]:
    """Return minimal patient roster for the tenant (id, dob, sex)."""
    with raf_cursor() as cur:
        cur.execute(
            "SELECT id, dob, sex FROM patients "
            "WHERE tenant_id = %s AND is_active = 1",
            (tenant_id,),
        )
        return list(cur.fetchall() or [])


# ---------------------------------------------------------------------------
# GET /measures
# ---------------------------------------------------------------------------

@router.get(
    "/measures",
    summary="List HEDIS measures supported by this MVP",
)
def list_hedis_measures(
    year: int = Query(None, description="Measurement year (defaults to current)"),
    current_user: dict = Depends(get_current_user),
    _perm: None = Depends(require_permission("reports", "read")),
) -> dict[str, Any]:
    """Return the measure catalog plus the NCQA Star cut-points used."""
    return {
        "measurement_year": _measurement_year(year),
        "measures": list_measures(),
        "star_cutoffs": NCQA_STAR_CUTOFFS,
        "licensing_notice": (
            "HEDIS measure specifications are copyright NCQA. Production use "
            "requires an NCQA license — see https://www.ncqa.org/hedis/measures/"
        ),
    }


# ---------------------------------------------------------------------------
# GET /scores
# ---------------------------------------------------------------------------

@router.get(
    "/scores",
    summary="Tenant-wide rate per HEDIS measure",
)
def hedis_scores(
    year: int = Query(None, description="Measurement year (defaults to current)"),
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
    _perm: None = Depends(require_permission("reports", "read")),
) -> dict[str, Any]:
    """Compute tenant-wide HEDIS rates for every implemented measure."""
    yr = _measurement_year(year)
    tid = int(tenant_id)
    patients = _load_tenant_patients(tid)

    out_measures: list[dict[str, Any]] = []
    for mid, measure in MEASURES.items():
        denom = 0
        num = 0
        # FUM has a secondary 7-day sub-rate alongside the 30-day primary
        sub_num: dict[str, int] = {}
        for p in patients:
            result = measure.compute(int(p["id"]), yr, tenant_id=tid)
            if not result["in_denominator"]:
                continue
            denom += 1
            if result["met"]:
                num += 1
            for sub_key, sub_val in (result.get("sub_results") or {}).items():
                if sub_val:
                    sub_num[sub_key] = sub_num.get(sub_key, 0) + 1
        rate_pct = (100.0 * num / denom) if denom else 0.0
        entry: dict[str, Any] = {
            "measure_id": mid,
            "name": measure.name,
            "denominator": denom,
            "numerator": num,
            "rate_pct": round(rate_pct, 2),
            "stars": stars_for_rate(mid, rate_pct),
            "star_cutoffs_pct": NCQA_STAR_CUTOFFS.get(mid, []),
        }
        if sub_num:
            entry["sub_rates"] = {
                k: {
                    "numerator": v,
                    "rate_pct": round(100.0 * v / denom, 2) if denom else 0.0,
                    "stars": stars_for_rate(k, (100.0 * v / denom) if denom else 0.0),
                }
                for k, v in sub_num.items()
            }
        out_measures.append(entry)

    return {
        "measurement_year": yr,
        "tenant_id": tid,
        "patient_population": len(patients),
        "measures": out_measures,
    }


# ---------------------------------------------------------------------------
# GET /scores/by-segment
# ---------------------------------------------------------------------------

@router.get(
    "/scores/by-segment",
    summary="HEDIS rates broken down by CMS Health Equity Index segment",
)
def hedis_scores_by_segment(
    year: int = Query(None, description="Measurement year (defaults to current)"),
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
    _perm: None = Depends(require_permission("reports", "read")),
) -> dict[str, Any]:
    """Compute HEDIS rates separately for dual / LIS / disability / other."""
    yr = _measurement_year(year)
    tid = int(tenant_id)
    patients = _load_tenant_patients(tid)
    pids = [int(p["id"]) for p in patients]
    segment_map = classify_patients_bulk(pids, tenant_id=tid)

    # Initialize counters: measures[mid][segment] = {denom, num}
    counters: dict[str, dict[str, dict[str, int]]] = {
        mid: {seg: {"denominator": 0, "numerator": 0} for seg in SEGMENTS}
        for mid in MEASURES
    }
    seg_population = {seg: 0 for seg in SEGMENTS}
    for p in patients:
        pid = int(p["id"])
        seg = segment_map.get(pid, "other")
        seg_population[seg] += 1
        for mid, measure in MEASURES.items():
            r = measure.compute(pid, yr, tenant_id=tid)
            if not r["in_denominator"]:
                continue
            counters[mid][seg]["denominator"] += 1
            if r["met"]:
                counters[mid][seg]["numerator"] += 1

    out: list[dict[str, Any]] = []
    for mid, measure in MEASURES.items():
        per_seg = []
        for seg in SEGMENTS:
            d = counters[mid][seg]["denominator"]
            n = counters[mid][seg]["numerator"]
            rate_pct = (100.0 * n / d) if d else 0.0
            per_seg.append(
                {
                    "segment": seg,
                    "denominator": d,
                    "numerator": n,
                    "rate_pct": round(rate_pct, 2),
                    "stars": stars_for_rate(mid, rate_pct),
                }
            )
        # Disparity gap = best - worst rate across segments with N>0
        rates = [r["rate_pct"] for r in per_seg if r["denominator"] > 0]
        disparity = round(max(rates) - min(rates), 2) if len(rates) >= 2 else 0.0
        out.append(
            {
                "measure_id": mid,
                "name": measure.name,
                "by_segment": per_seg,
                "disparity_gap_pct": disparity,
            }
        )

    return {
        "measurement_year": yr,
        "tenant_id": tid,
        "segment_population": seg_population,
        "measures": out,
        "segments": list(SEGMENTS),
    }


# ---------------------------------------------------------------------------
# GET /patients-failing/{measure_id}
# ---------------------------------------------------------------------------

@router.get(
    "/patients-failing/{measure_id}",
    summary="List patients in denominator but NOT in numerator (gap list)",
)
def patients_failing(
    measure_id: str = Path(..., description="HEDIS measure id, e.g. BCS"),
    year: int = Query(None, description="Measurement year"),
    limit: int = Query(200, ge=1, le=2000),
    offset: int = Query(0, ge=0),
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
    _perm: None = Depends(require_permission("reports", "read")),
) -> dict[str, Any]:
    """Return the gap-list for *measure_id*: patients in denom but not num."""
    yr = _measurement_year(year)
    tid = int(tenant_id)
    measure = get_measure(measure_id)
    if not measure:
        raise HTTPException(status_code=404, detail=f"unknown measure: {measure_id}")

    # Emit PHI audit record — this endpoint returns a list of patient IDs.
    log_phi_access(
        action="HEDIS_GAP_LIST_VIEWED",
        resource="hedis_measure",
        patient_id=None,
        user=str(current_user.get("email") or current_user.get("id") or "system"),
        details=f"measure_id={measure.measure_id} year={yr}",
        tenant_id=tid,
    )

    with raf_cursor() as cur:
        cur.execute(
            "SELECT id, first_name, last_name, dob, sex FROM patients "
            "WHERE tenant_id = %s AND is_active = 1",
            (tid,),
        )
        roster = list(cur.fetchall() or [])

    segments = classify_patients_bulk([int(p["id"]) for p in roster], tenant_id=tid)
    gap_rows: list[dict[str, Any]] = []
    for p in roster:
        pid = int(p["id"])
        r = measure.compute(pid, yr, tenant_id=tid)
        if r["in_denominator"] and not r["met"]:
            gap_rows.append(
                {
                    "patient_id": pid,
                    "first_name": p.get("first_name"),
                    "last_name": p.get("last_name"),
                    "dob": str(p.get("dob")) if p.get("dob") else None,
                    "sex": p.get("sex"),
                    "hei_segment": segments.get(pid, "other"),
                    "evidence": r["evidence"],
                    "exclusions": r["exclusions"],
                }
            )

    total = len(gap_rows)
    page = gap_rows[offset : offset + limit]
    return {
        "measure_id": measure.measure_id,
        "measurement_year": yr,
        "tenant_id": tid,
        "total": total,
        "limit": limit,
        "offset": offset,
        "patients": page,
    }


# ---------------------------------------------------------------------------
# GET /patient/{patient_id}/gaps
# ---------------------------------------------------------------------------

@router.get(
    "/patient/{patient_id}/gaps",
    summary="Open HEDIS gaps for a single patient (co-located with HCC suspects)",
)
def patient_gaps(
    patient_id: int = Path(..., description="Patient primary key"),
    year: int = Query(None, description="Measurement year (defaults to current)"),
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
    _perm: None = Depends(require_permission("reports", "read")),
) -> dict[str, Any]:
    """Return all HEDIS measures where *patient_id* is in the denominator but
    NOT in the numerator (i.e. the gap is open).  Designed for inline display
    alongside HCC suspects on the patient-detail page so a PCP sees co-located
    HCC + HEDIS gaps during a single visit.
    """
    yr = _measurement_year(year)
    tid = int(tenant_id)

    # Verify patient belongs to this tenant
    with raf_cursor() as cur:
        cur.execute(
            "SELECT id, first_name, last_name, dob, sex FROM patients "
            "WHERE id = %s AND tenant_id = %s AND is_active = 1",
            (patient_id, tid),
        )
        patient_row = cur.fetchone()

    if not patient_row:
        raise HTTPException(status_code=404, detail="Patient not found")

    log_phi_access(
        action="HEDIS_PATIENT_GAPS_VIEWED",
        resource="hedis_patient_gaps",
        patient_id=patient_id,
        user=str(current_user.get("email") or current_user.get("id") or "system"),
        details=f"patient_id={patient_id} year={yr}",
        tenant_id=tid,
    )

    open_gaps: list[dict[str, Any]] = []
    for mid, measure in MEASURES.items():
        try:
            result = measure.compute(patient_id, yr, tenant_id=tid)
        except Exception:
            logger.exception("HEDIS compute failed for measure %s patient %s", mid, patient_id)
            continue

        if not result["in_denominator"]:
            continue

        # Build a human-readable "last value" from evidence when available
        evidence_list = result.get("evidence") or []
        last_value: str | None = None
        due_date: str | None = None
        if evidence_list:
            ev = evidence_list[-1] if isinstance(evidence_list, list) else None
            if ev and isinstance(ev, dict):
                last_value = ev.get("value") or ev.get("result") or ev.get("date")
                due_date = ev.get("due_date") or ev.get("next_due")

        if not result["met"]:
            open_gaps.append(
                {
                    "measure_id": mid,
                    "name": measure.name,
                    "status": "open",
                    "last_value": last_value,
                    "due_date": due_date,
                    "evidence": evidence_list,
                    "exclusions": result.get("exclusions") or [],
                }
            )
        else:
            open_gaps.append(
                {
                    "measure_id": mid,
                    "name": measure.name,
                    "status": "met",
                    "last_value": last_value,
                    "due_date": due_date,
                    "evidence": evidence_list,
                    "exclusions": result.get("exclusions") or [],
                }
            )

    return {
        "patient_id": patient_id,
        "measurement_year": yr,
        "open_gaps": [g for g in open_gaps if g["status"] == "open"],
        "all_gaps": open_gaps,
    }
