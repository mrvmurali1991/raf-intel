"""
Tests for the suspect-confidence calibration layer.

Contract under test:

* Platt calibrator is monotone-increasing and bounded to [0,1]
* Isotonic calibrator recovers a step function (monotone)
* Bootstrap label generator produces a non-degenerate mix of 0/1
* Calibrator artifacts round-trip through joblib and return the same
  probabilities after load.

These are fast unit tests — no DB, no network, no sklearn training on
huge datasets.  They intentionally do not test production calibration
quality; see the module docstring at
``app.services.raf.calibration`` for the honest caveats.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from app.services.raf.calibration.bootstrap import (
    BootstrapRow,
    build_bootstrap_set,
    class_balance,
    read_csv,
    write_csv,
)
from app.services.raf.calibration.calibrator import (
    IdentityCalibrator,
    IsotonicCalibrator,
    PlattCalibrator,
)
from app.services.raf.calibration.persistence import (
    _normalise_source,
    load_calibrator,
    reset_cache,
    save_calibrator,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _noisy_sigmoid_labels(raw: np.ndarray, seed: int = 7) -> np.ndarray:
    """Generate labels that roughly follow a sigmoid of raw score."""
    rng = np.random.default_rng(seed)
    p = 1.0 / (1.0 + np.exp(-(raw - 0.5) * 8.0))
    return (rng.random(raw.shape[0]) < p).astype(int)


# ---------------------------------------------------------------------------
# Platt
# ---------------------------------------------------------------------------

def test_platt_monotone_and_bounded() -> None:
    rng = np.random.default_rng(0)
    raw = rng.uniform(0, 1, size=400)
    labels = _noisy_sigmoid_labels(raw)

    cal = PlattCalibrator().fit(raw, labels)
    assert cal.fitted

    grid = np.linspace(0.0, 1.0, 21)
    out = cal.transform(grid)

    # Bounded
    assert np.all(out >= 0.0), out
    assert np.all(out <= 1.0), out

    # Monotone non-decreasing
    diffs = np.diff(out)
    assert np.all(diffs >= -1e-9), f"non-monotone: {diffs}"


def test_platt_single_class_degenerate_fallback() -> None:
    """Platt with a single-class label set should not crash and should
    return the base rate (here: all zeros -> 0.0, all ones -> 1.0)."""
    raw = np.array([0.2, 0.3, 0.4, 0.5])
    zeros = np.zeros_like(raw, dtype=int)
    cal = PlattCalibrator().fit(raw, zeros)
    out = cal.transform(raw)
    assert np.allclose(out, 0.0)

    ones = np.ones_like(raw, dtype=int)
    cal2 = PlattCalibrator().fit(raw, ones)
    out2 = cal2.transform(raw)
    assert np.allclose(out2, 1.0)


# ---------------------------------------------------------------------------
# Isotonic
# ---------------------------------------------------------------------------

def test_isotonic_recovers_step_function() -> None:
    """Raw scores below 0.5 -> label 0; above -> label 1.  Isotonic
    should learn a near-step function.
    """
    raw = np.concatenate([
        np.linspace(0.0, 0.5, 50, endpoint=False),
        np.linspace(0.5, 1.0, 50),
    ])
    labels = (raw >= 0.5).astype(int)

    cal = IsotonicCalibrator().fit(raw, labels)

    # Below the knee -> ~0, above -> ~1
    low = cal.transform(np.array([0.0, 0.1, 0.25, 0.45]))
    high = cal.transform(np.array([0.55, 0.7, 0.9, 1.0]))

    assert np.all(low <= 0.1), low
    assert np.all(high >= 0.9), high

    # Monotonicity on a fine grid
    grid = np.linspace(0, 1, 101)
    out = cal.transform(grid)
    assert np.all(np.diff(out) >= -1e-9)
    assert np.all((out >= 0.0) & (out <= 1.0))


def test_identity_calibrator_returns_input() -> None:
    cal = IdentityCalibrator()
    assert cal.fitted
    raw = np.array([0.0, 0.25, 0.5, 0.75, 1.0])
    out = cal.transform(raw)
    assert np.allclose(out, raw)
    assert cal.transform_one(0.42) == pytest.approx(0.42)


# ---------------------------------------------------------------------------
# Bootstrap label generator
# ---------------------------------------------------------------------------

def _make_suspect(**overrides):
    base = {
        "patient_id": 1,
        "suspected_icd": "E11",
        "source": "lab",
        "confidence": 0.7,
        "evidence": {},
    }
    base.update(overrides)
    return base


def test_bootstrap_positive_via_corroboration() -> None:
    lab = _make_suspect(source="lab", suspected_icd="E119", confidence=0.6)
    med = _make_suspect(source="medication", suspected_icd="E119", confidence=0.5)
    rows = build_bootstrap_set([lab, med])
    labels = {r.source: r.label for r in rows}
    assert labels.get("lab") == 1
    assert labels.get("medication") == 1


def test_bootstrap_negative_via_negation() -> None:
    s = _make_suspect(
        source="nlp",
        confidence=0.85,
        evidence={"note_snippet": "Patient denies any history of diabetes."},
    )
    rows = build_bootstrap_set([s])
    assert len(rows) == 1
    assert rows[0].label == 0


def test_bootstrap_negative_via_weak_single_signal() -> None:
    s = _make_suspect(source="lab", confidence=0.30, evidence={})
    rows = build_bootstrap_set([s])
    assert len(rows) == 1
    assert rows[0].label == 0


def test_bootstrap_positive_via_strong_lab() -> None:
    s = _make_suspect(
        source="lab",
        confidence=0.6,
        evidence={"value": 15.0, "threshold": 7.0},  # ratio ~2.14
    )
    rows = build_bootstrap_set([s])
    assert len(rows) == 1
    assert rows[0].label == 1


def test_bootstrap_history_always_positive() -> None:
    s = _make_suspect(source="history", confidence=0.85)
    rows = build_bootstrap_set([s])
    assert rows[0].label == 1


def test_bootstrap_excludes_ambiguous() -> None:
    """Single mid-confidence lab with no corroboration, no negation,
    no extreme value -> ambiguous -> excluded."""
    s = _make_suspect(source="lab", confidence=0.6, evidence={})
    rows = build_bootstrap_set([s])
    assert rows == []


def test_bootstrap_class_balance_not_degenerate() -> None:
    """Build a mixed cohort and confirm the generator yields both
    labels and both sources, i.e. not 100%/0% on any axis."""
    suspects = [
        # Two corroborating pairs -> four positives
        _make_suspect(patient_id=1, source="lab",        suspected_icd="E119",  confidence=0.7),
        _make_suspect(patient_id=1, source="medication", suspected_icd="E119",  confidence=0.6),
        _make_suspect(patient_id=2, source="rule",       suspected_icd="I501",  confidence=0.8),
        _make_suspect(patient_id=2, source="nlp",        suspected_icd="I501",  confidence=0.55),
        # Two weak singletons -> two negatives
        _make_suspect(patient_id=3, source="lab",        suspected_icd="N189",  confidence=0.35, evidence={}),
        _make_suspect(patient_id=4, source="medication", suspected_icd="J449",  confidence=0.30, evidence={}),
        # One negation -> negative
        _make_suspect(
            patient_id=5, source="nlp", suspected_icd="F329", confidence=0.9,
            evidence={"note_snippet": "no evidence of depression noted."},
        ),
        # Ambiguous -> excluded
        _make_suspect(patient_id=6, source="lab", suspected_icd="E119", confidence=0.55, evidence={}),
    ]
    rows = build_bootstrap_set(suspects)
    balance = class_balance(rows)

    # At least one positive and at least one negative
    labels = [r.label for r in rows]
    assert 0 in labels
    assert 1 in labels

    # Overall not degenerate
    overall_pos = balance["_overall"]
    assert 0.0 < overall_pos < 1.0, balance


def test_bootstrap_csv_round_trip(tmp_path) -> None:
    rows = [
        BootstrapRow(source="lab", raw_score=0.7, label=1),
        BootstrapRow(source="med", raw_score=0.3, label=0),
    ]
    path = tmp_path / "bootstrap.csv"
    write_csv(rows, path)
    back = read_csv(path)
    assert back == rows


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

def test_persistence_round_trip(tmp_path, monkeypatch) -> None:
    """Save a fitted Platt calibrator, load it from disk, and confirm
    transform produces the identical probabilities."""
    from app.services.raf.calibration import persistence as P

    # Redirect MODEL_DIR to a temp path to avoid polluting the repo.
    monkeypatch.setattr(P, "MODEL_DIR", tmp_path)
    reset_cache()

    rng = np.random.default_rng(42)
    raw = rng.uniform(0, 1, size=200)
    labels = _noisy_sigmoid_labels(raw, seed=42)
    cal = PlattCalibrator().fit(raw, labels)

    save_calibrator("lab", cal)
    reset_cache()

    loaded = load_calibrator("lab")
    grid = np.linspace(0, 1, 11)
    assert np.allclose(cal.transform(grid), loaded.transform(grid))


def test_persistence_missing_artifact_falls_back_to_identity(tmp_path, monkeypatch) -> None:
    from app.services.raf.calibration import persistence as P

    monkeypatch.setattr(P, "MODEL_DIR", tmp_path)  # empty
    reset_cache()

    cal = load_calibrator("lab")
    assert isinstance(cal, IdentityCalibrator)
    # Identity returns raw, clipped
    assert cal.transform_one(0.42) == pytest.approx(0.42)
    assert cal.transform_one(1.5) == pytest.approx(1.0)


def test_source_normalisation_aliases() -> None:
    # A few aliases we actually see in production suspect rows.
    assert _normalise_source("medication") == "med"
    assert _normalise_source("MED") == "med"
    assert _normalise_source("rule") == "regex"
    assert _normalise_source("nlp") == "llm"
    assert _normalise_source(None) == "regex"
    assert _normalise_source("history") == "regex"
