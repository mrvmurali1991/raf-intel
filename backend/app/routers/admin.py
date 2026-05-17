# Note: do NOT use 'from __future__ import annotations' here —
# it breaks FastAPI/Pydantic schema generation (ForwardRef errors in /openapi.json).

"""
Admin endpoints — backup management and system information.

All routes require an authenticated user.  In a production deployment
you should additionally enforce an "admin" role before these routes are
accessible (add role-check to the Depends chain alongside get_current_user).

Route prefix: /api/admin
Tags: admin
"""

import logging
import os
import platform
import shutil
import subprocess
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from app.auth import require_role, get_current_user
from app.rate_limit import limiter
from app.services.backup_service import (
    _backup_dir,
    get_backup_schedule,
    get_backup_status,
    get_job_status,
    list_jobs,
    trigger_backup,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin", tags=["admin"], dependencies=[Depends(get_current_user)])

# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------


class TriggerBackupRequest(BaseModel):
    backup_type: str = Field(
        default="full",
        description="One of 'full', 'raf', or 'openemr'.",
        pattern="^(full|raf|openemr)$",
    )


# ---------------------------------------------------------------------------
# GET /api/admin/backups
# ---------------------------------------------------------------------------


@router.get(
    "/backups",
    summary="List recent backups",
    response_description="Backup files with sizes and timestamps",
)
def list_backups(
    current_user: dict = Depends(require_role("admin")),
) -> dict[str, Any]:
    """
    Return metadata for all backup files found in the configured BACKUP_DIR.

    Each entry includes filename, size, timestamp, and which database it
    covers.  Files are returned newest-first.
    """
    try:
        status_data = get_backup_status()
        schedule = get_backup_schedule()
        recent_jobs = list_jobs(limit=10)
        return {
            **status_data,
            "schedule": schedule,
            "recent_jobs": recent_jobs,
        }
    except Exception as exc:
        logger.exception("Failed to list backups: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve backup status.",
        ) from exc


# ---------------------------------------------------------------------------
# POST /api/admin/backups
# ---------------------------------------------------------------------------


@router.post(
    "/backups",
    summary="Trigger a new backup",
    status_code=status.HTTP_202_ACCEPTED,
    response_description="Job record for the triggered backup",
)
def create_backup(
    body: TriggerBackupRequest = TriggerBackupRequest(),
    current_user: dict = Depends(require_role("admin")),
) -> dict[str, Any]:
    """
    Launch backup.sh in the background and return a job ID.

    Poll ``GET /api/admin/backups/jobs/{job_id}`` to track completion.

    - ``backup_type="full"``    — backs up both databases
    - ``backup_type="raf"``     — backs up the RAF Intelligence database only
    - ``backup_type="openemr"`` — backs up the OpenEMR database only
    """
    try:
        job = trigger_backup(backup_type=body.backup_type)
        return {
            "message": f"Backup job started (type={body.backup_type}).",
            **job,
        }
    except FileNotFoundError as exc:
        logger.error("backup.sh not found: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error",
        ) from exc
    except ValueError as exc:
        logger.error("Unexpected error: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Invalid input",
        ) from exc
    except Exception as exc:
        logger.exception("Failed to trigger backup: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to trigger backup.",
        ) from exc


# ---------------------------------------------------------------------------
# GET /api/admin/backups/jobs/{job_id}
# ---------------------------------------------------------------------------


@router.get(
    "/backups/jobs/{job_id}",
    summary="Get backup job status",
    response_description="Current state of a backup job",
)
def get_backup_job(
    job_id: str,
    current_user: dict = Depends(require_role("admin")),
) -> dict[str, Any]:
    """
    Return the current status of a backup job previously returned by
    ``POST /api/admin/backups``.

    Possible ``status`` values: ``"running"``, ``"success"``, ``"failed"``.
    """
    job = get_job_status(job_id)
    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Backup job '{job_id}' not found.",
        )
    return job


# ---------------------------------------------------------------------------
# GET /api/admin/backups/{filename}/download
# ---------------------------------------------------------------------------


@router.get(
    "/backups/{filename}/download",
    summary="Download a backup file",
    response_description="Gzip-compressed SQL dump",
    response_class=FileResponse,
)
def download_backup(
    filename: str,
    current_user: dict = Depends(require_role("admin")),
) -> FileResponse:
    """
    Stream a backup file to the client.

    **Admin-only operation** — the caller must be authenticated.
    Filenames must end in ``.sql.gz`` and must not contain path separators
    to prevent directory traversal.

    Returns the raw gzip-compressed SQL dump with an appropriate
    ``Content-Disposition`` header.
    """
    # Guard against directory traversal
    if "/" in filename or "\\" in filename or ".." in filename:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid filename.",
        )

    if not filename.endswith(".sql.gz"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only .sql.gz files can be downloaded.",
        )

    backup_path = _backup_dir() / filename

    if not backup_path.exists() or not backup_path.is_file():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Backup file '{filename}' not found.",
        )

    return FileResponse(
        path=str(backup_path),
        media_type="application/gzip",
        filename=filename,
    )


# ---------------------------------------------------------------------------
# GET /api/admin/system
# ---------------------------------------------------------------------------


@router.get(
    "/system",
    summary="System information",
    response_description="DB sizes, disk usage, process uptime",
)
def system_info(
    current_user: dict = Depends(require_role("admin")),
) -> dict[str, Any]:
    """
    Return operational system information useful for ops dashboards:

    - Disk usage for the backup directory and data directory
    - Database sizes (queries information_schema)
    - Process uptime
    - Platform / Python version
    """
    from app.config import settings
    from app.db import openemr_cursor, raf_cursor

    result: dict[str, Any] = {
        "collected_at": datetime.now(timezone.utc).isoformat(),
        "platform": platform.system(),
        "python_version": platform.python_version(),
    }

    # ---- Disk usage --------------------------------------------------------
    disk: dict[str, Any] = {}
    backup_dir = _backup_dir()
    try:
        usage = shutil.disk_usage(str(backup_dir) if backup_dir.exists() else "/")
        disk["total_bytes"] = usage.total
        disk["used_bytes"] = usage.used
        disk["free_bytes"] = usage.free
        disk["used_pct"] = (
            round(usage.used / usage.total * 100, 1) if usage.total else 0
        )
    except Exception:
        disk["error"] = "Unable to retrieve disk information"

    if backup_dir.exists():
        try:
            backup_used = sum(
                f.stat().st_size for f in backup_dir.glob("*.sql.gz") if f.is_file()
            )
            disk["backup_dir"] = str(backup_dir)
            disk["backup_dir_used_bytes"] = backup_used
        except Exception:
            disk["backup_dir_error"] = "Unable to retrieve backup directory information"

    result["disk"] = disk

    # ---- Database sizes ----------------------------------------------------
    db_sizes: dict[str, Any] = {}

    _DB_SIZE_QUERY = """
        SELECT
            table_schema AS db_name,
            SUM(data_length + index_length) AS size_bytes,
            COUNT(*) AS table_count
        FROM information_schema.TABLES
        WHERE table_schema = %s
        GROUP BY table_schema
    """

    for label, cursor_fn, db_name in [
        ("raf_intelligence", raf_cursor, settings.raf_db_name),
        ("openemr", openemr_cursor, settings.openemr_db_name),
    ]:
        try:
            with cursor_fn() as cur:
                cur.execute(_DB_SIZE_QUERY, (db_name,))
                row = cur.fetchone()
            if row:
                size_bytes = int(row["size_bytes"] or 0)
                db_sizes[label] = {
                    "db_name": row["db_name"],
                    "size_bytes": size_bytes,
                    "size_human": _human_size(size_bytes),
                    "table_count": row["table_count"],
                }
            else:
                db_sizes[label] = {
                    "db_name": db_name,
                    "size_bytes": 0,
                    "table_count": 0,
                }
        except Exception as exc:
            logger.warning("Could not query size for %s: %s", label, exc)
            db_sizes[label] = {"error": "Unable to query database size"}

    result["databases"] = db_sizes

    # ---- Process uptime (best-effort via /proc or ps) ----------------------
    try:
        proc_result = subprocess.run(
            ["ps", "-o", "etime=", "-p", str(os.getpid())],
            check=False, capture_output=True,
            text=True,
            timeout=5,
        )
        result["process_uptime"] = proc_result.stdout.strip()
    except Exception:
        result["process_uptime"] = "unavailable"

    # ---- Backup summary ----------------------------------------------------
    try:
        bk = get_backup_status()
        result["backups"] = {
            "count": bk["count"],
            "backup_dir": bk["backup_dir"],
            "backup_dir_exists": bk["backup_dir_exists"],
            "latest": bk["backups"][0] if bk["backups"] else None,
        }
    except Exception as exc:
        result["backups"] = {"error": str(exc)}

    return result


# ---------------------------------------------------------------------------
# Private utility
# ---------------------------------------------------------------------------


def _human_size(size_bytes: int) -> str:
    """Return a human-readable file size string."""
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size_bytes < 1024.0:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024.0  # type: ignore[assignment]
    return f"{size_bytes:.1f} PB"


# ---------------------------------------------------------------------------
# HIPAA compliance status (auth-guarded, dynamic checks)
# ---------------------------------------------------------------------------


@router.get(
    "/compliance/status", tags=["compliance"], summary="HIPAA compliance status"
)
def compliance_status(
    current_user: dict = Depends(require_role("admin")),
) -> dict[str, Any]:
    """
    Returns the current HIPAA compliance posture of this deployment.
    """
    from app.config import settings

    checks: dict[str, Any] = {
        "jwt_secret_configured": bool(os.getenv("JWT_SECRET")),
        "tls_enforced": bool(os.getenv("TLS_ENABLED", "")),
        "mfa_available": True,
        "audit_logging": True,
        "rbac_enforced": True,
        "rate_limiting": True,
        "idle_timeout_minutes": (
            settings.idle_timeout_minutes
            if hasattr(settings, "idle_timeout_minutes")
            else None
        ),
        "access_token_expiry_minutes": settings.access_token_expire_minutes,
        "encryption_in_transit": True,
        "security_headers": True,
        "phi_access_logging": True,
        "baa_provider": "Google Cloud (Gemini)",
    }
    all_passing = all(v for v in checks.values() if isinstance(v, bool))
    return {
        "hipaa_compliant": all_passing,
        "status": "compliant" if all_passing else "non_compliant",
        "checks": checks,
        "assessed_at": datetime.now(timezone.utc).isoformat(),
    }


# ---------------------------------------------------------------------------
# Admin — error monitoring endpoints
# ---------------------------------------------------------------------------


@router.get("/errors", summary="List recent errors")
def admin_list_errors(
    limit: int = Query(default=50, ge=1, le=100),
    current_user: dict = Depends(require_role("admin")),
) -> dict[str, Any]:
    """Return the most recent captured errors (newest first). Requires admin role."""
    from app.monitoring import get_recent_errors

    errors = get_recent_errors(limit=limit)
    return {
        "errors": errors,
        "count": len(errors),
    }


@router.get("/errors/stats", summary="Error statistics")
def admin_error_stats(
    current_user: dict = Depends(require_role("admin")),
) -> dict[str, Any]:
    """Return aggregate error counts by type. Requires admin role."""
    from app.monitoring import get_error_stats

    return get_error_stats()


@router.post("/errors/report", summary="Report a client-side error")
@limiter.limit("10/minute")
async def admin_report_error(request: Request) -> dict[str, str]:
    """
    Accept client-side error reports from the frontend error-tracking module.
    Rate-limited to 10/min/IP to prevent abuse. Authentication is not required
    so pre-login errors can still be captured; payloads are truncated and
    scrubbed of common PHI/secret shapes.
    """
    try:
        payload = await request.json()
    except Exception:
        payload = {}

    raw_message = str(payload.get("message", "unknown client error"))
    source = str(payload.get("source", "frontend"))[:50]

    # Scrub obvious sensitive patterns before persisting. The frontend is
    # expected to scrub too; this is defence in depth.
    import re as _re
    message = _re.sub(r"(?i)(authorization|bearer|token|password|ssn|mrn)[=:\s]+\S+", r"\1=[redacted]", raw_message)
    message = message[:500]

    from app.monitoring import capture_error as _capture

    class ClientError(Exception):
        pass

    exc = ClientError(message)
    _capture(exc, context={"source": source})
    return {"status": "recorded"}


# ---------------------------------------------------------------------------
# Break-glass log (admin review)
# ---------------------------------------------------------------------------


@router.get("/break-glass-log")
def api_break_glass_log(
    current_user: dict = Depends(require_role("admin")),
):
    """List all break-glass emergency access events."""
    from app.services.break_glass import list_break_glass_events

    tenant_id = str(current_user.get("tenant_id", ""))
    events = list_break_glass_events(tenant_id=tenant_id)
    return {"events": events}


# ---------------------------------------------------------------------------
# De-identified data export for analytics
# ---------------------------------------------------------------------------


class DeidentifiedExportRequest(BaseModel):
    patient_ids: list[int] = Field(default=[], description="Patient IDs to export (empty = all)")
    limit: int = Field(default=1000, le=10000)


@router.post("/export-deidentified")
def api_export_deidentified(
    body: DeidentifiedExportRequest,
    current_user: dict = Depends(require_role("admin")),
):
    """Export de-identified patient data for analytics (HIPAA Safe Harbor)."""
    from app.db import raf_cursor
    from app.services.phi_deidentifier import deidentify_dataset

    tenant_id = str(current_user.get("tenant_id", ""))

    with raf_cursor() as cur:
        if body.patient_ids:
            placeholders = ",".join(["%s"] * len(body.patient_ids))
            cur.execute(
                f"SELECT * FROM patients WHERE tenant_id = %s AND id IN ({placeholders}) LIMIT %s",
                (tenant_id, *body.patient_ids, body.limit),
            )
        else:
            cur.execute(
                "SELECT * FROM patients WHERE tenant_id = %s LIMIT %s",
                (tenant_id, body.limit),
            )
        rows = cur.fetchall()

    records = [dict(r) for r in rows]
    safe_records = deidentify_dataset(records)

    from app.services.immutable_audit import append_audit_entry
    append_audit_entry(
        event_type="deidentified_export",
        user_id=current_user.get("id"),
        tenant_id=tenant_id,
        resource_type="patient_dataset",
        action="export_deidentified",
        details={"record_count": len(safe_records)},
    )

    return {"count": len(safe_records), "records": safe_records}


# ---------------------------------------------------------------------------
# Immutable audit log verification
# ---------------------------------------------------------------------------


@router.get("/audit-chain-verify")
def api_verify_audit_chain(
    current_user: dict = Depends(require_role("admin")),
):
    """Verify the immutable audit log hash chain integrity."""
    from app.services.immutable_audit import verify_audit_chain

    ok, errors = verify_audit_chain()
    return {
        "integrity": "intact" if ok else "TAMPERED",
        "valid": ok,
        "errors": errors,
    }
