"""Frailty adjustment tests (PACE / FIDE-SNP).

CMS applies a frailty addend on top of the normalized RAF score for certain
special-needs plans, computed from ADL (Activities of Daily Living)
impairment counts. This module locks:

- Count-to-score table per payment year (2024/2025/2026)
- Eligibility gate (only PACE / FIDE-SNP see the adjustment)
- ADL counting logic across boolean / int / string inputs
- Addend behaviour (score is *added*, not multiplied)
- Boundary clamping (0-6 impairment count)
"""

from __future__ import annotations

import pytest

from app.services.frailty_adjuster import (
    _FRAILTY_COEFFICIENTS,
    _FRAILTY_ELIGIBLE_PLAN_TYPES,
    apply_frailty_adjustment,
    count_adl_impairments,
    get_frailty_score,
)


# ---------------------------------------------------------------------------
# CMS coefficient table lock
# ---------------------------------------------------------------------------

class TestPY2026FrailtyTable:
    """CMS 2026 published values per public MA Rate Notice (frailty section)."""

    @pytest.mark.parametrize(
        "count,expected",
        [
            (0, 0.000),
            (1, 0.184),
            (2, 0.261),
            (3, 0.382),
            (4, 0.478),
            (5, 0.547),
            (6, 0.640),
        ],
    )
    def test_py2026_addend_matches_cms(self, count: int, expected: float) -> None:
        assert get_frailty_score(count, payment_year=2026) == expected


class TestPY2024PY2025FrailtyTable:
    """Prior-year locks: frailty addends for 2024 and 2025 payment years."""

    def test_py2024_full_table(self) -> None:
        table = _FRAILTY_COEFFICIENTS[2024]
        assert table == {
            0: 0.000, 1: 0.172, 2: 0.244, 3: 0.358,
            4: 0.449, 5: 0.513, 6: 0.601,
        }

    def test_py2025_full_table(self) -> None:
        table = _FRAILTY_COEFFICIENTS[2025]
        assert table == {
            0: 0.000, 1: 0.179, 2: 0.252, 3: 0.370,
            4: 0.463, 5: 0.530, 6: 0.621,
        }

    def test_monotonically_increasing(self) -> None:
        """Every table must be monotonically non-decreasing in ADL count."""
        for year, table in _FRAILTY_COEFFICIENTS.items():
            values = [table[i] for i in range(7)]
            for i in range(6):
                assert values[i + 1] >= values[i], (
                    f"PY{year}: frailty[{i+1}]={values[i+1]} < "
                    f"frailty[{i}]={values[i]}"
                )


# ---------------------------------------------------------------------------
# ADL counting
# ---------------------------------------------------------------------------

class TestCountADLImpairments:
    def test_all_false_is_zero(self) -> None:
        data = {f"{a}_impaired": False for a in (
            "bathing", "dressing", "eating", "toileting",
            "transferring", "continence",
        )}
        count, names = count_adl_impairments(data)
        assert count == 0 and names == []

    def test_all_true_is_six(self) -> None:
        data = {f"{a}_impaired": True for a in (
            "bathing", "dressing", "eating", "toileting",
            "transferring", "continence",
        )}
        count, names = count_adl_impairments(data)
        assert count == 6 and len(names) == 6

    def test_mixed_boolean_integer_string(self) -> None:
        data = {
            "bathing_impaired": True,
            "dressing_impaired": 1,
            "eating_impaired": "yes",
            "toileting_impaired": "Impaired",
            "transferring_impaired": False,
            "continence_impaired": "no",
        }
        count, _ = count_adl_impairments(data)
        assert count == 4

    def test_missing_fields_treated_as_intact(self) -> None:
        # Two explicitly impaired, four missing.
        data = {"bathing_impaired": True, "eating_impaired": True}
        count, names = count_adl_impairments(data)
        assert count == 2
        assert set(names) == {"bathing_impaired", "eating_impaired"}

    def test_empty_dict_is_zero(self) -> None:
        assert count_adl_impairments({}) == (0, [])


# ---------------------------------------------------------------------------
# Apply frailty adjustment — end-to-end
# ---------------------------------------------------------------------------

class TestApplyFrailtyAdjustment:
    def _full_impaired_adl(self) -> dict:
        return {f"{a}_impaired": True for a in (
            "bathing", "dressing", "eating", "toileting",
            "transferring", "continence",
        )}

    def test_non_eligible_plan_type_skips_adjustment(self) -> None:
        result = apply_frailty_adjustment(
            payment_raf=1.0,
            adl_data=self._full_impaired_adl(),
            plan_type="MA",
            payment_year=2026,
        )
        assert result["applies"] is False, (
            "Standard MA plans must not receive frailty adjustment"
        )
        assert result["adjusted_payment_raf"] == 1.0

    def test_pace_full_impairment_adds_max_addend(self) -> None:
        result = apply_frailty_adjustment(
            payment_raf=1.0,
            adl_data=self._full_impaired_adl(),
            plan_type="PACE",
            payment_year=2026,
        )
        assert result["applies"] is True
        assert result["adl_count"] == 6
        assert result["frailty_addend"] == pytest.approx(0.640, abs=1e-6)
        assert result["adjusted_payment_raf"] == pytest.approx(1.640, abs=1e-6)

    def test_fide_snp_triggers_adjustment(self) -> None:
        result = apply_frailty_adjustment(
            payment_raf=0.8,
            adl_data={"bathing_impaired": True, "eating_impaired": True},
            plan_type="FIDE_SNP",
            payment_year=2026,
        )
        assert result["applies"] is True
        assert result["adl_count"] == 2
        assert result["frailty_addend"] == pytest.approx(0.261, abs=1e-6)
        assert result["adjusted_payment_raf"] == pytest.approx(1.061, abs=1e-6)

    def test_zero_impairments_is_zero_addend(self) -> None:
        result = apply_frailty_adjustment(
            payment_raf=1.2,
            adl_data={},
            plan_type="PACE",
            payment_year=2026,
        )
        assert result["applies"] is True
        assert result["adl_count"] == 0
        assert result["frailty_addend"] == 0.0
        assert result["adjusted_payment_raf"] == 1.2

    def test_frailty_is_added_not_multiplied(self) -> None:
        """Frailty must be an additive addend, not a multiplicative factor."""
        base_raf = 2.0
        result = apply_frailty_adjustment(
            payment_raf=base_raf,
            adl_data={"bathing_impaired": True},
            plan_type="PACE",
            payment_year=2026,
        )
        addend = _FRAILTY_COEFFICIENTS[2026][1]  # 0.184
        assert result["adjusted_payment_raf"] == pytest.approx(
            base_raf + addend, abs=1e-6
        )

    @pytest.mark.parametrize("plan", sorted(_FRAILTY_ELIGIBLE_PLAN_TYPES))
    def test_every_eligible_plan_type_accepted(self, plan: str) -> None:
        result = apply_frailty_adjustment(
            payment_raf=1.0,
            adl_data={"bathing_impaired": True},
            plan_type=plan,
            payment_year=2026,
        )
        assert result["applies"] is True


# ---------------------------------------------------------------------------
# Boundary behaviour
# ---------------------------------------------------------------------------

class TestBoundaries:
    def test_count_over_six_clamps_to_six(self) -> None:
        # Can't physically happen (only 6 ADLs) but defend against bad input.
        assert get_frailty_score(7, 2026) == 0.640
        assert get_frailty_score(99, 2026) == 0.640

    def test_negative_count_treated_as_zero(self) -> None:
        assert get_frailty_score(-1, 2026) == 0.0

    def test_unknown_payment_year_uses_default_table(self) -> None:
        """Future years without a pinned table fall back to latest (2026)."""
        assert get_frailty_score(3, 2099) == _FRAILTY_COEFFICIENTS[2026][3]
