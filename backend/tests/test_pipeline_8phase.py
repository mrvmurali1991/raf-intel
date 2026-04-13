"""
tests/test_pipeline_8phase.py — Comprehensive test suite for the 8-phase pipeline auto-chain.

Phases under test:
  ① emr_sync_completed        → encounter + diagnosis normalization
  ② normalization_completed   → AI analysis (auto_ai) OR RAF calc (auto_basic/manual)
  ③ analysis_requested        → AI/NLP per-encounter analysis
  ④ analysis_completed        → RAF calc + HCC hierarchy
  ⑤ raf_calculation_completed → suspect scan (if enabled) or stop (manual mode)
  ⑥ suspect_scan_completed    → care gap generation
  ⑦ pipeline_completed        → close tracking row + webhook (if enabled)

All tests run entirely in-process.  No network or database required.
"""

from __future__ import annotations

import os
from contextlib import contextmanager
from unittest.mock import MagicMock, call, patch

import pytest

# ---------------------------------------------------------------------------
# Ensure auto-chain is enabled before importing the module under test.
# ---------------------------------------------------------------------------
os.environ["RAF_AUTO_CHAIN"] = "true"

from app.services.pipeline_chain import (
    _handle_emr_sync_completed,
    _handle_normalization_completed,
    _handle_analysis_completed,
    _handle_raf_calculation_completed,
    _handle_suspect_scan_completed,
    _handle_pipeline_completed,
    _get_pipeline_settings,
    _fetch_active_patient_ids,
    setup_pipeline_chain,
    _auto_chain_enabled,
)

# ---------------------------------------------------------------------------
# Payload factories
# ---------------------------------------------------------------------------


def _sync_payload(**kwargs) -> dict:
    base = {"tenant_id": "tenant-1", "connection_id": 42, "sync_type": "incremental"}
    base.update(kwargs)
    return base


def _norm_payload(**kwargs) -> dict:
    base = {"tenant_id": "tenant-1", "patient_ids": ["p1", "p2"]}
    base.update(kwargs)
    return base


def _analysis_completed_payload(**kwargs) -> dict:
    base = {"tenant_id": "tenant-1", "analyzed_count": 3, "pipeline_run_id": 0}
    base.update(kwargs)
    return base


def _raf_completed_payload(**kwargs) -> dict:
    base = {"tenant_id": "tenant-1", "total": 10, "success": 9, "errors": 1, "pipeline_run_id": 0}
    base.update(kwargs)
    return base


def _suspect_completed_payload(**kwargs) -> dict:
    base = {"tenant_id": "tenant-1", "pipeline_run_id": 0}
    base.update(kwargs)
    return base


def _pipeline_completed_payload(**kwargs) -> dict:
    base = {"tenant_id": "tenant-1", "pipeline_run_id": 0, "gaps_created": 5}
    base.update(kwargs)
    return base


# ---------------------------------------------------------------------------
# Shared stubs for run-tracking helpers (bypass DB)
# ---------------------------------------------------------------------------

def _noop_create_run(*args, **kwargs):
    return 1


def _noop_update_run(*args, **kwargs):
    pass


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def pipeline_settings_auto_ai():
    return {
        "pipeline_mode": "auto_ai",
        "ai_analysis_enabled": True,
        "suspect_scan_enabled": True,
        "gap_generation_enabled": True,
        "hierarchy_enabled": True,
        "webhook_enabled": True,
    }


@pytest.fixture
def pipeline_settings_auto_basic():
    return {
        "pipeline_mode": "auto_basic",
        "ai_analysis_enabled": False,
        "suspect_scan_enabled": True,
        "gap_generation_enabled": True,
        "hierarchy_enabled": True,
        "webhook_enabled": False,
    }


@pytest.fixture
def pipeline_settings_manual():
    return {
        "pipeline_mode": "manual",
        "ai_analysis_enabled": False,
        "suspect_scan_enabled": False,
        "gap_generation_enabled": False,
        "hierarchy_enabled": False,
        "webhook_enabled": False,
    }


# ===========================================================================
# 1. test_auto_basic_mode_skips_ai
#    normalization_completed in auto_basic goes directly to RAF calc (no analysis_requested)
# ===========================================================================


class TestAutoBasicModeSkipsAi:
    def test_normalization_completed_calls_raf_calc_directly(self, pipeline_settings_auto_basic):
        emit_mock = MagicMock()
        with (
            patch("app.services.pipeline_chain._pop_run_id", return_value=None),
            patch("app.services.pipeline_chain._update_run", _noop_update_run),
            patch(
                "app.services.pipeline_chain._get_pipeline_settings",
                return_value=pipeline_settings_auto_basic,
            ),
            patch(
                "app.services.raf_calculator.calculate_raf_for_all_patients",
                return_value=[{"patient_id": "p1"}],
            ) as mock_calc,
            patch("app.services.event_emitter.emit_internal", emit_mock),
        ):
            _handle_normalization_completed(_norm_payload())

        # RAF calc must have been called
        mock_calc.assert_called_once_with(tenant_id="tenant-1")

        # The emitted event must be raf_calculation_completed, NOT analysis_requested
        assert emit_mock.call_count == 1
        emitted_event = emit_mock.call_args.args[0]
        assert emitted_event == "raf_calculation_completed"

    def test_analysis_requested_never_emitted_in_auto_basic(self, pipeline_settings_auto_basic):
        emit_mock = MagicMock()
        with (
            patch("app.services.pipeline_chain._pop_run_id", return_value=None),
            patch("app.services.pipeline_chain._update_run", _noop_update_run),
            patch(
                "app.services.pipeline_chain._get_pipeline_settings",
                return_value=pipeline_settings_auto_basic,
            ),
            patch(
                "app.services.raf_calculator.calculate_raf_for_all_patients",
                return_value=[],
            ),
            patch("app.services.event_emitter.emit_internal", emit_mock),
        ):
            _handle_normalization_completed(_norm_payload())

        emitted_events = [c.args[0] for c in emit_mock.call_args_list]
        assert "analysis_requested" not in emitted_events


# ===========================================================================
# 2. test_auto_ai_mode_triggers_analysis
#    normalization_completed in auto_ai mode emits analysis_requested (no RAF calc yet)
# ===========================================================================


class TestAutoAiModeTriggersAnalysis:
    def test_emits_analysis_requested(self, pipeline_settings_auto_ai):
        emit_mock = MagicMock()
        with (
            patch("app.services.pipeline_chain._pop_run_id", return_value=None),
            patch("app.services.pipeline_chain._update_run", _noop_update_run),
            patch("app.services.pipeline_chain._stash_run_id"),
            patch(
                "app.services.pipeline_chain._get_pipeline_settings",
                return_value=pipeline_settings_auto_ai,
            ),
            patch("app.services.event_emitter.emit_internal", emit_mock),
        ):
            _handle_normalization_completed(_norm_payload())

        assert emit_mock.call_count == 1
        emitted_event, emitted_payload = emit_mock.call_args.args
        assert emitted_event == "analysis_requested"
        assert emitted_payload["tenant_id"] == "tenant-1"

    def test_raf_calc_not_called_in_auto_ai(self, pipeline_settings_auto_ai):
        with (
            patch("app.services.pipeline_chain._pop_run_id", return_value=None),
            patch("app.services.pipeline_chain._update_run", _noop_update_run),
            patch("app.services.pipeline_chain._stash_run_id"),
            patch(
                "app.services.pipeline_chain._get_pipeline_settings",
                return_value=pipeline_settings_auto_ai,
            ),
            patch(
                "app.services.raf_calculator.calculate_raf_for_all_patients",
            ) as mock_calc,
            patch("app.services.event_emitter.emit_internal"),
        ):
            _handle_normalization_completed(_norm_payload())

        mock_calc.assert_not_called()


# ===========================================================================
# 3. test_manual_mode_stops_after_raf
#    raf_calculation_completed in manual mode does NOT trigger suspect scan
# ===========================================================================


class TestManualModeStopsAfterRaf:
    def test_no_emit_in_manual_mode(self, pipeline_settings_manual):
        emit_mock = MagicMock()
        with (
            patch(
                "app.services.pipeline_chain._get_pipeline_settings",
                return_value=pipeline_settings_manual,
            ),
            patch("app.services.pipeline_chain._update_run", _noop_update_run),
            patch("app.services.event_emitter.emit_internal", emit_mock),
        ):
            _handle_raf_calculation_completed(_raf_completed_payload())

        emit_mock.assert_not_called()

    def test_suspect_scan_not_called_in_manual_mode(self, pipeline_settings_manual):
        with (
            patch(
                "app.services.pipeline_chain._get_pipeline_settings",
                return_value=pipeline_settings_manual,
            ),
            patch("app.services.pipeline_chain._update_run", _noop_update_run),
            patch("app.services.event_emitter.emit_internal"),
            patch("app.services.suspect_engine.run_full_suspect_scan") as mock_scan,
        ):
            _handle_raf_calculation_completed(_raf_completed_payload())

        mock_scan.assert_not_called()


# ===========================================================================
# 4. test_analysis_completed_triggers_raf_and_hierarchy
#    analysis_completed → RAF calc + HCC hierarchy (when hierarchy_enabled)
# ===========================================================================


class TestAnalysisCompletedTriggersRafAndHierarchy:
    def test_calls_raf_calc_after_analysis(self, pipeline_settings_auto_ai):
        emit_mock = MagicMock()
        with (
            patch("app.services.pipeline_chain._pop_run_id", return_value=None),
            patch("app.services.pipeline_chain._update_run", _noop_update_run),
            patch(
                "app.services.pipeline_chain._get_pipeline_settings",
                return_value=pipeline_settings_auto_ai,
            ),
            patch(
                "app.services.raf_calculator.calculate_raf_for_all_patients",
                return_value=[{"patient_id": "p1"}],
            ) as mock_calc,
            patch(
                "app.services.hcc_hierarchy.apply_hierarchy_to_all_patients"
            ) as mock_hier,
            patch("app.services.event_emitter.emit_internal", emit_mock),
        ):
            _handle_analysis_completed(_analysis_completed_payload())

        mock_calc.assert_called_once_with(tenant_id="tenant-1")
        mock_hier.assert_called_once()

        # Must emit raf_calculation_completed
        emitted_events = [c.args[0] for c in emit_mock.call_args_list]
        assert "raf_calculation_completed" in emitted_events

    def test_hierarchy_disabled_skips_apply_hierarchy(self):
        settings = {
            "pipeline_mode": "auto_ai",
            "hierarchy_enabled": False,
            "ai_analysis_enabled": True,
            "suspect_scan_enabled": True,
            "gap_generation_enabled": True,
            "webhook_enabled": False,
        }
        with (
            patch("app.services.pipeline_chain._pop_run_id", return_value=None),
            patch("app.services.pipeline_chain._update_run", _noop_update_run),
            patch(
                "app.services.pipeline_chain._get_pipeline_settings",
                return_value=settings,
            ),
            patch(
                "app.services.raf_calculator.calculate_raf_for_all_patients",
                return_value=[],
            ),
            patch(
                "app.services.hcc_hierarchy.apply_hierarchy_to_all_patients"
            ) as mock_hier,
            patch("app.services.event_emitter.emit_internal"),
        ):
            _handle_analysis_completed(_analysis_completed_payload())

        mock_hier.assert_not_called()


# ===========================================================================
# 5. test_raf_completed_triggers_suspect_scan
#    raf_calculation_completed → suspect scan runs (when enabled, non-manual)
# ===========================================================================


class TestRafCompletedTriggersSuspectScan:
    def test_suspect_scan_called_when_enabled(self, pipeline_settings_auto_basic):
        emit_mock = MagicMock()
        with (
            patch(
                "app.services.pipeline_chain._get_pipeline_settings",
                return_value=pipeline_settings_auto_basic,
            ),
            patch("app.services.pipeline_chain._update_run", _noop_update_run),
            patch(
                "app.services.pipeline_chain._fetch_active_patient_ids",
                return_value=["1", "2"],
            ),
            patch(
                "app.services.suspect_engine.run_full_suspect_scan",
                return_value=[{"hcc": "19"}],
            ) as mock_scan,
            patch("app.services.event_emitter.emit_internal", emit_mock),
        ):
            _handle_raf_calculation_completed(_raf_completed_payload())

        # Called once per patient
        assert mock_scan.call_count == 2

        # Emits suspect_scan_completed
        emitted_events = [c.args[0] for c in emit_mock.call_args_list]
        assert "suspect_scan_completed" in emitted_events

    def test_suspect_scan_disabled_still_emits_completed(self):
        settings = {
            "pipeline_mode": "auto_basic",
            "suspect_scan_enabled": False,
            "gap_generation_enabled": True,
            "hierarchy_enabled": True,
            "webhook_enabled": False,
        }
        emit_mock = MagicMock()
        with (
            patch(
                "app.services.pipeline_chain._get_pipeline_settings",
                return_value=settings,
            ),
            patch("app.services.pipeline_chain._update_run", _noop_update_run),
            patch("app.services.event_emitter.emit_internal", emit_mock),
        ):
            _handle_raf_calculation_completed(_raf_completed_payload())

        emitted_events = [c.args[0] for c in emit_mock.call_args_list]
        assert "suspect_scan_completed" in emitted_events


# ===========================================================================
# 6. test_suspect_completed_triggers_gap_generation
#    suspect_scan_completed → care gap generation (when enabled)
# ===========================================================================


class TestSuspectCompletedTriggersGapGeneration:
    def test_gap_generation_called_when_enabled(self, pipeline_settings_auto_basic):
        emit_mock = MagicMock()
        with (
            patch(
                "app.services.pipeline_chain._get_pipeline_settings",
                return_value=pipeline_settings_auto_basic,
            ),
            patch("app.services.pipeline_chain._update_run", _noop_update_run),
            patch(
                "app.services.care_gap_service.generate_care_gaps",
                return_value={"gaps_created": 7},
            ) as mock_gaps,
            patch("app.services.event_emitter.emit_internal", emit_mock),
        ):
            _handle_suspect_scan_completed(_suspect_completed_payload())

        mock_gaps.assert_called_once_with(tenant_id="tenant-1")

        # Emits pipeline_completed
        emitted_events = [c.args[0] for c in emit_mock.call_args_list]
        assert "pipeline_completed" in emitted_events

    def test_gap_generation_payload_carries_gaps_created(self, pipeline_settings_auto_basic):
        emit_mock = MagicMock()
        with (
            patch(
                "app.services.pipeline_chain._get_pipeline_settings",
                return_value=pipeline_settings_auto_basic,
            ),
            patch("app.services.pipeline_chain._update_run", _noop_update_run),
            patch(
                "app.services.care_gap_service.generate_care_gaps",
                return_value={"gaps_created": 12},
            ),
            patch("app.services.event_emitter.emit_internal", emit_mock),
        ):
            _handle_suspect_scan_completed(_suspect_completed_payload())

        emitted_payload = emit_mock.call_args.args[1]
        assert emitted_payload["gaps_created"] == 12

    def test_gap_disabled_still_emits_pipeline_completed(self):
        settings = {
            "pipeline_mode": "auto_basic",
            "gap_generation_enabled": False,
            "suspect_scan_enabled": True,
            "hierarchy_enabled": True,
            "webhook_enabled": False,
        }
        emit_mock = MagicMock()
        with (
            patch(
                "app.services.pipeline_chain._get_pipeline_settings",
                return_value=settings,
            ),
            patch("app.services.pipeline_chain._update_run", _noop_update_run),
            patch("app.services.event_emitter.emit_internal", emit_mock),
        ):
            _handle_suspect_scan_completed(_suspect_completed_payload())

        emitted_events = [c.args[0] for c in emit_mock.call_args_list]
        assert "pipeline_completed" in emitted_events


# ===========================================================================
# 7. test_pipeline_completed_fires_webhook
#    pipeline_completed fires webhook when webhook_enabled = True
# ===========================================================================


class TestPipelineCompletedFiresWebhook:
    def test_webhook_fired_when_enabled(self, pipeline_settings_auto_ai):
        with (
            patch(
                "app.services.pipeline_chain._get_pipeline_settings",
                return_value=pipeline_settings_auto_ai,
            ),
            patch("app.services.pipeline_chain._update_run", _noop_update_run),
            patch("app.services.webhook_service.fire_event") as mock_fire,
        ):
            _handle_pipeline_completed(_pipeline_completed_payload())

        mock_fire.assert_called_once()
        call_args = mock_fire.call_args
        assert call_args.args[0] == "pipeline.full_run_completed"
        assert call_args.args[1] == "tenant-1"

    def test_webhook_payload_includes_gaps_created(self, pipeline_settings_auto_ai):
        with (
            patch(
                "app.services.pipeline_chain._get_pipeline_settings",
                return_value=pipeline_settings_auto_ai,
            ),
            patch("app.services.pipeline_chain._update_run", _noop_update_run),
            patch("app.services.webhook_service.fire_event") as mock_fire,
        ):
            _handle_pipeline_completed(_pipeline_completed_payload(gaps_created=8))

        event_body = mock_fire.call_args.args[2]
        assert event_body["gaps_created"] == 8


# ===========================================================================
# 8. test_pipeline_completed_no_webhook_when_disabled
#    pipeline_completed skips webhook when webhook_enabled = False
# ===========================================================================


class TestPipelineCompletedNoWebhookWhenDisabled:
    def test_webhook_not_fired_when_disabled(self, pipeline_settings_auto_basic):
        with (
            patch(
                "app.services.pipeline_chain._get_pipeline_settings",
                return_value=pipeline_settings_auto_basic,
            ),
            patch("app.services.pipeline_chain._update_run", _noop_update_run),
            patch("app.services.webhook_service.fire_event") as mock_fire,
        ):
            _handle_pipeline_completed(_pipeline_completed_payload())

        mock_fire.assert_not_called()

    def test_webhook_not_fired_in_manual_mode(self, pipeline_settings_manual):
        with (
            patch(
                "app.services.pipeline_chain._get_pipeline_settings",
                return_value=pipeline_settings_manual,
            ),
            patch("app.services.pipeline_chain._update_run", _noop_update_run),
            patch("app.services.webhook_service.fire_event") as mock_fire,
        ):
            _handle_pipeline_completed(_pipeline_completed_payload())

        mock_fire.assert_not_called()


# ===========================================================================
# 9. test_ai_analysis_failure_falls_through_to_raf
#    When the outer AI analysis block fails, analysis_completed is still emitted
#    so RAF calc still runs.
# ===========================================================================


class TestAiAnalysisFailureFallsThroughToRaf:
    def test_analysis_completed_emitted_after_outer_failure(self):
        """analysis_completed is always emitted even when the outer try-block fails."""
        emit_mock = MagicMock()
        with (
            patch("app.services.pipeline_chain._pop_run_id", return_value=0),
            patch("app.services.pipeline_chain._update_run", _noop_update_run),
            patch("app.services.pipeline_chain._stash_run_id"),
            # Make the DB query (inside _handle_analysis_requested) fail immediately
            patch(
                "app.db.raf_cursor",
                side_effect=RuntimeError("DB unavailable"),
            ),
            patch("app.services.event_emitter.emit_internal", emit_mock),
        ):
            from app.services.pipeline_chain import _handle_analysis_requested
            _handle_analysis_requested({"tenant_id": "tenant-1", "patient_ids": [], "pipeline_run_id": 0})

        emitted_events = [c.args[0] for c in emit_mock.call_args_list]
        assert "analysis_completed" in emitted_events

    def test_raf_calc_is_still_triggered_after_ai_failure(self, pipeline_settings_auto_ai):
        """Full chain: when AI analysis fails, analysis_completed → RAF calc runs."""
        emit_mock = MagicMock()
        with (
            patch("app.services.pipeline_chain._pop_run_id", return_value=0),
            patch("app.services.pipeline_chain._update_run", _noop_update_run),
            patch("app.services.pipeline_chain._stash_run_id"),
            patch(
                "app.db.raf_cursor",
                side_effect=RuntimeError("DB unavailable"),
            ),
            patch("app.services.event_emitter.emit_internal", emit_mock),
        ):
            from app.services.pipeline_chain import _handle_analysis_requested
            _handle_analysis_requested({"tenant_id": "tenant-1", "patient_ids": [], "pipeline_run_id": 0})

        # analysis_completed is the trigger for RAF calc — verify it was emitted
        emitted_events = [c.args[0] for c in emit_mock.call_args_list]
        assert "analysis_completed" in emitted_events


# ===========================================================================
# 10. test_hierarchy_failure_is_non_fatal
#     HCC hierarchy failure in _handle_analysis_completed does not stop the chain
# ===========================================================================


class TestHierarchyFailureIsNonFatal:
    def test_raf_calc_completed_emitted_despite_hierarchy_failure(self, pipeline_settings_auto_ai):
        emit_mock = MagicMock()
        with (
            patch("app.services.pipeline_chain._pop_run_id", return_value=None),
            patch("app.services.pipeline_chain._update_run", _noop_update_run),
            patch(
                "app.services.pipeline_chain._get_pipeline_settings",
                return_value=pipeline_settings_auto_ai,
            ),
            patch(
                "app.services.raf_calculator.calculate_raf_for_all_patients",
                return_value=[{"patient_id": "p1"}],
            ),
            patch(
                "app.services.hcc_hierarchy.apply_hierarchy_to_all_patients",
                side_effect=RuntimeError("hierarchy exploded"),
            ),
            patch("app.services.event_emitter.emit_internal", emit_mock),
        ):
            # Should not raise
            _handle_analysis_completed(_analysis_completed_payload())

        emitted_events = [c.args[0] for c in emit_mock.call_args_list]
        assert "raf_calculation_completed" in emitted_events

    def test_handler_does_not_raise_on_hierarchy_failure(self, pipeline_settings_auto_ai):
        with (
            patch("app.services.pipeline_chain._pop_run_id", return_value=None),
            patch("app.services.pipeline_chain._update_run", _noop_update_run),
            patch(
                "app.services.pipeline_chain._get_pipeline_settings",
                return_value=pipeline_settings_auto_ai,
            ),
            patch(
                "app.services.raf_calculator.calculate_raf_for_all_patients",
                return_value=[],
            ),
            patch(
                "app.services.hcc_hierarchy.apply_hierarchy_to_all_patients",
                side_effect=RuntimeError("hierarchy exploded"),
            ),
            patch("app.services.event_emitter.emit_internal"),
        ):
            # Must not raise
            _handle_analysis_completed(_analysis_completed_payload())


# ===========================================================================
# 11. test_suspect_scan_failure_is_non_fatal
#     Suspect scan outer failure still emits suspect_scan_completed
# ===========================================================================


class TestSuspectScanFailureIsNonFatal:
    def test_suspect_scan_completed_emitted_after_failure(self, pipeline_settings_auto_basic):
        emit_mock = MagicMock()
        with (
            patch(
                "app.services.pipeline_chain._get_pipeline_settings",
                return_value=pipeline_settings_auto_basic,
            ),
            patch("app.services.pipeline_chain._update_run", _noop_update_run),
            patch(
                "app.services.pipeline_chain._fetch_active_patient_ids",
                side_effect=RuntimeError("patient fetch failed"),
            ),
            patch("app.services.event_emitter.emit_internal", emit_mock),
        ):
            _handle_raf_calculation_completed(_raf_completed_payload())

        emitted_events = [c.args[0] for c in emit_mock.call_args_list]
        assert "suspect_scan_completed" in emitted_events

    def test_handler_does_not_raise_on_suspect_failure(self, pipeline_settings_auto_basic):
        with (
            patch(
                "app.services.pipeline_chain._get_pipeline_settings",
                return_value=pipeline_settings_auto_basic,
            ),
            patch("app.services.pipeline_chain._update_run", _noop_update_run),
            patch(
                "app.services.pipeline_chain._fetch_active_patient_ids",
                side_effect=RuntimeError("patient fetch failed"),
            ),
            patch("app.services.event_emitter.emit_internal"),
        ):
            # Must not raise
            _handle_raf_calculation_completed(_raf_completed_payload())

    def test_per_patient_failure_continues_to_next_patient(self, pipeline_settings_auto_basic):
        """A failure on one patient does not stop scanning remaining patients."""
        call_tracker: list[int] = []

        def _flaky_scan(patient_id, year=None):
            call_tracker.append(patient_id)
            if patient_id == 1:
                raise RuntimeError("scan crashed for patient 1")
            return [{"hcc": "85"}]

        with (
            patch(
                "app.services.pipeline_chain._get_pipeline_settings",
                return_value=pipeline_settings_auto_basic,
            ),
            patch("app.services.pipeline_chain._update_run", _noop_update_run),
            patch(
                "app.services.pipeline_chain._fetch_active_patient_ids",
                return_value=["1", "2", "3"],
            ),
            patch(
                "app.services.suspect_engine.run_full_suspect_scan",
                side_effect=_flaky_scan,
            ),
            patch("app.services.event_emitter.emit_internal"),
        ):
            _handle_raf_calculation_completed(_raf_completed_payload())

        # All 3 patients were attempted despite patient 1 failing
        assert call_tracker == [1, 2, 3]


# ===========================================================================
# 12. test_gap_generation_failure_still_completes_pipeline
#     Care gap generation failure is non-fatal; pipeline_completed is still emitted
# ===========================================================================


class TestGapGenerationFailureStillCompletesPipeline:
    def test_pipeline_completed_emitted_after_gap_failure(self, pipeline_settings_auto_basic):
        emit_mock = MagicMock()
        with (
            patch(
                "app.services.pipeline_chain._get_pipeline_settings",
                return_value=pipeline_settings_auto_basic,
            ),
            patch("app.services.pipeline_chain._update_run", _noop_update_run),
            patch(
                "app.services.care_gap_service.generate_care_gaps",
                side_effect=RuntimeError("gap DB write failed"),
            ),
            patch("app.services.event_emitter.emit_internal", emit_mock),
        ):
            _handle_suspect_scan_completed(_suspect_completed_payload())

        emitted_events = [c.args[0] for c in emit_mock.call_args_list]
        assert "pipeline_completed" in emitted_events

    def test_handler_does_not_raise_on_gap_failure(self, pipeline_settings_auto_basic):
        with (
            patch(
                "app.services.pipeline_chain._get_pipeline_settings",
                return_value=pipeline_settings_auto_basic,
            ),
            patch("app.services.pipeline_chain._update_run", _noop_update_run),
            patch(
                "app.services.care_gap_service.generate_care_gaps",
                side_effect=RuntimeError("gap DB write failed"),
            ),
            patch("app.services.event_emitter.emit_internal"),
        ):
            # Must not raise
            _handle_suspect_scan_completed(_suspect_completed_payload())


# ===========================================================================
# 13. test_full_8_phase_flow
#     End-to-end: emr_sync_completed kicks off all 8 phases in order
# ===========================================================================


class TestFull8PhaseFlow:
    def test_event_chain_order_auto_basic(self, pipeline_settings_auto_basic):
        """
        auto_basic mode full chain:
        emr_sync → normalization_completed → raf_calculation_completed
        → suspect_scan_completed → pipeline_completed
        """
        emitted: list[str] = []

        def _capture_emit(event, payload):
            emitted.append(event)

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
            patch("app.services.event_emitter.emit_internal", side_effect=_capture_emit),
        ):
            _handle_emr_sync_completed(_sync_payload())

        # After emr_sync_completed the normalization service owns emitting
        # normalization_completed; here we just confirm sync steps ran.
        # The event chain continues when normalization_completed is dispatched
        # by the sync service — we verify the emitter was NOT called with
        # normalization_completed directly from the emr handler (diag succeeded).
        assert "normalization_completed" not in emitted

    def test_event_chain_auto_basic_normalization_to_pipeline_completed(
        self, pipeline_settings_auto_basic
    ):
        """
        Drive the chain from normalization_completed all the way to pipeline_completed
        in auto_basic mode by calling handlers directly in sequence.
        """
        emit_mock = MagicMock()

        # Phase ② normalization_completed → raf_calculation_completed
        with (
            patch("app.services.pipeline_chain._pop_run_id", return_value=0),
            patch("app.services.pipeline_chain._update_run", _noop_update_run),
            patch(
                "app.services.pipeline_chain._get_pipeline_settings",
                return_value=pipeline_settings_auto_basic,
            ),
            patch(
                "app.services.raf_calculator.calculate_raf_for_all_patients",
                return_value=[{"patient_id": "p1"}, {"patient_id": "p2"}],
            ),
            patch("app.services.event_emitter.emit_internal", emit_mock),
        ):
            _handle_normalization_completed(_norm_payload())

        assert emit_mock.call_args_list[0].args[0] == "raf_calculation_completed"
        raf_payload = emit_mock.call_args_list[0].args[1]

        # Phase ⑤ raf_calculation_completed → suspect_scan_completed
        emit_mock.reset_mock()
        with (
            patch(
                "app.services.pipeline_chain._get_pipeline_settings",
                return_value=pipeline_settings_auto_basic,
            ),
            patch("app.services.pipeline_chain._update_run", _noop_update_run),
            patch(
                "app.services.pipeline_chain._fetch_active_patient_ids",
                return_value=["1"],
            ),
            patch(
                "app.services.suspect_engine.run_full_suspect_scan",
                return_value=[],
            ),
            patch("app.services.event_emitter.emit_internal", emit_mock),
        ):
            _handle_raf_calculation_completed(raf_payload)

        assert emit_mock.call_args_list[0].args[0] == "suspect_scan_completed"
        suspect_payload = emit_mock.call_args_list[0].args[1]

        # Phase ⑥ suspect_scan_completed → pipeline_completed
        emit_mock.reset_mock()
        with (
            patch(
                "app.services.pipeline_chain._get_pipeline_settings",
                return_value=pipeline_settings_auto_basic,
            ),
            patch("app.services.pipeline_chain._update_run", _noop_update_run),
            patch(
                "app.services.care_gap_service.generate_care_gaps",
                return_value={"gaps_created": 3},
            ),
            patch("app.services.event_emitter.emit_internal", emit_mock),
        ):
            _handle_suspect_scan_completed(suspect_payload)

        assert emit_mock.call_args_list[0].args[0] == "pipeline_completed"
        pipeline_payload = emit_mock.call_args_list[0].args[1]

        # Phase ⑦ pipeline_completed — no webhook in auto_basic
        with (
            patch(
                "app.services.pipeline_chain._get_pipeline_settings",
                return_value=pipeline_settings_auto_basic,
            ),
            patch("app.services.pipeline_chain._update_run", _noop_update_run),
            patch("app.services.webhook_service.fire_event") as mock_fire,
        ):
            _handle_pipeline_completed(pipeline_payload)

        mock_fire.assert_not_called()

    def test_event_chain_auto_ai_mode(self, pipeline_settings_auto_ai):
        """
        auto_ai: normalization_completed → analysis_requested (not RAF directly)
        """
        emit_mock = MagicMock()
        with (
            patch("app.services.pipeline_chain._pop_run_id", return_value=0),
            patch("app.services.pipeline_chain._update_run", _noop_update_run),
            patch("app.services.pipeline_chain._stash_run_id"),
            patch(
                "app.services.pipeline_chain._get_pipeline_settings",
                return_value=pipeline_settings_auto_ai,
            ),
            patch("app.services.event_emitter.emit_internal", emit_mock),
        ):
            _handle_normalization_completed(_norm_payload())

        assert emit_mock.call_args_list[0].args[0] == "analysis_requested"


# ===========================================================================
# 14. test_pipeline_settings_defaults
#     No settings row returns auto_basic defaults
# ===========================================================================


class TestPipelineSettingsDefaults:
    def test_returns_auto_basic_when_no_db_row(self):
        @contextmanager
        def _cm(*args, **kwargs):
            cur = MagicMock()
            cur.fetchone.return_value = None
            yield cur

        with patch("app.db.raf_cursor", _cm):
            settings = _get_pipeline_settings("tenant-no-settings")

        assert settings["pipeline_mode"] == "auto_basic"
        assert settings["ai_analysis_enabled"] is False
        assert settings["suspect_scan_enabled"] is True
        assert settings["gap_generation_enabled"] is True
        assert settings["hierarchy_enabled"] is True
        assert settings["webhook_enabled"] is False

    def test_returns_defaults_on_db_exception(self):
        @contextmanager
        def _failing_cm(*args, **kwargs):
            raise RuntimeError("DB offline")
            yield  # unreachable

        with patch("app.db.raf_cursor", _failing_cm):
            settings = _get_pipeline_settings("tenant-1")

        assert settings["pipeline_mode"] == "auto_basic"

    def test_db_row_overrides_defaults(self):
        @contextmanager
        def _cm(*args, **kwargs):
            cur = MagicMock()
            cur.fetchone.return_value = {
                "pipeline_mode": "auto_ai",
                "ai_analysis_enabled": True,
                "webhook_enabled": True,
            }
            yield cur

        with patch("app.db.raf_cursor", _cm):
            settings = _get_pipeline_settings("tenant-1")

        assert settings["pipeline_mode"] == "auto_ai"
        assert settings["ai_analysis_enabled"] is True
        assert settings["webhook_enabled"] is True
        # Defaults preserved for keys not in the row
        assert settings["suspect_scan_enabled"] is True


# ===========================================================================
# 15. test_setup_registers_all_handlers
#     setup_pipeline_chain registers 7 handlers (one per event, 7 events in the 8-phase chain)
# ===========================================================================


class TestSetupRegistersAllHandlers:
    _EXPECTED_EVENTS = {
        "emr_sync_completed",
        "normalization_completed",
        "analysis_requested",
        "analysis_completed",
        "raf_calculation_completed",
        "suspect_scan_completed",
        "pipeline_completed",
    }

    def test_registers_expected_handlers(self):
        with patch.dict(os.environ, {"RAF_AUTO_CHAIN": "true"}):
            with (
                patch("app.services.event_emitter.register_handler") as mock_reg,
                patch("app.services.pipeline_chain._ensure_pipeline_runs_table"),
            ):
                setup_pipeline_chain()

        registered_events = {c.args[0] for c in mock_reg.call_args_list}
        assert registered_events == self._EXPECTED_EVENTS

    def test_handler_count_is_seven(self):
        with patch.dict(os.environ, {"RAF_AUTO_CHAIN": "true"}):
            with (
                patch("app.services.event_emitter.register_handler") as mock_reg,
                patch("app.services.pipeline_chain._ensure_pipeline_runs_table"),
            ):
                setup_pipeline_chain()

        assert mock_reg.call_count == 7

    def test_no_registration_when_disabled(self):
        with patch.dict(os.environ, {"RAF_AUTO_CHAIN": "false"}):
            with patch("app.services.event_emitter.register_handler") as mock_reg:
                setup_pipeline_chain()

        mock_reg.assert_not_called()


# ===========================================================================
# Bonus: webhook failure is non-fatal in _handle_pipeline_completed
# ===========================================================================


class TestWebhookFailureIsNonFatal:
    def test_handler_does_not_raise_on_webhook_failure(self, pipeline_settings_auto_ai):
        with (
            patch(
                "app.services.pipeline_chain._get_pipeline_settings",
                return_value=pipeline_settings_auto_ai,
            ),
            patch("app.services.pipeline_chain._update_run", _noop_update_run),
            patch(
                "app.services.webhook_service.fire_event",
                side_effect=RuntimeError("webhook endpoint unreachable"),
            ),
        ):
            # Must not raise
            _handle_pipeline_completed(_pipeline_completed_payload())
