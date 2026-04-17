"""Regression test: graft_months must not exceed actual enrollment.

Before this fix, ``calculate_raf_score`` hard-coded graft_months to 12 for
any ESRD_FG beneficiary without an explicit override, regardless of how
many months of MA enrollment the patient actually had. That overstated
duration interactions for partial-year enrollees — e.g. a patient enrolled
6 months post-transplant would still receive 12-month-graft coefficients.

Behaviour is now encapsulated in :func:`_resolve_graft_months`, a pure
helper that can be exercised in isolation without touching the DB layer.
"""

from __future__ import annotations

import pytest

calc = pytest.importorskip("app.services.raf.calculator")
_resolve_graft_months = calc._resolve_graft_months


class TestExplicitOverride:
    """An explicit enrollment_override always wins."""

    def test_override_beats_enrollment_clamp(self) -> None:
        assert (
            _resolve_graft_months(
                model_segment="ESRD_FG",
                enrollment_months=3,
                enrollment_override={"graft_months": 36},
            )
            == 36
        )

    def test_override_beats_clamp_for_non_esrd(self) -> None:
        # Override even works for non-ESRD segments — it's authoritative.
        assert (
            _resolve_graft_months(
                model_segment="CNA",
                enrollment_months=12,
                enrollment_override={"graft_months": 24},
            )
            == 24
        )

    def test_override_coerces_to_int(self) -> None:
        assert (
            _resolve_graft_months(
                model_segment="ESRD_FG",
                enrollment_months=12,
                enrollment_override={"graft_months": "18"},
            )
            == 18
        )

    def test_override_none_value_falls_through(self) -> None:
        # If override dict has graft_months=None, we fall through to the default.
        assert (
            _resolve_graft_months(
                model_segment="ESRD_FG",
                enrollment_months=6,
                enrollment_override={"graft_months": None},
            )
            == 6
        )


class TestESRDFGClamp:
    """ESRD_FG without override clamps to min(12, enrollment_months)."""

    @pytest.mark.parametrize(
        "enrollment,expected",
        [
            (1, 1),
            (6, 6),
            (11, 11),
            (12, 12),
            (24, 12),  # clamped to 12
            (None, 12),  # None → treat as missing data, fall back to 12
            (0, 12),  # 0 → missing data (same as None), fall back to 12
        ],
    )
    def test_clamp_bounds(self, enrollment: int | None, expected: int) -> None:
        assert (
            _resolve_graft_months(
                model_segment="ESRD_FG",
                enrollment_months=enrollment,
                enrollment_override=None,
            )
            == expected
        )

    def test_never_exceeds_enrollment(self) -> None:
        """Core regression: 6-month enrollee must not get 12-month graft."""
        for months in range(1, 12):
            got = _resolve_graft_months(
                model_segment="ESRD_FG",
                enrollment_months=months,
                enrollment_override=None,
            )
            assert got is not None and got <= months, (
                f"graft_months={got} exceeded enrollment_months={months}"
            )


class TestNonESRDSegments:
    """Other segments have no graft_months default — hccinfhir ignores the
    field when the model prefix isn't ESRD_FG-related."""

    @pytest.mark.parametrize(
        "segment",
        ["CNA", "CND", "CFA", "CFD", "CPA", "CPD", "INS", "ESRD_DLY", "ESRD_NE"],
    )
    def test_non_esrd_fg_returns_none(self, segment: str) -> None:
        assert (
            _resolve_graft_months(
                model_segment=segment,
                enrollment_months=6,
                enrollment_override=None,
            )
            is None
        )
