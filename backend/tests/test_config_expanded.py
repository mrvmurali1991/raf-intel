"""
Application Configuration — expanded test suite.

Covers: CMS revenue constant, LLM model configuration, storage backend,
MEAT billing gate setting, PHI scrub level, and settings completeness.

No database or network required.
"""
from __future__ import annotations

import os

import pytest


# ---------------------------------------------------------------------------
# 1. CMS revenue per RAF point
# ---------------------------------------------------------------------------

class TestCmsRevenue:
    """CMS revenue per RAF point must be a realistic value."""

    def test_revenue_per_raf_point_reasonable(self):
        from app.config import settings
        # CMS MA revenue per 1.0 RAF is approximately $11,800 for PY2026
        assert settings.cms_revenue_per_raf_point >= 10000
        assert settings.cms_revenue_per_raf_point <= 20000

    def test_revenue_is_float(self):
        from app.config import settings
        assert isinstance(settings.cms_revenue_per_raf_point, float)


# ---------------------------------------------------------------------------
# 2. LLM billing gate setting
# ---------------------------------------------------------------------------

class TestLlmBillingGate:
    """require_llm_meat_for_billing must be configured."""

    def test_attribute_exists(self):
        from app.config import settings
        assert hasattr(settings, "require_llm_meat_for_billing")

    def test_is_boolean(self):
        from app.config import settings
        assert isinstance(settings.require_llm_meat_for_billing, bool)


# ---------------------------------------------------------------------------
# 3. Gemini model configuration
# ---------------------------------------------------------------------------

class TestGeminiModelConfig:
    """Gemini and LLM model settings must be non-empty."""

    def test_gemini_model_configured(self):
        from app.config import settings
        assert settings.gemini_model
        assert "gemini" in settings.gemini_model.lower()

    def test_llm_model_blind_configured(self):
        from app.config import settings
        assert hasattr(settings, "llm_model_blind")
        assert settings.llm_model_blind  # non-empty

    def test_llm_model_contextual_configured(self):
        from app.config import settings
        assert hasattr(settings, "llm_model_contextual")
        assert settings.llm_model_contextual

    def test_llm_model_meat_configured(self):
        from app.config import settings
        assert hasattr(settings, "llm_model_meat")
        assert settings.llm_model_meat

    def test_llm_model_suspect_configured(self):
        from app.config import settings
        assert hasattr(settings, "llm_model_suspect")
        assert settings.llm_model_suspect

    def test_all_models_are_strings(self):
        from app.config import settings
        for attr in ("llm_model_blind", "llm_model_contextual",
                     "llm_model_meat", "llm_model_suspect"):
            val = getattr(settings, attr)
            assert isinstance(val, str), f"{attr} must be a string"


# ---------------------------------------------------------------------------
# 4. Storage backend
# ---------------------------------------------------------------------------

class TestStorageBackend:
    """Storage backend must be a valid option."""

    def test_storage_backend_valid(self):
        from app.config import settings
        assert settings.storage_backend in ("local", "s3")

    def test_storage_backend_is_string(self):
        from app.config import settings
        assert isinstance(settings.storage_backend, str)


# ---------------------------------------------------------------------------
# 5. PHI scrub level
# ---------------------------------------------------------------------------

class TestPhiScrubLevel:
    """PHI scrubbing configuration."""

    def test_phi_scrub_level_env_default(self):
        level = os.getenv("PHI_SCRUB_LEVEL", "aggressive")
        assert level in ("aggressive", "standard")


# ---------------------------------------------------------------------------
# 6. Settings object structure
# ---------------------------------------------------------------------------

class TestSettingsStructure:
    """Settings singleton must have required attributes."""

    def test_has_jwt_secret(self):
        from app.config import settings
        assert hasattr(settings, "jwt_secret")

    def test_has_jwt_algorithm(self):
        from app.config import settings
        assert hasattr(settings, "jwt_algorithm")

    def test_has_access_token_expire_minutes(self):
        from app.config import settings
        assert hasattr(settings, "access_token_expire_minutes")

    def test_has_idle_timeout_minutes(self):
        from app.config import settings
        assert hasattr(settings, "idle_timeout_minutes")

    def test_has_cms_revenue_per_raf_point(self):
        from app.config import settings
        assert hasattr(settings, "cms_revenue_per_raf_point")

    def test_has_storage_backend(self):
        from app.config import settings
        assert hasattr(settings, "storage_backend")

    def test_has_gemini_model(self):
        from app.config import settings
        assert hasattr(settings, "gemini_model")


# ---------------------------------------------------------------------------
# 7. Eligible encounter types constant
# ---------------------------------------------------------------------------

class TestEligibleEncounterTypes:
    """DOS rules module exports correct encounter type set."""

    def test_eligible_types_include_inpatient(self):
        from app.services.raf.dos_rules import ELIGIBLE_ENCOUNTER_TYPES
        assert "inpatient" in ELIGIBLE_ENCOUNTER_TYPES

    def test_eligible_types_include_outpatient(self):
        from app.services.raf.dos_rules import ELIGIBLE_ENCOUNTER_TYPES
        assert "outpatient" in ELIGIBLE_ENCOUNTER_TYPES

    def test_eligible_types_include_professional(self):
        from app.services.raf.dos_rules import ELIGIBLE_ENCOUNTER_TYPES
        assert "professional" in ELIGIBLE_ENCOUNTER_TYPES

    def test_eligible_types_include_telehealth(self):
        from app.services.raf.dos_rules import ELIGIBLE_ENCOUNTER_TYPES
        assert "telehealth" in ELIGIBLE_ENCOUNTER_TYPES

    def test_lab_is_not_eligible(self):
        from app.services.raf.dos_rules import ELIGIBLE_ENCOUNTER_TYPES
        assert "lab" not in ELIGIBLE_ENCOUNTER_TYPES

    def test_pharmacy_is_not_eligible(self):
        from app.services.raf.dos_rules import ELIGIBLE_ENCOUNTER_TYPES
        assert "pharmacy" not in ELIGIBLE_ENCOUNTER_TYPES
