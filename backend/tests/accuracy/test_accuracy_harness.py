"""CI gate: RAF calculator must match the hccinfhir oracle.

This is the only assertion file in ``tests/accuracy``. Everything else
(bundle fetch, bundle → score conversion, triple runner) is plain
Python that this test composes.

Hard thresholds (from the product spec):

  * >= 95% of (patient, model) rows must match within 1e-4 of oracle.
  * NO (patient, model) row may diverge by more than 1e-2.

Both models (V24, V28) are evaluated.

The test uses the hand-crafted fixtures by default so it runs offline
and deterministically. Setting ``RAF_ACCURACY_RUN_SYNTHEA=1`` in the
environment will (when Synthea + Java are available) generate 50 fresh
Medicare-aged patients first.
"""
from __future__ import annotations

import pytest

from tests.accuracy.synthea_fetch import ensure_bundles
from tests.accuracy.triple_score import MODELS, run, summary


MATCH_TOLERANCE = 1e-4
HARD_DIVERGENCE = 1e-2
MIN_MATCH_RATE = 0.95


@pytest.fixture(scope="module")
def scored_rows() -> list[dict]:
    bundles = ensure_bundles(min_count=20)
    assert bundles, "ensure_bundles() returned an empty list"
    return run(bundles)


def test_at_least_twenty_patients(scored_rows: list[dict]) -> None:
    patients = {r["patient_id"] for r in scored_rows}
    assert len(patients) >= 20, (
        f"Expected at least 20 patients, got {len(patients)}. "
        "Populate fixtures/synthea_bundles/hand or enable Synthea generation."
    )


@pytest.mark.parametrize("model", list(MODELS.keys()))
def test_model_match_rate(scored_rows: list[dict], model: str) -> None:
    rows = [r for r in scored_rows if r["model"] == model]
    assert rows, f"No rows scored for model {model}"
    matched = [r for r in rows if r["abs_diff"] <= MATCH_TOLERANCE]
    rate = len(matched) / len(rows)
    assert rate >= MIN_MATCH_RATE, (
        f"{model}: match rate {rate:.2%} below {MIN_MATCH_RATE:.0%}. "
        f"Worst diffs: "
        + ", ".join(
            f"{r['patient_id']}={r['abs_diff']:.4f}"
            for r in sorted(rows, key=lambda r: r["abs_diff"], reverse=True)[:5]
        )
    )


@pytest.mark.parametrize("model", list(MODELS.keys()))
def test_no_patient_wildly_off(scored_rows: list[dict], model: str) -> None:
    rows = [r for r in scored_rows if r["model"] == model]
    offenders = [r for r in rows if r["abs_diff"] > HARD_DIVERGENCE]
    assert not offenders, (
        f"{model}: {len(offenders)} patients exceed hard divergence "
        f"{HARD_DIVERGENCE}: "
        + ", ".join(
            f"{r['patient_id']} (ours={r['ours_raf']:.4f}, "
            f"oracle={r['oracle_raf']:.4f}, diff={r['abs_diff']:.4f})"
            for r in offenders
        )
    )


def test_summary_emitted(scored_rows: list[dict]) -> None:
    """Sanity check + print summary for pytest -s runs."""
    s = summary(scored_rows)
    print("\n[accuracy harness] summary:", s)
    for model in MODELS:
        assert s[f"{model}_n"] == len(
            [r for r in scored_rows if r["model"] == model]
        )
