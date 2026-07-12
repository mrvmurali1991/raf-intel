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
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, ConfigDict

from app.auth import get_current_user, get_tenant_id, require_permission
from app.db import openemr_cursor, raf_cursor
from app.middleware.idempotency import idempotency_key_dependency, store_idempotent_response
from app.rate_limit import limiter
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
from app.services.emr_manager import active_patients_subquery
from app.services.icd_validator import get_hcc_mapping
from app.services.redis_cache import invalidate_doc_dashboard

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/documents", tags=["documents"])


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------


class _DocBase(BaseModel):
    model_config = ConfigDict(extra="allow")


class DocumentListResponse(BaseModel):
    total: int
    limit: int
    offset: int
    documents: list[dict[str, Any]]


class DocumentStatsResponse(_DocBase):
    total_documents: int
    total_diagnoses: int


class BatchListResponse(BaseModel):
    total: int
    limit: int
    offset: int
    batches: list[dict[str, Any]]


class DeleteDocumentResponse(BaseModel):
    deleted: bool
    document_id: str


class DiagnosisListResponse(BaseModel):
    document_id: str
    count: int
    diagnoses: list[dict[str, Any]]


class DiagnosisReviewResponse(BaseModel):
    diagnosis_id: str
    review_status: str
    reviewed_by: str


class ApproveAndScoreResponse(BaseModel):
    approved: int
    patient_id: int
    new_hccs_added: list[dict[str, Any]]
    new_raf_score: float | None = None
    message: str


class OpenEMRDocumentListResponse(BaseModel):
    total: int
    documents: list[dict[str, Any]]
    warning: str | None = None


class DocumentExtractItem(BaseModel):
    """A single extracted finding pinned to a page of the source document.

    Used by the split-viewer UI (/documents/{id}/viewer). Each extract is the
    coder-facing summary of one suspect HCC condition: clicking it on the
    right pane jumps the PDF on the left to ``page_number``.
    """

    id: str
    label: str
    page_number: int
    snippet: str
    hcc_code: str | None = None
    icd10_code: str | None = None
    confidence: float | None = None


class DocumentExtractsResponse(BaseModel):
    document_id: str
    count: int
    extracts: list[DocumentExtractItem]
    # Indicates whether extracts were derived from real
    # ``raf_suspect_conditions`` rows or returned as mock stubs so the UI
    # can still be exercised end-to-end on dev data.
    source: str


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
    """Approve all HCC-relevant diagnoses and recalculate RAF score.

    Uses a single cursor context for the entire approve + HCC-insert + document
    status update so the operation is atomic — a mid-loop failure will not leave
    partial state.  The HCC existence check is batched into one IN-list query
    and inserts are issued with executemany instead of one round-trip per line.
    """
    if tenant_id is None:
        raise ValueError("tenant_id is required for _do_approve_and_score")
    from datetime import date as _d

    from app.services.raf_calculator import calculate_raf_score

    year = _d.today().year

    # ------------------------------------------------------------------
    # Single cursor block: fetch lines → mark approved → batch-insert
    # HCCs → update document status.  Everything runs inside one
    # connection so a failure rolls back together.
    # ------------------------------------------------------------------
    inserted: list[str] = []

    with raf_cursor() as cur:
        # 1. Fetch the diagnosis lines we need to approve.
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

        # 2. Mark all fetched lines as approved in one bulk update.
        ids = [l["id"] for l in lines]
        cur.executemany(
            "UPDATE document_diagnosis_lines SET review_status='approved' WHERE id = %s",
            [(i,) for i in ids],
        )

        # 3. Batch-check which HCC codes already exist for this patient/year
        #    so we avoid per-row SELECT round-trips.
        hcc_lines = [l for l in lines if l.get("hcc_code")]
        if hcc_lines:
            candidate_hccs = list({l["hcc_code"] for l in hcc_lines})
            ph_hcc = ",".join(["%s"] * len(candidate_hccs))
            cur.execute(
                f"SELECT hcc_code FROM raf_patient_hcc "
                f"WHERE patient_id = %s AND measurement_year = %s AND tenant_id = %s "
                f"AND hcc_code IN ({ph_hcc})",
                (patient_id, year, tenant_id, *candidate_hccs),
            )
            already_exists: set[str] = {r["hcc_code"] for r in cur.fetchall()}

            # 4. Build the list of truly-new HCC rows and insert them all at once.
            rows_to_insert = []
            for l in hcc_lines:
                hcc = l["hcc_code"]
                if hcc in already_exists:
                    continue
                already_exists.add(hcc)  # guard against duplicates within this document
                rows_to_insert.append((
                    patient_id,
                    hcc,
                    _json.dumps([l.get("icd10_code")] if l.get("icd10_code") else []),
                    l.get("description"),
                    year,
                    tenant_id,
                ))
                inserted.append(hcc)

            if rows_to_insert:
                cur.executemany(
                    "INSERT INTO raf_patient_hcc "
                    "(patient_id, hcc_code, icd10_codes, hcc_description, measurement_year, "
                    " source, tenant_id, model_version, created_at) "
                    "VALUES (%s, %s, %s, %s, %s, 'document_analysis', %s, 'V28', NOW())",
                    rows_to_insert,
                )

        # 5. Mark the document itself as approved inside the same connection.
        cur.execute(
            "UPDATE documents SET status='approved' WHERE id = %s AND tenant_id = %s",
            (document_id, tenant_id),
        )

    # ------------------------------------------------------------------
    # Recalculate RAF score (manages its own connection internally).
    # Run outside the cursor block so a scoring error does not roll back
    # the already-committed approve state.
    # ------------------------------------------------------------------
    try:
        raf_result = calculate_raf_score(patient_id, year, tenant_id=tenant_id)
        new_raf = raf_result.get("raf_score") or raf_result.get("final_raf", 0)
    except Exception:
        logger.debug("swallowed exception", exc_info=True)
        new_raf = None

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
    response: Response,
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
    _idem: None = Depends(idempotency_key_dependency()),
):
    """Upload a clinical document for storage and optional Gemini Vision analysis.

    Supports Idempotency-Key header (24h replay window).
    """
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
    store_idempotent_response(request, response, result)
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
    response_model=DocumentListResponse,
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

    # Batch-resolve patient names to avoid N+1 queries
    _patient_names: dict[str, str] = {}
    _patient_ids = list({str(r.get("patient_id") or "") for r in rows if r.get("patient_id") and not r.get("patient_name")})
    if _patient_ids:
        try:
            with raf_cursor() as _pc:
                _ph = ",".join(["%s"] * len(_patient_ids))
                _pc.execute(
                    f"SELECT id, CONCAT(first_name, ' ', last_name) AS name"
                    f" FROM patients WHERE id IN ({_ph}) AND tenant_id = %s",
                    (*_patient_ids, tenant_id),
                )
                for _pr in _pc.fetchall():
                    _patient_names[str(_pr["id"])] = _pr["name"]
                # FHIR fallback for unresolved IDs
                _remaining = [pid for pid in _patient_ids if pid not in _patient_names]
                if _remaining:
                    _ph2 = ",".join(["%s"] * len(_remaining))
                    _pc.execute(
                        f"SELECT epm.emr_pid, CONCAT(p.first_name, ' ', p.last_name) AS name"
                        f" FROM emr_patient_matches epm"
                        f" JOIN patients p ON p.id = epm.patient_id"
                        f" WHERE epm.emr_pid IN ({_ph2}) AND p.tenant_id = %s",
                        (*_remaining, tenant_id),
                    )
                    for _pr in _pc.fetchall():
                        _patient_names[str(_pr["emr_pid"])] = _pr["name"]
        except Exception:
            logger.debug("batch patient name lookup failed", exc_info=True)

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
        if not doc.get("patient_name") and doc.get("patient_id"):
            doc["patient_name"] = _patient_names.get(str(doc["patient_id"]), "")

        analysis = get_analysis(str(doc["id"]))
        if analysis:
            # Normalize diagnosis field names to match frontend interface
            raw_dx = analysis.get("extracted_diagnoses") or []
            if isinstance(raw_dx, str):
                import json as _j

                try:
                    raw_dx = _j.loads(raw_dx)
                except Exception:
                    logger.debug("swallowed exception", exc_info=True)
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
                    logger.debug("swallowed exception", exc_info=True)
                    raw_meds = []

            raw_labs = analysis.get("extracted_labs") or []
            if isinstance(raw_labs, str):
                import json as _j

                try:
                    raw_labs = _j.loads(raw_labs)
                except Exception:
                    logger.debug("swallowed exception", exc_info=True)
                    raw_labs = []

            raw_meat = analysis.get("meat_evidence")
            if isinstance(raw_meat, str):
                import json as _j

                try:
                    raw_meat = _j.loads(raw_meat)
                except Exception:
                    logger.debug("swallowed exception", exc_info=True)
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
    response_model=DocumentStatsResponse,
    response_model_exclude_none=True,
)
def document_stats(
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
    _perm: None = Depends(require_permission("documents", "read")),
) -> dict[str, Any]:
    raw = _serialize(get_document_stats(tenant_id)) or {}
    # Schema declares flat `total_documents` / `total_diagnoses` (used by the
    # admin dashboard summary). The service returns them nested under
    # `documents.*` / `diagnoses.*`; surface both shapes so existing
    # frontend consumers of the nested shape keep working AND the response
    # passes the declared response_model.
    raw.setdefault(
        "total_documents",
        (raw.get("documents") or {}).get("total_documents", 0),
    )
    raw.setdefault(
        "total_diagnoses",
        (raw.get("diagnoses") or {}).get("total_diagnoses", 0),
    )
    return raw


@router.get(
    "/batches",
    summary="List batches",
    description="List all document batches for a tenant.",
    response_model=BatchListResponse,
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
    tenant_id: str = Depends(get_tenant_id),
    _perm: None = Depends(require_permission("documents", "read")),
) -> dict[str, Any]:
    doc = get_document(document_id, tenant_id=tenant_id)
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
    tenant_id: str = Depends(get_tenant_id),
    _perm: None = Depends(require_permission("documents", "read")),
):
    from pathlib import Path

    from fastapi.responses import FileResponse, RedirectResponse, Response

    from app.config import settings as _settings
    from app.services.storage import get_storage_backend

    doc = get_document(document_id, tenant_id=tenant_id)
    if not doc:
        raise _doc_not_found(document_id)

    file_path = doc.get("file_path", "")
    if not file_path:
        raise HTTPException(
            status_code=404, detail="No file path recorded for this document"
        )

    media_type_map = {
        "pdf": "application/pdf",
        "png": "image/png",
        "jpg": "image/jpeg",
        "jpeg": "image/jpeg",
        "doc": "application/msword",
        "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    }
    ext = file_path.rsplit(".", 1)[-1].lower() if "." in file_path else ""
    media_type = doc.get("mime_type") or media_type_map.get(ext, "application/octet-stream")
    display_name = doc.get("document_name") or Path(file_path).name

    backend = str(_settings.storage_backend or "local").lower()
    storage = get_storage_backend()

    # Non-local backends (S3 / MinIO): return a presigned URL redirect so the
    # browser fetches the object directly from object storage.
    if backend != "local":
        try:
            url = storage.signed_url(file_path, expires_in=3600)
            return RedirectResponse(url=url, status_code=302)
        except Exception as exc:
            logger.warning(
                "signed_url failed for %s: %s — falling back to streamed bytes",
                file_path,
                exc,
            )

    # Local backend (or signed_url fallback): stream bytes through the API.
    try:
        data = storage.get(file_path)
        return Response(
            content=data,
            media_type=media_type,
            headers={"Content-Disposition": f'inline; filename="{display_name}"'},
        )
    except FileNotFoundError:
        # Legacy rows stored an absolute path under the project — try filesystem.
        project_root = Path(__file__).resolve().parent.parent.parent
        full_path = (project_root / file_path.lstrip("/")).resolve()
        if not full_path.is_relative_to(project_root.resolve()):
            raise HTTPException(status_code=403, detail="Access denied")
        if not full_path.exists():
            raise HTTPException(status_code=404, detail="File not found on disk")
        return FileResponse(
            path=str(full_path),
            media_type=media_type,
            filename=display_name,
            headers={"Content-Disposition": f'inline; filename="{display_name}"'},
        )


@router.get(
    "/{document_id}/extracts",
    summary="List extracts (HCCs) attached to a document",
    description=(
        "Return the coder-facing extract list for the split-viewer UI. Each "
        "extract is a suspect HCC pinned to a page of the source PDF. We try "
        "to derive extracts from ``raf_suspect_conditions`` rows for the "
        "document's patient that reference this document via "
        "``evidence_detail.source_document_id``. If none are found, we fall "
        "back to 3 mock extracts so the UI is exercisable on dev seed data."
    ),
    response_model=DocumentExtractsResponse,
)
def list_document_extracts(
    document_id: str,
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
    _perm: None = Depends(require_permission("documents", "read")),
) -> dict[str, Any]:
    doc = get_document(document_id, tenant_id=tenant_id)
    if not doc:
        raise _doc_not_found(document_id)

    patient_id = doc.get("patient_id")
    extracts: list[dict[str, Any]] = []
    source = "raf_suspect_conditions"

    if patient_id:
        try:
            with raf_cursor() as cur:
                cur.execute(
                    """
                    SELECT id, suspect_hcc, suspect_icd10, evidence_detail,
                           confidence_score, status
                    FROM raf_suspect_conditions
                    WHERE patient_id = %s AND tenant_id = %s
                    ORDER BY confidence_score DESC, id ASC
                    LIMIT 50
                    """,
                    (patient_id, tenant_id),
                )
                suspect_rows = cur.fetchall()
        except Exception as exc:
            logger.warning("extracts: suspect lookup failed for %s: %s", document_id, exc)
            suspect_rows = []

        for row in suspect_rows:
            ed_raw = row.get("evidence_detail")
            ed: dict[str, Any] = {}
            if isinstance(ed_raw, dict):
                ed = ed_raw
            elif isinstance(ed_raw, (str, bytes)):
                try:
                    ed = _json.loads(
                        ed_raw if isinstance(ed_raw, str) else ed_raw.decode("utf-8")
                    )
                    if not isinstance(ed, dict):
                        ed = {}
                except Exception:
                    logger.debug("swallowed exception", exc_info=True)
                    ed = {}

            src_doc_id = ed.get("source_document_id")
            # Only include if this suspect is linked to the document we're
            # serving. We compare as strings to avoid type mismatch
            # (document_id is a UUID string, ed values may be either).
            if src_doc_id is not None and str(src_doc_id) != str(document_id):
                continue
            # If no source_document_id is set on any rows for this patient,
            # we'll fall through to the mock path below.
            if src_doc_id is None:
                continue

            page_number = int(ed.get("page_number") or ed.get("page") or 1)
            snippet = str(
                ed.get("snippet")
                or ed.get("evidence_text")
                or ed.get("note")
                or ""
            )
            hcc = row.get("suspect_hcc")
            icd = row.get("suspect_icd10") or ""
            extracts.append(
                {
                    "id": f"suspect-{row['id']}",
                    "label": f"{icd}{' — ' if icd else ''}HCC {hcc}".strip(" —"),
                    "page_number": max(1, page_number),
                    "snippet": snippet[:400],
                    "hcc_code": str(hcc) if hcc is not None else None,
                    "icd10_code": icd or None,
                    "confidence": float(row["confidence_score"])
                    if row.get("confidence_score") is not None
                    else None,
                }
            )

    if not extracts:
        # Fallback: derive 3 mock extracts so the split-viewer UI is
        # immediately exercisable on dev data (where suspects often have no
        # source_document_id wired up yet).
        source = "mock"
        doc_name = doc.get("document_name") or doc.get("filename") or "this document"
        extracts = [
            {
                "id": f"mock-{document_id}-1",
                "label": "E11.9 — HCC 19 (Diabetes w/o complications)",
                "page_number": 1,
                "snippet": (
                    f"Mock extract derived from {doc_name}. Patient noted to "
                    "have type 2 diabetes, on metformin 500 mg BID."
                ),
                "hcc_code": "19",
                "icd10_code": "E11.9",
                "confidence": 0.82,
            },
            {
                "id": f"mock-{document_id}-2",
                "label": "I10 — HCC supports (Essential hypertension)",
                "page_number": 1,
                "snippet": (
                    "BP 148/92 mmHg recorded. Continue lisinopril 10 mg daily."
                ),
                "hcc_code": None,
                "icd10_code": "I10",
                "confidence": 0.74,
            },
            {
                "id": f"mock-{document_id}-3",
                "label": "N18.3 — HCC 138 (CKD stage 3)",
                "page_number": 2,
                "snippet": (
                    "Most recent eGFR 47 mL/min/1.73m^2. Discussed renal-"
                    "protective measures and avoidance of NSAIDs."
                ),
                "hcc_code": "138",
                "icd10_code": "N18.3",
                "confidence": 0.68,
            },
        ]

    return {
        "document_id": document_id,
        "count": len(extracts),
        "extracts": extracts,
        "source": source,
    }


@router.delete(
    "/{document_id}",
    summary="Delete document",
    description="Delete the document record, all analysis results, and the file on disk.",
    response_model=DeleteDocumentResponse,
)
def delete_document_endpoint(
    document_id: str,
    current_user: dict = Depends(get_current_user),
    _perm: None = Depends(require_permission("documents", "delete")),
) -> DeleteDocumentResponse:
    deleted = delete_document(document_id)
    if not deleted:
        raise _doc_not_found(document_id)
    return DeleteDocumentResponse(deleted=True, document_id=document_id)


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
    tenant_id: str = Depends(get_tenant_id),
) -> dict[str, Any]:
    doc = get_document(document_id, tenant_id=tenant_id)
    if not doc:
        raise _doc_not_found(document_id)

    if doc["status"] == "processing":
        raise HTTPException(
            status_code=409, detail="Analysis is already in progress for this document"
        )

    if run_in_background:
        background_tasks.add_task(analyze_document, document_id, tenant_id)
        return {
            "document_id": document_id,
            "status": "queued",
            "message": "Gemini Vision analysis started in background. Poll GET /{id}/analysis for results.",
        }

    try:
        result = analyze_document(document_id, tenant_id=tenant_id)
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
    tenant_id: str = Depends(get_tenant_id),
    _perm: None = Depends(require_permission("documents", "read")),
) -> dict[str, Any]:
    doc = get_document(document_id, tenant_id=tenant_id)
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
    response_model=DiagnosisListResponse,
)
def get_diagnoses_endpoint(
    document_id: str,
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
    _perm: None = Depends(require_permission("documents", "read")),
) -> dict[str, Any]:
    doc = get_document(document_id, tenant_id=tenant_id)
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
    response_model=DiagnosisReviewResponse,
)
def confirm_diagnosis(
    document_id: str,
    diag_id: str,
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
    _perm: None = Depends(require_permission("documents", "write")),
) -> dict[str, Any]:
    reviewed_by = f"user:{current_user.get('id', 'unknown')} ({current_user.get('email', 'unknown')})"
    doc = get_document(document_id, tenant_id=tenant_id)
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

    # A doc-level review change makes the ingestion dashboard counters stale.
    try:
        tenant_id = current_user.get("tenant_id") or "global"
        invalidate_doc_dashboard(tenant_id)
    except Exception as exc:
        logger.debug("confirm_diagnosis: cache invalidation failed: %s", exc)

    return DiagnosisReviewResponse(
        diagnosis_id=diag_id,
        review_status="confirmed",
        reviewed_by=reviewed_by,
    )


@router.put(
    "/{document_id}/diagnoses/{diag_id}/reject",
    summary="Reject a diagnosis",
    description=(
        "Mark a Gemini-extracted diagnosis as rejected/incorrect. "
        "The reviewer identity is derived from the authenticated JWT."
    ),
    response_model=DiagnosisReviewResponse,
)
def reject_diagnosis(
    document_id: str,
    diag_id: str,
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
    _perm: None = Depends(require_permission("documents", "write")),
) -> dict[str, Any]:
    reviewed_by = f"user:{current_user.get('id', 'unknown')} ({current_user.get('email', 'unknown')})"
    doc = get_document(document_id, tenant_id=tenant_id)
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

    return DiagnosisReviewResponse(
        diagnosis_id=diag_id,
        review_status="rejected",
        reviewed_by=reviewed_by,
    )


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
    tenant_id: str = Depends(get_tenant_id),
    _perm: None = Depends(require_permission("documents", "write")),
) -> dict[str, Any]:
    doc = get_document(document_id, tenant_id=tenant_id)
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

    doc = get_document(document_id, tenant_id=tenant_id)
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
    _sf, _sp = active_patients_subquery(int(tenant_id))
    with raf_cursor() as cur:
        cur.execute(
            f"SELECT 1 FROM raf_scores WHERE patient_id = %s AND {_sf} AND raf_scores.tenant_id = %s LIMIT 1",
            (patient_id, *_sp, int(tenant_id)),
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
    response_model=OpenEMRDocumentListResponse,
    response_model_exclude_none=True,
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
        logger.exception("list_openemr_documents error: %s", exc)
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
    response_model=ApproveAndScoreResponse,
    response_model_exclude_none=True,
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
    _sf2, _sp2 = active_patients_subquery(int(tenant_id))
    with raf_cursor() as cur:
        cur.execute(
            f"SELECT 1 FROM raf_scores WHERE patient_id = %s AND {_sf2} AND raf_scores.tenant_id = %s LIMIT 1",
            (patient_id, *_sp2, int(tenant_id)),
        )
        if not cur.fetchone():
            raise HTTPException(
                status_code=403,
                detail="Patient is not linked to an active EMR connection.",
            )

    result = _do_approve_and_score(
        document_id, patient_id, diagnosis_ids, tenant_id=tenant_id
    )

    return ApproveAndScoreResponse(
        approved=result["approved"],
        patient_id=patient_id,
        new_hccs_added=result.get("new_hccs", []),
        new_raf_score=round(float(result["new_raf"]), 4) if result.get("new_raf") else None,
        message=f"Approved {result['approved']} diagnoses, added {len(result.get('new_hccs', []))} new HCCs, RAF recalculated",
    )
