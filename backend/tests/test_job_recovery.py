"""Tests for recover_stale_jobs in app.services.job_service."""

from __future__ import annotations

from contextlib import contextmanager

import pytest

from app.services import job_service


class FakeCursor:
    """Records execute() calls and returns a configurable rowcount."""

    def __init__(self, rowcount: int | None = 0) -> None:
        self.rowcount = rowcount
        self.calls: list[tuple[str, tuple]] = []

    def execute(self, sql: str, params: tuple = ()) -> None:
        self.calls.append((sql, params))


def _install_fake_cursor(monkeypatch: pytest.MonkeyPatch, cur: FakeCursor) -> None:
    @contextmanager
    def fake_raf_cursor():
        yield cur

    # recover_stale_jobs does `from app.db import raf_cursor` inside the
    # function, so patch the source module.
    import app.db as db_module

    monkeypatch.setattr(db_module, "raf_cursor", fake_raf_cursor)


def test_recover_stale_jobs_where_clause_includes_all_states(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cur = FakeCursor(rowcount=0)
    _install_fake_cursor(monkeypatch, cur)

    job_service.recover_stale_jobs(stale_after_hours=1)

    assert len(cur.calls) == 1
    sql, _ = cur.calls[0]
    for state in ("QUEUED", "RUNNING", "PENDING", "STARTED", "PROGRESS"):
        assert state in sql, f"expected state {state!r} in WHERE clause"
    assert "UPDATE raf_jobs" in sql
    assert "FAILED" in sql
    assert "INTERVAL" in sql and "HOUR" in sql


def test_recover_stale_jobs_passes_interval_param(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cur = FakeCursor(rowcount=0)
    _install_fake_cursor(monkeypatch, cur)

    job_service.recover_stale_jobs(stale_after_hours=6)

    _, params = cur.calls[0]
    assert params == (6,)


def test_recover_stale_jobs_returns_rowcount(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cur = FakeCursor(rowcount=7)
    _install_fake_cursor(monkeypatch, cur)

    result = job_service.recover_stale_jobs(stale_after_hours=1)

    assert result == 7


def test_recover_stale_jobs_returns_zero_when_rowcount_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cur = FakeCursor(rowcount=None)
    _install_fake_cursor(monkeypatch, cur)

    result = job_service.recover_stale_jobs(stale_after_hours=2)

    assert result == 0
