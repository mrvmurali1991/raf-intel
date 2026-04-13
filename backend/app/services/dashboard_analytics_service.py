"""
Dashboard Analytics Service.

Provides four analytics functions that power the /api/analytics/* endpoints:

  get_raf_overview            – Population RAF summary, score distribution, trends
  get_coding_accuracy_metrics – HCC capture rate, MEAT compliance, missed HCCs
  get_provider_performance    – Per-provider effectiveness ranking
  get_patient_risk_stratification – Risk tier grouping + rising-risk patients

All functions are synchronous and use raf_cursor() directly.  They are
designed to be called from FastAPI route handlers that run in Starlette's
thread-pool executor (sync ``def`` endpoints).

Tenant isolation is enforced on every query by scoping to patients that
belong to the tenant and are marked is_active = 1.
"""

import logging
from datetime import date, datetime
from typing import Any

from app.db import raf_cursor

logger = logging.getLogger(__name__)

# CMS Medicare Advantage per-member per-year benchmark — same rate used across
# reports.py / insights.py so revenue estimates are consistent.
_PMPY: float = 11_015.04


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _int_tenant(tenant_id: str) -> int:
    """Convert tenant_id string to int, defaulting to 1 for safety."""
    try:
        return int(tenant_id)
    except (TypeError, ValueError):
        return 1


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value) if value is not None else default
    except (TypeError, ValueError):
        return default


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value) if value is not None else default
    except (TypeError, ValueError):
        return default


# ---------------------------------------------------------------------------
# 1. RAF Overview
# ---------------------------------------------------------------------------

def get_raf_overview(tenant_id: str, measurement_year: int) -> dict[str, Any]:
    """
    Return population-level RAF intelligence summary for a tenant + year.

    Fields returned
    ---------------
    total_patients          int    — active patients with at least one RAF score
    average_raf_score       float  — mean blended RAF score across the population
    total_hccs              int    — total HCC conditions across all patients
    total_recapture_gaps    int    — open recapture gaps (gracefully 0 if table missing)
    raf_score_distribution  dict   — bucket counts: <0.5, 0.5-1.0, 1.0-1.5, 1.5-2.0, 2.0+
    month_over_month_trend  list   — [{month, avg_raf_score, patient_count}, …] last 6 months
    estimated_annual_revenue float — avg_raf × PMPY × total_patients
    """
    tid = _int_tenant(tenant_id)

    # --- Core population stats -------------------------------------------
    total_patients = 0
    avg_raf = 0.0
    try:
        with raf_cursor() as cur:
            cur.execute(
                """
                SELECT
                    COUNT(DISTINCT rs.patient_id)   AS total_patients,
                    AVG(rs.raf_score)               AS avg_raf_score
                FROM raf_scores rs
                JOIN patients p ON p.id = rs.patient_id
                WHERE p.is_active = 1
                  AND p.tenant_id = %s
                  AND rs.measurement_year = %s
                  AND rs.score_type = 'prospective'
                """,
                (tid, measurement_year),
            )
            row = cur.fetchone()
            if row:
                total_patients = _safe_int(row.get("total_patients"))
                avg_raf = _safe_float(row.get("average_raf_score"))
    except Exception as exc:
        logger.warning("get_raf_overview: core stats query failed: %s", exc)

    # --- Total HCCs -------------------------------------------------------
    total_hccs = 0
    try:
        with raf_cursor() as cur:
            cur.execute(
                """
                SELECT COUNT(*) AS cnt
                FROM raf_patient_hcc rh
                JOIN patients p ON p.id = rh.patient_id
                WHERE p.is_active = 1
                  AND p.tenant_id = %s
                  AND rh.measurement_year = %s
                """,
                (tid, measurement_year),
            )
            row = cur.fetchone()
            if row:
                total_hccs = _safe_int(row.get("cnt"))
    except Exception as exc:
        logger.warning("get_raf_overview: total_hccs query failed: %s", exc)

    # --- Recapture gaps ---------------------------------------------------
    total_recapture_gaps = 0
    try:
        with raf_cursor() as cur:
            cur.execute(
                """
                SELECT COUNT(*) AS cnt
                FROM recapture_gaps rg
                JOIN patients p ON p.id = rg.patient_id
                WHERE p.is_active = 1
                  AND p.tenant_id = %s
                  AND rg.status = 'open'
                """,
                (tid,),
            )
            row = cur.fetchone()
            if row:
                total_recapture_gaps = _safe_int(row.get("cnt"))
    except Exception as exc:
        # recapture_gaps table may not exist in all deployments
        logger.debug("get_raf_overview: recapture_gaps query skipped: %s", exc)

    # --- RAF score distribution -------------------------------------------
    distribution: dict[str, int] = {
        "lt_0_5": 0,
        "0_5_to_1_0": 0,
        "1_0_to_1_5": 0,
        "1_5_to_2_0": 0,
        "gte_2_0": 0,
    }
    try:
        with raf_cursor() as cur:
            cur.execute(
                """
                SELECT
                    SUM(CASE WHEN rs.raf_score < 0.5 THEN 1 ELSE 0 END)                      AS lt_0_5,
                    SUM(CASE WHEN rs.raf_score >= 0.5  AND rs.raf_score < 1.0 THEN 1 ELSE 0 END) AS s0_5_1_0,
                    SUM(CASE WHEN rs.raf_score >= 1.0  AND rs.raf_score < 1.5 THEN 1 ELSE 0 END) AS s1_0_1_5,
                    SUM(CASE WHEN rs.raf_score >= 1.5  AND rs.raf_score < 2.0 THEN 1 ELSE 0 END) AS s1_5_2_0,
                    SUM(CASE WHEN rs.raf_score >= 2.0 THEN 1 ELSE 0 END)                     AS gte_2_0
                FROM raf_scores rs
                JOIN patients p ON p.id = rs.patient_id
                WHERE p.is_active = 1
                  AND p.tenant_id = %s
                  AND rs.measurement_year = %s
                  AND rs.score_type = 'prospective'
                """,
                (tid, measurement_year),
            )
            row = cur.fetchone()
            if row:
                distribution = {
                    "lt_0_5": _safe_int(row.get("lt_0_5")),
                    "0_5_to_1_0": _safe_int(row.get("s0_5_1_0")),
                    "1_0_to_1_5": _safe_int(row.get("s1_0_1_5")),
                    "1_5_to_2_0": _safe_int(row.get("s1_5_2_0")),
                    "gte_2_0": _safe_int(row.get("gte_2_0")),
                }
    except Exception as exc:
        logger.warning("get_raf_overview: distribution query failed: %s", exc)

    # --- Month-over-month trend (last 6 months) ---------------------------
    trend: list[dict[str, Any]] = []
    try:
        with raf_cursor() as cur:
            cur.execute(
                """
                SELECT
                    DATE_FORMAT(rs.calculated_at, '%%Y-%%m') AS month,
                    AVG(rs.raf_score)                        AS avg_raf_score,
                    COUNT(DISTINCT rs.patient_id)            AS patient_count
                FROM raf_scores rs
                JOIN patients p ON p.id = rs.patient_id
                WHERE p.is_active = 1
                  AND p.tenant_id = %s
                  AND rs.score_type = 'prospective'
                  AND rs.calculated_at >= DATE_SUB(NOW(), INTERVAL 6 MONTH)
                GROUP BY DATE_FORMAT(rs.calculated_at, '%%Y-%%m')
                ORDER BY month ASC
                LIMIT 6
                """,
                (tid,),
            )
            for r in cur.fetchall():
                trend.append(
                    {
                        "month": r.get("month") or "",
                        "average_raf_score": round(_safe_float(r.get("average_raf_score")), 4),
                        "patient_count": _safe_int(r.get("patient_count")),
                    }
                )
    except Exception as exc:
        logger.warning("get_raf_overview: trend query failed: %s", exc)

    estimated_annual_revenue = round(avg_raf * _PMPY * total_patients, 2)

    return {
        "measurement_year": measurement_year,
        "total_patients": total_patients,
        "average_raf_score": round(avg_raf, 4),
        "total_hccs": total_hccs,
        "total_recapture_gaps": total_recapture_gaps,
        "raf_score_distribution": distribution,
        "month_over_month_trend": trend,
        "estimated_annual_revenue": estimated_annual_revenue,
    }


# ---------------------------------------------------------------------------
# 2. Coding Accuracy Metrics
# ---------------------------------------------------------------------------

def get_coding_accuracy_metrics(tenant_id: str) -> dict[str, Any]:
    """
    Return HCC coding accuracy metrics for a tenant.

    Fields returned
    ---------------
    total_encounters        int
    coded_encounters        int    — encounters with ≥1 HCC diagnosis
    uncoded_encounters      int
    hcc_capture_rate        float  — coded_encounters / total_encounters
    meat_compliance_rate    float  — encounters with MEAT evidence / coded_encounters
    top_missed_hccs         list   — [{hcc_code, description, miss_count}, …] top-10
    """
    tid = _int_tenant(tenant_id)

    total_enc = 0
    coded_enc = 0
    uncoded_enc = 0
    hcc_capture_rate = 0.0
    meat_compliance_rate = 0.0

    # --- Encounter counts ------------------------------------------------
    try:
        with raf_cursor() as cur:
            cur.execute(
                """
                SELECT
                    COUNT(DISTINCT ne.id)                               AS total_encounters,
                    COUNT(DISTINCT CASE WHEN rh.encounter_id IS NOT NULL
                                        THEN ne.id END)                 AS coded_encounters
                FROM normalized_encounters ne
                JOIN patients p ON p.id = ne.patient_id
                LEFT JOIN raf_patient_hcc rh ON rh.encounter_id = ne.id
                WHERE p.is_active = 1
                  AND p.tenant_id = %s
                """,
                (tid,),
            )
            row = cur.fetchone()
            if row:
                total_enc = _safe_int(row.get("total_encounters"))
                coded_enc = _safe_int(row.get("coded_encounters"))
                uncoded_enc = max(0, total_enc - coded_enc)
                hcc_capture_rate = round(coded_enc / total_enc, 4) if total_enc > 0 else 0.0
    except Exception as exc:
        logger.warning("get_coding_accuracy_metrics: encounter counts failed: %s", exc)

    # --- MEAT compliance -------------------------------------------------
    try:
        with raf_cursor() as cur:
            cur.execute(
                """
                SELECT
                    COUNT(DISTINCT rh.encounter_id)                     AS hcc_encounters,
                    COUNT(DISTINCT CASE WHEN mv.meets_meat = 1
                                        THEN rh.encounter_id END)       AS meat_encounters
                FROM raf_patient_hcc rh
                JOIN patients p ON p.id = rh.patient_id
                LEFT JOIN meat_validations mv ON mv.patient_id = rh.patient_id
                                              AND mv.encounter_id = rh.encounter_id
                WHERE p.is_active = 1
                  AND p.tenant_id = %s
                  AND rh.encounter_id IS NOT NULL
                """,
                (tid,),
            )
            row = cur.fetchone()
            if row:
                hcc_enc = _safe_int(row.get("hcc_encounters"))
                meat_enc = _safe_int(row.get("meat_encounters"))
                meat_compliance_rate = round(meat_enc / hcc_enc, 4) if hcc_enc > 0 else 0.0
    except Exception as exc:
        logger.warning("get_coding_accuracy_metrics: MEAT compliance failed: %s", exc)

    # --- Top missed HCCs (suspect conditions that were not captured) ------
    top_missed: list[dict[str, Any]] = []
    try:
        with raf_cursor() as cur:
            cur.execute(
                """
                SELECT
                    sc.hcc_category                   AS hcc_code,
                    sc.condition_name                 AS description,
                    COUNT(*)                          AS miss_count
                FROM raf_suspect_conditions sc
                JOIN patients p ON p.id = sc.patient_id
                WHERE sc.status = 'open'
                  AND p.is_active = 1
                  AND p.tenant_id = %s
                  AND sc.hcc_category IS NOT NULL
                GROUP BY sc.hcc_category, sc.condition_name
                ORDER BY miss_count DESC
                LIMIT 10
                """,
                (tid,),
            )
            for r in cur.fetchall():
                top_missed.append(
                    {
                        "hcc_code": r.get("hcc_code") or "",
                        "description": r.get("description") or "",
                        "miss_count": _safe_int(r.get("miss_count")),
                    }
                )
    except Exception as exc:
        logger.warning("get_coding_accuracy_metrics: top_missed_hccs failed: %s", exc)

    return {
        "total_encounters": total_enc,
        "coded_encounters": coded_enc,
        "uncoded_encounters": uncoded_enc,
        "hcc_capture_rate": hcc_capture_rate,
        "meat_compliance_rate": meat_compliance_rate,
        "top_missed_hccs": top_missed,
    }


# ---------------------------------------------------------------------------
# 3. Provider Performance
# ---------------------------------------------------------------------------

def get_provider_performance(tenant_id: str) -> list[dict[str, Any]]:
    """
    Return per-provider RAF effectiveness metrics, ranked by avg RAF score descending.

    Each entry contains
    -------------------
    provider_id         int
    provider_name       str
    specialty           str | None
    patient_count       int
    avg_raf_score       float
    hcc_capture_rate    float  — proportion of encounters with ≥1 HCC coded
    gap_closure_rate    float  — closed recapture gaps / total gaps for this provider
    """
    tid = _int_tenant(tenant_id)
    current_year = date.today().year
    results: list[dict[str, Any]] = []

    try:
        with raf_cursor() as cur:
            cur.execute(
                """
                SELECT
                    prov.id                                             AS provider_id,
                    CONCAT(prov.first_name, ' ', prov.last_name)        AS provider_name,
                    prov.specialty,
                    COUNT(DISTINCT pp.patient_id)                       AS patient_count,
                    AVG(rs.raf_score)                                   AS avg_raf_score,
                    COUNT(DISTINCT ne.id)                               AS total_encounters,
                    COUNT(DISTINCT CASE WHEN rh.encounter_id IS NOT NULL
                                        THEN ne.id END)                 AS coded_encounters
                FROM providers prov
                JOIN provider_patients pp ON pp.provider_id = prov.id
                JOIN patients p ON p.id = pp.patient_id
                LEFT JOIN raf_scores rs ON rs.patient_id = p.id
                                       AND rs.measurement_year = %s
                                       AND rs.score_type = 'prospective'
                LEFT JOIN normalized_encounters ne ON ne.patient_id = p.id
                LEFT JOIN raf_patient_hcc rh ON rh.encounter_id = ne.id
                WHERE prov.tenant_id = %s
                  AND prov.status = 'active'
                  AND p.is_active = 1
                GROUP BY prov.id, prov.first_name, prov.last_name, prov.specialty
                ORDER BY avg_raf_score DESC
                """,
                (current_year, tid),
            )
            provider_rows = cur.fetchall()
    except Exception as exc:
        logger.warning("get_provider_performance: main query failed: %s", exc)
        return []

    # Gap closure rates — one query per provider to avoid a giant join
    for row in provider_rows:
        prov_id = _safe_int(row.get("provider_id"))
        total_enc = _safe_int(row.get("total_encounters"))
        coded_enc = _safe_int(row.get("coded_encounters"))
        hcc_capture = round(coded_enc / total_enc, 4) if total_enc > 0 else 0.0

        gap_closure = 0.0
        try:
            with raf_cursor() as cur:
                cur.execute(
                    """
                    SELECT
                        COUNT(*)                                            AS total_gaps,
                        SUM(CASE WHEN rg.status = 'closed' THEN 1 ELSE 0 END) AS closed_gaps
                    FROM recapture_gaps rg
                    JOIN patients p ON p.id = rg.patient_id
                    JOIN provider_patients pp ON pp.patient_id = p.id
                    WHERE pp.provider_id = %s
                      AND p.is_active = 1
                      AND p.tenant_id = %s
                    """,
                    (prov_id, tid),
                )
                gr = cur.fetchone()
                if gr:
                    total_gaps = _safe_int(gr.get("total_gaps"))
                    closed_gaps = _safe_int(gr.get("closed_gaps"))
                    gap_closure = round(closed_gaps / total_gaps, 4) if total_gaps > 0 else 0.0
        except Exception as exc:
            logger.debug("get_provider_performance: gap closure skipped for provider %s: %s", prov_id, exc)

        results.append(
            {
                "provider_id": prov_id,
                "provider_name": row.get("provider_name") or "",
                "specialty": row.get("specialty"),
                "patient_count": _safe_int(row.get("patient_count")),
                "average_raf_score": round(_safe_float(row.get("average_raf_score")), 4),
                "hcc_capture_rate": hcc_capture,
                "gap_closure_rate": gap_closure,
            }
        )

    return results


# ---------------------------------------------------------------------------
# 4. Patient Risk Stratification
# ---------------------------------------------------------------------------

def get_patient_risk_stratification(tenant_id: str) -> dict[str, Any]:
    """
    Group patients into risk tiers based on current-year RAF score.

    Tiers
    -----
    low       — RAF < 0.8
    medium    — 0.8 ≤ RAF < 1.2
    high      — 1.2 ≤ RAF < 1.8
    very_high — RAF ≥ 1.8

    Also identifies rising-risk patients: those whose RAF increased by ≥ 0.3
    compared to the previous year.

    Returns
    -------
    tiers           dict   — {tier_name: {count, avg_raf_score}}
    rising_risk     list   — [{patient_id, prior_raf, current_raf, delta}, …] top-20
    total_patients  int
    """
    tid = _int_tenant(tenant_id)
    current_year = date.today().year
    prior_year = current_year - 1

    tiers: dict[str, dict[str, Any]] = {
        "low": {"count": 0, "average_raf_score": 0.0},
        "medium": {"count": 0, "average_raf_score": 0.0},
        "high": {"count": 0, "average_raf_score": 0.0},
        "very_high": {"count": 0, "average_raf_score": 0.0},
    }
    total_patients = 0

    try:
        with raf_cursor() as cur:
            cur.execute(
                """
                SELECT
                    SUM(CASE WHEN rs.raf_score < 0.8 THEN 1 ELSE 0 END)                        AS low_count,
                    AVG(CASE WHEN rs.raf_score < 0.8 THEN rs.raf_score END)                     AS low_avg,
                    SUM(CASE WHEN rs.raf_score >= 0.8 AND rs.raf_score < 1.2 THEN 1 ELSE 0 END) AS med_count,
                    AVG(CASE WHEN rs.raf_score >= 0.8 AND rs.raf_score < 1.2 THEN rs.raf_score END) AS med_avg,
                    SUM(CASE WHEN rs.raf_score >= 1.2 AND rs.raf_score < 1.8 THEN 1 ELSE 0 END) AS high_count,
                    AVG(CASE WHEN rs.raf_score >= 1.2 AND rs.raf_score < 1.8 THEN rs.raf_score END) AS high_avg,
                    SUM(CASE WHEN rs.raf_score >= 1.8 THEN 1 ELSE 0 END)                        AS vh_count,
                    AVG(CASE WHEN rs.raf_score >= 1.8 THEN rs.raf_score END)                    AS vh_avg,
                    COUNT(DISTINCT rs.patient_id)                                               AS total_patients
                FROM raf_scores rs
                JOIN patients p ON p.id = rs.patient_id
                WHERE p.is_active = 1
                  AND p.tenant_id = %s
                  AND rs.measurement_year = %s
                  AND rs.score_type = 'prospective'
                """,
                (tid, current_year),
            )
            row = cur.fetchone()
            if row:
                total_patients = _safe_int(row.get("total_patients"))
                tiers = {
                    "low": {
                        "count": _safe_int(row.get("low_count")),
                        "average_raf_score": round(_safe_float(row.get("low_avg")), 4),
                    },
                    "medium": {
                        "count": _safe_int(row.get("med_count")),
                        "average_raf_score": round(_safe_float(row.get("med_avg")), 4),
                    },
                    "high": {
                        "count": _safe_int(row.get("high_count")),
                        "average_raf_score": round(_safe_float(row.get("high_avg")), 4),
                    },
                    "very_high": {
                        "count": _safe_int(row.get("vh_count")),
                        "average_raf_score": round(_safe_float(row.get("vh_avg")), 4),
                    },
                }
    except Exception as exc:
        logger.warning("get_patient_risk_stratification: tier query failed: %s", exc)

    # --- Rising risk patients -------------------------------------------
    rising_risk: list[dict[str, Any]] = []
    try:
        with raf_cursor() as cur:
            cur.execute(
                """
                SELECT
                    cur.patient_id,
                    prior.raf_score     AS prior_raf,
                    cur.raf_score       AS current_raf,
                    (cur.raf_score - prior.raf_score) AS delta
                FROM raf_scores cur
                JOIN raf_scores prior ON prior.patient_id = cur.patient_id
                                      AND prior.measurement_year = %s
                                      AND prior.score_type = 'prospective'
                JOIN patients p ON p.id = cur.patient_id
                WHERE cur.measurement_year = %s
                  AND cur.score_type = 'prospective'
                  AND p.is_active = 1
                  AND p.tenant_id = %s
                  AND (cur.raf_score - prior.raf_score) >= 0.3
                ORDER BY delta DESC
                LIMIT 20
                """,
                (prior_year, current_year, tid),
            )
            for r in cur.fetchall():
                rising_risk.append(
                    {
                        "patient_id": _safe_int(r.get("patient_id")),
                        "prior_raf": round(_safe_float(r.get("prior_raf")), 4),
                        "current_raf": round(_safe_float(r.get("current_raf")), 4),
                        "delta": round(_safe_float(r.get("delta")), 4),
                    }
                )
    except Exception as exc:
        logger.warning("get_patient_risk_stratification: rising-risk query failed: %s", exc)

    return {
        "measurement_year": current_year,
        "total_patients": total_patients,
        "tiers": tiers,
        "rising_risk_patients": rising_risk,
    }
