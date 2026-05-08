"""
Auto-sync polling loop.

Every AUTO_SYNC_INTERVAL_SECONDS (default 30 s) this coroutine:
  1. Queries openemr.patient_data for pids NOT yet in raf_intelligence.patients.
  2. For each new pid, calls (in order):
       sync_patient_from_openemr  → local_pid
       score_patient(local_pid)
       analyze_patient(local_pid)
       broadcast_patient_event for each milestone
  3. Persists last-run metadata to auto_sync_status (single row, id=1).
  4. Skips on per-patient errors without killing the loop.

Guarded: only runs when settings.auto_sync_enabled is True.
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


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _get_new_emr_pids() -> list[int]:
    """Return emr_pids present in openemr.patient_data but absent from raf_intelligence.patients."""
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
            cur.execute("SELECT emr_pid FROM patients WHERE emr_pid IS NOT NULL")
            known_pids = {row["emr_pid"] for row in cur.fetchall()}
    except Exception as exc:
        logger.warning("auto_sync: failed to query raf_intelligence.patients: %s", exc)
        return []

    new_pids = sorted(emr_pids - known_pids)
    return new_pids


def _persist_status(last_run_at: datetime, new_patients: int, errors: list[str], duration_ms: int) -> None:
    """Upsert a single status row into auto_sync_status."""
    from app.db import raf_cursor

    try:
        with raf_cursor() as cur:
            cur.execute(
                """
                INSERT INTO auto_sync_status (id, last_run_at, new_patients, errors_json, duration_ms)
                VALUES (1, %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                    last_run_at   = VALUES(last_run_at),
                    new_patients  = VALUES(new_patients),
                    errors_json   = VALUES(errors_json),
                    duration_ms   = VALUES(duration_ms)
                """,
                (
                    last_run_at.strftime("%Y-%m-%d %H:%M:%S"),
                    new_patients,
                    json.dumps(errors) if errors else None,
                    duration_ms,
                ),
            )
    except Exception as exc:
        logger.warning("auto_sync: failed to persist status: %s", exc)


def _safe_broadcast(event_type: str, payload: dict[str, Any]) -> None:
    if broadcast_patient_event is None:
        return
    try:
        broadcast_patient_event(event_type, payload)
    except Exception as exc:
        logger.debug("auto_sync: broadcast %s failed (non-fatal): %s", event_type, exc)


def _process_patient(emr_pid: int) -> tuple[int | None, str | None]:
    """
    Sync, score, and analyze a single patient.

    Returns (local_pid, error_str).  error_str is None on success.
    """
    # --- sync ---
    if sync_patient_from_openemr is None:
        return None, "auto_sync_service not available"

    try:
        local_pid = sync_patient_from_openemr(emr_pid)
    except Exception as exc:
        return None, f"sync emr_pid={emr_pid}: {exc}"

    if local_pid is None:
        return None, f"sync emr_pid={emr_pid}: returned None"

    _safe_broadcast("patient.synced", {"pid": local_pid, "emr_pid": emr_pid})

    # --- score ---
    if score_patient is not None:
        try:
            score_patient(local_pid)
            _safe_broadcast("patient.scored", {"pid": local_pid})
        except Exception as exc:
            logger.warning("auto_sync: score_patient(%s) failed (non-fatal): %s", local_pid, exc)

    # --- analyze ---
    if analyze_patient is not None:
        try:
            analyze_patient(local_pid)
            _safe_broadcast("patient.analyzed", {"pid": local_pid})
        except Exception as exc:
            logger.warning("auto_sync: analyze_patient(%s) failed (non-fatal): %s", local_pid, exc)

    return local_pid, None


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

    while True:
        await asyncio.sleep(interval)

        t0 = time.monotonic()
        cycle_errors: list[str] = []
        new_pids: list[int] = []

        try:
            new_pids = _get_new_emr_pids()
        except Exception as exc:
            logger.warning("auto_sync: _get_new_emr_pids failed: %s", exc)

        for emr_pid in new_pids:
            try:
                local_pid, err = _process_patient(emr_pid)
                if err:
                    logger.warning("auto_sync: patient skipped — %s", err)
                    cycle_errors.append(err)
                else:
                    logger.info("auto_sync: emr_pid=%s → local_pid=%s synced+scored+analyzed", emr_pid, local_pid)
            except Exception as exc:
                msg = f"emr_pid={emr_pid}: unexpected error: {exc}"
                logger.warning("auto_sync: %s", msg)
                cycle_errors.append(msg)

        duration_ms = int((time.monotonic() - t0) * 1000)
        now_utc = datetime.now(timezone.utc)

        logger.info(
            "auto_sync.cycle_complete",
            extra={
                "new_patients": len(new_pids),
                "errors": len(cycle_errors),
                "duration_ms": duration_ms,
            },
        )

        _persist_status(
            last_run_at=now_utc,
            new_patients=len(new_pids),
            errors=cycle_errors,
            duration_ms=duration_ms,
        )
