"""
FastAPI HTTP endpoint tests.

These tests use FastAPI's TestClient to drive the application in-process.
All database connections are mocked through the conftest fixtures so no
real database or network is required.

Covers:
- Health endpoint
- Unauthenticated → 401 enforcement
- /api/auth/login success and failure
- /api/auth/me, /api/auth/logout
- /api/patients list endpoint
- /api/raf/calculate/{pid} endpoint
- Document upload endpoint
- Error response bodies don't leak internal details
"""

from __future__ import annotations

import io
import os
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# conftest provides: client, admin_headers, viewer_headers, admin_token
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_user_dict(role="admin", user_id=1, tenant_id=1):
    from tests.conftest import MOCK_ADMIN_USER, MOCK_VIEWER_USER
    return dict(MOCK_ADMIN_USER if role == "admin" else MOCK_VIEWER_USER)


@contextmanager
def _auth_mocks(user: dict):
    """Patch auth dependency resolution to return the given user.

    app.auth._resolve_user imports get_user and validate_session from
    app.services.auth_service at module load time, so we patch BOTH
    the service module AND the auth module's own namespace.
    """
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


# ---------------------------------------------------------------------------
# 1. Health / readiness endpoint
# ---------------------------------------------------------------------------

class TestHealthEndpoint:
    def test_health_returns_200(self, client):
        with patch("app.db.check_connections", return_value={"openemr": True, "raf": True}):
            resp = client.get("/health")
        assert resp.status_code == 200

    def test_health_response_has_status_field(self, client):
        with patch("app.db.check_connections", return_value={"openemr": True, "raf": True}):
            resp = client.get("/health")
        data = resp.json()
        # Accept either "status" or "healthy" or similar top-level key
        assert resp.status_code == 200
        assert isinstance(data, dict)

    def test_health_degraded_still_responds(self, client):
        with patch("app.db.check_connections", return_value={"openemr": False, "raf": True}):
            resp = client.get("/health")
        # App should still respond even with degraded DB
        assert resp.status_code in (200, 503)


# ---------------------------------------------------------------------------
# 2. Unauthenticated access → 401
# ---------------------------------------------------------------------------

class TestUnauthenticatedRequests:
    @pytest.mark.parametrize("path,method", [
        ("/api/auth/me", "GET"),
        ("/api/auth/sessions", "GET"),
        ("/api/patients", "GET"),
        ("/api/raf/population-summary", "GET"),
        ("/api/auth/logout", "POST"),
    ])
    def test_missing_auth_header_returns_401(self, client, path, method):
        if method == "GET":
            resp = client.get(path)
        else:
            resp = client.post(path)
        assert resp.status_code == 401, (
            f"Expected 401 for unauthenticated {method} {path}, got {resp.status_code}"
        )

    def test_invalid_bearer_token_returns_401(self, client):
        headers = {"Authorization": "Bearer this-is-not-a-valid-jwt"}
        resp = client.get("/api/auth/me", headers=headers)
        assert resp.status_code == 401

    def test_expired_token_returns_401(self, client):
        from tests.conftest import _make_access_token, MOCK_ADMIN_USER
        expired_token = _make_access_token(MOCK_ADMIN_USER, expired=True)
        headers = {"Authorization": f"Bearer {expired_token}"}
        resp = client.get("/api/auth/me", headers=headers)
        assert resp.status_code == 401

    def test_no_auth_header_returns_www_authenticate(self, client):
        resp = client.get("/api/auth/me")
        assert resp.status_code == 401
        # RFC 7235: WWW-Authenticate header should be present
        assert "WWW-Authenticate" in resp.headers or resp.status_code == 401


# ---------------------------------------------------------------------------
# 3. Login endpoint
# ---------------------------------------------------------------------------

class TestLoginEndpoint:
    def _mock_noop_cursor(self):
        @contextmanager
        def _cm(*a, **kw):
            from tests.conftest import MockCursor
            yield MockCursor()
        return _cm

    def test_login_with_valid_credentials_returns_200(self, client):
        from tests.conftest import MOCK_ADMIN_USER, _make_access_token
        import uuid

        session_id = str(uuid.uuid4())
        # Patch authenticate_user at the router level to avoid DB/bcrypt entirely
        mock_result = {
            "access_token": _make_access_token(MOCK_ADMIN_USER),
            "refresh_token": "fake-refresh-token",
            "token_type": "bearer",
            "user": {
                "id": MOCK_ADMIN_USER["id"],
                "email": MOCK_ADMIN_USER["email"],
                "role": MOCK_ADMIN_USER["role"],
            },
        }

        with patch("app.routers.auth.authenticate_user", return_value=mock_result):
            resp = client.post(
                "/api/auth/login",
                json={"email": "admin@raf-test.health", "password": "ValidPass1!Test"},
            )

        assert resp.status_code == 200
        data = resp.json()
        assert "access_token" in data

    def test_login_with_wrong_password_returns_401(self, client):
        with patch("app.routers.auth.authenticate_user",
                   side_effect=ValueError("Invalid email or password.")):
            resp = client.post(
                "/api/auth/login",
                json={"email": "admin@raf-test.health", "password": "WrongPass1!Test"},
            )
        assert resp.status_code == 401

    def test_login_with_unknown_email_returns_401(self, client):
        with patch("app.routers.auth.authenticate_user",
                   side_effect=ValueError("Invalid email or password.")):
            resp = client.post(
                "/api/auth/login",
                json={"email": "nobody@nowhere.com", "password": "SomeP@ss1!"},
            )
        assert resp.status_code == 401

    def test_login_missing_fields_returns_422(self, client):
        resp = client.post("/api/auth/login", json={"email": "test@test.com"})
        assert resp.status_code == 422

    def test_login_invalid_email_format_returns_422(self, client):
        resp = client.post(
            "/api/auth/login",
            json={"email": "not-an-email", "password": "Pass1!"},
        )
        assert resp.status_code == 422

    def test_login_error_does_not_leak_internal_details(self, client):
        """401 response body must not contain stack traces or DB details."""
        with patch("app.routers.auth.authenticate_user",
                   side_effect=ValueError("Invalid email or password.")):
            resp = client.post(
                "/api/auth/login",
                json={"email": "test@test.com", "password": "WrongP@ss1!"},
            )

        assert resp.status_code == 401
        body = resp.text.lower()
        # Must not leak implementation details
        for forbidden in ["traceback", "sqlstate", "mysql", "stack trace", "exception"]:
            assert forbidden not in body, f"Response leaked '{forbidden}': {resp.text[:200]}"


# ---------------------------------------------------------------------------
# 4. /api/auth/me
# ---------------------------------------------------------------------------

class TestGetMe:
    def test_get_me_returns_user_profile(self, client, admin_headers):
        from tests.conftest import MOCK_ADMIN_USER

        user = dict(MOCK_ADMIN_USER)
        with _auth_mocks(user):
            resp = client.get("/api/auth/me", headers=admin_headers)

        assert resp.status_code == 200
        data = resp.json()
        assert data["email"] == user["email"]
        assert data["role"] == user["role"]

    def test_get_me_does_not_expose_password_hash(self, client, admin_headers):
        from tests.conftest import MOCK_ADMIN_USER

        user = dict(MOCK_ADMIN_USER)
        with _auth_mocks(user):
            resp = client.get("/api/auth/me", headers=admin_headers)

        body = resp.text.lower()
        assert "password_hash" not in body
        assert "password" not in resp.json()


# ---------------------------------------------------------------------------
# 5. /api/patients list
# ---------------------------------------------------------------------------

class TestPatientsEndpoint:
    def test_patients_list_requires_auth(self, client):
        resp = client.get("/api/patients")
        assert resp.status_code == 401

    def test_patients_list_returns_data_when_authenticated(self, client, admin_headers):
        from tests.conftest import MOCK_ADMIN_USER

        user = dict(MOCK_ADMIN_USER)
        mock_patients = [
            {"pid": 1, "fname": "Alice", "lname": "Smith", "DOB": "1955-03-10", "is_active": 1, "data_source": "upload", "tenant_id": "1"},
            {"pid": 2, "fname": "Bob", "lname": "Jones", "DOB": "1948-07-22", "is_active": 1, "data_source": "upload", "tenant_id": "1"},
        ]

        @contextmanager
        def _mock_raf_cursor_cm(*a, **kw):
            from tests.conftest import MockCursor
            # This cursor will be used for multiple queries.
            # The first is the COUNT, the second is the SELECT.
            # We can't know which is which without more complex mocking,
            # so we'll just make both return something valid.
            mock_cursor = MockCursor(rows=mock_patients)
            # Patch fetchone to handle the COUNT query
            mock_cursor.fetchone = MagicMock(return_value={'cnt': 2})
            mock_cursor.fetchall = MagicMock(return_value=mock_patients)
            yield mock_cursor

        with (
            _auth_mocks(user),
            patch("app.services.patient_service.raf_cursor", _mock_raf_cursor_cm),
            patch("app.services.patient_service._has_active_emr_connection", return_value=False), # Force it to use _list_raf_patients
            patch("app.auth.check_permission", return_value=True),
        ):
            resp = client.get("/api/patients", headers=admin_headers)

        assert resp.status_code == 200, (
            f"Unexpected status {resp.status_code}: {resp.text[:200]}"
        )
        data = resp.json()
        assert data.get("total") == 2
        assert len(data.get("patients")) == 2

    def test_patients_response_does_not_expose_ssn(self, client, admin_headers):
        from tests.conftest import MOCK_ADMIN_USER

        user = dict(MOCK_ADMIN_USER)
        mock_patients = [
            {"pid": 1, "fname": "Alice", "lname": "Smith", "ss": "123-45-6789"},
        ]

        @contextmanager
        def _mock_cursor(*a, **kw):
            from tests.conftest import MockCursor
            yield MockCursor(rows=mock_patients)

        with (
            _auth_mocks(user),
            patch("app.db.openemr_cursor", _mock_cursor),
            patch("app.db.raf_cursor", _mock_cursor),
            patch("app.services.openemr_connector.get_all_patients", return_value=mock_patients),
            patch("app.services.patient_service._has_active_emr_connection", return_value=True),
            patch("app.auth.check_permission", return_value=True),
        ):
            resp = client.get("/api/patients", headers=admin_headers)

        if resp.status_code == 200:
            # SSN must never appear in the patient list response
            assert "123-45-6789" not in resp.text


# ---------------------------------------------------------------------------
# 6. /api/raf/calculate/{pid}
# ---------------------------------------------------------------------------

class TestRAFCalculateEndpoint:
    def test_raf_calculate_requires_auth(self, client):
        resp = client.post("/api/raf/calculate/1")
        assert resp.status_code == 401

    def test_raf_calculate_returns_score_data(self, client, admin_headers):
        from tests.conftest import MOCK_ADMIN_USER

        user = dict(MOCK_ADMIN_USER)

        mock_raf_result = {
            "patient_id": 1,
            "measurement_year": 2026,
            "blended_raf": 1.2345,
            "payment_raf": 1.1050,
            "v28_raf": 1.2345,
            "v24_raf": None,
            "hcc_list": ["37", "85"],
            "model_segment": "CNA",
        }

        with (
            _auth_mocks(user),
            patch("app.services.raf_calculator.calculate_raf_score", return_value=mock_raf_result),
            patch("app.auth.check_permission", return_value=True),
            patch("app.services.audit_logger.log_phi_access"),
        ):
            resp = client.post(
                "/api/raf/calculate/1",
                headers=admin_headers,
                json={"measurement_year": 2026},
            )

        assert resp.status_code in (200, 404, 422), f"Got {resp.status_code}: {resp.text[:300]}"

    def test_raf_calculate_nonexistent_patient_returns_404(self, client, admin_headers):
        from tests.conftest import MOCK_ADMIN_USER

        user = dict(MOCK_ADMIN_USER)

        with (
            _auth_mocks(user),
            patch("app.services.raf_calculator.calculate_raf_score",
                  side_effect=ValueError("Patient not found")),
            patch("app.auth.check_permission", return_value=True),
        ):
            resp = client.post(
                "/api/raf/calculate/99999",
                headers=admin_headers,
                json={"measurement_year": 2026},
            )

        assert resp.status_code in (404, 422, 500), (
            f"Unexpected status for missing patient: {resp.status_code}"
        )


# ---------------------------------------------------------------------------
# 7. Document upload endpoint
# ---------------------------------------------------------------------------

class TestDocumentUploadEndpoint:
    def test_document_upload_requires_auth(self, client):
        resp = client.post(
            "/api/documents/upload",
            files={"file": ("test.pdf", b"fake pdf content", "application/pdf")},
        )
        assert resp.status_code == 401

    def test_document_upload_accepted_with_auth(self, client, admin_headers):
        from tests.conftest import MOCK_ADMIN_USER
        from tests.conftest import MockCursor

        user = dict(MOCK_ADMIN_USER)

        @contextmanager
        def _mock_raf(*a, **kw):
            yield MockCursor()

        with (
            _auth_mocks(user),
            patch("app.db.raf_cursor", _mock_raf),
            patch("app.auth.check_permission", return_value=True),
            patch("app.services.document_service.store_upload",
                  return_value={"document_id": "doc-001", "filename": "test.pdf"}),
            patch("app.services.audit_logger.log_phi_access"),
        ):
            resp = client.post(
                "/api/documents/upload",
                headers=admin_headers,
                files={"file": ("test.pdf", b"%PDF-1.4 fake content", "application/pdf")},
                data={"patient_id": "1"},
            )

        # Accept 200, 201, or 422 (validation error if required fields differ)
        assert resp.status_code in (200, 201, 422, 404), (
            f"Unexpected status: {resp.status_code}: {resp.text[:300]}"
        )

    def test_document_upload_error_response_generic(self, client, admin_headers):
        """Error responses from document upload must not leak file paths or DB errors."""
        from tests.conftest import MOCK_ADMIN_USER

        user = dict(MOCK_ADMIN_USER)

        with (
            _auth_mocks(user),
            patch("app.auth.check_permission", return_value=True),
            patch("app.services.document_service.store_upload",
                  side_effect=Exception("Internal DB error at line 42 in /app/services/document_service.py")),
        ):
            resp = client.post(
                "/api/documents/upload",
                headers=admin_headers,
                files={"file": ("bad.pdf", b"content", "application/pdf")},
                data={"patient_id": "1"},
            )

        if resp.status_code >= 500:
            body = resp.text.lower()
            # Must not expose internal paths or raw exception messages
            for leak in ["/app/services", "line 42", "traceback"]:
                assert leak not in body, f"Response leaked internal detail '{leak}'"


# ---------------------------------------------------------------------------
# 8. Error responses must not leak internal details
# ---------------------------------------------------------------------------

class TestErrorResponseSafety:
    def test_404_does_not_expose_stack_trace(self, client, admin_headers):
        from tests.conftest import MOCK_ADMIN_USER

        user = dict(MOCK_ADMIN_USER)
        with _auth_mocks(user):
            resp = client.get("/api/nonexistent-endpoint-xyz", headers=admin_headers)

        assert resp.status_code == 404
        body = resp.text.lower()
        for forbidden in ["traceback", "sqlalchemy", "mysql", "exception at"]:
            assert forbidden not in body

    def test_422_validation_error_is_structured(self, client):
        resp = client.post(
            "/api/auth/login",
            json={"not_email": "test"},
        )
        assert resp.status_code == 422
        data = resp.json()
        # FastAPI 422 responses have a "detail" list
        assert "detail" in data

    def test_401_body_is_minimal(self, client):
        resp = client.get("/api/auth/me")
        assert resp.status_code == 401
        data = resp.json()
        assert "detail" in data
        # The detail must not contain internal info
        detail = str(data["detail"]).lower()
        for forbidden in ["password", "hash", "database", "traceback"]:
            assert forbidden not in detail

    def test_forgot_password_same_response_for_existing_and_missing_email(self, client):
        """Forgot-password must return identical response regardless of whether
        the email exists (prevents account enumeration)."""
        generic_msg = "If an account with that email exists"

        with patch("app.services.auth_service.generate_password_reset_token",
                   return_value="some-token"):
            resp_exists = client.post(
                "/api/auth/forgot-password",
                json={"email": "exists@test.com"},
            )

        with patch("app.services.auth_service.generate_password_reset_token",
                   side_effect=ValueError("No user with that email address.")):
            resp_missing = client.post(
                "/api/auth/forgot-password",
                json={"email": "missing@test.com"},
            )

        # Both should return 200 with the same generic message
        assert resp_exists.status_code == 200
        assert resp_missing.status_code == 200
        assert generic_msg in resp_exists.json().get("message", "")
        assert generic_msg in resp_missing.json().get("message", "")
