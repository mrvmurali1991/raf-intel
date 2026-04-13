"""
Celery tasks for RAF Intelligence background work.

This module re-exports the Celery app from job_service and defines additional
periodic/operational tasks that replace the daemon-thread sync scheduler.

Worker startup
--------------
    # Process all queues (default + heavy)
    celery -A app.services.celery_tasks worker --loglevel=info --concurrency=4 -Q default,heavy

Beat scheduler (periodic tasks)
--------------------------------
    celery -A app.services.celery_tasks beat --loglevel=info

Both commands must be run from the ``backend/`` directory so that the
``app`` package is importable.

Task inventory
--------------
    raf.sync_emr_connection       — per-connection EMR sync (replaces daemon thread)
    raf.check_due_syncs           — Beat entry: queries DB and fans out sync tasks
    raf.retention_sweep           — Beat entry: HIPAA data-retention sweep
    raf.normalize_encounters      — encounter normalisation for a tenant
    raf.analyze_encounters_batch  — batch AI analysis of clinical encounters
    raf.calculate_raf_batch       — (re-exported from job_service)
    raf.generate_submission       — (re-exported from job_service)
    raf.transmit_submission       — SFTP transmission for a submission batch

All tasks import and call the canonical service functions — no business logic
is duplicated here.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

from celery.utils.log import get_task_logger

# ---------------------------------------------------------------------------
# Single Celery application — imported from job_service, NOT re-created here.
# ---------------------------------------------------------------------------
from app.services.job_service import (  # noqa: F401  (re-export for Beat)
    celery_app,
    _mark_started,
    _mark_progress,
    _mark_success,
    _mark_failure,
    _upsert_job,
    _audit,
    # Re-export existing tasks so callers can import from one place.
    task_calculate_raf_batch,
    task_generate_submission,
    task_analyze_document,
    task_process_claims_batch,
    task_sync_fhir,
    task_scan_suspects_all,
    task_calculate_provider_scorecards,
)

logger = logging.getLogger(__name__)
task_logger = get_task_logger(__name__)


# ---------------------------------------------------------------------------
# Register pipeline chain handlers in the worker process so that
# emit_internal("emr_sync_completed") triggers the full auto-chain
# even when the sync runs inside a Celery worker (not the FastAPI process).
# ---------------------------------------------------------------------------

from celery.signals import worker_ready

@worker_ready.connect
def _setup_pipeline_on_worker_ready(**kwargs):
    """Register pipeline chain event handlers when the Celery worker starts."""
    try:
        from app.services.pipeline_chain import setup_pipeline_chain
        setup_pipeline_chain()
        logger.info("celery_tasks: pipeline chain registered in worker process")
    except Exception as exc:
        logger.warning("celery_tasks: failed to register pipeline chain: %s", exc)


# ---------------------------------------------------------------------------
# Beat schedule — all periodic work lives here so a single Beat process
# drives everything without the FastAPI process being involved at all.
# ---------------------------------------------------------------------------

celery_app.conf.beat_schedule = {
    # Check every 60 s which EMR connections are due for a sync and fan out
    # individual raf.sync_emr_connection tasks for each one.
    "check-due-emr-syncs-every-60s": {
        "task": "raf.check_due_syncs",
        "schedule": 60.0,  # seconds
        "options": {"queue": "default"},
    },
    # HIPAA data-retention sweep — runs on the interval configured in settings.
    # The task itself reads RETENTION_CHECK_INTERVAL_HOURS and skips if not due,
    # so firing every hour is safe.
    "retention-sweep-every-hour": {
        "task": "raf.retention_sweep",
        "schedule": 3600.0,  # seconds — task guards against double-fire internally
        "options": {"queue": "default"},
    },
}


# ---------------------------------------------------------------------------
# Task: check which EMR connections are due and fan out sync tasks
# ---------------------------------------------------------------------------


@celery_app.task(
    name="raf.check_due_syncs",
    queue="default",
    max_retries=3,
    default_retry_delay=30,
    bind=True,
)
def task_check_due_syncs(self) -> dict[str, Any]:
    """Periodic Beat entry: find connections with sync_enabled=True that are due
    and enqueue an individual ``raf.sync_emr_connection`` task for each one.

    This replaces the daemon-thread loop in sync_scheduler.py.
    """
    task_logger.info("check_due_syncs: scanning EMR connections")
    try:
        from app.db import raf_cursor

        with raf_cursor() as cur:
            cur.execute(
                "SELECT id, tenant_id, sync_enabled, is_active, "
                "sync_interval_minutes, last_sync_at "
                "FROM emr_connections WHERE sync_enabled = 1 AND is_active = 1"
            )
            connections = cur.fetchall()
        now = datetime.now(timezone.utc)
        dispatched: list[int] = []
        skipped: list[int] = []

        for conn in connections:
            if not conn.get("sync_enabled"):
                continue
            if not conn.get("is_active"):
                continue

            interval_minutes: int = int(conn.get("sync_interval_minutes") or 60)
            last_sync = conn.get("last_sync_at")

            if last_sync:
                if isinstance(last_sync, str):
                    last_sync = datetime.fromisoformat(
                        last_sync.replace("Z", "+00:00")
                    )
                if last_sync.tzinfo is None:
                    last_sync = last_sync.replace(tzinfo=timezone.utc)
                elapsed_minutes = (now - last_sync).total_seconds() / 60
                if elapsed_minutes < interval_minutes:
                    skipped.append(conn["id"])
                    continue

            conn_id: int = conn["id"]
            tenant_id: str = str(conn.get("tenant_id") or "")
            if not tenant_id:
                task_logger.error(
                    "check_due_syncs: skipping connection %d — no tenant_id in connection row "
                    "(HIPAA multi-tenant isolation requires explicit tenant assignment)",
                    conn_id,
                )
                skipped.append(conn_id)
                continue
            task_logger.info(
                "check_due_syncs: dispatching sync for connection %d (tenant=%s)",
                conn_id,
                tenant_id,
            )
            task_sync_emr_connection.apply_async(
                kwargs={
                    "connection_id": conn_id,
                    "tenant_id": tenant_id,
                    "sync_type": "incremental",
                },
                queue="default",
            )
            dispatched.append(conn_id)

        result = {
            "dispatched": dispatched,
            "skipped": skipped,
            "checked_at": now.isoformat(),
        }
        task_logger.info(
            "check_due_syncs: dispatched=%d skipped=%d",
            len(dispatched),
            len(skipped),
        )
        return result

    except Exception as exc:
        task_logger.error("check_due_syncs failed: %s", exc, exc_info=True)
        raise self.retry(exc=exc, countdown=30 * (self.request.retries + 1))


# ---------------------------------------------------------------------------
# Task: sync a single EMR connection
# ---------------------------------------------------------------------------


@celery_app.task(
    bind=True,
    name="raf.sync_emr_connection",
    queue="default",
    max_retries=3,
    default_retry_delay=120,
)
def task_sync_emr_connection(
    self,
    connection_id: int,
    tenant_id: str,
    sync_type: str = "incremental",
) -> dict[str, Any]:
    """Sync a single EMR connection by delegating to emr_manager.trigger_sync.

    This task replaces the inline ``emr_mgr.trigger_sync`` call that lived
    inside the daemon thread loop.

    Args:
        connection_id: Row ID in ``emr_connections``.
        tenant_id:     Tenant identifier string.
        sync_type:     ``"incremental"`` (default) or ``"full"``.

    Returns:
        Dict from ``emr_manager.trigger_sync`` with sync stats.
    """
    job_id = self.request.id
    _mark_started(
        self,
        "raf.sync_emr_connection",
        {
            "connection_id": connection_id,
            "tenant_id": tenant_id,
            "sync_type": sync_type,
        },
    )
    _audit(
        "job_started",
        job_id,
        f"sync_emr_connection connection={connection_id} tenant={tenant_id} type={sync_type}",
    )
    task_logger.info(
        "sync_emr_connection starting: connection=%d tenant=%s type=%s",
        connection_id,
        tenant_id,
        sync_type,
    )

    try:
        from app.services import emr_manager as emr_mgr

        _mark_progress(self, 0, 1, f"Running {sync_type} EMR sync for connection {connection_id}")
        result = emr_mgr.trigger_sync(connection_id, sync_type=sync_type)
        _mark_progress(self, 1, 1, "Sync complete")

        outcome = {
            "connection_id": connection_id,
            "tenant_id": tenant_id,
            "sync_type": sync_type,
            **result,
        }
        _mark_success(self, outcome)
        _audit(
            "job_completed",
            job_id,
            f"sync_emr_connection connection={connection_id} result={json.dumps(result)[:200]}",
        )
        task_logger.info(
            "sync_emr_connection finished: connection=%d result=%s",
            connection_id,
            result,
        )
        return outcome

    except Exception as exc:
        _mark_failure(self, exc)
        _audit("job_failed", job_id, str(exc)[:500])
        task_logger.error(
            "sync_emr_connection failed: connection=%d error=%s",
            connection_id,
            exc,
            exc_info=True,
        )
        # Exponential back-off: 2 min, 4 min, 8 min
        raise self.retry(exc=exc, countdown=120 * (2 ** self.request.retries))


# ---------------------------------------------------------------------------
# Task: HIPAA data-retention sweep
# ---------------------------------------------------------------------------


@celery_app.task(
    bind=True,
    name="raf.retention_sweep",
    queue="default",
    max_retries=2,
    default_retry_delay=300,
)
def task_retention_sweep(self) -> dict[str, Any]:
    """Periodic Beat entry: run the HIPAA data-retention sweep.

    The underlying ``run_retention_sweep`` implementation is the single source
    of truth for retention policy — this task just invokes it on schedule.

    Returns:
        Dict with ``total_deleted`` and ``tables_processed`` keys.
    """
    job_id = self.request.id
    _mark_started(self, "raf.retention_sweep", {})
    _audit("job_started", job_id, "retention_sweep")
    task_logger.info("retention_sweep: starting HIPAA data-retention sweep")

    try:
        from app.services.data_retention import run_retention_sweep

        _mark_progress(self, 0, 1, "Running retention sweep")
        result = run_retention_sweep()
        _mark_progress(self, 1, 1, "Complete")

        _mark_success(self, result)
        _audit(
            "job_completed",
            job_id,
            f"retention_sweep deleted={result.get('total_deleted', 0)} "
            f"tables={result.get('tables_processed', 0)}",
        )
        task_logger.info(
            "retention_sweep finished: %d rows deleted across %d tables",
            result.get("total_deleted", 0),
            result.get("tables_processed", 0),
        )
        return result

    except Exception as exc:
        _mark_failure(self, exc)
        _audit("job_failed", job_id, str(exc)[:500])
        task_logger.error("retention_sweep failed: %s", exc, exc_info=True)
        raise self.retry(exc=exc, countdown=300 * (self.request.retries + 1))


# ---------------------------------------------------------------------------
# Task: normalize encounters for a tenant
# ---------------------------------------------------------------------------


@celery_app.task(
    bind=True,
    name="raf.normalize_encounters",
    queue="heavy",
    max_retries=3,
    default_retry_delay=60,
)
def task_normalize_encounters(
    self,
    tenant_id: str,
) -> dict[str, Any]:
    """Run encounter and diagnosis normalization for a tenant.

    Delegates to ``encounter_normalization_service.sync_all`` which syncs
    encounters then diagnoses in a single pass.

    Args:
        tenant_id: Tenant identifier string (required).

    Returns:
        Dict with encounter and diagnosis sync statistics.
    """
    if not tenant_id:
        raise ValueError(
            "task_normalize_encounters: tenant_id is required — "
            "refusing to run without tenant scope (HIPAA multi-tenant isolation)"
        )
    job_id = self.request.id
    _mark_started(self, "raf.normalize_encounters", {"tenant_id": tenant_id})
    _audit("job_started", job_id, f"normalize_encounters tenant={tenant_id}")
    task_logger.info("normalize_encounters starting for tenant=%s", tenant_id)

    try:
        from app.services.encounter_normalization_service import sync_all

        _mark_progress(self, 0, 2, "Syncing encounters")
        result = sync_all(tenant_id=tenant_id)
        _mark_progress(self, 2, 2, "Normalization complete")

        _mark_success(self, result)
        _audit(
            "job_completed",
            job_id,
            f"normalize_encounters tenant={tenant_id} "
            f"encounters={result.get('encounters_synced', 0)} "
            f"diagnoses={result.get('diagnoses_synced', 0)}",
        )
        task_logger.info(
            "normalize_encounters finished for tenant=%s: %s",
            tenant_id,
            result,
        )
        return result

    except Exception as exc:
        _mark_failure(self, exc)
        _audit("job_failed", job_id, str(exc)[:500])
        task_logger.error(
            "normalize_encounters failed tenant=%s: %s", tenant_id, exc, exc_info=True
        )
        raise self.retry(exc=exc, countdown=60 * (self.request.retries + 1))


# ---------------------------------------------------------------------------
# Task: batch AI analysis of clinical encounters
# ---------------------------------------------------------------------------


@celery_app.task(
    bind=True,
    name="raf.analyze_encounters_batch",
    queue="heavy",
    max_retries=1,
    default_retry_delay=300,
    soft_time_limit=1800,  # 30 min soft limit
    time_limit=2100,       # 35 min hard limit
)
def task_analyze_encounters_batch(
    self,
    tenant_id: str,
    patient_ids: list[int] | None = None,
    max_encounters: int = 500,
) -> dict[str, Any]:
    """Batch AI analysis of clinical encounters.

    Runs the 4-stage verified pipeline (Stage1 rule extraction -> Stage2 Gemini ->
    Stage3 verification -> Stage4 scoring) on all unanalyzed encounters for the tenant.

    This task is dispatched by pipeline_chain when pipeline_mode='auto_ai'.

    Args:
        tenant_id: Tenant identifier.
        patient_ids: Optional list of specific patient IDs to analyze. If None, all active patients.
        max_encounters: Maximum encounters to process in one batch (default 500).

    Returns:
        Dict with analyzed_count, error_count, skipped_count stats.
    """
    if not tenant_id:
        raise ValueError("tenant_id is required")

    job_id = self.request.id
    _mark_started(self, "raf.analyze_encounters_batch", {
        "tenant_id": tenant_id,
        "patient_ids": patient_ids,
        "max_encounters": max_encounters,
    })
    _audit("job_started", job_id, f"analyze_encounters_batch tenant={tenant_id}")
    task_logger.info("analyze_encounters_batch starting: tenant=%s max=%d", tenant_id, max_encounters)

    try:
        from app.db import raf_cursor
        from app.services.pipeline_orchestrator import run_verified_pipeline
        from app.services.openemr_connector import get_clinical_notes
        from app.services.meat_evidence_service import store_analysis_meat, update_hcc_meat_status
        from app.services.suspect_engine import save_suspects_from_analysis
        from app.routers.analysis import _save_encounter_analysis
        from datetime import date

        # Get unanalyzed encounters
        with raf_cursor() as cur:
            if patient_ids:
                placeholders = ",".join(["%s"] * len(patient_ids))
                cur.execute(f"""
                    SELECT ne.encounter_id, ne.patient_id, ne.encounter_date
                    FROM normalized_encounters ne
                    LEFT JOIN raf_encounter_analysis rea ON rea.encounter_id = ne.encounter_id
                    WHERE ne.tenant_id = %s AND ne.patient_id IN ({placeholders}) AND rea.id IS NULL
                    ORDER BY ne.encounter_date DESC
                    LIMIT %s
                """, (tenant_id, *patient_ids, max_encounters))
            else:
                cur.execute("""
                    SELECT ne.encounter_id, ne.patient_id, ne.encounter_date
                    FROM normalized_encounters ne
                    LEFT JOIN raf_encounter_analysis rea ON rea.encounter_id = ne.encounter_id
                    WHERE ne.tenant_id = %s AND rea.id IS NULL
                    ORDER BY ne.encounter_date DESC
                    LIMIT %s
                """, (tenant_id, max_encounters))
            encounters = cur.fetchall()

        total = len(encounters)
        analyzed = 0
        errors = 0
        skipped = 0

        task_logger.info("analyze_encounters_batch: found %d unanalyzed encounters", total)
        _mark_progress(self, 0, total, f"Found {total} encounters to analyze")

        for i, enc in enumerate(encounters):
            encounter_id = enc["encounter_id"]
            patient_id = enc["patient_id"]

            try:
                # Get clinical notes
                notes = get_clinical_notes(encounter_id)
                if not notes:
                    skipped += 1
                    continue

                note_text = "\n\n".join(
                    n.get("note_text") or n.get("subjective", "") or "" for n in notes
                )
                if not note_text.strip():
                    skipped += 1
                    continue

                # Get patient demographics
                patient_age = None
                patient_sex = None
                try:
                    with raf_cursor() as cur:
                        cur.execute("SELECT date_of_birth, gender FROM patients WHERE id = %s", (patient_id,))
                        pat = cur.fetchone()
                    if pat and pat.get("date_of_birth"):
                        from app.services.raf_calculator import _calculate_age
                        patient_age = _calculate_age(pat["date_of_birth"])
                        patient_sex = pat.get("gender")
                except Exception:
                    pass

                # Run 4-stage AI pipeline
                result = run_verified_pipeline(
                    clinical_note=note_text,
                    patient_age=patient_age,
                    patient_sex=patient_sex,
                )

                # Persist results
                _save_encounter_analysis(encounter_id, patient_id, result)

                # Save suspects
                suspects = result.get("suspect_conditions", [])
                if suspects:
                    save_suspects_from_analysis(patient_id, encounter_id, suspects, tenant_id=tenant_id)

                # Save MEAT evidence
                try:
                    gemini_compat = {
                        "diagnoses": [
                            {
                                "icd10": d.get("icd10", ""),
                                "hcc_code": d.get("hcc", ""),
                                "confidence": d.get("confidence", 0),
                                "negated": False,
                                "meat": {
                                    "monitoring": (d.get("meat") or {}).get("M", ""),
                                    "evaluation": (d.get("meat") or {}).get("E", ""),
                                    "assessment": (d.get("meat") or {}).get("A", ""),
                                    "treatment": (d.get("meat") or {}).get("T", ""),
                                },
                            }
                            for d in result.get("diagnoses", [])
                        ],
                        "_meta": {"encounter_id": encounter_id},
                    }
                    store_analysis_meat(patient_id, date.today().year, gemini_compat)
                    update_hcc_meat_status(patient_id, date.today().year)
                except Exception as meat_exc:
                    task_logger.warning("MEAT storage failed enc=%d: %s", encounter_id, meat_exc)

                analyzed += 1
                _mark_progress(self, i + 1, total, f"Analyzed {analyzed}/{total}")

            except Exception as exc:
                errors += 1
                task_logger.warning(
                    "analyze_encounters_batch: encounter %d failed: %s", encounter_id, exc
                )

        result_stats = {
            "tenant_id": tenant_id,
            "total_encounters": total,
            "analyzed": analyzed,
            "errors": errors,
            "skipped": skipped,
        }
        _mark_success(self, result_stats)
        _audit("job_completed", job_id, f"analyzed={analyzed} errors={errors} skipped={skipped}")
        task_logger.info("analyze_encounters_batch finished: %s", result_stats)

        # Emit event so downstream pipeline chain steps can continue
        try:
            from app.services.event_emitter import emit_internal
            emit_internal("analysis_completed", {
                "tenant_id": tenant_id,
                "analyzed_count": analyzed,
                "pipeline_run_id": 0,  # Chain recovers via stash
            })
        except Exception:
            pass

        return result_stats

    except Exception as exc:
        _mark_failure(self, exc)
        _audit("job_failed", job_id, str(exc)[:500])
        task_logger.error("analyze_encounters_batch failed: %s", exc, exc_info=True)
        raise self.retry(exc=exc, countdown=300)


# ---------------------------------------------------------------------------
# Task: transmit a submission via SFTP
# ---------------------------------------------------------------------------


@celery_app.task(
    bind=True,
    name="raf.transmit_submission",
    queue="default",
    max_retries=3,
    default_retry_delay=120,
)
def task_transmit_submission(
    self,
    tenant_id: str,
    submission_id: int,
) -> dict[str, Any]:
    """Transmit a generated CMS submission file via SFTP.

    Delegates to ``cms_sftp_service.transmit_submission``.

    Args:
        tenant_id:     Tenant identifier string.
        submission_id: Row ID of the submission batch to transmit.

    Returns:
        Dict with transmission status, bytes sent, and CMS acknowledgement info.
    """
    job_id = self.request.id
    _mark_started(
        self,
        "raf.transmit_submission",
        {"tenant_id": tenant_id, "submission_id": submission_id},
    )
    _audit(
        "job_started",
        job_id,
        f"transmit_submission tenant={tenant_id} submission={submission_id}",
    )
    task_logger.info(
        "transmit_submission starting: tenant=%s submission=%d",
        tenant_id,
        submission_id,
    )

    try:
        from app.services.cms_sftp_service import transmit_submission

        _mark_progress(self, 0, 2, f"Transmitting submission {submission_id} via SFTP")
        result = transmit_submission(
            submission_id=submission_id, tenant_id=tenant_id
        )
        _mark_progress(self, 2, 2, "Transmission complete")

        outcome = {
            "tenant_id": tenant_id,
            "submission_id": submission_id,
            **result,
        }
        _mark_success(self, outcome)
        _audit(
            "job_completed",
            job_id,
            f"transmit_submission submission={submission_id} "
            f"status={result.get('status', 'unknown')}",
        )
        task_logger.info(
            "transmit_submission finished: submission=%d status=%s",
            submission_id,
            result.get("status"),
        )
        return outcome

    except Exception as exc:
        _mark_failure(self, exc)
        _audit("job_failed", job_id, str(exc)[:500])
        task_logger.error(
            "transmit_submission failed: submission=%d error=%s",
            submission_id,
            exc,
            exc_info=True,
        )
        # Exponential back-off: 2 min, 4 min, 8 min
        raise self.retry(exc=exc, countdown=120 * (2 ** self.request.retries))


# ---------------------------------------------------------------------------
# Dispatch helpers for new tasks
# ---------------------------------------------------------------------------


def dispatch_sync_emr_connection(
    connection_id: int,
    tenant_id: str,
    sync_type: str = "incremental",
    submitted_by: int | None = None,
) -> str:
    """Enqueue a single EMR connection sync. Returns task ID."""
    task = task_sync_emr_connection.apply_async(
        kwargs={
            "connection_id": connection_id,
            "tenant_id": tenant_id,
            "sync_type": sync_type,
        },
        queue="default",
    )
    _upsert_job(
        task.id,
        task_name="raf.sync_emr_connection",
        status="PENDING",
        total=1,
        submitted_by=submitted_by,
        args_json=json.dumps(
            {"connection_id": connection_id, "tenant_id": tenant_id, "sync_type": sync_type}
        ),
    )
    return task.id


def dispatch_normalize_encounters(
    tenant_id: str,
    submitted_by: int | None = None,
) -> str:
    """Enqueue an encounter normalization job. Returns task ID."""
    if not tenant_id:
        raise ValueError(
            "dispatch_normalize_encounters: tenant_id is required — "
            "refusing to enqueue without tenant scope (HIPAA multi-tenant isolation)"
        )
    task = task_normalize_encounters.apply_async(
        kwargs={"tenant_id": tenant_id},
        queue="heavy",
    )
    _upsert_job(
        task.id,
        task_name="raf.normalize_encounters",
        status="PENDING",
        total=2,
        submitted_by=submitted_by,
        args_json=json.dumps({"tenant_id": tenant_id}),
    )
    return task.id


def dispatch_analyze_encounters_batch(
    tenant_id: str,
    patient_ids: list[int] | None = None,
    max_encounters: int = 500,
    submitted_by: int | None = None,
) -> str:
    """Enqueue a batch AI analysis job for a tenant. Returns task ID.

    Dispatches to the ``heavy`` queue so it does not compete with lightweight
    operational tasks.  The pipeline_chain should call this when
    ``pipeline_mode='auto_ai'`` rather than running analysis inline.

    Args:
        tenant_id: Tenant identifier (required).
        patient_ids: Optional subset of patient IDs to restrict the batch.
        max_encounters: Cap on encounters processed in one run (default 500).
        submitted_by: Optional user ID for audit trail.

    Returns:
        Celery task ID string.
    """
    if not tenant_id:
        raise ValueError(
            "dispatch_analyze_encounters_batch: tenant_id is required — "
            "refusing to enqueue without tenant scope (HIPAA multi-tenant isolation)"
        )
    task = task_analyze_encounters_batch.apply_async(
        kwargs={
            "tenant_id": tenant_id,
            "patient_ids": patient_ids,
            "max_encounters": max_encounters,
        },
        queue="heavy",
    )
    _upsert_job(
        task.id,
        task_name="raf.analyze_encounters_batch",
        status="PENDING",
        total=max_encounters,
        submitted_by=submitted_by,
        args_json=json.dumps({
            "tenant_id": tenant_id,
            "patient_ids": patient_ids,
            "max_encounters": max_encounters,
        }),
    )
    return task.id


def dispatch_transmit_submission(
    tenant_id: str,
    submission_id: int,
    submitted_by: int | None = None,
) -> str:
    """Enqueue an SFTP transmission job. Returns task ID."""
    task = task_transmit_submission.apply_async(
        kwargs={"tenant_id": tenant_id, "submission_id": submission_id},
        queue="default",
    )
    _upsert_job(
        task.id,
        task_name="raf.transmit_submission",
        status="PENDING",
        total=2,
        submitted_by=submitted_by,
        args_json=json.dumps({"tenant_id": tenant_id, "submission_id": submission_id}),
    )
    return task.id
