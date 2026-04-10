"""
RAF Intelligence — Unit Tests for Enterprise Features
=======================================================
Tests: ESRD segments, New Enrollee model, Sweep Periods, Frailty Adjuster,
       and coefficient table completeness.

Run with:
    cd backend && python -m pytest tests/test_raf_features.py -v
"""
from __future__ import annotations

import sys
import os
from datetime import date, timedelta

import pytest

# ── make app importable without installing ─────────────────────────────────
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# ===========================================================================
# ESRD Model Segment Routing
# ===========================================================================

class TestESRDSegments:
    """Verify that determine_model_segment routes ESRD correctly."""

    def _get_segment(self, **kwargs):
        from app.services.raf_calculator import determine_model_segment
        defaults = dict(
            age=68, sex="M", dual_status="non_dual",
            orec="0", institutional=False,
            icd_codes=[], enrollment_months=12,
        )
        defaults.update(kwargs)
        return determine_model_segment(**defaults)

    def test_community_non_aged_non_dual(self):
        seg = self._get_segment(orec="0", dual_status="non_dual")
        assert seg == "CNA", f"Expected CNA, got {seg}"

    def test_esrd_dialysis_segment(self):
        """OREC=2 + dialysis ICD → ESRD_DLY segment."""
        seg = self._get_segment(orec="2", icd_codes=["Z992"])
        assert seg == "ESRD_DLY", f"Expected ESRD_DLY, got {seg}"

    def test_esrd_functioning_graft(self):
        """OREC=2 + transplant ICD → ESRD_FG segment."""
        seg = self._get_segment(orec="2", icd_codes=["Z940"])
        assert seg == "ESRD_FG", f"Expected ESRD_FG, got {seg}"

    def test_esrd_new_enrollee(self):
        """OREC=2 or 3 + enrollment_months<12 → ESRD_NE segment."""
        seg = self._get_segment(orec="2", enrollment_months=6, icd_codes=[])
        assert seg == "ESRD_NE", f"Expected ESRD_NE, got {seg}"

    def test_orec3_esrd_new_enrollee(self):
        """OREC=3 (disabled+ESRD) + no Part B months → ESRD_NE."""
        seg = self._get_segment(orec="3", enrollment_months=3, icd_codes=[])
        assert seg == "ESRD_NE", f"Expected ESRD_NE, got {seg}"

    def test_institutional_segment(self):
        """Institutional flag → INS segment."""
        seg = self._get_segment(institutional=True)
        assert seg == "INS", f"Expected INS, got {seg}"

    def test_community_full_dual(self):
        seg = self._get_segment(dual_status="full_dual")
        assert seg in ("CFD", "CFA"), f"Expected CFD/CFA, got {seg}"


# ===========================================================================
# New Enrollee Model
# ===========================================================================

class TestNewEnrolleeModel:
    """Verify demographic-only path for patients with <12 months Part B."""

    def _ne_result(self, months: int, age: int = 67, sex: str = "F",
                   dual: str = "non_dual") -> dict:
        """
        Directly test the NE score branch in raf_calculator without DB.
        We patch _get_patient and _get_icd_codes to avoid DB calls.
        """
        from app.services.raf_calculator import (
            _NE_DEMO_SCORES, _calculate_age, determine_model_segment,
        )
        # Determine segment
        seg = determine_model_segment(
            age=age, sex=sex, dual_status=dual,
            orec="0", institutional=False,
            icd_codes=[], enrollment_months=months,
        )
        is_ne = months < 12 and seg.startswith("NE")
        # Look up NE demo score
        age_band = "65-69" if 65 <= age < 70 else "70-74" if age < 75 else "75-79"
        score = _NE_DEMO_SCORES.get((age_band, sex, seg), 0.0)
        return {"is_new_enrollee": is_ne, "segment": seg, "ne_demo_score": score}

    def test_ne_flag_triggered_at_11_months(self):
        r = self._ne_result(months=11)
        assert r["is_new_enrollee"] is True, "Should be NE with 11 months"

    def test_ne_flag_not_triggered_at_12_months(self):
        r = self._ne_result(months=12)
        assert r["is_new_enrollee"] is False, "Should NOT be NE with 12 months"

    def test_ne_segment_assigned(self):
        r = self._ne_result(months=6)
        assert r["segment"].startswith("NE"), f"Expected NE* segment, got {r['segment']}"

    def test_ne_demo_scores_populated(self):
        """_NE_DEMO_SCORES table should have entries."""
        from app.services.raf_calculator import _NE_DEMO_SCORES
        assert len(_NE_DEMO_SCORES) > 0, "_NE_DEMO_SCORES table empty"
        for key, val in _NE_DEMO_SCORES.items():
            assert isinstance(val, float), f"Non-float score for key {key}"
            assert val > 0, f"Zero/negative score for key {key}"


# ===========================================================================
# Sweep Period Date Filtering
# ===========================================================================

class TestSweepPeriods:
    """Verify CMS sweep window logic."""

    def test_initial_sweep_includes_q1(self):
        from app.services.sweep_periods import get_sweep_window
        win = get_sweep_window(2026, "initial")
        assert win["start"].month == 1
        assert win["end"].month == 3

    def test_midyear_sweep_ends_june(self):
        from app.services.sweep_periods import get_sweep_window
        win = get_sweep_window(2026, "midyear")
        assert win["end"].month == 6

    def test_final_sweep_ends_december(self):
        from app.services.sweep_periods import get_sweep_window
        win = get_sweep_window(2026, "final")
        assert win["end"].month == 12

    def test_icd_code_inside_window_passes(self):
        from app.services.sweep_periods import filter_codes_by_sweep
        code = {"icd_code": "E11.9", "date_of_service": "2026-02-15"}
        result = filter_codes_by_sweep([code], payment_year=2026, sweep="initial")
        assert len(result) == 1

    def test_icd_code_outside_window_filtered(self):
        from app.services.sweep_periods import filter_codes_by_sweep
        # April code should be excluded from initial sweep (Jan-Mar only)
        code = {"icd_code": "E11.9", "date_of_service": "2026-04-10"}
        result = filter_codes_by_sweep([code], payment_year=2026, sweep="initial")
        assert len(result) == 0

    def test_no_sweep_returns_all_codes(self):
        from app.services.sweep_periods import filter_codes_by_sweep
        codes = [
            {"icd_code": "E11.9", "date_of_service": "2026-01-15"},
            {"icd_code": "I10",   "date_of_service": "2026-09-20"},
        ]
        result = filter_codes_by_sweep(codes, payment_year=2026, sweep=None)
        assert len(result) == 2

    def test_codes_without_dos_pass_through(self):
        """Codes missing date_of_service should pass through (avoid dropping valid data)."""
        from app.services.sweep_periods import filter_codes_by_sweep
        code = {"icd_code": "I50.9"}  # no date_of_service
        result = filter_codes_by_sweep([code], payment_year=2026, sweep="initial")
        assert len(result) == 1


# ===========================================================================
# Frailty Adjuster
# ===========================================================================

class TestFrailtyAdjuster:
    """Verify PACE/FIDE-SNP frailty addend calculations."""

    def _calc(self, adl_impairments: int, plan_type: str = "PACE",
              payment_year: int = 2026) -> dict:
        from app.services.frailty_adjuster import compute_frailty_adjustment
        adl_data = {
            "bathing":      adl_impairments >= 1,
            "dressing":     adl_impairments >= 2,
            "eating":       adl_impairments >= 3,
            "toileting":    adl_impairments >= 4,
            "transferring": adl_impairments >= 5,
            "continence":   adl_impairments >= 6,
        }
        return compute_frailty_adjustment(adl_data, plan_type, payment_year)

    def test_no_adls_no_frailty(self):
        r = self._calc(0)
        assert r["frailty_addend"] == 0.0
        assert r["is_frail"] is False

    def test_two_adls_no_frailty(self):
        """CMS frailty threshold is ≥3 ADLs."""
        r = self._calc(2)
        assert r["frailty_addend"] == 0.0
        assert r["is_frail"] is False

    def test_three_adls_triggers_frailty(self):
        r = self._calc(3)
        assert r["is_frail"] is True
        assert r["frailty_addend"] > 0.0

    def test_six_adls_max_addend(self):
        r3 = self._calc(3)
        r6 = self._calc(6)
        assert r6["frailty_addend"] >= r3["frailty_addend"]

    def test_ma_plan_no_frailty(self):
        """Standard MA plans do not receive frailty adjustments."""
        r = self._calc(6, plan_type="MA")
        assert r["frailty_addend"] == 0.0
        assert r["is_frail"] is False

    def test_fide_snp_receives_frailty(self):
        r = self._calc(4, plan_type="FIDE_SNP")
        assert r["is_frail"] is True
        assert r["frailty_addend"] > 0.0

    def test_addend_is_positive_float(self):
        r = self._calc(5)
        assert isinstance(r["frailty_addend"], float)
        assert r["frailty_addend"] > 0.0

    def test_adl_count_returned(self):
        r = self._calc(4)
        assert r["adl_count"] == 4


# ===========================================================================
# Coefficient Table Completeness
# ===========================================================================

class TestCoefficientTableCompleteness:
    """Ensure all coefficient tables have the required minimum number of entries."""

    def test_rxhcc_icd_map_minimum_size(self):
        from app.services.multi_model_calculator import _RXHCC_ICD_MAP
        assert len(_RXHCC_ICD_MAP) >= 80, \
            f"_RXHCC_ICD_MAP has only {len(_RXHCC_ICD_MAP)} entries, expected ≥80"

    def test_rxhcc_coefficients_minimum_size(self):
        from app.services.multi_model_calculator import _RXHCC_COEFFICIENTS
        assert len(_RXHCC_COEFFICIENTS) >= 50, \
            f"_RXHCC_COEFFICIENTS has only {len(_RXHCC_COEFFICIENTS)} entries"

    def test_hhshcc_icd_map_minimum_size(self):
        from app.services.multi_model_calculator import _HHSHCC_ICD_MAP
        assert len(_HHSHCC_ICD_MAP) >= 80, \
            f"_HHSHCC_ICD_MAP has only {len(_HHSHCC_ICD_MAP)} entries"

    def test_hhshcc_coefficients_minimum_size(self):
        from app.services.multi_model_calculator import _HHSHCC_COEFFICIENTS
        assert len(_HHSHCC_COEFFICIENTS) >= 50, \
            f"_HHSHCC_COEFFICIENTS has only {len(_HHSHCC_COEFFICIENTS)} entries"

    def test_hhshcc_coefficients_have_required_fields(self):
        from app.services.multi_model_calculator import _HHSHCC_COEFFICIENTS
        for hcc_id, entry in _HHSHCC_COEFFICIENTS.items():
            assert "description" in entry, f"HCC {hcc_id} missing 'description'"
            assert "adult" in entry, f"HCC {hcc_id} missing 'adult' coefficient"
            assert "child" in entry, f"HCC {hcc_id} missing 'child' coefficient"
            assert isinstance(entry["adult"], float), \
                f"HCC {hcc_id} 'adult' should be float"

    def test_rxhcc_coefficients_have_required_fields(self):
        from app.services.multi_model_calculator import _RXHCC_COEFFICIENTS
        for rxhcc, entry in _RXHCC_COEFFICIENTS.items():
            assert "NLI_F" in entry, f"RxHCC {rxhcc} missing 'NLI_F'"
            assert "NLI_M" in entry, f"RxHCC {rxhcc} missing 'NLI_M'"
            assert "LI_F"  in entry, f"RxHCC {rxhcc} missing 'LI_F'"
            assert "LI_M"  in entry, f"RxHCC {rxhcc} missing 'LI_M'"

    def test_critical_rxhcc_present(self):
        """Key high-cost RxHCCs must always be present."""
        from app.services.multi_model_calculator import _RXHCC_COEFFICIENTS
        critical = [1, 5, 72, 77, 80, 112, 130, 211, 212, 253]
        for hcc in critical:
            assert hcc in _RXHCC_COEFFICIENTS, \
                f"Critical RxHCC {hcc} missing from coefficient table"

    def test_critical_hhshcc_present(self):
        from app.services.multi_model_calculator import _HHSHCC_COEFFICIENTS
        critical = [1, 8, 18, 41, 57, 67, 73, 77, 82, 110, 132]
        for hcc in critical:
            assert hcc in _HHSHCC_COEFFICIENTS, \
                f"Critical HHS-HCC {hcc} missing from coefficient table"

    def test_icd_maps_no_zero_hcc(self):
        """No ICD should map to HCC 0."""
        from app.services.multi_model_calculator import _RXHCC_ICD_MAP, _HHSHCC_ICD_MAP
        for icd, hcc in _RXHCC_ICD_MAP.items():
            assert hcc != 0, f"ICD '{icd}' maps to RxHCC 0 (invalid)"
        for icd, hcc in _HHSHCC_ICD_MAP.items():
            assert hcc != 0, f"ICD '{icd}' maps to HHS-HCC 0 (invalid)"


# ===========================================================================
# API Model Validation (schema-only, no DB)
# ===========================================================================

class TestAPIRequestModel:
    """Validate that CalculateRequest Pydantic model accepts new fields."""

    def test_default_request_valid(self):
        from app.routers.raf import CalculateRequest
        req = CalculateRequest()
        assert req.enrollment_months == 12
        assert req.plan_type == "MA"
        assert req.sweep_period is None
        assert req.adl_data is None

    def test_enrollment_months_bounds(self):
        from app.routers.raf import CalculateRequest
        import pydantic
        with pytest.raises((pydantic.ValidationError, ValueError)):
            CalculateRequest(enrollment_months=0)
        with pytest.raises((pydantic.ValidationError, ValueError)):
            CalculateRequest(enrollment_months=13)

    def test_sweep_period_valid_values(self):
        from app.routers.raf import CalculateRequest
        for v in ("initial", "midyear", "final", "none", None):
            req = CalculateRequest(sweep_period=v)
            assert req.sweep_period == v

    def test_adl_data_model_defaults_false(self):
        from app.routers.raf import ADLDataModel
        adl = ADLDataModel()
        assert adl.bathing is False
        assert adl.dressing is False
        assert adl.eating is False
        assert adl.toileting is False
        assert adl.transferring is False
        assert adl.continence is False

    def test_adl_data_round_trip(self):
        from app.routers.raf import ADLDataModel
        adl = ADLDataModel(bathing=True, eating=True, continence=True)
        d = adl.model_dump()
        assert d["bathing"] is True
        assert d["eating"] is True
        assert d["continence"] is True
        assert d["dressing"] is False
