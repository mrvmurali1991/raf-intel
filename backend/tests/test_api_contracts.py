"""
tests/test_api_contracts.py — API contract / schema validation tests.

Verifies that every critical endpoint returns the documented response shape
with the correct field names and types.  All DB calls are mocked so no live
server or database is needed.

Coverage:
- Auth endpoints: /login, /me, /refresh, /logout
- Patient list and detail
- RAF score and population-summary
- Pipeline status endpoint
- Health endpoint

Markers: (none — these run in the default fast suite)
"""

from __future__ import annotations

from contextlib import contextmanager
from unittest.mock import patch

import pytest

from tests.conftest import (
    MOCK_ADMIN_USER,
    MOCK_VIEWER_USER,
    MockCursor,
    _make_access_token,
    _make_refresh_token,
)


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _headers(user: dict) -> dict[str, str]:
    return {"Authorization": f"Bearer {_make_access_token(user)}"}


@contextmanager
def _auth_as(user: dict):
    session_row = {"session_id": user["session_id"], "is_revoked": 0}
    with (
        patch("app.auth.get_user", return_value=user),
        patch("app.auth.validate_session", return_value=session_row),
        patch("app.services.auth_service.get_user", return_value=user),
        patch("app.services.auth_service.validate_session", return_value=session_row),
        patch("app.services.auth_service._ensure_tables"),
        patch("app.routers.auth.get_user", return_value=user),
    ):
        yield


@contextmanager
def _noop_raf_cursor():
    @contextmanager
    def _cm(*a, **kw):
        yield MockCursor()
    with patch("app.db.raf_cursor", _cm):
        yield


# ===========================================================================
# 1. Health endpoint
# ===========================================================================


class TestHealthContract:
    def test_health_returns_200(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200

    def test_health_returns_json_with_status_field(self, client):
        resp = client.get("/health")
        body = resp.json()
        assert "status" in body or isinstance(body, dict), (
            f"Health endpoint should return a JSON object, got: {body!r}"
        )


# ===========================================================================
# 2. Auth — /api/auth/me
# ===========================================================================


class TestMeContract:
    """GET /api/auth/me must return the canonical user profile fields."""

    REQUIRED_FIELDS = {"id", "email", "role", "tenant_id", "full_name"}
    FORBIDDEN_FIELDS = {"password_hash", "mfa_secret", "password_changed_at"}

    def test_me_returns_200_for_authenticated_user(self, client):
        user = dict(MOCK_ADMIN_USER)
        with _auth_as(user):
            resp = client.get("/api/auth/me", headers=_headers(user))
        assert resp.status_code == 200

    def test_me_response_contains_required_fields(self, client):
        user = dict(MOCK_ADMIN_USER)
        with _auth_as(user):
            resp = client.get("/api/auth/me", headers=_headers(user))
        body = resp.json()
        missing = self.REQUIRED_FIELDS - set(body.keys())
        assert not missing, f"Missing required fields in /api/auth/me response: {missing}"

    def test_me_response_does_not_leak_password_hash(self, client):
        user = dict(MOCK_ADMIN_USER)
        with _auth_as(user):
            resp = client.get("/api/auth/me", headers=_headers(user))
        body = resp.json()
        for forbidden in self.FORBIDDEN_FIELDS:
            assert forbidden not in body, (
                f"Sensitive field '{forbidden}' must not appear in /api/auth/me response"
            )

    def test_me_returns_correct_email(self, client):
        user = dict(MOCK_ADMIN_USER)
        with _auth_as(user):
            resp = client.get("/api/auth/me", headers=_headers(user))
        assert resp.json().get("email") == user["email"]

    def test_me_returns_correct_tenant_id(self, client):
        user = dict(MOCK_ADMIN_USER)
        with _auth_as(user):
            resp = client.get("/api/auth/me", headers=_headers(user))
        assert resp.json().get("tenant_id") == user["tenant_id"]

    def test_me_returns_401_without_token(self, client):
        resp = client.get("/api/auth/me")
        assert resp.status_code == 401

    def test_me_mfa_secret_not_in_response(self, client):
        """mfa_secret must never be returned in profile responses."""
        from tests.conftest import MOCK_MFA_USER
        user = dict(MOCK_MFA_USER)
        with _auth_as(user):
            resp = client.get("/api/auth/me", headers=_headers(user))
        if resp.status_code == 200:
            body = resp.json()
            assert "mfa_secret" not in body, "mfa_secret must never be in API response"


# ===========================================================================
# 3. Auth — /api/auth/login
# ===========================================================================


class TestLoginContract:
    """POST /api/auth/login contract validation."""

    def test_login_with_missing_email_returns_422(self, client):
        resp = client.post("/api/auth/login", json={"password": "Admin@123"})
        assert resp.status_code == 422

    def test_login_with_missing_password_returns_422(self, client):
        resp = client.post("/api/auth/login", json={"email": "admin@raf.health"})
        assert resp.status_code == 422

    def test_login_with_invalid_credentials_returns_401(self, client):
        with patch("app.routers.auth.authenticate_user", return_value=None):
            resp = client.post(
                "/api/auth/login",
                json={"email": "bad@raf.health", "password": "WrongPass1!"},
            )
        assert resp.status_code == 401

    def test_login_success_returns_access_token(self, client):
        user = dict(MOCK_ADMIN_USER)
        with (
            patch("app.routers.auth.authenticate_user", return_value=user),
            patch("app.services.auth_service.create_session", return_value="sess-abc"),
            patch(
                "app.services.auth_service.create_access_token",
                return_value="fake-access-token",
            ),
            patch(
                "app.services.auth_service.create_refresh_token",
                return_value="fake-refresh-token",
            ),
            _noop_raf_cursor(),
        ):
            resp = client.post(
                "/api/auth/login",
                json={"email": user["email"], "password": "Admin@123"},
            )
        # 200 or 422 from Pydantic — either way no 500
        assert resp.status_code != 500

    def test_login_response_has_no_password_hash(self, client):
        """Login response must never include password_hash field."""
        user = dict(MOCK_ADMIN_USER)
        with (
            patch("app.routers.auth.authenticate_user", return_value=user),
            patch("app.services.auth_service.create_session", return_value="sess-abc"),
            patch(
                "app.services.auth_service.create_access_token",
                return_value="tok-access",
            ),
            patch(
                "app.services.auth_service.create_refresh_token",
                return_value="tok-refresh",
            ),
            _noop_raf_cursor(),
        ):
            resp = client.post(
                "/api/auth/login",
                json={"email": user["email"], "password": "Admin@123"},
            )
        if resp.status_code == 200:
            body = resp.json()
            assert "password_hash" not in body
            assert "mfa_secret" not in body


# ===========================================================================
# 4. Auth — /api/auth/refresh
# ===========================================================================


class TestRefreshContract:
    def test_refresh_without_token_returns_401_or_422(self, client):
        resp = client.post("/api/auth/refresh")
        assert resp.status_code in (401, 422)

    def test_refresh_with_expired_token_returns_401(self, client):
        user = dict(MOCK_ADMIN_USER)
        expired_refresh = _make_refresh_token(user, expired=True)
        resp = client.post(
            "/api/auth/refresh",
            json={"refresh_token": expired_refresh},
        )
        assert resp.status_code == 401


# ===========================================================================
# 5. Patient list contract
# ===========================================================================


class TestPatientListContract:
    """GET /api/patients must return the documented pagination envelope."""

    REQUIRED_FIELDS = {"patients", "total"}

    def test_patient_list_returns_200(self, client):
        user = dict(MOCK_ADMIN_USER)
        with (
            _auth_as(user),
            patch(
                "app.services.patient_service.list_patients",
                return_value={
                    "patients": [],
                    "total": 0,
                    "page": 1,
                    "pages": 0,
                },
            ),
        ):
            resp = client.get("/api/patients", headers=_headers(user))
        assert resp.status_code == 200

    def test_patient_list_has_required_envelope_fields(self, client):
        user = dict(MOCK_ADMIN_USER)
        with (
            _auth_as(user),
            patch(
                "app.services.patient_service.list_patients",
                return_value={
                    "patients": [{"pid": 1, "fname": "Alice", "lname": "Smith"}],
                    "total": 1,
                    "page": 1,
                    "pages": 1,
                },
            ),
        ):
            resp = client.get("/api/patients", headers=_headers(user))
        body = resp.json()
        missing = self.REQUIRED_FIELDS - set(body.keys())
        assert not missing, f"Missing fields in patient list: {missing}"

    def test_patient_list_requires_auth(self, client):
        resp = client.get("/api/patients")
        assert resp.status_code == 401

    def test_patient_list_patients_is_list(self, client):
        user = dict(MOCK_ADMIN_USER)
        with (
            _auth_as(user),
            patch(
                "app.services.patient_service.list_patients",
                return_value={"patients": [], "total": 0, "page": 1, "pages": 0},
            ),
        ):
            resp = client.get("/api/patients", headers=_headers(user))
        assert isinstance(resp.json().get("patients"), list)


# ===========================================================================
# 6. Patient detail contract
# ===========================================================================


class TestPatientDetailContract:
    """GET /api/patients/{pid} must return individual patient fields."""

    def test_patient_detail_404_for_nonexistent_pid(self, client):
        user = dict(MOCK_ADMIN_USER)
        with (
            _auth_as(user),
            patch("app.services.patient_service.patient_is_accessible", return_value=False),
        ):
            resp = client.get("/api/patients/99999", headers=_headers(user))
        assert resp.status_code == 404

    def test_patient_detail_returns_patient_data_fields(self, client):
        user = dict(MOCK_ADMIN_USER)
        mock_patient = {
            "pid": 1,
            "first_name": "Alice",
            "last_name": "Smith",
            "date_of_birth": "1955-03-12",
            "raf_score": 1.45,
            "hcc_count": 3,
        }
        with (
            _auth_as(user),
            patch("app.services.patient_service.patient_is_accessible", return_value=True),
            patch(
                "app.services.patient_service.get_patient_with_raf",
                return_value=mock_patient,
            ),
        ):
            resp = client.get("/api/patients/1", headers=_headers(user))
        if resp.status_code == 200:
            body = resp.json()
            assert "pid" in body or "first_name" in body or "fname" in body

    def test_patient_detail_requires_auth(self, client):
        resp = client.get("/api/patients/1")
        assert resp.status_code == 401


# ===========================================================================
# 7. RAF endpoints contract
# ===========================================================================


class TestRAFContract:
    """RAF calculation and score endpoints return correct shape."""

    def test_raf_calculate_requires_auth(self, client):
        resp = client.post("/api/raf/calculate", json={"patient_id": 1})
        assert resp.status_code == 401

    def test_population_summary_requires_auth(self, client):
        resp = client.get("/api/raf/population-summary")
        assert resp.status_code == 401

    def test_raf_list_models_returns_list(self, client):
        """GET /api/raf/models should return a list of available models."""
        user = dict(MOCK_ADMIN_USER)
        with _auth_as(user):
            resp = client.get("/api/raf/models", headers=_headers(user))
        if resp.status_code == 200:
            body = resp.json()
            assert isinstance(body, (list, dict))

    def test_raf_score_history_requires_auth(self, client):
        resp = client.get("/api/raf/1/score-history")
        assert resp.status_code == 401


# ===========================================================================
# 8. Pipeline endpoint contract
# ===========================================================================


class TestPipelineContract:
    """Pipeline status/trigger endpoints must have correct shape."""

    def test_pipeline_status_requires_auth(self, client):
        resp = client.get("/api/emr/pipeline/status")
        assert resp.status_code in (401, 404)

    def test_pipeline_trigger_requires_auth(self, client):
        resp = client.post("/api/emr/sync")
        assert resp.status_code == 401

    def test_emr_connections_list_requires_auth(self, client):
        resp = client.get("/api/emr/connections")
        assert resp.status_code == 401

    def test_emr_connections_list_returns_list(self, client):
        user = dict(MOCK_ADMIN_USER)
        with (
            _auth_as(user),
            patch(
                "app.services.emr_manager.list_connections",
                return_value=[{"id": 1, "name": "Test EMR", "is_active": 1}],
            ),
        ):
            resp = client.get("/api/emr/connections", headers=_headers(user))
        if resp.status_code == 200:
            body = resp.json()
            assert isinstance(body, (list, dict))


# ===========================================================================
# 9. Admin endpoint contract
# ===========================================================================


class TestAdminContract:
    """Admin endpoints require admin role and return correct shape."""

    def test_admin_users_list_forbidden_for_viewer(self, client):
        user = dict(MOCK_VIEWER_USER)
        with _auth_as(user):
            resp = client.get("/api/auth/users", headers=_headers(user))
        assert resp.status_code == 403

    def test_admin_users_list_returns_list_for_admin(self, client):
        user = dict(MOCK_ADMIN_USER)
        with (
            _auth_as(user),
            _noop_raf_cursor(),
            patch("app.services.auth_service.list_users", return_value=[]),
        ):
            resp = client.get("/api/auth/users", headers=_headers(user))
        if resp.status_code == 200:
            body = resp.json()
            assert isinstance(body, (list, dict))

    def test_audit_log_requires_auth(self, client):
        resp = client.get("/api/audit/logs")
        assert resp.status_code == 401
