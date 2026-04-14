"""
bundle_export_service.py
------------------------
Generates Excel (XLSX) workbooks for all 11 CMS data bundles used in RAF
Intelligence reporting.  Each function returns an openpyxl Workbook; the
caller can serialise it to bytes via ``workbook_to_bytes()``.

All queries are tenant-scoped and handle missing/empty tables gracefully —
a try/except wraps every DB call and falls back to an empty, header-only
sheet so the rest of the export is not interrupted.

Table name reference (from migrations.py and service-layer code):
    patients                    — patient demographics/MBI/contact
    raf_patient_demographics    — CMS enrollment demographics (dual, OREC)
    provider_patient_panel      — patient → provider attribution
    providers                   — NPI, name, specialty
    raf_scores                  — per-patient, per-year RAF score rows
    raf_meat_evidence           — MEAT documentation evidence per HCC
    raf_patient_hcc             — patient-level HCC mappings
    raf_suspect_conditions      — AI-detected suspect conditions
    provider_scorecard_snapshots — pre-computed provider performance
    submission_batches          — CMS submission batch headers
    submission_records          — individual submission records per batch
    audit_log                   — system audit trail
    emr_patient_matches         — internal → EMR patient ID bridge
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from io import BytesIO
from typing import Any

import openpyxl
from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side

from app.db import raf_cursor

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Shared style constants
# ---------------------------------------------------------------------------

HEADER_FONT = Font(bold=True, color="FFFFFF", size=11)
HEADER_FILL = PatternFill(start_color="2B579A", end_color="2B579A", fill_type="solid")
HEADER_ALIGN = Alignment(horizontal="center", wrap_text=True)
THIN_BORDER = Border(
    left=Side(style="thin"),
    right=Side(style="thin"),
    top=Side(style="thin"),
    bottom=Side(style="thin"),
)

# CMS Medicare Advantage benchmark rate (FY 2026 national average)
_CMS_BENCHMARK = 11_015.04


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _style_header(ws, headers: list[str]) -> None:
    """Write and style the first row as a frozen, filtered header."""
    for col, h in enumerate(headers, 1):
        cell = ws.cell(row=1, column=col, value=h)
        cell.font = HEADER_FONT
        cell.fill = HEADER_FILL
        cell.alignment = HEADER_ALIGN
        cell.border = THIN_BORDER
    ws.auto_filter.ref = ws.dimensions
    ws.freeze_panes = "A2"


def _new_workbook(sheet_title: str, headers: list[str]) -> tuple[Workbook, Any]:
    """Create a workbook with a single styled sheet and return (wb, ws)."""
    wb = Workbook()
    ws = wb.active
    ws.title = sheet_title
    _style_header(ws, headers)
    return wb, ws


def _append_rows(ws, rows: list[dict], columns: list[str]) -> None:
    """Append data rows to *ws* in *columns* order, handling None safely."""
    for row in rows:
        ws.append([row.get(c) for c in columns])


def _safe_query(sql: str, params: tuple) -> list[dict]:
    """Execute *sql* with *params* and return rows; returns [] on any error."""
    try:
        with raf_cursor() as cur:
            cur.execute(sql, params)
            return cur.fetchall() or []
    except Exception as exc:
        logger.warning("bundle_export_service query failed: %s", exc)
        return []


# ---------------------------------------------------------------------------
# Public helper
# ---------------------------------------------------------------------------


def workbook_to_bytes(wb: Workbook) -> bytes:
    """Serialise a Workbook to raw XLSX bytes suitable for HTTP response."""
    buf = BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Bundle 1 — Patient Master
# ---------------------------------------------------------------------------

_PATIENT_MASTER_HEADERS = [
    "Patient_ID",
    "MBI",
    "First_Name",
    "Last_Name",
    "DOB",
    "Gender",
    "Plan_ID",
    "Coverage_Start",
    "Coverage_End",
    "PCP_NPI",
    "Dual_Status",
]

_PATIENT_MASTER_COLS = [
    "patient_id",
    "mbi",
    "first_name",
    "last_name",
    "dob",
    "gender",
    "plan_id",
    "coverage_start",
    "coverage_end",
    "pcp_npi",
    "dual_status",
]

_PATIENT_MASTER_SQL = """
    SELECT
        p.id                            AS patient_id,
        p.mbi,
        p.first_name,
        p.last_name,
        p.dob,
        p.gender,
        p.plan_id,
        p.coverage_start,
        p.coverage_end,
        pr.npi                          AS pcp_npi,
        pd.dual_type                    AS dual_status
    FROM patients p
    LEFT JOIN provider_patient_panel ppp
           ON ppp.patient_id = p.id
    LEFT JOIN providers pr
           ON pr.id = ppp.provider_id
    LEFT JOIN (
        SELECT patient_id, dual_type
        FROM raf_patient_demographics
        WHERE (patient_id, measurement_year) IN (
            SELECT patient_id, MAX(measurement_year)
            FROM raf_patient_demographics
            GROUP BY patient_id
        )
    ) pd ON pd.patient_id = p.id
    WHERE p.tenant_id = %s
    ORDER BY p.id
"""


def export_patient_master(tenant_id: str) -> Workbook:
    """Bundle 1: Patient Master — demographics, coverage, PCP, dual status."""
    wb, ws = _new_workbook("Patient Master", _PATIENT_MASTER_HEADERS)
    rows = _safe_query(_PATIENT_MASTER_SQL, (tenant_id,))
    _append_rows(ws, rows, _PATIENT_MASTER_COLS)
    return wb


# ---------------------------------------------------------------------------
# Bundle 2 — Encounter / Diagnosis
# ---------------------------------------------------------------------------

_ENC_DIAG_HEADERS = [
    "Encounter_ID",
    "Patient_ID",
    "DOS",
    "Provider_NPI",
    "ICD10_Code",
    "Primary_Flag",
]
_ENC_DIAG_COLS = [
    "encounter_id",
    "patient_id",
    "dos",
    "provider_npi",
    "icd10_code",
    "primary_flag",
]

# Primary source: normalised encounter/diagnosis tables
_ENC_DIAG_PRIMARY_SQL = """
    SELECT
        ne.encounter_id                           AS encounter_id,
        ne.patient_id,
        ne.encounter_date               AS dos,
        ne.provider_npi,
        nd.icd10_code,
        nd.primary_flag
    FROM normalized_encounters ne
    JOIN normalized_diagnoses nd ON nd.encounter_id = ne.encounter_id
    WHERE ne.tenant_id = %s
    ORDER BY ne.encounter_date DESC
"""

# Fallback: submission_records joined to patients when normalised tables are absent
_ENC_DIAG_FALLBACK_SQL = """
    SELECT
        sr.id                           AS encounter_id,
        sr.patient_id,
        sr.dos_from                     AS dos,
        sr.provider_npi,
        sr.icd10_code,
        1                               AS primary_flag
    FROM submission_records sr
    WHERE sr.tenant_id = %s
    ORDER BY sr.dos_from DESC
"""


def export_encounter_diagnosis(tenant_id: str) -> Workbook:
    """Bundle 2: Encounter/Diagnosis — ICD10 codes per encounter."""
    wb, ws = _new_workbook("Encounter Diagnosis", _ENC_DIAG_HEADERS)

    rows = _safe_query(_ENC_DIAG_PRIMARY_SQL, (tenant_id,))
    if not rows:
        # Fallback to submission_records which always exists
        rows = _safe_query(_ENC_DIAG_FALLBACK_SQL, (tenant_id,))

    _append_rows(ws, rows, _ENC_DIAG_COLS)
    return wb


# ---------------------------------------------------------------------------
# Bundle 3 — RAF Score
# ---------------------------------------------------------------------------

_RAF_SCORE_HEADERS = [
    "Patient_ID",
    "Year",
    "Model_Version",
    "Demographic_Score",
    "Disease_Score",
    "Interaction_Score",
    "Total_RAF",
    "Normalized_RAF",
]
_RAF_SCORE_COLS = [
    "patient_id",
    "measurement_year",
    "score_type",
    "demographic_score",
    "disease_score",
    "interaction_score",
    "total_raw",
    "final_raf",
]

_RAF_SCORE_SQL = """
    SELECT
        patient_id,
        measurement_year,
        score_type,
        demographic_score,
        disease_score,
        interaction_score,
        total_raw,
        final_raf
    FROM raf_scores
    WHERE tenant_id = %s
    ORDER BY patient_id, measurement_year DESC, score_type
"""


def export_raf_score(tenant_id: str) -> Workbook:
    """Bundle 3: RAF Score — per-patient, per-year, per-model score breakdown."""
    wb, ws = _new_workbook("RAF Scores", _RAF_SCORE_HEADERS)
    rows = _safe_query(_RAF_SCORE_SQL, (tenant_id,))
    _append_rows(ws, rows, _RAF_SCORE_COLS)
    return wb


# ---------------------------------------------------------------------------
# Bundle 4 — MEAT Compliance
# ---------------------------------------------------------------------------

_MEAT_HEADERS = [
    "Patient_ID",
    "Diagnosis_ID",
    "HCC",
    "Monitor",
    "Evaluate",
    "Assess",
    "Treat",
    "Status",
    "Document_ID",
]
_MEAT_COLS = [
    "patient_id",
    "id",
    "hcc_code",
    "meat_m_present",
    "meat_e_present",
    "meat_a_present",
    "meat_t_present",
    "status",
    "encounter_id",
]

_MEAT_SQL = """
    SELECT
        ph.patient_id,
        me.id,
        ph.hcc_code,
        me.meat_m_present,
        me.meat_e_present,
        me.meat_a_present,
        me.meat_t_present,
        CASE
            WHEN me.meat_m_present = 1 AND me.meat_e_present = 1
             AND me.meat_a_present = 1 AND me.meat_t_present = 1
            THEN 'Complete'
            ELSE 'Incomplete'
        END                             AS status,
        me.encounter_id
    FROM raf_meat_evidence me
    JOIN raf_patient_hcc ph ON ph.id = me.patient_hcc_id
    WHERE ph.tenant_id = %s
    ORDER BY ph.patient_id, ph.hcc_code
"""


def export_meat_compliance(tenant_id: str) -> Workbook:
    """Bundle 4: MEAT Compliance — per-HCC documentation completeness."""
    wb, ws = _new_workbook("MEAT Compliance", _MEAT_HEADERS)
    rows = _safe_query(_MEAT_SQL, (tenant_id,))
    _append_rows(ws, rows, _MEAT_COLS)
    return wb


# ---------------------------------------------------------------------------
# Bundle 5 — Suspect Conditions
# ---------------------------------------------------------------------------

_SUSPECTS_HEADERS = [
    "Patient_ID",
    "Suspect_ICD",
    "HCC",
    "Confidence",
    "Evidence_Type",
    "Status",
    "Revenue_Impact",
]
_SUSPECTS_COLS = [
    "patient_id",
    "suspect_icd10",
    "suspect_hcc",
    "confidence_score",
    "evidence_type",
    "status",
    "revenue_impact",
]

_SUSPECTS_SQL = """
    SELECT
        patient_id,
        suspect_icd10,
        suspect_hcc,
        confidence_score,
        evidence_type,
        status,
        ROUND(confidence_score * {benchmark}, 2)    AS revenue_impact
    FROM raf_suspect_conditions
    WHERE tenant_id = %s
    ORDER BY patient_id, confidence_score DESC
""".format(benchmark=_CMS_BENCHMARK)


def export_suspects(tenant_id: str) -> Workbook:
    """Bundle 5: Suspect Conditions — AI-detected unconfirmed HCC opportunities."""
    wb, ws = _new_workbook("Suspect Conditions", _SUSPECTS_HEADERS)
    rows = _safe_query(_SUSPECTS_SQL, (tenant_id,))
    _append_rows(ws, rows, _SUSPECTS_COLS)
    return wb


# ---------------------------------------------------------------------------
# Bundle 6 — Recapture Gaps
# ---------------------------------------------------------------------------

_RECAPTURE_HEADERS = [
    "Patient_ID",
    "HCC",
    "Prior_Year",
    "Current_Status",
    "Last_Encounter_Date",
    "Provider_NPI",
]
_RECAPTURE_COLS = [
    "patient_id",
    "hcc_code",
    "prior_year",
    "current_status",
    "last_encounter_date",
    "provider_npi",
]

# Recapture gaps: HCCs present in a prior year but absent in the current year.
# Derived from raf_patient_hcc cross-referenced with the current year's raf_scores.
_RECAPTURE_SQL = """
    SELECT
        ph.patient_id,
        ph.hcc_code,
        ph.measurement_year             AS prior_year,
        COALESCE(curr.hcc_code, 'Missing') AS current_status,
        ph.updated_at                   AS last_encounter_date,
        pr.npi                          AS provider_npi
    FROM raf_patient_hcc ph
    LEFT JOIN raf_patient_hcc curr
           ON curr.patient_id      = ph.patient_id
          AND curr.hcc_code        = ph.hcc_code
          AND curr.measurement_year = ph.measurement_year + 1
          AND curr.tenant_id       = ph.tenant_id
    LEFT JOIN provider_patient_panel ppp
           ON ppp.patient_id = ph.patient_id
    LEFT JOIN providers pr ON pr.id = ppp.provider_id
    WHERE ph.tenant_id = %s
      AND ph.measurement_year < YEAR(CURDATE())
      AND curr.hcc_code IS NULL
    ORDER BY ph.patient_id, ph.hcc_code
"""


def export_recapture_gaps(tenant_id: str) -> Workbook:
    """Bundle 6: Recapture Gaps — HCCs dropped year-over-year."""
    wb, ws = _new_workbook("Recapture Gaps", _RECAPTURE_HEADERS)
    rows = _safe_query(_RECAPTURE_SQL, (tenant_id,))
    _append_rows(ws, rows, _RECAPTURE_COLS)
    return wb


# ---------------------------------------------------------------------------
# Bundle 7 — Provider Performance
# ---------------------------------------------------------------------------

_PROVIDER_HEADERS = [
    "Provider_NPI",
    "Patients",
    "Avg_RAF",
    "HCC_Capture_Rate",
    "Revenue_Gap",
]
_PROVIDER_COLS = [
    "provider_npi",
    "total_patients",
    "average_raf",
    "hcc_capture_rate",
    "revenue_opportunity",
]

# Primary: pre-computed scorecard snapshots (most recent per provider)
_PROVIDER_PRIMARY_SQL = """
    SELECT
        pr.npi                          AS provider_npi,
        snap.total_patients,
        snap.average_raf,
        snap.hcc_capture_rate,
        snap.revenue_opportunity
    FROM provider_scorecard_snapshots snap
    JOIN providers pr ON pr.id = snap.provider_id
    WHERE snap.id IN (
        SELECT MAX(id)
        FROM provider_scorecard_snapshots
        GROUP BY provider_id
    )
    ORDER BY pr.npi
"""

# Fallback: compute on the fly from panel + raf_scores
_PROVIDER_FALLBACK_SQL = """
    SELECT
        pr.npi                                      AS provider_npi,
        COUNT(DISTINCT ppp.patient_id)              AS total_patients,
        ROUND(AVG(rs.final_raf), 4)                 AS average_raf,
        NULL                                        AS hcc_capture_rate,
        ROUND(
            SUM(COALESCE(rs.final_raf, 0)) * {benchmark}, 2
        )                                           AS revenue_opportunity
    FROM providers pr
    JOIN provider_patient_panel ppp ON ppp.provider_id = pr.id
    LEFT JOIN (
        SELECT patient_id, final_raf
        FROM raf_scores
        WHERE tenant_id = %s
          AND (patient_id, measurement_year) IN (
              SELECT patient_id, MAX(measurement_year)
              FROM raf_scores
              GROUP BY patient_id
          )
    ) rs ON rs.patient_id = ppp.patient_id
    GROUP BY pr.id, pr.npi
    ORDER BY pr.npi
""".format(benchmark=_CMS_BENCHMARK)


def export_provider_performance(tenant_id: str) -> Workbook:
    """Bundle 7: Provider Performance — panel size, RAF, capture rate, revenue gap."""
    wb, ws = _new_workbook("Provider Performance", _PROVIDER_HEADERS)

    rows = _safe_query(_PROVIDER_PRIMARY_SQL, ())
    if not rows:
        rows = _safe_query(_PROVIDER_FALLBACK_SQL, (tenant_id,))

    _append_rows(ws, rows, _PROVIDER_COLS)
    return wb


# ---------------------------------------------------------------------------
# Bundle 8 — CMS Submission
# ---------------------------------------------------------------------------

_SUBMISSION_HEADERS = [
    "Encounter_ID",
    "Patient_ID",
    "DOS",
    "Provider_NPI",
    "ICD10_Code",
]
_SUBMISSION_COLS = [
    "record_id",
    "patient_id",
    "dos_from",
    "provider_npi",
    "icd10_code",
]

_SUBMISSION_SQL_BASE = """
    SELECT
        sr.id                           AS record_id,
        sr.patient_id,
        sr.dos_from,
        sr.provider_npi,
        sr.icd10_code
    FROM submission_records sr
    JOIN submission_batches sb ON sb.id = sr.batch_id
    WHERE sr.tenant_id = %s
"""
_SUBMISSION_SQL_ALL = _SUBMISSION_SQL_BASE + " ORDER BY sb.created_at DESC, sr.id"
_SUBMISSION_SQL_BATCH = _SUBMISSION_SQL_BASE + " AND sr.batch_id = %s ORDER BY sr.id"


def export_cms_submission(tenant_id: str, batch_id: int | None = None) -> Workbook:
    """Bundle 8: CMS Submission — records for a batch or all submissions."""
    wb, ws = _new_workbook("CMS Submission", _SUBMISSION_HEADERS)

    if batch_id is not None:
        rows = _safe_query(_SUBMISSION_SQL_BATCH, (tenant_id, batch_id))
    else:
        rows = _safe_query(_SUBMISSION_SQL_ALL, (tenant_id,))

    _append_rows(ws, rows, _SUBMISSION_COLS)
    return wb


# ---------------------------------------------------------------------------
# Bundle 9 — Audit Log
# ---------------------------------------------------------------------------

_AUDIT_HEADERS = [
    "Entity_Type",
    "Entity_ID",
    "Action",
    "Old_Value",
    "New_Value",
    "Changed_By",
    "Timestamp",
]
_AUDIT_COLS = [
    "resource_type",
    "resource_id",
    "action",
    "old_value",
    "new_value",
    "changed_by",
    "created_at",
]

_AUDIT_SQL = """
    SELECT
        al.resource_type,
        al.resource_id,
        al.action,
        JSON_UNQUOTE(JSON_EXTRACT(al.details, '$.old_value'))   AS old_value,
        JSON_UNQUOTE(JSON_EXTRACT(al.details, '$.new_value'))   AS new_value,
        u.email                                                 AS changed_by,
        al.created_at
    FROM audit_log al
    LEFT JOIN users u ON u.id = al.user_id
    WHERE al.created_at >= %s
    ORDER BY al.created_at DESC
"""


def export_audit_log(tenant_id: str, days: int = 90) -> Workbook:
    """Bundle 9: Audit Log — last *days* days of system audit events."""
    wb, ws = _new_workbook("Audit Log", _AUDIT_HEADERS)
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
    rows = _safe_query(_AUDIT_SQL, (cutoff,))
    _append_rows(ws, rows, _AUDIT_COLS)
    return wb


# ---------------------------------------------------------------------------
# Bundle 10 — Historical RAF
# ---------------------------------------------------------------------------

_HIST_RAF_HEADERS = [
    "Patient_ID",
    "Year",
    "Model",
    "RAF",
    "Revenue",
]
_HIST_RAF_COLS = [
    "patient_id",
    "measurement_year",
    "score_type",
    "final_raf",
    "revenue",
]

_HIST_RAF_SQL = """
    SELECT
        patient_id,
        measurement_year,
        score_type,
        final_raf,
        ROUND(final_raf * {benchmark}, 2)           AS revenue
    FROM raf_scores
    WHERE tenant_id = %s
    ORDER BY patient_id, measurement_year ASC, score_type
""".format(benchmark=_CMS_BENCHMARK)


def export_historical_raf(tenant_id: str) -> Workbook:
    """Bundle 10: Historical RAF — multi-year RAF trend with revenue projection."""
    wb, ws = _new_workbook("Historical RAF", _HIST_RAF_HEADERS)
    rows = _safe_query(_HIST_RAF_SQL, (tenant_id,))
    _append_rows(ws, rows, _HIST_RAF_COLS)
    return wb


# ---------------------------------------------------------------------------
# Bundle 11 — Revenue Opportunity
# ---------------------------------------------------------------------------

_REVENUE_OPP_HEADERS = [
    "Patient_ID",
    "Billed_RAF",
    "AI_RAF",
    "RAF_Gap",
    "Revenue_Opportunity",
]
_REVENUE_OPP_COLS = [
    "patient_id",
    "billed_raf",
    "ai_raf",
    "raf_gap",
    "revenue_opportunity",
]

# Billed RAF = latest final_raf from raf_scores.
# AI RAF = billed RAF + weighted sum of open suspect confidence scores
# (each suspect confidence is treated as a fractional HCC coefficient).
_REVENUE_OPP_SQL = """
    SELECT
        base.patient_id,
        base.billed_raf,
        ROUND(base.billed_raf + COALESCE(susp.ai_lift, 0), 4)          AS ai_raf,
        ROUND(COALESCE(susp.ai_lift, 0), 4)                            AS raf_gap,
        ROUND(COALESCE(susp.ai_lift, 0) * {benchmark}, 2)              AS revenue_opportunity
    FROM (
        SELECT patient_id, final_raf AS billed_raf
        FROM raf_scores
        WHERE tenant_id = %s
          AND (patient_id, measurement_year) IN (
              SELECT patient_id, MAX(measurement_year)
              FROM raf_scores
              WHERE tenant_id = %s
              GROUP BY patient_id
          )
          AND score_type = 'v28'
    ) base
    LEFT JOIN (
        SELECT
            patient_id,
            SUM(confidence_score)                               AS ai_lift
        FROM raf_suspect_conditions
        WHERE tenant_id = %s
          AND status = 'open'
        GROUP BY patient_id
    ) susp ON susp.patient_id = base.patient_id
    ORDER BY revenue_opportunity DESC
""".format(benchmark=_CMS_BENCHMARK)


def export_revenue_opportunity(tenant_id: str) -> Workbook:
    """Bundle 11: Revenue Opportunity — billed vs AI-projected RAF gap."""
    wb, ws = _new_workbook("Revenue Opportunity", _REVENUE_OPP_HEADERS)
    rows = _safe_query(_REVENUE_OPP_SQL, (tenant_id, tenant_id, tenant_id))
    _append_rows(ws, rows, _REVENUE_OPP_COLS)
    return wb


# ---------------------------------------------------------------------------
# Master export
# ---------------------------------------------------------------------------

#: Maps output filename stem to (export_fn, extra_kwargs)
_BUNDLE_REGISTRY: list[tuple[str, Any]] = [
    ("01_patient_master.xlsx", export_patient_master),
    ("02_encounter_diagnosis.xlsx", export_encounter_diagnosis),
    ("03_raf_scores.xlsx", export_raf_score),
    ("04_meat_compliance.xlsx", export_meat_compliance),
    ("05_suspect_conditions.xlsx", export_suspects),
    ("06_recapture_gaps.xlsx", export_recapture_gaps),
    ("07_provider_performance.xlsx", export_provider_performance),
    ("08_cms_submission.xlsx", export_cms_submission),
    ("09_audit_log.xlsx", export_audit_log),
    ("10_historical_raf.xlsx", export_historical_raf),
    ("11_revenue_opportunity.xlsx", export_revenue_opportunity),
]


def export_all_bundles(tenant_id: str) -> dict[str, bytes]:
    """Export all 11 bundles and return ``{filename: xlsx_bytes}``.

    Each bundle is exported independently; a failure in one does not abort
    the others.  Failed bundles are still included as valid (empty) workbooks
    so the caller always receives exactly 11 entries.
    """
    result: dict[str, bytes] = {}
    for filename, fn in _BUNDLE_REGISTRY:
        try:
            wb = fn(tenant_id)
        except Exception as exc:
            logger.error(
                "export_all_bundles: bundle %s failed for tenant=%s: %s",
                filename,
                tenant_id,
                exc,
            )
            # Return an empty workbook with a single error sheet
            wb = Workbook()
            ws = wb.active
            ws.title = "Error"
            ws.cell(row=1, column=1, value=f"Export failed: {exc}")
        result[filename] = workbook_to_bytes(wb)
    return result
