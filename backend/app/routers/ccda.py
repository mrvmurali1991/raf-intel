"""
C-CDA / CCD Document Router
============================
Endpoints for uploading, parsing, querying, and exporting Consolidated
Clinical Document Architecture (C-CDA) XML documents.

All PHI endpoints require a valid JWT Bearer token and enforce tenant
isolation via the ``tenant_id`` dependency.

Endpoints
---------
  POST   /api/ccda/upload                  — upload a C-CDA XML file
  POST   /api/ccda/{id}/parse              — trigger (re)parsing of a document
  GET    /api/ccda                         — list documents for the tenant
  GET    /api/ccda/{id}                    — document detail + parsed_data
  GET    /api/ccda/{id}/problems           — extracted problem list
  GET    /api/ccda/{id}/medications        — extracted medications
  GET    /api/ccda/{id}/results            — extracted lab results
  GET    /api/ccda/{id}/hcc-impact         — HCC categories found in the document
  POST   /api/ccda/export/{patient_id}     — generate a C-CDA export for a patient
  DELETE /api/ccda/{id}                    — delete document and file
"""
# Note: do NOT use 'from __future__ import annotations' here —
# it breaks FastAPI's UploadFile parameter resolution.

import datetime
import decimal
import logging
from typing import Any

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    UploadFile,
)
from fastapi.responses import Response

from app.auth import get_current_user, get_tenant_id, require_permission
from app.rate_limit import limiter
from app.services.ccda_service import (
    delete_ccda_document,
    generate_ccda_export,
    get_ccda_document,
    get_ccda_hcc_impact,
    get_ccda_medications,
    get_ccda_problems,
    get_ccda_results,
    list_ccda_documents,
    parse_ccda_document,
    store_ccda_upload,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/ccda", tags=["ccda"])

# ---------------------------------------------------------------------------
# Serialisation helper
# ---------------------------------------------------------------------------


def _serialize(obj: Any) -> Any:
    """Recursively convert non-JSON-serialisable values."""
    if isinstance(obj, dict):
        return {k: _serialize(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_serialize(i) for i in obj]
    if isinstance(obj, (datetime.datetime, datetime.date)):
        return obj.isoformat()
    if isinstance(obj, decimal.Decimal):
        return float(obj)
    if isinstance(obj, bytes):
        return obj.decode("utf-8", errors="replace")
    return obj


def _doc_not_found(ccda_id: int) -> HTTPException:
    return HTTPException(status_code=404, detail=f"C-CDA document {ccda_id} not found")


# ---------------------------------------------------------------------------
# Upload
# ---------------------------------------------------------------------------


@router.post(
    "/upload",
    summary="Upload a C-CDA XML document",
    description=(
        "Upload a Consolidated Clinical Document Architecture (C-CDA) XML file. "
        "Accepted MIME types: application/xml, text/xml. "
        "Maximum file size: 20 MB. "
        "The document is validated for basic C-CDA structure on upload. "
        "Use POST /api/ccda/{id}/parse to trigger full section extraction."
    ),
    status_code=201,
    response_model=None,
)
@limiter.limit("10/minute")
async def upload_ccda(
    request: Request,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(..., description="C-CDA XML file"),
    patient_id: int | None = Form(None, description="OpenEMR patient ID to link immediately"),
    source: str = Form(
        "upload",
        description="Ingestion channel: upload | fhir | direct_message | hl7",
    ),
    auto_parse: bool = Form(
        False,
        description="Trigger XML parsing automatically after upload",
    ),
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
    _perm: None = Depends(require_permission("documents", "write")),
) -> dict[str, Any]:
    xml_bytes = await file.read()

    if not xml_bytes:
        raise HTTPException(status_code=422, detail="Uploaded file is empty")

    valid_sources = {"upload", "fhir", "direct_message", "hl7"}
    if source not in valid_sources:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid source {source!r}. Must be one of: {', '.join(sorted(valid_sources))}",
        )

    result = store_ccda_upload(
        tenant_id=tenant_id,
        patient_id=patient_id,
        xml_bytes=xml_bytes,
        original_filename=file.filename or "upload.xml",
        source=source,
    )

    if not result["success"]:
        raise HTTPException(status_code=422, detail=result["error"])

    ccda_id: int = result["ccda_id"]

    if auto_parse:
        background_tasks.add_task(_parse_background, ccda_id)

    return {
        "ccda_id": ccda_id,
        "document_type": result.get("document_type", "ccd"),
        "file_size": result.get("file_size"),
        "status": "uploaded",
        "auto_parse_queued": auto_parse,
        "message": (
            "Document uploaded. Parsing queued in background."
            if auto_parse
            else "Document uploaded. POST /api/ccda/{id}/parse to extract data."
        ),
    }


def _parse_background(ccda_id: int) -> None:
    """Background task wrapper — swallows exceptions so the task runner is not disrupted."""
    try:
        parse_ccda_document(ccda_id)
    except Exception as exc:
        logger.error("Background C-CDA parse failed for document %d: %s", ccda_id, exc)


# ---------------------------------------------------------------------------
# Parse
# ---------------------------------------------------------------------------


@router.post(
    "/{ccda_id}/parse",
    summary="Parse a C-CDA document",
    description=(
        "Trigger structured extraction of all C-CDA sections (Problems, Medications, "
        "Results, Encounters, Procedures, Vital Signs). "
        "SNOMED codes are mapped to ICD-10; ICD-10 codes are mapped to CMS-HCC categories. "
        "Re-parsing an already-parsed document clears previous child rows and re-extracts. "
        "Use run_in_background=true for large documents to avoid gateway timeouts."
    ),
    response_model=None,
)
def parse_ccda(
    ccda_id: int,
    background_tasks: BackgroundTasks,
    run_in_background: bool = Query(
        False,
        description="Return immediately and parse asynchronously.",
    ),
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
    _perm: None = Depends(require_permission("documents", "write")),
) -> dict[str, Any]:
    doc = get_ccda_document(ccda_id, tenant_id)
    if not doc:
        raise _doc_not_found(ccda_id)

    if doc["status"] == "parsing":
        raise HTTPException(status_code=409, detail="Document is already being parsed")

    if run_in_background:
        background_tasks.add_task(_parse_background, ccda_id)
        return {
            "ccda_id": ccda_id,
            "status": "queued",
            "message": "Parsing started in background. Poll GET /api/ccda/{id} for status.",
        }

    try:
        result = parse_ccda_document(ccda_id)
    except FileNotFoundError as exc:
        logger.error("Unexpected error: %s", exc)
        raise HTTPException(status_code=404, detail="Internal server error")
    except ValueError as exc:
        logger.error("Unexpected error: %s", exc)
        raise HTTPException(status_code=422, detail="Resource not found")
    except RuntimeError as exc:
        logger.error("Unexpected error: %s", exc)
        raise HTTPException(status_code=409, detail="Conflict")

    return result


# ---------------------------------------------------------------------------
# List / detail / delete
# ---------------------------------------------------------------------------


@router.get(
    "",
    summary="List C-CDA documents",
    description=(
        "List C-CDA documents for the current tenant with optional filters. "
        "Results are paginated and ordered newest-first."
    ),
    response_model=None,
)
def list_documents(
    patient_id: int | None = Query(None, description="Filter by patient ID"),
    status: str | None = Query(
        None, description="Filter by status: uploaded | parsing | parsed | error"
    ),
    document_type: str | None = Query(
        None,
        description="Filter by document type: ccd | discharge_summary | referral | progress_note | history_physical",
    ),
    limit: int = Query(50, ge=1, le=200, description="Page size"),
    offset: int = Query(0, ge=0, description="Page offset"),
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
    _perm: None = Depends(require_permission("documents", "read")),
) -> dict[str, Any]:
    rows, total = list_ccda_documents(
        tenant_id=tenant_id,
        patient_id=patient_id,
        status=status,
        document_type=document_type,
        limit=limit,
        offset=offset,
    )
    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "documents": _serialize(rows),
    }


@router.get(
    "/{ccda_id}",
    summary="C-CDA document detail",
    description=(
        "Return the full C-CDA document record including header metadata and the "
        "parsed_data summary (section counts, encounters, procedures, vitals)."
    ),
    response_model=None,
)
def get_document(
    ccda_id: int,
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
    _perm: None = Depends(require_permission("documents", "read")),
) -> dict[str, Any]:
    doc = get_ccda_document(ccda_id, tenant_id)
    if not doc:
        raise _doc_not_found(ccda_id)

    result = dict(doc)
    # Deserialise the parsed_data JSON string if the driver returned it as str
    if isinstance(result.get("parsed_data"), str):
        import json
        try:
            result["parsed_data"] = json.loads(result["parsed_data"])
        except (ValueError, TypeError):
            pass

    return _serialize(result)


@router.delete(
    "/{ccda_id}",
    summary="Delete a C-CDA document",
    description=(
        "Delete the document record, all extracted child rows "
        "(problems, medications, results), and the XML file on disk."
    ),
    response_model=None,
)
def delete_document(
    ccda_id: int,
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
    _perm: None = Depends(require_permission("documents", "delete")),
) -> dict[str, Any]:
    deleted = delete_ccda_document(ccda_id, tenant_id)
    if not deleted:
        raise _doc_not_found(ccda_id)
    return {"deleted": True, "ccda_id": ccda_id}


# ---------------------------------------------------------------------------
# Extracted data sub-resources
# ---------------------------------------------------------------------------


@router.get(
    "/{ccda_id}/problems",
    summary="Extracted problems / diagnoses",
    description=(
        "Return all problem list entries extracted from the C-CDA document. "
        "Each entry includes ICD-10 code, SNOMED code, HCC mapping, onset date, "
        "and clinical status. Only available after parsing completes."
    ),
    response_model=None,
)
def get_problems(
    ccda_id: int,
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
    _perm: None = Depends(require_permission("documents", "read")),
) -> dict[str, Any]:
    doc = get_ccda_document(ccda_id, tenant_id)
    if not doc:
        raise _doc_not_found(ccda_id)

    _require_parsed(doc)

    problems = get_ccda_problems(ccda_id, tenant_id)
    return {
        "ccda_id": ccda_id,
        "count": len(problems),
        "problems": _serialize(problems),
    }


@router.get(
    "/{ccda_id}/medications",
    summary="Extracted medications",
    description=(
        "Return all medication entries extracted from the C-CDA document including "
        "RxNorm code, dose, route, frequency, and prescriber NPI."
    ),
    response_model=None,
)
def get_medications(
    ccda_id: int,
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
    _perm: None = Depends(require_permission("documents", "read")),
) -> dict[str, Any]:
    doc = get_ccda_document(ccda_id, tenant_id)
    if not doc:
        raise _doc_not_found(ccda_id)

    _require_parsed(doc)

    medications = get_ccda_medications(ccda_id, tenant_id)
    return {
        "ccda_id": ccda_id,
        "count": len(medications),
        "medications": _serialize(medications),
    }


@router.get(
    "/{ccda_id}/results",
    summary="Extracted lab results",
    description=(
        "Return all lab and diagnostic results extracted from the C-CDA Results section "
        "including LOINC code, numeric/text value, units, reference range, and abnormal flag."
    ),
    response_model=None,
)
def get_results(
    ccda_id: int,
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
    _perm: None = Depends(require_permission("documents", "read")),
) -> dict[str, Any]:
    doc = get_ccda_document(ccda_id, tenant_id)
    if not doc:
        raise _doc_not_found(ccda_id)

    _require_parsed(doc)

    results = get_ccda_results(ccda_id, tenant_id)
    return {
        "ccda_id": ccda_id,
        "count": len(results),
        "results": _serialize(results),
    }


@router.get(
    "/{ccda_id}/hcc-impact",
    summary="HCC impact analysis",
    description=(
        "Return all CMS-HCC V28 categories identified in the document's problem list. "
        "For each HCC category the response includes the count of supporting ICD-10 codes "
        "and the list of codes. Only available after parsing completes."
    ),
    response_model=None,
)
def get_hcc_impact(
    ccda_id: int,
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
    _perm: None = Depends(require_permission("documents", "read")),
) -> dict[str, Any]:
    doc = get_ccda_document(ccda_id, tenant_id)
    if not doc:
        raise _doc_not_found(ccda_id)

    _require_parsed(doc)

    hcc_rows = get_ccda_hcc_impact(ccda_id, tenant_id)
    return {
        "ccda_id": ccda_id,
        "hcc_count": len(hcc_rows),
        "hcc_codes": _serialize(hcc_rows),
    }


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------


@router.post(
    "/export/{patient_id}",
    summary="Generate C-CDA export for a patient",
    description=(
        "Generate a minimal but structurally valid CCD XML document for a patient "
        "using data stored in ccda_problems, ccda_medications, and ccda_results. "
        "Returns the XML directly with Content-Type: application/xml. "
        "The generated document conforms to HITSP C32 / HL7 CCD Release 1."
    ),
    response_class=Response,
    responses={
        200: {
            "content": {"application/xml": {}},
            "description": "C-CDA XML document",
        }
    },
)
def export_ccda(
    patient_id: int,
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
    _perm: None = Depends(require_permission("documents", "read")),
) -> Response:
    try:
        xml_str = generate_ccda_export(patient_id=patient_id, tenant_id=tenant_id)
    except Exception as exc:
        logger.error("C-CDA export failed for patient %d: %s", patient_id, exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to generate C-CDA export")

    return Response(
        content=xml_str.encode("utf-8"),
        media_type="application/xml",
        headers={
            "Content-Disposition": f'attachment; filename="ccd_patient_{patient_id}.xml"',
        },
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _require_parsed(doc: dict) -> None:
    """Raise 422 if the document has not been successfully parsed yet."""
    status = doc.get("status", "")
    if status == "uploaded":
        raise HTTPException(
            status_code=422,
            detail="Document has not been parsed yet. POST /api/ccda/{id}/parse to extract data.",
        )
    if status == "parsing":
        raise HTTPException(status_code=202, detail="Parsing is currently in progress.")
    if status == "error":
        raise HTTPException(
            status_code=422,
            detail=f"Parsing failed: {doc.get('error_message', 'unknown error')}",
        )
