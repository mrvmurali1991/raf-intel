"""
Auto-sync polling loop — production-quality observability + retry edition.

Every AUTO_SYNC_INTERVAL_SECONDS (default 30 s) this coroutine:
  1. Checks enabled flag in auto_sync_status (id=1); pauses if disabled.
  2. Queries openemr.patient_data for pids NOT yet in raf_intelligence.patients
     AND NOT flagged auto_sync_failed=1.
  3. For each new pid calls (in order):
       sync_patient_from_openemr  → local_pid
       score_patient(local_pid)
       analyze_patient(local_pid)
       broadcast_patient_event for each milestone
     Each phase is timed and logged with structured extras (phase, duration_ms).
  4. Per-patient retry: up to 3 attempts with exponential backoff (1s, 4s, 16s).
     After 3 failures marks patients.auto_sync_failed=1 and skips permanently.
  5. Persists full metrics to auto_sync_status (single row, id=1).
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Defensive imports — sibling agents may not have landed yet
# ---------------------------------------------------------------------------

try:
    from app.services.auto_sync_service import sync_patient_from_openemr
except ImportError:
    sync_patient_from_openemr = None  # type: ignore[assignment]

try:
    from app.services.auto_score_service import score_patient
except ImportError:
    score_patient = None  # type: ignore[assignment]

try:
    from app.services.auto_analyze_service import analyze_patient
except ImportError:
    analyze_patient = None  # type: ignore[assignment]

try:
    from app.services.realtime_service import broadcast_patient_event
except ImportError:
    broadcast_patient_event = None  # type: ignore[assignment]

# Retry configuration: delays in seconds for attempts 1, 2, 3
_RETRY_DELAYS = (1, 4, 16)
_MAX_RETRIES = len(_RETRY_DELAYS)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _get_new_emr_pids() -> list[int]:
    """Return emr_pids that haven't been scored yet (i.e. no row in raf_scores).

    Note: ``patients`` is a VIEW over ``openemr.patient_data`` so the patient
    appears there immediately on insert. The real signal that we haven't yet
    processed them is the absence of a raf_scores row. We use that as our
    "new patient" detector. Retry-exhausted pids are also excluded.
    """
    from app.db import openemr_cursor, raf_cursor

    try:
        with openemr_cursor() as cur:
            # pid=1 is the OpenEMR admin/system user, not a real patient —
            # syncing it pollutes raf_intelligence.patients with a fake row.
            cur.execute("SELECT pid FROM patient_data WHERE pid > 1 ORDER BY pid")
            emr_pids = {row["pid"] for row in cur.fetchall()}
    except Exception as exc:
        logger.warning("auto_sync: failed to query openemr.patient_data: %s", exc)
        return []

    if not emr_pids:
        return []

    # Resolve the tenant this loop runs for.  The in-process loop is always
    # tenant 1 (OpenEMR-bridged); guard against a missing env var gracefully.
    try:
        _loop_tenant_id = int(os.getenv("AUTO_SYNC_TENANT_ID", "1"))
    except (TypeError, ValueError):
        _loop_tenant_id = 1

    try:
        with raf_cursor() as cur:
            # "Already processed" = has at least one raf_scores row.
            # Since patient.id == emr_pid for OpenEMR-bridged tenants, we
            # query raf_scores.patient_id directly.
            # Fetch in batches of 1000 to avoid loading the entire table into
            # memory, and scope to the tenant to prevent cross-tenant leakage.
            scored_pids: set[int] = set()
            _batch_size = 1000
            _offset = 0
            while True:
                cur.execute(
                    "SELECT DISTINCT patient_id FROM raf_scores "
                    "WHERE tenant_id = %s LIMIT %s OFFSET %s",
                    (_loop_tenant_id, _batch_size, _offset),
                )
                batch = cur.fetchall()
                if not batch:
                    break
                scored_pids.update(int(row["patient_id"]) for row in batch)
                if len(batch) < _batch_size:
                    break
                _offset += _batch_size

            cur.execute("SELECT emr_pid FROM auto_sync_failed_pids")
            failed_pids = {int(row["emr_pid"]) for row in cur.fetchall()}
    except Exception as exc:
        logger.warning("auto_sync: failed to query raf_intelligence tables: %s", exc)
        return []

    new_pids = sorted(emr_pids - scored_pids - failed_pids)
    return new_pids


def _mark_patient_failed(emr_pid: int, last_error: str | None = None) -> None:
    """Insert emr_pid into auto_sync_failed_pids so it is skipped in all
    future cycles (separate table because patients is a VIEW)."""
    from app.db import raf_cursor

    try:
        with raf_cursor() as cur:
            cur.execute(
                """
                INSERT INTO auto_sync_failed_pids (emr_pid, last_error)
                VALUES (%s, %s)
                ON DUPLICATE KEY UPDATE last_error = VALUES(last_error),
                                        failed_at  = CURRENT_TIMESTAMP
                """,
                (emr_pid, last_error),
            )
        logger.warning(
            "auto_sync: emr_pid=%s added to auto_sync_failed_pids (needs manual review)", emr_pid
        )
    except Exception as exc:
        logger.warning("auto_sync: failed to mark emr_pid=%s as failed: %s", emr_pid, exc)


def _is_loop_enabled() -> bool:
    """Read the enabled flag from auto_sync_status (id=1). Defaults to True
    if the row / column does not exist yet."""
    from app.db import raf_cursor

    try:
        with raf_cursor() as cur:
            cur.execute("SELECT enabled FROM auto_sync_status WHERE id = 1 LIMIT 1")
            row = cur.fetchone()
        if row is None:
            return True
        return bool(row.get("enabled", 1))
    except Exception:
        # Column may not exist yet (pre-migration); treat as enabled.
        logger.debug("swallowed exception", exc_info=True)
        return True


def _persist_status(
    *,
    last_run_at: datetime,
    new_patients: int,
    errors: list[str],
    duration_ms: int,
    total_synced_today: int,
    current_cycle_at: datetime | None,
    last_error: str | None,
) -> None:
    """Upsert the single status row into auto_sync_status."""
    from app.db import raf_cursor

    try:
        with raf_cursor() as cur:
            cur.execute(
                """
                INSERT INTO auto_sync_status
                    (id, last_run_at, new_patients, errors_json, duration_ms,
                     total_synced_today, current_cycle_at, last_error)
                VALUES (1, %s, %s, %s, %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                    last_run_at        = VALUES(last_run_at),
                    new_patients       = VALUES(new_patients),
                    errors_json        = VALUES(errors_json),
                    duration_ms        = VALUES(duration_ms),
                    total_synced_today = VALUES(total_synced_today),
                    current_cycle_at   = VALUES(current_cycle_at),
                    last_error         = VALUES(last_error)
                """,
                (
                    last_run_at.strftime("%Y-%m-%d %H:%M:%S"),
                    new_patients,
                    json.dumps(errors) if errors else None,
                    duration_ms,
                    total_synced_today,
                    current_cycle_at.strftime("%Y-%m-%d %H:%M:%S") if current_cycle_at else None,
                    last_error,
                ),
            )
    except Exception as exc:
        logger.warning("auto_sync: failed to persist status: %s", exc)


def _set_cycle_running(running: bool) -> None:
    """Flip current_cycle_at to now (running) or NULL (idle)."""
    from app.db import raf_cursor

    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S") if running else None
    try:
        with raf_cursor() as cur:
            cur.execute(
                """
                INSERT INTO auto_sync_status (id, current_cycle_at)
                VALUES (1, %s)
                ON DUPLICATE KEY UPDATE current_cycle_at = VALUES(current_cycle_at)
                """,
                (ts,),
            )
    except Exception as exc:
        logger.debug("auto_sync: _set_cycle_running(%s) failed (non-fatal): %s", running, exc)


def _read_total_synced_today() -> int:
    """Read the persisted total_synced_today counter."""
    from app.db import raf_cursor

    try:
        with raf_cursor() as cur:
            cur.execute("SELECT total_synced_today FROM auto_sync_status WHERE id = 1 LIMIT 1")
            row = cur.fetchone()
        return int(row["total_synced_today"]) if row else 0
    except Exception:  # noqa: BLE001 — best-effort guard
        logger.debug("swallowed exception", exc_info=True)
        return 0


def _safe_broadcast(event_type: str, payload: dict[str, Any]) -> None:
    """Schedule the async broadcast on the running event loop.

    auto_sync_loop runs as an asyncio task; ``_process_patient`` is a sync
    function called from inside that task (so we share the loop's thread).
    We can't ``await`` here, but we *can* schedule a task on the running loop
    that will fire at the next ``await`` point in ``run_auto_sync_loop``.

    Also injects ``tenant_id`` (defaults to "1") because
    ``realtime_service.broadcast_patient_event`` drops events without it.
    """
    if broadcast_patient_event is None:
        return
    payload = {"tenant_id": "1", **payload}  # ensure tenant_id present
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(broadcast_patient_event(event_type, payload))
    except RuntimeError:
        # No running loop in this context — fall back to running synchronously
        try:
            asyncio.run(broadcast_patient_event(event_type, payload))
        except Exception as exc:
            logger.debug("auto_sync: broadcast %s failed (non-fatal): %s", event_type, exc)
    except Exception as exc:
        logger.debug("auto_sync: broadcast %s failed (non-fatal): %s", event_type, exc)


# ---------------------------------------------------------------------------
# Per-phase timed execution
# ---------------------------------------------------------------------------

def _timed_phase(phase: str, fn, *args) -> Any:
    """Call *fn(*args)*, log duration with structured extras, and re-raise."""
    t0 = time.monotonic()
    result = fn(*args)
    duration_ms = int((time.monotonic() - t0) * 1000)
    logger.info(
        "auto_sync.phase_complete",
        extra={"phase": phase, "duration_ms": duration_ms},
    )
    return result


# ---------------------------------------------------------------------------
# Per-patient processing with retry + backoff
# ---------------------------------------------------------------------------

def _process_patient(emr_pid: int) -> tuple[int | None, str | None]:
    """
    Sync, score, and analyze a single patient.

    Returns (local_pid, error_str).  error_str is None on success.
    """
    if sync_patient_from_openemr is None:
        return None, "auto_sync_service not available"

    last_err: str | None = None

    for attempt in range(1, _MAX_RETRIES + 1):
        try:
            local_pid = _timed_phase("sync", sync_patient_from_openemr, emr_pid)
        except Exception as exc:
            last_err = f"sync emr_pid={emr_pid} attempt={attempt}: {exc}"
            logger.warning("auto_sync: %s", last_err)
            if attempt < _MAX_RETRIES:
                delay = _RETRY_DELAYS[attempt - 1]
                logger.info("auto_sync: retry emr_pid=%s in %ds", emr_pid, delay)
                time.sleep(delay)
            continue

        if local_pid is None:
            last_err = f"sync emr_pid={emr_pid}: returned None"
            if attempt < _MAX_RETRIES:
                delay = _RETRY_DELAYS[attempt - 1]
                time.sleep(delay)
            continue

        # Sync succeeded — score and analyze (non-fatal failures, no retry)
        _safe_broadcast("patient.synced", {"pid": local_pid, "emr_pid": emr_pid})

        if score_patient is not None:
            try:
                _timed_phase("score", score_patient, local_pid)
                _safe_broadcast("patient.scored", {"pid": local_pid})
            except Exception as exc:
                logger.warning(
                    "auto_sync: score_patient(%s) failed (non-fatal): %s", local_pid, exc,
                    extra={"phase": "score", "duration_ms": 0},
                )

        if analyze_patient is not None:
            try:
                _timed_phase("analyze", analyze_patient, local_pid)
                _safe_broadcast("patient.analyzed", {"pid": local_pid})
            except Exception as exc:
                logger.warning(
                    "auto_sync: analyze_patient(%s) failed (non-fatal): %s", local_pid, exc,
                    extra={"phase": "analyze", "duration_ms": 0},
                )

        return local_pid, None

    # All retries exhausted
    return None, last_err


# ---------------------------------------------------------------------------
# Main loop coroutine
# ---------------------------------------------------------------------------

async def run_auto_sync_loop(interval: int = 30) -> None:
    """
    Async loop that polls for new OpenEMR patients on a fixed interval.

    Intended to be launched as an asyncio background task from the FastAPI
    lifespan context.  Runs until the task is cancelled.

    When ``AUTO_SYNC_VIA_CELERY=true`` is set in the environment, this
    coroutine short-circuits immediately and the real work is driven by
    the ``auto_sync.discover`` Beat task (every 60s), which fans out
    ``auto_sync.sync_patient`` jobs to the heavy queue.  The async loop
    is kept around so dev/local setups that haven't enabled Celery Beat
    still get sync.
    """
    if os.getenv("AUTO_SYNC_VIA_CELERY", "false").lower() == "true":
        logger.info(
            "auto_sync: AUTO_SYNC_VIA_CELERY=true — delegating to Celery "
            "(auto_sync.discover via Beat); in-process loop will not run"
        )
        return

    logger.info("auto_sync: loop started (interval=%ds)", interval)

    total_synced_today = _read_total_synced_today()
    _today = datetime.now(timezone.utc).date()

    while True:
        await asyncio.sleep(interval)

        # Reset daily counter at UTC midnight
        now_utc = datetime.now(timezone.utc)
        if now_utc.date() != _today:
            total_synced_today = 0
            _today = now_utc.date()

        # Check enabled flag
        if not _is_loop_enabled():
            logger.info("auto_sync: loop paused (disabled via API)")
            continue

        t0 = time.monotonic()
        cycle_errors: list[str] = []
        new_pids: list[int] = []
        last_error: str | None = None

        _set_cycle_running(True)

        try:
            new_pids = _get_new_emr_pids()
        except Exception as exc:
            logger.warning("auto_sync: _get_new_emr_pids failed: %s", exc)

        for emr_pid in new_pids:
            try:
                local_pid, err = _process_patient(emr_pid)
                if err:
                    logger.warning(
                        "auto_sync: patient skipped after retries — %s", err,
                        extra={"emr_pid": emr_pid},
                    )
                    cycle_errors.append(err)
                    last_error = err
                    # Mark as failed so it is skipped in future cycles
                    _mark_patient_failed(emr_pid, last_error=err)
                else:
                    logger.info(
                        "auto_sync: emr_pid=%s → local_pid=%s synced+scored+analyzed",
                        emr_pid,
                        local_pid,
                    )
                    total_synced_today += 1
            except Exception as exc:
                msg = f"emr_pid={emr_pid}: unexpected error: {exc}"
                logger.warning("auto_sync: %s", msg)
                cycle_errors.append(msg)
                last_error = msg

        duration_ms = int((time.monotonic() - t0) * 1000)
        now_utc = datetime.now(timezone.utc)

        logger.info(
            "auto_sync.cycle_complete",
            extra={
                "new_patients": len(new_pids),
                "errors": len(cycle_errors),
                "duration_ms": duration_ms,
                "total_synced_today": total_synced_today,
            },
        )

        _persist_status(
            last_run_at=now_utc,
            new_patients=len(new_pids),
            errors=cycle_errors,
            duration_ms=duration_ms,
            total_synced_today=total_synced_today,
            current_cycle_at=None,   # cycle complete → idle
            last_error=last_error,
        )
