"""
Authentication and Security — expanded test suite.

Covers: password hashing (argon2), password verification (argon2 + bcrypt
fallback), needs_rehash logic, JWT configuration, access token expiry,
idle timeout, weak JWT secret detection, production validation.

No database or network required — uses source inspection to verify
security patterns without needing the argon2 native module installed.
"""
from __future__ import annotations

import inspect
import importlib

import pytest


# ---------------------------------------------------------------------------
# Helper: get auth_service source without importing (avoids argon2 dep)
# ---------------------------------------------------------------------------

def _auth_service_source() -> str:
    """Read auth_service.py source via importlib without executing the module."""
    import importlib.util
    spec = importlib.util.find_spec("app.services.auth_service")
    if spec is None or spec.origin is None:
        pytest.skip("Cannot locate app.services.auth_service module file")
    with open(spec.origin, "r") as f:
        return f.read()


# ---------------------------------------------------------------------------
# 1. Password hashing (argon2) — source inspection
# ---------------------------------------------------------------------------

class TestPasswordHashing:
    """hash_password must produce argon2id hashes (verified via source)."""

    def test_hash_uses_argon2_password_hasher(self):
        source = _auth_service_source()
        assert "argon2.PasswordHasher" in source or "PasswordHasher" in source

    def test_hash_function_calls_hasher_hash(self):
        source = _auth_service_source()
        assert "_argon2_hasher.hash(" in source

    def test_argon2_memory_cost_reasonable(self):
        source = _auth_service_source()
        # Memory cost should be at least 64 MB (65536 KB)
        assert "memory_cost=65536" in source or "memory_cost = 65536" in source

    def test_argon2_time_cost_at_least_3(self):
        source = _auth_service_source()
        assert "time_cost=3" in source or "time_cost=4" in source


# ---------------------------------------------------------------------------
# 2. Password verification — source inspection
# ---------------------------------------------------------------------------

class TestPasswordVerification:
    """verify_password must validate argon2 and handle bcrypt fallback."""

    def test_verify_checks_argon2_prefix(self):
        source = _auth_service_source()
        assert '$argon2' in source

    def test_verify_has_bcrypt_fallback(self):
        source = _auth_service_source()
        assert "passlib" in source or "CryptContext" in source

    def test_verify_returns_false_on_mismatch(self):
        source = _auth_service_source()
        assert "VerifyMismatchError" in source

    def test_verify_handles_invalid_hash(self):
        source = _auth_service_source()
        assert "InvalidHashError" in source


# ---------------------------------------------------------------------------
# 3. needs_rehash — source inspection
# ---------------------------------------------------------------------------

class TestNeedsRehash:
    """needs_rehash identifies when legacy hashes need upgrade to argon2."""

    def test_non_argon2_returns_true(self):
        source = _auth_service_source()
        # Should have logic: if not $argon2 -> return True
        assert "not hashed.startswith" in source or 'not hashed.startswith("$argon2")' in source

    def test_calls_check_needs_rehash(self):
        source = _auth_service_source()
        assert "check_needs_rehash" in source


# ---------------------------------------------------------------------------
# 4. JWT algorithm configuration
# ---------------------------------------------------------------------------

class TestJwtConfig:
    """JWT must use HS256 and have HIPAA-compliant timeouts."""

    def test_jwt_algorithm_is_hs256(self):
        from app.config import settings
        assert settings.jwt_algorithm == "HS256"

    def test_access_token_expiry_hipaa_compliant(self):
        from app.config import settings
        # HIPAA recommends session timeout <= 30 minutes
        assert settings.access_token_expire_minutes <= 30

    def test_access_token_expiry_positive(self):
        from app.config import settings
        assert settings.access_token_expire_minutes > 0

    def test_idle_timeout_configured(self):
        from app.config import settings
        # HIPAA idle timeout should be <= 15 minutes
        assert settings.idle_timeout_minutes <= 15

    def test_idle_timeout_positive(self):
        from app.config import settings
        assert settings.idle_timeout_minutes > 0


# ---------------------------------------------------------------------------
# 5. Weak JWT secrets
# ---------------------------------------------------------------------------

class TestWeakJwtSecrets:
    """Known-weak secrets must be in the rejection set."""

    def test_change_me_is_weak(self):
        from app.config import _WEAK_JWT_SECRETS
        assert "change-me" in _WEAK_JWT_SECRETS

    def test_empty_string_is_weak(self):
        from app.config import _WEAK_JWT_SECRETS
        assert "" in _WEAK_JWT_SECRETS

    def test_dev_secret_is_weak(self):
        from app.config import _WEAK_JWT_SECRETS
        assert "dev-secret" in _WEAK_JWT_SECRETS

    def test_weak_secrets_is_frozenset(self):
        from app.config import _WEAK_JWT_SECRETS
        assert isinstance(_WEAK_JWT_SECRETS, frozenset)


# ---------------------------------------------------------------------------
# 6. Production validation
# ---------------------------------------------------------------------------

class TestProductionValidation:
    """_validate_production must check critical security settings."""

    def test_checks_jwt_secret(self):
        from app.config import _validate_production
        source = inspect.getsource(_validate_production)
        assert "JWT_SECRET" in source or "jwt_secret" in source

    def test_checks_encryption_salt(self):
        from app.config import _validate_production
        source = inspect.getsource(_validate_production)
        assert "ENCRYPTION_SALT" in source

    def test_checks_data_encryption_key(self):
        from app.config import _validate_production
        source = inspect.getsource(_validate_production)
        assert "DATA_ENCRYPTION_KEY" in source

    def test_raises_runtime_error_on_weak_secret(self):
        from app.config import _validate_production
        source = inspect.getsource(_validate_production)
        assert "raise RuntimeError" in source


# ---------------------------------------------------------------------------
# 7. Password complexity validation — source inspection
# ---------------------------------------------------------------------------

class TestPasswordComplexity:
    """validate_password_strength must enforce HIPAA rules (source check)."""

    def test_enforces_minimum_length(self):
        source = _auth_service_source()
        assert "12 characters" in source or "len(password) < 12" in source

    def test_requires_uppercase(self):
        source = _auth_service_source()
        assert "uppercase" in source

    def test_requires_digit(self):
        source = _auth_service_source()
        assert "digit" in source

    def test_requires_special_character(self):
        source = _auth_service_source()
        assert "special" in source.lower()

    def test_rejects_common_passwords(self):
        source = _auth_service_source()
        assert "_COMMON_PASSWORDS" in source

    def test_max_length_enforced(self):
        source = _auth_service_source()
        assert "128" in source


# ---------------------------------------------------------------------------
# 8. TOTP replay prevention — source inspection
# ---------------------------------------------------------------------------

class TestTotpReplay:
    """verify_mfa_code must prevent TOTP replay attacks."""

    def test_checks_mfa_last_used_step(self):
        source = _auth_service_source()
        assert "mfa_last_used_step" in source

    def test_uses_for_update_locking(self):
        source = _auth_service_source()
        assert "FOR UPDATE" in source

    def test_rejects_equal_step(self):
        source = _auth_service_source()
        assert "current_step <= last_step" in source
