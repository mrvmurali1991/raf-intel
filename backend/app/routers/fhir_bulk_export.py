"""Admin endpoints for FHIR Bulk Data $export lifecycle management.

Endpoints:
    POST /api/admin/fhir/bulk-export/run
    GET  /api/admin/fhir/bulk-export/{export_id}
    GET  /api/admin/fhir/bulk-export
"""
from __future__ import annotations

import json
import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.auth import get_current_user, get_tenant_id, require_permission

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/admin/fhir/bulk-export",
    tags=["fhir-bulk-export"],
    dependencies=[Depends(get_current_user)],
)


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------


class BulkExportRunRequest(BaseModel):
    ehr_connection_id: int
    since: str | None = Field(
        default=None,
        description="ISO-8601 datetime for incremental export, e.g. 2025-01-01T00:00:00Z",
    )
    group_id: str | None = Field(
        default=None, description="FHIR Group resource ID; defaults to 'all'"
    )
    types: list[str] | None = Field(
        default=None,
        description="FHIR resource types to request (default: DocumentReference, Condition, Encounter, Observation, Patient)",
    )


class BulkExportRunResponse(BaseModel):
    export_id: int
    status: str
    polling_url: str | None


# ---------------------------------------------------------------------------
# POST /api/admin/fhir/bulk-export/run
# ---------------------------------------------------------------------------


@router.post(
    "/run",
    response_model=BulkExportRunResponse,
    summary="Kick off a FHIR Bulk Data $export for an EHR connection",
)
def run_bulk_export(
    body: BulkExportRunRequest,
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
    _perm: None = Depends(require_permission("admin", "write")),
) -> dict[str, Any]:
    """Enqueue a `raf.fhir.bulk_export_run` Celery task and return its tracking ID.

    The task performs the full kickoff -> poll -> download -> extract pipeline
    asynchronously.  Use the GET endpoint to check progress.
    """
    from app.db import raf_cursor
    import datetime as _dt

    # Validate connection belongs to tenant
    with raf_cursor() as cur:
        cur.execute(
            "SELECT id, is_active FROM fhir_connections "
            "WHERE id = %s AND tenant_id = %s LIMIT 1",
            (body.ehr_connection_id, tenant_id),
        )
        conn = cur.fetchone()

    if not conn:
        raise HTTPException(
            status_code=404,
            detail=f"EHR connection {body.ehr_connection_id} not found for tenant",
        )
    if not conn.get("is_active"):
        raise HTTPException(
            status_code=400,
            detail=f"EHR connection {body.ehr_connection_id} is inactive",
        )

    # Insert a queued export row so we can return its ID immediately
    kickoff_url_preview = f"(pending kickoff for connection {body.ehr_connection_id})"
    since_dt: _dt.datetime | None = None
    if body.since:
        try:
            since_dt = _dt.datetime.fromisoformat(body.since.replace("Z", "+00:00"))
        except ValueError:
            raise HTTPException(
                status_code=400, detail=f"Invalid since format: {body.since!r}"
            )

    with raf_cursor() as cur:
        cur.execute(
            """
            INSERT INTO fhir_bulk_exports
                (tenant_id, ehr_id, kickoff_url, status, since_iso, group_id)
            VALUES (%s, %s, %s, 'queued', %s, %s)
            """,
            (
                tenant_id,
                body.ehr_connection_id,
                kickoff_url_preview,
                since_dt,
                body.group_id,
            ),
        )
        export_id: int = cur.lastrowid  # type: ignore[assignment]

    # Enqueue the heavy Celery task
    try:
        from app.services.celery_tasks import task_fhir_bulk_export_run

        task_fhir_bulk_export_run.apply_async(
            kwargs={
                "tenant_id": tenant_id,
                "ehr_connection_id": body.ehr_connection_id,
                "since": body.since,
                "group_id": body.group_id,
                "types": body.types,
            },
            queue="heavy",
        )
    except Exception as exc:
        logger.warning("Could not enqueue bulk export task: %s", exc)
        # Row is already inserted; caller can monitor via GET

    logger.info(
        "Bulk export enqueued: export_id=%s tenant=%s connection=%s",
        export_id,
        tenant_id,
        body.ehr_connection_id,
    )
    return {
        "export_id": export_id,
        "status": "queued",
        "polling_url": None,
    }


# ---------------------------------------------------------------------------
# GET /api/admin/fhir/bulk-export/{export_id}
# ---------------------------------------------------------------------------


@router.get(
    "/{export_id}",
    summary="Get full status and manifest for a FHIR bulk export",
)
def get_bulk_export(
    export_id: int,
    tenant_id: str = Depends(get_tenant_id),
    _perm: None = Depends(require_permission("admin", "read")),
) -> dict[str, Any]:
    from app.db import raf_read_cursor

    with raf_read_cursor() as cur:
        cur.execute(
            "SELECT * FROM fhir_bulk_exports WHERE id = %s AND tenant_id = %s LIMIT 1",
            (export_id, tenant_id),
        )
        row = cur.fetchone()

    if not row:
        raise HTTPException(
            status_code=404, detail=f"Export {export_id} not found for tenant"
        )

    result = dict(row)
    # Parse manifest_json if present
    if result.get("manifest_json"):
        try:
            result["manifest"] = json.loads(result["manifest_json"])
        except (json.JSONDecodeError, TypeError):
            result["manifest"] = None
    else:
        result["manifest"] = None

    # Attach file rows
    with raf_read_cursor() as cur:
        cur.execute(
            "SELECT * FROM fhir_bulk_export_files WHERE export_id = %s ORDER BY id",
            (export_id,),
        )
        result["files"] = cur.fetchall() or []

    return result


# ---------------------------------------------------------------------------
# GET /api/admin/fhir/bulk-export   (paginated list)
# ---------------------------------------------------------------------------


@router.get(
    "",
    summary="List FHIR bulk exports for the current tenant",
)
def list_bulk_exports(
    status: str | None = Query(default=None, description="Filter by status"),
    limit: int = Query(default=20, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    tenant_id: str = Depends(get_tenant_id),
    _perm: None = Depends(require_permission("admin", "read")),
) -> dict[str, Any]:
    from app.db import raf_read_cursor

    where_clauses = ["tenant_id = %s"]
    params: list[Any] = [tenant_id]

    if status:
        where_clauses.append("status = %s")
        params.append(status)

    where_sql = " AND ".join(where_clauses)

    with raf_read_cursor() as cur:
        cur.execute(
            f"SELECT COUNT(*) AS total FROM fhir_bulk_exports WHERE {where_sql}",
            params,
        )
        total_row = cur.fetchone()
        total = (total_row or {}).get("total") or 0

        cur.execute(
            f"""
            SELECT id, tenant_id, ehr_id, status, started_at, completed_at,
                   resources_count, since_iso, group_id, polling_url, error
            FROM fhir_bulk_exports
            WHERE {where_sql}
            ORDER BY started_at DESC
            LIMIT %s OFFSET %s
            """,
            [*params, limit, offset],
        )
        rows = cur.fetchall() or []

    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "items": [dict(r) for r in rows],
    }
