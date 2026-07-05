"""
HCC Mapping Service and hccinfhir_utils — expanded test suite.

Covers: ICD-10 to HCC lookup, model resolution, batch mapping,
hierarchy chain loading, coefficient retrieval, and label lookup.

No database or network required — uses hccinfhir library data directly.
"""
from __future__ import annotations

import pytest


# ---------------------------------------------------------------------------
# 1. map_icd10_to_hcc (hcc_mapping_service)
# ---------------------------------------------------------------------------

class TestMapIcd10ToHcc:
    """Authoritative ICD-10 -> HCC mapping via hcc_mapping_service."""

    def test_diabetes_maps_to_hcc(self):
        from app.services.hcc_mapping_service import map_icd10_to_hcc
        result = map_icd10_to_hcc("E119", "V28")
        assert result is not None
        assert result["hcc_code"] is not None
        assert len(result["hcc_codes"]) > 0

    def test_diabetes_with_dot_maps_same(self):
        from app.services.hcc_mapping_service import map_icd10_to_hcc
        result_dot = map_icd10_to_hcc("E11.9", "V28")
        result_clean = map_icd10_to_hcc("E119", "V28")
        assert result_dot is not None
        assert result_clean is not None
        assert result_dot["hcc_code"] == result_clean["hcc_code"]

    def test_heart_failure_maps_to_hcc(self):
        from app.services.hcc_mapping_service import map_icd10_to_hcc
        result = map_icd10_to_hcc("I509", "V28")
        assert result is not None
        assert result["hcc_code"] is not None

    def test_general_exam_does_not_map(self):
        from app.services.hcc_mapping_service import map_icd10_to_hcc
        # Z00.00 is a general exam code, not risk-adjusting
        result = map_icd10_to_hcc("Z0000", "V28")
        assert result is None

    def test_lowercase_input_normalized(self):
        from app.services.hcc_mapping_service import map_icd10_to_hcc
        result = map_icd10_to_hcc("e11.9", "V28")
        assert result is not None
        assert result["icd10_code"] == "E119"

    def test_result_contains_model_version(self):
        from app.services.hcc_mapping_service import map_icd10_to_hcc
        result = map_icd10_to_hcc("E119", "V28")
        assert result["model_version"] == "V28"
        assert result["model"] == "CMS-HCC Model V28"


# ---------------------------------------------------------------------------
# 2. _resolve_model
# ---------------------------------------------------------------------------

class TestResolveModel:
    """Model version string resolution."""

    def test_v28_resolves(self):
        from app.services.hcc_mapping_service import _resolve_model
        assert _resolve_model("V28") == "CMS-HCC Model V28"

    def test_v24_resolves(self):
        from app.services.hcc_mapping_service import _resolve_model
        assert _resolve_model("V24") == "CMS-HCC Model V24"

    def test_full_name_passthrough(self):
        from app.services.hcc_mapping_service import _resolve_model
        assert _resolve_model("CMS-HCC Model V28") == "CMS-HCC Model V28"

    def test_invalid_raises_value_error(self):
        from app.services.hcc_mapping_service import _resolve_model
        with pytest.raises(ValueError, match="Unknown model_version"):
            _resolve_model("V99")

    def test_empty_raises_value_error(self):
        from app.services.hcc_mapping_service import _resolve_model
        with pytest.raises(ValueError):
            _resolve_model("")


# ---------------------------------------------------------------------------
# 3. Batch mapping
# ---------------------------------------------------------------------------

class TestMapIcd10Batch:
    """Batch ICD-10 mapping returns dict keyed by normalized code."""

    def test_batch_returns_dict(self):
        from app.services.hcc_mapping_service import map_icd10_batch
        results = map_icd10_batch(["E119", "I509", "J449"], "V28")
        assert isinstance(results, dict)

    def test_batch_includes_risk_adjusting_codes(self):
        from app.services.hcc_mapping_service import map_icd10_batch
        results = map_icd10_batch(["E119", "I509"], "V28")
        assert "E119" in results
        assert "I509" in results

    def test_batch_excludes_non_mapping_codes(self):
        from app.services.hcc_mapping_service import map_icd10_batch
        results = map_icd10_batch(["Z0000"], "V28")
        # Non-mapping codes are omitted from results
        assert "Z0000" not in results


# ---------------------------------------------------------------------------
# 4. HCC hierarchy chains
# ---------------------------------------------------------------------------

class TestHccHierarchy:
    """V24 and V28 hierarchy chains must be loaded and populated."""

    def test_v28_hierarchy_loaded(self):
        from app.services.hcc_hierarchy import V28_HIERARCHY_CHAINS
        assert len(V28_HIERARCHY_CHAINS) > 10

    def test_v24_hierarchy_loaded(self):
        from app.services.hcc_hierarchy import V24_HIERARCHY_CHAINS
        assert len(V24_HIERARCHY_CHAINS) >= 13

    def test_v28_chains_are_tuples(self):
        from app.services.hcc_hierarchy import V28_HIERARCHY_CHAINS
        for chain in V28_HIERARCHY_CHAINS:
            assert isinstance(chain, tuple)
            assert all(isinstance(h, int) for h in chain)

    def test_v24_chains_are_tuples(self):
        from app.services.hcc_hierarchy import V24_HIERARCHY_CHAINS
        for chain in V24_HIERARCHY_CHAINS:
            assert isinstance(chain, tuple)
            assert all(isinstance(h, int) for h in chain)


# ---------------------------------------------------------------------------
# 5. HCC coefficient retrieval (hccinfhir_utils)
# ---------------------------------------------------------------------------

class TestGetHccCoefficient:
    """get_hcc_coefficient must return proper float values."""

    def test_known_hcc_has_positive_coefficient(self):
        from app.services.hccinfhir_utils import get_hcc_coefficient
        # HCC 37 (Diabetes) should have a positive coefficient
        coeff = get_hcc_coefficient("37", prefix="CNA_")
        assert coeff > 0

    def test_nonexistent_hcc_returns_zero(self):
        from app.services.hccinfhir_utils import get_hcc_coefficient
        coeff = get_hcc_coefficient("9999", prefix="CNA_")
        assert coeff == 0.0

    def test_strips_hcc_prefix(self):
        from app.services.hccinfhir_utils import get_hcc_coefficient
        coeff_bare = get_hcc_coefficient("37", prefix="CNA_")
        coeff_prefix = get_hcc_coefficient("HCC37", prefix="CNA_")
        assert coeff_bare == coeff_prefix


# ---------------------------------------------------------------------------
# 6. HCC label lookup
# ---------------------------------------------------------------------------

class TestGetHccLabel:
    """get_hcc_label must return non-empty labels for known HCCs."""

    def test_known_hcc_has_label(self):
        from app.services.hccinfhir_utils import get_hcc_label
        label = get_hcc_label("37")
        assert label is not None
        assert len(label) > 0

    def test_unknown_hcc_returns_empty(self):
        from app.services.hccinfhir_utils import get_hcc_label
        label = get_hcc_label("9999")
        assert label == ""

    def test_strips_hcc_prefix(self):
        from app.services.hccinfhir_utils import get_hcc_label
        label1 = get_hcc_label("37")
        label2 = get_hcc_label("HCC37")
        assert label1 == label2


# ---------------------------------------------------------------------------
# 7. lookup_hcc (hccinfhir_utils)
# ---------------------------------------------------------------------------

class TestLookupHcc:
    """lookup_hcc returns structured dict with correct shape."""

    def test_maps_to_hcc_true_for_risk_code(self):
        from app.services.hccinfhir_utils import lookup_hcc
        result = lookup_hcc("E119")
        assert result["maps_to_hcc"] is True

    def test_maps_to_hcc_false_for_non_risk_code(self):
        from app.services.hccinfhir_utils import lookup_hcc
        result = lookup_hcc("Z0000")
        assert result["maps_to_hcc"] is False

    def test_dot_stripped_in_returned_code(self):
        from app.services.hccinfhir_utils import lookup_hcc
        result = lookup_hcc("E11.9")
        assert "." not in result["icd10_code"]

    def test_result_has_required_keys(self):
        from app.services.hccinfhir_utils import lookup_hcc
        result = lookup_hcc("E119")
        for key in ("icd10_code", "model", "maps_to_hcc", "hcc_codes", "hcc_details"):
            assert key in result, f"Missing key {key}"


# ---------------------------------------------------------------------------
# 8. is_risk_adjusting
# ---------------------------------------------------------------------------

class TestIsRiskAdjusting:
    """Quick boolean check for whether an ICD-10 maps to any HCC."""

    def test_diabetes_is_risk_adjusting(self):
        from app.services.hccinfhir_utils import is_risk_adjusting
        assert is_risk_adjusting("E119") is True

    def test_general_exam_is_not_risk_adjusting(self):
        from app.services.hccinfhir_utils import is_risk_adjusting
        assert is_risk_adjusting("Z0000") is False

    def test_dot_handling(self):
        from app.services.hccinfhir_utils import is_risk_adjusting
        assert is_risk_adjusting("E11.9") == is_risk_adjusting("E119")
