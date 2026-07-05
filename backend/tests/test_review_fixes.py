"""
Tests for critical fixes surfaced during the 3-round code review.

Each section maps to a specific review finding.  All tests are pure-logic
or source-inspection tests that require no database connection.
"""
from __future__ import annotations

import inspect
import sys
from datetime import date
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# 1. Model version for year (recapture gaps)
# ---------------------------------------------------------------------------

class TestModelVersionForYear:
    """_model_version_for_year must return the correct CMS HCC model
    version string for any given measurement year."""

    def test_2024_returns_v28(self):
        from app.services.recapture_gap_service import _model_version_for_year
        assert _model_version_for_year(2024) == "V28"

    def test_2025_returns_v28(self):
        from app.services.recapture_gap_service import _model_version_for_year
        assert _model_version_for_year(2025) == "V28"

    def test_2023_returns_v24(self):
        from app.services.recapture_gap_service import _model_version_for_year
        assert _model_version_for_year(2023) == "V24"

    def test_2027_returns_v28(self):
        from app.services.recapture_gap_service import _model_version_for_year
        assert _model_version_for_year(2027) == "V28"

    def test_far_future_returns_v28(self):
        """Any year >= 2024 should map to V28 under the current table."""
        from app.services.recapture_gap_service import _model_version_for_year
        assert _model_version_for_year(2030) == "V28"

    def test_year_zero_returns_v24(self):
        """Year 0 should fall through to the V24 catch-all."""
        from app.services.recapture_gap_service import _model_version_for_year
        assert _model_version_for_year(0) == "V24"


# ---------------------------------------------------------------------------
# 2. DOB validation raises ValueError
# ---------------------------------------------------------------------------

class TestDobValidation:
    """Patient DOB must be present; the calculator should not silently
    default to a fallback date like 1950-01-01."""

    def test_calculate_raf_score_raises_on_missing_dob(self):
        """The primary calculate_raf_score function must raise ValueError
        when DOB is missing, rather than silently defaulting."""
        from app.services.raf.calculator import calculate_raf_score
        source = inspect.getsource(calculate_raf_score)
        assert "raise ValueError" in source, (
            "calculate_raf_score must raise ValueError on missing DOB"
        )
        # The primary scoring path should NOT silently fall back to 1950-01-01
        assert "1950-01-01" not in source, (
            "calculate_raf_score must not silently default DOB to 1950-01-01"
        )

    def test_calculate_raf_score_dob_error_message(self):
        """The ValueError message should mention 'date of birth' for clarity."""
        from app.services.raf.calculator import calculate_raf_score
        source = inspect.getsource(calculate_raf_score)
        assert "date of birth" in source.lower(), (
            "The DOB validation error message should mention 'date of birth'"
        )


# ---------------------------------------------------------------------------
# 3. ICD-10 dot removal in hccinfhir_utils
# ---------------------------------------------------------------------------

class TestIcd10DotRemoval:
    """lookup_hcc and is_risk_adjusting must strip dots so 'E11.9' and
    'E119' produce identical results."""

    def test_lookup_hcc_strips_dots(self):
        from app.services.hccinfhir_utils import lookup_hcc
        result_dotted = lookup_hcc("E11.9")
        result_clean = lookup_hcc("E119")
        assert result_dotted["maps_to_hcc"] == result_clean["maps_to_hcc"]
        assert result_dotted["hcc_codes"] == result_clean["hcc_codes"]

    def test_is_risk_adjusting_strips_dots(self):
        from app.services.hccinfhir_utils import is_risk_adjusting
        assert is_risk_adjusting("E11.9") == is_risk_adjusting("E119")

    def test_lookup_hcc_returns_cleaned_code(self):
        """The returned icd10_code should have the dot stripped."""
        from app.services.hccinfhir_utils import lookup_hcc
        result = lookup_hcc("E11.9")
        assert "." not in result["icd10_code"]

    def test_lookup_hcc_handles_lowercase(self):
        from app.services.hccinfhir_utils import lookup_hcc
        result_upper = lookup_hcc("E119")
        result_lower = lookup_hcc("e11.9")
        assert result_upper["maps_to_hcc"] == result_lower["maps_to_hcc"]


# ---------------------------------------------------------------------------
# 4. MEAT keyword completeness
# ---------------------------------------------------------------------------

class TestMeatKeywords:
    """MEAT keyword lexicons must include clinically relevant terms added
    during the review rounds."""

    def test_monitor_keywords_include_vitals(self):
        from app.services.meat_validator import MONITOR_KEYWORDS
        assert "vitals" in MONITOR_KEYWORDS
        assert "blood pressure" in MONITOR_KEYWORDS
        assert "a1c" in MONITOR_KEYWORDS
        assert "egfr" in MONITOR_KEYWORDS

    def test_monitor_keywords_include_lab_terms(self):
        from app.services.meat_validator import MONITOR_KEYWORDS
        assert "creatinine" in MONITOR_KEYWORDS
        assert "ejection fraction" in MONITOR_KEYWORDS

    def test_evaluate_keywords_include_exam_terms(self):
        from app.services.meat_validator import EVALUATE_KEYWORDS
        assert "auscultation" in EVALUATE_KEYWORDS
        assert "ros" in EVALUATE_KEYWORDS
        assert "physical exam" in EVALUATE_KEYWORDS

    def test_evaluate_keywords_include_palpation(self):
        from app.services.meat_validator import EVALUATE_KEYWORDS
        assert "palpation" in EVALUATE_KEYWORDS

    def test_treat_keywords_include_specific_treatments(self):
        from app.services.meat_validator import TREAT_KEYWORDS
        assert "insulin" in TREAT_KEYWORDS
        assert "dialysis" in TREAT_KEYWORDS
        assert "chemotherapy" in TREAT_KEYWORDS

    def test_treat_keywords_no_bare_continue(self):
        """'continue' alone is a false-positive trigger; only
        'continue medication' / 'continue current regimen' etc. are valid."""
        from app.services.meat_validator import TREAT_KEYWORDS
        assert "continue" not in TREAT_KEYWORDS

    def test_assess_keywords_include_status_terms(self):
        from app.services.meat_validator import ASSESS_KEYWORDS
        assert "improving" in ASSESS_KEYWORDS
        assert "at goal" in ASSESS_KEYWORDS

    def test_assess_keywords_include_controlled(self):
        from app.services.meat_validator import ASSESS_KEYWORDS
        assert "controlled" in ASSESS_KEYWORDS
        assert "uncontrolled" in ASSESS_KEYWORDS


# ---------------------------------------------------------------------------
# 5. Interaction score allows negative values
# ---------------------------------------------------------------------------

class TestInteractionScoreNotClamped:
    """The calculator must NOT clamp interaction_score to zero.
    CMS allows negative disease interaction adjustments."""

    def test_run_single_model_source_has_no_max_zero_clamp(self):
        """Inspect _run_single_model to verify interaction_score is not
        clamped to 0.  If max(0, ...) or similar pattern is applied to
        interaction_score, this test fails."""
        from app.services import raf_calculator
        source = inspect.getsource(raf_calculator)
        # Look for any line that both mentions interaction and clamps to 0
        lines = source.split("\n")
        for line in lines:
            low = line.lower()
            if "interaction" in low and "max(0" in low:
                pytest.fail(
                    f"interaction_score must not be clamped to zero: {line.strip()}"
                )


# ---------------------------------------------------------------------------
# 6. Blend weights single source of truth
# ---------------------------------------------------------------------------

class TestBlendWeightsCoverage:
    """PAYMENT_YEARS, _NORM_FACTORS_V28, and _MACI_FACTORS_V28 must cover
    at least the current and next payment year."""

    def test_payment_years_cover_current_and_next(self):
        from app.services.raf.dos_rules import PAYMENT_YEARS
        current_year = date.today().year
        assert current_year in PAYMENT_YEARS, (
            f"PY{current_year} missing from PAYMENT_YEARS"
        )
        assert current_year + 1 in PAYMENT_YEARS, (
            f"PY{current_year + 1} missing from PAYMENT_YEARS"
        )

    def test_norm_factors_cover_payment_years(self):
        from app.services.raf.dos_rules import PAYMENT_YEARS
        from app.services.raf.blend_weights import _NORM_FACTORS_V28
        for year in PAYMENT_YEARS:
            assert year in _NORM_FACTORS_V28, (
                f"PY{year} missing from _NORM_FACTORS_V28"
            )

    def test_maci_factors_cover_payment_years(self):
        from app.services.raf.dos_rules import PAYMENT_YEARS
        from app.services.raf.blend_weights import _MACI_FACTORS_V28
        for year in PAYMENT_YEARS:
            assert year in _MACI_FACTORS_V28, (
                f"PY{year} missing from _MACI_FACTORS_V28"
            )

    def test_blend_weights_sum_to_one(self):
        """For each payment year, model_blend percentages must sum to 1.0."""
        from app.services.raf.dos_rules import PAYMENT_YEARS
        for year, pw in PAYMENT_YEARS.items():
            total = sum(pw.model_blend.values())
            assert abs(total - 1.0) < 1e-9, (
                f"PY{year} model_blend sums to {total}, expected 1.0"
            )


# ---------------------------------------------------------------------------
# 7. Billing gate cache is bounded
# ---------------------------------------------------------------------------

class TestBillingGateCacheBound:
    """The billing gate context cache must have a reasonable upper bound
    to prevent unbounded memory growth."""

    def test_cache_max_is_bounded(self):
        from app.services.raf.clinical_rules.billing_gate import _CONTEXT_CACHE_MAX
        assert _CONTEXT_CACHE_MAX <= 1024, (
            f"_CONTEXT_CACHE_MAX is {_CONTEXT_CACHE_MAX}, expected <= 1024"
        )

    def test_cache_max_is_positive(self):
        from app.services.raf.clinical_rules.billing_gate import _CONTEXT_CACHE_MAX
        assert _CONTEXT_CACHE_MAX > 0


# ---------------------------------------------------------------------------
# 8. TOTP replay prevention
# ---------------------------------------------------------------------------

class TestTotpReplayPrevention:
    """verify_mfa_code must check mfa_last_used_step with SELECT ... FOR
    UPDATE to prevent TOTP replay attacks."""

    def test_totp_replay_guard_present_in_source(self):
        from app.services.auth_service import verify_mfa_code
        source = inspect.getsource(verify_mfa_code)
        assert "mfa_last_used_step" in source, (
            "verify_mfa_code must check mfa_last_used_step"
        )
        assert "FOR UPDATE" in source, (
            "verify_mfa_code must use SELECT ... FOR UPDATE to lock the row"
        )

    def test_totp_replay_rejects_equal_step(self):
        """The code must reject a code whose step is <= the last used step,
        not just strictly less-than."""
        from app.services.auth_service import verify_mfa_code
        source = inspect.getsource(verify_mfa_code)
        assert "current_step <= last_step" in source, (
            "Replay check must use <= (not <) to reject same-step reuse"
        )


# ---------------------------------------------------------------------------
# 9. Sync log field allowlist
# ---------------------------------------------------------------------------

class TestSyncLogAllowlist:
    """_update_sync_log must reject any kwargs key that is not in the
    allowlist, preventing SQL injection via dynamic field names."""

    def test_rejects_unknown_field(self):
        from app.services.fhir_service import _update_sync_log
        with pytest.raises(ValueError, match="disallowed field"):
            _update_sync_log(1, evil_field="drop table")

    def test_rejects_sql_injection_field_name(self):
        from app.services.fhir_service import _update_sync_log
        with pytest.raises(ValueError, match="disallowed field"):
            _update_sync_log(1, **{"status=1; DROP TABLE users; --": "x"})

    def test_allowlist_includes_expected_fields(self):
        from app.services.fhir_service import _SYNC_LOG_FIELDS
        assert "status" in _SYNC_LOG_FIELDS
        assert "message" in _SYNC_LOG_FIELDS
        assert "patients_synced" in _SYNC_LOG_FIELDS


# ---------------------------------------------------------------------------
# 10. Document get_document tenant isolation
# ---------------------------------------------------------------------------

class TestDocumentTenantIsolation:
    """get_document must accept a tenant_id parameter to enforce tenant
    isolation; callers without tenant_id get a warning log."""

    def test_get_document_signature_accepts_tenant_id(self):
        from app.services.document_service import get_document
        sig = inspect.signature(get_document)
        assert "tenant_id" in sig.parameters, (
            "get_document must accept a tenant_id parameter"
        )

    def test_get_document_tenant_id_is_optional(self):
        """tenant_id should have a default (None) so existing callers
        are not broken, but new callers should always pass it."""
        from app.services.document_service import get_document
        sig = inspect.signature(get_document)
        param = sig.parameters["tenant_id"]
        assert param.default is None or param.default is inspect.Parameter.empty, (
            "tenant_id default should be None (backward compat) or required"
        )
