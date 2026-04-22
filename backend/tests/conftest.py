"""
Shared pytest fixtures for the RAF Intelligence test suite.

Two fixture layers exist side-by-side:

1. Live-server fixtures (requests.Session, base_url, api_client ...)
   Used by the original test_api_health.py / test_raf.py.
   These hit a running backend at http://localhost:8500.

2. In-process fixtures (client, auth_headers, admin_headers ...)
   Used by the new mocked test modules.
   These use FastAPI TestClient — no external server needed.

3. Isolated unit-test fixtures (mock_raf_cursor, mock_openemr_cursor, ...)
   Used by test_raf_calculator.py / test_auth.py / test_api_endpoints.py /
   test_security.py.
   All DB calls are mocked — no database connection required.

All sets live in a single conftest.py so that all test files can share
fixtures without confusion.
"""

from __future__ import annotations

import os

# Compatibility patch for passlib and bcrypt >= 4.0.0
try:
    import bcrypt
    if not hasattr(bcrypt, "__about__"):
        class _About:
            __version__ = getattr(bcrypt, "__version__", "4.0.0")
        bcrypt.__about__ = _About()
except ImportError:
    pass
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from typing import Any
from unittest.mock import MagicMock, patch

import jwt
import pytest


@pytest.fixture(scope="session", autouse=True)
def _patch_emr_gate_for_all_tests():
    """
    Globally patch the `emr_gate` middleware check for all tests.
    The middleware checks for an active EMR or uploaded data. Since the DB
    is mocked, this check will always fail. This patch makes the check
    always succeed.
    """
    import importlib
    try:
        importlib.import_module("app.services.emr_manager")
    except Exception:
        yield
        return
    with patch(
        "app.services.emr_manager.list_connections", return_value=[{"is_active": 1}]
    ):
        yield


import requests
from fastapi.testclient import TestClient

# ---------------------------------------------------------------------------
# Environment setup — must happen BEFORE app is imported so that config.py
# reads test values instead of requiring real credentials.
# ---------------------------------------------------------------------------

os.environ.setdefault("APP_ENV", "development")
os.environ.setdefault("JWT_SECRET", "test-jwt-secret-for-pytest-do-not-use-in-prod")
os.environ.setdefault("JWT_REFRESH_SECRET", "test-refresh-secret-for-pytest")
os.environ.setdefault("OPENEMR_DB_USER", "test_user")
os.environ.setdefault("OPENEMR_DB_PASSWORD", "test_password")
os.environ.setdefault("RAF_DB_USER", "test_user")
os.environ.setdefault("RAF_DB_PASSWORD", "test_password")
os.environ.setdefault("DB_SSL_ENABLED", "false")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("GOOGLE_API_KEY", "fake-google-api-key-for-tests")
# Force tests to use the legacy API-key transport rather than Vertex AI so
# that llm_generate() does not attempt to load GCP service-account credentials
# during unit tests.  Individual tests that exercise Vertex transport
# explicitly re-set LLM_USE_VERTEX=true via monkeypatch.
os.environ.setdefault("LLM_USE_VERTEX", "false")
# Force env vars for test session before any app imports.
# Use assignment instead of setdefault to ensure they are overridden.
os.environ["RATE_LIMITING_ENABLED"] = "false"
os.environ["APP_ENV"] = "testing"
os.environ["FRONTEND_URL"] = "http://localhost:3000"
os.environ["STRICT_MIGRATIONS"] = "false"
os.environ["PHI_FERNET_KEY"] = "jA8a-p7k_j9yv-gXy_AhTzX_h8oZ_wYqFp_rWs3vDcE="
os.environ["PHI_AES256_KEY"] = "a2l2eW1veXFja25ia3hzeG5wbGp0d3JsdmJmY3p0YWE="


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

BASE_URL = os.getenv("TEST_BASE_URL", "http://localhost:8500")
TEST_JWT_SECRET = os.environ["JWT_SECRET"]
TEST_JWT_REFRESH_SECRET = os.environ["JWT_REFRESH_SECRET"]
TEST_JWT_ALGORITHM = "HS256"

# ---------------------------------------------------------------------------
# Shared mock user records — used by fixtures and test modules
# ---------------------------------------------------------------------------

MOCK_ADMIN_USER: dict[str, Any] = {
    "id": 1,
    "email": "admin@raf-test.health",
    "full_name": "Test Admin",
    "role": "admin",
    "tenant_id": 1,
    "is_active": 1,
    "session_id": "session-admin-001",
    "token_role": "admin",
    "avatar_url": None,
    "last_login_at": datetime(2026, 4, 1, 12, 0, 0),
    # Password hash for 'Admin@123' (bcrypt)
    "password_hash": "$2b$12$kYSTW3D7Xp2U1RzY7Z0R3e4u8m6P1y7.jS1VfKz/mGtH5E6D7G8I2",
    "password_changed_at": datetime(2026, 3, 1, 12, 0, 0),
    "created_at": datetime(2026, 1, 1),
    "updated_at": datetime(2026, 3, 1),
    "must_change_password": False,
    "mfa_enabled": 0,
    "mfa_secret": None,
    "mfa_recovery_codes": None,
}

MOCK_VIEWER_USER: dict[str, Any] = {
    "id": 2,
    "email": "viewer@raf-test.health",
    "full_name": "Test Viewer",
    "role": "viewer",
    "tenant_id": 1,
    "is_active": 1,
    "session_id": "session-viewer-002",
    "token_role": "viewer",
    "avatar_url": None,
    "last_login_at": None,
    "password_hash": "$2b$12$kYSTW3D7Xp2U1RzY7Z0R3e4u8m6P1y7.jS1VfKz/mGtH5E6D7G8I2",
    "password_changed_at": None,
    "created_at": datetime(2026, 1, 1),
    "updated_at": datetime(2026, 1, 1),
    "must_change_password": True,
    "mfa_enabled": 0,
    "mfa_secret": None,
    "mfa_recovery_codes": None,
}

MOCK_MANAGER_USER: dict[str, Any] = {
    "id": 3,
    "email": "manager@raf-test.health",
    "full_name": "Test Manager",
    "role": "manager",
    "tenant_id": 1,
    "is_active": 1,
    "session_id": "session-manager-003",
    "token_role": "manager",
    "avatar_url": None,
    "last_login_at": datetime(2026, 4, 1, 10, 0, 0),
    "password_changed_at": datetime(2026, 3, 1, 10, 0, 0),
    "created_at": datetime(2026, 1, 1),
    "updated_at": datetime(2026, 3, 1),
    "must_change_password": False,
    "mfa_enabled": 0,
    "mfa_secret": None,
    "mfa_recovery_codes": None,
}

MOCK_TENANT_B_USER: dict[str, Any] = {
    "id": 99,
    "email": "tenantb@other-org.health",
    "full_name": "Tenant B User",
    "role": "admin",
    "tenant_id": 2,
    "is_active": 1,
    "session_id": "session-tenant-b-099",
    "token_role": "admin",
    "avatar_url": None,
    "last_login_at": None,
    "password_changed_at": datetime(2026, 2, 1),
    "created_at": datetime(2026, 1, 1),
    "updated_at": datetime(2026, 1, 1),
    "must_change_password": False,
    "mfa_enabled": 0,
    "mfa_secret": None,
    "mfa_recovery_codes": None,
}

MOCK_MFA_USER: dict[str, Any] = {
    "id": 5,
    "email": "mfa@raf-test.health",
    "full_name": "MFA User",
    "role": "viewer",
    "tenant_id": 1,
    "is_active": 1,
    "session_id": "session-mfa-005",
    "token_role": "viewer",
    "avatar_url": None,
    "last_login_at": None,
    "password_changed_at": datetime(2026, 3, 1),
    "created_at": datetime(2026, 1, 1),
    "updated_at": datetime(2026, 3, 1),
    "must_change_password": False,
    "mfa_enabled": 1,
    "mfa_secret": "JBSWY3DPEHPK3PXP",  # well-known test TOTP secret
    "mfa_recovery_codes": None,
}


# ---------------------------------------------------------------------------
# JWT token helpers
# ---------------------------------------------------------------------------


def _make_access_token(user: dict[str, Any], expired: bool = False) -> str:
    """Mint a test access token for the given user dict."""
    now = datetime.now(timezone.utc)
    exp = now - timedelta(minutes=5) if expired else now + timedelta(minutes=15)
    payload = {
        "sub": str(user["id"]),
        "email": user["email"],
        "role": user["role"],
        "tenant_id": user["tenant_id"],
        "session_id": user["session_id"],
        "iat": now,
        "exp": exp,
        "type": "access",
    }
    return jwt.encode(payload, TEST_JWT_SECRET, algorithm=TEST_JWT_ALGORITHM)


def _make_refresh_token(user: dict[str, Any], expired: bool = False) -> str:
    """Mint a test refresh token for the given user dict."""
    now = datetime.now(timezone.utc)
    exp = now - timedelta(days=1) if expired else now + timedelta(days=7)
    payload = {
        "sub": str(user["id"]),
        "session_id": user["session_id"],
        "iat": now,
        "exp": exp,
        "type": "refresh",
    }
    return jwt.encode(payload, TEST_JWT_REFRESH_SECRET, algorithm=TEST_JWT_ALGORITHM)


def _make_mfa_pending_token(user_id: int, expired: bool = False) -> str:
    """Mint a test mfa_pending token."""
    now = datetime.now(timezone.utc)
    exp = now - timedelta(minutes=1) if expired else now + timedelta(minutes=5)
    payload = {
        "sub": str(user_id),
        "iat": now,
        "exp": exp,
        "type": "mfa_pending",
    }
    return jwt.encode(payload, TEST_JWT_SECRET, algorithm=TEST_JWT_ALGORITHM)


# ---------------------------------------------------------------------------
# Mock cursor context-manager factory
# ---------------------------------------------------------------------------


class MockCursor:
    """Minimal dict-based cursor mock matching mysql-connector-python interface."""

    def __init__(self, rows: list[dict] | None = None, lastrowid: int = 1):
        self._default_rows = list(rows or [])
        self._active_rows = self._default_rows
        self.lastrowid = lastrowid
        self.rowcount = len(self._active_rows)
        self._query_log: list[str] = []

    def execute(self, query: str, params=None):
        self._query_log.append(query)
        self.rowcount = len(self._active_rows)

    def executemany(self, query: str, params_seq=None):
        self._query_log.append(query)

    def fetchone(self) -> dict | None:
        return self._active_rows[0] if self._active_rows else None

    def fetchall(self) -> list[dict]:
        return list(self._active_rows)

    def close(self):
        pass


def make_cursor_cm(rows: list[dict] | None = None, lastrowid: int = 1):
    """Return a context-manager mock that yields a MockCursor."""
    cursor = MockCursor(rows=rows, lastrowid=lastrowid)

    @contextmanager
    def _cm(*args, **kwargs):
        yield cursor

    return _cm, cursor


# ---------------------------------------------------------------------------
# In-process FastAPI TestClient fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def _mock_db_for_app():
    """
    Session-scoped patch that replaces all DB pool construction with no-ops.
    Applied before the app is first imported so that MySQLConnectionPool is
    never actually called during unit tests.
    """
    # Default mock patient for TestClient tests to prevent 404s
    dummy_patient = {"pid": "1", "fname": "Test", "lname": "Patient", "DOB": "1960-01-01", "sex": "Female"}
    openemr_cm, _ = make_cursor_cm(rows=[dummy_patient])
    noop_cm, _ = make_cursor_cm()
    with (
        patch("app.db._build_openemr_pool", return_value=MagicMock()),
        patch("app.db._build_raf_pool", return_value=MagicMock()),
        patch("app.db.check_connections", return_value={"openemr": True, "raf": True}),
        patch("app.db.raf_cursor", noop_cm),
        patch("app.db.openemr_cursor", openemr_cm),
        patch(
            "app.services.emr_manager.get_active_direct_db_credentials",
            return_value=None,
        ),
        patch("app.migrations.run_all_migrations", return_value={}),
    ):
        yield


@pytest.fixture(scope="session")
def app(_mock_db_for_app):
    """Return the FastAPI application (session-scoped, constructed once)."""
    from app.main import app as _app

    return _app


@pytest.fixture(scope="session")
def client(app):
    """TestClient wrapping the FastAPI app — no live server needed."""
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


# ---------------------------------------------------------------------------
# Auth header fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def mock_admin_user():
    """Return a copy of the admin user dict."""
    return dict(MOCK_ADMIN_USER)


@pytest.fixture()
def mock_viewer_user():
    """Return a copy of the viewer user dict."""
    return dict(MOCK_VIEWER_USER)


@pytest.fixture()
def mock_manager_user():
    """Return a copy of the manager user dict."""
    return dict(MOCK_MANAGER_USER)


@pytest.fixture()
def admin_token(mock_admin_user) -> str:
    return _make_access_token(mock_admin_user)


@pytest.fixture()
def viewer_token(mock_viewer_user) -> str:
    return _make_access_token(mock_viewer_user)


@pytest.fixture()
def manager_token(mock_manager_user) -> str:
    return _make_access_token(mock_manager_user)


@pytest.fixture()
def tenant_b_token() -> str:
    return _make_access_token(MOCK_TENANT_B_USER)


@pytest.fixture()
def admin_headers(admin_token) -> dict[str, str]:
    return {"Authorization": f"Bearer {admin_token}"}


@pytest.fixture()
def viewer_headers(viewer_token) -> dict[str, str]:
    return {"Authorization": f"Bearer {viewer_token}"}


@pytest.fixture()
def manager_headers(manager_token) -> dict[str, str]:
    return {"Authorization": f"Bearer {manager_token}"}


@pytest.fixture()
def tenant_b_headers(tenant_b_token) -> dict[str, str]:
    return {"Authorization": f"Bearer {tenant_b_token}"}


@pytest.fixture(scope="module")
def module_scoped_admin_headers() -> dict[str, str]:
    """Return a module-scoped admin auth header."""
    token = _make_access_token(MOCK_ADMIN_USER)
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture()
def auth_headers(viewer_token) -> dict[str, str]:
    """Generic auth headers — viewer role for safe cross-router testing.
    
    RBAC tests in test_auth_flow.py and test_security.py expect this to be
    a low-privilege role so they can verify 403 Forbidden responses.
    Router smoke tests that require admin access must use admin_headers explicitly.
    """
    return {"Authorization": f"Bearer {viewer_token}"}


@pytest.fixture()
def _test_user_credentials() -> tuple[str, str]:
    """Canonical test credentials — matches MOCK_ADMIN_USER email + a known password."""
    return ("admin@raf.health", "Admin@123")


# ---------------------------------------------------------------------------
# Auto-patch auth resolution so JWT-based tests resolve to mock users
# ---------------------------------------------------------------------------

_MOCK_CRUD_USER: dict[str, Any] = {
    "id": 99, "email": "crud_user@raf-test.example", "full_name": "CRUD Test User",
    "role": "viewer", "tenant_id": 1, "is_active": 1, "session_id": "session-crud-099",
    "token_role": "viewer", "avatar_url": None,
    "last_login_at": None, "password_changed_at": None,
    "created_at": datetime(2026, 4, 12), "updated_at": datetime(2026, 4, 12),
    "must_change_password": False, "mfa_enabled": 0, "mfa_secret": None, "mfa_recovery_codes": None,
}

_USERS_BY_ID: dict[int, dict[str, Any]] = {
    u["id"]: u
    for u in (MOCK_ADMIN_USER, MOCK_VIEWER_USER, MOCK_MANAGER_USER, MOCK_TENANT_B_USER, _MOCK_CRUD_USER)
}


@pytest.fixture(autouse=True)
def _patch_auth_resolution():
    """
    Globally patch get_user and validate_session so that any JWT token
    created by _make_access_token resolves to the corresponding mock user.

    Each patch target is import-guarded: unit tests that never exercise
    HTTP auth (e.g. pure scoring/reconcile tests) don't need the full
    service layer importable, so we silently skip targets whose parent
    module fails to import.
    """
    import importlib
    from contextlib import ExitStack

    def _fake_get_user(user_id: int) -> dict | None:
        return dict(_USERS_BY_ID[user_id]) if user_id in _USERS_BY_ID else None

    def _fake_validate_session(session_id: str) -> dict | None:
        return {"session_id": session_id, "is_revoked": 0}

    def _fake_get_user_by_email(email: str) -> dict | None:
        for u in _USERS_BY_ID.values():
            if u.get("email") == email:
                return dict(u)
        return None

    # (target, kwargs-for-patch)
    _targets: list[tuple[str, dict]] = [
        ("app.rate_limit.limiter.enabled", {"new": False}),
        ("app.services.auth_service.get_user", {"side_effect": _fake_get_user}),
        ("app.services.auth_service.get_user_by_email", {"side_effect": _fake_get_user_by_email}),
        ("app.services.auth_service.validate_session", {"side_effect": _fake_validate_session}),
        ("app.auth.get_user", {"side_effect": _fake_get_user}),
        ("app.auth.validate_session", {"side_effect": _fake_validate_session}),
        ("app.routers.auth.get_user", {"side_effect": _fake_get_user}),
        ("app.routers.auth.get_user_permissions", {"return_value": []}),
        ("app.routers.auth.set_user_permissions", {"return_value": None}),
        ("app.routers.realtime.get_user", {"side_effect": _fake_get_user}),
        ("app.routers.realtime.validate_session", {"side_effect": _fake_validate_session}),
    ]

    with ExitStack() as stack:
        for target, kwargs in _targets:
            parent = target.rsplit(".", 1)[0]
            try:
                importlib.import_module(parent)
            except Exception:
                continue
            try:
                stack.enter_context(patch(target, **kwargs))
            except (AttributeError, ModuleNotFoundError):
                continue
        yield


# ---------------------------------------------------------------------------
# Reusable DB cursor mock fixtures (function-scoped — fresh per test)
# ---------------------------------------------------------------------------


@pytest.fixture()
def mock_raf_cursor_factory():
    """Return a factory that creates a patched raf_cursor yielding given rows."""

    def _factory(rows=None, lastrowid=1):
        cm, cursor = make_cursor_cm(rows=rows, lastrowid=lastrowid)
        return patch("app.db.raf_cursor", cm), cursor

    return _factory


@pytest.fixture()
def mock_openemr_cursor_factory():
    """Return a factory that creates a patched openemr_cursor yielding given rows."""

    def _factory(rows=None, lastrowid=1):
        cm, cursor = make_cursor_cm(rows=rows, lastrowid=lastrowid)
        return patch("app.db.openemr_cursor", cm), cursor

    return _factory


# ---------------------------------------------------------------------------
# Authenticated client helper — patches get_current_user for a single test
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def authed_client(client):
    """
    TestClient with get_current_user and validate_session pre-mocked so that
    auth dependency injection succeeds without a real database.

    Module-scoped for use in expensive fixtures.
    """
    user = dict(MOCK_ADMIN_USER)
    with (
        patch("app.services.auth_service.get_user", return_value=user),
        patch(
            "app.services.auth_service.validate_session",
            return_value={"session_id": user["session_id"]},
        ),
        patch("app.auth.get_user", return_value=user),
        patch(
            "app.auth.validate_session", return_value={"session_id": user["session_id"]}
        ),
    ):
        # The client needs headers to be authenticated
        token = _make_access_token(user)
        client.headers["Authorization"] = f"Bearer {token}"
        yield client
        # Clean up headers after
        del client.headers["Authorization"]


# ---------------------------------------------------------------------------
# Mock Redis fixture
# ---------------------------------------------------------------------------

@pytest.fixture()
def nonexistent_pid() -> int:
    """Return a PID that is guaranteed not to exist in mock DBs."""
    return 999999


@pytest.fixture()
def mock_redis():
    """Return a MagicMock that mimics a Redis client."""
    r = MagicMock()
    r.get.return_value = None
    r.set.return_value = True
    r.delete.return_value = 1
    r.exists.return_value = 0
    r.expire.return_value = True
    r.incr.return_value = 1
    return r


# ---------------------------------------------------------------------------
# Legacy live-server fixtures (kept for backward compat with test_api_health)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def base_url():
    return BASE_URL


@pytest.fixture(scope="session")
def api_client(base_url):
    session = requests.Session()
    session.headers.update({"Content-Type": "application/json"})
    # Authenticate for live API tests
    try:
        r = session.post(
            f"{base_url}/api/auth/login",
            json={"email": "admin@raf.health", "password": "Admin@123"},
        )
        if r.status_code == 200:
            token = r.json().get("access_token")
            if token:
                session.headers["Authorization"] = f"Bearer {token}"
    except Exception:
        pass  # Server may not be running; tests will skip/fail gracefully
    return session


@pytest.fixture(scope="session")
def first_pid() -> int:
    """Return a static patient ID for live API tests."""
    return 1


@pytest.fixture(scope="session")
def sample_patients(api_client, base_url) -> list[dict]:
    """Fetch a small list of patients from the live API for plausibility tests."""
    try:
        r = api_client.get(f"{base_url}/api/patients?limit=5", timeout=10)
        if r.status_code == 200:
            data = r.json()
            return data.get("patients", data) if isinstance(data, dict) else data
    except Exception:
        pass
    return []
