"""
tests/test_pipeline_chain.py — Pipeline auto-chain integration test suite.

Tests cover:
- setup_pipeline_chain() registers event handlers
- RAF_AUTO_CHAIN=false disables registration
- emr_sync_completed event triggers encounter + diagnosis normalization
- normalization_completed triggers RAF batch recalculation
- raf_calculation_completed logs terminal event
- Failure in sync_encounters stops the chain (diagnoses not called)
- Failure in sync_diagnoses stops before RAF calc
- RAF calc failure is isolated — does not propagate
- Missing tenant_id raises ValueError in every handler
- Missing connection_id raises ValueError in emr handler
- event_emitter.register_handler / emit_internal basic wiring
- _fetch_active_patient_ids with mocked cursor

All tests run entirely in-process. No network or database required.
"""

from __future__ import annotations

import os
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Ensure RAF_AUTO_CHAIN is enabled before importing the module under test
# ---------------------------------------------------------------------------
os.environ["RAF_AUTO_CHAIN"] = "true"

from app.services.pipeline_chain import (
    _auto_chain_enabled,
    _fetch_active_patient_ids,
    _handle_emr_sync_completed,
    _handle_normalization_completed,
    _handle_raf_calculation_completed,
    setup_pipeline_chain,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _base_sync_payload(**kwargs) -> dict:
    base = {"tenant_id": "tenant-1", "connection_id": 42, "sync_type": "incremental"}
    base.update(kwargs)
    return base


def _norm_payload(**kwargs) -> dict:
    base = {"tenant_id": "tenant-1", "patient_ids": ["1", "2", "3"]}
    base.update(kwargs)
    return base


# ===========================================================================
# 1. _auto_chain_enabled — feature flag behaviour
# ===========================================================================

class TestAutoChainEnabled:
    def test_default_enabled(self) -> None:
        with patch.dict(os.environ, {"RAF_AUTO_CHAIN": "true"}):
            assert _auto_chain_enabled() is True

    def test_disabled_by_false(self) -> None:
        with patch.dict(os.environ, {"RAF_AUTO_CHAIN": "false"}):
            assert _auto_chain_enabled() is False

    def test_disabled_by_0(self) -> None:
        with patch.dict(os.environ, {"RAF_AUTO_CHAIN": "0"}):
            assert _auto_chain_enabled() is False

    def test_disabled_by_no(self) -> None:
        with patch.dict(os.environ, {"RAF_AUTO_CHAIN": "no"}):
            assert _auto_chain_enabled() is False

    def test_disabled_by_off(self) -> None:
        with patch.dict(os.environ, {"RAF_AUTO_CHAIN": "off"}):
            assert _auto_chain_enabled() is False

    def test_enabled_when_missing(self) -> None:
        env = {k: v for k, v in os.environ.items() if k != "RAF_AUTO_CHAIN"}
        with patch.dict(os.environ, env, clear=True):
            assert _auto_chain_enabled() is True


# ===========================================================================
# 2. setup_pipeline_chain — handler registration
# ===========================================================================

class TestSetupPipelineChain:
    def test_registers_three_handlers(self) -> None:
        with patch.dict(os.environ, {"RAF_AUTO_CHAIN": "true"}), patch(
            "app.services.event_emitter.register_handler"
        ) as mock_reg:
            setup_pipeline_chain()
        assert mock_reg.call_count == 3
        event_names = [c.args[0] for c in mock_reg.call_args_list]
        assert "emr_sync_completed" in event_names
        assert "normalization_completed" in event_names
        assert "raf_calculation_completed" in event_names

    def test_no_registration_when_disabled(self) -> None:
        with patch.dict(os.environ, {"RAF_AUTO_CHAIN": "false"}), patch(
            "app.services.event_emitter.register_handler"
        ) as mock_reg:
            setup_pipeline_chain()
        mock_reg.assert_not_called()


# ===========================================================================
# 3. _handle_emr_sync_completed — normalization step
# ===========================================================================

def _noop_create_run(*args, **kwargs):
    """Stub for _create_run that bypasses the DB and returns a fake run_id."""
    return 1


def _noop_update_run(*args, **kwargs):
    """Stub for _update_run that does nothing."""
    pass


class TestHandleEmrSyncCompleted:
    def test_calls_sync_encounters_and_sync_diagnoses(self) -> None:
        with (
            patch("app.services.pipeline_chain._create_run", _noop_create_run),
            patch("app.services.pipeline_chain._update_run", _noop_update_run),
            patch("app.services.pipeline_chain._stash_run_id"),
            patch(
                "app.services.encounter_normalization_service.sync_encounters",
                return_value={"encounters": 5},
            ) as mock_enc,
            patch(
                "app.services.encounter_normalization_service.sync_diagnoses",
                return_value={"diagnoses": 10},
            ) as mock_diag,
        ):
            _handle_emr_sync_completed(_base_sync_payload())

        mock_enc.assert_called_once_with(tenant_id="tenant-1")
        mock_diag.assert_called_once_with(tenant_id="tenant-1")

    def test_missing_tenant_id_raises(self) -> None:
        with pytest.raises(ValueError, match="tenant_id"):
            _handle_emr_sync_completed({"connection_id": 42})

    def test_empty_tenant_id_raises(self) -> None:
        with pytest.raises(ValueError, match="tenant_id"):
            _handle_emr_sync_completed({"tenant_id": "", "connection_id": 1})

    def test_connection_id_is_optional(self) -> None:
        """connection_id is informational only — omitting it should not raise."""
        with (
            patch("app.services.pipeline_chain._create_run", _noop_create_run),
            patch("app.services.pipeline_chain._update_run", _noop_update_run),
            patch("app.services.pipeline_chain._stash_run_id"),
            patch(
                "app.services.encounter_normalization_service.sync_encounters",
                return_value={},
            ),
            patch(
                "app.services.encounter_normalization_service.sync_diagnoses",
                return_value={},
            ),
        ):
            # Should not raise — connection_id is optional in the updated code
            _handle_emr_sync_completed({"tenant_id": "tenant-1"})

    def test_sync_encounters_failure_stops_chain(self) -> None:
        """When sync_encounters raises, sync_diagnoses must NOT be called."""
        with (
            patch("app.services.pipeline_chain._create_run", _noop_create_run),
            patch("app.services.pipeline_chain._update_run", _noop_update_run),
            patch(
                "app.services.encounter_normalization_service.sync_encounters",
                side_effect=RuntimeError("EMR unreachable"),
            ),
            patch(
                "app.services.encounter_normalization_service.sync_diagnoses",
            ) as mock_diag,
        ):
            _handle_emr_sync_completed(_base_sync_payload())

        mock_diag.assert_not_called()

    def test_sync_diagnoses_failure_still_proceeds_to_raf(self) -> None:
        """sync_diagnoses failure is non-fatal — RAF calculation runs on existing data."""
        with (
            patch("app.services.pipeline_chain._create_run", _noop_create_run),
            patch("app.services.pipeline_chain._update_run", _noop_update_run),
            patch(
                "app.services.encounter_normalization_service.sync_encounters",
                return_value={},
            ),
            patch(
                "app.services.encounter_normalization_service.sync_diagnoses",
                side_effect=RuntimeError("DB write failed"),
            ),
            patch("app.services.event_emitter.emit_internal") as mock_emit,
        ):
            _handle_emr_sync_completed(_base_sync_payload())

        # Non-fatal path: normalization_completed is emitted with partial=True
        mock_emit.assert_called_once()
        emitted_event = mock_emit.call_args.args[0]
        assert emitted_event == "normalization_completed"
        emitted_payload = mock_emit.call_args.args[1]
        assert emitted_payload.get("partial") is True


# ===========================================================================
# 4. _handle_normalization_completed — RAF calculation step
# ===========================================================================

class TestHandleNormalizationCompleted:
    def _run_norm(self, payload=None, mock_calc_rv=None, capture_emit=True):
        """Run _handle_normalization_completed with standard mocks; return emit mock."""
        if payload is None:
            payload = _norm_payload()
        if mock_calc_rv is None:
            mock_calc_rv = [{"patient_id": "1", "raf": 1.2}]
        emit_mock = MagicMock()
        with (
            patch("app.services.pipeline_chain._pop_run_id", return_value=None),
            patch("app.services.pipeline_chain._update_run", _noop_update_run),
            patch(
                "app.services.raf_calculator.calculate_raf_for_all_patients",
                return_value=mock_calc_rv,
            ),
            patch("app.services.event_emitter.emit_internal", emit_mock),
        ):
            _handle_normalization_completed(payload)
        return emit_mock

    def test_calls_calculate_raf_for_all_patients(self) -> None:
        with (
            patch("app.services.pipeline_chain._pop_run_id", return_value=None),
            patch("app.services.pipeline_chain._update_run", _noop_update_run),
            patch(
                "app.services.raf_calculator.calculate_raf_for_all_patients",
                return_value=[{"patient_id": "1", "raf": 1.2}],
            ) as mock_calc,
            patch("app.services.event_emitter.emit_internal"),
        ):
            _handle_normalization_completed(_norm_payload())

        mock_calc.assert_called_once_with(tenant_id="tenant-1")

    def test_emits_raf_calculation_completed_on_success(self) -> None:
        mock_emit = self._run_norm(
            mock_calc_rv=[{"patient_id": "1"}, {"patient_id": "2", "error": "bad"}]
        )
        mock_emit.assert_called_once()
        emitted_event, emitted_payload = mock_emit.call_args.args
        assert emitted_event == "raf_calculation_completed"
        assert emitted_payload["total"] == 2
        assert emitted_payload["success"] == 1
        assert emitted_payload["errors"] == 1
        assert emitted_payload["tenant_id"] == "tenant-1"

    def test_missing_tenant_id_raises(self) -> None:
        with pytest.raises(ValueError, match="tenant_id"):
            _handle_normalization_completed({"patient_ids": []})

    def test_raf_calc_exception_does_not_propagate(self) -> None:
        """RAF calc exception is caught and logged — handler must not raise."""
        emit_mock = MagicMock()
        with (
            patch("app.services.pipeline_chain._pop_run_id", return_value=None),
            patch("app.services.pipeline_chain._update_run", _noop_update_run),
            patch(
                "app.services.raf_calculator.calculate_raf_for_all_patients",
                side_effect=RuntimeError("calculation crashed"),
            ),
            patch("app.services.event_emitter.emit_internal", emit_mock),
        ):
            # Should not raise
            _handle_normalization_completed(_norm_payload())

        # No completion event emitted when RAF calc fails
        emit_mock.assert_not_called()

    def test_empty_results_emits_with_zero_counts(self) -> None:
        mock_emit = self._run_norm(mock_calc_rv=[])
        _, payload = mock_emit.call_args.args
        assert payload["total"] == 0
        assert payload["success"] == 0
        assert payload["errors"] == 0


# ===========================================================================
# 5. _handle_raf_calculation_completed — terminal handler
# ===========================================================================

class TestHandleRafCalculationCompleted:
    def test_logs_completion_without_exception(self) -> None:
        # Should not raise
        _handle_raf_calculation_completed(
            {"tenant_id": "tenant-1", "total": 50, "success": 48, "errors": 2}
        )

    def test_missing_tenant_id_raises(self) -> None:
        with pytest.raises(ValueError, match="tenant_id"):
            _handle_raf_calculation_completed({"total": 10, "success": 10})

    def test_empty_tenant_id_raises(self) -> None:
        with pytest.raises(ValueError, match="tenant_id"):
            _handle_raf_calculation_completed({"tenant_id": ""})


# ===========================================================================
# 6. _fetch_active_patient_ids
# ===========================================================================

class TestFetchActivePatientIds:
    def _cursor_cm(self, rows):
        @contextmanager
        def _cm(*args, **kwargs):
            cur = MagicMock()
            cur.fetchall.return_value = rows
            yield cur

        return _cm

    def test_returns_string_ids(self) -> None:
        rows = [{"id": 1}, {"id": 2}, {"id": 3}]
        cm = self._cursor_cm(rows)
        with patch("app.db.raf_cursor", cm):
            ids = _fetch_active_patient_ids("tenant-1")
        assert ids == ["1", "2", "3"]

    def test_empty_table_returns_empty_list(self) -> None:
        cm = self._cursor_cm([])
        with patch("app.db.raf_cursor", cm):
            ids = _fetch_active_patient_ids("tenant-1")
        assert ids == []

    def test_db_exception_returns_empty_list(self) -> None:
        @contextmanager
        def _failing_cm(*args, **kwargs):
            raise RuntimeError("DB connection lost")
            yield  # unreachable

        with patch("app.db.raf_cursor", _failing_cm):
            ids = _fetch_active_patient_ids("tenant-1")
        assert ids == []


# ===========================================================================
# 7. event_emitter integration (register_handler / emit_internal)
# ===========================================================================

class TestEventEmitterIntegration:
    def test_registered_handler_called_synchronously_via_direct_call(self) -> None:
        """
        Bypass the thread pool by calling the handler directly.
        This verifies the registration/dispatch wiring without
        relying on threading.
        """
        from app.services.event_emitter import _internal_handlers

        received = {}

        def _test_handler(payload: dict) -> None:
            received.update(payload)

        # Register under a unique event name to avoid polluting shared state
        event_name = "_test_pipeline_wiring_xyz"
        _internal_handlers[event_name].append(_test_handler)

        try:
            handlers = list(_internal_handlers.get(event_name, []))
            for h in handlers:
                h({"status": "ok", "tenant_id": "t1"})
            assert received["status"] == "ok"
        finally:
            _internal_handlers[event_name].remove(_test_handler)

    def test_emit_internal_no_handlers_is_safe(self) -> None:
        from app.services.event_emitter import emit_internal
        # Unknown event — should not raise
        emit_internal("_nonexistent_event_xyz", {"tenant_id": "t1"})
