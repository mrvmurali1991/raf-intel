"""
Celery tasks for RAF Intelligence background work.

This module re-exports the Celery app from job_service and defines additional
periodic/operational tasks that replace the daemon-thread sync scheduler.

Worker startup
--------------
    # All-queues worker (development):
    celery -A app.services.celery_tasks worker --loglevel=info --concurrency=4 \
        -Q default,heavy,pipeline,notifications

    # Dedicated heavy-AI worker (production):
    celery -A app.services.celery_tasks worker --loglevel=info \
        --autoscale=10,3 -Q heavy --hostname heavy@%%h

    # Dedicated pipeline/event worker:
    celery -A app.services.celery_tasks worker --loglevel=info \
        --concurrency=4 -Q pipeline --hostname pipeline@%%h

    # Dedicated notification/webhook worker:
    celery -A app.services.celery_tasks worker --loglevel=info \
        --concurrency=8 -Q notifications --hostname notify@%%h

Beat scheduler (periodic tasks)
--------------------------------
    celery -A app.services.celery_tasks beat --loglevel=info

Both commands must be run from the ``backend/`` directory so that the
``app`` package is importable.

Queue definitions
-----------------
    default       — lightweight operational tasks (EMR syncs, health checks, sweeps)
    heavy         — long-running AI analysis (30-35 min tasks); autoscale=10,3
    pipeline      — pipeline chain event handlers (ordered, low-latency)
    notifications — outbound webhooks and alert delivery; high concurrency, short TTL

Task inventory
--------------
    raf.sync_emr_connection       — per-connection EMR sync  [default]
    raf.check_due_syncs           — Beat: scan and fan out sync tasks  [default]
    raf.retention_sweep           — Beat: HIPAA data-retention sweep  [default]
    raf.normalize_encounters      — encounter normalisation  [heavy]
    raf.analyze_encounters_batch  — batch AI analysis  [heavy]
    raf.calculate_raf_batch       — (re-exported from job_service)  [heavy]
    raf.generate_submission       — (re-exported from job_service)  [default]
    raf.transmit_submission       — SFTP transmission  [default]
    raf.pipeline_step             — pipeline chain step  [pipeline]
    raf.send_notification         — webhook/alert delivery  [notifications]

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
from app.services import raf_inbox
from app.services.job_service import (  # noqa: F401  (re-export for Beat)
    _audit,
    _mark_failure,
    _mark_progress,
    _mark_started,
    _mark_success,
    _upsert_job,
    celery_app,
    task_analyze_document,
    task_calculate_provider_scorecards,
    # Re-export existing tasks so callers can import from one place.
    task_calculate_raf_batch,
    task_generate_submission,
    task_process_claims_batch,
    task_scan_suspects_all,
    task_sync_fhir,
)
from app.services.raf.calculator import calculate_raf_score

logger = logging.getLogger(__name__)
task_logger = get_task_logger(__name__)

# ---------------------------------------------------------------------------
# Queue configuration and task routing
#
# Four named queues separate workloads by resource profile:
#
#   default       — fast operational tasks (< 2 min); 4–8 concurrent workers
#   heavy         — AI analysis tasks (up to 35 min); autoscale workers 3–10
#   pipeline      — ordered pipeline chain steps; dedicated workers for low
#                   scheduling latency
#   notifications — outbound webhook / alert delivery; high concurrency,
#                   short time limits
#
# Priority levels (0 = highest, 9 = lowest) give Beat-driven periodic tasks
# a lower priority so manual user-triggered jobs are not starved.
# ---------------------------------------------------------------------------

from celery.schedules import crontab
from kombu import Queue

celery_app.conf.task_queues = [
    Queue("default",       routing_key="default",       queue_arguments={"x-max-priority": 10}),
    Queue("heavy",         routing_key="heavy",         queue_arguments={"x-max-priority": 10}),
    Queue("pipeline",      routing_key="pipeline",      queue_arguments={"x-max-priority": 10}),
    Queue("notifications", routing_key="notifications", queue_arguments={"x-max-priority": 10}),
]

celery_app.conf.task_default_queue = "default"
celery_app.conf.task_default_routing_key = "default"

# Explicit per-task routing so callers do not need to specify queue= on every
# apply_async() call.
celery_app.conf.task_routes = {
    # Heavy AI analysis tasks
    "raf.analyze_encounters_batch":      {"queue": "heavy",    "priority": 5},
    "raf.normalize_encounters":          {"queue": "heavy",    "priority": 5},
    "raf.calculate_raf_batch":           {"queue": "heavy",    "priority": 5},
    "raf.analyze_document":              {"queue": "heavy",    "priority": 5},
    "raf.scan_suspects_all":             {"queue": "heavy",    "priority": 4},
    "raf.calculate_provider_scorecards": {"queue": "heavy",    "priority": 4},
    "raf.bulk_ingest.run":               {"queue": "heavy",    "priority": 6},
    "raf.refresh_v28_portfolio":         {"queue": "heavy",    "priority": 4},
    # Pipeline chain event steps
    "raf.cleanup_stale_runs":            {"queue": "pipeline", "priority": 6},
    # Per-patient MEAT refresh (user-triggered, short-lived)
    "raf.refresh_meat_for_patient":      {"queue": "default",  "priority": 6},
    # Default operational tasks
    "raf.sync_emr_connection":           {"queue": "default",  "priority": 5},
    "raf.check_due_syncs":               {"queue": "default",  "priority": 3},
    "raf.retention_sweep":               {"queue": "default",  "priority": 2},
    "raf.generate_submission":           {"queue": "default",  "priority": 5},
    "raf.transmit_submission":           {"queue": "default",  "priority": 6},
    "raf.process_claims_batch":          {"queue": "default",  "priority": 5},
    "raf.sync_fhir":                     {"queue": "default",  "priority": 5},
    "raf.fhir_sync":                     {"queue": "default",  "priority": 5},
}

# Enforce JSON serialization (safer than default which allows pickle).
celery_app.conf.task_serializer = "json"
celery_app.conf.result_serializer = "json"
celery_app.conf.accept_content = ["json"]


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
    # Nightly audit-chain integrity verification (03:00 UTC).
    "verify-audit-chain": {
        "task": "raf.verify_audit_chain",
        "schedule": crontab(hour=3, minute=0),
        "options": {"queue": "default"},
    },
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
    # Clean up pipeline_runs rows that are stuck in a non-terminal state (e.g.
    # worker crashed mid-chain).  Runs every 30 minutes; the underlying service
    # function decides what qualifies as "stale".
    "cleanup-stale-pipeline-runs-every-30m": {
        "task": "raf.cleanup_stale_runs",
        "schedule": 1800.0,
        "options": {"queue": "default"},
    },
    # Drain the RAF recompute inbox every 15 seconds.
    "drain-raf-inbox-every-15s": {
        "task": "raf.drain_raf_inbox",
        "schedule": 15.0,
        "options": {"queue": "default"},
    },
    # Auto-sync discovery: scan OpenEMR for new patients and fan out
    # sync_patient_task per new pid.  Runs every 60s — matches the legacy
    # in-process loop interval (see AUTO_SYNC_INTERVAL_SECONDS env var, default
    # 30s; we run at 60s here to halve the discovery load now that work is
    # actually dispatched to Celery rather than running inline).
    "auto_sync_discover": {
        "task": "auto_sync.discover",
        "schedule": 60.0,
        "options": {"queue": "default"},
    },
}


# ---------------------------------------------------------------------------
# Task: drain the RAF recompute inbox
# ---------------------------------------------------------------------------


@celery_app.task(
    bind=True,
    name="raf.drain_raf_inbox",
    queue="default",
    max_retries=3,
    default_retry_delay=10,
)
def task_drain_raf_inbox(self) -> dict[str, Any]:
    """Drain the raf_recompute_pending inbox, recalculating RAF scores."""
    if not raf_inbox.is_enabled():
        task_logger.info("drain_raf_inbox: feature disabled, skipping")
        return {"drained": 0, "skipped": 1}

    # Reap orphaned processing rows (worker crashed mid-flight). Runs every
    # tick — cheap when there's nothing stale, unblocks the queue otherwise.
    reaped = raf_inbox.reap_stale_processing()
    if reaped:
        task_logger.warning("drain_raf_inbox: reaped %d stale processing rows", reaped)

    drained = 0
    errored = 0
    max_rows = 200

    while drained + errored < max_rows:
        row = raf_inbox.claim_next()
        if row is None:
            break
        try:
            result = calculate_raf_score(patient_id=row["pid"], tenant_id=row["tenant_id"])
            raf_inbox.mark_done(row["id"])
            drained += 1
            try:
                from app.services.realtime_service import publish_raf_updated_sync
                publish_raf_updated_sync(
                    pid=row["pid"],
                    tenant_id=row["tenant_id"],
                    raf_score=result.get("payment_raf") or result.get("raf_score"),
                )
            except (ImportError, AttributeError) as pub_exc:
                task_logger.info("drain_raf_inbox: publish skipped: %s", pub_exc)
            except Exception as pub_exc:
                task_logger.warning("drain_raf_inbox: publish failed (non-fatal): %s", pub_exc)
        except Exception as exc:
            raf_inbox.mark_failed(row["id"], repr(exc))
            errored += 1
            task_logger.warning("drain_raf_inbox: row %d failed: %s", row["id"], exc)

    task_logger.info(
        "drain_raf_inbox: drained=%d errored=%d reaped=%d",
        drained, errored, reaped,
    )
    return {"drained": drained, "errored": errored, "reaped": reaped, "skipped": 0}


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

        # Directly invoke pipeline chain if sync succeeded (the in-process
        # event emitter does not work reliably in Celery's prefork workers).
        if result.get("status") not in ("failed",):
            try:
                from app.services.pipeline_chain import _handle_emr_sync_completed
                task_logger.info(
                    "sync_emr_connection: triggering pipeline chain for tenant=%s",
                    tenant_id,
                )
                _handle_emr_sync_completed({
                    "tenant_id": tenant_id,
                    "connection_id": connection_id,
                    "sync_type": sync_type,
                    "sync_id": result.get("sync_id"),
                })
            except Exception as chain_exc:
                task_logger.error(
                    "sync_emr_connection: pipeline chain failed: %s", chain_exc, exc_info=True
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
# Task: clean up stale pipeline runs
# ---------------------------------------------------------------------------


@celery_app.task(name="raf.cleanup_stale_runs")
def task_cleanup_stale_runs():
    from app.services.pipeline_chain import cleanup_stale_runs
    cleanup_stale_runs()


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
        from datetime import date

        from app.db import raf_cursor
        from app.services.analysis_service import (
            save_encounter_analysis as _save_encounter_analysis,
        )
        from app.services.meat_evidence_service import (
            store_analysis_meat,
            update_hcc_meat_status,
        )
        from app.services.openemr_connector import (
            get_clinical_notes,
            get_latest_vitals,
            get_medication_diagnoses,
            get_medications,
            get_problem_list,
            get_recapture_gaps,
        )
        from app.services.pipeline_orchestrator import run_verified_pipeline
        from app.services.suspect_engine import save_suspects_from_analysis

        # Get unanalyzed encounters
        with raf_cursor() as cur:
            if patient_ids:
                placeholders = ",".join(["%s"] * len(patient_ids))
                cur.execute(f"""
                    SELECT ne.encounter_id, ne.patient_id, ne.encounter_date,
                           ne.openemr_encounter_id
                    FROM normalized_encounters ne
                    LEFT JOIN raf_encounter_analysis rea ON rea.encounter_id = ne.encounter_id
                    WHERE ne.tenant_id = %s AND ne.patient_id IN ({placeholders}) AND rea.id IS NULL
                    ORDER BY ne.encounter_date DESC
                    LIMIT %s
                """, (tenant_id, *patient_ids, max_encounters))
            else:
                cur.execute("""
                    SELECT ne.encounter_id, ne.patient_id, ne.encounter_date,
                           ne.openemr_encounter_id
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
            emr_encounter_id = enc.get("openemr_encounter_id") or encounter_id

            try:
                # Get clinical notes (use OpenEMR encounter ID for SOAP lookup)
                notes = get_clinical_notes(emr_encounter_id, tenant_id=tenant_id)
                if not notes:
                    skipped += 1
                    continue

                note_text = "\n\n".join(
                    n.get("note_text") or n.get("subjective", "") or "" for n in notes
                )
                if not note_text.strip():
                    skipped += 1
                    continue

                # Get patient demographics — try local patients table first,
                # then fall back to emr_patient_matches for FHIR patients.
                patient_age = None
                patient_sex = None
                try:
                    with raf_cursor() as cur:
                        cur.execute("SELECT dob, gender FROM patients WHERE id = %s AND tenant_id = %s", (patient_id, tenant_id))
                        pat = cur.fetchone()
                    if pat and pat.get("dob"):
                        from app.services.raf_calculator import _calculate_age
                        patient_age = _calculate_age(pat["dob"])
                        patient_sex = pat.get("gender")
                    else:
                        # FHIR patient — look up in emr_patient_matches
                        from app.services.patient_service import _get_fhir_patient_row
                        from app.services.raf_calculator import _calculate_age
                        fhir_row = _get_fhir_patient_row(patient_id)
                        if fhir_row:
                            dob_raw = fhir_row.get("DOB") or ""
                            if dob_raw:
                                patient_age = _calculate_age(str(dob_raw)[:10])
                            patient_sex = fhir_row.get("sex") or ""
                except Exception as exc:
                    logger.warning("FHIR patient demographics lookup failed for encounter %s: %s", encounter_id, exc)

                # Resolve emr_pid for OpenEMR lookups
                emr_pid: int | str | None = None
                try:
                    with raf_cursor() as cur:
                        cur.execute(
                            "SELECT emr_pid FROM patients WHERE id = %s AND tenant_id = %s",
                            (patient_id, tenant_id),
                        )
                        _emr_row = cur.fetchone()
                        if _emr_row and _emr_row.get("emr_pid"):
                            _raw = _emr_row["emr_pid"]
                            try:
                                emr_pid = int(float(_raw))
                            except (ValueError, TypeError):
                                emr_pid = str(_raw)  # FHIR UUID
                except Exception:
                    pass

                # Gather enrichment data (all best-effort, free local DB queries)
                medications = None
                problem_list = None
                recapture_gaps = None
                latest_vitals = None
                med_diagnoses = None
                existing_hccs: list[str] = []
                if emr_pid:
                    try:
                        medications = [
                            m.get("drug", "") for m in (get_medications(emr_pid, tenant_id=tenant_id) or [])
                        ]
                    except Exception:
                        pass
                    try:
                        problem_list = get_problem_list(emr_pid, tenant_id=tenant_id)
                    except Exception:
                        pass
                    try:
                        recapture_gaps = get_recapture_gaps(emr_pid, date.today().year, tenant_id=tenant_id)
                    except Exception:
                        pass
                    try:
                        latest_vitals = get_latest_vitals(emr_pid, tenant_id=tenant_id)
                    except Exception:
                        pass
                    try:
                        med_diagnoses = get_medication_diagnoses(emr_pid, tenant_id=tenant_id)
                    except Exception:
                        pass
                try:
                    with raf_cursor() as cur:
                        cur.execute(
                            "SELECT DISTINCT hcc_code FROM raf_patient_hcc "
                            "WHERE patient_id = %s AND measurement_year = %s",
                            (patient_id, date.today().year),
                        )
                        existing_hccs = [str(r["hcc_code"]) for r in cur.fetchall()]
                except Exception:
                    pass

                # Append structured EHR context to note text for Gemini
                # Save original note before enrichment (used for Z-code validation)
                _original_note_text = note_text
                extra_sections: list[str] = []
                if emr_pid:
                    try:
                        from app.services.openemr_connector import get_immunizations
                        imm = get_immunizations(emr_pid)
                        if imm:
                            imm_text = "; ".join(f"{v.get('vaccine_name','')} ({v.get('administered_date','')})" for v in imm[:20])
                            extra_sections.append(f"IMMUNIZATIONS: {imm_text}")
                    except Exception:
                        pass
                    try:
                        from app.services.openemr_connector import get_allergies
                        allergies = get_allergies(emr_pid)
                        if allergies:
                            allergy_text = "; ".join(a.get("title", "") for a in allergies[:20])
                            extra_sections.append(f"ALLERGIES: {allergy_text}")
                    except Exception:
                        pass
                    try:
                        from app.services.openemr_connector import get_family_history
                        fhx = get_family_history(emr_pid)
                        if fhx and any(v for v in fhx.values() if v):
                            fhx_items = [f"{k}: {v}" for k, v in fhx.items() if v and k != "pid"]
                            extra_sections.append(f"FAMILY HISTORY: {'; '.join(fhx_items[:15])}")
                    except Exception:
                        pass
                    try:
                        from app.services.openemr_connector import get_sdoh_data
                        sdoh = get_sdoh_data(emr_pid)
                        if sdoh and any(v for v in sdoh.values() if v):
                            sdoh_items = [f"{k}: {v}" for k, v in sdoh.items() if v and k != "pid"]
                            extra_sections.append(f"SOCIAL HISTORY: {'; '.join(sdoh_items[:15])}")
                    except Exception:
                        pass
                    try:
                        from app.services.openemr_connector import get_referrals
                        refs = get_referrals(emr_pid)
                        if refs:
                            ref_text = "; ".join(f"{r.get('refer_to','')} - {r.get('reason','')}" for r in refs[:10])
                            extra_sections.append(f"REFERRALS: {ref_text}")
                    except Exception:
                        pass
                if extra_sections:
                    note_text += "\n\n--- EHR STRUCTURED DATA ---\n" + "\n".join(extra_sections)

                # Run 4-stage AI pipeline with full context
                result = run_verified_pipeline(
                    clinical_note=note_text,
                    patient_age=patient_age,
                    patient_sex=patient_sex,
                    medications=medications,
                    problem_list=problem_list,
                    recapture_gaps=recapture_gaps,
                    latest_vitals=latest_vitals,
                    med_diagnoses=med_diagnoses,
                    existing_hccs=existing_hccs,
                    encounter_year=date.today().year,
                )

                # ── Evidence-based diagnosis filter ──────────────────────
                # Every AI-found code must have evidence in the current
                # encounter's note.  Three checks:
                #  1. Hallucinated SDOH Z-codes (Z55-Z65) with no Stage 1 basis
                #  2. Cross-encounter bleed: code category not in Stage 1 or note
                #  3. Upcoding: AI combo-code when doctor wrote simpler code
                #
                # Collect Stage 1 codes (extracted from THIS encounter's note)
                _stage1_codes: set[str] = set()
                _stage1_categories: set[str] = set()  # first 3 chars (e.g. "E11", "I50")
                try:
                    ext = result.get("extraction", {})
                    # all_unique_codes is a flat list of ICD-10 strings
                    for c in (ext.get("all_unique_codes") or []):
                        c = str(c).upper().strip()
                        if c:
                            _stage1_codes.add(c)
                            _stage1_categories.add(c[:3])
                except Exception:
                    pass

                def _has_note_evidence(dx: dict) -> bool:
                    """Check if a Gemini diagnosis has evidence in this encounter."""
                    code = (dx.get("icd10") or "").upper().strip()
                    if not code:
                        return False

                    category = code[:3]  # e.g. E11, I50, N18, J81

                    # 1. SDOH Z-codes (Z55-Z65): only keep if the doctor
                    #    explicitly wrote the code in the assessment section.
                    #    These require patient attestation and must never be
                    #    inferred by AI — even if Stage 1 regex picks them up
                    #    from enrichment text or partial matches.
                    if category in ("Z55", "Z56", "Z57", "Z58", "Z59",
                                    "Z60", "Z61", "Z62", "Z63", "Z64", "Z65"):
                        # Only keep if doctor wrote this exact code in SOAP note
                        return code in _original_note_text

                    # 2. Exact match or same category in Stage 1 → keep
                    if code in _stage1_codes or category in _stage1_categories:
                        return True

                    # 3. Check if Gemini upgraded a code in the same disease
                    #    group. E.g. I10 (HTN) in note → I11.0 (HTN+HF) or
                    #    I13.0 (HTN+HF+CKD) from AI. Allow only if the
                    #    *base* condition category is in Stage 1.
                    #    Hypertensive combos: I11, I12, I13 ← I10 in note
                    if category in ("I11", "I12", "I13") and "I10" in _stage1_categories:
                        return True
                    #    Diabetes combos: E11.2x, E11.4x ← E11.6x in note
                    if category == "E11" and "E11" in _stage1_categories:
                        return True

                    # 4. Not in Stage 1 at all → cross-encounter bleed, remove
                    return False

                orig_dx = result.get("diagnoses", [])
                filtered_dx = [d for d in orig_dx if _has_note_evidence(d)]
                removed = len(orig_dx) - len(filtered_dx)
                if removed:
                    removed_codes = [d.get("icd10", "?") for d in orig_dx if not _has_note_evidence(d)]
                    task_logger.info(
                        "analyze_encounters_batch: enc=%d removed %d unsupported codes: %s",
                        encounter_id, removed, ", ".join(removed_codes),
                    )
                    result["diagnoses"] = filtered_dx

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
        except Exception as exc:
            logger.warning("Failed to emit analysis_completed event: %s", exc)

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


# ---------------------------------------------------------------------------
# Task: FHIR connection sync (tenant-scoped)
# ---------------------------------------------------------------------------


@celery_app.task(
    bind=True,
    name="raf.fhir_sync",
    queue="default",
    max_retries=3,
    default_retry_delay=120,
)
def fhir_sync_task(
    self,
    connection_id: int,
    tenant_id: str,
    user_id: str,
    sync_type: str = "incremental",
    resource_types: list[str] | None = None,
    use_bulk: bool = False,
) -> dict[str, Any]:
    """Sync a single FHIR connection, re-validating tenant ownership.

    The daemon-thread implementation this replaces did not re-check which
    tenant owns the connection, so a task queued by tenant A could end up
    syncing a connection that had been re-assigned to tenant B.  This task
    re-queries ``fhir_connections`` with an explicit tenant filter before
    touching any PHI.
    """
    if not tenant_id:
        raise ValueError(
            "fhir_sync_task: tenant_id is required — refusing to run "
            "without tenant scope (HIPAA multi-tenant isolation)"
        )

    job_id = self.request.id
    _mark_started(
        self,
        "raf.fhir_sync",
        {
            "connection_id": connection_id,
            "tenant_id": tenant_id,
            "user_id": user_id,
            "sync_type": sync_type,
        },
    )
    _audit(
        "job_started",
        job_id,
        f"fhir_sync connection={connection_id} tenant={tenant_id} user={user_id}",
    )

    try:
        import app.services.fhir_service as fhir_svc
        from app.db import raf_cursor

        # Re-validate tenant ownership inside the worker process.
        with raf_cursor() as cur:
            cur.execute(
                "SELECT id, tenant_id, is_active FROM fhir_connections "
                "WHERE id = %s AND tenant_id = %s LIMIT 1",
                (connection_id, tenant_id),
            )
            row = cur.fetchone()

        if not row:
            msg = (
                f"fhir_sync_task: connection {connection_id} does not belong "
                f"to tenant {tenant_id} — aborting (possible tenant leak)"
            )
            task_logger.error(msg)
            _mark_failure(self, PermissionError(msg))
            _audit("job_failed", job_id, msg[:500])
            return {"status": "aborted", "reason": "tenant_mismatch"}

        if not row.get("is_active"):
            msg = f"fhir_sync_task: connection {connection_id} is disabled"
            task_logger.warning(msg)
            _mark_failure(self, RuntimeError(msg))
            _audit("job_failed", job_id, msg[:500])
            return {"status": "aborted", "reason": "inactive"}

        _mark_progress(self, 0, 1, f"Running {sync_type} FHIR sync for connection {connection_id}")
        result = fhir_svc.run_sync(
            connection_id=connection_id,
            sync_type=sync_type,
            resource_types=resource_types,
            use_bulk=use_bulk,
        )
        _mark_progress(self, 1, 1, "Sync complete")

        outcome = {
            "connection_id": connection_id,
            "tenant_id": tenant_id,
            "user_id": user_id,
            "sync_type": sync_type,
            **(result or {}),
        }
        _mark_success(self, outcome)
        _audit(
            "job_completed",
            job_id,
            f"fhir_sync connection={connection_id} result={json.dumps(result or {})[:200]}",
        )
        return outcome

    except Exception as exc:
        _mark_failure(self, exc)
        _audit("job_failed", job_id, str(exc)[:500])
        task_logger.error(
            "fhir_sync_task failed: connection=%d tenant=%s error=%s",
            connection_id, tenant_id, exc, exc_info=True,
        )
        raise self.retry(exc=exc, countdown=120 * (2 ** self.request.retries))


# ---------------------------------------------------------------------------
# Task: refresh MEAT evidence for a single patient (async, request-scoped)
# ---------------------------------------------------------------------------


@celery_app.task(
    bind=True,
    name="raf.refresh_meat_for_patient",
    queue="default",
    max_retries=2,
    default_retry_delay=60,
    soft_time_limit=300,   # 5 min soft limit — MEAT extraction is multi-second per note
    time_limit=360,        # 6 min hard kill
)
def task_refresh_meat_for_patient(
    self,
    tenant_id: str,
    patient_id: int,
    year: int | None = None,
    max_days_lookback: int = 365,
) -> dict[str, Any]:
    """Run the rule-based MEAT extractor for a single patient in the background.

    Enqueued by POST /api/raf-central/{pid}/actions/refresh-meat instead of
    running synchronously in the request path.  The endpoint returns HTTP 202
    with ``{status: "queued", job_id: <celery_task_id>}``; the frontend should
    poll GET /api/jobs/{job_id} for completion status.

    Front-end polling follow-up required:
        The refresh-meat endpoint now returns immediately with 202/queued.
        The frontend needs to poll ``GET /api/jobs/{job_id}`` and refresh the
        RAF Central panel when the job reaches SUCCEEDED status.  This is a
        separate concern tracked in the frontend backlog.

    Args:
        tenant_id: Tenant identifier (required for HIPAA multi-tenant isolation).
        patient_id: RAF Intelligence patient ID.
        year: Measurement year. Defaults to current year if None.
        max_days_lookback: Number of days back to look for clinical notes.

    Returns:
        Summary dict from ``run_auto_meat_for_patient`` with MEAT extraction stats.
    """
    if not tenant_id:
        raise ValueError(
            "task_refresh_meat_for_patient: tenant_id is required — "
            "refusing to run without tenant scope (HIPAA multi-tenant isolation)"
        )

    job_id = self.request.id
    _mark_started(
        self,
        "raf.refresh_meat_for_patient",
        {"tenant_id": tenant_id, "patient_id": patient_id, "year": year},
    )
    _audit(
        "job_started",
        job_id,
        f"refresh_meat_for_patient patient={patient_id} tenant={tenant_id} year={year}",
    )
    task_logger.info(
        "refresh_meat_for_patient: starting patient=%d tenant=%s year=%s",
        patient_id, tenant_id, year,
    )

    try:
        from app.cache import cache_delete_pattern
        from app.services.auto_meat_extractor import run_auto_meat_for_patient

        _mark_progress(self, 0, 1, f"Running MEAT extraction for patient {patient_id}")
        summary = run_auto_meat_for_patient(
            patient_id,
            tenant_id=tenant_id,
            year=year,
            max_days_lookback=max_days_lookback,
        )
        _mark_progress(self, 1, 1, "MEAT extraction complete")

        # Invalidate the RAF Central panel cache so the next GET reflects new data.
        try:
            cache_delete_pattern(f"raf-central:{tenant_id}:*:{patient_id}:*")
        except Exception as cache_exc:
            task_logger.warning(
                "refresh_meat_for_patient: cache invalidation failed (non-fatal): %s", cache_exc
            )

        _mark_success(self, summary)
        _audit(
            "job_completed",
            job_id,
            f"refresh_meat patient={patient_id} wrote={summary.get('evidence_written', 0)}",
        )
        task_logger.info(
            "refresh_meat_for_patient: finished patient=%d summary=%s", patient_id, summary
        )
        return summary

    except Exception as exc:
        _mark_failure(self, exc)
        _audit("job_failed", job_id, str(exc)[:500])
        task_logger.error(
            "refresh_meat_for_patient failed patient=%d: %s", patient_id, exc, exc_info=True
        )
        raise self.retry(exc=exc, countdown=60 * (self.request.retries + 1))


# ---------------------------------------------------------------------------
# EMR Activate Pipeline — auto-sync + RAF calc on EMR switch
# ---------------------------------------------------------------------------

@celery_app.task(
    bind=True,
    name="raf.emr_activate_pipeline",
    queue="default",
    max_retries=1,
    default_retry_delay=30,
)
def task_emr_activate_pipeline(
    self,
    connection_id: int,
    tenant_id: str,
) -> dict[str, Any]:
    """Auto-run sync + RAF calculation when an EMR connection is activated.

    Steps:
    1. Trigger sync for the newly activated connection
    2. Calculate RAF scores for all active patients
    3. Apply HCC hierarchy
    """
    logger.info(
        "emr_activate_pipeline: starting for connection_id=%s tenant=%s",
        connection_id, tenant_id,
    )
    result: dict[str, Any] = {"connection_id": connection_id, "tenant_id": tenant_id}

    # Step 1: Sync
    try:
        from app.services.emr_manager import trigger_sync
        sync_result = trigger_sync(connection_id, sync_type="incremental", tenant_id=tenant_id)
        result["sync"] = {
            "status": sync_result.get("status"),
            "patients_synced": sync_result.get("patients_synced", 0),
            "conditions_found": sync_result.get("conditions_found", 0),
        }
        logger.info("emr_activate_pipeline: sync done — %s", result["sync"])
    except Exception as exc:
        logger.error("emr_activate_pipeline: sync failed: %s", exc)
        result["sync"] = {"status": "failed", "error": str(exc)}

    # Step 2: RAF calculation for all active patients
    try:
        from app.services.raf.calculator import calculate_raf_for_all_patients
        raf_result = calculate_raf_for_all_patients(tenant_id=tenant_id)
        result["raf_calc"] = {"status": "completed", "details": str(raf_result)[:200]}
        logger.info("emr_activate_pipeline: RAF calc done")
    except Exception as exc:
        logger.error("emr_activate_pipeline: RAF calc failed: %s", exc)
        result["raf_calc"] = {"status": "failed", "error": str(exc)}

    # Step 3: HCC hierarchy
    try:
        from app.db import raf_cursor
        from app.services.hcc_hierarchy import apply_hierarchy_to_patient
        with raf_cursor() as cur:
            cur.execute(
                "SELECT id FROM patients WHERE is_active = 1 AND tenant_id = %s",
                (tenant_id,),
            )
            patient_ids = [r["id"] for r in cur.fetchall()]
        for pid in patient_ids:
            try:
                apply_hierarchy_to_patient(pid, tenant_id=tenant_id)
            except Exception:
                pass
        result["hierarchy"] = {"status": "completed", "patients": len(patient_ids)}
        logger.info("emr_activate_pipeline: hierarchy done for %d patients", len(patient_ids))
    except Exception as exc:
        logger.error("emr_activate_pipeline: hierarchy failed: %s", exc)
        result["hierarchy"] = {"status": "failed", "error": str(exc)}

    logger.info("emr_activate_pipeline: complete — %s", result)
    return result


# ---------------------------------------------------------------------------
# Task: nightly audit-chain integrity verification
# ---------------------------------------------------------------------------


celery_app.conf.task_routes["raf.verify_audit_chain"] = {"queue": "default", "priority": 2}


@celery_app.task(
    bind=True,
    name="raf.verify_audit_chain",
    queue="default",
    max_retries=1,
    default_retry_delay=300,
)
def verify_audit_chain_task(self) -> dict[str, Any]:
    """Nightly Beat task: verify the JSONL immutable audit chain integrity.

    Calls ``verify_audit_chain()`` from immutable_audit, logs the result, and
    emits an ``AUDIT_CHAIN_VERIFIED`` audit event with the outcome so the
    verification itself is in the immutable record.

    Scheduled at 03:00 UTC via the ``"verify-audit-chain"`` beat entry.
    Task name: ``raf.verify_audit_chain``
    """
    from app.services.immutable_audit import emit_audit_event, verify_audit_chain

    task_logger.info("verify_audit_chain_task: starting nightly chain verification")
    try:
        ok, errors = verify_audit_chain()
    except Exception as exc:
        task_logger.error("verify_audit_chain_task: verification raised: %s", exc, exc_info=True)
        raise self.retry(exc=exc)

    result: dict[str, Any] = {
        "ok": ok,
        "error_count": len(errors),
        "errors": errors[:20],  # cap payload; full set is in JSONL
        "verified_at": datetime.now(timezone.utc).isoformat(),
    }

    if ok:
        task_logger.info("verify_audit_chain_task: chain intact")
    else:
        task_logger.error(
            "verify_audit_chain_task: chain BROKEN — %d error(s): %s",
            len(errors),
            "; ".join(errors[:5]),
        )

    # Emit the verification result into the audit trail itself.
    try:
        emit_audit_event(
            "AUDIT_CHAIN_VERIFIED",
            payload={
                "ok": ok,
                "error_count": len(errors),
                "first_errors": errors[:5],
            },
        )
    except Exception as emit_exc:
        task_logger.warning("verify_audit_chain_task: failed to emit audit event: %s", emit_exc)

    return result


# ---------------------------------------------------------------------------
# Auto-sync via Celery
#
# These tasks replace the in-process asyncio loop in ``auto_sync_loop.py``
# when ``AUTO_SYNC_VIA_CELERY=true``.  The Beat scheduler fires
# ``auto_sync.discover`` every 60s; that task scans for new OpenEMR pids
# and enqueues ``auto_sync.sync_patient`` per pid on the ``heavy`` queue.
# ---------------------------------------------------------------------------

# Route the new auto-sync tasks so callers don't have to pass queue= on
# every .delay() / .apply_async() call.
celery_app.conf.task_routes["auto_sync.sync_patient"] = {"queue": "heavy",   "priority": 5}
celery_app.conf.task_routes["auto_sync.discover"]     = {"queue": "default", "priority": 4}
celery_app.conf.task_routes["webhook.deliver"]        = {"queue": "notifications", "priority": 5}


@celery_app.task(
    bind=True,
    max_retries=3,
    default_retry_delay=60,
    queue="heavy",
    name="auto_sync.sync_patient",
)
def sync_patient_task(self, tenant_id: str, pid: int) -> dict[str, Any]:
    """Sync a single OpenEMR patient → score → analyze.

    Replaces the in-process per-patient pipeline that lived in
    ``auto_sync_loop._process_patient``.  On any exception the task retries
    with exponential back-off: 4s, 8s, 16s.
    """
    task_logger.info(
        "auto_sync.sync_patient: starting tenant=%s pid=%s", tenant_id, pid
    )
    try:
        from app.services.auto_analyze_service import analyze_patient
        from app.services.auto_score_service import score_patient
        from app.services.auto_sync_service import sync_patient_from_openemr

        local_pid = sync_patient_from_openemr(pid)
        if local_pid is None:
            raise RuntimeError(
                f"sync_patient_from_openemr returned None for emr_pid={pid}"
            )

        score_patient(local_pid)
        analyze_patient(local_pid)

        task_logger.info(
            "auto_sync.sync_patient: completed tenant=%s emr_pid=%s local_pid=%s",
            tenant_id, pid, local_pid,
        )
        return {"tenant_id": tenant_id, "emr_pid": pid, "local_pid": local_pid}

    except Exception as exc:
        task_logger.warning(
            "auto_sync.sync_patient: tenant=%s pid=%s failed (attempt %d): %s",
            tenant_id, pid, self.request.retries + 1, exc,
        )
        # Exponential back-off: 4s, 8s, 16s for attempts 0/1/2
        raise self.retry(exc=exc, countdown=2 ** self.request.retries * 4)


@celery_app.task(
    bind=True,
    max_retries=5,
    default_retry_delay=30,
    queue="default",
    name="webhook.deliver",
)
def deliver_webhook_task(
    self,
    subscription_id: int,
    event_type: str,
    payload: dict[str, Any],
    delivery_id: str | None = None,
) -> dict[str, Any]:
    """Asynchronous webhook delivery — runs the real HTTP POST.

    Reuses ``webhook_service._deliver_to_webhook`` so signing / retry / record
    logic stays in one place.  When ``WEBHOOK_DELIVERY_VIA_CELERY=true``,
    ``webhook_service.fire_event`` enqueues this task instead of doing the
    HTTP call inline in the request thread.
    """
    task_logger.info(
        "webhook.deliver: starting subscription=%s event=%s delivery=%s",
        subscription_id, event_type, delivery_id,
    )
    try:
        from app.services import webhook_service

        webhook = webhook_service.get_webhook(subscription_id)
        if not webhook:
            task_logger.warning(
                "webhook.deliver: subscription %s not found — dropping", subscription_id
            )
            return {"status": "not_found", "subscription_id": subscription_id}

        # get_webhook redacts the secret; re-fetch the raw row for HMAC signing.
        from app.db import raf_cursor
        with raf_cursor() as cur:
            cur.execute(
                "SELECT id, tenant_id, url, secret, is_active "
                "FROM webhooks WHERE id = %s",
                (subscription_id,),
            )
            row = cur.fetchone()
        if not row or not row.get("is_active"):
            return {"status": "inactive", "subscription_id": subscription_id}

        webhook_service._deliver_to_webhook(row, event_type, payload)
        return {
            "status": "delivered",
            "subscription_id": subscription_id,
            "event_type": event_type,
            "delivery_id": delivery_id,
        }
    except Exception as exc:
        task_logger.warning(
            "webhook.deliver: subscription=%s event=%s failed (attempt %d): %s",
            subscription_id, event_type, self.request.retries + 1, exc,
        )
        raise self.retry(exc=exc, countdown=30 * (2 ** self.request.retries))


@celery_app.task(name="auto_sync.discover")
def discover_loop_task() -> dict[str, Any]:
    """Beat-driven discovery: scan for new OpenEMR pids and fan out sync tasks.

    Replaces the in-process asyncio loop's discovery half.  Each new pid is
    enqueued onto the ``heavy`` queue via ``sync_patient_task.delay(...)``.

    Tenant scope: the legacy loop hard-codes tenant_id="1" (OpenEMR-bridged
    single-tenant deployment).  We preserve that behavior here — if/when
    multi-tenant OpenEMR bridging lands, this task should iterate over
    enabled tenant connections instead.
    """
    from app.services.auto_sync_loop import _get_new_emr_pids, _is_loop_enabled

    if not _is_loop_enabled():
        task_logger.info("auto_sync.discover: loop disabled, skipping")
        return {"dispatched": 0, "skipped": True}

    try:
        new_pids = _get_new_emr_pids()
    except Exception as exc:
        task_logger.warning("auto_sync.discover: _get_new_emr_pids failed: %s", exc)
        return {"dispatched": 0, "error": str(exc)}

    tenant_id = "1"
    dispatched: list[int] = []
    for pid in new_pids:
        try:
            sync_patient_task.delay(tenant_id, pid)
            dispatched.append(pid)
        except Exception as exc:
            task_logger.warning(
                "auto_sync.discover: failed to enqueue pid=%s: %s", pid, exc
            )

    task_logger.info(
        "auto_sync.discover: dispatched %d new patient sync tasks", len(dispatched)
    )
    return {"dispatched": len(dispatched), "pids": dispatched}


# ---------------------------------------------------------------------------
# Bulk FHIR ingest task — imported so the Celery worker auto-discovers it.
# The task body lives in app.services.bulk_ingest_task to keep this module
# at a manageable size.
# ---------------------------------------------------------------------------
from app.services.bulk_ingest_task import task_run_bulk_ingest  # noqa: F401, E402


# ---------------------------------------------------------------------------
# V28 Transition Impact — daily portfolio refresh
# ---------------------------------------------------------------------------


@celery_app.task(
    bind=True,
    name="raf.refresh_v28_portfolio",
    queue="heavy",
    max_retries=2,
    default_retry_delay=120,
    soft_time_limit=600,
    time_limit=900,
)
def task_refresh_v28_portfolio(
    self,
    tenant_id: str,
    year: int | None = None,
) -> dict[str, Any]:
    if not tenant_id:
        raise ValueError(
            "task_refresh_v28_portfolio: tenant_id is required "
            "(HIPAA multi-tenant isolation)"
        )

    job_id = self.request.id
    _mark_started(
        self,
        "raf.refresh_v28_portfolio",
        {"tenant_id": tenant_id, "year": year},
    )
    _audit(
        "job_started",
        job_id,
        f"refresh_v28_portfolio tenant={tenant_id} year={year}",
    )

    try:
        from app.services.v28_transition_calculator import refresh_portfolio_cache
        payload = refresh_portfolio_cache(tenant_id=tenant_id, year=year)
        summary = {
            "tenant_id":            tenant_id,
            "year":                 payload.get("measurement_year"),
            "patient_count":        payload.get("patient_count"),
            "computed_patient_count": payload.get("computed_patient_count"),
            "total_raf_delta":      payload.get("total_raf_delta"),
            "total_revenue_delta":  payload.get("total_revenue_delta"),
            "raf_erosion_pct":      payload.get("raf_erosion_pct"),
        }
        _mark_success(self, summary)
        _audit("job_completed", job_id, f"refresh_v28_portfolio {summary}")
        task_logger.info("refresh_v28_portfolio: %s", summary)
        return summary
    except Exception as exc:
        _mark_failure(self, exc)
        _audit("job_failed", job_id, str(exc)[:500])
        task_logger.error(
            "refresh_v28_portfolio failed tenant=%s: %s", tenant_id, exc, exc_info=True
        )
        raise self.retry(exc=exc, countdown=120 * (self.request.retries + 1))
