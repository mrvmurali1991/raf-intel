"""
Real-time clinical intelligence insights router.

Endpoint
--------
GET /api/insights             – Primary endpoint (also at /api/dashboard/insights).
                               Array of data-driven insights generated from
                               live RAF and OpenEMR database state.

Each insight is derived from a single, efficient SQL query against real data.
Query failures are isolated — one bad query never blocks the rest.
"""
# Removed: from __future__ import annotations (breaks FastAPI schema generation)

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends

from app.auth import get_current_user
from app.db import NoActiveEMRConnection, openemr_cursor, raf_cursor
from app.services.emr_manager import active_patients_subquery

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["Dashboard"])

# CMS Medicare Advantage per-member per-year benchmark rate used for all
# revenue estimates.  $12,000 is a rounded population average; $10,400 is the
# conservative floor used in reports.py.  We use $12,000 here for forward-
# looking opportunity sizing.
_PMPY = 12_000


# ---------------------------------------------------------------------------
# Priority ordering helper
# ---------------------------------------------------------------------------

_PRIORITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3}


def _sort_key(insight: dict) -> int:
    return _PRIORITY_ORDER.get(insight.get("priority", "low"), 99)


def _uid() -> str:
    return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Insight generators — each returns a dict or None on failure
# ---------------------------------------------------------------------------


def _suspect_conditions_summary(now: str, tenant_id: str | None = None) -> dict | None:
    """Insight 1: Open suspect conditions — total count, patients, revenue."""
    _tid = int(tenant_id) if tenant_id is not None else 1
    _sf, _sp = active_patients_subquery(_tid)
    try:
        with raf_cursor() as cur:
            cur.execute(
                f"""
                SELECT
                    COUNT(*)                             AS total_suspects,
                    COUNT(DISTINCT patient_id)           AS patients_affected,
                    AVG(confidence_score)                AS avg_confidence,
                    COUNT(DISTINCT evidence_type)        AS evidence_types
                FROM raf_suspect_conditions
                WHERE status = 'open'
                  AND {_sf}
                  AND raf_suspect_conditions.tenant_id = %s
                """,
                (*_sp, _tid),
            )
            row = cur.fetchone()

        if not row or not row["total_suspects"]:
            return None

        total = int(row["total_suspects"])
        patients = int(row["patients_affected"])
        # Average RAF coefficient for an HCC is ~0.35; multiply by PMPY for
        # per-suspect revenue opportunity.
        avg_coeff = 0.35
        revenue = int(total * avg_coeff * _PMPY)
        priority = "critical" if total > 20 else "high" if total > 10 else "medium"

        return {
            "id": _uid(),
            "category": "revenue",
            "priority": priority,
            "title": f"{total} Open Suspect Conditions Awaiting Review",
            "description": (
                f"{total} unreviewed suspect conditions across {patients} patients "
                f"represent an estimated ${revenue:,} in uncaptured annual revenue. "
                f"Conditions span {int(row['evidence_types'])} evidence types."
            ),
            "metric_value": f"${revenue:,}",
            "action_label": "Review Suspects",
            "action_href": "/suspects",
            "icon": "dollar",
            "generated_at": now,
        }
    except Exception as exc:
        logger.warning("insights: suspect_conditions_summary failed: %s", exc)
        return None


def _hcc_recapture_gaps(now: str, tenant_id: str | None = None) -> dict | None:
    """Insight 2: HCCs captured in prior year not yet seen in current year."""
    try:
        with raf_cursor() as cur:
            cur.execute(
                """
                SELECT
                    COUNT(*)               AS gap_count,
                    COUNT(DISTINCT p.patient_id) AS patients_at_risk,
                    COALESCE(SUM(p.raf_coefficient), 0) AS total_coefficient
                FROM raf_patient_hcc p
                WHERE p.measurement_year = YEAR(CURDATE()) - 1
                  AND p.patient_id IN (SELECT id FROM patients WHERE is_active = 1 AND tenant_id = %s)
                  AND p.tenant_id = %s
                  AND NOT EXISTS (
                      SELECT 1
                      FROM raf_patient_hcc c
                      WHERE c.patient_id       = p.patient_id
                        AND c.hcc_code         = p.hcc_code
                        AND c.measurement_year = YEAR(CURDATE())
                  )
                """,
                (str(tenant_id) if tenant_id is not None else "1",
                 str(tenant_id) if tenant_id is not None else "1"),
            )
            row = cur.fetchone()

        if not row or not row["gap_count"]:
            return None

        gap_count = int(row["gap_count"])
        patients = int(row["patients_at_risk"])
        revenue = int(float(row["total_coefficient"]) * _PMPY)
        priority = "critical" if gap_count > 50 else "high" if gap_count > 20 else "medium"

        return {
            "id": _uid(),
            "category": "revenue",
            "priority": priority,
            "title": f"{gap_count} HCCs at Risk of Not Being Recaptured",
            "description": (
                f"{gap_count} HCC codes documented in the prior year have not yet "
                f"appeared in current-year billing across {patients} patients, "
                f"putting ${revenue:,} in annual revenue at risk."
            ),
            "metric_value": f"{gap_count} HCCs",
            "action_label": "View Recapture Gaps",
            "action_href": "/reports/recapture-gaps",
            "icon": "alert",
            "generated_at": now,
        }
    except Exception as exc:
        logger.warning("insights: hcc_recapture_gaps failed: %s", exc)
        return None


def _high_risk_unreviewed(now: str, tenant_id: str | None = None) -> dict | None:
    """Insight 3: High-RAF patients (>= 2.0) with open suspect conditions."""
    try:
        with raf_cursor() as cur:
            cur.execute(
                """
                SELECT
                    COUNT(DISTINCT rs.patient_id) AS patient_count,
                    AVG(rs.final_raf)             AS avg_raf,
                    COUNT(rsc.id)                 AS open_suspects
                FROM raf_scores rs
                JOIN raf_suspect_conditions rsc
                  ON rsc.patient_id = rs.patient_id
                 AND rsc.status     = 'open'
                WHERE rs.final_raf          >= 2.0
                  AND rs.measurement_year   = YEAR(CURDATE())
                  AND rs.patient_id IN (SELECT id FROM patients WHERE is_active = 1)
                  AND rs.tenant_id = %s
                """,
                (str(tenant_id) if tenant_id is not None else "1",),
            )
            row = cur.fetchone()

        if not row or not row["patient_count"]:
            return None

        patient_count = int(row["patient_count"])
        open_suspects = int(row["open_suspects"])
        avg_raf = round(float(row["avg_raf"]), 2)
        # Revenue at risk = patients * avg_raf * PMPY (each open suspect could
        # keep the risk score from being validated)
        revenue_at_risk = int(patient_count * avg_raf * _PMPY)
        priority = "critical" if patient_count > 10 else "high"

        return {
            "id": _uid(),
            "category": "clinical",
            "priority": priority,
            "title": f"{patient_count} High-Risk Patients Have Unreviewed Suspects",
            "description": (
                f"{patient_count} patients with an average RAF of {avg_raf} each have "
                f"open suspect conditions (total {open_suspects}). "
                f"These represent ${revenue_at_risk:,} in revenue requiring clinical validation."
            ),
            "metric_value": f"{patient_count} patients",
            "action_label": "Review Now",
            "action_href": "/patients?filter=high-risk",
            "icon": "alert",
            "generated_at": now,
        }
    except Exception as exc:
        logger.warning("insights: high_risk_unreviewed failed: %s", exc)
        return None


def _provider_coding_variation(now: str, tenant_id: str | None = None) -> dict | None:
    """Insight 4: Spread between highest and lowest average RAF by provider."""
    try:
        with raf_cursor() as cur:
            cur.execute(
                """
                SELECT
                    p.full_name,
                    ROUND(AVG(rs.final_raf), 3) AS avg_raf,
                    COUNT(DISTINCT rs.patient_id) AS patient_count
                FROM providers p
                JOIN provider_patient_panel ppp ON ppp.provider_id = p.id
                JOIN raf_scores rs
                  ON rs.patient_id       = ppp.patient_id
                 AND rs.measurement_year = YEAR(CURDATE())
                WHERE p.status = 'active'
                  AND rs.patient_id IN (SELECT id FROM patients WHERE is_active = 1)
                  AND rs.tenant_id = %s
                GROUP BY p.id, p.full_name
                HAVING patient_count >= 5
                ORDER BY avg_raf DESC
                LIMIT 10
                """,
                (str(tenant_id) if tenant_id is not None else "1",),
            )
            rows = cur.fetchall()

        if not rows or len(rows) < 2:
            return None

        highest = rows[0]
        lowest = rows[-1]
        spread = round(float(highest["avg_raf"]) - float(lowest["avg_raf"]), 3)

        if spread < 0.1:
            return None

        priority = "high" if spread > 0.5 else "medium"

        return {
            "id": _uid(),
            "category": "quality",
            "priority": priority,
            "title": f"RAF Coding Spread of {spread} Across Providers",
            "description": (
                f"Dr. {highest['full_name']} averages RAF {highest['avg_raf']} "
                f"({highest['patient_count']} patients) vs Dr. {lowest['full_name']} "
                f"at {lowest['avg_raf']} ({lowest['patient_count']} patients). "
                f"A {spread} spread may indicate under-coding or documentation gaps."
            ),
            "metric_value": f"{spread} RAF spread",
            "action_label": "View Provider Analytics",
            "action_href": "/providers",
            "icon": "chart",
            "generated_at": now,
        }
    except Exception as exc:
        logger.warning("insights: provider_coding_variation failed: %s", exc)
        return None


def _ckd_stage_upgrades(now: str, tenant_id: str | None = None) -> dict | None:
    """Insight 5: CKD staging upgrade opportunities (N18.x suspect conditions)."""
    _tid = int(tenant_id) if tenant_id is not None else 1
    _sf, _sp = active_patients_subquery(_tid)
    try:
        with raf_cursor() as cur:
            cur.execute(
                f"""
                SELECT
                    COUNT(*)                        AS total,
                    COUNT(DISTINCT patient_id)      AS patients,
                    ROUND(AVG(confidence_score), 2) AS avg_confidence
                FROM raf_suspect_conditions
                WHERE suspect_icd10 LIKE 'N18%'
                  AND status = 'open'
                  AND {_sf}
                  AND raf_suspect_conditions.tenant_id = %s
                """,
                (*_sp, _tid),
            )
            row = cur.fetchone()

        if not row or not row["total"]:
            return None

        total = int(row["total"])
        patients = int(row["patients"])
        avg_conf = float(row["avg_confidence"] or 0)
        # CKD staging upgrades (e.g. N18.3 -> N18.4) carry a coefficient
        # delta of ~0.18–0.37; use 0.25 as the midpoint.
        revenue = int(total * 0.25 * _PMPY)
        priority = "critical" if total > 5 else "high"

        return {
            "id": _uid(),
            "category": "clinical",
            "priority": priority,
            "title": f"{total} CKD Stage Upgrade Opportunities Identified",
            "description": (
                f"{total} patients across {patients} records have suspect CKD staging "
                f"codes (N18.x) with {avg_conf:.0%} average confidence. "
                f"Documenting the correct CKD stage could add ${revenue:,} in annual revenue."
            ),
            "metric_value": f"${revenue:,}",
            "action_label": "Review CKD Suspects",
            "action_href": "/suspects?icd=N18",
            "icon": "trending",
            "generated_at": now,
        }
    except Exception as exc:
        logger.warning("insights: ckd_stage_upgrades failed: %s", exc)
        return None


def _unanalyzed_patient_coverage(now: str, tenant_id: str | None = None) -> dict | None:
    """Insight 6: Patients in OpenEMR not yet analyzed by the RAF engine."""
    try:
        # Total patients from raf_intelligence.patients table (tenant-scoped)
        try:
            with raf_cursor() as cur:
                if tenant_id is not None:
                    cur.execute(
                        "SELECT COUNT(*) AS total FROM patients WHERE is_active = 1 AND tenant_id = %s",
                        (tenant_id,),
                    )
                else:
                    cur.execute("SELECT COUNT(*) AS total FROM patients WHERE is_active = 1")
                emr_row = cur.fetchone()
            total_emr = int(emr_row["total"]) if emr_row else 0
        except Exception as exc:
            logger.debug("insights: patients table unavailable for coverage check: %s", exc)
            total_emr = None

        with raf_cursor() as cur:
            cur.execute(
                f"SELECT COUNT(DISTINCT pid) AS analyzed FROM raf_encounter_analysis WHERE {_ACTIVE_PIDS_SUBQUERY}"
            )
            raf_row = cur.fetchone()
        analyzed = int(raf_row["analyzed"]) if raf_row else 0

        if total_emr is None:
            # Fall back: show what we have analyzed without a denominator
            if not analyzed:
                return None
            return {
                "id": _uid(),
                "category": "workflow",
                "priority": "medium",
                "title": f"{analyzed} Patients Have Been Analyzed by the RAF Engine",
                "description": (
                    f"The RAF engine has completed analysis for {analyzed} patients. "
                    "Connect your EMR to see full population coverage metrics."
                ),
                "metric_value": f"{analyzed} analyzed",
                "action_label": "Configure EMR",
                "action_href": "/settings/emr",
                "icon": "users",
                "generated_at": now,
            }

        gap = max(0, total_emr - analyzed)
        coverage_pct = round((analyzed / total_emr) * 100, 1) if total_emr else 0
        priority = "high" if coverage_pct < 80 else "medium" if coverage_pct < 95 else "low"

        return {
            "id": _uid(),
            "category": "workflow",
            "priority": priority,
            "title": f"{gap} Patients Not Yet Analyzed ({coverage_pct}% Coverage)",
            "description": (
                f"The RAF engine has analyzed {analyzed} of {total_emr} total EMR patients "
                f"({coverage_pct}% coverage). "
                f"{gap} patients have no RAF encounter analysis on record."
            ),
            "metric_value": f"{coverage_pct}% coverage",
            "action_label": "Run Analysis",
            "action_href": "/jobs",
            "icon": "users",
            "generated_at": now,
        }
    except Exception as exc:
        logger.warning("insights: unanalyzed_patient_coverage failed: %s", exc)
        return None


def _data_freshness(now: str) -> dict | None:
    """Insight 7: How recently data was synced and analyzed."""
    try:
        with raf_cursor() as cur:
            cur.execute(
                """
                SELECT
                    MAX(analyzed_at) AS last_analysis,
                    COUNT(*)         AS total_encounters
                FROM raf_encounter_analysis
                """
            )
            analysis_row = cur.fetchone()

            cur.execute(
                """
                SELECT
                    updated_at AS last_sync,
                    display_name,
                    vendor
                FROM emr_connections
                WHERE is_active = 1
                ORDER BY updated_at DESC
                LIMIT 1
                """
            )
            conn_row = cur.fetchone()

        last_analysis = analysis_row["last_analysis"] if analysis_row else None
        last_sync = conn_row["last_sync"] if conn_row else None
        total_enc = int(analysis_row["total_encounters"]) if analysis_row else 0

        if not last_analysis and not last_sync:
            return {
                "id": _uid(),
                "category": "compliance",
                "priority": "high",
                "title": "No Data Synchronization Has Occurred Yet",
                "description": (
                    "No EMR sync or encounter analysis records were found. "
                    "Configure an EMR connection and run the initial analysis job."
                ),
                "metric_value": "Never synced",
                "action_label": "Configure EMR",
                "action_href": "/settings/emr",
                "icon": "clock",
                "generated_at": now,
            }

        # Determine staleness
        ref = datetime.now(timezone.utc)
        staleness_hours: float | None = None
        if last_analysis:
            if hasattr(last_analysis, "tzinfo") and last_analysis.tzinfo is None:
                last_analysis = last_analysis.replace(tzinfo=timezone.utc)
            staleness_hours = (ref - last_analysis).total_seconds() / 3600

        display_dt = (
            last_analysis.strftime("%Y-%m-%d %H:%M UTC")
            if last_analysis
            else "unknown"
        )
        emr_label = (
            f"{conn_row['display_name']} ({conn_row['vendor']})" if conn_row else "Unknown EMR"
        )

        if staleness_hours is not None and staleness_hours > 48:
            priority = "high"
            stale_msg = f"Last analysis was {staleness_hours:.0f} hours ago — data may be stale."
        elif staleness_hours is not None and staleness_hours > 24:
            priority = "medium"
            stale_msg = f"Last analysis was {staleness_hours:.0f} hours ago."
        else:
            priority = "low"
            stale_msg = "Data is current."

        return {
            "id": _uid(),
            "category": "compliance",
            "priority": priority,
            "title": f"Data Last Analyzed: {display_dt}",
            "description": (
                f"{total_enc} encounter records analyzed from {emr_label}. "
                f"{stale_msg}"
            ),
            "metric_value": display_dt,
            "action_label": "View Sync Status",
            "action_href": "/settings/emr",
            "icon": "clock",
            "generated_at": now,
        }
    except Exception as exc:
        logger.warning("insights: data_freshness failed: %s", exc)
        return None


def _top_revenue_patient(now: str) -> dict | None:
    """Insight 8: Single patient with the highest revenue gap (AI RAF vs billed RAF)."""
    try:
        with raf_cursor() as cur:
            cur.execute(
                f"""
                SELECT
                    ea.pid,
                    ea.overall_score                       AS ai_score,
                    COALESCE(rs.final_raf, 0)             AS billed_raf,
                    ROUND(ea.overall_score - COALESCE(rs.final_raf, 0), 3) AS raf_gap,
                    ea.hcc_opportunity_count
                FROM raf_encounter_analysis ea
                LEFT JOIN raf_scores rs
                  ON rs.patient_id       = ea.pid
                 AND rs.measurement_year = YEAR(CURDATE())
                WHERE ea.overall_score > COALESCE(rs.final_raf, 0)
                  AND {_ACTIVE_PIDS_SUBQUERY.replace("pid IN", "ea.pid IN")}
                ORDER BY raf_gap DESC
                LIMIT 1
                """
            )
            row = cur.fetchone()

        if not row or not row["raf_gap"]:
            return None

        pid = row["pid"]
        raf_gap = round(float(row["raf_gap"]), 3)
        ai_score = round(float(row["ai_score"]), 3)
        billed = round(float(row["billed_raf"]), 3)
        revenue_gap = int(raf_gap * _PMPY)
        opportunities = int(row["hcc_opportunity_count"] or 0)

        return {
            "id": _uid(),
            "category": "revenue",
            "priority": "high",
            "title": f"Top Revenue Patient: ${revenue_gap:,} Gap for Patient #{pid}",
            "description": (
                f"Patient #{pid} has an AI-calculated RAF of {ai_score} vs billed RAF "
                f"of {billed} — a gap of {raf_gap} translating to ${revenue_gap:,} "
                f"in uncaptured annual revenue across {opportunities} HCC opportunities."
            ),
            "metric_value": f"${revenue_gap:,}",
            "action_label": "View Patient",
            "action_href": f"/patients/{pid}",
            "icon": "dollar",
            "generated_at": now,
        }
    except Exception as exc:
        logger.warning("insights: top_revenue_patient failed: %s", exc)
        return None


def _medication_signal_alerts(now: str, tenant_id: str | None = None) -> dict | None:
    """Insight 9: Medication-based suspect conditions — high-confidence signals."""
    _tid = int(tenant_id) if tenant_id is not None else 1
    _sf, _sp = active_patients_subquery(_tid)
    try:
        with raf_cursor() as cur:
            cur.execute(
                f"""
                SELECT
                    COUNT(*)                             AS total,
                    COUNT(DISTINCT patient_id)           AS patients,
                    ROUND(AVG(confidence_score), 3)      AS avg_confidence,
                    COUNT(DISTINCT suspect_hcc)          AS distinct_hccs
                FROM raf_suspect_conditions
                WHERE evidence_type = 'medication'
                  AND status        = 'open'
                  AND {_sf}
                  AND raf_suspect_conditions.tenant_id = %s
                """,
                (*_sp, _tid),
            )
            row = cur.fetchone()

        if not row or not row["total"]:
            return None

        total = int(row["total"])
        patients = int(row["patients"])
        avg_conf = float(row["avg_confidence"] or 0)
        hcc_types = int(row["distinct_hccs"])
        revenue = int(total * 0.35 * _PMPY)
        priority = "high" if avg_conf >= 0.80 else "medium"

        return {
            "id": _uid(),
            "category": "clinical",
            "priority": priority,
            "title": f"{total} Medication-Derived HCC Signals Need Review",
            "description": (
                f"{total} suspect conditions across {patients} patients were flagged "
                f"from medication records with {avg_conf:.0%} average confidence, "
                f"covering {hcc_types} distinct HCC categories and ~${revenue:,} opportunity."
            ),
            "metric_value": f"{avg_conf:.0%} confidence",
            "action_label": "View Medication Signals",
            "action_href": "/suspects?evidence=medication",
            "icon": "shield",
            "generated_at": now,
        }
    except Exception as exc:
        logger.warning("insights: medication_signal_alerts failed: %s", exc)
        return None


def _data_completeness_warning(now: str, tenant_id: str | None = None) -> dict | None:
    """Insight 10: Patients with no billing codes and no problem list entries."""
    try:
        try:
            # Get active patients with emr_pid from raf_intelligence.patients
            # (tenant-scoped), then check OpenEMR clinical tables for completeness
            with raf_cursor() as cur:
                if tenant_id is not None:
                    cur.execute(
                        "SELECT id, emr_pid FROM patients WHERE is_active = 1 AND emr_pid IS NOT NULL AND tenant_id = %s",
                        (tenant_id,),
                    )
                else:
                    cur.execute(
                        "SELECT id, emr_pid FROM patients WHERE is_active = 1 AND emr_pid IS NOT NULL"
                    )
                patient_rows = cur.fetchall()

            if not patient_rows:
                return None

            emr_pids = [r["emr_pid"] for r in patient_rows]
            fmt = ",".join(["%s"] * len(emr_pids))

            with openemr_cursor() as cur:
                cur.execute(
                    f"""
                    SELECT COUNT(*) AS incomplete
                    FROM patient_data pd
                    WHERE pd.pid IN ({fmt})
                      AND NOT EXISTS (
                          SELECT 1
                          FROM billing b
                          WHERE b.pid      = pd.pid
                            AND b.activity = 1
                      )
                      AND NOT EXISTS (
                          SELECT 1
                          FROM lists l
                          WHERE l.pid      = pd.pid
                            AND l.type     = 'medical_problem'
                            AND l.activity = 1
                      )
                    """,
                    emr_pids,
                )
                row = cur.fetchone()
        except (NoActiveEMRConnection, Exception) as exc:
            logger.debug("insights: openemr unavailable for completeness check: %s", exc)
            return None

        if not row or not row["incomplete"]:
            return None

        incomplete = int(row["incomplete"])
        priority = "high" if incomplete > 50 else "medium" if incomplete > 10 else "low"

        return {
            "id": _uid(),
            "category": "compliance",
            "priority": priority,
            "title": f"{incomplete} Patients Have Incomplete Clinical Records",
            "description": (
                f"{incomplete} patients in OpenEMR have neither active billing codes "
                "nor a documented problem list. These patients cannot be accurately "
                "risk-scored and may represent compliance gaps."
            ),
            "metric_value": f"{incomplete} patients",
            "action_label": "View Incomplete Records",
            "action_href": "/reports/data-completeness",
            "icon": "shield",
            "generated_at": now,
        }
    except Exception as exc:
        logger.warning("insights: data_completeness_warning failed: %s", exc)
        return None


# ---------------------------------------------------------------------------
# Ordered list of all generators
# ---------------------------------------------------------------------------

_GENERATORS = [
    _suspect_conditions_summary,
    _hcc_recapture_gaps,
    _high_risk_unreviewed,
    _provider_coding_variation,
    _ckd_stage_upgrades,
    _unanalyzed_patient_coverage,
    _data_freshness,
    _top_revenue_patient,
    _medication_signal_alerts,
    _data_completeness_warning,
]


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------

@router.get("/insights", summary="Real-time clinical intelligence insights", include_in_schema=False)
@router.get("/dashboard/insights", summary="Real-time clinical intelligence insights")
def get_insights(current_user: dict = Depends(get_current_user)) -> dict[str, Any]:
    """Return a prioritized list of data-driven clinical insights.

    Each insight is generated by a dedicated SQL query against live RAF and
    OpenEMR data.  Individual query failures are caught and logged; the
    endpoint always returns a valid response even when some generators fail.

    Insights are sorted: critical > high > medium > low.
    """
    import inspect as _inspect
    now = datetime.now(timezone.utc).isoformat()
    tenant_id = str(current_user.get("tenant_id", "1")) if current_user else "1"
    insights: list[dict] = []

    for generator in _GENERATORS:
        try:
            # Pass tenant_id to generators that accept it; older ones ignore.
            sig = _inspect.signature(generator)
            if "tenant_id" in sig.parameters:
                result = generator(now, tenant_id=tenant_id)
            else:
                result = generator(now)
        except Exception as exc:
            logger.warning("insight generator %s failed: %s", getattr(generator, "__name__", "?"), exc)
            result = None
        if result is not None:
            insights.append(result)

    insights.sort(key=_sort_key)

    return {
        "insights": insights,
        "generated_at": now,
        "count": len(insights),
    }
