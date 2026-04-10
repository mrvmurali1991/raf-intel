"""
Uploads router — CSV/Excel patient data uploads as an alternative to EMR sync.

Routes
------
GET    /api/uploads/template        Download CSV (or ?format=xlsx) import template
POST   /api/uploads/patients        Upload a CSV/XLSX file of patients
GET    /api/uploads                 List past upload sessions for the tenant
GET    /api/uploads/{upload_id}     Details of a single upload
DELETE /api/uploads/{upload_id}     Soft-delete (is_active=0) all patients from an upload

The actual parse/validate/insert logic is delegated to the existing
``patient_import_service``; this router adds upload-session tracking and
tags imported rows with ``data_source='upload'`` + ``upload_id`` so they
can be distinguished from EMR-synced rows and individually removed.
"""

import logging
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import Response

from app.auth import get_current_user, get_tenant_id, require_permission
from app.db import raf_cursor
from app.rate_limit import limiter
from app.services.audit_logger import log_phi_access

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/uploads", tags=["uploads"])

_MAX_UPLOAD_BYTES = 10 * 1024 * 1024  # 10 MB


# ---------------------------------------------------------------------------
# Template download
# ---------------------------------------------------------------------------


@router.get("/template", summary="Download patient upload template (CSV or XLSX)")
def download_template(
    format: str = Query("csv", regex="^(csv|xlsx)$"),
    current_user: dict = Depends(get_current_user),
    _perm: None = Depends(require_permission("patients", "write")),
) -> Response:
    """Return a downloadable template file with the canonical columns."""
    from app.services.patient_import_service import (
        get_import_template as _csv_tpl,
        get_import_template_xlsx as _xlsx_tpl,
    )

    if format == "xlsx":
        content = _xlsx_tpl()
        return Response(
            content=content,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={
                "Content-Disposition": "attachment; filename=raf_patient_template.xlsx"
            },
        )

    csv_text = _csv_tpl()
    return Response(
        content=csv_text,
        media_type="text/csv",
        headers={
            "Content-Disposition": "attachment; filename=raf_patient_template.csv"
        },
    )


# ---------------------------------------------------------------------------
# Upload (patients)
# ---------------------------------------------------------------------------


def _create_upload_session(
    tenant_id: str,
    user_id: int,
    filename: str,
    file_size: int,
    file_type: str,
) -> int:
    with raf_cursor() as cur:
        cur.execute(
            """
            INSERT INTO raf_data_uploads
                (tenant_id, uploaded_by, filename, file_size_bytes, file_type, status)
            VALUES (%s, %s, %s, %s, %s, 'processing')
            """,
            (tenant_id, user_id, filename[:512], file_size, file_type),
        )
        return int(cur.lastrowid)


def _finalize_upload_session(
    upload_id: int,
    status: str,
    total: int,
    imported: int,
    failed: int,
    error_summary: str | None,
) -> None:
    with raf_cursor() as cur:
        cur.execute(
            """
            UPDATE raf_data_uploads
               SET status = %s,
                   row_count_total = %s,
                   row_count_imported = %s,
                   row_count_failed = %s,
                   error_summary = %s,
                   completed_at = %s
             WHERE id = %s
            """,
            (
                status,
                total,
                imported,
                failed,
                (error_summary or "")[:4000] or None,
                datetime.utcnow(),
                upload_id,
            ),
        )


def _tag_uploaded_rows(
    tenant_id: str,
    upload_id: int,
    since_id: int,
) -> int:
    """Tag newly inserted rows for this tenant with data_source/upload_id."""
    with raf_cursor() as cur:
        cur.execute(
            """
            UPDATE patients
               SET data_source = 'upload', upload_id = %s
             WHERE tenant_id = %s AND id > %s AND is_active = 1
            """,
            (upload_id, tenant_id, since_id),
        )
        return int(cur.rowcount or 0)


def _insert_hcc_codes_for_rows(
    tenant_id: str,
    upload_id: int,
    rows: list[dict],
) -> int:
    """If rows carry hcc_codes / ICD-10 lists, insert them into raf_patient_hcc.

    Uses the same grouped-by-patient shape that the EMR direct_db sync uses
    (``raf_patient_hcc`` with a JSON ``icd10_codes`` column).
    """
    import json

    inserted = 0
    measurement_year = datetime.utcnow().year

    # Map MRN -> row's hcc codes and optional measurement_year.
    with raf_cursor() as cur:
        for row in rows:
            codes_raw = (row.get("hcc_codes") or "").strip()
            if not codes_raw:
                continue
            codes = [c.strip().upper() for c in codes_raw.split(",") if c.strip()]
            if not codes:
                continue
            mrn = (row.get("mrn") or "").strip()
            first = (row.get("first_name") or "").strip()
            last = (row.get("last_name") or "").strip()
            dob = (row.get("dob") or "").strip()

            # Resolve patient id within this upload session (so we don't touch
            # EMR-synced patients of the same tenant).
            pid_row = None
            if mrn:
                cur.execute(
                    "SELECT id FROM patients WHERE tenant_id = %s AND mrn = %s AND upload_id = %s LIMIT 1",
                    (tenant_id, mrn, upload_id),
                )
                pid_row = cur.fetchone()
            if pid_row is None and first and last and dob:
                cur.execute(
                    """SELECT id FROM patients
                        WHERE tenant_id = %s AND upload_id = %s
                          AND first_name = %s AND last_name = %s AND dob = %s
                        LIMIT 1""",
                    (tenant_id, upload_id, first, last, dob),
                )
                pid_row = cur.fetchone()
            if not pid_row:
                continue
            pid = int(pid_row["id"])

            try:
                try:
                    my = int(str(row.get("measurement_year") or measurement_year)[:4])
                except (ValueError, TypeError):
                    my = measurement_year

                cur.execute(
                    """SELECT id, icd10_codes FROM raf_patient_hcc
                        WHERE patient_id = %s AND measurement_year = %s
                          AND tenant_id = %s LIMIT 1""",
                    (pid, my, tenant_id),
                )
                existing = cur.fetchone()
                if existing:
                    try:
                        old = json.loads(existing["icd10_codes"] or "[]")
                    except (json.JSONDecodeError, TypeError):
                        old = []
                    merged = sorted(set(list(old) + codes))
                    cur.execute(
                        "UPDATE raf_patient_hcc SET icd10_codes = %s, updated_at = NOW() WHERE id = %s",
                        (json.dumps(merged), existing["id"]),
                    )
                else:
                    cur.execute(
                        """INSERT INTO raf_patient_hcc
                            (patient_id, measurement_year, hcc_code, icd10_codes,
                             source_encounter_ids, raf_coefficient, meat_status, is_trumped, tenant_id)
                           VALUES (%s, %s, 0, %s, '[]', 0, 'missing', 0, %s)""",
                        (pid, my, json.dumps(codes), tenant_id),
                    )
                inserted += len(codes)
            except Exception as exc:
                logger.warning("uploads: hcc insert failed for pid=%s: %s", pid, exc)
    return inserted


@router.post("/patients", summary="Upload a CSV/XLSX file of patients")
@limiter.limit("10/minute")
async def upload_patients(
    request: Request,
    file: UploadFile = File(..., description="CSV or Excel (.xlsx) patient file"),
    current_user: dict = Depends(get_current_user),
    _perm: None = Depends(require_permission("patients", "write")),
) -> dict[str, Any]:
    """Parse + validate + insert patients from an uploaded file.

    Rows are tagged with ``data_source='upload'`` and ``upload_id`` pointing
    back to the ``raf_data_uploads`` session for later review/deletion.
    """
    from app.services.patient_import_service import (
        import_patients as _import,
        parse_patient_csv as _parse_csv,
        parse_patient_xlsx as _parse_xlsx,
    )

    fname = (file.filename or "").strip()
    fname_lower = fname.lower()
    if not fname or not (fname_lower.endswith(".csv") or fname_lower.endswith(".xlsx")):
        raise HTTPException(
            status_code=422,
            detail="Only .csv and .xlsx files are accepted.",
        )
    file_type = "xlsx" if fname_lower.endswith(".xlsx") else "csv"

    content = await file.read()
    if len(content) == 0:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")
    if len(content) > _MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"File too large. Max {_MAX_UPLOAD_BYTES // (1024*1024)} MB.",
        )

    tenant_id = get_tenant_id(current_user)
    user_id = int(current_user.get("id") or 0)

    # Parse first so we fail fast on malformed files.
    if file_type == "xlsx":
        rows, parse_errors = _parse_xlsx(content)
    else:
        rows, parse_errors = _parse_csv(content)

    if parse_errors and not rows:
        raise HTTPException(
            status_code=422,
            detail={"message": "Could not parse uploaded file.", "errors": parse_errors},
        )

    # Create upload session row.
    upload_id = _create_upload_session(
        tenant_id=tenant_id,
        user_id=user_id,
        filename=fname,
        file_size=len(content),
        file_type=file_type,
    )

    # Snapshot current max(patients.id) so we can tag only rows we insert.
    try:
        with raf_cursor() as cur:
            cur.execute(
                "SELECT COALESCE(MAX(id), 0) AS max_id FROM patients WHERE tenant_id = %s",
                (tenant_id,),
            )
            row = cur.fetchone()
            since_id = int(row["max_id"]) if row else 0
    except Exception:
        since_id = 0

    uploader_name = (
        current_user.get("username")
        or current_user.get("email")
        or current_user.get("sub")
        or "upload"
    )

    try:
        summary = _import(
            rows,
            uploaded_by=str(uploader_name),
            on_duplicate="update",
            source="csv" if file_type == "csv" else "excel",
            tenant_id=int(tenant_id) if str(tenant_id).isdigit() else 1,
        )
    except Exception as exc:
        logger.error("uploads: import_patients failed: %s", exc)
        _finalize_upload_session(
            upload_id, "failed", len(rows), 0, len(rows), f"Importer error: {exc}"
        )
        raise HTTPException(status_code=500, detail="Import failed") from exc

    # Tag newly inserted rows with upload_id / data_source='upload'.
    try:
        _tag_uploaded_rows(tenant_id=tenant_id, upload_id=upload_id, since_id=since_id)
    except Exception as exc:
        logger.warning("uploads: tag rows failed: %s", exc)

    # Insert HCC/ICD-10 codes if the file carried them.
    try:
        _insert_hcc_codes_for_rows(
            tenant_id=tenant_id, upload_id=upload_id, rows=rows
        )
    except Exception as exc:
        logger.warning("uploads: hcc insertion failed: %s", exc)

    total = int(summary.get("total_rows") or 0)
    imported = int(summary.get("imported") or 0)
    updated = int(summary.get("updated") or 0)
    failed = int(summary.get("errors") or 0)
    error_details = summary.get("error_details") or []
    if parse_errors:
        failed += len(parse_errors)
        error_details = list(parse_errors) + list(error_details)

    status = "completed"
    if failed and (imported + updated) == 0:
        status = "failed"
    elif failed:
        status = "partial"

    error_summary_str = "\n".join(str(e) for e in error_details[:50]) if error_details else None
    _finalize_upload_session(
        upload_id=upload_id,
        status=status,
        total=total,
        imported=imported + updated,
        failed=failed,
        error_summary=error_summary_str,
    )

    log_phi_access(
        action="file_upload",
        resource="patient",
        details=(
            f"upload_id={upload_id} filename={fname!r} total={total} "
            f"imported={imported} updated={updated} failed={failed}"
        ),
    )

    return {
        "upload_id": upload_id,
        "filename": fname,
        "file_type": file_type,
        "row_count_total": total,
        "row_count_imported": imported + updated,
        "row_count_failed": failed,
        "status": status,
        "errors": error_details[:100],
    }


# ---------------------------------------------------------------------------
# List / detail / delete
# ---------------------------------------------------------------------------


@router.get("", summary="List past patient uploads")
def list_uploads(
    current_user: dict = Depends(get_current_user),
    _perm: None = Depends(require_permission("patients", "read")),
) -> dict[str, Any]:
    tenant_id = get_tenant_id(current_user)
    with raf_cursor() as cur:
        cur.execute(
            """
            SELECT id, tenant_id, uploaded_by, filename, file_size_bytes, file_type,
                   row_count_total, row_count_imported, row_count_failed,
                   status, created_at, completed_at
              FROM raf_data_uploads
             WHERE tenant_id = %s
             ORDER BY created_at DESC
             LIMIT 200
            """,
            (tenant_id,),
        )
        rows = cur.fetchall() or []
    out = []
    for r in rows:
        item = {k: v for k, v in r.items()}
        for k, v in list(item.items()):
            if hasattr(v, "isoformat"):
                item[k] = v.isoformat()
        out.append(item)
    return {"uploads": out, "total": len(out)}


@router.get("/{upload_id}", summary="Get details of a single upload")
def get_upload(
    upload_id: int,
    current_user: dict = Depends(get_current_user),
    _perm: None = Depends(require_permission("patients", "read")),
) -> dict[str, Any]:
    tenant_id = get_tenant_id(current_user)
    with raf_cursor() as cur:
        cur.execute(
            "SELECT * FROM raf_data_uploads WHERE id = %s AND tenant_id = %s",
            (upload_id, tenant_id),
        )
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Upload not found")
        cur.execute(
            "SELECT COUNT(*) AS cnt FROM patients WHERE upload_id = %s AND tenant_id = %s AND is_active = 1",
            (upload_id, tenant_id),
        )
        active_count = int((cur.fetchone() or {}).get("cnt") or 0)

    item = {k: v for k, v in row.items()}
    for k, v in list(item.items()):
        if hasattr(v, "isoformat"):
            item[k] = v.isoformat()
    item["active_patient_count"] = active_count
    return item


@router.delete("/{upload_id}", summary="Soft-delete all patients from an upload")
def delete_upload(
    upload_id: int,
    confirm: bool = Query(False, description="Set to true to confirm deletion"),
    current_user: dict = Depends(get_current_user),
    _perm: None = Depends(require_permission("patients", "write")),
) -> dict[str, Any]:
    if not confirm:
        raise HTTPException(
            status_code=400,
            detail="Deletion requires ?confirm=true",
        )
    tenant_id = get_tenant_id(current_user)
    with raf_cursor() as cur:
        cur.execute(
            "SELECT id FROM raf_data_uploads WHERE id = %s AND tenant_id = %s",
            (upload_id, tenant_id),
        )
        if not cur.fetchone():
            raise HTTPException(status_code=404, detail="Upload not found")

        cur.execute(
            "UPDATE patients SET is_active = 0 WHERE upload_id = %s AND tenant_id = %s AND is_active = 1",
            (upload_id, tenant_id),
        )
        deleted = int(cur.rowcount or 0)

    log_phi_access(
        action="delete",
        resource="upload",
        details=f"upload_id={upload_id} soft_deleted={deleted}",
    )
    return {"upload_id": upload_id, "deleted": deleted}
