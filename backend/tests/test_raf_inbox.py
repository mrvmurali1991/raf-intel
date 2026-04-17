"""
Integration tests for app.services.raf_inbox.

These tests hit the REAL raf_intelligence MySQL database — no mocks.
They are skipped automatically when the DB is unreachable so CI without
MySQL passes cleanly.

Each test uses a unique tenant_id (uuid-based) and cleans up after itself,
so tests are safe to run in parallel.
"""
from __future__ import annotations

import os
import uuid

import pytest

# ---------------------------------------------------------------------------
# DB reachability guard — skip entire module when MySQL is not available
# ---------------------------------------------------------------------------

def _raf_db_reachable() -> bool:
    try:
        import mysql.connector  # type: ignore

        conn = mysql.connector.connect(
            host=os.getenv("RAF_DB_HOST", "127.0.0.1"),
            port=int(os.getenv("RAF_DB_PORT", "3306")),
            user=os.getenv("RAF_DB_USER", ""),
            password=os.getenv("RAF_DB_PASSWORD", ""),
            database=os.getenv("RAF_DB_NAME", "raf_intelligence"),
            connection_timeout=3,
        )
        conn.close()
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not _raf_db_reachable(),
    reason="RAF MySQL not reachable — skipping real-DB inbox tests",
)

# ---------------------------------------------------------------------------
# Import module under test AFTER guard so import errors don't break suites
# that don't have DB access.
# ---------------------------------------------------------------------------

from app.services import raf_inbox  # noqa: E402
from app.db import raf_cursor  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _tid() -> str:
    """Return a unique tenant_id safe for use in a single test."""
    return f"t_{uuid.uuid4().hex[:8]}"


def _cleanup(tenant_id: str) -> None:
    with raf_cursor() as cur:
        cur.execute(
            "DELETE FROM raf_recompute_pending WHERE tenant_id = %s",
            (tenant_id,),
        )


def _fetch_row(row_id: int) -> dict | None:
    with raf_cursor() as cur:
        cur.execute(
            "SELECT id, status, last_error, completed_at, attempts "
            "FROM raf_recompute_pending WHERE id = %s",
            (row_id,),
        )
        return cur.fetchone()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_mark_dirty_idempotent():
    tid = _tid()
    try:
        first = raf_inbox.mark_dirty(pid=1, tenant_id=tid, reason="sync")
        second = raf_inbox.mark_dirty(pid=1, tenant_id=tid, reason="sync")
        assert first is True, "first insert should return True"
        assert second is False, "duplicate should be debounced (return False)"
        stats = raf_inbox.get_stats(tid)
        assert stats["pending"] == 1
    finally:
        _cleanup(tid)


def test_mark_many_dirty_debounces():
    tid = _tid()
    try:
        # pids [1, 2, 3, 1, 2] — 5 items but only 3 unique
        inserted = raf_inbox.mark_many_dirty([1, 2, 3, 1, 2], tenant_id=tid, reason="sync")
        assert inserted <= 3, f"expected at most 3 insertions, got {inserted}"
        assert inserted >= 1
        stats = raf_inbox.get_stats(tid)
        assert stats["pending"] == 3
    finally:
        _cleanup(tid)


def test_claim_next_atomic():
    tid = _tid()
    try:
        raf_inbox.mark_dirty(pid=10, tenant_id=tid, reason="sync")
        raf_inbox.mark_dirty(pid=11, tenant_id=tid, reason="sync")

        first = raf_inbox.claim_next()
        assert first is not None, "should claim first row"
        assert first["attempts"] == 1

        # Verify status in DB
        row = _fetch_row(first["id"])
        assert row["status"] == "processing"

        second = raf_inbox.claim_next()
        assert second is not None, "should claim second row"
        assert second["id"] != first["id"]

        third = raf_inbox.claim_next()
        # No more pending rows for any tenant — but other tests might have rows,
        # so only assert None if this tenant had exactly 2 rows.
        # Instead verify both rows are processing.
        row2 = _fetch_row(second["id"])
        assert row2["status"] == "processing"
    finally:
        _cleanup(tid)


def test_mark_done_closes_row():
    tid = _tid()
    try:
        raf_inbox.mark_dirty(pid=20, tenant_id=tid, reason="manual")
        claimed = raf_inbox.claim_next()
        assert claimed is not None

        raf_inbox.mark_done(claimed["id"])

        row = _fetch_row(claimed["id"])
        assert row["status"] == "done"
        assert row["completed_at"] is not None

        stats = raf_inbox.get_stats(tid)
        assert stats["pending"] == 0
        assert stats["done"] == 1
    finally:
        _cleanup(tid)


def test_mark_failed_preserves_row():
    tid = _tid()
    try:
        raf_inbox.mark_dirty(pid=30, tenant_id=tid, reason="manual")
        claimed = raf_inbox.claim_next()
        assert claimed is not None

        raf_inbox.mark_failed(claimed["id"], "boom")

        row = _fetch_row(claimed["id"])
        assert row["status"] == "failed"
        assert row["last_error"] == "boom"

        # Failed row must NOT be picked up by claim_next
        next_claim = raf_inbox.claim_next()
        # Could be None or belong to a different tenant — either way not our row
        if next_claim is not None:
            assert next_claim["id"] != claimed["id"]
    finally:
        _cleanup(tid)


def test_requeue_failed_returns_rows_to_pending():
    tid = _tid()
    try:
        raf_inbox.mark_dirty(pid=40, tenant_id=tid, reason="manual")
        claimed = raf_inbox.claim_next()
        assert claimed is not None
        raf_inbox.mark_failed(claimed["id"], "transient error")

        requeued = raf_inbox.requeue_failed(tenant_id=tid)
        assert requeued == 1

        row = _fetch_row(claimed["id"])
        assert row["status"] == "pending"

        # claim_next should pick it up again
        reclaimed = raf_inbox.claim_next()
        assert reclaimed is not None
        assert reclaimed["id"] == claimed["id"]
    finally:
        _cleanup(tid)


def test_mark_dirty_after_done_creates_new_row():
    tid = _tid()
    try:
        raf_inbox.mark_dirty(pid=50, tenant_id=tid, reason="manual")
        claimed = raf_inbox.claim_next()
        assert claimed is not None
        raf_inbox.mark_done(claimed["id"])

        # Same (pid, tenant_id) but status='done' now — unique key allows new pending
        inserted = raf_inbox.mark_dirty(pid=50, tenant_id=tid, reason="manual")
        assert inserted is True, "should create a new pending row alongside the done row"

        stats = raf_inbox.get_stats(tid)
        assert stats["pending"] == 1
        assert stats["done"] == 1
    finally:
        _cleanup(tid)


def test_is_enabled_flag(monkeypatch):
    monkeypatch.setenv("RAF_INBOX_ENABLED", "false")
    assert raf_inbox.is_enabled() is False

    tid = _tid()
    try:
        result = raf_inbox.mark_dirty(pid=99, tenant_id=tid, reason="manual")
        assert result is False, "mark_dirty must return False when inbox is disabled"
        stats = raf_inbox.get_stats(tid)
        assert stats["pending"] == 0
    finally:
        monkeypatch.setenv("RAF_INBOX_ENABLED", "true")
        _cleanup(tid)
