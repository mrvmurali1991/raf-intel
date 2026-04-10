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
"""
from __future__ import annotations

import json
import logging
from datetime import date, datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Query

from collections import Counter

from app.db import raf_cursor, openemr_cursor

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/reports", tags=["reports"])

# CMS per-member per-year revenue multiplier (MA benchmark rate)
_ANNUAL_REVENUE_PER_RAF_POINT = 10_398.44


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

@router.get("/revenue-opportunity", summary="Population-level RAF gap and revenue opportunity")
def revenue_opportunity(year: int = Query(default=None)) -> dict[str, Any]:
    """
    Aggregate comparison of billing RAF scores vs AI-detected RAF scores.

    Returns total patients analyzed, the RAF gap between what was billed and
    what the AI found, and an estimated annual revenue opportunity based on
    the CMS per-member rate of $10,398.44 per RAF point.
    """
    calc_year = year or date.today().year

    try:
        # Count distinct patients that have been through AI analysis
        with raf_cursor() as cur:
            cur.execute(
                "SELECT COUNT(DISTINCT pid) AS cnt FROM raf_encounter_analysis",
            )
            row = cur.fetchone()
            total_patients_analyzed = int(row["cnt"]) if row else 0

        # Sum billing RAF — one score per patient (latest calculation for the year)
        with raf_cursor() as cur:
            cur.execute(
                """
                SELECT rs.patient_id, rs.final_raf
                FROM raf_scores rs
                INNER JOIN (
                    SELECT patient_id, MAX(calculated_at) AS latest
                    FROM raf_scores
                    WHERE measurement_year = %s
                    GROUP BY patient_id
                ) latest_scores
                ON rs.patient_id = latest_scores.patient_id
                   AND rs.calculated_at = latest_scores.latest
                """,
                (calc_year,),
            )
            billing_rows = cur.fetchall()

        # Sum AI RAF — latest overall_score per patient from raf_encounter_analysis
        with raf_cursor() as cur:
            cur.execute(
                """
                SELECT pid, overall_score
                FROM raf_encounter_analysis
                WHERE overall_score IS NOT NULL
                ORDER BY pid, encounter_id DESC
                """,
            )
            ai_rows = cur.fetchall()

    except Exception as exc:
        logger.error("revenue_opportunity db error: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))

    # Aggregate billing RAF per patient
    billing_by_pid: dict[int, float] = {}
    for row in billing_rows:
        pid = int(row["patient_id"])
        if pid not in billing_by_pid:
            billing_by_pid[pid] = float(row["final_raf"])

    # Aggregate AI RAF per patient — take the highest overall_score per patient
    # (encounter-level scores represent the most complete picture per encounter;
    # the highest score per patient reflects the full clinical picture found)
    ai_by_pid: dict[int, float] = {}
    for row in ai_rows:
        pid = int(row["pid"])
        score = float(row["overall_score"])
        if pid not in ai_by_pid or score > ai_by_pid[pid]:
            ai_by_pid[pid] = score

    total_billing_raf = round(sum(billing_by_pid.values()), 4)
    total_ai_raf = round(sum(ai_by_pid.values()), 4)
    total_gap = round(total_ai_raf - total_billing_raf, 4)
    estimated_annual_revenue = round(total_gap * _ANNUAL_REVENUE_PER_RAF_POINT, 2)

    all_scores = list(billing_by_pid.values())
    average_raf_score = round(sum(all_scores) / len(all_scores), 4) if all_scores else 0.0

    return {
        "measurement_year": calc_year,
        "total_patients_analyzed": total_patients_analyzed,
        "total_billing_raf": total_billing_raf,
        "total_ai_raf": total_ai_raf,
        "total_gap": total_gap,
        "estimated_annual_revenue": estimated_annual_revenue,
        "average_raf_score": average_raf_score,
    }


# ---------------------------------------------------------------------------
# GET /patient-scorecard
# ---------------------------------------------------------------------------

@router.get("/patient-scorecard", summary="Per-patient billing vs AI RAF scorecard")
def patient_scorecard(year: int = Query(default=None)) -> list[dict[str, Any]]:
    """
    Return one row per patient with their billing RAF, AI RAF, gap, and
    estimated revenue opportunity.  Patients without a billing RAF score show
    null for billing fields; patients without AI analysis are flagged with
    analyzed=false.
    """
    calc_year = year or date.today().year

    try:
        # All patients from OpenEMR
        with openemr_cursor() as cur:
            cur.execute(
                "SELECT pid, fname, lname, DOB, sex FROM patient_data ORDER BY pid"
            )
            patients = cur.fetchall()

        # Latest billing RAF per patient for the year
        with raf_cursor() as cur:
            cur.execute(
                """
                SELECT rs.patient_id, rs.final_raf, rs.hcc_count
                FROM raf_scores rs
                INNER JOIN (
                    SELECT patient_id, MAX(calculated_at) AS latest
                    FROM raf_scores
                    WHERE measurement_year = %s
                    GROUP BY patient_id
                ) latest_scores
                ON rs.patient_id = latest_scores.patient_id
                   AND rs.calculated_at = latest_scores.latest
                """,
                (calc_year,),
            )
            billing_rows = cur.fetchall()

        # Latest AI overall_score per patient (max overall_score across encounters)
        with raf_cursor() as cur:
            cur.execute(
                """
                SELECT pid,
                       MAX(overall_score) AS ai_raf,
                       SUM(hcc_opportunity_count) AS hcc_count_ai
                FROM raf_encounter_analysis
                GROUP BY pid
                """,
            )
            ai_rows = cur.fetchall()

    except Exception as exc:
        logger.error("patient_scorecard db error: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))

    # Index billing and AI data by pid
    billing_by_pid: dict[int, dict[str, Any]] = {
        int(r["patient_id"]): r for r in billing_rows
    }
    ai_by_pid: dict[int, dict[str, Any]] = {
        int(r["pid"]): r for r in ai_rows
    }

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
            revenue_opportunity = round(gap * _ANNUAL_REVENUE_PER_RAF_POINT, 2)
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

@router.get("/hcc-distribution", summary="HCC code frequency across the population")
def hcc_distribution(year: int = Query(default=None)) -> list[dict[str, Any]]:
    """
    Return every HCC code present in raf_patient_hcc along with the count of
    distinct patients carrying that HCC in the given measurement year.
    Results are ordered by patient count descending.
    """
    calc_year = year or date.today().year

    try:
        with raf_cursor() as cur:
            cur.execute(
                """
                SELECT
                    hcc_code,
                    COUNT(DISTINCT patient_id) AS patient_count
                FROM raf_patient_hcc
                WHERE measurement_year = %s
                GROUP BY hcc_code
                ORDER BY patient_count DESC
                """,
                (calc_year,),
            )
            rows = cur.fetchall()
    except Exception as exc:
        logger.error("hcc_distribution db error: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))

    return [
        {
            "hcc_code": str(row["hcc_code"]),
            "patient_count": int(row["patient_count"]),
        }
        for row in rows
    ]


# ---------------------------------------------------------------------------
# GET /suspects-summary
# ---------------------------------------------------------------------------

@router.get("/suspects-summary", summary="All open suspect conditions across all patients")
def suspects_summary(
    status: str = Query(default="open", description="Filter by status: open, accepted, rejected, or all"),
) -> list[dict[str, Any]]:
    """
    Return all suspect conditions from raf_suspect_conditions.

    Pass status=all to retrieve every record regardless of workflow status.
    The default (status=open) returns only conditions not yet reviewed.
    """
    try:
        with raf_cursor() as cur:
            if status.lower() == "all":
                cur.execute(
                    """
                    SELECT
                        patient_id, condition, icd10_code, hcc_code,
                        confidence_score, status, rationale
                    FROM raf_suspect_conditions
                    ORDER BY confidence_score DESC, patient_id
                    """
                )
            else:
                cur.execute(
                    """
                    SELECT
                        patient_id, condition, icd10_code, hcc_code,
                        confidence_score, status, rationale
                    FROM raf_suspect_conditions
                    WHERE status = %s
                    ORDER BY confidence_score DESC, patient_id
                    """,
                    (status.lower(),),
                )
            rows = cur.fetchall()
    except Exception as exc:
        logger.error("suspects_summary db error: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))

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

@router.get("/recapture-gaps", summary="Recapture gap analysis across all patients")
def recapture_gaps_report(year: int = Query(default=None)) -> dict[str, Any]:
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
    sql = """
        SELECT
            l.pid,
            pd.fname,
            pd.lname,
            l.title,
            l.diagnosis,
            l.begdate
        FROM lists l
        JOIN patient_data pd ON pd.pid = l.pid
        WHERE l.type        = 'medical_problem'
          AND l.activity    = 1
          AND l.diagnosis   IS NOT NULL
          AND l.diagnosis   != ''
          AND NOT EXISTS (
              SELECT 1
              FROM billing b
              WHERE b.pid       = l.pid
                AND b.code      = l.diagnosis
                AND b.code_type = 'ICD10'
                AND b.activity  = 1
                AND YEAR(b.date) = %s
          )
        ORDER BY pd.lname, pd.fname
        LIMIT 1000
    """

    try:
        with openemr_cursor() as cur:
            cur.execute(sql, (calc_year,))
            rows = cur.fetchall()
    except Exception as exc:
        logger.error("recapture_gaps_report db error: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))

    gaps: list[dict[str, Any]] = []
    for row in rows:
        gaps.append({
            "pid": int(row["pid"]),
            "first_name": row.get("fname") or "",
            "last_name": row.get("lname") or "",
            "condition": row.get("title") or "",
            "icd_code": row.get("diagnosis") or "",
            "onset_date": row["begdate"].isoformat() if hasattr(row.get("begdate"), "isoformat") else (row.get("begdate") or ""),
        })

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

@router.get("/data-completeness", summary="Data quality metrics across the patient population")
def data_completeness() -> dict[str, Any]:
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
    # Each SELECT returns one labeled row.  Using a UNION ALL keeps this as a
    # single round-trip and avoids opening/closing multiple cursors.
    sql = """
        SELECT 'total_patients'               AS metric, COUNT(*)              AS cnt FROM patient_data WHERE pid > 0
        UNION ALL
        SELECT 'patients_with_billing',               COUNT(DISTINCT pid)      FROM billing          WHERE activity = 1
        UNION ALL
        SELECT 'patients_with_problems',              COUNT(DISTINCT pid)      FROM lists            WHERE type = 'medical_problem' AND activity = 1
        UNION ALL
        SELECT 'patients_with_clinical_notes',        COUNT(DISTINCT pid)      FROM form_clinical_notes
        UNION ALL
        SELECT 'patients_with_vitals',                COUNT(DISTINCT pid)      FROM form_vitals      WHERE activity = 1
        UNION ALL
        SELECT 'patients_with_immunizations',         COUNT(DISTINCT pid)      FROM immunizations    WHERE added_erroneously = 0 OR added_erroneously IS NULL
        UNION ALL
        SELECT 'patients_with_insurance',             COUNT(DISTINCT pid)      FROM insurance_data
    """

    try:
        with openemr_cursor() as cur:
            cur.execute(sql)
            rows = cur.fetchall()
    except Exception as exc:
        logger.error("data_completeness db error: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))

    counts: dict[str, int] = {row["metric"]: int(row["cnt"]) for row in rows}

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

    return {
        "total_patients": total,
        "patients_with_billing": counts.get("patients_with_billing", 0),
        "patients_with_problems": counts.get("patients_with_problems", 0),
        "patients_with_clinical_notes": counts.get("patients_with_clinical_notes", 0),
        "patients_with_vitals": counts.get("patients_with_vitals", 0),
        "patients_with_immunizations": counts.get("patients_with_immunizations", 0),
        "patients_with_insurance": counts.get("patients_with_insurance", 0),
        "completeness_score": completeness_score,
    }
