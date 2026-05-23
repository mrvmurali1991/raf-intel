"""
Bulk FHIR ingest router.

Endpoints
---------
``POST   /api/bulk-ingest/start``        — kick off an async Celery ingest job.
``POST   /api/bulk-ingest/upload``       — multipart NDJSON upload (one-shot).
``GET    /api/bulk-ingest/jobs``         — list recent jobs for the caller's tenant.
``GET    /api/bulk-ingest/jobs/{id}``    — single job detail (progress, errors).
``GET    /api/bulk-ingest/jobs/{id}/stream`` — SSE stream of progress events
                                              published to Redis by the worker.

All endpoints are tenant-scoped — the ``tenant_id`` is pulled from the
authenticated user record, never from the request body, per
``feedback_field_names`` / multi-tenant isolation rules.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import tempfile
import uuid
from typing import Any, Optional

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    UploadFile,
    status,
)
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, field_validator
from slowapi.util import get_remote_address

from app.auth import get_current_user, get_tenant_id, require_permission
from app.services import bulk_ingest_service
from app.services.bulk_ingest_service import MAX_UPLOAD_BYTES, PROGRESS_CHANNEL_FMT

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/bulk-ingest", tags=["bulk_ingest"])


# ---------------------------------------------------------------------------
# Request / response schemas
# ---------------------------------------------------------------------------

_ALLOWED_SOURCE_TYPES = {"fhir_bulk_export", "ndjson_upload"}
_DEFAULT_RESOURCE_TYPES = ["Patient", "Condition", "Encounter", "Observation"]
_ALLOWED_RESOURCE_TYPES = {"Patient", "Condition", "Encounter", "Observation"}


class BulkIngestStartIn(BaseModel):
    source_url: Optional[str] = Field(
        default=None,
        description="FHIR Bulk Data $export endpoint URL (required when source_type=fhir_bulk_export).",
    )
    source_type: str = Field(
        ...,
        description="One of 'fhir_bulk_export' or 'ndjson_upload'.",
    )
    resource_types: list[str] = Field(
        default_factory=lambda: list(_DEFAULT_RESOURCE_TYPES),
        description="Subset of {Patient, Condition, Encounter, Observation} to ingest.",
    )

    @field_validator("source_type")
    @classmethod
    def _valid_source_type(cls, v: str) -> str:
        if v not in _ALLOWED_SOURCE_TYPES:
            raise ValueError(
                f"source_type must be one of {sorted(_ALLOWED_SOURCE_TYPES)}"
            )
        return v

    @field_validator("resource_types")
    @classmethod
    def _valid_resource_types(cls, v: list[str]) -> list[str]:
        bad = [r for r in v if r not in _ALLOWED_RESOURCE_TYPES]
        if bad:
            raise ValueError(
                f"unsupported resource types: {bad}. allowed={sorted(_ALLOWED_RESOURCE_TYPES)}"
            )
        return v


class BulkIngestStartOut(BaseModel):
    job_id: str
    status: str
    source_type: str


class BulkIngestJobOut(BaseModel):
    id: str
    tenant_id: str
    source_type: str
    source_url: Optional[str] = None
    status: str
    total_resources: int
    ingested_resources: int
    errors_count: int
    patient_count: int
    condition_count: int
    encounter_count: int
    observation_count: int
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    errors: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Simple per-actor rate limit — a single tenant should not be allowed to
# queue more than 5 ingest jobs per minute.  Sliding-window counters in
# Redis are overkill for this volume; a small in-process dict is fine.
# ---------------------------------------------------------------------------

_RATE_WINDOW_S = 60
_RATE_MAX_REQUESTS = 5
_rate_state: dict[str, list[float]] = {}


def _enforce_rate_limit(actor_key: str) -> None:
    import time

    now = time.monotonic()
    bucket = [t for t in _rate_state.get(actor_key, []) if now - t < _RATE_WINDOW_S]
    if len(bucket) >= _RATE_MAX_REQUESTS:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Too many bulk-ingest requests. Limit is {_RATE_MAX_REQUESTS} per {_RATE_WINDOW_S}s.",
        )
    bucket.append(now)
    _rate_state[actor_key] = bucket


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _dispatch_job(
    *,
    job_id: str,
    tenant_id: str,
    source_type: str,
    source_url: Optional[str],
    resource_types: list[str],
    local_file_path: Optional[str],
) -> None:
    """Hand the job off to Celery (heavy queue).  Falls back to inline
    execution only when Celery is unreachable so the local dev experience
    doesn't require a worker for one-off testing."""
    try:
        from app.services.bulk_ingest_task import task_run_bulk_ingest

        task_run_bulk_ingest.apply_async(
            kwargs={
                "job_id": job_id,
                "tenant_id": tenant_id,
                "source_type": source_type,
                "source_url": source_url,
                "resource_types": resource_types,
                "local_file_path": local_file_path,
            },
            queue="heavy",
        )
    except Exception as exc:  # noqa: BLE001
        # Fallback: run inline in a thread so the HTTP request returns
        # quickly.  This is intentionally lo-fi; production deployments must
        # have a Celery worker available.
        logger.warning(
            "bulk_ingest: Celery dispatch failed (%s); running inline as fallback",
            exc,
        )
        import threading

        threading.Thread(
            target=bulk_ingest_service.process_bulk_ingest_job,
            kwargs={
                "job_id": job_id,
                "tenant_id": tenant_id,
                "source_type": source_type,
                "source_url": source_url,
                "resource_types": resource_types,
                "local_file_path": local_file_path,
            },
            daemon=True,
        ).start()


def _serialise_job(row: dict[str, Any]) -> BulkIngestJobOut:
    return BulkIngestJobOut(
        id=row["id"],
        tenant_id=str(row["tenant_id"]),
        source_type=row["source_type"],
        source_url=row.get("source_url"),
        status=row["status"],
        total_resources=int(row.get("total_resources") or 0),
        ingested_resources=int(row.get("ingested_resources") or 0),
        errors_count=int(row.get("errors_count") or 0),
        patient_count=int(row.get("patient_count") or 0),
        condition_count=int(row.get("condition_count") or 0),
        encounter_count=int(row.get("encounter_count") or 0),
        observation_count=int(row.get("observation_count") or 0),
        started_at=row["started_at"].isoformat() if row.get("started_at") else None,
        completed_at=row["completed_at"].isoformat() if row.get("completed_at") else None,
        errors=row.get("errors") or [],
    )


# ---------------------------------------------------------------------------
# POST /start  — JSON body, kicks off async job
# ---------------------------------------------------------------------------

@router.post(
    "/start",
    response_model=BulkIngestStartOut,
    summary="Kick off a bulk FHIR ingest from a $export URL.",
)
def start_bulk_ingest(
    body: BulkIngestStartIn,
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
    _perm: dict = Depends(require_permission("patients", "write")),
) -> BulkIngestStartOut:
    _enforce_rate_limit(f"tenant:{tenant_id}")

    if body.source_type == "fhir_bulk_export" and not body.source_url:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="source_url is required when source_type=fhir_bulk_export",
        )
    if body.source_type == "ndjson_upload":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Use POST /api/bulk-ingest/upload for ndjson_upload",
        )

    job_id = f"bulk-{uuid.uuid4().hex[:16]}"
    bulk_ingest_service.create_job_row(
        job_id=job_id,
        tenant_id=tenant_id,
        source_url=body.source_url,
        source_type=body.source_type,
        resource_types=body.resource_types,
        submitted_by=int(current_user.get("id") or 0) or None,
    )
    _dispatch_job(
        job_id=job_id,
        tenant_id=tenant_id,
        source_type=body.source_type,
        source_url=body.source_url,
        resource_types=body.resource_types,
        local_file_path=None,
    )
    return BulkIngestStartOut(job_id=job_id, status="pending", source_type=body.source_type)


# ---------------------------------------------------------------------------
# POST /upload — multipart NDJSON upload (max 1 GB)
# ---------------------------------------------------------------------------

@router.post(
    "/upload",
    response_model=BulkIngestStartOut,
    summary="Upload an NDJSON file for one-shot bulk ingest.",
)
async def upload_ndjson(
    file: UploadFile = File(..., description="FHIR NDJSON file (max 1 GB)."),
    resource_types: Optional[str] = Form(
        default=None,
        description="JSON array of resource types to ingest. Default: all four.",
    ),
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
    _perm: dict = Depends(require_permission("patients", "write")),
) -> BulkIngestStartOut:
    _enforce_rate_limit(f"tenant:{tenant_id}")

    parsed_types: list[str] = list(_DEFAULT_RESOURCE_TYPES)
    if resource_types:
        try:
            parsed_types = json.loads(resource_types)
            if not isinstance(parsed_types, list) or not all(
                t in _ALLOWED_RESOURCE_TYPES for t in parsed_types
            ):
                raise ValueError
        except (ValueError, json.JSONDecodeError):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"resource_types must be a JSON array of {sorted(_ALLOWED_RESOURCE_TYPES)}",
            )

    # Stream the upload to a tempfile while enforcing the 1 GB cap.
    job_id = f"bulk-{uuid.uuid4().hex[:16]}"
    tmp_dir = tempfile.mkdtemp(prefix="raf_bulk_")
    tmp_path = os.path.join(tmp_dir, f"{job_id}.ndjson")

    total_bytes = 0
    try:
        with open(tmp_path, "wb") as out_fh:
            while True:
                chunk = await file.read(1024 * 1024)
                if not chunk:
                    break
                total_bytes += len(chunk)
                if total_bytes > MAX_UPLOAD_BYTES:
                    raise HTTPException(
                        status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                        detail=f"Upload exceeds {MAX_UPLOAD_BYTES // (1024 ** 3)} GB cap.",
                    )
                out_fh.write(chunk)
    except HTTPException:
        # Clean up partial upload on validation failure
        try:
            os.remove(tmp_path)
            os.rmdir(tmp_dir)
        except OSError:
            pass
        raise

    if total_bytes == 0:
        try:
            os.remove(tmp_path)
            os.rmdir(tmp_dir)
        except OSError:
            pass
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Uploaded file is empty.",
        )

    bulk_ingest_service.create_job_row(
        job_id=job_id,
        tenant_id=tenant_id,
        source_url=None,
        source_type="ndjson_upload",
        resource_types=parsed_types,
        submitted_by=int(current_user.get("id") or 0) or None,
    )
    _dispatch_job(
        job_id=job_id,
        tenant_id=tenant_id,
        source_type="ndjson_upload",
        source_url=None,
        resource_types=parsed_types,
        local_file_path=tmp_path,
    )
    return BulkIngestStartOut(job_id=job_id, status="pending", source_type="ndjson_upload")


# ---------------------------------------------------------------------------
# GET /jobs — recent jobs
# ---------------------------------------------------------------------------

@router.get(
    "/jobs",
    response_model=list[BulkIngestJobOut],
    summary="List recent bulk-ingest jobs for the caller's tenant.",
)
def list_jobs(
    limit: int = Query(default=50, ge=1, le=200),
    _user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
) -> list[BulkIngestJobOut]:
    rows = bulk_ingest_service.list_jobs(tenant_id, limit=limit)
    return [_serialise_job(r) for r in rows]


# ---------------------------------------------------------------------------
# GET /jobs/{id}
# ---------------------------------------------------------------------------

@router.get(
    "/jobs/{job_id}",
    response_model=BulkIngestJobOut,
    summary="Fetch a single bulk-ingest job (progress + errors).",
)
def get_job(
    job_id: str,
    _user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
) -> BulkIngestJobOut:
    row = bulk_ingest_service.fetch_job(job_id, tenant_id=tenant_id)
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="job not found")
    return _serialise_job(row)


# ---------------------------------------------------------------------------
# GET /jobs/{id}/stream — SSE
# ---------------------------------------------------------------------------

@router.get(
    "/jobs/{job_id}/stream",
    summary="SSE stream of progress events from the Redis pub/sub channel.",
    response_class=StreamingResponse,
)
async def stream_job(
    job_id: str,
    token: str = Query(..., description="JWT access token (browser EventSource cannot set headers)."),
) -> StreamingResponse:
    # Validate the JWT.  Reuse the same query-token helper as realtime.py.
    from app.routers.realtime import _resolve_token_param

    user = await _resolve_token_param(token)
    tenant_id = str(user.get("tenant_id"))

    # Confirm the caller owns the job.
    row = bulk_ingest_service.fetch_job(job_id, tenant_id=tenant_id)
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="job not found")

    async def _gen():
        # Send an initial snapshot so clients can render immediately even
        # before the next worker progress event lands on the channel.
        snapshot = bulk_ingest_service.fetch_job(job_id, tenant_id=tenant_id) or {}
        yield f"data: {json.dumps({'event': 'snapshot', 'job': _serialise_job(snapshot).model_dump()})}\n\n"

        client = bulk_ingest_service._get_redis()
        pubsub = client.pubsub()
        channel = PROGRESS_CHANNEL_FMT.format(job_id=job_id)
        try:
            pubsub.subscribe(channel)
            terminal_seen = snapshot.get("status") in {"completed", "failed"}
            while not terminal_seen:
                # Pull message with timeout so we can emit a heartbeat
                msg = await asyncio.to_thread(pubsub.get_message, ignore_subscribe_messages=True, timeout=20.0)
                if msg is None:
                    yield ": ping\n\n"
                    # Re-check job status — worker might have completed while we
                    # were idle and no new event will arrive.
                    refreshed = bulk_ingest_service.fetch_job(job_id, tenant_id=tenant_id)
                    if refreshed and refreshed.get("status") in {"completed", "failed"}:
                        yield f"data: {json.dumps({'event': refreshed['status'], 'job': _serialise_job(refreshed).model_dump()})}\n\n"
                        terminal_seen = True
                    continue
                data = msg.get("data")
                if data:
                    yield f"data: {data}\n\n"
                    try:
                        parsed = json.loads(data)
                        if parsed.get("event") in {"completed", "failed"}:
                            terminal_seen = True
                    except (TypeError, ValueError):
                        pass
        finally:
            try:
                pubsub.unsubscribe(channel)
                pubsub.close()
            except Exception:  # noqa: BLE001 — best-effort guard
                logger.debug("swallowed exception", exc_info=True)

    return StreamingResponse(
        _gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )
