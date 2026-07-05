"""
Expanded RAF Calculation Engine tests — pure-logic / source-inspection.

Covers: processor singletons, age calculation, sex normalization, ICD-10
formatting, age-band mapping, blend weights, ESRD/NE coefficients, and
_run_single_model return-key contract.

No database or network required.
"""
from __future__ import annotations

import inspect
from datetime import date

import pytest


# ---------------------------------------------------------------------------
# 1. Processor singletons exist and are non-None
# ---------------------------------------------------------------------------

class TestProcessorSingletons:
    """All 5 hccinfhir processor singletons must be initialized at import."""

    def test_processor_v28_initialized(self):
        from app.services.raf.calculator import _processor_v28
        assert _processor_v28 is not None

    def test_processor_v24_initialized(self):
        from app.services.raf.calculator import _processor_v24
        assert _processor_v24 is not None

    def test_processor_v22_initialized(self):
        from app.services.raf.calculator import _processor_v22
        assert _processor_v22 is not None

    def test_processor_esrd_v24_initialized(self):
        from app.services.raf.calculator import _processor_esrd_v24
        assert _processor_esrd_v24 is not None

    def test_backward_compat_alias_is_v28(self):
        from app.services.raf.calculator import _processor, _processor_v28
        assert _processor is _processor_v28


# ---------------------------------------------------------------------------
# 2. Age calculation (CMS Feb 1 reference date)
# ---------------------------------------------------------------------------

class TestCalculateAge:
    """CMS uses February 1 of measurement year as the age reference date."""

    def test_born_after_feb1_same_year(self):
        from app.services.raf.calculator import _calculate_age
        # Born 1950-03-15, measurement year 2026 -> age on Feb 1, 2026 = 75
        assert _calculate_age("1950-03-15", 2026) == 75

    def test_born_before_feb1_same_year(self):
        from app.services.raf.calculator import _calculate_age
        # Born 1950-01-15, measurement year 2026 -> age on Feb 1, 2026 = 76
        assert _calculate_age("1950-01-15", 2026) == 76

    def test_born_on_feb1(self):
        from app.services.raf.calculator import _calculate_age
        # Born 1950-02-01 -> on Feb 1 2026 = exactly 76
        assert _calculate_age("1950-02-01", 2026) == 76

    def test_born_on_feb2(self):
        from app.services.raf.calculator import _calculate_age
        # Born 1950-02-02 -> on Feb 1 2026 = 75 (birthday hasn't happened yet)
        assert _calculate_age("1950-02-02", 2026) == 75

    def test_accepts_date_object(self):
        from app.services.raf.calculator import _calculate_age
        assert _calculate_age(date(1960, 6, 15), 2026) == 65

    def test_age_never_negative(self):
        from app.services.raf.calculator import _calculate_age
        # Future DOB should clamp to 0
        assert _calculate_age("2030-01-01", 2026) == 0

    def test_calc_age_alias_matches(self):
        from app.services.raf.calculator import _calc_age, _calculate_age
        assert _calc_age is _calculate_age


# ---------------------------------------------------------------------------
# 3. Sex code normalization
# ---------------------------------------------------------------------------

class TestSexCode:
    """_sex_code must normalize varied sex representations."""

    def test_male_short(self):
        from app.services.raf.calculator import _sex_code
        assert _sex_code("M") == "M"

    def test_male_full(self):
        from app.services.raf.calculator import _sex_code
        assert _sex_code("Male") == "M"

    def test_female_short(self):
        from app.services.raf.calculator import _sex_code
        assert _sex_code("F") == "F"

    def test_female_full(self):
        from app.services.raf.calculator import _sex_code
        assert _sex_code("Female") == "F"

    def test_empty_defaults_to_m(self):
        from app.services.raf.calculator import _sex_code
        assert _sex_code("") == "M"

    def test_none_defaults_to_m(self):
        from app.services.raf.calculator import _sex_code
        assert _sex_code(None) == "M"

    def test_lowercase_female(self):
        from app.services.raf.calculator import _sex_code
        assert _sex_code("female") == "F"


# ---------------------------------------------------------------------------
# 4. ICD-10 formatting (_format_icd10)
# ---------------------------------------------------------------------------

class TestFormatIcd10:
    """_format_icd10 adds the dot back to dotless ICD-10 codes."""

    def test_adds_dot_to_four_char(self):
        from app.services.raf.icd_formatter import _format_icd10
        assert _format_icd10("E119") == "E11.9"

    def test_adds_dot_to_five_char(self):
        from app.services.raf.icd_formatter import _format_icd10
        assert _format_icd10("E1165") == "E11.65"

    def test_preserves_existing_dot(self):
        from app.services.raf.icd_formatter import _format_icd10
        assert _format_icd10("E11.9") == "E11.9"

    def test_uppercases_code(self):
        from app.services.raf.icd_formatter import _format_icd10
        assert _format_icd10("e119") == "E11.9"

    def test_three_char_code_unchanged(self):
        from app.services.raf.icd_formatter import _format_icd10
        assert _format_icd10("N18") == "N18"

    def test_strips_whitespace(self):
        from app.services.raf.icd_formatter import _format_icd10
        assert _format_icd10("  I509  ") == "I50.9"


# ---------------------------------------------------------------------------
# 5. Age band mapping
# ---------------------------------------------------------------------------

class TestAgeBand:
    """_get_age_band_from_age must return correct CMS age bands."""

    def test_under_35(self):
        from app.services.raf.score_persistence import _get_age_band_from_age
        assert _get_age_band_from_age(0) == "0-34"
        assert _get_age_band_from_age(34) == "0-34"

    def test_35_44(self):
        from app.services.raf.score_persistence import _get_age_band_from_age
        assert _get_age_band_from_age(35) == "35-44"
        assert _get_age_band_from_age(44) == "35-44"

    def test_45_54(self):
        from app.services.raf.score_persistence import _get_age_band_from_age
        assert _get_age_band_from_age(45) == "45-54"
        assert _get_age_band_from_age(54) == "45-54"

    def test_65_69(self):
        from app.services.raf.score_persistence import _get_age_band_from_age
        assert _get_age_band_from_age(65) == "65-69"
        assert _get_age_band_from_age(69) == "65-69"

    def test_95_plus(self):
        from app.services.raf.score_persistence import _get_age_band_from_age
        assert _get_age_band_from_age(95) == "95+"
        assert _get_age_band_from_age(110) == "95+"


# ---------------------------------------------------------------------------
# 6. Blend weights sum to one
# ---------------------------------------------------------------------------

class TestBlendWeights:
    """Model blend weights must sum to 1.0 for every payment year."""

    def test_all_payment_years_blend_sums_to_one(self):
        from app.services.raf.dos_rules import PAYMENT_YEARS
        for year, pw in PAYMENT_YEARS.items():
            total = sum(pw.model_blend.values())
            assert abs(total - 1.0) < 0.001, f"PY{year} blend sums to {total}"

    def test_py2026_is_100_percent_v28(self):
        from app.services.raf.dos_rules import PAYMENT_YEARS
        assert PAYMENT_YEARS[2026].model_blend.get("V28") == 1.0

    def test_py2024_blend_67_33(self):
        from app.services.raf.dos_rules import PAYMENT_YEARS
        assert abs(PAYMENT_YEARS[2024].model_blend["V24"] - 0.67) < 0.01
        assert abs(PAYMENT_YEARS[2024].model_blend["V28"] - 0.33) < 0.01


# ---------------------------------------------------------------------------
# 7. ESRD demographic scores
# ---------------------------------------------------------------------------

class TestEsrdDemoScores:
    """ESRD demographic coefficient tables must be populated."""

    def test_esrd_dly_scores_populated(self):
        from app.services.raf.calculator import _ESRD_DLY_DEMO_SCORES
        assert len(_ESRD_DLY_DEMO_SCORES) > 0

    def test_esrd_fg_scores_populated(self):
        from app.services.raf.calculator import _ESRD_FG_DEMO_SCORES
        assert len(_ESRD_FG_DEMO_SCORES) > 0

    def test_esrd_dly_covers_all_age_bands(self):
        from app.services.raf.calculator import _ESRD_DLY_DEMO_SCORES
        expected_bands = ["0-34", "35-44", "45-54", "55-59", "60-64",
                         "65-69", "70-74", "75-79", "80-84", "85-89",
                         "90-94", "95+"]
        for band in expected_bands:
            assert (band, "M") in _ESRD_DLY_DEMO_SCORES, f"Missing ({band}, M)"
            assert (band, "F") in _ESRD_DLY_DEMO_SCORES, f"Missing ({band}, F)"

    def test_esrd_scores_are_positive(self):
        from app.services.raf.calculator import _ESRD_DLY_DEMO_SCORES
        for key, val in _ESRD_DLY_DEMO_SCORES.items():
            assert val > 0, f"ESRD DLY score for {key} should be positive"


# ---------------------------------------------------------------------------
# 8. New Enrollee coefficients
# ---------------------------------------------------------------------------

class TestNewEnrolleeCoefficients:
    """NE demographic coefficient tables must exist and be well-formed."""

    def test_ne_demo_scores_populated(self):
        from app.services.raf.calculator import _NE_DEMO_SCORES
        assert len(_NE_DEMO_SCORES) > 0

    def test_ne_cms_coefficients_has_four_segments(self):
        from app.services.raf.calculator import _NE_CMS_COEFFICIENTS
        assert len(_NE_CMS_COEFFICIENTS) == 4

    def test_ne_coefficients_positive(self):
        from app.services.raf.calculator import _NE_CMS_COEFFICIENTS
        for seg, coeffs in _NE_CMS_COEFFICIENTS.items():
            for key, val in coeffs.items():
                assert val > 0, f"NE coeff for {seg}/{key} should be positive"


# ---------------------------------------------------------------------------
# 9. _run_single_model return-key contract (source inspection)
# ---------------------------------------------------------------------------

class TestRunSingleModelContract:
    """_run_single_model must return a dict with all required keys."""

    def test_return_keys_present_in_source(self):
        from app.services.raf.calculator import _run_single_model
        source = inspect.getsource(_run_single_model)
        required_keys = [
            "raw_raf", "payment_raf", "demographic_score", "disease_score",
            "interaction_score", "hcc_list", "norm_factor", "maci_factor",
        ]
        for key in required_keys:
            assert (f'"{key}"' in source or f"'{key}'" in source), (
                f"Missing return key '{key}' in _run_single_model"
            )

    def test_maci_formula_present_in_calculator(self):
        """payment_raf = raw * (1 - maci) / norm formula must be in calculator module."""
        import app.services.raf.calculator as calc_mod
        source = inspect.getsource(calc_mod)
        # The formula uses (1 - maci) in the calculate_raf_score flow
        assert "(1 - maci)" in source, (
            "MACI adjustment formula '(1 - maci)' missing from calculator module"
        )


# ---------------------------------------------------------------------------
# 10. ESRD code sets
# ---------------------------------------------------------------------------

class TestEsrdCodeSets:
    """ESRD indicator code sets must include critical codes."""

    def test_dialysis_codes_include_z992(self):
        from app.services.raf.icd_formatter import _ESRD_DIALYSIS_CODES
        assert "Z992" in _ESRD_DIALYSIS_CODES or "Z99.2" in _ESRD_DIALYSIS_CODES

    def test_functioning_graft_codes_include_z940(self):
        from app.services.raf.icd_formatter import _ESRD_FUNCTIONING_GRAFT_CODES
        assert "Z940" in _ESRD_FUNCTIONING_GRAFT_CODES or "Z94.0" in _ESRD_FUNCTIONING_GRAFT_CODES

    def test_code_sets_are_frozensets(self):
        from app.services.raf.icd_formatter import (
            _ESRD_DIALYSIS_CODES,
            _ESRD_FUNCTIONING_GRAFT_CODES,
        )
        assert isinstance(_ESRD_DIALYSIS_CODES, frozenset)
        assert isinstance(_ESRD_FUNCTIONING_GRAFT_CODES, frozenset)
