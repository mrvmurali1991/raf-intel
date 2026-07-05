"""
DOS Rules and Enrollment Resolver — expanded test suite.

Covers: payment year windows, eligible encounter types, model segment
determination, enrollment resolution prefix mapping, and blend weight
registry completeness.

No database or network required.
"""
from __future__ import annotations

import inspect
from datetime import date

import pytest


# ---------------------------------------------------------------------------
# 1. Payment year window registry
# ---------------------------------------------------------------------------

class TestPaymentYearRegistry:
    """PAYMENT_YEARS must cover current and upcoming years correctly."""

    def test_py2024_exists(self):
        from app.services.raf.dos_rules import PAYMENT_YEARS
        assert 2024 in PAYMENT_YEARS

    def test_py2025_exists(self):
        from app.services.raf.dos_rules import PAYMENT_YEARS
        assert 2025 in PAYMENT_YEARS

    def test_py2026_exists(self):
        from app.services.raf.dos_rules import PAYMENT_YEARS
        assert 2026 in PAYMENT_YEARS

    def test_current_year_covered(self):
        from app.services.raf.dos_rules import PAYMENT_YEARS
        current_year = date.today().year
        assert current_year in PAYMENT_YEARS

    def test_dos_window_is_prior_calendar_year(self):
        from app.services.raf.dos_rules import PAYMENT_YEARS
        for year, pw in PAYMENT_YEARS.items():
            assert pw.dos_start == date(year - 1, 1, 1), (
                f"PY{year} dos_start should be Jan 1 of prior year"
            )
            assert pw.dos_end == date(year - 1, 12, 31), (
                f"PY{year} dos_end should be Dec 31 of prior year"
            )

    def test_dos_end_after_dos_start(self):
        from app.services.raf.dos_rules import PAYMENT_YEARS
        for year, pw in PAYMENT_YEARS.items():
            assert pw.dos_end >= pw.dos_start


# ---------------------------------------------------------------------------
# 2. Eligible encounter types
# ---------------------------------------------------------------------------

class TestEligibleEncounterTypes:
    """CMS-approved face-to-face encounter types."""

    def test_exactly_four_eligible_types(self):
        from app.services.raf.dos_rules import ELIGIBLE_ENCOUNTER_TYPES
        assert len(ELIGIBLE_ENCOUNTER_TYPES) == 4

    def test_is_frozenset(self):
        from app.services.raf.dos_rules import ELIGIBLE_ENCOUNTER_TYPES
        assert isinstance(ELIGIBLE_ENCOUNTER_TYPES, frozenset)

    def test_all_lowercase(self):
        from app.services.raf.dos_rules import ELIGIBLE_ENCOUNTER_TYPES
        for t in ELIGIBLE_ENCOUNTER_TYPES:
            assert t == t.lower()


# ---------------------------------------------------------------------------
# 3. Known ineligible types
# ---------------------------------------------------------------------------

class TestKnownIneligibleTypes:
    """Ineligible encounter types should have human-readable reasons."""

    def test_lab_is_ineligible(self):
        from app.services.raf.dos_rules import _KNOWN_INELIGIBLE_TYPES
        assert "lab" in _KNOWN_INELIGIBLE_TYPES

    def test_pharmacy_is_ineligible(self):
        from app.services.raf.dos_rules import _KNOWN_INELIGIBLE_TYPES
        assert "pharmacy" in _KNOWN_INELIGIBLE_TYPES

    def test_dme_is_ineligible(self):
        from app.services.raf.dos_rules import _KNOWN_INELIGIBLE_TYPES
        assert "dme" in _KNOWN_INELIGIBLE_TYPES

    def test_reasons_are_strings(self):
        from app.services.raf.dos_rules import _KNOWN_INELIGIBLE_TYPES
        for enc_type, reason in _KNOWN_INELIGIBLE_TYPES.items():
            assert isinstance(reason, str)
            assert len(reason) > 10


# ---------------------------------------------------------------------------
# 4. Model segment prefix mapping
# ---------------------------------------------------------------------------

class TestSegmentToPrefix:
    """_SEGMENT_TO_PREFIX must map all segments to coefficient prefixes."""

    def test_cna_segment_exists(self):
        from app.services.raf.enrollment_resolver import _SEGMENT_TO_PREFIX
        assert "CNA" in _SEGMENT_TO_PREFIX

    def test_cnd_segment_exists(self):
        from app.services.raf.enrollment_resolver import _SEGMENT_TO_PREFIX
        assert "CND" in _SEGMENT_TO_PREFIX

    def test_cfa_segment_exists(self):
        from app.services.raf.enrollment_resolver import _SEGMENT_TO_PREFIX
        assert "CFA" in _SEGMENT_TO_PREFIX

    def test_ins_segment_exists(self):
        from app.services.raf.enrollment_resolver import _SEGMENT_TO_PREFIX
        assert "INS" in _SEGMENT_TO_PREFIX

    def test_all_prefixes_are_strings(self):
        from app.services.raf.enrollment_resolver import _SEGMENT_TO_PREFIX
        for seg, prefix in _SEGMENT_TO_PREFIX.items():
            assert isinstance(prefix, str)
            assert len(prefix) > 0


# ---------------------------------------------------------------------------
# 5. ESRD detection (segment-based)
# ---------------------------------------------------------------------------

class TestEsrdDetection:
    """_is_esrd identifies ESRD model segments by prefix."""

    def test_esrd_dialysis_segment_is_esrd(self):
        from app.services.raf.enrollment_resolver import _is_esrd
        assert _is_esrd("ESRD_DLY") is True

    def test_esrd_functioning_graft_is_esrd(self):
        from app.services.raf.enrollment_resolver import _is_esrd
        assert _is_esrd("ESRD_FG") is True

    def test_community_segment_is_not_esrd(self):
        from app.services.raf.enrollment_resolver import _is_esrd
        assert _is_esrd("CNA") is False

    def test_new_enrollee_is_not_esrd(self):
        from app.services.raf.enrollment_resolver import _is_esrd
        assert _is_esrd("NE_CNA") is False

    def test_is_new_enrollee_detects_ne_prefix(self):
        from app.services.raf.enrollment_resolver import _is_new_enrollee
        assert _is_new_enrollee("NE_CNA") is True
        assert _is_new_enrollee("CNA") is False


# ---------------------------------------------------------------------------
# 6. Norm and MACI factor tables
# ---------------------------------------------------------------------------

class TestNormMaciFactors:
    """Normalization and MACI factor tables must cover all payment years."""

    def test_norm_factors_v28_has_current_year(self):
        from app.services.raf.blend_weights import _NORM_FACTORS_V28
        current_year = date.today().year
        assert current_year in _NORM_FACTORS_V28

    def test_maci_factors_v28_has_current_year(self):
        from app.services.raf.blend_weights import _MACI_FACTORS_V28
        current_year = date.today().year
        assert current_year in _MACI_FACTORS_V28

    def test_norm_factors_are_positive(self):
        from app.services.raf.blend_weights import _NORM_FACTORS_V28
        for year, factor in _NORM_FACTORS_V28.items():
            assert factor > 0, f"Norm factor for PY{year} must be positive"

    def test_maci_factors_are_between_zero_and_one(self):
        from app.services.raf.blend_weights import _MACI_FACTORS_V28
        for year, factor in _MACI_FACTORS_V28.items():
            assert 0 <= factor <= 1, f"MACI factor for PY{year} must be in [0,1]"

    def test_norm_factors_v24_exists(self):
        from app.services.raf.blend_weights import _NORM_FACTORS_V24
        assert len(_NORM_FACTORS_V24) > 0

    def test_norm_factors_v22_exists(self):
        from app.services.raf.blend_weights import _NORM_FACTORS_V22
        assert len(_NORM_FACTORS_V22) > 0


# ---------------------------------------------------------------------------
# 7. PaymentYearWindow self-validation
# ---------------------------------------------------------------------------

class TestPaymentYearWindowValidation:
    """PaymentYearWindow dataclass has self-validating __post_init__."""

    def test_invalid_blend_raises_value_error(self):
        from app.services.raf.dos_rules import PaymentYearWindow
        with pytest.raises(ValueError, match="sum to 1.0"):
            PaymentYearWindow(
                year=9999,
                dos_start=date(9998, 1, 1),
                dos_end=date(9998, 12, 31),
                model_blend={"V28": 0.5},  # sums to 0.5, not 1.0
            )

    def test_invalid_date_range_raises_value_error(self):
        from app.services.raf.dos_rules import PaymentYearWindow
        with pytest.raises(ValueError, match="before dos_start"):
            PaymentYearWindow(
                year=9999,
                dos_start=date(9998, 12, 31),
                dos_end=date(9998, 1, 1),  # end before start
                model_blend={"V28": 1.0},
            )
