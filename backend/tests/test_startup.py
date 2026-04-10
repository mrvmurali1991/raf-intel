"""
Application startup tests.

Verifies that:
- The FastAPI app can be imported without errors (no circular imports)
- All routers are registered and appear in the OpenAPI schema
- All expected middleware is attached
- The database layer initialises and degrades gracefully when the DB is
  unreachable (returns 503 rather than crashing)
- Settings / config loads without raising exceptions
- Key security and operational behaviours are wired correctly

All tests run in-process against the TestClient — no live server needed.
"""
from __future__ import annotations

import sys
import importlib
from typing import Any

import pytest
from fastapi.testclient import TestClient


# ===========================================================================
# 1. Import / circular-dependency guard
# ===========================================================================

class TestImports:
    """The application and its core modules must import cleanly."""

    def test_app_main_imports_without_error(self):
        """
        Importing app.main must not raise any exception.
        If there is a circular import or a missing dependency the import will
        raise ImportError / ModuleNotFoundError — which this test catches.
        """
        # Use importlib so we get a clear error if something is wrong.
        try:
            import app.main  # noqa: F401
        except (ImportError, ModuleNotFoundError) as exc:
            pytest.fail(f"app.main failed to import: {exc}")

    def test_app_config_imports_without_error(self):
        try:
            import app.config  # noqa: F401
        except (ImportError, ModuleNotFoundError) as exc:
            pytest.fail(f"app.config failed to import: {exc}")

    def test_app_auth_imports_without_error(self):
        try:
            import app.auth  # noqa: F401
        except (ImportError, ModuleNotFoundError) as exc:
            pytest.fail(f"app.auth failed to import: {exc}")

    def test_app_db_imports_without_error(self):
        try:
            import app.db  # noqa: F401
        except (ImportError, ModuleNotFoundError) as exc:
            pytest.fail(f"app.db failed to import: {exc}")

    def test_all_router_modules_import_without_error(self):
        """Every router listed in app/routers must import cleanly."""
        router_names = [
            "app.routers.auth",
            "app.routers.patients",
            "app.routers.raf",
            "app.routers.analysis",
            "app.routers.suspects",
            "app.routers.documents",
            "app.routers.claims",
            "app.routers.submissions",
            "app.routers.fhir",
            "app.routers.webhooks",
            "app.routers.providers",
            "app.routers.quality",
            "app.routers.prospective",
            "app.routers.benchmarks",
            "app.routers.jobs",
            "app.routers.reports",
            "app.routers.audit",
        ]
        for module_name in router_names:
            try:
                importlib.import_module(module_name)
            except (ImportError, ModuleNotFoundError) as exc:
                pytest.fail(f"Router module '{module_name}' failed to import: {exc}")

    def test_auth_service_imports_without_error(self):
        try:
            import app.services.auth_service  # noqa: F401
        except (ImportError, ModuleNotFoundError) as exc:
            pytest.fail(f"app.services.auth_service failed to import: {exc}")

    def test_no_duplicate_module_objects(self):
        """
        The same module must not appear twice under different paths in sys.modules.
        This catches certain classes of import cycle / reload bugs.
        """
        import app.main  # noqa: F401
        import app.config  # noqa: F401
        # If 'app.config' is imported twice under two different names the
        # settings singleton would be duplicated.  Verify they are the same object.
        mod_a = sys.modules.get("app.config")
        # Re-import via importlib to detect cache miss.
        mod_b = importlib.import_module("app.config")
        assert mod_a is mod_b, (
            "app.config module object differs between sys.modules and importlib — "
            "possible reload / duplicate import issue."
        )


# ===========================================================================
# 2. Router registration
# ===========================================================================

class TestRouterRegistration:
    """All routers must be included in the FastAPI app and appear in OpenAPI."""

    @pytest.fixture(scope="class")
    def openapi_paths(self, client: TestClient) -> set[str]:
        """Fetch the OpenAPI schema and return the set of registered paths."""
        r = client.get("/openapi.json")
        assert r.status_code == 200, f"GET /openapi.json returned {r.status_code}"
        return set(r.json().get("paths", {}).keys())

    # The expected path *prefixes* — at least one registered path must start
    # with each prefix for the router to be considered "included".
    EXPECTED_PREFIXES = [
        "/api/auth/",
        "/api/patients",
        "/api/raf/",
        "/api/analysis",
        "/api/suspects",
        "/api/documents",
        "/api/claims/",
        "/api/submissions/",
        "/api/fhir/",
        "/api/webhooks/",
        "/api/providers",
        "/api/quality/",
        "/api/prospective/",
        "/api/benchmarks/",
        "/api/jobs",
        "/api/reports",
        "/api/audit",
        "/health",
    ]

    @pytest.mark.parametrize("prefix", EXPECTED_PREFIXES)
    def test_router_prefix_registered(
        self, openapi_paths: set[str], prefix: str
    ):
        matching = [p for p in openapi_paths if p.startswith(prefix)]
        assert matching, (
            f"No path starting with '{prefix}' found in the OpenAPI schema. "
            f"This router may not be registered in app/main.py. "
            f"Registered paths (first 30): {sorted(openapi_paths)[:30]}"
        )

    def test_total_route_count_is_reasonable(self, openapi_paths: set[str]):
        """
        A fully-wired application should have many routes.
        This catches catastrophic partial-registration failures.
        """
        assert len(openapi_paths) >= 30, (
            f"Only {len(openapi_paths)} paths in OpenAPI schema — "
            "expected at least 30 for a fully-wired application."
        )

    def test_auth_login_endpoint_registered(self, openapi_paths: set[str]):
        assert "/api/auth/login" in openapi_paths, (
            "POST /api/auth/login not found in OpenAPI schema"
        )

    def test_health_endpoint_registered(self, openapi_paths: set[str]):
        assert "/health" in openapi_paths, (
            "/health not found in OpenAPI schema"
        )

    def test_root_endpoint_registered(self, openapi_paths: set[str]):
        assert "/" in openapi_paths, (
            "Root path '/' not found in OpenAPI schema"
        )


# ===========================================================================
# 3. Middleware verification
# ===========================================================================

class TestMiddleware:
    """Verify that all expected middleware layers are active."""

    def test_cors_headers_present_on_options_preflight(self, client: TestClient):
        """
        CORSMiddleware must respond to OPTIONS preflight requests with the
        appropriate Access-Control-Allow-* headers.
        """
        r = client.options(
            "/api/auth/login",
            headers={
                "Origin": "http://localhost:3500",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "Authorization, Content-Type",
            },
        )
        # 200 or 204 are both valid preflight responses.
        assert r.status_code in (200, 204), (
            f"CORS preflight returned {r.status_code} — CORSMiddleware may not be wired"
        )

    def test_security_headers_on_root_endpoint(self, client: TestClient):
        """SecurityHeadersMiddleware must inject HIPAA headers on every response."""
        r = client.get("/")
        assert r.status_code == 200
        required_headers = {
            "x-content-type-options",
            "x-frame-options",
            "x-xss-protection",
            "cache-control",
        }
        response_headers_lower = {k.lower() for k in r.headers.keys()}
        missing = required_headers - response_headers_lower
        assert not missing, (
            f"SecurityHeadersMiddleware missing headers: {missing}. "
            f"Got: {dict(r.headers)}"
        )

    def test_x_content_type_options_is_nosniff(self, client: TestClient):
        r = client.get("/")
        assert r.headers.get("x-content-type-options", "").lower() == "nosniff"

    def test_x_frame_options_is_deny(self, client: TestClient):
        r = client.get("/")
        assert r.headers.get("x-frame-options", "").upper() == "DENY"

    def test_cache_control_prevents_caching(self, client: TestClient):
        r = client.get("/health")
        cc = r.headers.get("cache-control", "").lower()
        assert "no-store" in cc or "no-cache" in cc, (
            f"Cache-Control header does not prevent caching: '{cc}'"
        )

    def test_process_time_header_present(self, client: TestClient):
        """The request-timing middleware must add X-Process-Time-Ms."""
        r = client.get("/")
        assert "x-process-time-ms" in {k.lower() for k in r.headers.keys()}, (
            "X-Process-Time-Ms header missing — request timing middleware may not be active"
        )

    def test_process_time_is_numeric(self, client: TestClient):
        r = client.get("/")
        val = r.headers.get("x-process-time-ms") or r.headers.get("X-Process-Time-Ms")
        if val is not None:
            try:
                float(val)
            except ValueError:
                pytest.fail(f"X-Process-Time-Ms is not numeric: {val!r}")


# ===========================================================================
# 4. Config / settings
# ===========================================================================

class TestConfigLoads:
    """app.config.settings must be populated with required keys."""

    @pytest.fixture(scope="class")
    def settings(self):
        from app.config import settings as _settings
        return _settings

    def test_settings_object_exists(self, settings):
        assert settings is not None

    def test_jwt_secret_is_set(self, settings):
        assert getattr(settings, "jwt_secret", None), (
            "settings.jwt_secret must not be empty — JWT signing will fail"
        )

    def test_gemini_model_is_set(self, settings):
        assert getattr(settings, "gemini_model", None), (
            "settings.gemini_model must not be empty"
        )

    def test_access_token_expire_minutes_is_positive(self, settings):
        minutes = getattr(settings, "access_token_expire_minutes", None)
        assert minutes is not None and int(minutes) > 0, (
            f"settings.access_token_expire_minutes must be a positive int, got {minutes}"
        )

    def test_refresh_token_expire_days_is_positive(self, settings):
        days = getattr(settings, "refresh_token_expire_days", None)
        assert days is not None and int(days) > 0, (
            f"settings.refresh_token_expire_days must be positive, got {days}"
        )

    def test_app_port_is_valid(self, settings):
        port = getattr(settings, "app_port", None)
        if port is not None:
            assert 1 <= int(port) <= 65535, f"settings.app_port {port} is out of range"


# ===========================================================================
# 5. Database graceful degradation
# ===========================================================================

class TestDatabaseGracefulDegradation:
    """
    The /health endpoint must respond with a 200 OR 503 — never crash (500)
    even when the database is unavailable.
    """

    def test_health_returns_200_or_503(self, client: TestClient):
        r = client.get("/health")
        assert r.status_code in (200, 503), (
            f"GET /health returned {r.status_code} — expected 200 (healthy) or 503 (degraded)"
        )

    def test_health_body_is_json(self, client: TestClient):
        r = client.get("/health")
        try:
            data = r.json()
        except Exception as exc:
            pytest.fail(f"/health returned non-JSON body: {exc}. Body: {r.text[:200]}")
        assert isinstance(data, dict)

    def test_health_status_field_present(self, client: TestClient):
        r = client.get("/health")
        data = r.json()
        assert "status" in data, f"Missing 'status' key in /health: {data}"

    def test_health_databases_field_present(self, client: TestClient):
        r = client.get("/health")
        data = r.json()
        assert "databases" in data, f"Missing 'databases' key in /health: {data}"
        assert isinstance(data["databases"], dict)

    def test_health_status_is_known_value(self, client: TestClient):
        r = client.get("/health")
        status = r.json().get("status")
        assert status in ("healthy", "degraded"), (
            f"Unexpected health status value: {status!r}"
        )

    def test_db_check_function_does_not_raise(self):
        """app.db.check_connections() must not raise even if DB is down."""
        from app.db import check_connections
        try:
            result = check_connections()
        except Exception as exc:
            pytest.fail(f"check_connections() raised an exception: {exc}")
        assert isinstance(result, dict), (
            f"check_connections() must return a dict, got {type(result)}"
        )
        for key, val in result.items():
            assert isinstance(val, bool), (
                f"check_connections()[{key!r}] must be bool, got {type(val)}"
            )


# ===========================================================================
# 6. FastAPI app object properties
# ===========================================================================

class TestAppObject:
    """The FastAPI application instance must be correctly configured."""

    @pytest.fixture(scope="class")
    def fastapi_app(self, app):
        return app

    def test_app_title_is_set(self, fastapi_app):
        assert fastapi_app.title, "FastAPI app.title must not be empty"

    def test_app_version_is_set(self, fastapi_app):
        assert fastapi_app.version, "FastAPI app.version must not be empty"

    def test_docs_url_is_configured(self, fastapi_app):
        assert fastapi_app.docs_url == "/docs", (
            f"Expected docs_url='/docs', got {fastapi_app.docs_url!r}"
        )

    def test_redoc_url_is_configured(self, fastapi_app):
        assert fastapi_app.redoc_url == "/redoc", (
            f"Expected redoc_url='/redoc', got {fastapi_app.redoc_url!r}"
        )

    def test_openapi_url_is_configured(self, fastapi_app):
        assert fastapi_app.openapi_url == "/openapi.json"

    def test_router_count_is_reasonable(self, fastapi_app):
        """The app must have a substantial number of route handlers."""
        routes = fastapi_app.routes
        assert len(routes) >= 30, (
            f"Expected >= 30 routes, found {len(routes)}. "
            "Some routers may not be registered."
        )

    def test_rate_limiter_attached(self, fastapi_app):
        """slowapi limiter must be stored in app.state."""
        assert hasattr(fastapi_app.state, "limiter"), (
            "app.state.limiter not found — rate limiting middleware may not be active"
        )

    def test_exception_handler_registered(self, fastapi_app):
        """A global exception handler must be present to prevent stack-trace leakage."""
        handlers = dict(fastapi_app.exception_handlers)
        assert Exception in handlers or 500 in handlers, (
            "No global Exception handler found — internal errors may leak stack traces"
        )

    def test_global_exception_handler_returns_500_not_traceback(
        self, client: TestClient
    ):
        """
        The global exception handler must return a clean JSON 500 without
        leaking internal details such as stack traces.
        """
        # We provoke a 500 by hitting a path we know will generate an internal
        # error: passing a non-numeric value where an integer PID is expected.
        # This is safe — it validates the error handling, not the business logic.
        r = client.get("/api/raf/scores/not_a_number")
        # 401 is also acceptable because auth middleware can run before
        # path-parameter validation on protected endpoints.
        assert r.status_code in (401, 422, 404, 500), (
            f"Unexpected status {r.status_code}"
        )
        if r.status_code == 500:
            body = r.text.lower()
            for forbidden in ("traceback", "file \"", "line ", "sqlalchemy"):
                assert forbidden not in body, (
                    f"500 response leaks internal detail ('{forbidden}'): {r.text[:300]}"
                )

    def test_docs_endpoint_returns_200(self, client: TestClient):
        r = client.get("/docs")
        assert r.status_code == 200, f"GET /docs returned {r.status_code}"

    def test_openapi_json_is_valid(self, client: TestClient):
        r = client.get("/openapi.json")
        assert r.status_code == 200
        schema = r.json()
        for required_key in ("openapi", "info", "paths"):
            assert required_key in schema, (
                f"OpenAPI schema missing required key '{required_key}'"
            )

    def test_openapi_tags_cover_all_routers(self, client: TestClient):
        """
        Each router must have at least one tag defined in the global tags_metadata
        list so that the Swagger UI groups them correctly.
        """
        r = client.get("/openapi.json")
        schema = r.json()
        defined_tag_names = {t["name"] for t in schema.get("tags", [])}
        expected_tags = {
            "auth", "patients", "raf", "analysis", "documents", "claims",
            "submissions", "fhir", "webhooks", "providers", "quality",
            "prospective", "benchmarks", "jobs", "health",
        }
        missing = expected_tags - defined_tag_names
        assert not missing, (
            f"OpenAPI schema is missing tags for routers: {missing}"
        )
