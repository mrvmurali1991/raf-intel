"""
EMR Sync Scheduler
Runs periodic sync jobs for all EMR connections that have sync_enabled=True.
Uses a background thread with a simple loop — no external dependencies needed.
For production with Celery, tasks are dispatched to the Celery worker.

Also drives the HIPAA data-retention sweep on a configurable interval
(default: every 24 hours, controlled by RETENTION_CHECK_INTERVAL_HOURS).
"""
import threading
import time
import logging
from datetime import datetime, timezone
from app.services import emr_manager as emr_mgr
from app.config import settings

logger = logging.getLogger(__name__)

_scheduler_thread: threading.Thread | None = None
_stop_event = threading.Event()
_CHECK_INTERVAL = 60  # Check for due syncs every 60 seconds

# Retention sweep state — track when the last sweep ran so we fire at most
# once per RETENTION_CHECK_INTERVAL_HOURS regardless of the tight loop.
_last_retention_sweep: datetime | None = None


def start_scheduler():
    """Start the background sync scheduler. Called once from app lifespan."""
    global _scheduler_thread
    if _scheduler_thread and _scheduler_thread.is_alive():
        logger.warning("Sync scheduler already running")
        return
    _stop_event.clear()
    _scheduler_thread = threading.Thread(
        target=_scheduler_loop,
        daemon=True,
        name="emr-sync-scheduler",
    )
    _scheduler_thread.start()
    logger.info("EMR sync scheduler started (check interval: %ds)", _CHECK_INTERVAL)


def stop_scheduler():
    """Stop the scheduler gracefully. Called from app lifespan shutdown."""
    _stop_event.set()
    if _scheduler_thread:
        _scheduler_thread.join(timeout=5)
    logger.info("EMR sync scheduler stopped")


def _scheduler_loop():
    """Main loop — checks all connections and triggers syncs that are due."""
    while not _stop_event.is_set():
        try:
            _check_and_run_due_syncs()
        except Exception as exc:
            logger.error("Sync scheduler error: %s", exc, exc_info=True)
        try:
            _check_and_run_retention_sweep()
        except Exception as exc:
            logger.error("Retention scheduler error: %s", exc, exc_info=True)
        _stop_event.wait(timeout=_CHECK_INTERVAL)


def _check_and_run_due_syncs():
    """Check all connections with sync_enabled=True and run if due."""
    connections = emr_mgr.list_connections()
    now = datetime.now(timezone.utc)

    for conn in connections:
        if not conn.get("sync_enabled"):
            continue
        # Only sync connections that are active (is_active=1/True)
        if not conn.get("is_active"):
            continue

        interval_minutes = conn.get("sync_interval_minutes") or 60
        last_sync = conn.get("last_sync_at")

        # Check if sync is due
        if last_sync:
            # Parse last_sync datetime
            if isinstance(last_sync, str):
                last_sync = datetime.fromisoformat(last_sync.replace("Z", "+00:00"))
            if last_sync.tzinfo is None:
                last_sync = last_sync.replace(tzinfo=timezone.utc)

            elapsed_minutes = (now - last_sync).total_seconds() / 60
            if elapsed_minutes < interval_minutes:
                continue  # Not due yet

        # Sync is due — trigger it
        conn_id = conn["id"]
        conn_name = conn.get("display_name") or conn.get("name") or ""
        logger.info(
            "Triggering scheduled sync for connection %d (%s)",
            conn_id,
            conn_name,
        )
        try:
            result = emr_mgr.trigger_sync(conn_id, sync_type="incremental")
            logger.info(
                "Scheduled sync started for connection %d: %s",
                conn_id,
                result,
            )
        except Exception as exc:
            logger.error(
                "Failed to trigger sync for connection %d: %s",
                conn_id,
                exc,
            )


def _check_and_run_retention_sweep() -> None:
    """Fire a retention sweep if the configured interval has elapsed."""
    global _last_retention_sweep

    interval_hours = settings.retention_check_interval_hours
    now = datetime.now(timezone.utc)

    if _last_retention_sweep is not None:
        elapsed_hours = (now - _last_retention_sweep).total_seconds() / 3600
        if elapsed_hours < interval_hours:
            return  # Not due yet

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
    except Exception as exc:
        logger.error("Retention sweep failed: %s", exc, exc_info=True)
        # Still update the timestamp so we don't hammer the DB on repeated failures.
        _last_retention_sweep = now


def get_scheduler_status() -> dict:
    """Return current scheduler status for the health endpoint."""
    return {
        "running": _scheduler_thread is not None and _scheduler_thread.is_alive(),
        "check_interval_seconds": _CHECK_INTERVAL,
        "retention_check_interval_hours": settings.retention_check_interval_hours,
        "last_retention_sweep": (
            _last_retention_sweep.isoformat() if _last_retention_sweep else None
        ),
    }
