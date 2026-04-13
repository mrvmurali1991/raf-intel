"""
Document Upload & Gemini Vision Analysis — Router
==================================================
Provides endpoints for uploading clinical documents, triggering Gemini Vision
analysis, reviewing extracted diagnoses, and managing upload batches.

All PHI interactions are logged via the standard audit logger.
"""
# Note: do NOT use 'from __future__ import annotations' here —
# it breaks FastAPI's UploadFile parameter resolution.

import json as _json
import logging
from typing import Any

from fastapi import (
    Depends,
    APIRouter,
    BackgroundTasks,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    UploadFile,
)
from fastapi.responses import JSONResponse

from app.auth import get_current_user, get_tenant_id, require_permission
from app.db import raf_cursor, openemr_cursor
from app.services.emr_manager import ACTIVE_PATIENTS_SUBQUERY
from app.rate_limit import limiter
from app.services.icd_validator import get_hcc_mapping
from app.services.document_service import (
    analyze_document,
    create_batch,
    delete_document,
    get_analysis,
    get_batch,
    get_diagnosis_lines,
    get_document,
    get_document_stats,
    link_document_to_patient,
    list_batches,
    list_documents,
    match_patient_from_analysis,
    process_batch,
    set_diagnosis_review_status,
    store_upload,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/documents", tags=["documents"])

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _serialize(obj: Any) -> Any:
    """Convert non-JSON-serialisable values (datetime, Decimal, bytes) recursively."""
    import datetime
    import decimal

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


def _doc_not_found(document_id: str) -> HTTPException:
    return HTTPException(status_code=404, detail=f"Document {document_id!r} not found")


def _analyze_and_maybe_approve(
    document_id: str,
    auto_approve: bool,
    patient_id: str | None,
    tenant_id: str | None = None,
) -> None:
    """Background task: analyze document, then optionally auto-approve and update RAF."""
    try:
        analyze_document(document_id)
    except Exception as exc:
        logger.error("Background analysis failed for %s: %s", document_id, exc)
        return

    if auto_approve and patient_id:
        try:
            _do_approve_and_score(document_id, int(patient_id), tenant_id=tenant_id)
        except Exception as exc:
            logger.error("Auto-approve failed for %s: %s", document_id, exc)


def _do_approve_and_score(
    document_id: str,
    patient_id: int,
    diagnosis_ids: list[str] | None = None,
    tenant_id: str | None = None,
) -> dict[str, Any]:
    """Approve all HCC-relevant diagnoses and recalculate RAF score."""
    from app.services.raf_calculator import calculate_raf_score
    from datetime import date as _d

    year = _d.today().year

    with raf_cursor() as cur:
        if diagnosis_ids:
            ph = ",".join(["%s"] * len(diagnosis_ids))
            cur.execute(
                f"SELECT * FROM document_diagnosis_lines WHERE document_id = %s AND id IN ({ph})",
                (document_id, *diagnosis_ids),
            )
        else:
            cur.execute(
                "SELECT * FROM document_diagnosis_lines "
                "WHERE document_id = %s AND hcc_code IS NOT NULL",
                (document_id,),
            )
        lines = cur.fetchall()

    if not lines:
        return {"approved": 0}

    # Mark approved
    ids = [l["id"] for l in lines]
    with raf_cursor() as cur:
        cur.executemany(
            "UPDATE document_diagnosis_lines SET review_status='approved' WHERE id = %s",
            [(i,) for i in ids],
        )

    # Insert into raf_patient_hcc
    inserted = []
    for l in lines:
        hcc = l.get("hcc_code")
        if not hcc:
            continue
        with raf_cursor() as cur:
            if tenant_id is not None:
                cur.execute(
                    "SELECT id FROM raf_patient_hcc WHERE patient_id=%s AND hcc_code=%s AND measurement_year=%s AND tenant_id=%s LIMIT 1",
                    (patient_id, hcc, year, tenant_id),
                )
            else:
                cur.execute(
                    "SELECT id FROM raf_patient_hcc WHERE patient_id=%s AND hcc_code=%s AND measurement_year=%s LIMIT 1",
                    (patient_id, hcc, year),
                )
            if cur.fetchone():
                continue
            cur.execute(
                "INSERT INTO raf_patient_hcc (patient_id, hcc_code, icd10_code, hcc_description, measurement_year, source, tenant_id, created_at) "
                "VALUES (%s,%s,%s,%s,%s,'document_analysis',%s,NOW())",
                (
                    patient_id,
                    hcc,
                    l.get("icd10_code"),
                    l.get("description"),
                    year,
                    tenant_id,
                ),
            )
            inserted.append(hcc)

    # Recalculate RAF
    try:
        raf_result = calculate_raf_score(patient_id, year, tenant_id=tenant_id)
        new_raf = raf_result.get("raf_score") or raf_result.get("final_raf", 0)
    except Exception:
        new_raf = None

    with raf_cursor() as cur:
        if tenant_id is not None:
            cur.execute(
                "UPDATE documents SET status='approved' WHERE id=%s AND tenant_id=%s",
                (document_id, tenant_id),
            )
        else:
            cur.execute(
                "UPDATE documents SET status='approved' WHERE id=%s",
                (document_id,),
            )

    return {"approved": len(ids), "new_hccs": inserted, "new_raf": new_raf}


# ---------------------------------------------------------------------------
# Upload
# ---------------------------------------------------------------------------


@router.post(
    "/upload",
    summary="Upload a single document",
    description=(
        "Upload a clinical document (PDF, image) for storage and optional Gemini Vision "
        "analysis. Accepted types: pdf, png, jpg, jpeg, tiff, bmp, gif, webp, heic. "
        "Max size: 50 MB. Duplicate files (same SHA-256) are detected and the existing "
        "document ID is returned without re-storing the file."
    ),
    status_code=201,
    response_model=None,
)
@limiter.limit("10/minute")
async def upload_document(
    request: Request,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(..., description="Clinical document file"),
    patient_id: str | None = Form(
        None, description="OpenEMR patient ID to link immediately"
    ),
    document_type: str = Form(
        "unknown",
        description="Document type hint: progress_note, lab_report, discharge_summary, rx, radiology, consult, other",
    ),
    encounter_date: str | None = Form(
        None, description="ISO-8601 date of the encounter, e.g. 2024-03-15"
    ),
    auto_analyze: bool = Form(
        False, description="Trigger Gemini Vision analysis automatically after upload"
    ),
    auto_approve: bool = Form(
        False,
        description="Auto-approve extracted diagnoses and update RAF scores (disabled by default for compliance)",
    ),
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
    _perm: None = Depends(require_permission("documents", "write")),
):
    file_bytes = await file.read()
    result = store_upload(
        tenant_id=tenant_id,
        patient_id=patient_id,
        file_bytes=file_bytes,
        original_filename=file.filename or "upload.bin",
        document_type=document_type,
        encounter_date=encounter_date,
    )

    if not result["success"]:
        raise HTTPException(status_code=422, detail=result["error"])

    if auto_analyze and not result.get("is_duplicate"):
        background_tasks.add_task(
            _analyze_and_maybe_approve,
            result["document_id"],
            auto_approve,
            patient_id,
            tenant_id,
        )

    result["auto_approve"] = auto_approve
    return result


@router.post(
    "/upload-batch",
    summary="Upload multiple documents",
    description=(
        "Upload several clinical documents in a single request. A batch record is created "
        "automatically. Use POST /batches/{id}/process to trigger analysis of all items."
    ),
    status_code=201,
    response_model=None,
)
async def upload_batch_documents(
    files: list[UploadFile] = File(
        ..., description="One or more clinical document files"
    ),
    batch_name: str = Form("Batch Upload", description="Name for this batch"),
    batch_description: str = Form("", description="Optional description"),
    patient_id: str | None = Form(
        None, description="Patient ID to link all documents to"
    ),
    document_type: str = Form(
        "unknown", description="Document type hint for all files"
    ),
    encounter_date: str | None = Form(None, description="Encounter date for all files"),
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
    _perm: None = Depends(require_permission("documents", "write")),
) -> dict[str, Any]:
    if not files:
        raise HTTPException(status_code=422, detail="No files provided")

    if len(files) > 50:
        raise HTTPException(
            status_code=422, detail="Maximum 50 files per batch upload request"
        )

    uploaded_ids: list[str] = []
    errors: list[dict] = []

    for upload_file in files:
        file_bytes = await upload_file.read()
        result = store_upload(
            tenant_id=tenant_id,
            patient_id=patient_id,
            file_bytes=file_bytes,
            original_filename=upload_file.filename or "upload.bin",
            document_type=document_type,
            encounter_date=encounter_date,
        )
        if result["success"]:
            uploaded_ids.append(result["document_id"])
        else:
            errors.append(
                {
                    "filename": upload_file.filename,
                    "error": result.get("error"),
                }
            )

    if not uploaded_ids and errors:
        raise HTTPException(
            status_code=422,
            detail={"message": "All uploads failed", "errors": errors},
        )

    batch_id = create_batch(
        tenant_id=tenant_id,
        name=batch_name,
        description=batch_description,
        document_ids=uploaded_ids,
    )

    return {
        "batch_id": batch_id,
        "uploaded_count": len(uploaded_ids),
        "failed_count": len(errors),
        "document_ids": uploaded_ids,
        "errors": errors,
    }


# ---------------------------------------------------------------------------
# List / detail / delete
# ---------------------------------------------------------------------------


@router.get(
    "",
    summary="List documents",
    description="List uploaded documents with optional filters. Results are paginated.",
)
def list_documents_endpoint(
    patient_id: str | None = Query(None, description="Filter by patient ID"),
    status: str | None = Query(
        None, description="Filter by status: uploaded|processing|analyzed|failed"
    ),
    document_type: str | None = Query(None, description="Filter by document type"),
    date_from: str | None = Query(
        None, description="ISO-8601 date — include documents created on/after"
    ),
    date_to: str | None = Query(
        None, description="ISO-8601 date — include documents created on/before"
    ),
    limit: int = Query(50, ge=1, le=200, description="Page size"),
    offset: int = Query(0, ge=0, description="Page offset"),
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
    _perm: None = Depends(require_permission("documents", "read")),
) -> dict[str, Any]:
    rows, total = list_documents(
        tenant_id=tenant_id,
        patient_id=patient_id,
        status=status,
        document_type=document_type,
        date_from=date_from,
        date_to=date_to,
        limit=limit,
        offset=offset,
    )

    # Enrich each document with its analysis results so the frontend has
    # diagnoses, medications, labs, clinical_summary, meat_evidence, etc.
    enriched = []
    for row in rows:
        doc = dict(row) if not isinstance(row, dict) else row
        # Map DB column names to frontend expected field names
        if "document_name" in doc and "filename" not in doc:
            doc["filename"] = doc["document_name"]
        if "created_at" in doc and "upload_date" not in doc:
            doc["upload_date"] = str(doc["created_at"]) if doc["created_at"] else None
        if "file_size_bytes" in doc and "file_size" not in doc:
            doc["file_size"] = doc.get("file_size_bytes") or doc.get("file_size", 0)
        # Resolve patient_name from raf_intelligence.patients if not set
        if not doc.get("patient_name") and doc.get("patient_id"):
            try:
                with raf_cursor() as _pc:
                    _pc.execute(
                        "SELECT CONCAT(first_name, ' ', last_name) AS name FROM patients WHERE id = %s AND tenant_id = %s",
                        (doc["patient_id"], tenant_id),
                    )
                    _pr = _pc.fetchone()
                    doc["patient_name"] = _pr["name"] if _pr else ""
            except Exception:
                doc["patient_name"] = ""

        analysis = get_analysis(str(doc["id"]))
        if analysis:
            # Normalize diagnosis field names to match frontend interface
            raw_dx = analysis.get("extracted_diagnoses") or []
            if isinstance(raw_dx, str):
                import json as _j

                try:
                    raw_dx = _j.loads(raw_dx)
                except Exception:
                    raw_dx = []
            diagnoses = []
            for d in raw_dx:
                if isinstance(d, str):
                    diagnoses.append(
                        {
                            "icd10_code": d,
                            "description": "",
                            "hcc_number": None,
                            "confidence": 0,
                        }
                    )
                    continue
                diagnoses.append(
                    {
                        "icd10_code": d.get("icd10_code") or d.get("icd10", ""),
                        "description": d.get("description") or d.get("desc", ""),
                        "hcc_number": d.get("hcc_number") or d.get("hcc"),
                        "confidence": d.get("confidence") or d.get("conf", 0),
                        "page_number": d.get("page_number") or d.get("page"),
                        "evidence_text": d.get("evidence_text")
                        or d.get("evidence", ""),
                        "confirmed": d.get("confirmed"),
                    }
                )

            raw_meds = analysis.get("extracted_medications") or []
            if isinstance(raw_meds, str):
                import json as _j

                try:
                    raw_meds = _j.loads(raw_meds)
                except Exception:
                    raw_meds = []

            raw_labs = analysis.get("extracted_labs") or []
            if isinstance(raw_labs, str):
                import json as _j

                try:
                    raw_labs = _j.loads(raw_labs)
                except Exception:
                    raw_labs = []

            raw_meat = analysis.get("meat_evidence")
            if isinstance(raw_meat, str):
                import json as _j

                try:
                    raw_meat = _j.loads(raw_meat)
                except Exception:
                    raw_meat = None

            doc["analysis_results"] = {
                "diagnoses": diagnoses,
                "medications": raw_meds,
                "labs": raw_labs,
                "clinical_summary": analysis.get("clinical_summary"),
                "meat_evidence": raw_meat,
                "raw_text": analysis.get("extracted_text"),
            }
            doc["hcc_codes_found"] = analysis.get("hcc_codes_found") or []
            doc["hcc_count"] = len(diagnoses)
            doc["quality_score"] = analysis.get("quality_score")
            doc["extracted_text"] = analysis.get("extracted_text")
            doc["processing_time_ms"] = analysis.get("processing_time_ms")
            doc["tokens_used"] = analysis.get("token_count")
        else:
            doc.setdefault("hcc_count", 0)
        enriched.append(doc)

    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "documents": _serialize(enriched),
    }


@router.get(
    "/stats",
    summary="Document statistics",
    description="Aggregate counts for documents, diagnoses, and batches for a tenant.",
)
def document_stats(
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
    _perm: None = Depends(require_permission("documents", "read")),
) -> dict[str, Any]:
    return _serialize(get_document_stats(tenant_id))


@router.get(
    "/batches",
    summary="List batches",
    description="List all document batches for a tenant.",
)
def list_batches_endpoint(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
    _perm: None = Depends(require_permission("documents", "read")),
) -> dict[str, Any]:
    rows, total = list_batches(tenant_id=tenant_id, limit=limit, offset=offset)
    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "batches": _serialize(rows),
    }


@router.get(
    "/batches/{batch_id}",
    summary="Batch detail",
    description="Return a batch record with the status of all its document items.",
)
def get_batch_endpoint(
    batch_id: str,
    current_user: dict = Depends(get_current_user),
    _perm: None = Depends(require_permission("documents", "read")),
) -> dict[str, Any]:
    batch = get_batch(batch_id)
    if not batch:
        raise HTTPException(status_code=404, detail=f"Batch {batch_id!r} not found")
    return _serialize(batch)


@router.post(
    "/batches/{batch_id}/process",
    summary="Process all documents in a batch",
    description=(
        "Trigger Gemini Vision analysis for all pending documents in the batch. "
        "Processing is sequential. Large batches may take several minutes."
    ),
)
def process_batch_endpoint(
    batch_id: str,
    background_tasks: BackgroundTasks,
    run_in_background: bool = Query(
        False,
        description="If true, processing runs in a background task and the endpoint returns immediately.",
    ),
    current_user: dict = Depends(get_current_user),
    _perm: None = Depends(require_permission("documents", "write")),
) -> dict[str, Any]:
    batch = get_batch(batch_id)
    if not batch:
        raise HTTPException(status_code=404, detail=f"Batch {batch_id!r} not found")

    if batch["status"] == "processing":
        raise HTTPException(status_code=409, detail="Batch is already being processed")

    if run_in_background:
        background_tasks.add_task(process_batch, batch_id)
        return {
            "batch_id": batch_id,
            "status": "queued",
            "message": "Processing started in background",
        }

    result = process_batch(batch_id)
    return result


@router.get(
    "/{document_id}",
    summary="Document detail",
    description="Return the full document record.",
)
def get_document_endpoint(
    document_id: str,
    current_user: dict = Depends(get_current_user),
    _perm: None = Depends(require_permission("documents", "read")),
) -> dict[str, Any]:
    doc = get_document(document_id)
    if not doc:
        raise _doc_not_found(document_id)
    return _serialize(doc)


@router.get(
    "/{document_id}/view",
    summary="View/download document file",
    description="Serve the uploaded document file (PDF, image, etc.) for viewing in the browser.",
)
def view_document_file(
    document_id: str,
    current_user: dict = Depends(get_current_user),
    _perm: None = Depends(require_permission("documents", "read")),
):
    from pathlib import Path
    from fastapi.responses import FileResponse

    doc = get_document(document_id)
    if not doc:
        raise _doc_not_found(document_id)

    file_path = doc.get("file_path", "")
    if not file_path:
        raise HTTPException(
            status_code=404, detail="No file path recorded for this document"
        )

    # Resolve relative to project root
    project_root = Path(__file__).resolve().parent.parent.parent
    full_path = (project_root / file_path.lstrip("/")).resolve()

    # Security: ensure path is within project
    if not full_path.is_relative_to(project_root.resolve()):
        raise HTTPException(status_code=403, detail="Access denied")

    if not full_path.exists():
        raise HTTPException(status_code=404, detail="File not found on disk")

    media_type_map = {
        "pdf": "application/pdf",
        "png": "image/png",
        "jpg": "image/jpeg",
        "jpeg": "image/jpeg",
        "doc": "application/msword",
        "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    }
    ext = full_path.suffix.lstrip(".").lower()
    media_type = media_type_map.get(ext, "application/octet-stream")

    return FileResponse(
        path=str(full_path),
        media_type=media_type,
        filename=doc.get("document_name", full_path.name),
        headers={
            "Content-Disposition": f'inline; filename="{doc.get("document_name", full_path.name)}"'
        },
    )


@router.delete(
    "/{document_id}",
    summary="Delete document",
    description="Delete the document record, all analysis results, and the file on disk.",
)
def delete_document_endpoint(
    document_id: str,
    current_user: dict = Depends(get_current_user),
    _perm: None = Depends(require_permission("documents", "delete")),
) -> dict[str, Any]:
    deleted = delete_document(document_id)
    if not deleted:
        raise _doc_not_found(document_id)
    return {"deleted": True, "document_id": document_id}


# ---------------------------------------------------------------------------
# Analysis
# ---------------------------------------------------------------------------


@router.post(
    "/{document_id}/analyze",
    summary="Trigger Gemini Vision analysis",
    description=(
        "Send the stored document to Gemini Vision for clinical data extraction. "
        "Returns a summary when complete. Use run_in_background=true for large PDFs "
        "to avoid gateway timeouts."
    ),
)
def trigger_analysis(
    document_id: str,
    background_tasks: BackgroundTasks,
    run_in_background: bool = Query(
        False,
        description="Run analysis asynchronously. Endpoint returns immediately; poll GET /{id}/analysis for results.",
    ),
    current_user: dict = Depends(get_current_user),
    _perm: None = Depends(require_permission("documents", "write")),
) -> dict[str, Any]:
    doc = get_document(document_id)
    if not doc:
        raise _doc_not_found(document_id)

    if doc["status"] == "processing":
        raise HTTPException(
            status_code=409, detail="Analysis is already in progress for this document"
        )

    if run_in_background:
        background_tasks.add_task(analyze_document, document_id)
        return {
            "document_id": document_id,
            "status": "queued",
            "message": "Gemini Vision analysis started in background. Poll GET /{id}/analysis for results.",
        }

    try:
        result = analyze_document(document_id)
    except ValueError as exc:
        logger.error("Unexpected error: %s", exc)
        raise HTTPException(status_code=404, detail="Resource not found")
    except RuntimeError as exc:
        logger.error("Unexpected error: %s", exc)
        raise HTTPException(status_code=502, detail="Resource not found")

    return result


@router.get(
    "/{document_id}/analysis",
    summary="Get analysis results",
    description=(
        "Return the full Gemini Vision extraction result for a document including "
        "full text, medications, lab results, vital signs, procedures, suspect conditions, "
        "and quality assessment."
    ),
)
def get_analysis_endpoint(
    document_id: str,
    current_user: dict = Depends(get_current_user),
    _perm: None = Depends(require_permission("documents", "read")),
) -> dict[str, Any]:
    doc = get_document(document_id)
    if not doc:
        raise _doc_not_found(document_id)

    analysis = get_analysis(document_id)
    if not analysis:
        status = doc.get("status", "unknown")
        if status == "uploaded":
            raise HTTPException(
                status_code=404,
                detail="Analysis has not been run yet. POST /{id}/analyze to trigger it.",
            )
        if status == "processing":
            raise HTTPException(
                status_code=202, detail="Analysis is currently in progress"
            )
        if status == "failed":
            raise HTTPException(
                status_code=422,
                detail=f"Analysis failed: {doc.get('error_message', 'unknown error')}",
            )
        raise HTTPException(status_code=404, detail="Analysis results not found")

    # Parse JSON sub-fields for the response
    def _parse_json_field(value: Any) -> Any:
        if isinstance(value, str):
            try:
                return _json.loads(value)
            except (ValueError, TypeError):
                return value
        return value

    result = dict(analysis)
    for field in (
        "medications_json",
        "lab_results_json",
        "vital_signs_json",
        "procedures_json",
        "suspect_conditions_json",
        "quality_json",
    ):
        key = field.replace("_json", "")
        result[key] = _parse_json_field(result.pop(field, None))

    # Omit raw Gemini response from default output (large, internal)
    result.pop("raw_gemini_json", None)

    return _serialize(result)


# ---------------------------------------------------------------------------
# Diagnoses
# ---------------------------------------------------------------------------


@router.get(
    "/{document_id}/diagnoses",
    summary="Extracted diagnoses",
    description=(
        "Return all diagnosis lines extracted by Gemini Vision, with ICD-10 codes, "
        "HCC mappings, RAF weights, MEAT evidence, and review status. "
        "Results are ordered by RAF weight (highest first)."
    ),
)
def get_diagnoses_endpoint(
    document_id: str,
    current_user: dict = Depends(get_current_user),
    _perm: None = Depends(require_permission("documents", "read")),
) -> dict[str, Any]:
    doc = get_document(document_id)
    if not doc:
        raise _doc_not_found(document_id)

    lines = get_diagnosis_lines(document_id)
    return {
        "document_id": document_id,
        "count": len(lines),
        "diagnoses": _serialize(lines),
    }


@router.put(
    "/{document_id}/diagnoses/{diag_id}/confirm",
    summary="Confirm a diagnosis",
    description=(
        "Mark a Gemini-extracted diagnosis as clinically confirmed by a reviewer. "
        "The reviewer identity is derived from the authenticated JWT."
    ),
)
def confirm_diagnosis(
    document_id: str,
    diag_id: str,
    current_user: dict = Depends(get_current_user),
    _perm: None = Depends(require_permission("documents", "write")),
) -> dict[str, Any]:
    reviewed_by = f"user:{current_user.get('id', 'unknown')} ({current_user.get('email', 'unknown')})"
    doc = get_document(document_id)
    if not doc:
        raise _doc_not_found(document_id)

    updated = set_diagnosis_review_status(
        diag_id=diag_id,
        document_id=document_id,
        review_status="confirmed",
        reviewed_by=reviewed_by,
    )
    if not updated:
        raise HTTPException(
            status_code=404, detail=f"Diagnosis line {diag_id!r} not found"
        )

    return {
        "diagnosis_id": diag_id,
        "review_status": "confirmed",
        "reviewed_by": reviewed_by,
    }


@router.put(
    "/{document_id}/diagnoses/{diag_id}/reject",
    summary="Reject a diagnosis",
    description=(
        "Mark a Gemini-extracted diagnosis as rejected/incorrect. "
        "The reviewer identity is derived from the authenticated JWT."
    ),
)
def reject_diagnosis(
    document_id: str,
    diag_id: str,
    current_user: dict = Depends(get_current_user),
    _perm: None = Depends(require_permission("documents", "write")),
) -> dict[str, Any]:
    reviewed_by = f"user:{current_user.get('id', 'unknown')} ({current_user.get('email', 'unknown')})"
    doc = get_document(document_id)
    if not doc:
        raise _doc_not_found(document_id)

    updated = set_diagnosis_review_status(
        diag_id=diag_id,
        document_id=document_id,
        review_status="rejected",
        reviewed_by=reviewed_by,
    )
    if not updated:
        raise HTTPException(
            status_code=404, detail=f"Diagnosis line {diag_id!r} not found"
        )

    return {
        "diagnosis_id": diag_id,
        "review_status": "rejected",
        "reviewed_by": reviewed_by,
    }


# ---------------------------------------------------------------------------
# Patient linking
# ---------------------------------------------------------------------------


@router.post(
    "/{document_id}/link-patient",
    summary="Link document to patient",
    description=(
        "Explicitly link a document to a patient by providing patient_id, OR "
        "trigger automatic matching using the name/DOB detected in the Gemini analysis."
    ),
)
def link_patient_endpoint(
    document_id: str,
    patient_id: str | None = Query(
        None, description="OpenEMR patient ID to link explicitly"
    ),
    auto_match: bool = Query(
        False,
        description=(
            "If true and no patient_id is provided, attempt to match via name/DOB "
            "detected in the document's Gemini analysis."
        ),
    ),
    current_user: dict = Depends(get_current_user),
    _perm: None = Depends(require_permission("documents", "write")),
) -> dict[str, Any]:
    doc = get_document(document_id)
    if not doc:
        raise _doc_not_found(document_id)

    if patient_id:
        link_document_to_patient(document_id, patient_id)
        return {
            "document_id": document_id,
            "patient_id": patient_id,
            "linked": True,
            "method": "explicit",
        }

    if auto_match:
        result = match_patient_from_analysis(document_id)
        result["document_id"] = document_id
        result["method"] = "auto"
        return result

    raise HTTPException(
        status_code=422,
        detail="Provide either patient_id or set auto_match=true",
    )


# ---------------------------------------------------------------------------
# Draft RAF score calculation
# ---------------------------------------------------------------------------

REVENUE_FACTOR = 10_000.0  # Approximate per-member annual revenue factor


@router.post(
    "/{document_id}/draft-raf",
    summary="Calculate draft RAF score impact",
    description=(
        "Project how this document's extracted diagnoses would impact the linked "
        "patient's RAF score. Merges document-extracted HCC codes with the patient's "
        "existing HCCs and returns the delta, new codes, and estimated revenue impact."
    ),
)
def draft_raf_score(
    document_id: str,
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
    _perm: None = Depends(require_permission("documents", "read")),
) -> dict[str, Any]:
    from datetime import date

    doc = get_document(document_id)
    if not doc:
        raise _doc_not_found(document_id)

    patient_id = doc.get("patient_id")
    if not patient_id:
        raise HTTPException(
            status_code=422,
            detail="Document must be linked to a patient first.",
        )

    calc_year = date.today().year

    # Verify the patient belongs to an active EMR connection
    with raf_cursor() as cur:
        cur.execute(
            f"SELECT 1 FROM raf_scores WHERE patient_id = %s AND {ACTIVE_PATIENTS_SUBQUERY} AND raf_scores.tenant_id = %s LIMIT 1",
            (patient_id, int(tenant_id)),
        )
        if not cur.fetchone():
            raise HTTPException(
                status_code=403,
                detail="Patient is not linked to an active EMR connection.",
            )

    # ------------------------------------------------------------------
    # 1. Get the patient's current RAF score (latest entry)
    # ------------------------------------------------------------------
    with raf_cursor() as cur:
        cur.execute(
            """
            SELECT final_raf, measurement_year
            FROM raf_scores
            WHERE patient_id = %s
            ORDER BY calculated_at DESC
            LIMIT 1
            """,
            (patient_id,),
        )
        raf_row = cur.fetchone()

    current_raf = float(raf_row["final_raf"]) if raf_row else 0.0

    # ------------------------------------------------------------------
    # 2. Get the patient's current HCC codes
    # ------------------------------------------------------------------
    with raf_cursor() as cur:
        cur.execute(
            """
            SELECT hcc_code, icd10_codes
            FROM raf_patient_hcc
            WHERE patient_id = %s AND measurement_year = %s AND tenant_id = %s
            """,
            (
                patient_id,
                raf_row["measurement_year"] if raf_row else calc_year,
                tenant_id,
            ),
        )
        existing_hcc_rows = cur.fetchall()

    existing_hcc_set: set[str] = {str(r["hcc_code"]) for r in existing_hcc_rows}

    # ------------------------------------------------------------------
    # 3. Get document diagnosis lines (confirmed first, else all non-rejected)
    # ------------------------------------------------------------------
    with raf_cursor() as cur:
        cur.execute(
            """
            SELECT id, icd10_code, description, hcc_code, hcc_label,
                   raf_weight, review_status
            FROM document_diagnosis_lines
            WHERE document_id = %s AND review_status = 'confirmed'
            """,
            (document_id,),
        )
        diag_rows = cur.fetchall()

        # If none are confirmed yet, use all non-rejected diagnoses
        if not diag_rows:
            cur.execute(
                """
                SELECT id, icd10_code, description, hcc_code, hcc_label,
                       raf_weight, review_status
                FROM document_diagnosis_lines
                WHERE document_id = %s AND review_status != 'rejected'
                """,
                (document_id,),
            )
            diag_rows = cur.fetchall()

    # ------------------------------------------------------------------
    # 4. Map document diagnoses to HCC codes
    # ------------------------------------------------------------------
    document_diagnoses: list[dict[str, Any]] = []
    new_hcc_codes: list[dict[str, Any]] = []
    new_hcc_set: set[str] = set()
    draft_raf_delta = 0.0

    for row in diag_rows:
        hcc_code = str(row["hcc_code"]) if row.get("hcc_code") else None
        raf_weight = float(row["raf_weight"]) if row.get("raf_weight") else 0.0

        # If the stored hcc_code is empty, try a fresh lookup
        if not hcc_code:
            mapping = get_hcc_mapping(row["icd10_code"])
            if mapping:
                hcc_code = str(mapping["hcc_code"])
                raf_weight = float(mapping.get("raf_weight", 0.0))

        diagnosis_entry = {
            "diagnosis_id": row["id"],
            "icd10_code": row["icd10_code"],
            "description": row["description"],
            "hcc_code": hcc_code,
            "hcc_label": row.get("hcc_label")
            or (f"HCC {hcc_code}" if hcc_code else None),
            "raf_weight": raf_weight,
            "review_status": row["review_status"],
            "is_new": bool(hcc_code and hcc_code not in existing_hcc_set),
        }
        document_diagnoses.append(diagnosis_entry)

        if (
            hcc_code
            and hcc_code not in existing_hcc_set
            and hcc_code not in new_hcc_set
        ):
            new_hcc_set.add(hcc_code)
            new_hcc_codes.append(
                {
                    "hcc_code": hcc_code,
                    "hcc_label": diagnosis_entry["hcc_label"],
                    "raf_weight": raf_weight,
                    "source_icd10": row["icd10_code"],
                }
            )
            draft_raf_delta += raf_weight

    draft_raf_score = round(current_raf + draft_raf_delta, 4)
    estimated_revenue_impact = round(draft_raf_delta * REVENUE_FACTOR, 2)

    return _serialize(
        {
            "document_id": document_id,
            "patient_id": patient_id,
            "current_raf_score": round(current_raf, 4),
            "draft_raf_score": draft_raf_score,
            "raf_delta": round(draft_raf_delta, 4),
            "new_hcc_codes": new_hcc_codes,
            "existing_hcc_codes": sorted(existing_hcc_set),
            "document_diagnoses": document_diagnoses,
            "estimated_revenue_impact": estimated_revenue_impact,
        }
    )


# ---------------------------------------------------------------------------
# OpenEMR Document Pull
# ---------------------------------------------------------------------------


@router.get(
    "/openemr/list",
    summary="List documents stored in OpenEMR",
)
@limiter.limit("30/minute")
def list_openemr_documents(
    request: Request,
    patient_id: int = Query(None, description="Filter by patient PID"),
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
    _perm: None = Depends(require_permission("documents", "read")),
) -> dict[str, Any]:
    """List documents from OpenEMR's documents table, optionally filtered by patient."""
    try:  # noqa: C901
        where = "WHERE d.deleted = 0"
        params: list = []
        if patient_id:
            where += " AND d.foreign_id = %s"
            params.append(patient_id)

        with openemr_cursor() as cur:
            cur.execute(
                f"""
                SELECT d.id, d.name, d.mimetype, d.size, d.date, d.foreign_id AS patient_id,
                       d.docdate, d.pages,
                       c.name AS category,
                       pd.fname, pd.lname
                FROM documents d
                LEFT JOIN categories_to_documents cd ON d.id = cd.document_id
                LEFT JOIN categories c ON cd.category_id = c.id
                LEFT JOIN patient_data pd ON d.foreign_id = pd.pid
                {where}
                ORDER BY d.date DESC
                LIMIT 100
                """,
                params or None,
            )
            rows = cur.fetchall()

        # Check which have already been imported into RAF
        openemr_ids = [r["id"] for r in rows]
        imported_set: set[int] = set()
        if openemr_ids:
            placeholders = ",".join(["%s"] * len(openemr_ids))
            with raf_cursor() as cur:
                cur.execute(
                    f"SELECT CAST(SUBSTRING_INDEX(filename, '_emr_', -1) AS UNSIGNED) AS emr_id "
                    f"FROM documents WHERE tenant_id = %s AND filename LIKE '%%_emr_%%' AND "
                    f"CAST(SUBSTRING_INDEX(filename, '_emr_', -1) AS UNSIGNED) IN ({placeholders})",
                    (tenant_id, *openemr_ids),
                )
                for r in cur.fetchall():
                    imported_set.add(int(r["emr_id"]))

        documents = []
        for r in rows:
            documents.append(
                {
                    "openemr_doc_id": r["id"],
                    "name": r["name"],
                    "mimetype": r["mimetype"],
                    "size": r["size"],
                    "date": r["date"].isoformat() if r.get("date") else None,
                    "patient_id": r["patient_id"],
                    "patient_name": f"{r.get('fname', '')} {r.get('lname', '')}".strip(),
                    "category": r.get("category", "Uncategorized"),
                    "already_imported": r["id"] in imported_set,
                }
            )

        return {"total": len(documents), "documents": _serialize(documents)}
    except Exception as exc:
        err_msg = str(exc)
        if "doesn't exist" in err_msg or "1146" in err_msg:
            # OpenEMR documents table not available (minimal install)
            return {
                "total": 0,
                "documents": [],
                "warning": "OpenEMR documents table not available",
            }
        logger.error("list_openemr_documents error: %s", exc)
        raise HTTPException(status_code=500, detail="Could not connect to OpenEMR")


@router.post(
    "/openemr/pull/{openemr_doc_id}",
    summary="Pull a document from OpenEMR and import into RAF",
    status_code=201,
)
@limiter.limit("10/minute")
def pull_openemr_document(
    request: Request,
    openemr_doc_id: int,
    auto_analyze: bool = Query(
        True, description="Auto-trigger Gemini analysis after pull"
    ),
    auto_approve: bool = Query(
        False, description="Auto-approve diagnoses and update RAF (disabled by default)"
    ),
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
    _perm: None = Depends(require_permission("documents", "write")),
) -> dict[str, Any]:
    """Pull a document from OpenEMR, store in RAF, and optionally analyze with Gemini."""
    # Fetch document from OpenEMR
    with openemr_cursor() as cur:
        cur.execute(
            "SELECT id, name, mimetype, size, foreign_id, document_data, date "
            "FROM documents WHERE id = %s AND deleted = 0",
            (openemr_doc_id,),
        )
        emr_doc = cur.fetchone()

    if not emr_doc:
        raise HTTPException(
            status_code=404, detail=f"OpenEMR document {openemr_doc_id} not found"
        )

    file_bytes = emr_doc.get("document_data")
    if not file_bytes:
        raise HTTPException(
            status_code=422, detail="Document has no content (empty blob)"
        )

    patient_id = str(emr_doc["foreign_id"]) if emr_doc.get("foreign_id") else None
    filename = emr_doc.get("name") or f"openemr_doc_{openemr_doc_id}.pdf"
    mime = emr_doc.get("mimetype") or "application/pdf"

    # Store in RAF system
    result = store_upload(
        tenant_id=tenant_id,
        patient_id=patient_id,
        file_bytes=file_bytes
        if isinstance(file_bytes, bytes)
        else file_bytes.encode("latin-1"),
        original_filename=filename,
        document_type="openemr_import",
        encounter_date=emr_doc["date"].strftime("%Y-%m-%d")
        if emr_doc.get("date")
        else None,
    )

    response = {
        "success": True,
        "source": "openemr",
        "openemr_doc_id": openemr_doc_id,
        "document_id": result["document_id"],
        "patient_id": patient_id,
        "filename": filename,
        "is_duplicate": result.get("is_duplicate", False),
    }

    # Auto-analyze with Gemini
    if auto_analyze and not result.get("is_duplicate"):
        try:
            analysis = analyze_document(result["document_id"])
            response["analysis"] = {
                "analysis_id": analysis.get("analysis_id"),
                "diagnosis_count": analysis.get("diagnosis_count", 0),
                "processing_ms": analysis.get("processing_ms", 0),
            }
            # Auto-approve if enabled
            if auto_approve and patient_id:
                approve_result = _do_approve_and_score(
                    result["document_id"], int(patient_id), tenant_id=tenant_id
                )
                response["auto_approved"] = approve_result
        except Exception as exc:
            logger.error(
                "Auto-analysis failed for pulled doc %s: %s", openemr_doc_id, exc
            )
            response["analysis_error"] = "Auto-analysis failed"

    response["auto_approve"] = auto_approve

    return JSONResponse(status_code=201, content=_serialize(response))


# ---------------------------------------------------------------------------
# Push Approved Diagnoses → RAF Scores
# ---------------------------------------------------------------------------


@router.post(
    "/{document_id}/approve-and-score",
    summary="Approve diagnoses and update RAF scores",
)
@limiter.limit("10/minute")
def approve_and_update_raf(
    request: Request,
    document_id: str,
    diagnosis_ids: list[str] = Query(
        None,
        description="Specific diagnosis line IDs to approve. If empty, approves all.",
    ),
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
    _perm: None = Depends(require_permission("documents", "write")),
) -> dict[str, Any]:
    """
    Approve document diagnoses and push them into the RAF scoring pipeline.
    Updates raf_patient_hcc and recalculates raf_scores for the patient.
    """
    # Get the document's patient (tenant-scoped)
    with raf_cursor() as cur:
        cur.execute(
            "SELECT patient_id FROM documents WHERE id = %s AND tenant_id = %s",
            (document_id, tenant_id),
        )
        doc = cur.fetchone()
    if not doc or not doc.get("patient_id"):
        raise HTTPException(status_code=422, detail="Document not linked to a patient")

    patient_id = int(doc["patient_id"])

    # Verify the patient belongs to an active EMR connection
    with raf_cursor() as cur:
        cur.execute(
            f"SELECT 1 FROM raf_scores WHERE patient_id = %s AND {ACTIVE_PATIENTS_SUBQUERY} AND raf_scores.tenant_id = %s LIMIT 1",
            (patient_id, int(tenant_id)),
        )
        if not cur.fetchone():
            raise HTTPException(
                status_code=403,
                detail="Patient is not linked to an active EMR connection.",
            )

    result = _do_approve_and_score(
        document_id, patient_id, diagnosis_ids, tenant_id=tenant_id
    )

    return {
        "approved": result["approved"],
        "patient_id": patient_id,
        "new_hccs_added": result.get("new_hccs", []),
        "new_raf_score": round(float(result["new_raf"]), 4)
        if result.get("new_raf")
        else None,
        "message": f"Approved {result['approved']} diagnoses, added {len(result.get('new_hccs', []))} new HCCs, RAF recalculated",
    }
