"""
Unit tests for phi_access_logger and audit_middleware.

All DB calls are patched out — these tests run without a live MySQL server.
"""
from __future__ import annotations

import queue
import time
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _drain(flush_fn):
    """Call the flush helper and give the worker a moment to settle."""
    flush_fn()
    time.sleep(0.05)


# ---------------------------------------------------------------------------
# phi_access_logger tests
# ---------------------------------------------------------------------------

class TestPhiEnqueue:
    def test_enqueue_increments_pending(self):
        from app.phi_access_logger import _enqueue, _metrics, _record_queue

        before = _record_queue.qsize()
        _enqueue({"user_id": "1", "action": "READ", "resource_type": "patient"})
        assert _record_queue.qsize() == before + 1
        # drain so we don't pollute other tests
        try:
            _record_queue.get_nowait()
            _metrics["phi_access_log_pending"] = max(0, _metrics["phi_access_log_pending"] - 1)
        except queue.Empty:
            pass

    def test_queue_full_increments_dropped(self, monkeypatch):
        from app import phi_access_logger as mod

        monkeypatch.setattr(mod, "_record_queue", queue.Queue(maxsize=1))
        mod._record_queue.put_nowait({"sentinel": True})  # fill it

        before_dropped = mod._metrics["phi_access_log_dropped"]
        mod._enqueue({"user_id": "x"})
        assert mod._metrics["phi_access_log_dropped"] == before_dropped + 1


class TestFlushPending:
    def test_flush_writes_to_db(self):
        from app.phi_access_logger import _enqueue, _flush_pending

        mock_cur = MagicMock()
        mock_cur.__enter__ = MagicMock(return_value=mock_cur)
        mock_cur.__exit__ = MagicMock(return_value=False)

        with patch("app.phi_access_logger._write_to_db", return_value=True) as mock_db:
            _enqueue({"user_id": "u1", "action": "READ", "resource_type": "patient",
                      "timestamp": "2024-01-01T00:00:00+00:00"})
            _flush_pending()
            # DB write should have been attempted
            assert mock_db.call_count >= 1

    def test_flush_falls_back_to_overflow_on_db_failure(self, tmp_path, monkeypatch):
        from app import phi_access_logger as mod

        overflow = tmp_path / "overflow.jsonl"
        monkeypatch.setattr(mod, "_OVERFLOW_PATH", overflow)

        with patch.object(mod, "_write_to_db", return_value=False):
            mod._enqueue({"user_id": "u2", "action": "READ", "resource_type": "patient",
                          "timestamp": "2024-01-01T00:00:00+00:00"})
            mod._flush_pending()

        assert overflow.exists(), "Overflow file should be created on DB failure"
        lines = overflow.read_text().strip().splitlines()
        assert len(lines) >= 1
        import json
        obj = json.loads(lines[0])
        assert obj["user_id"] == "u2"


class TestDirectCallApi:
    """log_phi_access() called with kwargs should enqueue immediately (no FastAPI request)."""

    def test_direct_call_enqueues(self):
        from app.phi_access_logger import _record_queue, log_phi_access

        before = _record_queue.qsize()
        result = log_phi_access(user_id=99, patient_id=42, action="read",
                                resource="patient", tenant_id=7)
        assert result is None  # direct-call path returns None, not a dependency
        assert _record_queue.qsize() == before + 1

    def test_direct_call_flush_ok(self):
        """Verify script from task description works end-to-end (DB patched)."""
        from app.phi_access_logger import _flush_pending, log_phi_access

        with patch("app.phi_access_logger._write_to_db", return_value=True):
            log_phi_access(user_id=1, patient_id=1, action="read",
                           resource="test", tenant_id=1)
            _flush_pending()
        # No exception == pass


class TestPhiMetrics:
    def test_phi_metrics_returns_dict(self):
        from app.phi_access_logger import phi_metrics

        m = phi_metrics()
        assert "phi_access_log_pending" in m
        assert "phi_access_log_dropped" in m
        assert isinstance(m["phi_access_log_pending"], int)
        assert isinstance(m["phi_access_log_dropped"], int)


# ---------------------------------------------------------------------------
# audit_middleware tests
# ---------------------------------------------------------------------------

class TestAuditMiddlewareHook:
    def setup_method(self):
        from app.audit_middleware import reset_audit_counter
        reset_audit_counter()

    def test_counter_starts_at_zero(self):
        from app.audit_middleware import get_audit_counter
        assert get_audit_counter() == 0

    def test_record_audit_entry_increments(self):
        from app.audit_middleware import _record_audit_entry, get_audit_counter
        _record_audit_entry()
        _record_audit_entry()
        assert get_audit_counter() == 2

    def test_reset_clears_counter(self):
        from app.audit_middleware import _record_audit_entry, get_audit_counter, reset_audit_counter
        _record_audit_entry()
        reset_audit_counter()
        assert get_audit_counter() == 0

    @pytest.mark.asyncio
    async def test_middleware_increments_on_authed_patient_route(self):
        """Middleware increments counter when Authorization + patient path present."""
        from app.audit_middleware import AuditRequestContextMiddleware, get_audit_counter

        async def dummy_app(scope, receive, send):
            pass

        middleware = AuditRequestContextMiddleware(dummy_app)

        scope = {
            "type": "http",
            "method": "GET",
            "path": "/api/patients/123/raf",
            "client": ("127.0.0.1", 9000),
            "headers": [
                (b"authorization", b"Bearer sometoken"),
                (b"user-agent", b"pytest"),
            ],
        }
        await middleware(scope, None, None)
        assert get_audit_counter() == 1

    @pytest.mark.asyncio
    async def test_middleware_does_not_increment_unauthenticated(self):
        """No Authorization header — counter stays at 0."""
        from app.audit_middleware import AuditRequestContextMiddleware, get_audit_counter

        async def dummy_app(scope, receive, send):
            pass

        middleware = AuditRequestContextMiddleware(dummy_app)

        scope = {
            "type": "http",
            "method": "GET",
            "path": "/api/patients/123",
            "client": ("127.0.0.1", 9000),
            "headers": [],
        }
        await middleware(scope, None, None)
        assert get_audit_counter() == 0
