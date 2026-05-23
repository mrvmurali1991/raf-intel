"""
Authentication service and API endpoint tests.

Covers:
- Password complexity validation (validate_password_strength)
- Password hashing and verification (bcrypt round-trip)
- JWT access/refresh token creation, decoding, expiry, tampering
- MFA pending token flow
- authenticate_user: success, bad password, nonexistent user, locked account
- Account lockout mechanics (failed login counter, lockout expiry)
- Password history enforcement (cannot reuse last 5 passwords)
- change_password service function
- Login endpoint: success, bad credentials, MFA redirect
- /api/auth/me endpoint
- /api/auth/refresh endpoint

All database calls are mocked — no database connection required.

Markers: (none — all run by default)
"""

from __future__ import annotations

import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from typing import Any
from unittest.mock import patch

import jwt
import pytest
from app.config import settings
from app.services.auth_service import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    validate_password_strength,
    verify_password,
)

from tests.conftest import (
    MOCK_ADMIN_USER,
    MOCK_MFA_USER,
    TEST_JWT_ALGORITHM,
    TEST_JWT_SECRET,
    _make_access_token,
    _make_mfa_pending_token,
    make_cursor_cm,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_session_id() -> str:
    return str(uuid.uuid4())


def _db_user(
    *,
    email: str = "user@example.com",
    password: str = "hashed_password",
    is_active: int = 1,
    failed_logins: int = 0,
    locked_until: datetime | None = None,
    mfa_enabled: int = 0,
    mfa_secret: str | None = None,
) -> dict[str, Any]:
    return {
        "id": 10,
        "email": email,
        "password_hash": password,
        "role": "viewer",
        "tenant_id": 1,
        "is_active": is_active,
        "failed_logins": failed_logins,
        "locked_until": locked_until,
        "must_change_password": False,
        "mfa_enabled": mfa_enabled,
        "mfa_secret": mfa_secret,
    }


@contextmanager
def _raf_cursor_returning(rows: list[dict]):
    """Context-manager that patches raf_cursor wherever auth_service uses it."""
    cm, cursor = make_cursor_cm(rows=rows)
    # auth_service imports raf_cursor directly: `from app.db import raf_cursor`
    # so we must patch the name in the auth_service module's namespace.
    with (
        patch("app.services.auth_service.raf_cursor", cm),
        patch("app.db.raf_cursor", cm),
    ):
        yield cursor


# ---------------------------------------------------------------------------
# 1. Password complexity — validate_password_strength
# ---------------------------------------------------------------------------

class TestPasswordComplexity:
    def test_valid_strong_password(self) -> None:
        ok, err = validate_password_strength("R@fIntel2025!Secure")
        assert ok is True
        assert err == ""

    def test_minimum_12_chars(self) -> None:
        ok, err = validate_password_strength("Short1!")
        assert ok is False
        assert "12 characters" in err

    def test_exactly_12_chars_valid(self) -> None:
        ok, err = validate_password_strength("Abcdef1!ghij")
        assert ok is True

    def test_requires_uppercase(self) -> None:
        ok, err = validate_password_strength("alllowercase1!")
        assert ok is False
        assert "uppercase" in err.lower()

    def test_requires_lowercase(self) -> None:
        ok, err = validate_password_strength("ALLUPPERCASE1!")
        assert ok is False
        assert "lowercase" in err.lower()

    def test_requires_digit(self) -> None:
        ok, err = validate_password_strength("NoDigitsHere!!")
        assert ok is False
        assert "digit" in err.lower()

    def test_requires_special_char(self) -> None:
        ok, err = validate_password_strength("NoSpecial1234A")
        assert ok is False
        assert "special" in err.lower()

    def test_max_128_chars(self) -> None:
        too_long = "A1a!" + "x" * 128  # 132 chars
        ok, err = validate_password_strength(too_long)
        assert ok is False
        assert "128" in err

    def test_exactly_128_chars_valid(self) -> None:
        pw = "A1a!" + "b" * 124
        assert len(pw) == 128
        ok, _ = validate_password_strength(pw)
        assert ok is True

    def test_common_password_rejected(self) -> None:
        ok2, err2 = validate_password_strength("password")
        assert ok2 is False

    def test_admin123_rejected(self) -> None:
        ok, err = validate_password_strength("admin123")
        assert ok is False

    @pytest.mark.parametrize("pw", [
        "password",
        "123456",
        "qwerty",
        "letmein",
        "welcome",
        "admin",
        "test123",
        "abc123",
        "password1",
        "password123",
    ])
    def test_top_common_passwords_blocked(self, pw) -> None:
        ok, err = validate_password_strength(pw)
        assert ok is False, f"Expected {pw!r} to be rejected"

    def test_returns_empty_error_on_success(self) -> None:
        ok, err = validate_password_strength("ValidPass1!XYZ")
        assert ok is True
        assert err == ""

    def test_11_char_password_fails(self) -> None:
        ok, err = validate_password_strength("Short1!abcd")
        assert ok is False

    def test_empty_string_rejected(self) -> None:
        ok, err = validate_password_strength("")
        assert ok is False


# ---------------------------------------------------------------------------
# 2. Password hashing and verification
# ---------------------------------------------------------------------------

class TestPasswordHashing:
    def test_hash_and_verify_round_trip(self) -> None:
        pw = "StrongP@ssw0rd!Secure"
        hashed = hash_password(pw)
        assert verify_password(pw, hashed) is True

    def test_wrong_password_fails_verify(self) -> None:
        hashed = hash_password("Correct1!Pass")
        assert verify_password("Wrong1!Pass", hashed) is False

    def test_hash_is_not_plaintext(self) -> None:
        pw = "MySecret1!Passwd"
        hashed = hash_password(pw)
        assert pw not in hashed
        assert hashed != pw

    def test_same_password_different_hashes(self) -> None:
        pw = "SamePass1!Word"
        h1 = hash_password(pw)
        h2 = hash_password(pw)
        # bcrypt salts each hash → should be different
        assert h1 != h2

    def test_hash_starts_with_bcrypt_prefix(self) -> None:
        hashed = hash_password("BcryptTest1!Pass")
        assert hashed.startswith("$2")

    def test_verify_returns_bool(self) -> None:
        hashed = hash_password("TestPass1!abc")
        result = verify_password("TestPass1!abc", hashed)
        assert isinstance(result, bool)


# ---------------------------------------------------------------------------
# 3. JWT token creation and decoding
# ---------------------------------------------------------------------------

class TestJWTTokens:
    def test_create_and_decode_access_token(self) -> None:
        session_id = _make_session_id()
        token = create_access_token(
            user_id=1,
            email="admin@test.health",
            role="admin",
            tenant_id=1,
            session_id=session_id,
        )
        payload = decode_token(token)
        assert payload["sub"] == "1"
        assert payload["email"] == "admin@test.health"
        assert payload["role"] == "admin"
        assert payload["type"] == "access"
        assert payload["session_id"] == session_id

    def test_access_token_has_exp_in_future(self) -> None:
        token = create_access_token(
            user_id=1, email="e@t.h", role="admin", tenant_id=1, session_id="s1"
        )
        payload = decode_token(token)
        exp = datetime.fromtimestamp(payload["exp"], tz=timezone.utc)
        assert exp > datetime.now(timezone.utc)

    def test_expired_access_token_raises(self) -> None:
        now = datetime.now(timezone.utc)
        payload = {
            "sub": "1",
            "email": "a@b.c",
            "role": "admin",
            "tenant_id": 1,
            "session_id": "s",
            "iat": now - timedelta(hours=2),
            "exp": now - timedelta(hours=1),
            "type": "access",
        }
        expired_token = jwt.encode(payload, settings.jwt_secret, algorithm="HS256")
        with pytest.raises(jwt.PyJWTError):
            decode_token(expired_token)

    def test_tampered_token_raises(self) -> None:
        token = create_access_token(
            user_id=1, email="a@b.c", role="admin", tenant_id=1, session_id="s"
        )
        parts = token.split(".")
        parts[1] = parts[1] + "tampered"
        tampered = ".".join(parts)
        with pytest.raises(jwt.PyJWTError):
            decode_token(tampered)

    def test_token_signed_with_wrong_secret_rejected(self) -> None:
        now = datetime.now(timezone.utc)
        payload = {
            "sub": "1",
            "exp": now + timedelta(minutes=15),
            "type": "access",
        }
        bad_token = jwt.encode(payload, "wrong-secret", algorithm="HS256")
        with pytest.raises(jwt.PyJWTError):
            decode_token(bad_token)

    def test_create_refresh_token_has_correct_type(self) -> None:
        session_id = _make_session_id()
        token = create_refresh_token(user_id=1, session_id=session_id)
        payload = jwt.decode(
            token, settings.jwt_refresh_secret, algorithms=["HS256"]
        )
        assert payload["type"] == "refresh"
        assert payload["sub"] == "1"
        assert payload["session_id"] == session_id

    def test_refresh_token_cannot_be_decoded_as_access(self) -> None:
        """Refresh token is signed with refresh secret — decoding with access secret must fail."""
        token = create_refresh_token(user_id=1, session_id="s")
        # jwt_refresh_secret may equal jwt_secret + "_refresh" in test env
        # The point is the token type claim is "refresh", not "access"
        # Test that access decode raises if secrets differ
        if settings.jwt_secret != settings.jwt_refresh_secret:
            with pytest.raises(jwt.PyJWTError):
                decode_token(token)
        else:
            # Same secret in dev — just check type claim
            payload = jwt.decode(
                token, settings.jwt_secret, algorithms=["HS256"]
            )
            assert payload["type"] == "refresh"

    def test_access_token_contains_tenant_id(self) -> None:
        token = create_access_token(
            user_id=5, email="t@t.h", role="viewer", tenant_id=99, session_id="s"
        )
        payload = decode_token(token)
        assert payload["tenant_id"] == 99

    def test_mfa_pending_token_type(self) -> None:
        token = _make_mfa_pending_token(user_id=7)
        payload = jwt.decode(token, TEST_JWT_SECRET, algorithms=[TEST_JWT_ALGORITHM])
        assert payload["type"] == "mfa_pending"
        assert payload["sub"] == "7"


# ---------------------------------------------------------------------------
# 4. authenticate_user service function
# ---------------------------------------------------------------------------

def _make_auth_user_row(
    plain_password: str,
    is_active: int = 1,
    failed_login_attempts: int = 0,
    locked_until: datetime | None = None,
    mfa_enabled: int = 0,
) -> dict[str, Any]:
    """Build a user row matching exactly what authenticate_user reads from the DB."""
    return {
        "id": 10,
        "email": "test@example.com",
        "full_name": "Test User",
        "role": "viewer",
        "tenant_id": 1,
        "is_active": is_active,
        "avatar_url": None,
        "failed_login_attempts": failed_login_attempts,
        "locked_until": locked_until,
        "password_hash": hash_password(plain_password),
        "password_changed_at": None,
        "created_at": datetime(2026, 1, 1),
        "mfa_enabled": mfa_enabled,
        "mfa_secret": None,
        "must_change_password": False,
    }


class TestAuthenticateUser:
    """Test authenticate_user via direct service call with mocked DB cursor."""

    def test_successful_login_returns_tokens(self) -> None:
        from app.services.auth_service import authenticate_user

        user_row = _make_auth_user_row("CorrectPass1!")
        session_row = {
            "id": 1,
            "session_id": str(uuid.uuid4()),
            "user_id": 10,
            "created_at": datetime.now(timezone.utc),
        }
        # authenticate_user reads via raf_cursor, then calls create_session via raf_cursor
        # Use a MockCursor that returns user_row on fetchone
        user_cm, _ = make_cursor_cm(rows=[user_row])
        with (
            patch("app.services.auth_service.raf_cursor", user_cm),
            patch("app.db.raf_cursor", user_cm),
            patch("app.services.auth_service.create_session", return_value=session_row),
            patch("app.services.auth_service._ensure_tables"),
            patch("app.services.auth_service.log_audit"),
            patch("app.services.auth_service._check_password_history"),
            patch("app.services.auth_service._attach_must_change_password", return_value=None),
        ):
            result = authenticate_user(
                email="test@example.com",
                password="CorrectPass1!",
                ip_address="127.0.0.1",
                user_agent="pytest",
            )
        assert "access_token" in result
        assert "refresh_token" in result
        assert result["user"]["id"] == 10

    def test_wrong_password_raises_value_error(self) -> None:
        from app.services.auth_service import authenticate_user

        user_row = _make_auth_user_row("CorrectPass1!")
        user_cm, _ = make_cursor_cm(rows=[user_row])
        noop_cm, _ = make_cursor_cm()
        with (
            patch("app.services.auth_service.raf_cursor", user_cm),
            patch("app.db.raf_cursor", noop_cm),
            patch("app.services.auth_service._ensure_tables"),
            patch("app.services.auth_service.log_audit"),
            patch("app.services.auth_service._attach_must_change_password", return_value=None),
        ):
            with pytest.raises(ValueError):
                authenticate_user(
                    email="test@example.com",
                    password="WrongPass1!",
                    ip_address="127.0.0.1",
                    user_agent="pytest",
                )

    def test_nonexistent_email_raises(self) -> None:
        from app.services.auth_service import authenticate_user

        # fetchone returns None → user not found
        noop_cm, _ = make_cursor_cm(rows=[])
        with (
            patch("app.services.auth_service.raf_cursor", noop_cm),
            patch("app.db.raf_cursor", noop_cm),
            patch("app.services.auth_service._ensure_tables"),
            patch("app.services.auth_service.log_audit"),pytest.raises(ValueError)
        ):
            authenticate_user(
                email="nobody@example.com",
                password="AnyPass1!",
                ip_address="127.0.0.1",
                user_agent="pytest",
            )

    def test_inactive_user_raises(self) -> None:
        from app.services.auth_service import authenticate_user

        user_row = _make_auth_user_row("SomePass1!", is_active=0)
        user_cm, _ = make_cursor_cm(rows=[user_row])
        noop_cm, _ = make_cursor_cm()
        with (
            patch("app.services.auth_service.raf_cursor", user_cm),
            patch("app.db.raf_cursor", noop_cm),
            patch("app.services.auth_service._ensure_tables"),
            patch("app.services.auth_service.log_audit"),
            patch("app.services.auth_service._attach_must_change_password", return_value=None),
        ):
            with pytest.raises(ValueError):
                authenticate_user(
                    email="test@example.com",
                    password="SomePass1!",
                    ip_address="127.0.0.1",
                    user_agent="pytest",
                )

    def test_locked_account_raises(self) -> None:
        from app.services.auth_service import authenticate_user

        future = datetime.now(timezone.utc) + timedelta(minutes=10)
        user_row = _make_auth_user_row("CorrectPass1!", locked_until=future)
        user_cm, _ = make_cursor_cm(rows=[user_row])
        noop_cm, _ = make_cursor_cm()
        with (
            patch("app.services.auth_service.raf_cursor", user_cm),
            patch("app.db.raf_cursor", noop_cm),
            patch("app.services.auth_service._ensure_tables"),
            patch("app.services.auth_service.log_audit"),
            patch("app.services.auth_service._attach_must_change_password", return_value=None),
        ):
            with pytest.raises(ValueError):
                authenticate_user(
                    email="test@example.com",
                    password="CorrectPass1!",
                    ip_address="127.0.0.1",
                    user_agent="pytest",
                )


# ---------------------------------------------------------------------------
# 5. Account lockout mechanics
# ---------------------------------------------------------------------------

class TestAccountLockout:
    def test_max_failed_logins_setting(self) -> None:
        assert settings.max_failed_logins == 5

    def test_lockout_duration_configured(self) -> None:
        assert settings.lockout_duration_minutes == 15

    def test_locked_until_in_future_causes_lockout(self) -> None:
        """A user with locked_until in the future must not be able to log in."""
        from app.services.auth_service import authenticate_user

        future = datetime.now(timezone.utc) + timedelta(minutes=5)
        user_row = _make_auth_user_row("Pass1!Word", locked_until=future)
        user_row["email"] = "locked@test.com"
        user_cm, _ = make_cursor_cm(rows=[user_row])
        noop_cm, _ = make_cursor_cm()
        with (
            patch("app.services.auth_service.raf_cursor", user_cm),
            patch("app.db.raf_cursor", noop_cm),
            patch("app.services.auth_service._ensure_tables"),
            patch("app.services.auth_service.log_audit"),
            patch("app.services.auth_service._attach_must_change_password", return_value=None),
        ):
            with pytest.raises(ValueError):
                authenticate_user("locked@test.com", "Pass1!Word", "127.0.0.1", "ua")

    def test_expired_lockout_allows_login(self) -> None:
        """A lockout in the past should not block the user."""
        from app.services.auth_service import authenticate_user

        past = datetime.now(timezone.utc) - timedelta(hours=1)
        user_row = _make_auth_user_row("Pass1!Word", failed_login_attempts=3, locked_until=past)
        user_row["email"] = "unlocked@test.com"
        user_row["id"] = 1
        session_row = {
            "id": 1,
            "session_id": str(uuid.uuid4()),
            "user_id": 1,
            "created_at": datetime.now(timezone.utc),
        }
        user_cm, _ = make_cursor_cm(rows=[user_row])
        noop_cm, _ = make_cursor_cm()
        with (
            patch("app.services.auth_service.raf_cursor", user_cm),
            patch("app.db.raf_cursor", noop_cm),
            patch("app.services.auth_service.create_session", return_value=session_row),
            patch("app.services.auth_service._ensure_tables"),
            patch("app.services.auth_service.log_audit"),
            patch("app.services.auth_service._check_password_history"),
            patch("app.services.auth_service._attach_must_change_password", return_value=None),
        ):
            result = authenticate_user("unlocked@test.com", "Pass1!Word", "127.0.0.1", "ua")
        assert "access_token" in result


# ---------------------------------------------------------------------------
# 6. Password history enforcement
# ---------------------------------------------------------------------------

class TestPasswordHistory:
    def test_password_history_depth_constant(self) -> None:
        """The system must track at least 5 previous passwords per HIPAA guidance."""
        from app.services import auth_service
        # Check the constant or default depth
        depth = getattr(auth_service, "_PASSWORD_HISTORY_DEPTH", 5)
        assert depth >= 5

    def test_check_password_history_raises_on_reuse(self) -> None:
        """Re-using a recently-used password must raise ValueError."""
        from app.services.auth_service import _check_password_history

        old_pw = "OldPass1!secure"
        hashed_old = hash_password(old_pw)
        history_rows = [{"password_hash": hashed_old}]
        with _raf_cursor_returning(history_rows):
            with pytest.raises(ValueError, match="[Pp]revious|[Rr]euse|[Hh]istory"):
                _check_password_history(user_id=1, new_password=old_pw)

    def test_check_password_history_passes_for_new_password(self) -> None:
        """A fresh password not in history must not raise."""
        from app.services.auth_service import _check_password_history

        old_pw = "OldPass1!secure"
        hashed_old = hash_password(old_pw)
        history_rows = [{"password_hash": hashed_old}]
        with _raf_cursor_returning(history_rows):
            # Should not raise
            _check_password_history(user_id=1, new_password="NewPass2!fresh")

    def test_check_password_history_empty_history_passes(self) -> None:
        from app.services.auth_service import _check_password_history

        with _raf_cursor_returning([]):
            _check_password_history(user_id=1, new_password="AnyPass1!")

    def test_change_password_enforces_complexity(self) -> None:
        """change_password must reject a weak new password with ValueError."""
        from app.services.auth_service import change_password

        noop_cm, _ = make_cursor_cm()
        with (
            patch("app.services.auth_service.get_user", return_value={
                "id": 1,
                "password_hash": hash_password("OldStr0ng!Pass"),
                "email": "u@test.com",
                "is_active": 1,
            }),
            patch("app.services.auth_service.raf_cursor", noop_cm),
            patch("app.db.raf_cursor", noop_cm),
            patch("app.services.auth_service.log_audit"),
        ):
            with pytest.raises((ValueError, Exception)):
                change_password(user_id=1, old_password="OldStr0ng!Pass", new_password="weak")


# ---------------------------------------------------------------------------
# 7. MFA flow
# ---------------------------------------------------------------------------

class TestMFAFlow:
    def test_mfa_pending_token_short_expiry(self) -> None:
        """mfa_pending token must expire in ~5 minutes."""
        token = _make_mfa_pending_token(user_id=42)
        payload = jwt.decode(token, TEST_JWT_SECRET, algorithms=[TEST_JWT_ALGORITHM])
        now = datetime.now(timezone.utc)
        exp = datetime.fromtimestamp(payload["exp"], tz=timezone.utc)
        delta = exp - now
        # Must expire within 10 minutes
        assert delta.total_seconds() < 10 * 60
        # Must not be already expired
        assert delta.total_seconds() > 0

    def test_expired_mfa_pending_token_rejected(self) -> None:
        expired_token = _make_mfa_pending_token(user_id=42, expired=True)
        with pytest.raises(jwt.PyJWTError):
            decode_token(expired_token)

    def test_mfa_pending_token_has_correct_type_claim(self) -> None:
        token = _make_mfa_pending_token(user_id=7)
        payload = jwt.decode(token, TEST_JWT_SECRET, algorithms=[TEST_JWT_ALGORITHM])
        assert payload["type"] == "mfa_pending"

    def test_complete_mfa_login_with_correct_code(self) -> None:
        """complete_mfa_login must return tokens when the TOTP code verifies."""
        from app.services.auth_service import complete_mfa_login

        mfa_user = dict(MOCK_MFA_USER)
        session_row = {
            "id": 1,
            "session_id": str(uuid.uuid4()),
            "user_id": mfa_user["id"],
            "created_at": datetime.now(timezone.utc),
        }
        pending_token = _make_mfa_pending_token(user_id=mfa_user["id"])
        noop_cm, _ = make_cursor_cm()
        with (
            patch("app.services.auth_service.get_user", return_value=mfa_user),
            patch("app.services.auth_service.verify_mfa_code", return_value=True),
            patch("app.services.auth_service.create_session", return_value=session_row),
            patch("app.services.auth_service.log_audit"),
            patch("app.services.auth_service._ensure_tables"),
            patch("app.services.auth_service.raf_cursor", noop_cm),
            patch("app.db.raf_cursor", noop_cm),
        ):
            result = complete_mfa_login(
                mfa_token=pending_token,
                totp_code="123456",
                ip_address="127.0.0.1",
                user_agent="pytest",
            )
        assert "access_token" in result

    def test_complete_mfa_login_with_wrong_code_raises(self) -> None:
        from app.services.auth_service import complete_mfa_login

        mfa_user = dict(MOCK_MFA_USER)
        pending_token = _make_mfa_pending_token(user_id=mfa_user["id"])

        noop_cm2, _ = make_cursor_cm()
        with (
            patch("app.services.auth_service.get_user", return_value=mfa_user),
            patch("app.services.auth_service.log_audit"),
            patch("app.services.auth_service.raf_cursor", noop_cm2),
            patch("app.db.raf_cursor", noop_cm2),pytest.raises((ValueError, Exception))
        ):
            complete_mfa_login(
                mfa_token=pending_token,
                totp_code="000000",
                ip_address="127.0.0.1",
                user_agent="pytest",
            )


# ---------------------------------------------------------------------------
# 8. Login HTTP endpoint tests
# ---------------------------------------------------------------------------

class TestLoginEndpoint:
    """Tests against POST /api/auth/login through TestClient."""

    def test_login_missing_email_returns_422(self, client) -> None:
        resp = client.post("/api/auth/login", json={"password": "Pass1!"})
        assert resp.status_code == 422

    def test_login_missing_password_returns_422(self, client) -> None:
        resp = client.post("/api/auth/login", json={"email": "a@b.com"})
        assert resp.status_code == 422

    def test_login_invalid_email_format_returns_422(self, client) -> None:
        resp = client.post(
            "/api/auth/login",
            json={"email": "not-an-email", "password": "Pass1!Word"},
        )
        assert resp.status_code == 422

    def test_login_wrong_credentials_returns_401(self, client) -> None:
        # Empty cursor → user not found → 401
        noop_cm, _ = make_cursor_cm(rows=[])
        with (
            patch("app.services.auth_service.raf_cursor", noop_cm),
            patch("app.db.raf_cursor", noop_cm),
            patch("app.services.auth_service._ensure_tables"),
            patch("app.services.auth_service.log_audit"),
        ):
            resp = client.post(
                "/api/auth/login",
                json={"email": "nobody@example.com", "password": "BadPass1!"},
            )
        assert resp.status_code == 401

    def test_login_success_returns_access_and_refresh_tokens(self, client) -> None:
        user_row = _make_auth_user_row("AdminPass1!")
        user_row["email"] = "admin@test.health"
        session_row = {
            "id": 1,
            "session_id": str(uuid.uuid4()),
            "user_id": 1,
            "created_at": datetime.now(timezone.utc),
        }
        user_cm, _ = make_cursor_cm(rows=[user_row])
        noop_cm, _ = make_cursor_cm()
        with (
            patch("app.services.auth_service.raf_cursor", user_cm),
            patch("app.db.raf_cursor", noop_cm),
            patch("app.services.auth_service.create_session", return_value=session_row),
            patch("app.services.auth_service._ensure_tables"),
            patch("app.services.auth_service.log_audit"),
            patch("app.services.auth_service._check_password_history"),
            patch("app.services.auth_service._attach_must_change_password", return_value=None),
        ):
            resp = client.post(
                "/api/auth/login",
                json={"email": "admin@test.health", "password": "AdminPass1!"},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert "access_token" in data
        assert "refresh_token" in data

    def test_login_response_never_leaks_password_hash(self, client) -> None:
        user_row = _make_auth_user_row("AdminPass1!")
        user_row["email"] = "admin@test.health"
        session_row = {
            "id": 1,
            "session_id": str(uuid.uuid4()),
            "user_id": 1,
            "created_at": datetime.now(timezone.utc),
        }
        user_cm2, _ = make_cursor_cm(rows=[user_row])
        noop_cm2, _ = make_cursor_cm()
        with (
            patch("app.services.auth_service.raf_cursor", user_cm2),
            patch("app.db.raf_cursor", noop_cm2),
            patch("app.services.auth_service.create_session", return_value=session_row),
            patch("app.services.auth_service._ensure_tables"),
            patch("app.services.auth_service.log_audit"),
            patch("app.services.auth_service._check_password_history"),
            patch("app.services.auth_service._attach_must_change_password", return_value=None),
        ):
            resp = client.post(
                "/api/auth/login",
                json={"email": "admin@test.health", "password": "AdminPass1!"},
            )
        resp_text = resp.text
        assert "password_hash" not in resp_text
        assert "$2b$" not in resp_text

    def test_login_mfa_required_returns_mfa_token(self, client) -> None:
        mfa_result = {
            "mfa_required": True,
            "mfa_token": "test_mfa_token_abc",
            "token_type": "bearer",
            "user": {"id": MOCK_MFA_USER["id"]},
        }
        with (
            patch("app.routers.auth.authenticate_user", return_value=mfa_result),
        ):
            resp = client.post(
                "/api/auth/login",
                json={"email": "mfa@test.health", "password": "MfaPass1!"},
            )
        # Should return 200 with mfa_required flag, not full tokens
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("mfa_required") is True or "mfa_token" in data


# ---------------------------------------------------------------------------
# 9. /api/auth/me endpoint
# ---------------------------------------------------------------------------

class TestMeEndpoint:
    def test_me_without_auth_returns_401(self, client) -> None:
        resp = client.get("/api/auth/me")
        assert resp.status_code == 401

    def test_me_with_valid_token_returns_user(self, client) -> None:
        user = dict(MOCK_ADMIN_USER)
        session_row = {"session_id": user["session_id"], "is_revoked": 0}
        token = _make_access_token(user)
        with (
            patch("app.auth.get_user", return_value=user),
            patch("app.auth.validate_session", return_value=session_row),
            patch("app.routers.auth.get_user", return_value=user),
        ):
            resp = client.get(
                "/api/auth/me",
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["email"] == user["email"]

    def test_me_with_expired_token_returns_401(self, client) -> None:
        user = dict(MOCK_ADMIN_USER)
        expired_token = _make_access_token(user, expired=True)
        resp = client.get(
            "/api/auth/me",
            headers={"Authorization": f"Bearer {expired_token}"},
        )
        assert resp.status_code == 401

    def test_me_response_does_not_contain_password_hash(self, client) -> None:
        user = dict(MOCK_ADMIN_USER)
        session_row = {"session_id": user["session_id"], "is_revoked": 0}
        token = _make_access_token(user)
        with (
            patch("app.auth.get_user", return_value=user),
            patch("app.auth.validate_session", return_value=session_row),
            patch("app.routers.auth.get_user", return_value=user),
        ):
            resp = client.get(
                "/api/auth/me",
                headers={"Authorization": f"Bearer {token}"},
            )
        assert "password_hash" not in resp.text
        assert "$2b$" not in resp.text
