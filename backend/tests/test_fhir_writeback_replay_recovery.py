"""Replay-loop recovery test for fhir_writeback_async.

Covers the round-12/13 fix: when celery `.delay()` raises mid-loop, the
row must be flipped back from 'pending' to 'failed' via
`mark_writeback_failed` so subsequent replays still see it. Also covers
the celery-import-failure early-return path (no DB mutations).

Pure-unit — calls `replay_failed` as a plain function with stubbed deps;
no TestClient, no live DB.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch


def _call_replay(current_user: dict, tenant_id: str = "1"):
    from app.routers.fhir_writeback_async import replay_failed
    return replay_failed(current_user=current_user, tenant_id=tenant_id)


def test_enqueue_failure_restores_failed_status() -> None:
    failed_rows = [{"id": 7, "patient_id": 1, "suspect_icd10": "E11.9"}]
    fake_task = MagicMock()
    fake_task.delay.side_effect = RuntimeError("broker unreachable")
    fake_celery_mod = MagicMock(task_fhir_writeback_async=fake_task)

    with (
        patch("app.routers.fhir_writeback_async.svc.list_failed_writebacks",
              return_value=failed_rows),
        patch("app.routers.fhir_writeback_async.svc.mark_writeback_pending") as mp,
        patch("app.routers.fhir_writeback_async.svc.mark_writeback_failed") as mf,
        patch.dict("sys.modules", {"app.services.celery_tasks": fake_celery_mod}),
    ):
        body = _call_replay({"id": 1, "role": "admin"})

    assert body == {"replayed_count": 0, "skipped_count": 1, "failed_total": 1}
    mp.assert_called_once_with(tenant_id="1", suspect_id=7)
    mf.assert_called_once()
    kwargs = mf.call_args.kwargs
    assert kwargs["tenant_id"] == "1"
    assert kwargs["suspect_id"] == 7
    assert "broker unreachable" in kwargs["error"]


def test_celery_import_failure_returns_early_without_db_mutation() -> None:
    failed_rows = [{"id": 9, "patient_id": 2, "suspect_icd10": "I10"}]
    real_import = __builtins__["__import__"] if isinstance(__builtins__, dict) else __builtins__.__import__

    def _raising_import(name, *args, **kwargs):
        if name == "app.services.celery_tasks":
            raise ImportError("celery not installed")
        return real_import(name, *args, **kwargs)

    with (
        patch("app.routers.fhir_writeback_async.svc.list_failed_writebacks",
              return_value=failed_rows),
        patch("app.routers.fhir_writeback_async.svc.mark_writeback_pending") as mp,
        patch("app.routers.fhir_writeback_async.svc.mark_writeback_failed") as mf,
        patch("builtins.__import__", side_effect=_raising_import),
    ):
        body = _call_replay({"id": 1, "role": "admin"})

    assert body == {"replayed_count": 0, "skipped_count": 1, "failed_total": 1}
    # No DB mutations on the celery-unavailable path
    mp.assert_not_called()
    mf.assert_not_called()


def test_status_restore_failure_does_not_abort_loop() -> None:
    """Warning-5 fix: if mark_writeback_failed itself raises, the loop must
    still process the remaining rows and return a valid response."""
    failed_rows = [
        {"id": 1, "patient_id": 1, "suspect_icd10": "E11.9"},
        {"id": 2, "patient_id": 2, "suspect_icd10": "I10"},
    ]
    fake_task = MagicMock()
    fake_task.delay.side_effect = RuntimeError("broker down")
    fake_celery_mod = MagicMock(task_fhir_writeback_async=fake_task)

    with (
        patch("app.routers.fhir_writeback_async.svc.list_failed_writebacks",
              return_value=failed_rows),
        patch("app.routers.fhir_writeback_async.svc.mark_writeback_pending"),
        patch("app.routers.fhir_writeback_async.svc.mark_writeback_failed",
              side_effect=RuntimeError("DB unreachable")),
        patch.dict("sys.modules", {"app.services.celery_tasks": fake_celery_mod}),
    ):
        # Must not raise — every row counted as skipped, response returned
        body = _call_replay({"id": 1, "role": "admin"})

    assert body == {"replayed_count": 0, "skipped_count": 2, "failed_total": 2}
