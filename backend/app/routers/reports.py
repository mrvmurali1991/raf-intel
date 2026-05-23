"""
Reporting and analytics router.

Endpoints
---------
GET /api/reports/revenue-opportunity   – Population-level RAF gap and revenue estimate
GET /api/reports/patient-scorecard     – Per-patient billing vs AI RAF comparison
GET /api/reports/hcc-distribution      – HCC code frequency across population
GET /api/reports/suspects-summary      – All open suspect conditions across all patients
GET /api/reports/recapture-gaps        – Active problems not billed in the current year
GET /api/reports/data-completeness     – Data quality metrics across the patient population
GET /api/reports/workflow-summary      – Dashboard workflow queue counts from the database
"""
# Removed: from __future__ import annotations (breaks FastAPI schema generation)

import logging
from collections import Counter
from datetime import date, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict

from app.auth import get_current_user, get_tenant_id, require_permission
from app.cache import cache_get, cache_set
from app.config import settings
from app.db import NoActiveEMRConnection, openemr_cursor, raf_cursor
from app.services.cache_strategy import (
    get_active_connection_id as _active_connection_id,
)
from app.services.emr_manager import active_patients_subquery
from app.services.metrics_service import revenue_at_risk as _canonical_revenue_at_risk

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/reports", tags=["reports"])


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------


class _ReportBase(BaseModel):
    """Base for report response models — allows extra fields so complex reports
    don't get silently stripped by FastAPI's response serialization."""

    model_config = ConfigDict(extra="allow")


class RevenueOpportunityResponse(_ReportBase):
    measurement_year: int
    total_patients_analyzed: int
    total_billing_raf: float
    total_ai_raf: float
    total_gap: float
    estimated_annual_revenue: float
    average_raf_score: float


class PatientScorecardResponse(_ReportBase):
    year: int
    patients: list[dict[str, Any]]


class HccDistributionResponse(_ReportBase):
    year: int
    distribution: list[dict[str, Any]]


class SuspectsSummaryResponse(_ReportBase):
    year: int
    total: int
    suspects: list[dict[str, Any]]


class RecaptureGapsReportResponse(_ReportBase):
    year: int
    total: int
    gaps: list[dict[str, Any]]


class DataCompletenessResponse(_ReportBase):
    total_patients: int
    completeness_score: float


class WorkflowSummaryResponse(_ReportBase):
    open_suspects: int
    open_recapture_gaps: int = 0
    patients_unanalyzed: int = 0
    patients_total: int = 0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _calculate_age(dob: Any, as_of_year: int | None = None) -> int:
    """Return integer age as of Feb 1 of the measurement year."""
    if dob is None:
        return 0
    if isinstance(dob, str):
        try:
            dob = datetime.strptime(dob[:10], "%Y-%m-%d").date()
        except ValueError:
            return 0
    elif isinstance(dob, datetime):
        dob = dob.date()
    ref = date(as_of_year or date.today().year, 2, 1)
    age = ref.year - dob.year - ((ref.month, ref.day) < (dob.month, dob.day))
    return max(0, age)


# ---------------------------------------------------------------------------
# GET /revenue-opportunity
# ---------------------------------------------------------------------------

@router.get("/revenue-opportunity", summary="Population-level RAF gap and revenue opportunity", response_model=RevenueOpportunityResponse)
def revenue_opportunity(year: int = Query(default=None),
    payment_year: int = Query(default=None, description="CMS payment year for Revenue-at-Risk (retroactive close periods). Defaults to measurement year."),
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
    _perm: None = Depends(require_permission("reports", "read"))) -> RevenueOpportunityResponse:
    """
    Aggregate comparison of billing RAF scores vs AI-detected RAF scores.

    Returns total patients analyzed, the RAF gap between what was billed and
    what the AI found, and an estimated annual revenue opportunity based on
    the CMS per-member rate of $11,015.04 per RAF point (2026 rate).

    Pass payment_year to scope Revenue-at-Risk to a retroactive CMS payment
    year (e.g. PY2024 for retrospective close period reconciliation).
    """
    calc_year = year or date.today().year
    rar_year = payment_year or calc_year

    # --- cache check ---
    _acid = _active_connection_id(tenant_id)
    _cache_key = f"report:revenue:{calc_year}:{rar_year}:{tenant_id}:{_acid}"
    _cached = cache_get(_cache_key)
    if _cached is not None:
        return _cached

    try:
        # Count distinct patients that have been through AI analysis — active connections only.
        # When no EMR is active, scope to uploaded patients instead.
        with raf_cursor() as cur:
            cur.execute(
                """
                SELECT COUNT(DISTINCT ea.pid) AS cnt
                FROM raf_encounter_analysis ea
                WHERE ea.pid IN (SELECT id FROM patients WHERE is_active = 1 AND tenant_id = %s)
                """,
                (tenant_id,),
            )
            row = cur.fetchone()
            total_patients_analyzed = int(row["cnt"]) if row else 0

            # Fall back to raf_scores count if no AI analysis yet
            if total_patients_analyzed == 0:
                cur.execute(
                    """
                    SELECT COUNT(DISTINCT patient_id) AS cnt
                    FROM raf_scores
                    WHERE measurement_year = %s
                      AND patient_id IN (SELECT id FROM patients WHERE is_active = 1 AND tenant_id = %s)
                    """,
                    (calc_year, tenant_id),
                )
                row = cur.fetchone()
                total_patients_analyzed = int(row["cnt"]) if row else 0

        # Sum billing RAF — one prospective score per patient for the year,
        # restricted to patients from active EMR connections.
        # score_type='prospective' is the canonical coded billing RAF;
        # v28/v24 are model-comparison scores and must not be used here.
        # Latest billing RAF per patient regardless of model variant
        # (v24/v28/prospective), matching patient-scorecard semantics.
        with raf_cursor() as cur:
            cur.execute(
                """
                SELECT rs.patient_id, rs.final_raf
                FROM raf_scores rs
                INNER JOIN (
                    SELECT patient_id, MAX(calculated_at) AS max_calc
                    FROM raf_scores
                    WHERE measurement_year = %s
                    GROUP BY patient_id
                ) latest
                  ON latest.patient_id = rs.patient_id
                 AND latest.max_calc   = rs.calculated_at
                WHERE rs.measurement_year = %s
                  AND rs.patient_id IN (SELECT id FROM patients WHERE is_active = 1 AND tenant_id = %s)
                """,
                (calc_year, calc_year, tenant_id),
            )
            billing_rows = cur.fetchall()

        # Sum AI RAF — latest overall_score per patient from raf_encounter_analysis,
        # restricted to active patients (works for both EMR and uploaded patients).
        with raf_cursor() as cur:
            cur.execute(
                """
                SELECT pid, overall_score
                FROM raf_encounter_analysis
                WHERE overall_score IS NOT NULL
                  AND YEAR(analyzed_at) = %s
                  AND pid IN (SELECT id FROM patients WHERE is_active = 1 AND tenant_id = %s)
                ORDER BY pid, encounter_id DESC
                """,
                (calc_year, tenant_id),
            )
            ai_rows = cur.fetchall()

    except Exception as exc:
        logger.error("revenue_opportunity db error: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")

    # Aggregate billing RAF per patient
    billing_by_pid: dict[int, float] = {}
    for row in billing_rows:
        pid = int(row["patient_id"])
        if pid not in billing_by_pid:
            billing_by_pid[pid] = float(row["final_raf"])

    # Aggregate AI RAF per patient — take the most recent overall_score per patient.
    # The query is ordered by (pid, encounter_id DESC) so the first row per pid is
    # the latest encounter's AI estimate. Using the max would inflate the total by
    # cherry-picking the best single-encounter score rather than the latest view.
    ai_by_pid: dict[int, float] = {}
    for row in ai_rows:
        pid = int(row["pid"])
        if pid not in ai_by_pid:
            ai_by_pid[pid] = float(row["overall_score"])

    total_billing_raf = round(sum(billing_by_pid.values()), 4)
    total_ai_raf = round(sum(ai_by_pid.values()), 4)

    # When AI analysis hasn't been run, estimate the gap from open suspect
    # conditions. Each suspect has an estimated_raf_impact; sum those for
    # the total potential uplift.
    if total_ai_raf == 0 and not ai_by_pid:
        try:
            with raf_cursor() as cur:
                cur.execute(
                    """
                    SELECT COUNT(*) * 0.25 AS total_gap
                    FROM raf_suspect_conditions
                    WHERE status = 'open' AND tenant_id = %s
                      AND patient_id IN (SELECT id FROM patients WHERE is_active = 1 AND tenant_id = %s)
                    """,
                    (tenant_id, tenant_id),
                )
                row = cur.fetchone()
                suspect_gap = float(row["total_gap"] or 0) if row else 0.0
        except Exception:
            logger.debug("swallowed exception", exc_info=True)
            suspect_gap = 0.0
        total_gap = round(suspect_gap, 4)
    else:
        total_gap = round(total_ai_raf - total_billing_raf, 4)

    # Revenue-at-Risk: canonical single source (scope=recapture — matches /recapture page).
    # Uses rar_year so a retroactive payment_year param cascades the rate and period.
    _rar = _canonical_revenue_at_risk(tenant_id, payment_year=rar_year, scope="recapture")
    estimated_annual_revenue = _rar["value"]
    _revenue_meta = _rar["_meta"]

    # Average across the AI/calculated RAF per patient — billing-only RAF is
    # often empty for demo data because there are no submitted claims yet, so
    # falling back to ai_by_pid keeps the dashboard meaningful.
    score_source = ai_by_pid if ai_by_pid else billing_by_pid
    all_scores = list(score_source.values())
    average_raf_score = round(sum(all_scores) / len(all_scores), 4) if all_scores else 0.0

    result = {
        "measurement_year": calc_year,
        "total_patients_analyzed": total_patients_analyzed,
        "total_patients": total_patients_analyzed,
        "total_billing_raf": total_billing_raf,
        "total_ai_raf": total_ai_raf if total_ai_raf > 0 else round(total_billing_raf + total_gap, 4),
        "total_gap": total_gap,
        "estimated_annual_revenue": estimated_annual_revenue,
        "estimated_annual_revenue_meta": _revenue_meta,
        "average_raf_score": average_raf_score,
    }
    cache_set(_cache_key, result, ttl=300)
    return RevenueOpportunityResponse(**result)


# ---------------------------------------------------------------------------
# GET /patient-scorecard
# ---------------------------------------------------------------------------

@router.get("/patient-scorecard", summary="Per-patient billing vs AI RAF scorecard", response_model=list[dict[str, Any]])
def patient_scorecard(year: int = Query(default=None),
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
    _perm: None = Depends(require_permission("reports", "read"))) -> list[dict[str, Any]]:
    """
    Return one row per patient with their billing RAF, AI RAF, gap, and
    estimated revenue opportunity.  Patients without a billing RAF score show
    null for billing fields; patients without AI analysis are flagged with
    analyzed=false.
    """
    calc_year = year or date.today().year

    try:
        # All patients from raf_intelligence.patients (tenant-scoped)
        with raf_cursor() as cur:
            cur.execute(
                "SELECT id AS pid, first_name AS fname, last_name AS lname, dob AS DOB, sex FROM patients WHERE is_active = 1 AND tenant_id = %s ORDER BY id LIMIT %s OFFSET %s",
                (tenant_id, limit, offset),
            )
            patients = cur.fetchall()

        # Latest billing RAF per patient for the year — active connections only.
        # Pick the most recently calculated row per patient regardless of model
        # variant (v24, v28, prospective, etc.) so we always have a billing
        # baseline if any score has been computed.
        with raf_cursor() as cur:
            cur.execute(
                """
                SELECT rs.patient_id, rs.final_raf, rs.hcc_count
                FROM raf_scores rs
                INNER JOIN (
                    SELECT patient_id, MAX(calculated_at) AS max_calc
                    FROM raf_scores
                    WHERE measurement_year = %s
                    GROUP BY patient_id
                ) latest
                  ON latest.patient_id = rs.patient_id
                 AND latest.max_calc   = rs.calculated_at
                WHERE rs.measurement_year = %s
                  AND rs.patient_id IN (SELECT id FROM patients WHERE is_active = 1 AND tenant_id = %s)
                """,
                (calc_year, calc_year, tenant_id),
            )
            billing_rows = cur.fetchall()

        # Latest AI overall_score per patient — scoped to active patients for this tenant
        with raf_cursor() as cur:
            cur.execute(
                """
                SELECT pid,
                       MAX(overall_score) AS ai_raf,
                       MAX(hcc_opportunity_count) AS hcc_count_ai
                FROM raf_encounter_analysis
                WHERE pid IN (SELECT id FROM patients WHERE is_active = 1 AND tenant_id = %s)
                GROUP BY pid
                """,
                (tenant_id,),
            )
            ai_rows = cur.fetchall()

    except NoActiveEMRConnection:
        ai_rows = []
    except Exception as exc:
        logger.error("patient_scorecard db error: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")

    # Index billing and AI data by pid
    billing_by_pid: dict[int, dict[str, Any]] = {
        int(r["patient_id"]): r for r in billing_rows
    }
    ai_by_pid: dict[int, dict[str, Any]] = {
        int(r["pid"]): r for r in ai_rows
    }

    # When AI analysis hasn't run, estimate gap from open suspect conditions.
    # Each suspect HCC has an estimated RAF coefficient that represents the
    # potential uplift if the condition is confirmed and coded.
    suspect_by_pid: dict[int, dict[str, Any]] = {}
    if not ai_by_pid:
        try:
            with raf_cursor() as cur:
                cur.execute(
                    """
                    SELECT patient_id,
                           COUNT(*) AS suspect_count,
                           COUNT(*) * 0.25 AS estimated_gap
                    FROM raf_suspect_conditions
                    WHERE status = 'open' AND tenant_id = %s
                    GROUP BY patient_id
                    """,
                    (tenant_id,),
                )
                for r in cur.fetchall():
                    suspect_by_pid[int(r["patient_id"])] = r
        except Exception:  # noqa: BLE001 — best-effort guard
            logger.debug("swallowed exception", exc_info=True)

    scorecard: list[dict[str, Any]] = []
    for p in patients:
        pid = int(p["pid"])
        name = f"{p.get('fname', '')} {p.get('lname', '')}".strip()
        age = _calculate_age(p.get("DOB"), calc_year)
        sex = (p.get("sex") or "").strip() or "Unknown"

        billing = billing_by_pid.get(pid)
        ai = ai_by_pid.get(pid)

        billing_raf = round(float(billing["final_raf"]), 4) if billing else None
        hcc_count_billing = int(billing["hcc_count"]) if billing else 0

        ai_raf = round(float(ai["ai_raf"]), 4) if ai and ai["ai_raf"] is not None else None
        hcc_count_ai = int(ai["hcc_count_ai"] or 0) if ai else 0

        if billing_raf is not None and ai_raf is not None:
            gap = round(ai_raf - billing_raf, 4)
            revenue_opportunity = round(gap * settings.cms_revenue_per_raf_point, 2)
        elif billing_raf is not None and pid in suspect_by_pid:
            # Estimate gap from open suspect conditions
            est_gap = float(suspect_by_pid[pid]["estimated_gap"] or 0)
            gap = round(est_gap, 4)
            ai_raf = round(billing_raf + gap, 4)
            revenue_opportunity = round(gap * settings.cms_revenue_per_raf_point, 2)
            hcc_count_ai = int(suspect_by_pid[pid]["suspect_count"])
        else:
            gap = None
            revenue_opportunity = None

        scorecard.append({
            "pid": pid,
            "name": name,
            "age": age,
            "sex": sex,
            "billing_raf": billing_raf,
            "ai_raf": ai_raf,
            "gap": gap,
            "revenue_opportunity": revenue_opportunity,
            "hcc_count_billing": hcc_count_billing,
            "hcc_count_ai": hcc_count_ai,
            "analyzed": ai is not None,
        })

    return scorecard


# ---------------------------------------------------------------------------
# GET /hcc-distribution
# ---------------------------------------------------------------------------

@router.get("/hcc-distribution", summary="HCC code frequency across the population", response_model=list[dict[str, Any]])
def hcc_distribution(year: int = Query(default=None),
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
    _perm: None = Depends(require_permission("reports", "read"))) -> list[dict[str, Any]]:
    """
    Return every HCC code present in raf_patient_hcc along with the count of
    distinct patients carrying that HCC in the given measurement year.
    Results are ordered by patient count descending.
    """
    calc_year = year or date.today().year

    # --- cache check ---
    _acid = _active_connection_id(tenant_id)
    _cache_key = f"report:hcc_distribution:{calc_year}:{tenant_id}:{_acid}"
    _cached = cache_get(_cache_key)
    if _cached is not None:
        return _cached

    _sf, _sp = active_patients_subquery(int(tenant_id))
    try:
        with raf_cursor() as cur:
            cur.execute(
                f"""
                SELECT
                    hcc_code,
                    COUNT(DISTINCT patient_id) AS patient_count
                FROM raf_patient_hcc
                WHERE measurement_year = %s
                  AND tenant_id = %s
                  AND {_sf}
                GROUP BY hcc_code
                ORDER BY patient_count DESC
                """,
                (calc_year, int(tenant_id), *_sp),
            )
            rows = cur.fetchall()
    except Exception as exc:
        logger.error("hcc_distribution db error: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")

    result = [
        {
            "hcc_code": str(row["hcc_code"]),
            "patient_count": int(row["patient_count"]),
        }
        for row in rows
    ]
    cache_set(_cache_key, result, ttl=300)
    return result


# ---------------------------------------------------------------------------
# GET /suspects-summary
# ---------------------------------------------------------------------------

@router.get("/suspects-summary", summary="All open suspect conditions across all patients", response_model=list[dict[str, Any]])
def suspects_summary(
    status: str = Query(default="open", description="Filter by status: open, accepted, rejected, or all"),
    limit: int = Query(200, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
    _perm: None = Depends(require_permission("reports", "read"))) -> list[dict[str, Any]]:
    """
    Return all suspect conditions from raf_suspect_conditions.

    Pass status=all to retrieve every record regardless of workflow status.
    The default (status=open) returns only conditions not yet reviewed.
    """
    _ALLOWED_STATUSES = {"open", "accepted", "dismissed", "coded", "all"}
    if status.lower() not in _ALLOWED_STATUSES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid status {status!r}. Allowed values: {', '.join(sorted(_ALLOWED_STATUSES))}",
        )
    _sf, _sp = active_patients_subquery(int(tenant_id))
    try:
        with raf_cursor() as cur:
            if status.lower() == "all":
                cur.execute(
                    f"""
                    SELECT
                        patient_id, suspect_icd10 AS `condition`, suspect_icd10 AS icd10_code, suspect_hcc AS hcc_code,
                        confidence_score, status, evidence_detail AS rationale
                    FROM raf_suspect_conditions
                    WHERE {_sf}
                      AND raf_suspect_conditions.tenant_id = %s
                    ORDER BY confidence_score DESC, patient_id
                    LIMIT %s OFFSET %s
                    """,
                    (*_sp, int(tenant_id), limit, offset),
                )
            else:
                cur.execute(
                    f"""
                    SELECT
                        patient_id, suspect_icd10 AS `condition`, suspect_icd10 AS icd10_code, suspect_hcc AS hcc_code,
                        confidence_score, status, evidence_detail AS rationale
                    FROM raf_suspect_conditions
                    WHERE status = %s
                      AND {_sf}
                      AND raf_suspect_conditions.tenant_id = %s
                    ORDER BY confidence_score DESC, patient_id
                    LIMIT %s OFFSET %s
                    """,
                    (status.lower(), *_sp, int(tenant_id), limit, offset),
                )
            rows = cur.fetchall()
    except Exception as exc:
        logger.error("suspects_summary db error: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")

    return [
        {
            "patient_id": int(row["patient_id"]),
            "condition": row["condition"],
            "icd10_code": row["icd10_code"],
            "hcc_code": str(row["hcc_code"]) if row["hcc_code"] is not None else None,
            "confidence_score": float(row["confidence_score"]) if row["confidence_score"] is not None else None,
            "status": row["status"],
            "rationale": row["rationale"],
        }
        for row in rows
    ]


# ---------------------------------------------------------------------------
# GET /recapture-gaps
# ---------------------------------------------------------------------------

@router.get("/recapture-gaps", summary="Recapture gap analysis across all patients", response_model_exclude_none=True)
def recapture_gaps_report(year: int = Query(default=None),
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
    _perm: None = Depends(require_permission("reports", "read"))) -> dict[str, Any]:
    """
    Find active medical problems not billed in the current year.

    These are conditions documented in the problem list but absent from
    billing — representing revenue recapture opportunities where an HCC
    will drop from the risk score unless re-documented and re-billed before
    the payment year closes.

    Results are capped at 1000 rows to protect query performance against
    the 990K-row lists table.  Use the year parameter to override the
    default (current calendar year).

    Returns a summary envelope:
        total_gaps        – number of unbilled problem-list entries found
        patients_affected – count of distinct patients with at least one gap
        gaps              – list of individual gap records
        top_conditions    – top 10 ICD codes by gap frequency
    """
    calc_year = year or date.today().year

    # NOT EXISTS is used instead of NOT IN to avoid the NULL-safety pitfall:
    # if billing.code is ever NULL the NOT IN subquery would return no rows,
    # silently hiding every gap.  NOT EXISTS correctly ignores NULL-code rows.

    # Step 1: Build emr_pid→patient name map from raf_intelligence.patients
    try:
        with raf_cursor() as cur:
            cur.execute(
                "SELECT id, emr_pid, first_name, last_name FROM patients WHERE is_active = 1 AND emr_pid IS NOT NULL AND tenant_id = %s",
                (tenant_id,),
            )
            pat_rows = cur.fetchall()
    except Exception as exc:
        logger.error("recapture_gaps_report patients lookup: %s", exc, exc_info=True)
        pat_rows = []

    emr_pid_to_name: dict[int, dict[str, str]] = {}
    emr_pid_to_id: dict[int, int] = {}
    for pr in pat_rows:
        emr_pid_to_name[pr["emr_pid"]] = {"first_name": pr["first_name"] or "", "last_name": pr["last_name"] or ""}
        emr_pid_to_id[pr["emr_pid"]] = pr["id"]

    # Step 2: Query OpenEMR clinical tables for recapture gaps.
    # JOIN patient_data directly so we get names from OpenEMR's own source —
    # the raf_intelligence.patients map can miss when emr_pid is UUID-format
    # while openemr lists.pid is integer.
    sql = """
        SELECT
            l.pid,
            l.title,
            l.diagnosis,
            l.begdate,
            pd.fname,
            pd.lname
        FROM lists l
        -- Join on patient_data.id (autoincrement, what lists.pid actually
        -- references in OpenEMR seed data). Fall back to pd.pid via COALESCE
        -- in the upstream Python so we get names for both shapes.
        LEFT JOIN patient_data pd ON (pd.id = l.pid OR pd.pid = l.pid)
        WHERE l.type        = 'medical_problem'
          AND l.activity    = 1
          AND l.diagnosis   IS NOT NULL
          AND l.diagnosis   != ''
          AND NOT EXISTS (
              SELECT 1
              FROM billing b
              JOIN form_encounter fe ON b.pid = fe.pid AND b.encounter = fe.encounter
              WHERE b.pid       = l.pid
                AND b.code      = l.diagnosis
                AND b.code_type = 'ICD10'
                AND b.activity  = 1
                AND fe.date >= %s AND fe.date < %s
          )
        ORDER BY l.pid
        LIMIT 1000
    """

    gaps: list[dict[str, Any]] = []
    try:
        with openemr_cursor(tenant_id=tenant_id) as cur:
            cur.execute(sql, (f"{calc_year}-01-01", f"{calc_year + 1}-01-01"))
            rows = cur.fetchall()
        for row in rows:
            emr_pid = int(row["pid"])
            # Prefer raf_intelligence mapping when available, fall back to
            # patient_data fname/lname from OpenEMR.
            names = emr_pid_to_name.get(emr_pid, {})
            first_name = names.get("first_name") or (row.get("fname") or "")
            last_name = names.get("last_name") or (row.get("lname") or "")
            # Skip rows where patient name could not be resolved from either
            # raf_intelligence.patients or OpenEMR patient_data — these are
            # orphaned EMR records with no valid patient context.
            if not first_name and not last_name:
                continue
            raf_patient_id = emr_pid_to_id.get(emr_pid, emr_pid)
            # OpenEMR lists.diagnosis stores codes as "ICD10:E11.65"; strip
            # the "ICD10:" type prefix so UI displays clean codes like "E11.65".
            raw_diag = row.get("diagnosis") or ""
            icd_code = raw_diag.split(":", 1)[1] if ":" in raw_diag else raw_diag
            gaps.append({
                "pid": raf_patient_id,
                "first_name": first_name,
                "last_name": last_name,
                "condition": row.get("title") or "",
                "icd_code": icd_code,
                "onset_date": row["begdate"].isoformat() if hasattr(row.get("begdate"), "isoformat") else (row.get("begdate") or ""),
            })
    except NoActiveEMRConnection:
        pass  # Fall through to suspect-conditions fallback below
    except Exception as exc:
        logger.error("recapture_gaps_report db error: %s", exc, exc_info=True)

    # When no OpenEMR gaps found (e.g. EMR off + uploaded patients), fall back to
    # open suspect conditions as recapture opportunities.
    if not gaps:
        try:
            _rcap_sf, _rcap_sp = active_patients_subquery(int(tenant_id))
            with raf_cursor() as cur:
                cur.execute(
                    f"""
                    SELECT sc.patient_id, sc.suspect_icd10, sc.suspect_hcc,
                           sc.evidence_detail, sc.created_at,
                           p.first_name, p.last_name
                    FROM raf_suspect_conditions sc
                    JOIN patients p ON p.id = sc.patient_id
                    WHERE sc.status = 'open'
                      AND {_rcap_sf}
                      AND sc.tenant_id = %s
                    ORDER BY sc.confidence_score DESC
                    LIMIT 1000
                    """,
                    (*_rcap_sp, int(tenant_id)),
                )
                sc_rows = cur.fetchall()
            for row in sc_rows:
                gaps.append({
                    "pid": int(row["patient_id"]),
                    "first_name": row.get("first_name") or "",
                    "last_name": row.get("last_name") or "",
                    "condition": row.get("evidence_detail") or row.get("suspect_icd10") or "",
                    "icd_code": row.get("suspect_icd10") or "",
                    "onset_date": row["created_at"].isoformat() if hasattr(row.get("created_at"), "isoformat") else str(row.get("created_at") or ""),
                })
        except Exception as exc:
            logger.warning("recapture_gaps_report suspect fallback error: %s", exc)

    # Distinct patients with at least one gap
    patients_affected = len({g["pid"] for g in gaps})

    # Top 10 conditions by gap frequency — computed in Python to avoid a
    # second aggregation query over the same large table.
    code_counts: Counter = Counter(
        g["icd_code"] for g in gaps if g["icd_code"]
    )
    # Attach the condition title from the first matching gap row
    title_by_code: dict[str, str] = {}
    for g in gaps:
        code = g["icd_code"]
        if code and code not in title_by_code:
            title_by_code[code] = g["condition"]

    top_conditions = [
        {
            "icd_code": code,
            "condition": title_by_code.get(code, ""),
            "gap_count": count,
        }
        for code, count in code_counts.most_common(10)
    ]

    return {
        "measurement_year": calc_year,
        "total_gaps": len(gaps),
        "patients_affected": patients_affected,
        "gaps": gaps,
        "top_conditions": top_conditions,
    }


# ---------------------------------------------------------------------------
# GET /data-completeness
# ---------------------------------------------------------------------------

@router.get("/data-completeness", summary="Data quality metrics across the patient population", response_model=DataCompletenessResponse)
def data_completeness(
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
    _perm: None = Depends(require_permission("reports", "read"))) -> DataCompletenessResponse:
    """
    Report the presence of key clinical data categories across the patient
    population to surface data quality gaps.

    Each counter uses a COUNT(DISTINCT pid) aggregate so the query is
    index-only and does not load individual rows.  All six counts run in
    a single database round-trip using a UNION ALL of aggregate selects.

    Returns:
        total_patients              – all active patient_data rows
        patients_with_billing       – patients with at least one active billing code
        patients_with_problems      – patients with at least one active medical problem
        patients_with_clinical_notes – patients with at least one clinical note
        patients_with_vitals        – patients with at least one vitals entry
        patients_with_immunizations – patients with at least one immunization record
        patients_with_insurance     – patients with at least one insurance record
        completeness_score          – integer 0-100; mean fill-rate across the six
                                      clinical categories relative to total_patients
    """

    # --- cache check ---
    _acid = _active_connection_id(tenant_id)
    _cache_key = f"report:data_completeness:{tenant_id}:{_acid}"
    _cached = cache_get(_cache_key)
    if _cached is not None:
        return _cached

    # Total patients from raf_intelligence.patients; clinical categories from OpenEMR.
    counts: dict[str, int] = {}

    try:
        with raf_cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) AS cnt FROM patients WHERE is_active = 1 AND tenant_id = %s",
                (tenant_id,),
            )
            row = cur.fetchone()
            counts["total_patients"] = int(row["cnt"]) if row else 0
    except Exception as exc:
        logger.error("data_completeness patients count error: %s", exc, exc_info=True)
        counts["total_patients"] = 0

    # First, get the OpenEMR PIDs that are mapped to our RAF patients so we
    # only count clinical data for patients we actually manage.
    _mapped_emr_pids: list[int] = []
    try:
        with raf_cursor() as cur:
            cur.execute(
                "SELECT emr_pid FROM patients WHERE is_active = 1 AND tenant_id = %s AND emr_pid IS NOT NULL",
                (tenant_id,),
            )
            _mapped_emr_pids = [int(r["emr_pid"]) for r in cur.fetchall()]
    except Exception:  # noqa: BLE001 — best-effort guard
        logger.debug("swallowed exception", exc_info=True)

    # Build a PID filter for OpenEMR queries.  If no mapped PIDs exist, we
    # fall back to counting all OpenEMR patients (upload-only tenants won't
    # have EMR data at all, so zeros are correct).
    if _mapped_emr_pids:
        _pid_list = ",".join(str(p) for p in _mapped_emr_pids)
        _pid_filter = f"pid IN ({_pid_list})"
        _patient_id_filter = f"patient_id IN ({_pid_list})"
    else:
        _pid_filter = "1=1"
        _patient_id_filter = "1=1"

    # Run each clinical category as its own query so that a missing table
    # only zeros out that one metric rather than aborting the entire batch.
    _clinical_queries: list[tuple[str, str]] = [
        (
            "patients_with_billing",
            f"SELECT COUNT(DISTINCT pid) AS cnt FROM billing WHERE activity = 1 AND {_pid_filter}",
        ),
        (
            "patients_with_problems",
            f"SELECT COUNT(DISTINCT pid) AS cnt FROM lists WHERE type = 'medical_problem' AND activity = 1 AND {_pid_filter}",
        ),
        (
            "patients_with_clinical_notes",
            f"SELECT COUNT(DISTINCT pid) AS cnt FROM form_clinical_notes WHERE {_pid_filter}",
        ),
        (
            "patients_with_vitals",
            f"SELECT COUNT(DISTINCT pid) AS cnt FROM form_vitals WHERE {_pid_filter}",
        ),
        (
            "patients_with_immunizations",
            f"SELECT COUNT(DISTINCT patient_id) AS cnt FROM immunizations WHERE (added_erroneously = 0 OR added_erroneously IS NULL) AND {_patient_id_filter}",
        ),
        (
            "patients_with_insurance",
            f"SELECT COUNT(DISTINCT pid) AS cnt FROM insurance_data WHERE {_pid_filter}",
        ),
    ]

    try:
        with openemr_cursor(tenant_id=tenant_id) as cur:
            for metric, sql in _clinical_queries:
                try:
                    cur.execute(sql)
                    row = cur.fetchone()
                    counts[metric] = int(row["cnt"]) if row else 0
                except Exception as _qexc:
                    logger.debug(
                        "data_completeness: query for %s failed (table may be absent): %s",
                        metric, _qexc,
                    )
                    counts[metric] = 0
    except NoActiveEMRConnection:
        # No EMR available — clinical categories from OpenEMR are unavailable,
        # but we still return total_patients and zero-filled categories so the
        # frontend renders properly.
        pass
    except Exception as exc:
        # Any DB connection or pool error (not just NoActiveEMRConnection) should
        # degrade gracefully — return zero-filled clinical metrics rather than 500.
        logger.error("data_completeness db error (degraded): %s", exc, exc_info=True)

    total = counts.get("total_patients", 0)

    # The six clinical categories we measure fill-rate against.
    category_keys = [
        "patients_with_billing",
        "patients_with_problems",
        "patients_with_clinical_notes",
        "patients_with_vitals",
        "patients_with_immunizations",
        "patients_with_insurance",
    ]

    if total > 0:
        fill_rates = [
            min(counts.get(k, 0) / total, 1.0)
            for k in category_keys
        ]
        completeness_score = round(sum(fill_rates) / len(fill_rates) * 100)
    else:
        completeness_score = 0

    result = {
        "total_patients": total,
        "patients_with_billing": counts.get("patients_with_billing", 0),
        "patients_with_problems": counts.get("patients_with_problems", 0),
        "patients_with_clinical_notes": counts.get("patients_with_clinical_notes", 0),
        "patients_with_vitals": counts.get("patients_with_vitals", 0),
        "patients_with_immunizations": counts.get("patients_with_immunizations", 0),
        "patients_with_insurance": counts.get("patients_with_insurance", 0),
        "completeness_score": completeness_score,
    }
    cache_set(_cache_key, result, ttl=300)
    return DataCompletenessResponse(**result)


# ---------------------------------------------------------------------------
# GET /workflow-summary
# ---------------------------------------------------------------------------

@router.get("/workflow-summary", summary="Dashboard workflow queue counts", response_model=WorkflowSummaryResponse)
def workflow_summary(
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
    _perm: None = Depends(require_permission("reports", "read")),
) -> WorkflowSummaryResponse:
    """
    Return real-time workflow queue counts for the dashboard.

    Each metric is fetched in its own try/except so a single table failure
    (e.g. providers table missing, OpenEMR unreachable) never aborts the
    entire response.  Failures default to 0 for counts and None for
    timestamps.
    """
    open_suspects: int = 0
    high_confidence_suspects: int = 0
    patients_unanalyzed: int = 0
    patients_total: int = 0
    recent_analyses: int = 0
    providers_active: int = 0
    avg_confidence: float = 0.0
    last_sync_at: str | None = None
    last_analysis_at: str | None = None

    _wf_sf, _wf_sp = active_patients_subquery(int(tenant_id))

    # 1. open_suspects — scoped to active-connection patients only
    try:
        with raf_cursor() as cur:
            cur.execute(
                f"SELECT COUNT(*) AS cnt FROM raf_suspect_conditions WHERE status = 'open' AND {_wf_sf} AND raf_suspect_conditions.tenant_id = %s",
                (*_wf_sp, int(tenant_id)),
            )
            row = cur.fetchone()
            open_suspects = int(row["cnt"]) if row else 0
    except Exception as exc:
        logger.warning("workflow_summary: open_suspects query failed: %s", exc)

    # 2. high_confidence_suspects — scoped to active-connection patients only
    try:
        with raf_cursor() as cur:
            cur.execute(
                f"SELECT COUNT(*) AS cnt FROM raf_suspect_conditions WHERE status = 'open' AND confidence_score >= 0.85 AND {_wf_sf} AND raf_suspect_conditions.tenant_id = %s",
                (*_wf_sp, int(tenant_id)),
            )
            row = cur.fetchone()
            high_confidence_suspects = int(row["cnt"]) if row else 0
    except Exception as exc:
        logger.warning("workflow_summary: high_confidence_suspects query failed: %s", exc)

    # 3. patients_unanalyzed — total patients minus those in raf_encounter_analysis
    #    analyzed_count is scoped to active-connection patients so the delta is meaningful.
    try:
        with raf_cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) AS cnt FROM patients WHERE is_active = 1 AND tenant_id = %s",
                (tenant_id,),
            )
            row = cur.fetchone()
            patients_total = int(row["cnt"]) if row else 0
        try:
            with raf_cursor() as cur:
                cur.execute(
                    """
                    SELECT COUNT(DISTINCT ea.pid) AS cnt
                    FROM raf_encounter_analysis ea
                    WHERE ea.pid IN (SELECT id FROM patients WHERE is_active = 1 AND tenant_id = %s)
                    """,
                    (tenant_id,),
                )
                row = cur.fetchone()
                analyzed_count = int(row["cnt"]) if row else 0
            patients_unanalyzed = max(0, patients_total - analyzed_count)
        except Exception as exc:
            logger.warning("workflow_summary: analyzed_count query failed: %s", exc)
            patients_unanalyzed = patients_total
    except Exception as exc:
        logger.warning("workflow_summary: patients_total query failed: %s", exc)

    # 4. recent_analyses — encounters analyzed in the last 7 days
    try:
        with raf_cursor() as cur:
            cur.execute(
                """
                SELECT COUNT(*) AS cnt
                FROM raf_encounter_analysis
                WHERE (analyzed_at >= DATE_SUB(NOW(), INTERVAL 7 DAY)
                   OR created_at  >= DATE_SUB(NOW(), INTERVAL 7 DAY))
                  AND pid IN (SELECT id FROM patients WHERE is_active = 1)
                """
            )
            row = cur.fetchone()
            recent_analyses = int(row["cnt"]) if row else 0
    except Exception as exc:
        logger.warning("workflow_summary: recent_analyses query failed: %s", exc)

    # 5. providers_active
    try:
        with raf_cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) AS cnt FROM providers WHERE status = 'active'"
            )
            row = cur.fetchone()
            providers_active = int(row["cnt"]) if row else 0
    except Exception as exc:
        logger.warning("workflow_summary: providers_active query failed: %s", exc)

    # 6. avg_confidence
    try:
        with raf_cursor() as cur:
            cur.execute(
                f"SELECT AVG(confidence_score) AS avg_conf FROM raf_suspect_conditions WHERE status = 'open' AND {_wf_sf} AND raf_suspect_conditions.tenant_id = %s",
                (*_wf_sp, int(tenant_id)),
            )
            row = cur.fetchone()
            raw = row["avg_conf"] if row else None
            avg_confidence = round(float(raw), 4) if raw is not None else 0.0
    except Exception as exc:
        logger.warning("workflow_summary: avg_confidence query failed: %s", exc)

    # 7. last_sync_at
    try:
        with raf_cursor() as cur:
            cur.execute(
                "SELECT MAX(updated_at) AS ts FROM emr_connections WHERE is_active = 1"
            )
            row = cur.fetchone()
            ts = row["ts"] if row else None
            last_sync_at = ts.isoformat() if hasattr(ts, "isoformat") else (str(ts) if ts is not None else None)
    except Exception as exc:
        logger.warning("workflow_summary: last_sync_at query failed: %s", exc)

    # 8. last_analysis_at — prefer analyzed_at, fall back to created_at
    try:
        with raf_cursor() as cur:
            cur.execute(
                """
                SELECT MAX(ea.analyzed_at) AS ts
                FROM raf_encounter_analysis ea
                WHERE (
                    EXISTS (
                        SELECT 1
                        FROM emr_patient_matches pm
                        JOIN emr_connections ec ON ec.id = pm.connection_id
                        WHERE ec.is_active = 1
                          AND pm.raf_patient_id = ea.pid
                          AND pm.raf_patient_id IS NOT NULL
                    )
                    OR EXISTS (
                        SELECT 1 FROM emr_connections
                        WHERE connection_type = 'direct_db' AND is_active = 1
                    )
                )
                """
            )
            row = cur.fetchone()
            ts = row["ts"] if row else None
            if ts is None:
                cur.execute(
                    """
                    SELECT MAX(ea.created_at) AS ts
                    FROM raf_encounter_analysis ea
                    WHERE (
                        EXISTS (
                            SELECT 1
                            FROM emr_patient_matches pm
                            JOIN emr_connections ec ON ec.id = pm.connection_id
                            WHERE ec.is_active = 1
                              AND pm.raf_patient_id = ea.pid
                              AND pm.raf_patient_id IS NOT NULL
                        )
                        OR EXISTS (
                            SELECT 1 FROM emr_connections
                            WHERE connection_type = 'direct_db' AND is_active = 1
                        )
                    )
                    """
                )
                row = cur.fetchone()
                ts = row["ts"] if row else None
            last_analysis_at = ts.isoformat() if hasattr(ts, "isoformat") else (str(ts) if ts is not None else None)
    except Exception as exc:
        logger.warning("workflow_summary: last_analysis_at query failed: %s", exc)

    return WorkflowSummaryResponse(
        open_suspects=open_suspects,
        high_confidence_suspects=high_confidence_suspects,
        patients_unanalyzed=patients_unanalyzed,
        patients_total=patients_total,
        recent_analyses_7d=recent_analyses,
        providers_active=providers_active,
        avg_confidence=avg_confidence,
        last_sync_at=last_sync_at,
        last_analysis_at=last_analysis_at,
    )
