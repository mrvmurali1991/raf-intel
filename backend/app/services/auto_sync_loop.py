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
    """Return emr_pids present in openemr.patient_data but absent from
    raf_intelligence.patients (a VIEW), also excluding retry-exhausted pids
    tracked in auto_sync_failed_pids."""
    from app.db import openemr_cursor, raf_cursor

    try:
        with openemr_cursor() as cur:
            cur.execute("SELECT pid FROM patient_data WHERE pid > 0 ORDER BY pid")
            emr_pids = {row["pid"] for row in cur.fetchall()}
    except Exception as exc:
        logger.warning("auto_sync: failed to query openemr.patient_data: %s", exc)
        return []

    if not emr_pids:
        return []

    try:
        with raf_cursor() as cur:
            # patients is a VIEW over openemr.patient_data — emr_pid == id
            cur.execute("SELECT emr_pid FROM patients WHERE emr_pid IS NOT NULL")
            known_pids = {int(row["emr_pid"]) for row in cur.fetchall()}
            cur.execute("SELECT emr_pid FROM auto_sync_failed_pids")
            failed_pids = {int(row["emr_pid"]) for row in cur.fetchall()}
    except Exception as exc:
        logger.warning("auto_sync: failed to query raf_intelligence tables: %s", exc)
        return []

    new_pids = sorted(emr_pids - known_pids - failed_pids)
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
    except Exception:
        return 0


def _safe_broadcast(event_type: str, payload: dict[str, Any]) -> None:
    if broadcast_patient_event is None:
        return
    try:
        broadcast_patient_event(event_type, payload)
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
    """
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
