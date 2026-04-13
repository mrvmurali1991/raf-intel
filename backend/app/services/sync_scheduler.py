"""
EMR Sync Scheduler — Celery Beat edition.

The periodic sync work (EMR connections, HIPAA retention sweep) is now driven
by Celery Beat rather than a Python daemon thread.  This module retains the
same public API (``start_scheduler``, ``stop_scheduler``, ``get_scheduler_status``)
so that ``app/main.py`` and any health endpoints continue to work unchanged.

How the periodic tasks are scheduled
-------------------------------------
Celery Beat reads ``celery_app.conf.beat_schedule`` which is configured in
``app/services/celery_tasks.py``:

    "check-due-emr-syncs-every-60s": task ``raf.check_due_syncs`` every 60 s
    "retention-sweep-every-hour":     task ``raf.retention_sweep`` every hour

The Beat process must be started separately from the FastAPI process:

    # In one terminal — Celery worker:
    celery -A app.services.celery_tasks worker --loglevel=info --concurrency=4 -Q default,heavy

    # In another terminal — Celery Beat scheduler:
    celery -A app.services.celery_tasks beat --loglevel=info

Both commands must be run from the ``backend/`` directory.

Legacy functions kept for backward-compatibility
-------------------------------------------------
``start_scheduler()`` and ``stop_scheduler()`` are now no-ops — they log a
reminder that Beat handles scheduling.  ``get_scheduler_status()`` returns a
status dict indicating that Celery Beat is the active scheduler.

The underlying sync and retention logic (``_check_and_run_due_syncs`` and
``_check_and_run_retention_sweep``) is preserved as private helpers; they are
called from the corresponding Celery tasks and can still be invoked directly
in tests or one-off scripts.
"""

import logging
from datetime import datetime, timezone

from app.config import settings
from app.services import emr_manager as emr_mgr

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Module-level state — kept for get_scheduler_status() compatibility.
# ---------------------------------------------------------------------------

# No daemon thread; Beat drives scheduling externally.
_SCHEDULER_BACKEND = "celery_beat"
_CHECK_INTERVAL = 60  # seconds — informational only, matches Beat schedule

# The last time a retention sweep ran is now tracked by Celery Beat / the task
# itself; we keep this variable so get_scheduler_status() can surface it when
# the task updates it via _update_last_retention_sweep().
_last_retention_sweep: datetime | None = None


def _update_last_retention_sweep(ts: datetime | None = None) -> None:
    """Called by the retention Celery task after a successful sweep."""
    global _last_retention_sweep
    _last_retention_sweep = ts or datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Backward-compatible public API
# ---------------------------------------------------------------------------


def start_scheduler() -> None:
    """No-op — periodic tasks are managed by Celery Beat.

    Kept so that ``app/main.py`` lifespan does not need to change.
    A log message reminds operators to start Beat alongside the worker.
    """
    logger.info(
        "Sync scheduler: Celery Beat is the active scheduler. "
        "Ensure the Beat process is running: "
        "celery -A app.services.celery_tasks beat --loglevel=info"
    )


def stop_scheduler() -> None:
    """No-op — Beat is an external process; FastAPI cannot stop it."""
    logger.info("Sync scheduler: stop_scheduler() called (no-op; Beat runs externally).")


def get_scheduler_status() -> dict:
    """Return scheduler status for the /health endpoint.

    Returns a dict that is compatible with the old daemon-thread status shape
    so existing health-check consumers do not break.
    """
    return {
        "running": True,  # Beat is always assumed running if deployed correctly
        "backend": _SCHEDULER_BACKEND,
        "check_interval_seconds": _CHECK_INTERVAL,
        "retention_check_interval_hours": settings.retention_check_interval_hours,
        "last_retention_sweep": (
            _last_retention_sweep.isoformat() if _last_retention_sweep else None
        ),
        "note": (
            "Scheduling is handled by Celery Beat. "
            "Start with: celery -A app.services.celery_tasks beat --loglevel=info"
        ),
    }


# ---------------------------------------------------------------------------
# Core business logic — called by Celery tasks, also usable in tests/scripts
# ---------------------------------------------------------------------------


def _check_and_run_due_syncs() -> dict:
    """Check all connections with sync_enabled=True and dispatch syncs that are due.

    Returns a summary dict with ``dispatched`` and ``skipped`` lists.

    This function is called from ``celery_tasks.task_check_due_syncs``; it can
    also be invoked directly from tests or one-off management scripts.
    """
    from app.services.celery_tasks import task_sync_emr_connection

    connections = emr_mgr.list_connections()
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
                last_sync = datetime.fromisoformat(last_sync.replace("Z", "+00:00"))
            if last_sync.tzinfo is None:
                last_sync = last_sync.replace(tzinfo=timezone.utc)
            elapsed_minutes = (now - last_sync).total_seconds() / 60
            if elapsed_minutes < interval_minutes:
                skipped.append(conn["id"])
                continue

        conn_id: int = conn["id"]
        tenant_id: str = str(conn.get("tenant_id") or "")
        if not tenant_id:
            logger.error(
                "Skipping sync for connection %d — no tenant_id in connection row "
                "(HIPAA multi-tenant isolation requires explicit tenant assignment)",
                conn_id,
            )
            skipped.append(conn_id)
            continue
        logger.info(
            "Dispatching scheduled sync for connection %d (tenant=%s)", conn_id, tenant_id
        )
        try:
            task_sync_emr_connection.apply_async(
                kwargs={
                    "connection_id": conn_id,
                    "tenant_id": tenant_id,
                    "sync_type": "incremental",
                },
                queue="default",
            )
            dispatched.append(conn_id)
        except Exception as exc:
            logger.error("Failed to enqueue sync for connection %d: %s", conn_id, exc)

    return {"dispatched": dispatched, "skipped": skipped, "checked_at": now.isoformat()}


def _check_and_run_retention_sweep() -> dict:
    """Run the HIPAA data-retention sweep if the configured interval has elapsed.

    Returns the result dict from ``run_retention_sweep``, or ``{}`` if not due.

    Called from ``celery_tasks.task_retention_sweep``; also usable in tests.
    """
    global _last_retention_sweep

    interval_hours = settings.retention_check_interval_hours
    now = datetime.now(timezone.utc)

    if _last_retention_sweep is not None:
        elapsed_hours = (now - _last_retention_sweep).total_seconds() / 3600
        if elapsed_hours < interval_hours:
            logger.debug(
                "Retention sweep not due (%.1f h elapsed, interval=%s h)",
                elapsed_hours,
                interval_hours,
            )
            return {}

    from app.services.data_retention import run_retention_sweep

    logger.info("Running scheduled data retention sweep")
    try:
        result = run_retention_sweep()
        _last_retention_sweep = now
        logger.info(
            "Retention sweep finished: %d rows deleted across %d tables",
            result.get("total_deleted", 0),
            result.get("tables_processed", 0),
        )
        return result
    except Exception as exc:
        logger.error("Retention sweep failed: %s", exc, exc_info=True)
        # Still update timestamp to avoid hammering the DB on repeated failures.
        _last_retention_sweep = now
        return {"error": str(exc)}
