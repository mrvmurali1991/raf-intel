"""
CMS Data Bundles router
=======================
Provides download endpoints for all 11 CMS risk-adjustment data bundles
as Excel (XLSX) files, a combined ZIP archive, and a JSON metadata listing.

Endpoints
---------
GET  /api/bundles/list                  – JSON metadata for all 11 bundles
GET  /api/bundles/patient-master        – Bundle 01: Patient Master & Enrollment
GET  /api/bundles/encounter-diagnosis   – Bundle 02: Encounter & Diagnosis
GET  /api/bundles/raf-score             – Bundle 03: RAF Score Summary
GET  /api/bundles/meat-compliance       – Bundle 04: MEAT Compliance
GET  /api/bundles/suspects              – Bundle 05: HCC Suspects
GET  /api/bundles/recapture-gaps        – Bundle 06: Recapture Gaps
GET  /api/bundles/provider-performance  – Bundle 07: Provider Performance
GET  /api/bundles/cms-submission        – Bundle 08: CMS Submission (optional: batch_id)
GET  /api/bundles/audit-log             – Bundle 09: Audit Log (optional: days=90)
GET  /api/bundles/historical-raf        – Bundle 10: Historical RAF Trends
GET  /api/bundles/revenue-opportunity   – Bundle 11: Revenue Opportunity
GET  /api/bundles/all                   – ZIP archive of all 11 bundles

Authentication: all endpoints require a valid Bearer JWT.
"""
# Do NOT use 'from __future__ import annotations' — breaks FastAPI schema generation.

import logging
import zipfile
from io import BytesIO
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse

from app.auth import get_current_user, get_tenant_id
from app.services.bundle_export_service import (
    export_audit_log,
    export_cms_submission,
    export_encounter_diagnosis,
    export_historical_raf,
    export_meat_compliance,
    export_patient_master,
    export_provider_performance,
    export_raf_score,
    export_recapture_gaps,
    export_revenue_opportunity,
    export_suspects,
    export_all_bundles,
    workbook_to_bytes,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/bundles", tags=["CMS Data Bundles"])

# ---------------------------------------------------------------------------
# Bundle metadata — single source of truth for /list and downstream consumers
# ---------------------------------------------------------------------------

BUNDLE_METADATA: list[dict[str, Any]] = [
    {
        "id": 1,
        "name": "Patient Master & Enrollment",
        "description": "Demographic and enrollment data for all attributed patients.",
        "endpoint": "/api/bundles/patient-master",
        "filename": "01_Patient_Master.xlsx",
    },
    {
        "id": 2,
        "name": "Encounter & Diagnosis",
        "description": "All encounter records with associated ICD-10 diagnosis codes.",
        "endpoint": "/api/bundles/encounter-diagnosis",
        "filename": "02_Encounter_Diagnosis.xlsx",
    },
    {
        "id": 3,
        "name": "RAF Score Summary",
        "description": "Calculated RAF scores per patient with HCC contribution breakdown.",
        "endpoint": "/api/bundles/raf-score",
        "filename": "03_RAF_Score_Summary.xlsx",
    },
    {
        "id": 4,
        "name": "MEAT Compliance",
        "description": "MEAT criteria documentation status for each captured HCC.",
        "endpoint": "/api/bundles/meat-compliance",
        "filename": "04_MEAT_Compliance.xlsx",
    },
    {
        "id": 5,
        "name": "HCC Suspects",
        "description": "Suspected HCC conditions not yet confirmed in the current period.",
        "endpoint": "/api/bundles/suspects",
        "filename": "05_HCC_Suspects.xlsx",
    },
    {
        "id": 6,
        "name": "Recapture Gaps",
        "description": "HCCs confirmed in prior years that are missing in the current year.",
        "endpoint": "/api/bundles/recapture-gaps",
        "filename": "06_Recapture_Gaps.xlsx",
    },
    {
        "id": 7,
        "name": "Provider Performance",
        "description": "RAF capture rates, gap closure, and coding quality by provider.",
        "endpoint": "/api/bundles/provider-performance",
        "filename": "07_Provider_Performance.xlsx",
    },
    {
        "id": 8,
        "name": "CMS Submission",
        "description": "Records staged or submitted to CMS for risk-adjustment payment.",
        "endpoint": "/api/bundles/cms-submission",
        "filename": "08_CMS_Submission.xlsx",
    },
    {
        "id": 9,
        "name": "Audit Log",
        "description": "Full activity audit trail for compliance and review purposes.",
        "endpoint": "/api/bundles/audit-log",
        "filename": "09_Audit_Log.xlsx",
    },
    {
        "id": 10,
        "name": "Historical RAF Trends",
        "description": "Year-over-year RAF score and HCC count trends per patient.",
        "endpoint": "/api/bundles/historical-raf",
        "filename": "10_Historical_RAF_Trends.xlsx",
    },
    {
        "id": 11,
        "name": "Revenue Opportunity",
        "description": "Estimated revenue impact of open HCC gaps and suspect conditions.",
        "endpoint": "/api/bundles/revenue-opportunity",
        "filename": "11_Revenue_Opportunity.xlsx",
    },
]


# ---------------------------------------------------------------------------
# Internal helper
# ---------------------------------------------------------------------------

def _xlsx_response(wb: Any, filename: str) -> StreamingResponse:
    """Convert an openpyxl Workbook to a streaming XLSX download response."""
    try:
        data = workbook_to_bytes(wb)
    except Exception as exc:
        logger.error("Failed to serialise workbook '%s': %s", filename, exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to generate Excel file")
    return StreamingResponse(
        BytesIO(data),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ---------------------------------------------------------------------------
# Metadata listing
# ---------------------------------------------------------------------------

@router.get(
    "/list",
    summary="List all available CMS data bundles",
    description=(
        "Returns metadata for all 11 CMS risk-adjustment data bundles, "
        "including download endpoints and expected filenames."
    ),
)
def list_bundles(
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
) -> dict[str, Any]:
    return {
        "count": len(BUNDLE_METADATA),
        "bundles": BUNDLE_METADATA,
    }


# ---------------------------------------------------------------------------
# Bundle 01 — Patient Master & Enrollment
# ---------------------------------------------------------------------------

@router.get(
    "/patient-master",
    summary="Bundle 01 — Patient Master & Enrollment",
    description="Downloads demographic and enrollment data for all attributed patients as XLSX.",
)
def download_patient_master(
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
) -> StreamingResponse:
    try:
        wb = export_patient_master(tenant_id)
    except Exception as exc:
        logger.error("export_patient_master failed (tenant=%s): %s", tenant_id, exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to export Patient Master bundle")
    return _xlsx_response(wb, "01_Patient_Master.xlsx")


# ---------------------------------------------------------------------------
# Bundle 02 — Encounter & Diagnosis
# ---------------------------------------------------------------------------

@router.get(
    "/encounter-diagnosis",
    summary="Bundle 02 — Encounter & Diagnosis",
    description="Downloads all encounter records with associated ICD-10 diagnosis codes as XLSX.",
)
def download_encounter_diagnosis(
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
) -> StreamingResponse:
    try:
        wb = export_encounter_diagnosis(tenant_id)
    except Exception as exc:
        logger.error("export_encounter_diagnosis failed (tenant=%s): %s", tenant_id, exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to export Encounter & Diagnosis bundle")
    return _xlsx_response(wb, "02_Encounter_Diagnosis.xlsx")


# ---------------------------------------------------------------------------
# Bundle 03 — RAF Score Summary
# ---------------------------------------------------------------------------

@router.get(
    "/raf-score",
    summary="Bundle 03 — RAF Score Summary",
    description="Downloads calculated RAF scores per patient with HCC contribution breakdown as XLSX.",
)
def download_raf_score(
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
) -> StreamingResponse:
    try:
        wb = export_raf_score(tenant_id)
    except Exception as exc:
        logger.error("export_raf_score failed (tenant=%s): %s", tenant_id, exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to export RAF Score bundle")
    return _xlsx_response(wb, "03_RAF_Score_Summary.xlsx")


# ---------------------------------------------------------------------------
# Bundle 04 — MEAT Compliance
# ---------------------------------------------------------------------------

@router.get(
    "/meat-compliance",
    summary="Bundle 04 — MEAT Compliance",
    description="Downloads MEAT criteria documentation status for each captured HCC as XLSX.",
)
def download_meat_compliance(
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
) -> StreamingResponse:
    try:
        wb = export_meat_compliance(tenant_id)
    except Exception as exc:
        logger.error("export_meat_compliance failed (tenant=%s): %s", tenant_id, exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to export MEAT Compliance bundle")
    return _xlsx_response(wb, "04_MEAT_Compliance.xlsx")


# ---------------------------------------------------------------------------
# Bundle 05 — HCC Suspects
# ---------------------------------------------------------------------------

@router.get(
    "/suspects",
    summary="Bundle 05 — HCC Suspects",
    description="Downloads suspected HCC conditions not yet confirmed in the current period as XLSX.",
)
def download_suspects(
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
) -> StreamingResponse:
    try:
        wb = export_suspects(tenant_id)
    except Exception as exc:
        logger.error("export_suspects failed (tenant=%s): %s", tenant_id, exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to export HCC Suspects bundle")
    return _xlsx_response(wb, "05_HCC_Suspects.xlsx")


# ---------------------------------------------------------------------------
# Bundle 06 — Recapture Gaps
# ---------------------------------------------------------------------------

@router.get(
    "/recapture-gaps",
    summary="Bundle 06 — Recapture Gaps",
    description="Downloads HCCs confirmed in prior years that are missing in the current year as XLSX.",
)
def download_recapture_gaps(
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
) -> StreamingResponse:
    try:
        wb = export_recapture_gaps(tenant_id)
    except Exception as exc:
        logger.error("export_recapture_gaps failed (tenant=%s): %s", tenant_id, exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to export Recapture Gaps bundle")
    return _xlsx_response(wb, "06_Recapture_Gaps.xlsx")


# ---------------------------------------------------------------------------
# Bundle 07 — Provider Performance
# ---------------------------------------------------------------------------

@router.get(
    "/provider-performance",
    summary="Bundle 07 — Provider Performance",
    description="Downloads RAF capture rates, gap closure, and coding quality by provider as XLSX.",
)
def download_provider_performance(
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
) -> StreamingResponse:
    try:
        wb = export_provider_performance(tenant_id)
    except Exception as exc:
        logger.error("export_provider_performance failed (tenant=%s): %s", tenant_id, exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to export Provider Performance bundle")
    return _xlsx_response(wb, "07_Provider_Performance.xlsx")


# ---------------------------------------------------------------------------
# Bundle 08 — CMS Submission
# ---------------------------------------------------------------------------

@router.get(
    "/cms-submission",
    summary="Bundle 08 — CMS Submission",
    description=(
        "Downloads records staged or submitted to CMS for risk-adjustment payment as XLSX. "
        "Optionally filter to a specific submission batch via batch_id."
    ),
)
def download_cms_submission(
    batch_id: str | None = Query(default=None, description="Filter to a specific CMS submission batch ID"),
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
) -> StreamingResponse:
    try:
        wb = export_cms_submission(tenant_id, batch_id=batch_id)
    except Exception as exc:
        logger.error("export_cms_submission failed (tenant=%s, batch_id=%s): %s", tenant_id, batch_id, exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to export CMS Submission bundle")
    filename = f"08_CMS_Submission_{batch_id}.xlsx" if batch_id else "08_CMS_Submission.xlsx"
    return _xlsx_response(wb, filename)


# ---------------------------------------------------------------------------
# Bundle 09 — Audit Log
# ---------------------------------------------------------------------------

@router.get(
    "/audit-log",
    summary="Bundle 09 — Audit Log",
    description=(
        "Downloads the full activity audit trail for compliance and review as XLSX. "
        "Use the days parameter to limit the lookback window (default: 90 days)."
    ),
)
def download_audit_log(
    days: int = Query(default=90, ge=1, le=730, description="Number of days of audit history to include"),
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
) -> StreamingResponse:
    try:
        wb = export_audit_log(tenant_id, days=days)
    except Exception as exc:
        logger.error("export_audit_log failed (tenant=%s, days=%s): %s", tenant_id, days, exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to export Audit Log bundle")
    return _xlsx_response(wb, "09_Audit_Log.xlsx")


# ---------------------------------------------------------------------------
# Bundle 10 — Historical RAF Trends
# ---------------------------------------------------------------------------

@router.get(
    "/historical-raf",
    summary="Bundle 10 — Historical RAF Trends",
    description="Downloads year-over-year RAF score and HCC count trends per patient as XLSX.",
)
def download_historical_raf(
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
) -> StreamingResponse:
    try:
        wb = export_historical_raf(tenant_id)
    except Exception as exc:
        logger.error("export_historical_raf failed (tenant=%s): %s", tenant_id, exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to export Historical RAF Trends bundle")
    return _xlsx_response(wb, "10_Historical_RAF_Trends.xlsx")


# ---------------------------------------------------------------------------
# Bundle 11 — Revenue Opportunity
# ---------------------------------------------------------------------------

@router.get(
    "/revenue-opportunity",
    summary="Bundle 11 — Revenue Opportunity",
    description="Downloads estimated revenue impact of open HCC gaps and suspect conditions as XLSX.",
)
def download_revenue_opportunity(
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
) -> StreamingResponse:
    try:
        wb = export_revenue_opportunity(tenant_id)
    except Exception as exc:
        logger.error("export_revenue_opportunity failed (tenant=%s): %s", tenant_id, exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to export Revenue Opportunity bundle")
    return _xlsx_response(wb, "11_Revenue_Opportunity.xlsx")


# ---------------------------------------------------------------------------
# All bundles — ZIP archive
# ---------------------------------------------------------------------------

@router.get(
    "/all",
    summary="Download all 11 bundles as a single ZIP archive",
    description=(
        "Generates all 11 CMS data bundle XLSX files and packages them into a "
        "single ZIP archive for download. "
        "export_all_bundles() returns a dict mapping filename -> bytes."
    ),
)
def download_all_bundles(
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
) -> StreamingResponse:
    try:
        bundles: dict[str, bytes] = export_all_bundles(tenant_id)
    except Exception as exc:
        logger.error("export_all_bundles failed (tenant=%s): %s", tenant_id, exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to generate bundle archive")

    buf = BytesIO()
    try:
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for filename, data in bundles.items():
                zf.writestr(filename, data)
    except Exception as exc:
        logger.error("ZIP assembly failed (tenant=%s): %s", tenant_id, exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to assemble bundle ZIP")

    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={"Content-Disposition": 'attachment; filename="RAF_CMS_Bundles.zip"'},
    )
