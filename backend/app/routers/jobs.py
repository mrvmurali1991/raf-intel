"""
Job management router — async task queue status and control.

All heavy background operations (RAF batch calculation, document analysis,
FHIR sync, etc.) are dispatched as Celery tasks.  These endpoints let the
frontend poll for progress and let operators inspect or cancel work in flight.

Security
--------
- All list/get queries are **tenant-scoped** to the authenticated user's
  tenant.  Users cannot see jobs from other tenants.
- Dispatch endpoints require explicit ``jobs:write`` permission.
- ``tenant_id`` is derived from the JWT — callers cannot spoof it.
"""
# Removed: from __future__ import annotations (breaks FastAPI schema generation)

import logging
from datetime import datetime, timezone
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.auth import get_current_user, get_tenant_id, require_permission

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------


class JobSummary(BaseModel):
    id: str
    task_name: str
    status: str
    progress: int
    total: int
    tenant_id: int | None = None
    submitted_by: int | None = None
    error_message: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    created_at: datetime


class JobDetail(JobSummary):
    args_json: str | None = None
    result_json: str | None = None
    # Live Celery meta (progress messages) — None if backend unavailable
    celery_meta: dict[str, Any] | None = None


class JobStats(BaseModel):
    pending: int
    started: int
    progress: int
    success: int
    failure: int
    total: int
    # Per-task-name breakdown
    by_task: dict[str, int]


class DispatchResponse(BaseModel):
    job_id: str
    message: str


# ---------------------------------------------------------------------------
# Dispatch request models (tenant_id removed — derived from JWT)
# ---------------------------------------------------------------------------


class RafBatchRequest(BaseModel):
    patient_ids: list[int] = Field(..., min_length=1, max_length=5000)
    year: int = Field(..., ge=2024, le=2030)


class AnalyzeDocumentRequest(BaseModel):
    document_id: int


class ClaimsBatchRequest(BaseModel):
    batch_id: int


class FhirSyncRequest(BaseModel):
    connection_id: int
    sync_type: Literal["full", "incremental"] = "incremental"


class SubmissionRequest(BaseModel):
    payment_year: int = Field(..., ge=2024, le=2030)
    submission_type: Literal["RAPS", "EDPS"]
    sweep_type: Literal["initial", "mid_year", "final"] = "initial"


class SuspectScanRequest(BaseModel):
    year: int = Field(..., ge=2024, le=2030)


class ProviderScorecardsRequest(BaseModel):
    year: int = Field(..., ge=2024, le=2030)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _fetch_jobs(
    *,
    tenant_id: str,
    status: str | None = None,
    task_name: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[dict]:
    """Query raf_jobs with tenant isolation and optional filters."""
    from app.db import raf_cursor

    clauses: list[str] = ["tenant_id = %s"]
    params: list[Any] = [tenant_id]

    if status:
        clauses.append("status = %s")
        params.append(status)
    if task_name:
        clauses.append("task_name = %s")
        params.append(task_name)

    where = "WHERE " + " AND ".join(clauses)
    sql = f"""
        SELECT id, task_name, status, progress, total, tenant_id, submitted_by,
               args_json, result_json, error_message, started_at, finished_at, created_at
          FROM raf_jobs
         {where}
          ORDER BY created_at DESC
          LIMIT %s OFFSET %s
    """
    params.extend([limit, offset])

    with raf_cursor() as cur:
        cur.execute(sql, params)
        return cur.fetchall() or []


def _fetch_job(job_id: str, tenant_id: str) -> dict | None:
    """Fetch a single job row by ID, scoped to the user's tenant."""
    from app.db import raf_cursor

    with raf_cursor() as cur:
        cur.execute(
            """
            SELECT id, task_name, status, progress, total, tenant_id, submitted_by,
                   args_json, result_json, error_message, started_at, finished_at, created_at
              FROM raf_jobs
             WHERE id = %s AND tenant_id = %s
            """,
            (job_id, tenant_id),
        )
        row = cur.fetchone()
    return row


def _get_celery_meta(job_id: str) -> dict[str, Any] | None:
    """Pull live Celery task state from the result backend (best-effort)."""
    try:
        from app.services.job_service import celery_app

        result = celery_app.AsyncResult(job_id)
        state = result.state
        meta = result.info if isinstance(result.info, dict) else {}
        return {"state": state, **meta}
    except Exception:  # noqa: BLE001
        return None


def _submitter_id(current_user: dict) -> int | None:
    # get_current_user returns a dict with key "id", not "user_id"
    try:
        return int(current_user.get("id", 0)) or None
    except (TypeError, ValueError):
        return None


def _require_tenant_int(tenant_id: str) -> int:
    try:
        return int(tenant_id)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"Job dispatch requires a numeric tenant_id. Got: {tenant_id!r}",
        )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("", response_model=list[JobSummary], summary="List jobs")
def list_jobs(
    status: str | None = Query(None, description="Filter by status"),
    task_name: str | None = Query(None, description="Filter by task name"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
    _perm: None = Depends(require_permission("jobs", "read")),
) -> list[JobSummary]:
    """Return a paginated list of jobs for the authenticated user's tenant."""
    try:
        rows = _fetch_jobs(
            tenant_id=tenant_id,
            status=status,
            task_name=task_name,
            limit=limit,
            offset=offset,
        )
    except Exception as exc:
        logger.error("Failed to list jobs: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to query job list")

    return [JobSummary(**row) for row in rows]


@router.get("/stats", response_model=JobStats, summary="Job queue statistics")
def job_stats(
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
    _perm: None = Depends(require_permission("jobs", "read")),
) -> JobStats:
    """Return aggregate counts by status and per-task-name breakdown for the current tenant."""
    from app.db import raf_cursor

    try:
        with raf_cursor() as cur:
            # Status counts (tenant-scoped)
            cur.execute(
                "SELECT status, COUNT(*) AS cnt FROM raf_jobs WHERE tenant_id = %s GROUP BY status",
                (tenant_id,),
            )
            status_rows = cur.fetchall() or []

            # Per-task counts (last 24 h, tenant-scoped)
            cur.execute(
                """
                SELECT task_name, COUNT(*) AS cnt
                  FROM raf_jobs
                 WHERE tenant_id = %s AND created_at >= NOW() - INTERVAL 24 HOUR
                 GROUP BY task_name
                """,
                (tenant_id,),
            )
            task_rows = cur.fetchall() or []

    except Exception as exc:
        logger.error("Failed to compute job stats: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to query job statistics")

    status_counts: dict[str, int] = {r["status"]: r["cnt"] for r in status_rows}
    by_task: dict[str, int] = {r["task_name"]: r["cnt"] for r in task_rows}

    total = sum(status_counts.values())

    return JobStats(
        pending=status_counts.get("PENDING", 0),
        started=status_counts.get("STARTED", 0),
        progress=status_counts.get("PROGRESS", 0),
        success=status_counts.get("SUCCESS", 0),
        failure=status_counts.get("FAILURE", 0),
        total=total,
        by_task=by_task,
    )


@router.get("/{job_id}", response_model=JobDetail, summary="Get job detail")
def get_job(
    job_id: str,
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
    _perm: None = Depends(require_permission("jobs", "read")),
) -> JobDetail:
    """Return full detail for a single job, including live Celery progress meta."""
    row = _fetch_job(job_id, tenant_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")

    celery_meta = _get_celery_meta(job_id)
    return JobDetail(**row, celery_meta=celery_meta)


@router.post("/{job_id}/cancel", summary="Cancel a job")
def cancel_job(
    job_id: str,
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
    _perm: None = Depends(require_permission("jobs", "write")),
) -> dict[str, str]:
    """Request cancellation of a PENDING or running job.

    Sends Celery REVOKE with ``terminate=True`` (SIGTERM to the worker process
    handling this task) and marks the row FAILURE in the database.
    """
    row = _fetch_job(job_id, tenant_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")

    if row["status"] in ("SUCCESS", "FAILURE"):
        raise HTTPException(
            status_code=409,
            detail=f"Job is already in terminal state: {row['status']}",
        )

    try:
        from app.services.job_service import celery_app

        celery_app.control.revoke(job_id, terminate=True, signal="SIGTERM")
    except Exception as exc:  # noqa: BLE001
        logger.warning("Celery revoke failed for job %s: %s", job_id, exc)

    # Mark as FAILURE in DB regardless of whether Celery revoke succeeded
    try:
        from app.db import raf_cursor

        with raf_cursor() as cur:
            cur.execute(
                """
                UPDATE raf_jobs
                   SET status = 'FAILURE',
                       error_message = 'Cancelled by user',
                       finished_at = %s
                 WHERE id = %s
                """,
                (datetime.now(timezone.utc), job_id),
            )
    except Exception as exc:
        logger.error("Failed to mark job %s cancelled: %s", job_id, exc)
        raise HTTPException(status_code=500, detail="Failed to update job status")

    logger.info("Job %s cancelled by user %s", job_id, current_user.get("id"))
    return {"job_id": job_id, "status": "cancellation_requested"}


# ---------------------------------------------------------------------------
# Dispatch endpoints
# ---------------------------------------------------------------------------


@router.post(
    "/dispatch/raf-batch",
    response_model=DispatchResponse,
    summary="Dispatch RAF batch calculation",
)
def dispatch_raf_batch(
    body: RafBatchRequest,
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
    _perm: None = Depends(require_permission("jobs", "write")),
) -> DispatchResponse:
    """Enqueue a RAF score calculation for a list of patients."""
    from app.services.job_service import dispatch_calculate_raf_batch

    job_id = dispatch_calculate_raf_batch(
        patient_ids=body.patient_ids,
        year=body.year,
        tenant_id=_require_tenant_int(tenant_id),
        submitted_by=_submitter_id(current_user),
    )
    logger.info(
        "Dispatched raf.calculate_batch job=%s patients=%d",
        job_id,
        len(body.patient_ids),
    )
    return DispatchResponse(
        job_id=job_id,
        message=f"RAF batch calculation queued for {len(body.patient_ids)} patients (year {body.year})",
    )


@router.post(
    "/dispatch/analyze-document",
    response_model=DispatchResponse,
    summary="Dispatch document analysis",
)
def dispatch_analyze_document(
    body: AnalyzeDocumentRequest,
    current_user: dict = Depends(get_current_user),
    _perm: None = Depends(require_permission("jobs", "write")),
) -> DispatchResponse:
    """Enqueue Gemini Vision analysis for a stored document."""
    from app.services.job_service import dispatch_analyze_document as _dispatch

    job_id = _dispatch(
        document_id=body.document_id,
        submitted_by=_submitter_id(current_user),
    )
    logger.info(
        "Dispatched raf.analyze_document job=%s doc=%d", job_id, body.document_id
    )
    return DispatchResponse(
        job_id=job_id,
        message=f"Document analysis queued for document {body.document_id}",
    )


@router.post(
    "/dispatch/claims-batch",
    response_model=DispatchResponse,
    summary="Dispatch claims batch processing",
)
def dispatch_claims_batch(
    body: ClaimsBatchRequest,
    current_user: dict = Depends(get_current_user),
    _perm: None = Depends(require_permission("jobs", "write")),
) -> DispatchResponse:
    """Enqueue patient matching and HCC mapping for a claims batch."""
    from app.services.job_service import dispatch_process_claims_batch

    job_id = dispatch_process_claims_batch(
        batch_id=body.batch_id,
        submitted_by=_submitter_id(current_user),
    )
    logger.info(
        "Dispatched raf.process_claims_batch job=%s batch=%d", job_id, body.batch_id
    )
    return DispatchResponse(
        job_id=job_id,
        message=f"Claims batch {body.batch_id} processing queued",
    )


@router.post(
    "/dispatch/fhir-sync", response_model=DispatchResponse, summary="Dispatch FHIR sync"
)
def dispatch_fhir_sync(
    body: FhirSyncRequest,
    current_user: dict = Depends(get_current_user),
    _perm: None = Depends(require_permission("jobs", "write")),
) -> DispatchResponse:
    """Enqueue a FHIR sync for a configured connection."""
    from app.services.job_service import dispatch_sync_fhir

    job_id = dispatch_sync_fhir(
        connection_id=body.connection_id,
        sync_type=body.sync_type,
        submitted_by=_submitter_id(current_user),
    )
    logger.info(
        "Dispatched raf.sync_fhir job=%s conn=%d type=%s",
        job_id,
        body.connection_id,
        body.sync_type,
    )
    return DispatchResponse(
        job_id=job_id,
        message=f"FHIR {body.sync_type} sync queued for connection {body.connection_id}",
    )


@router.post(
    "/dispatch/submission",
    response_model=DispatchResponse,
    summary="Dispatch submission file generation",
)
def dispatch_submission(
    body: SubmissionRequest,
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
    _perm: None = Depends(require_permission("jobs", "write")),
) -> DispatchResponse:
    """Enqueue RAPS or EDPS submission file generation."""
    from app.services.job_service import dispatch_generate_submission

    job_id = dispatch_generate_submission(
        tenant_id=_require_tenant_int(tenant_id),
        payment_year=body.payment_year,
        submission_type=body.submission_type,
        sweep_type=body.sweep_type,
        submitted_by=_submitter_id(current_user),
    )
    logger.info(
        "Dispatched raf.generate_submission job=%s type=%s year=%d",
        job_id,
        body.submission_type,
        body.payment_year,
    )
    return DispatchResponse(
        job_id=job_id,
        message=(
            f"{body.submission_type} {body.sweep_type} submission generation queued "
            f"for year {body.payment_year}"
        ),
    )


@router.post(
    "/dispatch/suspects-scan",
    response_model=DispatchResponse,
    summary="Dispatch full suspect scan",
)
def dispatch_suspects_scan(
    body: SuspectScanRequest,
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
    _perm: None = Depends(require_permission("jobs", "write")),
) -> DispatchResponse:
    """Enqueue a suspect condition scan for all active patients."""
    from app.services.job_service import dispatch_scan_suspects_all

    job_id = dispatch_scan_suspects_all(
        tenant_id=_require_tenant_int(tenant_id),
        year=body.year,
        submitted_by=_submitter_id(current_user),
    )
    logger.info(
        "Dispatched raf.scan_suspects_all job=%s tenant=%s year=%d",
        job_id,
        tenant_id,
        body.year,
    )
    return DispatchResponse(
        job_id=job_id,
        message=f"Suspect scan queued for year {body.year}",
    )


@router.post(
    "/dispatch/provider-scorecards",
    response_model=DispatchResponse,
    summary="Dispatch provider scorecard refresh",
)
def dispatch_provider_scorecards(
    body: ProviderScorecardsRequest,
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
    _perm: None = Depends(require_permission("jobs", "write")),
) -> DispatchResponse:
    """Enqueue a provider scorecard refresh for all providers in a tenant."""
    from app.services.job_service import dispatch_calculate_provider_scorecards

    job_id = dispatch_calculate_provider_scorecards(
        tenant_id=_require_tenant_int(tenant_id),
        year=body.year,
        submitted_by=_submitter_id(current_user),
    )
    logger.info(
        "Dispatched raf.calculate_provider_scorecards job=%s tenant=%s year=%d",
        job_id,
        tenant_id,
        body.year,
    )
    return DispatchResponse(
        job_id=job_id,
        message=f"Provider scorecard refresh queued for year {body.year}",
    )
