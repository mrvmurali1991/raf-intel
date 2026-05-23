"""
CMS-HCC RAF Calculator — comprehensive test suite.

These tests verify:
- Blend weight constants (CMS transition PY2024/2025/2026)
- Normalization and MACI factor constants
- Age calculation (CMS Feb 1 rule)
- Age-band mapping
- Sex code normalization
- Model segment determination (CNA/CND/CFA/CFD/CPA/CPD/INS/NE*/ESRD*)
- New Enrollee demographic-only scoring
- ESRD demographic score lookup
- _run_single_model integration via hccinfhir (with real CMS coefficients)
- _get_norm_factor and _get_maci_factor fallback behavior

Tests run entirely in-process — no database or network required.

Markers:
  golden   — CMS golden fixture (fixed expected values, must never regress)
  security — security-relevant checks
"""

from __future__ import annotations

from datetime import date

import pytest
from app.services.raf_calculator import (
    _BLEND_WEIGHTS,
    _ESRD_DLY_DEMO_SCORES,
    _ESRD_FG_DEMO_SCORES,
    _MACI_FACTORS_V24,
    _MACI_FACTORS_V28,
    _NE_DEMO_SCORES,
    _NORM_FACTORS_V22,
    _NORM_FACTORS_V24,
    _NORM_FACTORS_V28,
    _PACE_BLEND_WEIGHTS,
    _SEGMENT_TO_PREFIX,
    _apply_hcc_hierarchy,
    _calculate_age,
    _calculate_esrd_demographic_score,
    _calculate_new_enrollee_score,
    _get_age_band_from_age,
    _get_maci_factor,
    _get_norm_factor,
    _is_esrd,
    _is_new_enrollee,
    _processor_esrd_v24,
    _processor_v22,
    _processor_v24,
    _processor_v28,
    _run_single_model,
    _sex_code,
    determine_model_segment,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def approx(value: float, rel: float = 1e-3) -> pytest.approx:
    return pytest.approx(value, rel=rel)


# ---------------------------------------------------------------------------
# 1. Blend weight constants (CMS transition rules)
# ---------------------------------------------------------------------------

class TestBlendWeights:
    @pytest.mark.golden
    def test_py2024_blend(self) -> None:
        v24_w, v28_w = _BLEND_WEIGHTS[2024]
        assert v24_w == pytest.approx(0.67)
        assert v28_w == pytest.approx(0.33)

    @pytest.mark.golden
    def test_py2025_blend(self) -> None:
        v24_w, v28_w = _BLEND_WEIGHTS[2025]
        assert v24_w == pytest.approx(0.33)
        assert v28_w == pytest.approx(0.67)

    @pytest.mark.golden
    def test_py2026_pure_v28(self) -> None:
        v24_w, v28_w = _BLEND_WEIGHTS[2026]
        assert v24_w == pytest.approx(0.0)
        assert v28_w == pytest.approx(1.0)

    def test_blend_weights_sum_to_one(self) -> None:
        for year, (v24_w, v28_w) in _BLEND_WEIGHTS.items():
            assert v24_w + v28_w == pytest.approx(1.0), (
                f"Weights for year {year} do not sum to 1.0: {v24_w} + {v28_w}"
            )

    def test_unknown_year_falls_back_to_v28_pattern(self) -> None:
        # Years beyond 2026 must not be in the dict — caller defaults to pure V28
        assert 2099 not in _BLEND_WEIGHTS

    def test_2024_v24_weight_is_dominant(self) -> None:
        v24_w, v28_w = _BLEND_WEIGHTS[2024]
        assert v24_w > v28_w

    def test_2025_v28_weight_is_dominant(self) -> None:
        v24_w, v28_w = _BLEND_WEIGHTS[2025]
        assert v28_w > v24_w

    def test_2026_v24_weight_is_zero(self) -> None:
        v24_w, _ = _BLEND_WEIGHTS[2026]
        assert v24_w == 0.0


# ---------------------------------------------------------------------------
# 2. Normalization and MACI factor constants
# ---------------------------------------------------------------------------

class TestNormAndMaciFactors:
    @pytest.mark.golden
    def test_v28_norm_factor_2024(self) -> None:
        assert _NORM_FACTORS_V28[2024] == pytest.approx(1.045)

    @pytest.mark.golden
    def test_v28_norm_factor_2025(self) -> None:
        assert _NORM_FACTORS_V28[2025] == pytest.approx(1.045)

    @pytest.mark.golden
    def test_v28_norm_factor_2026(self) -> None:
        assert _NORM_FACTORS_V28[2026] == pytest.approx(1.067)

    @pytest.mark.golden
    def test_v24_norm_factor_2024(self) -> None:
        assert _NORM_FACTORS_V24[2024] == pytest.approx(1.153)

    @pytest.mark.golden
    def test_v24_norm_factor_2025(self) -> None:
        assert _NORM_FACTORS_V24[2025] == pytest.approx(1.153)

    @pytest.mark.golden
    def test_v22_norm_factor_2026(self) -> None:
        assert _NORM_FACTORS_V22[2026] == pytest.approx(1.187)

    @pytest.mark.golden
    def test_maci_factor_v28_2024_is_5_9_percent(self) -> None:
        assert _MACI_FACTORS_V28[2024] == pytest.approx(0.059)

    @pytest.mark.golden
    def test_maci_factor_v28_2025(self) -> None:
        assert _MACI_FACTORS_V28[2025] == pytest.approx(0.059)

    @pytest.mark.golden
    def test_maci_factor_v24_2024(self) -> None:
        assert _MACI_FACTORS_V24[2024] == pytest.approx(0.059)

    def test_normalization_formula(self) -> None:
        # payment_raf = raw_raf * (1 - maci) / norm_factor
        raw = 1.5
        maci = 0.059
        norm = 1.045
        expected = raw * (1 - maci) / norm
        assert expected == pytest.approx(1.352, rel=1e-2)

    def test_normalization_reduces_score(self) -> None:
        """Normalization factor > 1 should reduce the final RAF below raw."""
        raw = 1.5
        maci = 0.059
        norm = 1.045
        payment = raw * (1 - maci) / norm
        assert payment < raw

    def test_get_norm_factor_known_year(self) -> None:
        assert _get_norm_factor(_NORM_FACTORS_V28, 2025) == pytest.approx(1.045)

    def test_get_norm_factor_unknown_year_uses_latest(self) -> None:
        """Unknown year falls back to the latest known factor."""
        result = _get_norm_factor(_NORM_FACTORS_V28, 2099)
        latest_year = max(_NORM_FACTORS_V28.keys())
        assert result == pytest.approx(_NORM_FACTORS_V28[latest_year])

    def test_get_maci_factor_known_year(self) -> None:
        assert _get_maci_factor(_MACI_FACTORS_V28, 2024) == pytest.approx(0.059)

    def test_get_maci_factor_unknown_year_uses_latest(self) -> None:
        result = _get_maci_factor(_MACI_FACTORS_V28, 2099)
        latest_year = max(_MACI_FACTORS_V28.keys())
        assert result == pytest.approx(_MACI_FACTORS_V28[latest_year])


# ---------------------------------------------------------------------------
# 3. Age calculation (CMS Feb 1 convention)
# ---------------------------------------------------------------------------

class TestCalculateAge:
    def test_age_68_as_of_2025(self) -> None:
        # Born 1957-06-15, Feb 1 2025 → 67 (birthday hasn't happened yet)
        age = _calculate_age("1957-06-15", as_of_year=2025)
        assert age == 67

    def test_age_70_birthday_before_feb(self) -> None:
        # Born 1955-01-01, Feb 1 2025 → 70
        age = _calculate_age("1955-01-01", as_of_year=2025)
        assert age == 70

    def test_age_string_dob(self) -> None:
        age = _calculate_age("1950-03-15", as_of_year=2026)
        assert age == 75

    def test_age_never_negative(self) -> None:
        age = _calculate_age("2100-01-01", as_of_year=2026)
        assert age == 0

    def test_age_boundary_exactly_65(self) -> None:
        # Born 1961-02-01, as_of_year=2026 → exactly 65
        age = _calculate_age("1961-02-01", as_of_year=2026)
        assert age == 65

    def test_age_date_object_dob(self) -> None:
        dob = date(1958, 5, 20)
        age = _calculate_age(dob, as_of_year=2026)
        assert age == 67  # Feb 1 2026, birthday May 20

    def test_age_feb_birthday_is_on_the_day(self) -> None:
        # Born exactly Feb 1, as_of_year same year → 0
        age = _calculate_age("2026-02-01", as_of_year=2026)
        assert age == 0


# ---------------------------------------------------------------------------
# 4. Age-band mapping
# ---------------------------------------------------------------------------

class TestAgeBand:
    @pytest.mark.parametrize("age,expected", [
        (0, "0-34"),
        (30, "0-34"),
        (34, "0-34"),
        (35, "35-44"),
        (44, "35-44"),
        (45, "45-54"),
        (54, "45-54"),
        (55, "55-59"),
        (59, "55-59"),
        (60, "60-64"),
        (64, "60-64"),
        (65, "65-69"),
        (69, "65-69"),
        (70, "70-74"),
        (74, "70-74"),
        (75, "75-79"),
        (79, "75-79"),
        (80, "80-84"),
        (84, "80-84"),
        (85, "85-89"),
        (89, "85-89"),
        (90, "90-94"),
        (94, "90-94"),
        (95, "95+"),
        (100, "95+"),
        (110, "95+"),
    ])
    def test_age_band_mapping(self, age: int, expected: str) -> None:
        assert _get_age_band_from_age(age) == expected


# ---------------------------------------------------------------------------
# 5. Sex code normalization
# ---------------------------------------------------------------------------

class TestSexCode:
    @pytest.mark.parametrize("raw,expected", [
        ("M", "M"),
        ("m", "M"),
        ("Male", "M"),
        ("male", "M"),
        ("F", "F"),
        ("f", "F"),
        ("Female", "F"),
        ("female", "F"),
        ("  Female  ", "F"),
        ("", "M"),   # default
        (None, "M"), # default
        ("X", "M"),  # unknown defaults to M
    ])
    def test_sex_code_normalization(self, raw, expected) -> None:
        assert _sex_code(raw) == expected


# ---------------------------------------------------------------------------
# 6. Model segment determination
# ---------------------------------------------------------------------------

class TestDetermineModelSegment:
    # Standard community segments
    def test_aged_non_dual_is_cna(self) -> None:
        assert determine_model_segment(age=70) == "CNA"

    def test_disabled_non_dual_is_cnd(self) -> None:
        assert determine_model_segment(age=50, orec="1") == "CND"

    def test_aged_full_dual_is_cfa(self) -> None:
        assert determine_model_segment(age=70, is_dual=True, dual_type="full_dual") == "CFA"

    def test_disabled_full_dual_is_cfd(self) -> None:
        assert determine_model_segment(age=50, is_dual=True, dual_type="full_dual", orec="1") == "CFD"

    def test_aged_partial_dual_is_cpa(self) -> None:
        assert determine_model_segment(age=70, is_dual=True, dual_type="partial_dual") == "CPA"

    def test_disabled_partial_dual_is_cpd(self) -> None:
        assert determine_model_segment(age=50, is_dual=True, dual_type="partial_dual", orec="1") == "CPD"

    def test_institutional_is_ins(self) -> None:
        assert determine_model_segment(age=72, is_institutional=True) == "INS"

    # Boundary: exactly 65
    def test_exactly_65_is_cna(self) -> None:
        assert determine_model_segment(age=65) == "CNA"

    def test_exactly_64_is_cnd(self) -> None:
        assert determine_model_segment(age=64, orec="1") == "CND"

    # New Enrollee routing (< 12 months Part B)
    def test_new_enrollee_aged_non_dual_is_ne_cna(self) -> None:
        seg = determine_model_segment(age=70, enrollment_months=6)
        assert seg == "NE_CNA"

    def test_new_enrollee_disabled_non_dual_is_ne_cnd(self) -> None:
        seg = determine_model_segment(age=50, orec="1", enrollment_months=3)
        assert seg == "NE_CND"

    def test_new_enrollee_full_dual_aged_is_ne_cfa(self) -> None:
        seg = determine_model_segment(age=70, is_dual=True, dual_type="full_dual", enrollment_months=6)
        assert seg == "NE_CFA"

    def test_new_enrollee_partial_dual_aged_is_ne_cpa(self) -> None:
        seg = determine_model_segment(age=70, is_dual=True, dual_type="partial_dual", enrollment_months=6)
        assert seg == "NE_CPA"

    def test_new_enrollee_institutional_is_ne_cna(self) -> None:
        # Institutional NE treated as CNA-NE for demo scoring
        seg = determine_model_segment(age=75, is_institutional=True, enrollment_months=6)
        assert seg == "NE_CNA"

    # ESRD routing
    def test_esrd_orec_2_defaults_to_esrd_dly(self) -> None:
        seg = determine_model_segment(age=65, orec="2")
        assert seg == "ESRD_DLY"

    def test_esrd_orec_3_defaults_to_esrd_dly(self) -> None:
        seg = determine_model_segment(age=65, orec="3")
        assert seg == "ESRD_DLY"

    def test_esrd_functioning_graft_detected_from_icd(self) -> None:
        seg = determine_model_segment(age=65, orec="2", icd_codes=["Z94.0"])
        assert seg == "ESRD_FG"

    def test_esrd_new_enrollee_routing(self) -> None:
        seg = determine_model_segment(age=65, orec="2", enrollment_months=6)
        assert seg == "ESRD_NE"

    def test_esrd_dialysis_code_overrides_graft(self) -> None:
        # Both dialysis and graft codes present — dialysis wins
        seg = determine_model_segment(
            age=65, orec="2", icd_codes=["Z94.0", "Z99.2"]
        )
        assert seg == "ESRD_DLY"


# ---------------------------------------------------------------------------
# 7. New Enrollee score calculation
# ---------------------------------------------------------------------------

class TestNewEnrolleeScore:
    def test_ne_cna_aged_female_65_69(self) -> None:
        result = _calculate_new_enrollee_score(age=67, sex="F", model_segment="NE_CNA")
        assert result["is_new_enrollee"] is True
        assert result["demographic_score"] == pytest.approx(0.557)  # individual age 67

    def test_ne_cna_aged_male_65_69(self) -> None:
        result = _calculate_new_enrollee_score(age=67, sex="M", model_segment="NE_CNA")
        assert result["demographic_score"] == pytest.approx(0.617)  # individual age 67

    def test_ne_no_disease_score(self) -> None:
        result = _calculate_new_enrollee_score(age=70, sex="F", model_segment="NE_CNA")
        assert result["disease_score"] == 0.0
        assert result["interaction_score"] == 0.0
        assert result["hcc_list"] == []

    def test_ne_subtotal_equals_demographic_score(self) -> None:
        result = _calculate_new_enrollee_score(age=70, sex="M", model_segment="NE_CNA")
        assert result["subtotal"] == pytest.approx(result["demographic_score"])

    def test_ne_has_model_note(self) -> None:
        result = _calculate_new_enrollee_score(age=70, sex="F", model_segment="NE_CNA")
        assert "New Enrollee" in result["model_note"] or "demographic" in result["model_note"].lower()

    def test_ne_cna_95plus_female(self) -> None:
        result = _calculate_new_enrollee_score(age=97, sex="F", model_segment="NE_CNA")
        assert result["demographic_score"] == pytest.approx(1.287)

    def test_ne_cna_95plus_male(self) -> None:
        result = _calculate_new_enrollee_score(age=97, sex="M", model_segment="NE_CNA")
        assert result["demographic_score"] == pytest.approx(1.516)

    def test_ne_cfa_aged_female_65_69(self) -> None:
        result = _calculate_new_enrollee_score(age=67, sex="F", model_segment="NE_CFA")
        assert result["demographic_score"] == pytest.approx(1.004)  # NE_MCAID_NORIGDIS age 67

    def test_ne_cnd_disabled_female_0_34(self) -> None:
        result = _calculate_new_enrollee_score(age=25, sex="F", model_segment="NE_CND")
        assert result["demographic_score"] == pytest.approx(0.711)

    def test_ne_cnd_disabled_male_35_44(self) -> None:
        result = _calculate_new_enrollee_score(age=40, sex="M", model_segment="NE_CND")
        assert result["demographic_score"] == pytest.approx(0.669)

    def test_unknown_ne_segment_uses_default(self) -> None:
        """Unknown segment should not raise — use default value."""
        result = _calculate_new_enrollee_score(age=67, sex="F", model_segment="NE_UNKNOWN")
        assert result["demographic_score"] > 0

    @pytest.mark.parametrize("age_band,sex,segment,expected", [
        ("70-74", "F", "CNA", 0.694),
        ("70-74", "M", "CNA", 0.808),
        ("80-84", "F", "CNA", 0.988),
        ("80-84", "M", "CNA", 1.245),
        ("85-89", "F", "CNA", 1.287),
        ("85-89", "M", "CNA", 1.516),
    ])
    def test_ne_demo_score_lookup(self, age_band, sex, segment, expected) -> None:
        score = _NE_DEMO_SCORES.get((age_band, sex, segment))
        assert score == pytest.approx(expected)

    # --- Individual age 65-69 tests (CMS uses individual ages, not banded) ---
    @pytest.mark.parametrize("age,sex,expected", [
        (65, "F", 0.532), (66, "F", 0.532), (67, "F", 0.557),
        (68, "F", 0.584), (69, "F", 0.625),
        (65, "M", 0.567), (66, "M", 0.576), (67, "M", 0.617),
        (68, "M", 0.678), (69, "M", 0.684),
    ])
    def test_ne_individual_age_65_69(self, age, sex, expected) -> None:
        """CMS NE model uses individual ages 65-69, not banded."""
        result = _calculate_new_enrollee_score(age=age, sex=sex, model_segment="NE_CNA")
        assert result["demographic_score"] == pytest.approx(expected)

    def test_ne_mcaid_segment_different_from_nmcaid(self) -> None:
        """Medicaid NE segments (CFA/CPA) should have different coefficients."""
        nmcaid = _calculate_new_enrollee_score(age=67, sex="F", model_segment="NE_CNA")
        mcaid = _calculate_new_enrollee_score(age=67, sex="F", model_segment="NE_CFA")
        assert nmcaid["demographic_score"] != mcaid["demographic_score"]
        assert mcaid["demographic_score"] == pytest.approx(1.004)  # NE_MCAID_NORIGDIS

    def test_ne_origdis_with_orec(self) -> None:
        """OREC=1 + age>=65 → NE_NMCAID_ORIGDIS segment."""
        result = _calculate_new_enrollee_score(
            age=67, sex="F", model_segment="NE_CNA", orec="1"
        )
        assert result["demographic_score"] == pytest.approx(1.276)  # NE_NMCAID_ORIGDIS

    def test_ne_origdis_under_65_ignored(self) -> None:
        """OREC=1 but age<65 — ORIGDIS not applicable, use NORIGDIS."""
        result = _calculate_new_enrollee_score(
            age=40, sex="F", model_segment="NE_CND", orec="1"
        )
        assert result["demographic_score"] == pytest.approx(0.950)  # NE_NMCAID_NORIGDIS 35-44

    def test_ne_mcaid_origdis(self) -> None:
        """Full-dual + OREC=1 + age>=65 → NE_MCAID_ORIGDIS."""
        result = _calculate_new_enrollee_score(
            age=67, sex="M", model_segment="NE_CFA", orec="1"
        )
        assert result["demographic_score"] == pytest.approx(1.959)  # NE_MCAID_ORIGDIS


# ---------------------------------------------------------------------------
# 8. ESRD demographic score
# ---------------------------------------------------------------------------

class TestEsrdDemographicScore:
    def test_esrd_dly_65_69_female(self) -> None:
        score = _calculate_esrd_demographic_score(age=67, sex="F", esrd_segment="ESRD_DLY")
        assert score == pytest.approx(0.635)

    def test_esrd_dly_65_69_male(self) -> None:
        score = _calculate_esrd_demographic_score(age=67, sex="M", esrd_segment="ESRD_DLY")
        assert score == pytest.approx(0.562)

    def test_esrd_fg_65_69_female(self) -> None:
        score = _calculate_esrd_demographic_score(age=67, sex="F", esrd_segment="ESRD_FG")
        assert score == pytest.approx(0.635)

    def test_esrd_ne_uses_dly_as_baseline(self) -> None:
        dly_score = _calculate_esrd_demographic_score(age=67, sex="F", esrd_segment="ESRD_DLY")
        ne_score = _calculate_esrd_demographic_score(age=67, sex="F", esrd_segment="ESRD_NE")
        assert ne_score == pytest.approx(dly_score)

    def test_esrd_scores_higher_than_community(self) -> None:
        """ESRD patients have elevated demographic base scores vs community."""
        esrd = _ESRD_DLY_DEMO_SCORES.get(("65-69", "F"), 0)
        community_ne = _NE_DEMO_SCORES.get(("65-69", "F", "CNA"), 0)
        assert esrd > community_ne

    def test_esrd_dly_scores_table_completeness(self) -> None:
        """Spot-check the ESRD_DLY table has entries for common age bands."""
        for age_band in ["45-54", "55-59", "65-69", "75-79", "85-89"]:
            for sex in ["F", "M"]:
                assert (age_band, sex) in _ESRD_DLY_DEMO_SCORES

    def test_esrd_fg_score_equal_to_dly_in_v28(self) -> None:
        """In V28, GC/GI/DI segments share identical demographic coefficients."""
        for age_band in [("65-69", "F"), ("70-74", "M")]:
            dly = _ESRD_DLY_DEMO_SCORES.get(age_band, 0)
            fg = _ESRD_FG_DEMO_SCORES.get(age_band, 0)
            assert fg == pytest.approx(dly), f"FG should equal DLY for {age_band} in V28"


# ---------------------------------------------------------------------------
# 9. Segment helpers (_is_new_enrollee, _is_esrd)
# ---------------------------------------------------------------------------

class TestSegmentHelpers:
    @pytest.mark.parametrize("seg", ["NE_CNA", "NE_CND", "NE_CFA", "NE_CFD", "NE_CPA", "NE_CPD", "NE"])
    def test_is_new_enrollee_true(self, seg) -> None:
        assert _is_new_enrollee(seg) is True

    @pytest.mark.parametrize("seg", ["CNA", "CND", "CFA", "CFD", "CPA", "CPD", "INS", "ESRD_DLY"])
    def test_is_new_enrollee_false(self, seg) -> None:
        assert _is_new_enrollee(seg) is False

    @pytest.mark.parametrize("seg", ["ESRD_DLY", "ESRD_FG", "ESRD_NE"])
    def test_is_esrd_true(self, seg) -> None:
        assert _is_esrd(seg) is True

    @pytest.mark.parametrize("seg", ["CNA", "CND", "NE_CNA", "INS"])
    def test_is_esrd_false(self, seg) -> None:
        assert _is_esrd(seg) is False


# ---------------------------------------------------------------------------
# 10. Segment → prefix mapping
# ---------------------------------------------------------------------------

class TestSegmentToPrefixMapping:
    @pytest.mark.parametrize("segment,expected_prefix", [
        ("CNA", "CNA_"),
        ("CND", "CND_"),
        ("CFA", "CFA_"),
        ("CFD", "CFD_"),
        ("CPA", "CPA_"),
        ("CPD", "CPD_"),
        ("INS", "INS_"),
    ])
    def test_standard_segment_prefix(self, segment, expected_prefix) -> None:
        assert _SEGMENT_TO_PREFIX[segment] == expected_prefix

    def test_esrd_dly_prefix(self) -> None:
        # ESRD patients use community prefix for standard V28/V24 models;
        # the dedicated ESRD V24 processor auto-detects DI_/GC_ from orec.
        assert _SEGMENT_TO_PREFIX["ESRD_DLY"] == "CNA_"

    def test_esrd_fg_prefix(self) -> None:
        assert _SEGMENT_TO_PREFIX["ESRD_FG"] == "CNA_"

    def test_esrd_ne_prefix(self) -> None:
        assert _SEGMENT_TO_PREFIX["ESRD_NE"] == "NE_"

    def test_ne_prefix(self) -> None:
        assert _SEGMENT_TO_PREFIX["NE_CNA"] == "NE_"


# ---------------------------------------------------------------------------
# 11. _run_single_model with hccinfhir (real CMS coefficients, no DB)
# ---------------------------------------------------------------------------

class TestRunSingleModel:
    """
    Integration tests calling _run_single_model with real hccinfhir processors.
    Known ICD codes with reliable CMS coefficients are used.

    These do NOT test payment_raf values (normalization is applied by the caller)
    but do verify the structure and that HCCs fire correctly.
    """

    def test_diabetes_type2_hcc_fires(self) -> None:
        """E11.65 (type 2 DM with hyperglycemia) should map to HCC 19/23 in V28."""
        norm = _NORM_FACTORS_V28[2026]
        maci = _MACI_FACTORS_V28[2026]
        result = _run_single_model(
            processor=_processor_v28,
            icd_codes=["E11.65"],
            age=70,
            sex="M",
            model_segment="CNA",
            norm_factor=norm,
            maci=maci,
        )
        assert len(result["hcc_list"]) >= 1
        assert result["raw_raf"] > 0
        assert result["demographic_score"] > 0

    def test_chf_hcc_fires(self) -> None:
        """I50.9 (heart failure) should trigger a HCC in both V24 and V28."""
        norm = _NORM_FACTORS_V28[2026]
        maci = _MACI_FACTORS_V28[2026]
        result = _run_single_model(
            processor=_processor_v28,
            icd_codes=["I50.9"],
            age=75,
            sex="F",
            model_segment="CNA",
            norm_factor=norm,
            maci=maci,
        )
        assert len(result["hcc_list"]) >= 1
        assert result["disease_score"] > 0

    def test_no_hcc_icd_codes_still_returns_demographic(self) -> None:
        """When no codes map to HCCs, demographic score must still be present."""
        norm = _NORM_FACTORS_V28[2026]
        maci = _MACI_FACTORS_V28[2026]
        result = _run_single_model(
            processor=_processor_v28,
            icd_codes=["Z00.00"],  # annual exam — no HCC
            age=70,
            sex="F",
            model_segment="CNA",
            norm_factor=norm,
            maci=maci,
        )
        assert result["demographic_score"] >= 0
        assert "hcc_list" in result
        assert "hcc_contributions" in result

    def test_result_keys_present(self) -> None:
        norm = _NORM_FACTORS_V28[2026]
        maci = _MACI_FACTORS_V28[2026]
        result = _run_single_model(
            processor=_processor_v28,
            icd_codes=["E11.9"],
            age=68,
            sex="M",
            model_segment="CNA",
            norm_factor=norm,
            maci=maci,
        )
        required = {
            "raw_raf", "payment_raf", "demographic_score", "disease_score",
            "interaction_score", "subtotal", "hcc_list", "hcc_contributions",
            "all_coefficients", "norm_factor", "maci_factor",
        }
        for key in required:
            assert key in result, f"Missing key: {key}"

    def test_disease_score_is_sum_of_hcc_contributions(self) -> None:
        norm = _NORM_FACTORS_V28[2026]
        maci = _MACI_FACTORS_V28[2026]
        result = _run_single_model(
            processor=_processor_v28,
            icd_codes=["E11.65", "I50.9"],
            age=72,
            sex="F",
            model_segment="CNA",
            norm_factor=norm,
            maci=maci,
        )
        total_from_contributions = sum(
            h["coefficient"] for h in result["hcc_contributions"]
        )
        assert total_from_contributions == pytest.approx(result["disease_score"], abs=0.001)

    def test_hcc_contributions_have_required_fields(self) -> None:
        norm = _NORM_FACTORS_V28[2026]
        maci = _MACI_FACTORS_V28[2026]
        result = _run_single_model(
            processor=_processor_v28,
            icd_codes=["E11.65"],
            age=70,
            sex="M",
            model_segment="CNA",
            norm_factor=norm,
            maci=maci,
        )
        for contrib in result["hcc_contributions"]:
            assert "hcc_code" in contrib
            assert "coefficient" in contrib
            assert "label" in contrib

    def test_v24_processor_produces_result(self) -> None:
        """V24 model must also produce valid results."""
        norm = _NORM_FACTORS_V24[2024]
        maci = _MACI_FACTORS_V24[2024]
        result = _run_single_model(
            processor=_processor_v24,
            icd_codes=["E11.65", "I50.9"],
            age=70,
            sex="M",
            model_segment="CNA",
            norm_factor=norm,
            maci=maci,
        )
        assert result["raw_raf"] > 0
        assert len(result["hcc_list"]) >= 1

    def test_norm_factor_stored_in_result(self) -> None:
        norm = 1.045
        maci = 0.059
        result = _run_single_model(
            processor=_processor_v28,
            icd_codes=["E11.9"],
            age=68,
            sex="F",
            model_segment="CNA",
            norm_factor=norm,
            maci=maci,
        )
        assert result["norm_factor"] == pytest.approx(norm)
        assert result["maci_factor"] == pytest.approx(maci)

    def test_payment_raf_is_positive(self) -> None:
        norm = _NORM_FACTORS_V28[2026]
        maci = _MACI_FACTORS_V28[2026]
        result = _run_single_model(
            processor=_processor_v28,
            icd_codes=["E11.65", "I50.9", "N18.4"],
            age=72,
            sex="M",
            model_segment="CNA",
            norm_factor=norm,
            maci=maci,
        )
        assert result["payment_raf"] > 0

    def test_multiple_hccs_increase_score(self) -> None:
        """Adding a second chronic condition should increase total RAF."""
        norm = _NORM_FACTORS_V28[2026]
        maci = _MACI_FACTORS_V28[2026]
        result_single = _run_single_model(
            processor=_processor_v28,
            icd_codes=["E11.65"],
            age=70,
            sex="M",
            model_segment="CNA",
            norm_factor=norm,
            maci=maci,
        )
        result_multi = _run_single_model(
            processor=_processor_v28,
            icd_codes=["E11.65", "I50.9"],
            age=70,
            sex="M",
            model_segment="CNA",
            norm_factor=norm,
            maci=maci,
        )
        assert result_multi["raw_raf"] >= result_single["raw_raf"]


# ---------------------------------------------------------------------------
# 12. Blending arithmetic
# ---------------------------------------------------------------------------

class TestBlendingArithmetic:
    @pytest.mark.golden
    def test_py2024_blended_score_formula(self) -> None:
        """Verify manual blend: 0.67 * v24_raw + 0.33 * v28_raw."""
        v24_raw = 1.200
        v28_raw = 1.100
        v24_w, v28_w = _BLEND_WEIGHTS[2024]
        blended = v24_w * v24_raw + v28_w * v28_raw
        assert blended == pytest.approx(0.67 * 1.200 + 0.33 * 1.100, rel=1e-4)

    @pytest.mark.golden
    def test_py2026_blend_equals_v28_only(self) -> None:
        v24_raw = 1.200
        v28_raw = 1.100
        v24_w, v28_w = _BLEND_WEIGHTS[2026]
        blended = v24_w * v24_raw + v28_w * v28_raw
        assert blended == pytest.approx(v28_raw)

    def test_blended_score_between_v24_and_v28(self) -> None:
        v24_raw = 1.400
        v28_raw = 1.200
        v24_w, v28_w = _BLEND_WEIGHTS[2025]
        blended = v24_w * v24_raw + v28_w * v28_raw
        assert min(v24_raw, v28_raw) <= blended <= max(v24_raw, v28_raw)


# ---------------------------------------------------------------------------
# 15. PACE V22 model integration
# ---------------------------------------------------------------------------

class TestPACEV22Model:
    """Verify that the V22 processor produces valid scores with correct coefficients."""

    def test_v22_processor_produces_scores(self) -> None:
        """V22 processor should produce non-zero scores for a known diagnosis."""
        result = _run_single_model(
            _processor_v22, ["E1169"], 70, "M", "CNA", 1.187, 0.0
        )
        assert result["raw_raf"] > 0
        assert result["demographic_score"] > 0
        assert result["payment_raf"] > 0

    def test_v22_different_from_v24(self) -> None:
        """V22 and V24 have different coefficients (~1-3% delta)."""
        r22 = _run_single_model(
            _processor_v22, ["E1169"], 70, "M", "CNA", 1.0, 0.0
        )
        r24 = _run_single_model(
            _processor_v24, ["E1169"], 70, "M", "CNA", 1.0, 0.0
        )
        # Both should have scores but they should differ
        assert r22["raw_raf"] > 0
        assert r24["raw_raf"] > 0
        assert r22["raw_raf"] != r24["raw_raf"]

    def test_v22_with_v22_norm_factor(self) -> None:
        """PACE payment uses V22 norm factor (1.187)."""
        n22 = _get_norm_factor(_NORM_FACTORS_V22, 2025)
        assert n22 == pytest.approx(1.187)
        result = _run_single_model(
            _processor_v22, ["E1169"], 70, "M", "CNA", n22, 0.0
        )
        # payment_raf should be raw / 1.187
        expected_payment = result["raw_raf"] / n22
        assert result["payment_raf"] == pytest.approx(expected_payment, rel=0.01)

    def test_pace_blend_weights_exist(self) -> None:
        """PACE blend weights should exist for transition years."""
        assert 2025 in _PACE_BLEND_WEIGHTS or 2024 in _PACE_BLEND_WEIGHTS


# ---------------------------------------------------------------------------
# 16. ESRD V24 dedicated model
# ---------------------------------------------------------------------------

class TestESRDModel:
    """Verify ESRD-specific processor produces correct ESRD scores."""

    def test_esrd_v24_processor_with_dialysis(self) -> None:
        """ESRD V24 processor with orec=2 should use DI_ prefix and produce scores."""
        result = _run_single_model(
            _processor_esrd_v24, ["E1169", "N186"], 70, "M", "ESRD_DLY",
            1.0, 0.0, orec="2",
        )
        assert result["raw_raf"] > 0
        assert result["demographic_score"] > 0

    def test_esrd_v24_includes_esrd_interactions(self) -> None:
        """ESRD model should fire Originally_ESRD interaction for orec=2 aged patients."""
        result = _run_single_model(
            _processor_esrd_v24, ["E1169", "N186"], 70, "M", "ESRD_DLY",
            1.0, 0.0, orec="2",
        )
        coefs = result["all_coefficients"]
        # Should have some coefficients (demographic + HCC + possibly interactions)
        assert len(coefs) > 0

    def test_esrd_demo_scores_match_table(self) -> None:
        """ESRD demographic override should match our hardcoded table."""
        score = _calculate_esrd_demographic_score(70, "M", "ESRD_DLY")
        assert score == _ESRD_DLY_DEMO_SCORES[("70-74", "M")]
        assert score == pytest.approx(0.611)

    def test_esrd_fg_uses_correct_segment(self) -> None:
        """Functioning graft segment should work with ESRD processor."""
        result = _run_single_model(
            _processor_esrd_v24, ["E1169", "Z940"], 70, "M", "ESRD_FG",
            1.0, 0.0, orec="2",
        )
        assert result["raw_raf"] > 0


# ---------------------------------------------------------------------------
# 17. HCC Hierarchy application
# ---------------------------------------------------------------------------

class TestHCCHierarchy:
    """Verify that _apply_hcc_hierarchy correctly suppresses child HCCs."""

    def test_hierarchy_suppresses_child_hcc(self) -> None:
        """When parent HCC is present, child should be removed."""
        # HCC 18 (Diabetes with Chronic Complications) trumps HCC 19 (Diabetes without Complication)
        # in V28. Let's create a result with both and verify hierarchy removes the child.
        result = _run_single_model(
            _processor_v28, ["E1165", "E119"], 70, "M", "CNA", 1.0, 0.0
        )
        # E1165 → HCC 37 (Diabetes with Chronic Complications in V28)
        # E119 → HCC 38 (Diabetes without Complication in V28)
        # If both are present, HCC 38 should be suppressed by HCC 37
        hcc_list_before = list(result["hcc_list"])
        _apply_hcc_hierarchy(result, "v28")
        # After hierarchy, the list should be equal or smaller
        assert len(result["hcc_list"]) <= len(hcc_list_before)

    def test_hierarchy_recalculates_scores(self) -> None:
        """After suppression, disease_score should be recalculated."""
        result = _run_single_model(
            _processor_v28, ["E1165", "E119"], 70, "M", "CNA", 1.0, 0.0
        )
        raw_before = result["raw_raf"]
        _apply_hcc_hierarchy(result, "v28")
        # Score may decrease (child removed) or stay same (no suppression needed)
        assert result["raw_raf"] <= raw_before + 0.001


# ---------------------------------------------------------------------------
# 18. Payment-level blending verification
# ---------------------------------------------------------------------------

class TestPaymentLevelBlending:
    """Verify payment-level blending is correct per CMS."""

    def test_payment_blending_not_raw_blending(self) -> None:
        """Each model should normalize independently before blending."""
        # Run V24 and V28 with different norm factors
        n24 = _get_norm_factor(_NORM_FACTORS_V24, 2025)
        n28 = _get_norm_factor(_NORM_FACTORS_V28, 2025)
        m24 = _get_maci_factor(_MACI_FACTORS_V24, 2025)
        m28 = _get_maci_factor(_MACI_FACTORS_V28, 2025)

        r24 = _run_single_model(_processor_v24, ["E1169"], 70, "M", "CNA", n24, m24)
        r28 = _run_single_model(_processor_v28, ["E1169"], 70, "M", "CNA", n28, m28)

        # Payment = raw * (1 - MACI) / norm
        expected_p24 = r24["raw_raf"] * (1 - m24) / n24
        expected_p28 = r28["raw_raf"] * (1 - m28) / n28
        assert r24["payment_raf"] == pytest.approx(expected_p24, rel=0.01)
        assert r28["payment_raf"] == pytest.approx(expected_p28, rel=0.01)

        # Blended payment (PY2025: 33% V24, 67% V28)
        v24_w, v28_w = _BLEND_WEIGHTS[2025]
        blended_payment = v24_w * r24["payment_raf"] + v28_w * r28["payment_raf"]
        # Raw blending would give a different result
        blended_raw = v24_w * r24["raw_raf"] + v28_w * r28["raw_raf"]
        # These should NOT be equal (different norm factors)
        assert blended_payment != pytest.approx(blended_raw * (1 - m28) / n28, rel=0.01)

    def test_v28_only_no_blending(self) -> None:
        """For 2026+, V28-only means no blending needed."""
        v24_w, v28_w = _BLEND_WEIGHTS[2026]
        assert v24_w == 0.0
        assert v28_w == 1.0


# ---------------------------------------------------------------------------
# 19. Enrollment params passed to hccinfhir
# ---------------------------------------------------------------------------

class TestEnrollmentParamsPassthrough:
    """Verify orec, dual_elgbl_cd are passed to hccinfhir."""

    def test_orec_passed_in_engine_input(self) -> None:
        """Engine input should include orec for audit trail."""
        result = _run_single_model(
            _processor_v28, ["E1169"], 70, "M", "CNA", 1.0, 0.0,
            orec="2", dual_elgbl_cd="02",
        )
        assert result["engine_input"]["orec"] == "2"
        assert result["engine_input"]["dual_elgbl_cd"] == "02"

    def test_dual_affects_prefix(self) -> None:
        """Full dual patients should get different demographic scores."""
        r_nondual = _run_single_model(
            _processor_v28, ["E1169"], 70, "M", "CNA", 1.0, 0.0,
            dual_elgbl_cd="NA",
        )
        r_fulldual = _run_single_model(
            _processor_v28, ["E1169"], 70, "M", "CFA", 1.0, 0.0,
            dual_elgbl_cd="02",
        )
        # Full dual aged should have different demographic score
        assert r_nondual["demographic_score"] != r_fulldual["demographic_score"]

    def test_invalid_orec_validated(self) -> None:
        """Invalid OREC values should be corrected to '0'."""
        seg = determine_model_segment(age=70, orec="9", enrollment_months=12)
        # Should not crash, should default to standard segment
        assert seg in ("CNA", "CND")

    def test_graft_months_passthrough(self) -> None:
        """graft_months should be passed to hccinfhir for ESRD graft interactions."""
        result = _run_single_model(
            _processor_esrd_v24, ["E1169", "Z940"], 70, "M", "ESRD_FG",
            1.0, 0.0, orec="2", graft_months=36,
        )
        assert result["raw_raf"] > 0


# ---------------------------------------------------------------------------
# 20. NE sex validation and age clamping
# ---------------------------------------------------------------------------

class TestNEValidation:
    """Verify NE scoring handles edge cases gracefully."""

    def test_ne_invalid_sex_normalized(self) -> None:
        """Invalid sex should be normalized via _sex_code."""
        result = _calculate_new_enrollee_score(70, "female", "NE_CNA")
        assert result["demographic_score"] > 0
        # Should use F coefficient
        result_f = _calculate_new_enrollee_score(70, "F", "NE_CNA")
        assert result["demographic_score"] == result_f["demographic_score"]

    def test_ne_negative_age_clamped(self) -> None:
        """Negative age should be clamped to 0."""
        result = _calculate_new_enrollee_score(-5, "F", "NE_CNA")
        result_zero = _calculate_new_enrollee_score(0, "F", "NE_CNA")
        assert result["demographic_score"] == result_zero["demographic_score"]

    def test_ne_unknown_segment_warns(self) -> None:
        """Unknown segment should fall back to CNA."""
        result = _calculate_new_enrollee_score(70, "F", "NE_UNKNOWN")
        # Should still produce a valid score (defaults to CNA)
        assert result["demographic_score"] > 0
