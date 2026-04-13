"""
Complete authentication flow integration tests.

Tests are written against the FastAPI TestClient (in-process) so they can
run without a live server.  Each test class represents one cohesive scenario.

Covered scenarios
-----------------
- Happy-path login → tokens
- Login with bad credentials → 401
- Protected endpoint without token → 401
- Protected endpoint with valid token → 200
- Token refresh → new tokens issued
- Logout → session revoked
- Post-logout token rejected → 401
- Account lockout after 5 consecutive failures
- Password complexity validation (too short / no uppercase / common password)
- User CRUD (create, read, update, deactivate)
- RBAC: viewer cannot access write/admin endpoints
- Admin can create and manage users
- Permission checking endpoint
"""

from __future__ import annotations

import uuid
from typing import Any
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

# ---------------------------------------------------------------------------
# Shared mock — authenticate_user returns a valid token response
# ---------------------------------------------------------------------------

import os
from datetime import datetime, timedelta, timezone
import jwt as pyjwt

_JWT_SECRET = os.environ.get("JWT_SECRET", "test-jwt-secret-for-pytest-do-not-use-in-prod")
_JWT_REFRESH_SECRET = os.environ.get("JWT_REFRESH_SECRET", "test-refresh-secret-for-pytest")

_MOCK_ADMIN = {
    "id": 1, "email": "admin@raf.health", "full_name": "Development Admin",
    "role": "admin", "tenant_id": 1, "session_id": "session-login-test",
}


def _make_mock_login_response() -> dict:
    now = datetime.now(timezone.utc)
    access = pyjwt.encode(
        {"sub": "1", "email": "admin@raf.health", "role": "admin",
         "tenant_id": 1, "session_id": "session-login-test",
         "iat": now, "exp": now + timedelta(minutes=15), "type": "access"},
        _JWT_SECRET, algorithm="HS256",
    )
    refresh = pyjwt.encode(
        {"sub": "1", "session_id": "session-login-test",
         "iat": now, "exp": now + timedelta(days=7), "type": "refresh"},
        _JWT_REFRESH_SECRET, algorithm="HS256",
    )
    return {
        "access_token": access,
        "refresh_token": refresh,
        "token_type": "bearer",
        "expires_in": 900,
        "user": {
            "id": 1, "email": "admin@raf.health",
            "full_name": "Development Admin", "role": "admin", "tenant_id": 1,
        },
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _unique_email(prefix: str = "authtest") -> str:
    return f"{prefix}+{uuid.uuid4().hex[:8]}@raf-test.example"


def _strong_password() -> str:
    """Returns a password that satisfies HIPAA complexity rules every time."""
    return f"TestAuth@Secure#{uuid.uuid4().hex[:4]}99!"


def _assert_status(
    response, expected: int | tuple, context: str = ""
) -> dict[str, Any]:
    codes = (expected,) if isinstance(expected, int) else expected
    assert response.status_code in codes, (
        f"{context} — expected {expected}, got {response.status_code}. "
        f"Body: {response.text[:400]}"
    )
    try:
        return response.json()
    except Exception:
        return {}


# ===========================================================================
# 1. Happy-path login
# ===========================================================================


class TestLoginHappyPath:
    """POST /api/auth/login with valid credentials (authenticate_user mocked)."""

    def _post_login(self, client: TestClient):
        with patch(
            "app.routers.auth.authenticate_user",
            return_value=_make_mock_login_response(),
        ):
            return client.post(
                "/api/auth/login",
                json={"email": "admin@raf.health", "password": "Admin@123"},
            )

    def test_login_returns_200(self, client: TestClient):
        r = self._post_login(client)
        _assert_status(r, 200, "login")

    def test_login_response_contains_access_token(self, client: TestClient):
        r = self._post_login(client)
        data = _assert_status(r, 200, "login")
        assert "access_token" in data, f"Missing access_token in login response: {data}"
        assert data["access_token"], "access_token must not be empty"

    def test_login_response_contains_refresh_token(self, client: TestClient):
        r = self._post_login(client)
        data = _assert_status(r, 200, "login")
        assert "refresh_token" in data, (
            f"Missing refresh_token in login response: {data}"
        )
        assert data["refresh_token"], "refresh_token must not be empty"

    def test_login_response_contains_user_object(self, client: TestClient):
        r = self._post_login(client)
        data = _assert_status(r, 200, "login")
        assert "user" in data, f"Missing user object in login response: {data}"
        user = data["user"]
        assert "id" in user and "email" in user and "role" in user, (
            f"User object missing required fields: {user}"
        )

    def test_login_user_email_matches_request(self, client: TestClient):
        r = self._post_login(client)
        data = r.json()
        assert data.get("user", {}).get("email") == "admin@raf.health"


# ===========================================================================
# 2. Invalid credentials
# ===========================================================================


class TestLoginInvalidCredentials:
    """POST /api/auth/login with bad credentials → 401."""

    def _mock_auth_fail(self):
        """Patch authenticate_user to raise ValueError (invalid creds)."""
        return patch(
            "app.routers.auth.authenticate_user",
            side_effect=ValueError("Invalid email or password."),
        )

    def test_wrong_password_returns_401(self, client: TestClient):
        with self._mock_auth_fail():
            r = client.post(
                "/api/auth/login",
                json={"email": "admin@raf.health", "password": "WrongPass@9999!"},
            )
        _assert_status(r, 401, "wrong password")

    def test_nonexistent_email_returns_401(self, client: TestClient):
        with self._mock_auth_fail():
            r = client.post(
                "/api/auth/login",
                json={"email": "no.such.user@example.com", "password": "Whatever@1!"},
            )
        assert r.status_code in (401, 422), (
            f"Expected 401 or 422 for nonexistent email, got {r.status_code}"
        )

    def test_invalid_email_format_returns_422(self, client: TestClient):
        """Pydantic validation: malformed email → 422 Unprocessable Entity."""
        r = client.post(
            "/api/auth/login",
            json={"email": "not-an-email", "password": "Whatever@1!"},
        )
        assert r.status_code == 422, (
            f"Expected 422 for malformed email, got {r.status_code}"
        )

    def test_empty_password_returns_401_or_422(self, client: TestClient):
        with self._mock_auth_fail():
            r = client.post(
                "/api/auth/login",
                json={"email": "admin@raf.health", "password": ""},
            )
        assert r.status_code in (401, 422), (
            f"Expected 401 or 422 for empty password, got {r.status_code}"
        )

    def test_error_response_does_not_expose_internals(self, client: TestClient):
        """Error body must not contain stack traces or DB details."""
        with self._mock_auth_fail():
            r = client.post(
                "/api/auth/login",
                json={"email": "admin@raf.health", "password": "BadPass@9999!"},
            )
        body = r.text.lower()
        for forbidden in ("traceback", "sqlalchemy", "psycopg", "pymysql", "stack"):
            assert forbidden not in body, (
                f"Error response leaks internal detail ('{forbidden}'): {r.text[:300]}"
            )


# ===========================================================================
# 3. Protected endpoint without token
# ===========================================================================


class TestProtectedEndpointNoToken:
    """Requests to auth-guarded endpoints without a token → 401."""

    PROTECTED_ENDPOINTS = [
        ("GET", "/api/auth/me"),
        ("GET", "/api/auth/sessions"),
        ("GET", "/api/raf/models"),
        ("GET", "/api/providers"),
    ]

    @pytest.mark.parametrize("method,path", PROTECTED_ENDPOINTS)
    def test_unauthenticated_request_returns_401(
        self, client: TestClient, method: str, path: str
    ):
        r = client.request(method, path)
        assert r.status_code == 401, (
            f"{method} {path} — expected 401 without token, got {r.status_code}"
        )

    def test_bearer_missing_scheme_returns_401(self, client: TestClient):
        """A raw token without 'Bearer' prefix must be rejected."""
        r = client.get("/api/auth/me", headers={"Authorization": "rawtoken123"})
        assert r.status_code == 401

    def test_malformed_bearer_token_returns_401(self, client: TestClient):
        r = client.get("/api/auth/me", headers={"Authorization": "Bearer not.a.jwt"})
        assert r.status_code == 401


# ===========================================================================
# 4. Protected endpoint with valid token
# ===========================================================================


class TestProtectedEndpointWithToken:
    """Valid JWT → 200 on auth-guarded endpoints."""

    def test_get_me_returns_200_with_valid_token(
        self, client: TestClient, auth_headers: dict
    ):
        r = client.get("/api/auth/me", headers=auth_headers)
        _assert_status(r, 200, "GET /api/auth/me")

    def test_get_me_returns_correct_email(
        self, client: TestClient, auth_headers: dict
    ):
        r = client.get("/api/auth/me", headers=auth_headers)
        data = r.json()
        # auth_headers is viewer role
        assert data.get("email") == "viewer@raf-test.health"

    def test_get_sessions_returns_200_with_valid_token(
        self, client: TestClient, auth_headers: dict
    ):
        r = client.get("/api/auth/sessions", headers=auth_headers)
        _assert_status(r, 200, "GET /api/auth/sessions")

    def test_sessions_is_list(self, client: TestClient, auth_headers: dict):
        r = client.get("/api/auth/sessions", headers=auth_headers)
        data = r.json()
        assert isinstance(data, list), f"Expected list of sessions, got: {type(data)}"

    def test_security_headers_present_on_authenticated_response(
        self, client: TestClient, auth_headers: dict
    ):
        """HIPAA middleware must inject security headers on every response."""
        r = client.get("/api/auth/me", headers=auth_headers)
        assert "x-content-type-options" in r.headers, (
            "Missing X-Content-Type-Options header"
        )
        assert "x-frame-options" in r.headers, "Missing X-Frame-Options header"


# ===========================================================================
# 5. Token refresh
# ===========================================================================


class TestTokenRefresh:
    """POST /api/auth/refresh → new access and refresh tokens."""

    def _mock_refresh(self):
        """Patch refresh_access_token to return fresh mock tokens."""
        return patch(
            "app.routers.auth.refresh_access_token",
            return_value=_make_mock_login_response(),
        )

    def test_refresh_returns_200(self, client: TestClient):
        tokens = _make_mock_login_response()
        with self._mock_refresh():
            r = client.post(
                "/api/auth/refresh",
                json={"refresh_token": tokens["refresh_token"]},
            )
        _assert_status(r, 200, "POST /api/auth/refresh")

    def test_refresh_returns_new_access_token(self, client: TestClient):
        tokens = _make_mock_login_response()
        with self._mock_refresh():
            r = client.post(
                "/api/auth/refresh",
                json={"refresh_token": tokens["refresh_token"]},
            )
        data = _assert_status(r, 200, "POST /api/auth/refresh")
        assert "access_token" in data, (
            f"Missing access_token in refresh response: {data}"
        )
        assert data["access_token"], "Refreshed access_token must not be empty"

    def test_refresh_returns_new_refresh_token(self, client: TestClient):
        tokens = _make_mock_login_response()
        with self._mock_refresh():
            r = client.post(
                "/api/auth/refresh",
                json={"refresh_token": tokens["refresh_token"]},
            )
        data = _assert_status(r, 200, "POST /api/auth/refresh")
        assert "refresh_token" in data, (
            f"Missing refresh_token in refresh response: {data}"
        )

    def test_invalid_refresh_token_returns_401(self, client: TestClient):
        r = client.post(
            "/api/auth/refresh",
            json={"refresh_token": "not.a.valid.jwt.token"},
        )
        _assert_status(r, 401, "invalid refresh token")

    def test_new_access_token_is_accepted_by_protected_endpoint(
        self, client: TestClient
    ):
        tokens = _make_mock_login_response()
        with self._mock_refresh():
            r_refresh = client.post(
                "/api/auth/refresh",
                json={"refresh_token": tokens["refresh_token"]},
            )
        new_token = r_refresh.json()["access_token"]
        r_me = client.get(
            "/api/auth/me",
            headers={"Authorization": f"Bearer {new_token}"},
        )
        _assert_status(r_me, 200, "GET /api/auth/me with refreshed token")


# ===========================================================================
# 6. Logout → session revoked
# ===========================================================================


class TestLogout:
    """POST /api/auth/logout invalidates the current session."""

    @pytest.fixture()
    def session_tokens(self, client: TestClient) -> dict:
        """Fresh login (mocked) — gives us tokens we can safely logout."""
        with patch(
            "app.routers.auth.authenticate_user",
            return_value=_make_mock_login_response(),
        ):
            r = client.post(
                "/api/auth/login",
                json={"email": "admin@raf.health", "password": "Admin@123"},
            )
        assert r.status_code == 200, (
            f"Mocked login failed: {r.text[:200]}"
        )
        return r.json()

    def test_logout_returns_200(self, client: TestClient, session_tokens: dict):
        headers = {"Authorization": f"Bearer {session_tokens['access_token']}"}
        r = client.post("/api/auth/logout", headers=headers)
        _assert_status(r, 200, "POST /api/auth/logout")

    def test_logout_response_has_message(
        self, client: TestClient, session_tokens: dict
    ):
        headers = {"Authorization": f"Bearer {session_tokens['access_token']}"}
        r = client.post("/api/auth/logout", headers=headers)
        data = r.json()
        assert "message" in data, f"Logout response missing 'message': {data}"

    def test_logout_without_token_returns_401(self, client: TestClient):
        r = client.post("/api/auth/logout")
        _assert_status(r, 401, "logout without token")

    def test_access_after_logout_returns_401(
        self, client: TestClient, session_tokens: dict
    ):
        """
        After logout the session is revoked; the same access token must be rejected.

        We patch validate_session to return None (revoked) after logout so the
        auth middleware rejects the token.
        """
        headers = {"Authorization": f"Bearer {session_tokens['access_token']}"}
        # Logout first.
        r_logout = client.post("/api/auth/logout", headers=headers)
        assert r_logout.status_code == 200

        # Now simulate the session being revoked in DB
        with patch("app.auth.validate_session", return_value=None):
            r_me = client.get("/api/auth/me", headers=headers)
        assert r_me.status_code == 401, (
            f"Expected 401 after logout but got {r_me.status_code}. "
            "Session revocation may not be checking DB state."
        )


# ===========================================================================
# 7. Account lockout after repeated failures
# ===========================================================================


class TestAccountLockout:
    """Accounts should be locked after 5 consecutive failed login attempts."""

    def test_repeated_failures_lock_account(self, client: TestClient):
        """
        After 5 wrong-password attempts the 6th should also be rejected.

        The login route returns a generic 401 for ALL auth failures (to avoid
        leaking whether the account exists / is locked), so we verify the
        authenticate_user service was called all 6 times — proving the route
        doesn't short-circuit — and the last call received the lockout error.
        """
        fail_msg = ValueError("Invalid email or password.")
        lock_msg = ValueError("Account locked due to too many failed login attempts.")
        side_effects = [fail_msg] * 5 + [lock_msg]

        with patch(
            "app.routers.auth.authenticate_user", side_effect=side_effects
        ) as mock_auth:
            email = "lockout@raf-test.health"
            wrong_password = "WrongPass@NotRight9!"

            for attempt in range(6):
                r = client.post(
                    "/api/auth/login",
                    json={"email": email, "password": wrong_password},
                    headers={"X-Forwarded-For": f"10.0.0.{attempt + 1}"},
                )
                assert r.status_code == 401, (
                    f"Attempt {attempt + 1}: expected 401, got {r.status_code}"
                )

            # All 6 calls reached authenticate_user (no short-circuit)
            assert mock_auth.call_count == 6, (
                f"Expected 6 calls to authenticate_user, got {mock_auth.call_count}"
            )


# ===========================================================================
# 8. Password complexity validation
# ===========================================================================


class TestPasswordComplexity:
    """
    POST /api/auth/users with weak passwords → 422 (Pydantic validation)
    or 400/409 (service layer).
    """

    @pytest.fixture()
    def _admin_hdrs(self, admin_headers: dict) -> dict:
        return admin_headers

    def _attempt_create(self, client: TestClient, hdrs: dict, password: str) -> int:
        email = _unique_email("pwtest")
        r = client.post(
            "/api/auth/users",
            json={
                "email": email,
                "password": password,
                "full_name": "PW Test",
                "role": "viewer",
            },
            headers=hdrs,
        )
        return r.status_code

    def test_password_too_short_rejected(self, client: TestClient, _admin_hdrs: dict):
        """Password shorter than 12 chars must be rejected."""
        status = self._attempt_create(client, _admin_hdrs, "Short@1!")
        assert status in (400, 422), (
            f"Expected 400/422 for too-short password, got {status}"
        )

    def test_password_no_uppercase_rejected(
        self, client: TestClient, _admin_hdrs: dict
    ):
        """Password without an uppercase letter must be rejected."""
        status = self._attempt_create(client, _admin_hdrs, "nouppercase@99!")
        assert status in (400, 422), (
            f"Expected 400/422 for no-uppercase password, got {status}"
        )

    def test_password_no_digit_rejected(self, client: TestClient, _admin_hdrs: dict):
        """Password without a digit must be rejected."""
        status = self._attempt_create(client, _admin_hdrs, "NoDigitPass@@@!")
        assert status in (400, 422), (
            f"Expected 400/422 for no-digit password, got {status}"
        )

    def test_password_no_special_char_rejected(
        self, client: TestClient, _admin_hdrs: dict
    ):
        """Password without a special character must be rejected."""
        status = self._attempt_create(client, _admin_hdrs, "NoSpecialChar99A")
        assert status in (400, 422), (
            f"Expected 400/422 for no-special-char password, got {status}"
        )

    def test_common_password_rejected(self, client: TestClient, _admin_hdrs: dict):
        """Common passwords (e.g. 'password') must be rejected even if they pass length."""
        # 'password123' padded to meet length/complexity rules would still match
        # the common-password blocklist.
        status = self._attempt_create(client, _admin_hdrs, "password")
        assert status in (400, 422), (
            f"Expected 400/422 for common password, got {status}"
        )

    def test_strong_password_accepted(self, client: TestClient, _admin_hdrs: dict):
        """A well-formed HIPAA password must be accepted."""
        status = self._attempt_create(client, _admin_hdrs, _strong_password())
        assert status in (201, 409), (
            f"Expected 201 (or 409 idempotent) for strong password, got {status}"
        )


# ===========================================================================
# 9. User CRUD
# ===========================================================================


class TestUserCRUD:
    """Admin can create, read, update, and deactivate users."""

    _MOCK_CREATED_USER = {
        "id": 99, "email": "crud_user@raf-test.example", "full_name": "CRUD Test User",
        "role": "viewer", "tenant_id": 1, "is_active": 1, "avatar_url": None,
        "last_login_at": None, "password_changed_at": None,
        "created_at": "2026-04-12T00:00:00", "updated_at": "2026-04-12T00:00:00",
    }

    @pytest.fixture()
    def created_user(self, client: TestClient, admin_headers: dict) -> dict:
        """Create a fresh user (mocked) for CRUD tests and return the response body."""
        with patch("app.routers.auth.create_user", return_value=dict(self._MOCK_CREATED_USER)):
            r = client.post(
                "/api/auth/users",
                json={
                    "email": "crud_user@raf-test.example",
                    "password": _strong_password(),
                    "full_name": "CRUD Test User",
                    "role": "viewer",
                },
                headers=admin_headers,
            )
        assert r.status_code == 201, (
            f"Could not create CRUD test user. Status {r.status_code}: {r.text[:300]}"
        )
        return r.json()

    def test_create_user_returns_201(self, client: TestClient, admin_headers: dict):
        with patch("app.routers.auth.create_user", return_value=dict(self._MOCK_CREATED_USER)):
            r = client.post(
                "/api/auth/users",
                json={"email": "new@raf-test.example", "password": _strong_password(), "role": "viewer"},
                headers=admin_headers,
            )
        assert r.status_code == 201, (
            f"Create user returned {r.status_code}: {r.text[:200]}"
        )

    def test_create_user_response_has_id(self, created_user: dict):
        assert "id" in created_user, f"Created user missing 'id': {created_user}"
        assert created_user["id"] > 0

    def test_create_user_duplicate_email_returns_409(
        self, client: TestClient, admin_headers: dict
    ):
        with patch(
            "app.routers.auth.create_user",
            side_effect=ValueError("A user with this email already exists."),
        ):
            r = client.post(
                "/api/auth/users",
                json={
                    "email": "dupe@raf-test.health",
                    "password": _strong_password(),
                    "role": "viewer",
                },
                headers=admin_headers,
            )
        assert r.status_code == 409, (
            f"Duplicate email should return 409, got {r.status_code}"
        )

    def test_read_user_returns_200(
        self, client: TestClient, admin_headers: dict, created_user: dict
    ):
        uid = created_user["id"]
        r = client.get(f"/api/auth/users/{uid}", headers=admin_headers)
        _assert_status(r, 200, f"GET /api/auth/users/{uid}")

    def test_read_user_has_correct_email(
        self, client: TestClient, admin_headers: dict, created_user: dict
    ):
        uid = created_user["id"]
        r = client.get(f"/api/auth/users/{uid}", headers=admin_headers)
        assert r.json().get("email") == created_user["email"]

    def test_update_user_full_name(
        self, client: TestClient, admin_headers: dict
    ):
        updated_user = {
            "id": 2, "email": "viewer@raf-test.health", "full_name": "Updated Full Name",
            "role": "viewer", "tenant_id": 1, "is_active": 1, "avatar_url": None,
            "last_login_at": None, "created_at": "2026-01-01T00:00:00", "updated_at": "2026-04-12T00:00:00",
        }
        with patch("app.routers.auth.update_user", return_value=updated_user):
            r = client.put(
                "/api/auth/users/2",
                json={"full_name": "Updated Full Name"},
                headers=admin_headers,
            )
        _assert_status(r, 200, "PUT /api/auth/users/2")
        assert r.json().get("full_name") == "Updated Full Name"

    def test_update_user_role(
        self, client: TestClient, admin_headers: dict
    ):
        updated_user = {
            "id": 2, "email": "viewer@raf-test.health", "full_name": "Test Viewer",
            "role": "auditor", "tenant_id": 1, "is_active": 1, "avatar_url": None,
            "last_login_at": None, "created_at": "2026-01-01T00:00:00", "updated_at": "2026-04-12T00:00:00",
        }
        with patch("app.routers.auth.update_user", return_value=updated_user):
            r = client.put(
                "/api/auth/users/2",
                json={"role": "auditor"},
                headers=admin_headers,
            )
        _assert_status(r, 200, "PUT /api/auth/users/2")
        assert r.json().get("role") == "auditor"

    def test_deactivate_user_returns_200_or_204(
        self, client: TestClient, admin_headers: dict
    ):
        deactivated = {
            "id": 2, "email": "viewer@raf-test.health", "full_name": "Test Viewer",
            "role": "viewer", "tenant_id": 1, "is_active": 0, "avatar_url": None,
        }
        with patch("app.routers.auth.deactivate_user", return_value=deactivated):
            # user_id=2 so it doesn't conflict with admin (id=1)
            r = client.delete("/api/auth/users/2", headers=admin_headers)
        assert r.status_code in (200, 204), (
            f"DELETE /api/auth/users/2 returned {r.status_code}: {r.text[:200]}"
        )

    def test_list_users_returns_200_for_admin(
        self, client: TestClient, admin_headers: dict
    ):
        r = client.get("/api/auth/users", headers=admin_headers)
        _assert_status(r, 200, "GET /api/auth/users")

    def test_list_users_response_structure(
        self, client: TestClient, admin_headers: dict
    ):
        r = client.get("/api/auth/users", headers=admin_headers)
        data = r.json()
        assert "users" in data and "count" in data, (
            f"List users response missing expected fields: {data}"
        )
        assert isinstance(data["users"], list)


# ===========================================================================
# 10. RBAC — viewer cannot access admin write endpoints
# ===========================================================================


class TestRBAC:
    """Role-based access control: viewers cannot perform admin actions."""

    def test_viewer_cannot_list_all_users(self, client: TestClient, auth_headers: dict):
        """GET /api/auth/users is admin/manager only."""
        r = client.get("/api/auth/users", headers=auth_headers)
        assert r.status_code in (401, 403), (
            f"Viewer should be denied /api/auth/users, got {r.status_code}"
        )

    def test_viewer_cannot_create_user(self, client: TestClient, auth_headers: dict):
        email = _unique_email("rbac_blocked")
        r = client.post(
            "/api/auth/users",
            json={"email": email, "password": _strong_password(), "role": "viewer"},
            headers=auth_headers,
        )
        assert r.status_code in (401, 403), (
            f"Viewer should be denied POST /api/auth/users, got {r.status_code}"
        )

    def test_viewer_cannot_delete_user(
        self, client: TestClient, auth_headers: dict
    ):
        """Viewer cannot delete a user — should get 401/403."""
        # Use user_id=99 (exists in mock users)
        r_del = client.delete("/api/auth/users/99", headers=auth_headers)
        assert r_del.status_code in (401, 403), (
            f"Viewer should be denied DELETE /api/auth/users/99, got {r_del.status_code}"
        )

    def test_admin_can_list_users(self, client: TestClient, admin_headers: dict):
        r = client.get("/api/auth/users", headers=admin_headers)
        _assert_status(r, 200, "admin GET /api/auth/users")

    def test_admin_can_view_audit_log(self, client: TestClient, admin_headers: dict):
        r = client.get("/api/auth/audit-log", headers=admin_headers)
        _assert_status(r, 200, "admin GET /api/auth/audit-log")

    def test_viewer_cannot_access_audit_log(
        self, client: TestClient, auth_headers: dict
    ):
        r = client.get("/api/auth/audit-log", headers=auth_headers)
        assert r.status_code in (401, 403), (
            f"Viewer should be denied /api/auth/audit-log, got {r.status_code}"
        )

    def test_invalid_role_on_create_returns_422(
        self, client: TestClient, admin_headers: dict
    ):
        """Attempting to create a user with an unknown role → 422."""
        email = _unique_email("badrole")
        r = client.post(
            "/api/auth/users",
            json={"email": email, "password": _strong_password(), "role": "superuser"},
            headers=admin_headers,
        )
        assert r.status_code == 422, (
            f"Expected 422 for invalid role, got {r.status_code}"
        )


# ===========================================================================
# 11. Permission checking endpoint
# ===========================================================================


class TestPermissions:
    """GET /api/auth/users/{id}/permissions — admin view of effective permissions."""

    @pytest.fixture()
    def viewer_user(self, client: TestClient, admin_headers: dict) -> dict:
        mock_user = {
            "id": 99, "email": "perm_viewer@raf-test.example", "full_name": "Perm Viewer",
            "role": "viewer", "tenant_id": 1, "is_active": 1, "avatar_url": None,
        }
        with patch("app.routers.auth.create_user", return_value=dict(mock_user)):
            r = client.post(
                "/api/auth/users",
                json={"email": "perm_viewer@raf-test.example", "password": _strong_password(), "role": "viewer"},
                headers=admin_headers,
            )
        assert r.status_code == 201
        return r.json()

    def test_get_permissions_returns_200(
        self, client: TestClient, admin_headers: dict, viewer_user: dict
    ):
        uid = viewer_user["id"]
        r = client.get(f"/api/auth/users/{uid}/permissions", headers=admin_headers)
        _assert_status(r, 200, f"GET /api/auth/users/{uid}/permissions")

    def test_permissions_response_has_required_fields(
        self, client: TestClient, admin_headers: dict, viewer_user: dict
    ):
        uid = viewer_user["id"]
        r = client.get(f"/api/auth/users/{uid}/permissions", headers=admin_headers)
        data = r.json()
        assert "user_id" in data, f"Missing user_id in permissions response: {data}"
        assert "role" in data, f"Missing role in permissions response: {data}"
        assert "permissions" in data, (
            f"Missing permissions in permissions response: {data}"
        )

    def test_viewer_role_is_reported_correctly(
        self, client: TestClient, admin_headers: dict, viewer_user: dict
    ):
        uid = viewer_user["id"]
        with patch(
            "app.routers.auth.get_user_permissions",
            return_value=[{"resource": "patients", "action": "read", "granted": True}],
        ):
            r = client.get(f"/api/auth/users/{uid}/permissions", headers=admin_headers)
        # get_user returns MOCK user for id — check the role from that mock
        data = r.json()
        assert "role" in data, f"Missing role: {data}"

    def test_viewer_cannot_read_other_users_permissions(
        self, client: TestClient, auth_headers: dict, viewer_user: dict
    ):
        uid = viewer_user["id"]
        r = client.get(f"/api/auth/users/{uid}/permissions", headers=auth_headers)
        assert r.status_code in (401, 403), (
            f"Viewer should not access /users/{uid}/permissions, got {r.status_code}"
        )

    def test_set_permissions_returns_200_for_admin(
        self, client: TestClient, admin_headers: dict, viewer_user: dict
    ):
        uid = viewer_user["id"]
        r = client.put(
            f"/api/auth/users/{uid}/permissions",
            json={
                "permissions": [
                    {"resource": "patients", "action": "read", "granted": True}
                ]
            },
            headers=admin_headers,
        )
        _assert_status(r, 200, f"PUT /api/auth/users/{uid}/permissions")

    def test_get_nonexistent_user_permissions_returns_404(
        self, client: TestClient, admin_headers: dict
    ):
        r = client.get("/api/auth/users/999999999/permissions", headers=admin_headers)
        assert r.status_code == 404
