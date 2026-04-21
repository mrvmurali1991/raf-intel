"""
Celery-based async job processing service for RAF Intelligence.

Broker and result backend are both Redis (REDIS_URL in .env).

Worker startup:
    celery -A app.services.job_service worker \\
        --loglevel=info --concurrency=4 -Q default

Beat scheduler (if periodic tasks are needed):
    celery -A app.services.job_service beat --loglevel=info

Each task:
  - Persists status / progress to the ``raf_jobs`` table in raf_intelligence DB.
  - Reports fine-grained progress via Celery's update_state so callers can
    poll GET /api/jobs/{id} for live feedback.
  - Retries up to 3 times on transient failures with exponential back-off.
  - Writes an audit trail row via audit_logger on completion or failure.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

from celery import Celery
from celery.utils.log import get_task_logger

from app.config import settings

logger = logging.getLogger(__name__)
task_logger = get_task_logger(__name__)

# ---------------------------------------------------------------------------
# Celery application
# ---------------------------------------------------------------------------

celery_app = Celery(
    "raf_intelligence",
    broker=settings.redis_url,
    backend=settings.redis_url,
)

celery_app.conf.update(
    # Serialization
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    # Timezone
    timezone="UTC",
    enable_utc=True,
    # Observability
    task_track_started=True,
    task_send_sent_event=True,
    # Limits — individual tasks that run longer than 1 hour are killed.
    task_time_limit=3600,  # hard kill after 60 min
    task_soft_time_limit=3000,  # SoftTimeLimitExceeded at 50 min
    # Worker health — restart each worker child after 50 tasks to prevent
    # memory bloat from long-lived Python processes.
    worker_max_tasks_per_child=50,
    # Fair scheduling — each worker only fetches one task at a time so
    # slow tasks don't starve fast ones on a shared queue.
    worker_prefetch_multiplier=1,
    # Result expiry — keep results 24 hours.
    result_expires=86400,
    # Queues
    task_default_queue="default",
    task_queues={
        "default": {"exchange": "default", "routing_key": "default"},
        "heavy": {"exchange": "heavy", "routing_key": "heavy"},
    },
)

# ---------------------------------------------------------------------------
# Database helpers (synchronous — Celery workers are not async)
# ---------------------------------------------------------------------------


def _db_execute(sql: str, params: tuple = (), *, fetchone: bool = False) -> Any:
    """Execute a single SQL statement against the RAF Intelligence DB."""
    from app.db import raf_cursor

    with raf_cursor() as cur:
        cur.execute(sql, params)
        if fetchone:
            return cur.fetchone()
    return None


def _ensure_jobs_table() -> None:
    """No-op — tables are managed by the centralized migration runner."""
    pass


def _upsert_job(
    job_id: str,
    *,
    task_name: str = "",
    status: str = "PENDING",
    progress: int = 0,
    total: int = 0,
    tenant_id: int | None = None,
    submitted_by: int | None = None,
    args_json: str | None = None,
    result_json: str | None = None,
    error_message: str | None = None,
    started_at: datetime | None = None,
    finished_at: datetime | None = None,
) -> None:
    """Insert or update a job row in raf_jobs."""
    from app.db import raf_cursor

    with raf_cursor() as cur:
        cur.execute(
            """
            INSERT INTO raf_jobs
                (id, task_name, status, progress, total, tenant_id, submitted_by,
                 args_json, result_json, error_message, started_at, finished_at,
                 submitted_at)
            VALUES
                (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
            ON DUPLICATE KEY UPDATE
                status        = VALUES(status),
                progress      = VALUES(progress),
                total         = VALUES(total),
                result_json   = COALESCE(VALUES(result_json),   result_json),
                error_message = COALESCE(VALUES(error_message), error_message),
                started_at    = COALESCE(VALUES(started_at),    started_at),
                finished_at   = COALESCE(VALUES(finished_at),   finished_at),
                submitted_at  = COALESCE(submitted_at,          VALUES(submitted_at))
            """,
            (
                job_id,
                task_name,
                status,
                progress,
                total,
                tenant_id,
                submitted_by,
                args_json,
                result_json,
                error_message,
                started_at,
                finished_at,
            ),
        )


def _get_job(job_id: str) -> dict[str, Any] | None:
    """Fetch a single job row from raf_jobs. Returns None if not found."""
    from app.db import raf_cursor

    with raf_cursor() as cur:
        cur.execute(
            """
            SELECT id, task_name, status, progress, total, tenant_id,
                   submitted_by, args_json, result_json, error_message,
                   started_at, finished_at, created_at, submitted_at
            FROM raf_jobs WHERE id = %s
            """,
            (job_id,),
        )
        row = cur.fetchone()
    if not row:
        return None
    result = dict(row)
    # Serialize datetimes
    for key in ("started_at", "finished_at", "created_at", "submitted_at"):
        if isinstance(result.get(key), datetime):
            result[key] = result[key].isoformat()
    # Parse JSON fields
    for key in ("args_json", "result_json"):
        if isinstance(result.get(key), str):
            try:
                result[key] = json.loads(result[key])
            except Exception:
                pass
    return result


def recover_stale_jobs(stale_after_hours: int = 1) -> int:
    """Mark jobs left in QUEUED/RUNNING state as FAILED after a server restart.

    FastAPI BackgroundTasks are in-process and lost on restart, which strands
    rows in the ``raf_jobs`` table as zombies. This helper is called once from
    the FastAPI lifespan startup hook. A time threshold avoids racing with
    in-flight jobs from another worker/container.

    Args:
        stale_after_hours: Only mark rows whose ``submitted_at`` is older than
            this many hours.

    Returns:
        The number of rows updated.
    """
    from app.db import raf_cursor

    try:
        with raf_cursor() as cur:
            cur.execute(
                """
                UPDATE raf_jobs
                   SET status = 'FAILED',
                       error_message = 'Interrupted by server restart',
                       finished_at = NOW()
                 WHERE status IN ('QUEUED', 'RUNNING', 'PENDING', 'STARTED', 'PROGRESS')
                   AND submitted_at < NOW() - INTERVAL %s HOUR
                """,
                (stale_after_hours,),
            )
            return cur.rowcount or 0
    except Exception as exc:  # noqa: BLE001
        msg = str(exc)
        if "Unknown column" in msg and "submitted_at" in msg:
            logger.warning(
                "recover_stale_jobs skipped: raf_jobs.submitted_at column missing "
                "(run migrations to enable restart recovery)"
            )
            return 0
        raise


def _mark_started(task_self: Any, task_name: str, args_dict: dict) -> None:
    """Persist STARTED status and record the wall-clock start time."""
    _upsert_job(
        task_self.request.id,
        task_name=task_name,
        status="STARTED",
        args_json=json.dumps(args_dict),
        started_at=datetime.now(timezone.utc),
    )


def _mark_progress(task_self: Any, current: int, total: int, message: str = "") -> None:
    """Push progress to Celery result backend and update DB row."""
    meta = {"current": current, "total": total, "message": message}
    task_self.update_state(state="PROGRESS", meta=meta)
    from app.db import raf_cursor

    with raf_cursor() as cur:
        cur.execute(
            "UPDATE raf_jobs SET status='PROGRESS', progress=%s, total=%s WHERE id=%s",
            (current, total, task_self.request.id),
        )


def _mark_success(task_self: Any, result: dict) -> None:
    """Persist SUCCESS status with serialised result."""
    _upsert_job(
        task_self.request.id,
        status="SUCCESS",
        progress=100,
        result_json=json.dumps(result),
        finished_at=datetime.now(timezone.utc),
    )


def _mark_failure(task_self: Any, exc: Exception) -> None:
    """Persist FAILURE status with error message."""
    _upsert_job(
        task_self.request.id,
        status="FAILURE",
        error_message=str(exc)[:2000],
        finished_at=datetime.now(timezone.utc),
    )


def _audit(action: str, job_id: str, detail: str = "") -> None:
    """Best-effort audit log — never raises."""
    try:
        from app.services.audit_logger import log_phi_access

        log_phi_access(
            user_id=None,
            action=action,
            resource_type="job",
            resource_id=str(job_id),
            detail=detail,
        )
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Signal: ensure table exists when workers come online
# ---------------------------------------------------------------------------

from celery.signals import worker_ready  # noqa: E402


@worker_ready.connect
def on_worker_ready(**_kwargs):
    """Create raf_jobs table on first worker startup."""
    try:
        _ensure_jobs_table()
        logger.info("raf_jobs table verified / created.")
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not verify raf_jobs table: %s", exc)


# ---------------------------------------------------------------------------
# Task: calculate RAF for a batch of patients
# ---------------------------------------------------------------------------


@celery_app.task(
    bind=True,
    name="raf.calculate_batch",
    queue="heavy",
    max_retries=3,
    default_retry_delay=60,
)
def task_calculate_raf_batch(
    self,
    patient_ids: list[int],
    year: int,
    tenant_id: int | None = None,
) -> dict[str, Any]:
    """Calculate RAF scores for a list of patient IDs.

    Args:
        patient_ids: List of OpenEMR patient IDs.
        year:        Payment year (2024, 2025, 2026…).
        tenant_id:   Optional tenant identifier for multi-tenant deployments.

    Returns:
        Dict with ``processed``, ``failed``, and ``results`` keys.
    """
    job_id = self.request.id
    _mark_started(
        self,
        "raf.calculate_batch",
        {"patient_ids": patient_ids, "year": year, "tenant_id": tenant_id},
    )
    _audit(
        "job_started",
        job_id,
        f"calculate_batch year={year} patients={len(patient_ids)}",
    )

    results: list[dict] = []
    failed: list[dict] = []
    total = len(patient_ids)

    try:
        from app.services.raf_calculator import calculate_raf_score

        for i, pid in enumerate(patient_ids, start=1):
            try:
                score = calculate_raf_score(pid, year, tenant_id=tenant_id)
                results.append({"patient_id": pid, "raf_score": score})
            except Exception as exc:  # noqa: BLE001
                task_logger.warning(
                    "RAF calculation failed for patient %s: %s", pid, exc
                )
                failed.append({"patient_id": pid, "error": str(exc)})

            if i % 10 == 0 or i == total:
                _mark_progress(self, i, total, f"Processed {i}/{total} patients")

        outcome = {
            "processed": len(results),
            "failed": len(failed),
            "results": results,
            "errors": failed,
        }
        _mark_success(self, outcome)
        _audit(
            "job_completed",
            job_id,
            f"calculate_batch processed={len(results)} failed={len(failed)}",
        )
        return outcome

    except Exception as exc:
        _mark_failure(self, exc)
        _audit("job_failed", job_id, str(exc)[:500])
        raise self.retry(exc=exc, countdown=60 * (self.request.retries + 1))


# ---------------------------------------------------------------------------
# Task: analyze a document with Gemini Vision
# ---------------------------------------------------------------------------


@celery_app.task(
    bind=True,
    name="raf.analyze_document",
    queue="heavy",
    max_retries=2,
    default_retry_delay=30,
)
def task_analyze_document(self, document_id: int) -> dict[str, Any]:
    """Run Gemini Vision NLP analysis on a stored document.

    Args:
        document_id: Row ID from the ``raf_documents`` table.

    Returns:
        Dict containing extracted ICD codes, HCC mappings, and confidence scores.
    """
    job_id = self.request.id
    _mark_started(self, "raf.analyze_document", {"document_id": document_id})
    _audit("job_started", job_id, f"analyze_document id={document_id}")

    try:
        _mark_progress(self, 1, 4, "Loading document")
        from app.services.document_service import analyze_document

        _mark_progress(self, 2, 4, "Running Gemini Vision analysis")
        result = analyze_document(str(document_id))

        _mark_progress(self, 4, 4, "Complete")
        outcome = {
            "document_id": document_id,
            "icd_codes": result.get("icd_codes", []),
            "hccs": result.get("hcc_codes", []),
        }
        _mark_success(self, outcome)
        _audit(
            "job_completed",
            job_id,
            f"analyze_document id={document_id} codes={len(outcome['icd_codes'])}",
        )
        return outcome

    except Exception as exc:
        _mark_failure(self, exc)
        _audit("job_failed", job_id, str(exc)[:500])
        raise self.retry(exc=exc, countdown=30 * (self.request.retries + 1))


# ---------------------------------------------------------------------------
# Task: process a claims batch
# ---------------------------------------------------------------------------


@celery_app.task(
    bind=True,
    name="raf.process_claims_batch",
    queue="heavy",
    max_retries=3,
    default_retry_delay=60,
)
def task_process_claims_batch(self, batch_id: int) -> dict[str, Any]:
    """Process a claims batch: patient matching, HCC mapping, and persistence.

    Args:
        batch_id: Row ID in the ``raf_claims_batches`` table.

    Returns:
        Dict with match statistics and HCC mapping counts.
    """
    job_id = self.request.id
    _mark_started(self, "raf.process_claims_batch", {"batch_id": batch_id})
    _audit("job_started", job_id, f"process_claims_batch id={batch_id}")

    try:
        _mark_progress(self, 0, 3, "Loading batch")
        from app.services.claims_service import (
            get_batch,
            map_hcc_codes_for_batch,
            match_patients_to_openemr,
            process_batch,
        )

        batch = get_batch(batch_id)
        if batch is None:
            raise ValueError(f"Claims batch {batch_id} not found")
        total_claims = batch.get("record_count", 0)

        _mark_progress(self, 1, 3, f"Matching {total_claims} claims to patients")
        match_result = match_patients_to_openemr(batch_id)

        _mark_progress(self, 2, 3, "Mapping HCC codes")
        hcc_result = map_hcc_codes_for_batch(batch_id)

        _mark_progress(self, 3, 3, "Processing batch")
        process_result = process_batch(batch_id)

        outcome = {
            "batch_id": batch_id,
            "total_claims": total_claims,
            "matched": match_result.get("matched", 0),
            "hcc_mappings": hcc_result.get("mapped_count", 0),
            "processed": process_result.get("processed", 0),
        }
        _mark_success(self, outcome)
        _audit(
            "job_completed",
            job_id,
            f"process_claims_batch id={batch_id} matched={match_result.get('matched', 0)}",
        )
        return outcome

    except Exception as exc:
        _mark_failure(self, exc)
        _audit("job_failed", job_id, str(exc)[:500])
        raise self.retry(exc=exc, countdown=60 * (self.request.retries + 1))


# ---------------------------------------------------------------------------
# Task: FHIR sync
# ---------------------------------------------------------------------------


@celery_app.task(
    bind=True,
    name="raf.sync_fhir",
    queue="default",
    max_retries=3,
    default_retry_delay=120,
)
def task_sync_fhir(
    self,
    connection_id: int,
    sync_type: str = "incremental",
) -> dict[str, Any]:
    """Run a FHIR sync for a configured connection.

    Args:
        connection_id: Row ID in ``fhir_connections``.
        sync_type:     ``"full"`` or ``"incremental"``.

    Returns:
        Dict with resources synced, errors, and timing.
    """
    job_id = self.request.id
    _mark_started(
        self, "raf.sync_fhir", {"connection_id": connection_id, "sync_type": sync_type}
    )
    _audit(
        "job_started", job_id, f"sync_fhir connection={connection_id} type={sync_type}"
    )

    try:
        from app.services.fhir_service import run_sync

        _mark_progress(
            self, 0, 1, f"Running {sync_type} FHIR sync for connection {connection_id}"
        )
        stats = run_sync(connection_id=connection_id, sync_type=sync_type)

        _mark_progress(self, 1, 1, "Sync complete")
        outcome = {
            "connection_id": connection_id,
            "sync_type": sync_type,
            "resources_synced": stats.get("synced", 0),
            "errors": stats.get("errors", 0),
        }
        _mark_success(self, outcome)
        _audit(
            "job_completed", job_id, f"sync_fhir synced={outcome['resources_synced']}"
        )
        return outcome

    except Exception as exc:
        _mark_failure(self, exc)
        _audit("job_failed", job_id, str(exc)[:500])
        # Exponential back-off: 2min, 4min, 8min
        raise self.retry(exc=exc, countdown=120 * (2**self.request.retries))


# ---------------------------------------------------------------------------
# Task: generate RAPS / EDPS submission file
# ---------------------------------------------------------------------------


@celery_app.task(
    bind=True,
    name="raf.generate_submission",
    queue="heavy",
    max_retries=2,
    default_retry_delay=60,
)
def task_generate_submission(
    self,
    tenant_id: int,
    payment_year: int,
    submission_type: str,
    sweep_type: str = "initial",
) -> dict[str, Any]:
    """Generate a RAPS or EDPS submission file.

    Args:
        tenant_id:       Tenant for which the file is generated.
        payment_year:    CMS payment year.
        submission_type: ``"RAPS"`` or ``"EDPS"``.
        sweep_type:      ``"initial"``, ``"mid_year"``, or ``"final"``.

    Returns:
        Dict with file path, record count, and validation warnings.
    """
    job_id = self.request.id
    _mark_started(
        self,
        "raf.generate_submission",
        {
            "tenant_id": tenant_id,
            "payment_year": payment_year,
            "submission_type": submission_type,
            "sweep_type": sweep_type,
        },
    )
    _audit(
        "job_started",
        job_id,
        f"generate_submission type={submission_type} year={payment_year}",
    )

    try:
        _mark_progress(self, 0, 3, "Generating submission file")
        if submission_type.upper() == "RAPS":
            from app.services.submission_service import generate_raps_file

            file_result = generate_raps_file(str(tenant_id), payment_year, sweep_type)
        else:
            from app.services.submission_service import generate_edps_file

            file_result = generate_edps_file(str(tenant_id), payment_year, sweep_type)

        total = file_result.get("record_count", 0)
        file_path = file_result.get("file_path", "")
        batch_id = file_result.get("batch_id", "")

        _mark_progress(self, 2, 3, "Validating submission file")
        from app.services.submission_service import validate_submission

        validation = validate_submission(batch_id)

        _mark_progress(self, 3, 3, "Complete")
        outcome = {
            "file_path": file_path,
            "batch_id": batch_id,
            "record_count": total,
            "submission_type": submission_type,
            "payment_year": payment_year,
            "sweep_type": sweep_type,
            "validation_warnings": file_result.get("warnings", []),
            "validation_errors": validation.get("errors", []),
        }
        _mark_success(self, outcome)
        _audit(
            "job_completed",
            job_id,
            f"generate_submission file={file_path} records={total}",
        )
        return outcome

    except Exception as exc:
        _mark_failure(self, exc)
        _audit("job_failed", job_id, str(exc)[:500])
        raise self.retry(exc=exc, countdown=60 * (self.request.retries + 1))


# ---------------------------------------------------------------------------
# Task: suspect scan for all patients
# ---------------------------------------------------------------------------


@celery_app.task(
    bind=True,
    name="raf.scan_suspects_all",
    queue="heavy",
    max_retries=2,
    default_retry_delay=120,
)
def task_scan_suspects_all(self, tenant_id: int, year: int) -> dict[str, Any]:
    """Run the suspect condition scan across all active patients for a tenant.

    Args:
        tenant_id: Tenant identifier.
        year:      Payment year to scope the scan.

    Returns:
        Dict with patient count, total suspects found, and high-confidence count.
    """
    job_id = self.request.id
    _mark_started(self, "raf.scan_suspects_all", {"tenant_id": tenant_id, "year": year})
    _audit("job_started", job_id, f"scan_suspects_all tenant={tenant_id} year={year}")

    try:
        # Fetch all active patient IDs for this tenant
        from app.db import openemr_cursor

        with openemr_cursor() as cur:
            cur.execute(
                "SELECT pid FROM patient_data WHERE inactive != 1 ORDER BY pid",
            )
            rows = cur.fetchall()

        patient_ids = [r["pid"] for r in rows] if rows else []
        total = len(patient_ids)
        suspects_found = 0
        high_confidence = 0

        from app.services.suspect_engine import run_full_suspect_scan

        for i, pid in enumerate(patient_ids, start=1):
            try:
                suspects = run_full_suspect_scan(pid, tenant_id=str(tenant_id))
                suspects_found += len(suspects)
                high_confidence += sum(
                    1 for s in suspects if s.get("confidence", 0) >= 0.8
                )
            except Exception as exc:  # noqa: BLE001
                task_logger.warning("Suspect scan failed for patient %s: %s", pid, exc)

            if i % 25 == 0 or i == total:
                _mark_progress(
                    self,
                    i,
                    total,
                    f"Scanned {i}/{total} patients — {suspects_found} suspects found",
                )

        outcome = {
            "tenant_id": tenant_id,
            "year": year,
            "patients_scanned": total,
            "suspects_found": suspects_found,
            "high_confidence_suspects": high_confidence,
        }
        _mark_success(self, outcome)
        _audit("job_completed", job_id, f"scan_suspects_all suspects={suspects_found}")
        return outcome

    except Exception as exc:
        _mark_failure(self, exc)
        _audit("job_failed", job_id, str(exc)[:500])
        raise self.retry(exc=exc, countdown=120 * (self.request.retries + 1))


# ---------------------------------------------------------------------------
# Task: provider scorecard refresh
# ---------------------------------------------------------------------------


@celery_app.task(
    bind=True,
    name="raf.calculate_provider_scorecards",
    queue="heavy",
    max_retries=2,
    default_retry_delay=60,
)
def task_calculate_provider_scorecards(
    self, tenant_id: int, year: int
) -> dict[str, Any]:
    """Refresh all provider RAF scorecards for a tenant and payment year.

    Args:
        tenant_id: Tenant identifier.
        year:      Payment year.

    Returns:
        Dict with provider count and aggregate scorecard statistics.
    """
    job_id = self.request.id
    _mark_started(
        self,
        "raf.calculate_provider_scorecards",
        {"tenant_id": tenant_id, "year": year},
    )
    _audit(
        "job_started",
        job_id,
        f"calculate_provider_scorecards tenant={tenant_id} year={year}",
    )

    try:
        from app.services.provider_service import (
            calculate_provider_scorecard,
            list_providers,
        )

        providers = list_providers(tenant_id=tenant_id)
        total = len(providers)
        processed = 0
        errors = 0

        for i, provider in enumerate(providers, start=1):
            try:
                calculate_provider_scorecard(provider["id"], year, tenant_id=tenant_id)
                processed += 1
            except Exception as exc:  # noqa: BLE001
                task_logger.warning(
                    "Scorecard failed for provider %s: %s", provider.get("id"), exc
                )
                errors += 1

            if i % 5 == 0 or i == total:
                _mark_progress(
                    self, i, total, f"Refreshed {processed}/{total} scorecards"
                )

        outcome = {
            "tenant_id": tenant_id,
            "year": year,
            "providers_processed": processed,
            "errors": errors,
        }
        _mark_success(self, outcome)
        _audit(
            "job_completed",
            job_id,
            f"calculate_provider_scorecards processed={processed}",
        )
        return outcome

    except Exception as exc:
        _mark_failure(self, exc)
        _audit("job_failed", job_id, str(exc)[:500])
        raise self.retry(exc=exc, countdown=60 * (self.request.retries + 1))


# ---------------------------------------------------------------------------
# Public dispatch helpers — used by routers to enqueue tasks
# ---------------------------------------------------------------------------


def dispatch_calculate_raf_batch(
    patient_ids: list[int],
    year: int,
    tenant_id: int | None = None,
    submitted_by: int | None = None,
) -> str:
    """Enqueue a RAF batch calculation and register the job row.

    Returns the Celery task ID (job_id) for status polling.
    """
    task = task_calculate_raf_batch.apply_async(
        kwargs={"patient_ids": patient_ids, "year": year, "tenant_id": tenant_id},
        queue="heavy",
    )
    _upsert_job(
        task.id,
        task_name="raf.calculate_batch",
        status="PENDING",
        total=len(patient_ids),
        tenant_id=tenant_id,
        submitted_by=submitted_by,
        args_json=json.dumps({"patient_ids": patient_ids, "year": year}),
    )
    return task.id


def dispatch_analyze_document(document_id: int, submitted_by: int | None = None) -> str:
    """Enqueue a document analysis job. Returns task ID."""
    task = task_analyze_document.apply_async(
        kwargs={"document_id": document_id},
        queue="heavy",
    )
    _upsert_job(
        task.id,
        task_name="raf.analyze_document",
        status="PENDING",
        total=4,
        submitted_by=submitted_by,
        args_json=json.dumps({"document_id": document_id}),
    )
    return task.id


def dispatch_process_claims_batch(
    batch_id: int, submitted_by: int | None = None
) -> str:
    """Enqueue a claims batch processing job. Returns task ID."""
    task = task_process_claims_batch.apply_async(
        kwargs={"batch_id": batch_id},
        queue="heavy",
    )
    _upsert_job(
        task.id,
        task_name="raf.process_claims_batch",
        status="PENDING",
        total=3,
        submitted_by=submitted_by,
        args_json=json.dumps({"batch_id": batch_id}),
    )
    return task.id


def dispatch_sync_fhir(
    connection_id: int,
    sync_type: str = "incremental",
    submitted_by: int | None = None,
) -> str:
    """Enqueue a FHIR sync job. Returns task ID."""
    task = task_sync_fhir.apply_async(
        kwargs={"connection_id": connection_id, "sync_type": sync_type},
        queue="default",
    )
    _upsert_job(
        task.id,
        task_name="raf.sync_fhir",
        status="PENDING",
        total=1,
        submitted_by=submitted_by,
        args_json=json.dumps({"connection_id": connection_id, "sync_type": sync_type}),
    )
    return task.id


def dispatch_generate_submission(
    tenant_id: int,
    payment_year: int,
    submission_type: str,
    sweep_type: str = "initial",
    submitted_by: int | None = None,
) -> str:
    """Enqueue a submission file generation job. Returns task ID."""
    task = task_generate_submission.apply_async(
        kwargs={
            "tenant_id": tenant_id,
            "payment_year": payment_year,
            "submission_type": submission_type,
            "sweep_type": sweep_type,
        },
        queue="heavy",
    )
    _upsert_job(
        task.id,
        task_name="raf.generate_submission",
        status="PENDING",
        total=3,
        tenant_id=tenant_id,
        submitted_by=submitted_by,
        args_json=json.dumps(
            {
                "tenant_id": tenant_id,
                "payment_year": payment_year,
                "submission_type": submission_type,
                "sweep_type": sweep_type,
            }
        ),
    )
    return task.id


def dispatch_scan_suspects_all(
    tenant_id: int,
    year: int,
    submitted_by: int | None = None,
) -> str:
    """Enqueue a full suspect scan job. Returns task ID."""
    task = task_scan_suspects_all.apply_async(
        kwargs={"tenant_id": tenant_id, "year": year},
        queue="heavy",
    )
    _upsert_job(
        task.id,
        task_name="raf.scan_suspects_all",
        status="PENDING",
        tenant_id=tenant_id,
        submitted_by=submitted_by,
        args_json=json.dumps({"tenant_id": tenant_id, "year": year}),
    )
    return task.id


def dispatch_calculate_provider_scorecards(
    tenant_id: int,
    year: int,
    submitted_by: int | None = None,
) -> str:
    """Enqueue a provider scorecard refresh job. Returns task ID."""
    task = task_calculate_provider_scorecards.apply_async(
        kwargs={"tenant_id": tenant_id, "year": year},
        queue="heavy",
    )
    _upsert_job(
        task.id,
        task_name="raf.calculate_provider_scorecards",
        status="PENDING",
        tenant_id=tenant_id,
        submitted_by=submitted_by,
        args_json=json.dumps({"tenant_id": tenant_id, "year": year}),
    )
    return task.id
