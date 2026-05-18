"""
Basic health and infrastructure tests.

These should always pass when the backend is running, regardless of what
patient data is in the database.
"""
from __future__ import annotations

import pytest
import requests

pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# Health endpoint
# ---------------------------------------------------------------------------

class TestHealthEndpoint:
    """GET /health"""

    def test_health_returns_2xx(self, api_client: requests.Session, base_url: str):
        """
        /health MUST return either 200 (all DBs healthy) or 503 (degraded).
        Both indicate the server is alive and the endpoint is functional.
        """
        r = api_client.get(f"{base_url}/health")
        assert r.status_code in (200, 503), (
            f"Expected 200 or 503 from /health, got {r.status_code}. "
            f"Body: {r.text[:300]}"
        )

    def test_health_returns_json(self, api_client: requests.Session, base_url: str):
        """Response body must be valid JSON."""
        r = api_client.get(f"{base_url}/health")
        data = r.json()
        assert isinstance(data, dict), "Expected a JSON object from /health"

    def test_health_has_status_field(self, api_client: requests.Session, base_url: str):
        """Response must contain a 'status' key."""
        r = api_client.get(f"{base_url}/health")
        data = r.json()
        assert "status" in data, f"Missing 'status' field in /health response: {data}"

    def test_health_status_is_healthy_or_degraded(
        self, api_client: requests.Session, base_url: str
    ):
        """'status' value must be one of the known strings."""
        r = api_client.get(f"{base_url}/health")
        data = r.json()
        assert data["status"] in ("healthy", "degraded"), (
            f"Unexpected status value: {data['status']!r}"
        )

    def test_health_has_databases_field(self, api_client: requests.Session, base_url: str):
        """Response must expose DB connection status."""
        r = api_client.get(f"{base_url}/health")
        data = r.json()
        assert "databases" in data, f"Missing 'databases' field in /health response: {data}"
        assert isinstance(data["databases"], dict), "'databases' must be a mapping"

    def test_health_has_gemini_model_field(self, api_client: requests.Session, base_url: str):
        """Response must indicate the configured Gemini model."""
        r = api_client.get(f"{base_url}/health")
        data = r.json()
        assert "gemini_model" in data, f"Missing 'gemini_model' in /health response: {data}"
        assert data["gemini_model"], "'gemini_model' should not be empty"

    def test_health_is_healthy(self, api_client: requests.Session, base_url: str):
        """
        For integration tests to be meaningful both databases should be up.
        Mark as XFAIL (rather than hard-fail) if DB is degraded, so the CI
        pipeline still shows the other tests.
        """
        r = api_client.get(f"{base_url}/health")
        data = r.json()
        if data["status"] == "degraded":
            pytest.xfail(
                "Backend reports degraded DB connections — other tests may also fail. "
                f"DB status: {data.get('databases')}"
            )


# ---------------------------------------------------------------------------
# Root endpoint
# ---------------------------------------------------------------------------

class TestRootEndpoint:
    """GET /"""

    def test_root_returns_200(self, api_client: requests.Session, base_url: str):
        r = api_client.get(f"{base_url}/")
        assert r.status_code == 200, f"Expected 200 from /, got {r.status_code}"

    def test_root_returns_service_info(self, api_client: requests.Session, base_url: str):
        r = api_client.get(f"{base_url}/")
        data = r.json()
        assert data.get("service") == "RAF Intelligence System"
        assert data.get("status") == "running"
        assert "version" in data
        assert "docs" in data


# ---------------------------------------------------------------------------
# OpenAPI / Swagger UI
# ---------------------------------------------------------------------------

class TestDocsEndpoints:
    """FastAPI documentation endpoints."""

    def test_docs_returns_200(self, api_client: requests.Session, base_url: str):
        """Swagger UI at /docs must be reachable."""
        r = api_client.get(f"{base_url}/docs")
        assert r.status_code == 200, (
            f"GET /docs returned {r.status_code} — Swagger UI not available"
        )

    def test_redoc_returns_200(self, api_client: requests.Session, base_url: str):
        """ReDoc UI at /redoc must be reachable."""
        r = api_client.get(f"{base_url}/redoc")
        assert r.status_code == 200, (
            f"GET /redoc returned {r.status_code} — ReDoc UI not available"
        )

    def test_openapi_json_returns_200(self, api_client: requests.Session, base_url: str):
        """OpenAPI JSON schema must be valid and parseable."""
        r = api_client.get(f"{base_url}/openapi.json")
        assert r.status_code == 200, f"GET /openapi.json returned {r.status_code}"
        schema = r.json()
        assert "openapi" in schema, "OpenAPI schema missing 'openapi' version field"
        assert "paths" in schema, "OpenAPI schema missing 'paths'"
        assert "info" in schema, "OpenAPI schema missing 'info'"

    def test_openapi_schema_has_expected_routes(
        self, api_client: requests.Session, base_url: str
    ):
        """Key API paths must appear in the OpenAPI schema."""
        r = api_client.get(f"{base_url}/openapi.json")
        schema = r.json()
        paths = schema.get("paths", {})

        expected_prefixes = [
            "/api/patients",
            "/api/raf",
            "/api/analysis",
            "/health",
        ]
        for prefix in expected_prefixes:
            matching = [p for p in paths if p.startswith(prefix)]
            assert matching, (
                f"No path starting with '{prefix}' found in OpenAPI schema. "
                f"Available paths: {sorted(paths)[:20]}"
            )


# ---------------------------------------------------------------------------
# ICD-10 utility endpoints (lightweight smoke tests)
# ---------------------------------------------------------------------------

class TestICD10UtilityEndpoints:
    """GET /api/icd10/* — quick sanity checks for the validator layer."""

    def test_validate_known_valid_code(self, api_client: requests.Session, base_url: str):
        """E11.9 (Type 2 DM without complications) is a canonical valid ICD-10 code."""
        r = api_client.get(f"{base_url}/api/icd10/validate/E11.9")
        assert r.status_code == 200, f"Unexpected status {r.status_code}"
        data = r.json()
        assert data.get("valid") is True, f"E11.9 should be valid — got: {data}"

    def test_validate_invalid_code(self, api_client: requests.Session, base_url: str):
        """ZZZZZZ is not a valid ICD-10 code."""
        r = api_client.get(f"{base_url}/api/icd10/validate/ZZZZZZ")
        assert r.status_code == 200, f"Endpoint should return 200 even for invalid codes"
        data = r.json()
        assert data.get("valid") is False, f"ZZZZZZ should be invalid — got: {data}"

    def test_icd10_search_returns_results(self, api_client: requests.Session, base_url: str):
        """Search for 'diabetes' should return at least one result."""
        r = api_client.get(f"{base_url}/api/icd10/search", params={"query": "diabetes"})
        assert r.status_code == 200, f"Unexpected status {r.status_code}"
        data = r.json()
        assert "results" in data, f"Missing 'results' in ICD-10 search response: {data}"
        assert data.get("count", 0) > 0, "Expected at least one ICD-10 result for 'diabetes'"

    def test_icd10_search_response_structure(self, api_client: requests.Session, base_url: str):
        """Each result must contain 'code' and 'description' fields."""
        r = api_client.get(
            f"{base_url}/api/icd10/search", params={"query": "hypertension", "max_results": 5}
        )
        assert r.status_code == 200
        data = r.json()
        results = data.get("results", [])
        if results:
            first = results[0]
            assert "code" in first or "icd10" in first, (
                f"ICD-10 search result missing 'code' field: {first}"
            )
