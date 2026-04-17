"""
RAF recompute inbox — dirty-marker queue driving asynchronous RAF recalculation.

This module is the single write point for "this patient's RAF score needs
to be recomputed". Every mutation path (EMR sync normalization, encounter
analysis, suspect accept/dismiss, sweep-period change, manual edit) calls
``mark_dirty`` / ``mark_many_dirty``. A Celery Beat worker drains the inbox
every 15 s and runs ``calculate_raf_score`` for each claimed row.

Design
------
  * ``INSERT IGNORE`` on a unique (pid, tenant_id, status='pending') key
    gives us natural debouncing — a storm of events for one patient
    coalesces into a single pending row.
  * ``claim_next`` wraps ``UPDATE ... WHERE status='pending' ORDER BY
    queued_at LIMIT 1`` inside a transaction using ``SELECT ... FOR UPDATE
    SKIP LOCKED`` so multiple workers can run without double-processing.
  * Feature flag ``RAF_INBOX_ENABLED`` (default: true) lets operators
    fall back to the legacy in-process chain if needed.

Usage
-----
    from app.services import raf_inbox

    raf_inbox.mark_dirty(pid=42, tenant_id="default", reason="analysis")
    raf_inbox.mark_many_dirty([1, 2, 3], tenant_id="default", reason="sync")

    # worker (see task_drain_raf_inbox in celery_tasks.py):
    claimed = raf_inbox.claim_next()
    if claimed:
        try:
            ...  # run calculation
            raf_inbox.mark_done(claimed["id"])
        except Exception as exc:
            raf_inbox.mark_failed(claimed["id"], str(exc))
"""
# Do NOT use ``from __future__ import annotations`` — type hints are
# evaluated at runtime by FastAPI (this module is imported from routers).

import logging
import os
from typing import Any

from app.db import raf_cursor

logger = logging.getLogger(__name__)

# Reasons are conventional, not enforced at the DB layer. Keep the set
# small so dashboards / metrics stay legible.
VALID_REASONS = frozenset(
    {"sync", "analysis", "suspect", "sweep_change", "manual", "backfill"}
)


def is_enabled() -> bool:
    """
    Return True when the inbox path is active. When False, callers fall
    back to whatever legacy code path they previously used.

    Read at call-time (not import-time) so operators can flip the flag
    on the running container without a restart.
    """
    raw = os.environ.get("RAF_INBOX_ENABLED", "true").strip().lower()
    return raw not in ("0", "false", "no", "off")


def mark_dirty(pid: int, tenant_id: str, reason: str = "manual") -> bool:
    """
    Mark a single patient as needing RAF recalculation.

    Returns True if a new pending row was inserted, False if one already
    existed (i.e., the write was debounced by the unique key).

    Never raises on duplicate-key — this is the hot path and must be safe
    to call from anywhere, including request handlers and event handlers.
    """
    if not is_enabled():
        return False
    if not tenant_id:
        logger.warning("raf_inbox.mark_dirty: refusing empty tenant_id (pid=%s)", pid)
        return False
    if reason not in VALID_REASONS:
        logger.debug("raf_inbox.mark_dirty: non-canonical reason %r", reason)
    try:
        with raf_cursor() as cur:
            cur.execute(
                "INSERT IGNORE INTO raf_recompute_pending "
                "(pid, tenant_id, reason, status) VALUES (%s, %s, %s, 'pending')",
                (int(pid), str(tenant_id), str(reason)),
            )
            inserted = int(cur.rowcount or 0) > 0
        if inserted:
            logger.info(
                "raf_inbox: marked dirty pid=%s tenant=%s reason=%s",
                pid, tenant_id, reason,
            )
        return inserted
    except Exception as exc:
        logger.exception(
            "raf_inbox.mark_dirty failed pid=%s tenant=%s reason=%s: %s",
            pid, tenant_id, reason, exc,
        )
        return False


def mark_many_dirty(
    pids: list[int] | list[str], tenant_id: str, reason: str = "sync"
) -> int:
    """
    Mark many patients dirty in a single INSERT. Returns the number of
    newly-inserted pending rows (others were debounced).
    """
    if not is_enabled() or not pids or not tenant_id:
        return 0
    try:
        int_pids = sorted({int(p) for p in pids if p is not None})
    except (TypeError, ValueError) as exc:
        logger.warning("raf_inbox.mark_many_dirty: invalid pid list: %s", exc)
        return 0
    if not int_pids:
        return 0
    rows = [(p, str(tenant_id), str(reason)) for p in int_pids]
    try:
        with raf_cursor() as cur:
            cur.executemany(
                "INSERT IGNORE INTO raf_recompute_pending "
                "(pid, tenant_id, reason, status) VALUES (%s, %s, %s, 'pending')",
                rows,
            )
            inserted = int(cur.rowcount or 0)
        logger.info(
            "raf_inbox: marked %d/%d patients dirty tenant=%s reason=%s",
            inserted, len(int_pids), tenant_id, reason,
        )
        return inserted
    except Exception as exc:
        logger.exception(
            "raf_inbox.mark_many_dirty failed tenant=%s reason=%s: %s",
            tenant_id, reason, exc,
        )
        return 0


def claim_next() -> dict[str, Any] | None:
    """
    Atomically claim the oldest pending row for processing. Returns the
    claimed row as a dict with keys {id, pid, tenant_id, reason, attempts},
    or None if the inbox is empty.

    Uses SELECT ... FOR UPDATE SKIP LOCKED so multiple workers can drain
    concurrently without stepping on each other. MySQL 8+ required.
    """
    try:
        with raf_cursor() as cur:
            cur.execute(
                "SELECT id, pid, tenant_id, reason, attempts "
                "FROM raf_recompute_pending "
                "WHERE status = 'pending' "
                "ORDER BY queued_at ASC "
                "LIMIT 1 "
                "FOR UPDATE SKIP LOCKED"
            )
            row = cur.fetchone()
            if not row:
                return None
            row_id = int(row["id"])
            cur.execute(
                "UPDATE raf_recompute_pending "
                "SET status = 'processing', claimed_at = CURRENT_TIMESTAMP, "
                "    attempts = attempts + 1 "
                "WHERE id = %s AND status = 'pending'",
                (row_id,),
            )
            if int(cur.rowcount or 0) == 0:
                # Another worker beat us to it despite SKIP LOCKED (shouldn't
                # happen on MySQL 8+, but guard anyway).
                return None
        return {
            "id": row_id,
            "pid": int(row["pid"]),
            "tenant_id": str(row["tenant_id"]),
            "reason": str(row["reason"]),
            "attempts": int(row["attempts"]) + 1,
        }
    except Exception as exc:
        logger.exception("raf_inbox.claim_next failed: %s", exc)
        return None


def mark_done(row_id: int) -> None:
    """Mark a claimed row as successfully processed."""
    try:
        with raf_cursor() as cur:
            cur.execute(
                "UPDATE raf_recompute_pending "
                "SET status = 'done', completed_at = CURRENT_TIMESTAMP, "
                "    last_error = NULL "
                "WHERE id = %s",
                (int(row_id),),
            )
    except Exception as exc:
        logger.exception("raf_inbox.mark_done failed id=%s: %s", row_id, exc)


def mark_failed(row_id: int, error: str) -> None:
    """
    Mark a claimed row as failed. The error text is truncated to fit.
    Row stays in the table for observability + manual requeue.
    """
    try:
        with raf_cursor() as cur:
            cur.execute(
                "UPDATE raf_recompute_pending "
                "SET status = 'failed', completed_at = CURRENT_TIMESTAMP, "
                "    last_error = %s "
                "WHERE id = %s",
                ((error or "")[:2000], int(row_id)),
            )
    except Exception as exc:
        logger.exception("raf_inbox.mark_failed failed id=%s: %s", row_id, exc)


def reap_stale_processing(stale_seconds: int | None = None) -> int:
    """Recover rows stuck in ``processing`` after a worker crash.

    The unique key ``(pid, tenant_id, status)`` means a single orphaned
    processing row blocks every future recompute for that patient with
    ``Duplicate entry '...-processing'``. We resolve it by deleting stale
    rows outright — the pending row (if any) for the same patient then
    claims cleanly on the next tick.

    ``stale_seconds`` defaults to ``RAF_INBOX_STALE_SECONDS`` (300s / 5 min).
    Returns the number of rows reaped.
    """
    if stale_seconds is None:
        try:
            stale_seconds = int(os.getenv("RAF_INBOX_STALE_SECONDS", "300"))
        except ValueError:
            stale_seconds = 300
    try:
        with raf_cursor() as cur:
            cur.execute(
                "SELECT id, pid, tenant_id, attempts, "
                "TIMESTAMPDIFF(SECOND, claimed_at, NOW()) AS age_s "
                "FROM raf_recompute_pending "
                "WHERE status = 'processing' "
                "AND claimed_at < NOW() - INTERVAL %s SECOND",
                (int(stale_seconds),),
            )
            stale = cur.fetchall() or []
            if not stale:
                return 0
            for row in stale:
                logger.warning(
                    "raf_inbox: reaping stale processing row id=%s pid=%s "
                    "tenant=%s attempts=%s age=%ss",
                    row.get("id"), row.get("pid"), row.get("tenant_id"),
                    row.get("attempts"), row.get("age_s"),
                )
            ids = [int(r["id"]) for r in stale]
            placeholders = ",".join(["%s"] * len(ids))
            cur.execute(
                f"DELETE FROM raf_recompute_pending WHERE id IN ({placeholders})",
                ids,
            )
            return len(ids)
    except Exception as exc:
        logger.exception("raf_inbox.reap_stale_processing failed: %s", exc)
        return 0


def requeue_failed(tenant_id: str | None = None, max_rows: int = 100) -> int:
    """
    Move failed rows back to pending so the worker retries them.
    Optionally scoped to a single tenant. Returns rows requeued.
    """
    try:
        with raf_cursor() as cur:
            if tenant_id:
                cur.execute(
                    "UPDATE raf_recompute_pending SET status='pending', "
                    "last_error = CONCAT('requeued from: ', IFNULL(last_error, '')) "
                    "WHERE status='failed' AND tenant_id=%s LIMIT %s",
                    (tenant_id, int(max_rows)),
                )
            else:
                cur.execute(
                    "UPDATE raf_recompute_pending SET status='pending', "
                    "last_error = CONCAT('requeued from: ', IFNULL(last_error, '')) "
                    "WHERE status='failed' LIMIT %s",
                    (int(max_rows),),
                )
            return int(cur.rowcount or 0)
    except Exception as exc:
        logger.exception("raf_inbox.requeue_failed failed: %s", exc)
        return 0


def get_stats(tenant_id: str | None = None) -> dict[str, Any]:
    """
    Return counts per status + oldest-pending-age for dashboards.
    Scoped to a tenant when provided; otherwise global.
    """
    stats: dict[str, Any] = {
        "pending": 0,
        "processing": 0,
        "done": 0,
        "failed": 0,
        "oldest_pending_age_seconds": None,
    }
    try:
        with raf_cursor() as cur:
            if tenant_id:
                cur.execute(
                    "SELECT status, COUNT(*) AS c FROM raf_recompute_pending "
                    "WHERE tenant_id=%s GROUP BY status",
                    (tenant_id,),
                )
            else:
                cur.execute(
                    "SELECT status, COUNT(*) AS c FROM raf_recompute_pending "
                    "GROUP BY status"
                )
            for row in cur.fetchall() or []:
                key = str(row["status"])
                if key in stats:
                    stats[key] = int(row["c"] or 0)
            if tenant_id:
                cur.execute(
                    "SELECT TIMESTAMPDIFF(SECOND, MIN(queued_at), NOW()) AS age "
                    "FROM raf_recompute_pending WHERE status='pending' "
                    "AND tenant_id=%s",
                    (tenant_id,),
                )
            else:
                cur.execute(
                    "SELECT TIMESTAMPDIFF(SECOND, MIN(queued_at), NOW()) AS age "
                    "FROM raf_recompute_pending WHERE status='pending'"
                )
            row = cur.fetchone()
            if row and row.get("age") is not None:
                stats["oldest_pending_age_seconds"] = int(row["age"])
    except Exception as exc:
        logger.exception("raf_inbox.get_stats failed: %s", exc)
    return stats


__all__ = [
    "VALID_REASONS",
    "is_enabled",
    "mark_dirty",
    "mark_many_dirty",
    "claim_next",
    "mark_done",
    "mark_failed",
    "reap_stale_processing",
    "requeue_failed",
    "get_stats",
]
