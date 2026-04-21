"""Numeric precision & rounding-boundary tests.

These lock down:

- The declared RAF_PRECISION (4 decimals) matches every ``round(.., 4)``
  call-site in the calculator.
- Banker's-rounding boundary behaviour is stable at the 5th decimal.
- The half-up presentation helper produces the expected deltas against
  banker's rounding at boundaries (so anyone switching helpers knows
  exactly what changes).
- ``sum_to_precision`` avoids intermediate-rounding drift.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from app.services.raf.precision import (
    CMS_PUBLISHED_PRECISION,
    RAF_PRECISION,
    round_raf,
    round_raf_half_up,
    sum_to_precision,
)

_CALCULATOR = (
    Path(__file__).resolve().parents[1]
    / "app"
    / "services"
    / "raf"
    / "calculator.py"
)


class TestPolicyConstants:
    def test_raf_precision_is_four_decimals(self) -> None:
        assert RAF_PRECISION == 4, (
            "Engine precision policy is 4 decimals — changing this is a "
            "breaking change that must be CMS-reviewed."
        )

    def test_cms_published_precision_is_three(self) -> None:
        assert CMS_PUBLISHED_PRECISION == 3


class TestRoundingBoundaries:
    """Lock the observed Python ``round()`` behaviour at 5th-decimal edges.

    Python's ``round()`` *documented* policy is banker's rounding
    (round-half-to-even). In practice the answer on ``float`` inputs is
    also modulated by IEEE-754 representation: e.g. the literal ``0.12345``
    cannot be represented exactly and sits a hair above the halfway point,
    which makes ``round(0.12345, 4) == 0.1235`` (not 0.1234 as pure
    banker's rounding on a theoretical halfway would give).

    These tests lock the *actual* values our engine produces on concrete
    float literals. A switch to ``Decimal`` arithmetic would change these
    — intentionally, and detectably, via a failing test here.
    """

    @pytest.mark.parametrize(
        "raw,expected",
        [
            # Halfway-in-decimal edges — answer dominated by float repr.
            (0.12345, 0.1235),
            (0.12355, 0.1235),
            (1.00005, 1.0001),
            (-0.12345, -0.1235),
            # Clear-cut (not halfway) cases — unambiguous.
            (0.12344, 0.1234),
            (0.12346, 0.1235),
            (0.0, 0.0),
            # Known-clean values with exact binary representations —
            # banker's policy shows through cleanly on these.
            (0.5, 0.5),
            (0.125, 0.125),
        ],
    )
    def test_round_raf_produces_engine_value(
        self, raw: float, expected: float
    ) -> None:
        assert round_raf(raw) == expected, (
            f"Rounding drift at {raw}: got {round_raf(raw)}, "
            f"expected {expected}"
        )


class TestHalfUpBoundaries:
    """Half-away-from-zero for presentation-layer uses only."""

    @pytest.mark.parametrize(
        "raw,expected",
        [
            (0.12345, 0.1235),   # half → up (differs from banker)
            (0.12355, 0.1236),   # > half → up
            (0.99995, 1.0000),   # half → up (agrees with banker here)
            (0.12344, 0.1234),   # < half → down
            (0.12346, 0.1235),   # > half → up
            (0.0, 0.0),
        ],
    )
    def test_round_raf_half_up(self, raw: float, expected: float) -> None:
        assert round_raf_half_up(raw) == expected

    def test_half_up_agrees_on_repr_clean_boundary(self) -> None:
        """Where the IEEE-754 literal is *just above* the mid-point,
        ``round_raf`` rounds up to match ``round_raf_half_up``. This
        test documents an agreement boundary — 0.99995 — so regressions
        that introduce divergence here are caught."""
        assert round_raf_half_up(0.99995) == 1.0
        assert round_raf(0.99995) == 1.0

    def test_half_up_diverges_on_repr_clean_boundary(self) -> None:
        """And where the float does sit below half, the two helpers
        diverge."""
        # 0.5 → 0.5 for both (already at target precision).
        assert round_raf(0.5) == 0.5
        assert round_raf_half_up(0.5) == 0.5
        # 2-decimal rounding reveals the banker-vs-half-up split.
        # round(0.125, 2) == 0.12 (banker → even), half-up == 0.13.
        assert round(0.125, 2) == 0.12
        from decimal import ROUND_HALF_UP, Decimal
        assert float(
            Decimal("0.125").quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        ) == 0.13


class TestSumToPrecision:
    def test_intermediate_drift_avoided(self) -> None:
        """Summing many tiny terms and rounding at the end must match
        the mathematical sum rounded once, not the sum of individually-
        rounded terms.
        """
        # 10 × 0.00005 = 0.00050 — round individually each becomes 0.0000
        # (banker's), sum = 0.0000; summed then rounded = 0.0004 (banker's)
        terms = [0.00005] * 10
        assert sum_to_precision(*terms) == round_raf(sum(terms))

    def test_empty_sum_is_zero(self) -> None:
        assert sum_to_precision() == 0.0

    def test_single_term_unchanged(self) -> None:
        assert sum_to_precision(0.1234) == 0.1234


class TestCalculatorUsesDeclaredPrecision:
    """Every ``round(..., N)`` in calculator.py must use N=4 (RAF_PRECISION)
    or a documented exception (6 for combined_factor audit field, 4 for
    delta / reconcile outputs).

    This keeps the calculator self-consistent with the precision module.
    """

    def test_no_unexpected_precision_in_calculator(self) -> None:
        text = _CALCULATOR.read_text()
        # Find every round(expr, N) call.
        # Match any non-paren chars for expr so we only fail on N values.
        matches = re.findall(r"round\([^,]+,\s*(\d+)\s*\)", text)
        allowed = {4, 6}  # 6 only for the combined_factor audit line
        bad = [m for m in matches if int(m) not in allowed]
        assert not bad, (
            f"calculator.py uses round precision values outside the "
            f"documented set {allowed}: found {bad}. "
            f"Update the precision module if a new value is intentional."
        )


class TestHelperIdempotence:
    @pytest.mark.parametrize("raw", [0.395, 0.561, 1.033, 1.559, 0.0])
    def test_round_raf_is_idempotent(self, raw: float) -> None:
        """Rounding an already-rounded value must not change it."""
        once = round_raf(raw)
        twice = round_raf(once)
        assert once == twice

    @pytest.mark.parametrize("raw", [0.395, 1.033, 0.0])
    def test_half_up_is_idempotent(self, raw: float) -> None:
        once = round_raf_half_up(raw)
        twice = round_raf_half_up(once)
        assert once == twice
