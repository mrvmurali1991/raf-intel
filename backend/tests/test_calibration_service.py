"""
Unit tests for ``app.services.knowledge_graph.calibration_service``.

These tests exercise the inference-time Platt calibration loader:

* The seeded artefact loads and yields finite floats.
* A missing artefact falls back to identity ``(1.0, 0.0)``.
* ``apply_calibration`` matches a textbook sigmoid for known inputs.
* ``apply_calibration`` clamps extreme inputs to ``[0, 1]``.

The service has no DB, no network, and no third-party dependencies, so the
tests stay self-contained and run as fast pure-python unit tests.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from app.services.knowledge_graph import calibration_service


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _reset() -> None:
    calibration_service.reload_calibration()


# ---------------------------------------------------------------------------
# load_calibration
# ---------------------------------------------------------------------------

def test_load_calibration_returns_floats_from_seeded_artefact():
    """The repo ships ``platt_v1.json`` — load it and assert (a, b) are finite floats."""
    # Make sure we're not seeing a stale identity tuple from another test.
    _reset()
    a, b = calibration_service.load_calibration()
    assert isinstance(a, float)
    assert isinstance(b, float)
    assert math.isfinite(a)
    assert math.isfinite(b)
    # The seeded artefact is a non-trivial fit; assert it's not identity so
    # downstream callers actually exercise the calibrated path.
    assert not calibration_service.is_identity(a, b), (
        "Seeded artefact should not be the identity Platt fit; "
        "check calibration_artefacts/platt_v1.json"
    )


def test_load_calibration_caches_result(monkeypatch):
    """Second call should hit the module-level cache (no disk read)."""
    _reset()
    a1, b1 = calibration_service.load_calibration()

    # Replace ARTEFACT_PATH with a dangling Path; if the cache works, a
    # second call still returns the original tuple.
    monkeypatch.setattr(
        calibration_service, "ARTEFACT_PATH",
        Path("/nonexistent/calibration_artefacts/platt_v999.json"),
    )
    a2, b2 = calibration_service.load_calibration()
    assert (a1, b1) == (a2, b2)


def test_load_calibration_falls_back_to_identity_when_artefact_missing(tmp_path, monkeypatch):
    """Point the loader at a non-existent path and confirm identity fallback."""
    monkeypatch.setattr(
        calibration_service, "ARTEFACT_PATH",
        tmp_path / "does_not_exist.json",
    )
    _reset()  # re-read with the new path
    a, b = calibration_service.load_calibration()
    assert (a, b) == (1.0, 0.0)
    assert calibration_service.is_identity(a, b)


def test_load_calibration_falls_back_on_malformed_json(tmp_path, monkeypatch):
    bad = tmp_path / "platt_bad.json"
    bad.write_text("{not valid json")
    monkeypatch.setattr(calibration_service, "ARTEFACT_PATH", bad)
    _reset()
    a, b = calibration_service.load_calibration()
    assert (a, b) == (1.0, 0.0)


def test_load_calibration_falls_back_on_missing_keys(tmp_path, monkeypatch):
    bad = tmp_path / "platt_missing.json"
    bad.write_text(json.dumps({"trained_on_charts": 52}))  # no a / b
    monkeypatch.setattr(calibration_service, "ARTEFACT_PATH", bad)
    _reset()
    a, b = calibration_service.load_calibration()
    assert (a, b) == (1.0, 0.0)


def test_load_calibration_falls_back_on_non_finite(tmp_path, monkeypatch):
    bad = tmp_path / "platt_nan.json"
    bad.write_text(json.dumps({"a": "Infinity", "b": "NaN"}))
    monkeypatch.setattr(calibration_service, "ARTEFACT_PATH", bad)
    _reset()
    a, b = calibration_service.load_calibration()
    # JSON parses "Infinity" and "NaN" as strings here so the float() cast
    # raises ValueError → identity fallback.  Non-finite numerics are also
    # rejected when they pass float() (e.g. via custom encoders).
    assert (a, b) == (1.0, 0.0)


# ---------------------------------------------------------------------------
# apply_calibration
# ---------------------------------------------------------------------------

def test_apply_calibration_sigmoid_at_zero_with_identity_params():
    """sigmoid(1*0.5 + 0) ≈ 0.6225 — the classic logistic point."""
    out = calibration_service.apply_calibration(0.5, 1.0, 0.0)
    assert out == pytest.approx(0.6224593, rel=1e-5)


def test_apply_calibration_clamps_huge_negative_to_zero():
    """A huge negative z should not return a tiny negative number — clamp at 0."""
    out = calibration_service.apply_calibration(-1e9, 1.0, 0.0)
    assert out == pytest.approx(0.0, abs=1e-12)
    assert 0.0 <= out <= 1.0


def test_apply_calibration_clamps_huge_positive_to_one():
    out = calibration_service.apply_calibration(1e9, 1.0, 0.0)
    assert out == pytest.approx(1.0, abs=1e-12)
    assert 0.0 <= out <= 1.0


def test_apply_calibration_identity_when_params_are_none():
    """``a=None`` or ``b=None`` should pass through (clipped to [0,1])."""
    assert calibration_service.apply_calibration(0.42, None, None) == pytest.approx(0.42)
    assert calibration_service.apply_calibration(0.42, 1.5, None) == pytest.approx(0.42)
    assert calibration_service.apply_calibration(0.42, None, 0.1) == pytest.approx(0.42)


def test_apply_calibration_clips_when_passthrough_is_out_of_range():
    """Pass-through still clips to [0, 1] for safety."""
    assert calibration_service.apply_calibration(2.5, None, None) == pytest.approx(1.0)
    assert calibration_service.apply_calibration(-0.3, None, None) == pytest.approx(0.0)


def test_apply_calibration_handles_none_input():
    """A ``None`` raw should not raise — return 0."""
    assert calibration_service.apply_calibration(None, 1.0, 0.0) == 0.0


def test_apply_calibration_handles_non_numeric_input():
    """A non-castable raw should not raise — return 0."""
    assert calibration_service.apply_calibration("not a number", 1.0, 0.0) == 0.0  # type: ignore[arg-type]


def test_apply_calibration_with_seeded_params_lifts_low_confidence():
    """The seeded artefact's (a, b) should map a 0.5 raw confidence to a
    value in (0, 1) — i.e. it actually computes a sigmoid, not pass-through."""
    _reset()
    a, b = calibration_service.load_calibration()
    out = calibration_service.apply_calibration(0.5, a, b)
    assert 0.0 < out < 1.0


# ---------------------------------------------------------------------------
# Metadata + helpers
# ---------------------------------------------------------------------------

def test_get_metadata_returns_dict_with_artefact_keys():
    _reset()
    meta = calibration_service.get_metadata()
    assert isinstance(meta, dict)
    # The seeded artefact carries trained_on_charts + ECE numbers.
    assert "trained_on_charts" in meta
    assert "ece_before" in meta
    assert "ece_after" in meta


def test_is_identity_returns_true_for_default():
    assert calibration_service.is_identity(1.0, 0.0)
    assert not calibration_service.is_identity(1.0341, 0.1189)
    assert not calibration_service.is_identity(0.9, 0.0)


def test_reload_calibration_picks_up_disk_change(tmp_path, monkeypatch):
    """Write artefact A, load, swap to artefact B, reload, confirm B values."""
    a_path = tmp_path / "a.json"
    a_path.write_text(json.dumps({"a": 2.0, "b": 0.5}))
    monkeypatch.setattr(calibration_service, "ARTEFACT_PATH", a_path)
    calibration_service.reload_calibration()
    assert calibration_service.load_calibration() == (2.0, 0.5)

    a_path.write_text(json.dumps({"a": 3.5, "b": -1.25}))
    calibration_service.reload_calibration()
    assert calibration_service.load_calibration() == (3.5, -1.25)
