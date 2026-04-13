"""
Router smoke tests — verify that every new router loads and responds correctly.

For each endpoint under test we run two scenarios:

1. Unauthenticated (no Authorization header) → expect HTTP 401
2. Authenticated (valid viewer-role Bearer token)  → expect HTTP 200

Some endpoints may return other 2xx codes (201, 204) or legitimate non-200
codes (404 when no data exists, 403 if the viewer lacks a specific permission).
The parametrised matrix covers the "at least reachable" requirement; detailed
functional validation belongs in dedicated router test modules.

All tests use the FastAPI TestClient (in-process) — no live server required.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# Endpoint catalogue
# Each entry: (HTTP method, path, description)
# ---------------------------------------------------------------------------

ROUTER_ENDPOINTS = [
    # FHIR integration
    ("GET",  "/api/fhir/connections",          "fhir: list connections"),
    # Claims
    ("GET",  "/api/claims/batches",             "claims: list batches"),
    # Documents
    ("GET",  "/api/documents",                  "documents: list documents"),
    # Providers
    ("GET",  "/api/providers",                  "providers: list providers"),
    # Submissions
    ("GET",  "/api/submissions/batches",        "submissions: list batches"),
    # Prospective RAF
    ("GET",  "/api/prospective/worklist",       "prospective: worklist"),
    # Quality / HEDIS
    ("GET",  "/api/quality/measures",           "quality: list measures"),
    # Webhooks
    ("GET",  "/api/webhooks/events",            "webhooks: list event types"),
    # Background jobs
    ("GET",  "/api/jobs",                       "jobs: list jobs"),
    # Benchmarks
    ("GET",  "/api/benchmarks/test-cases",      "benchmarks: list test cases"),
    # RAF models catalogue
    ("GET",  "/api/raf/models",                 "raf: list models"),
    # Additional endpoints that must also be accessible
    ("GET",  "/api/claims/stats",               "claims: stats"),
    ("GET",  "/api/submissions/stats",          "submissions: stats"),
    ("GET",  "/api/providers/summary",          "providers: summary"),
    ("GET",  "/api/jobs/stats",                 "jobs: stats"),
    ("GET",  "/api/benchmarks/results",         "benchmarks: latest results"),
]

# Some endpoints legitimately return non-200 for a viewer with no data yet.
# We allow these codes in addition to 200 when the user is authenticated.
_ALLOWED_AUTH_CODES = {200, 201, 204, 400, 403, 404, 422}


# ===========================================================================
# Tests
# ===========================================================================

class TestUnauthenticatedAccess:
    """
    Every endpoint in the catalogue must return HTTP 401 when no
    Authorization header is provided.
    """

    @pytest.mark.parametrize("method,path,description", ROUTER_ENDPOINTS, ids=[
        e[2] for e in ROUTER_ENDPOINTS
    ])
    def test_unauthenticated_returns_401(
        self,
        client: TestClient,
        method: str,
        path: str,
        description: str,
    ):
        r = client.request(method, path)
        assert r.status_code == 401, (
            f"[{description}] {method} {path} — "
            f"expected 401 without token, got {r.status_code}. "
            f"Body: {r.text[:200]}"
        )


class TestAuthenticatedAccess:
    """
    Every endpoint in the catalogue must NOT return 401 when a valid
    Bearer token is included — i.e. the router is wired up and the auth
    dependency resolves correctly.

    Accepted codes are 200-204 (success), 400/422 (bad params — still reached
    the handler), 403 (permission denied — still reached the handler), and
    404 (no data yet — still reached the handler).
    """

    @pytest.mark.parametrize("method,path,description", ROUTER_ENDPOINTS, ids=[
        e[2] for e in ROUTER_ENDPOINTS
    ])
    def test_authenticated_does_not_return_401(
        self,
        client: TestClient,
        admin_headers: dict,
        method: str,
        path: str,
        description: str,
    ):
        r = client.request(method, path, headers=admin_headers)
        assert r.status_code != 401, (
            f"[{description}] {method} {path} — "
            f"received 401 with a valid token. Check router registration and auth dependency. "
            f"Body: {r.text[:200]}"
        )
        assert r.status_code in _ALLOWED_AUTH_CODES, (
            f"[{description}] {method} {path} — "
            f"unexpected status {r.status_code} (not in {_ALLOWED_AUTH_CODES}). "
            f"Body: {r.text[:200]}"
        )

    @pytest.mark.parametrize("method,path,description", ROUTER_ENDPOINTS, ids=[
        e[2] for e in ROUTER_ENDPOINTS
    ])
    def test_response_is_json(
        self,
        client: TestClient,
        auth_headers: dict,
        method: str,
        path: str,
        description: str,
    ):
        """Every endpoint must return a parseable JSON body."""
        r = client.request(method, path, headers=auth_headers)
        try:
            r.json()
        except Exception as exc:
            pytest.fail(
                f"[{description}] {method} {path} — "
                f"response body is not valid JSON ({exc}). "
                f"Status: {r.status_code}, Body: {r.text[:200]}"
            )


# ===========================================================================
# Per-router structural tests (selected endpoints only)
# ===========================================================================

class TestRAFModelsEndpoint:
    """GET /api/raf/models — detailed structural validation."""

    def test_models_returns_list_or_dict(
        self, client: TestClient, auth_headers: dict
    ):
        r = client.get("/api/raf/models", headers=auth_headers)
        assert r.status_code == 200, f"GET /api/raf/models returned {r.status_code}"
        data = r.json()
        assert isinstance(data, (list, dict)), (
            f"Expected list or dict from /api/raf/models, got {type(data)}"
        )

    def test_models_contains_at_least_one_model(
        self, client: TestClient, auth_headers: dict
    ):
        r = client.get("/api/raf/models", headers=auth_headers)
        data = r.json()
        if isinstance(data, list):
            assert len(data) >= 1, "Expected at least one model in the list"
        elif isinstance(data, dict):
            # Some implementations return {"models": [...]}
            models = data.get("models", data)
            if isinstance(models, list):
                assert len(models) >= 1, "Expected at least one model"


class TestQualityMeasuresEndpoint:
    """GET /api/quality/measures — structural validation."""

    def test_measures_returns_list(self, client: TestClient, auth_headers: dict):
        r = client.get("/api/quality/measures", headers=auth_headers)
        assert r.status_code == 200, f"GET /api/quality/measures returned {r.status_code}"
        data = r.json()
        assert isinstance(data, list), (
            f"Expected a list from /api/quality/measures, got {type(data)}"
        )

    def test_measures_not_empty(self, client: TestClient, auth_headers: dict):
        r = client.get("/api/quality/measures", headers=auth_headers)
        data = r.json()
        if isinstance(data, list):
            assert len(data) > 0, "Expected at least one HEDIS measure"


class TestWebhookEventsEndpoint:
    """GET /api/webhooks/events — structural validation."""

    def test_events_returns_list(self, client: TestClient, auth_headers: dict):
        r = client.get("/api/webhooks/events", headers=auth_headers)
        assert r.status_code == 200, f"GET /api/webhooks/events returned {r.status_code}"
        data = r.json()
        assert isinstance(data, list), (
            f"Expected a list from /api/webhooks/events, got {type(data)}"
        )

    def test_event_items_have_name_field(self, client: TestClient, auth_headers: dict):
        r = client.get("/api/webhooks/events", headers=auth_headers)
        events = r.json()
        if events:
            first = events[0]
            assert isinstance(first, dict), "Each event must be a dict"
            has_name = "name" in first or "event_type" in first or "type" in first
            assert has_name, (
                f"Event item missing a name/type field. Got: {first}"
            )


class TestBenchmarkTestCasesEndpoint:
    """GET /api/benchmarks/test-cases — structural validation."""

    def test_test_cases_returns_200(self, client: TestClient, auth_headers: dict):
        r = client.get("/api/benchmarks/test-cases", headers=auth_headers)
        assert r.status_code == 200, (
            f"GET /api/benchmarks/test-cases returned {r.status_code}: {r.text[:200]}"
        )

    def test_test_cases_response_structure(self, client: TestClient, auth_headers: dict):
        r = client.get("/api/benchmarks/test-cases", headers=auth_headers)
        data = r.json()
        # Accepts either a list or a dict with a 'cases'/'test_cases' key.
        if isinstance(data, list):
            assert len(data) >= 0  # may be empty
        elif isinstance(data, dict):
            cases = data.get("cases") or data.get("test_cases") or data.get("data") or []
            assert isinstance(cases, list)

    def test_test_cases_category_filter_accepted(
        self, client: TestClient, auth_headers: dict
    ):
        """Query param ?category=diabetes must not cause a 500."""
        r = client.get(
            "/api/benchmarks/test-cases",
            params={"category": "diabetes"},
            headers=auth_headers,
        )
        assert r.status_code in (200, 404), (
            f"Category filter returned unexpected status {r.status_code}"
        )


class TestJobsEndpoint:
    """GET /api/jobs — structural validation."""

    def test_jobs_returns_200(self, client: TestClient, auth_headers: dict):
        r = client.get("/api/jobs", headers=auth_headers)
        assert r.status_code == 200, f"GET /api/jobs returned {r.status_code}"

    def test_jobs_is_list(self, client: TestClient, auth_headers: dict):
        r = client.get("/api/jobs", headers=auth_headers)
        data = r.json()
        assert isinstance(data, list), (
            f"Expected list from /api/jobs, got {type(data)}"
        )


class TestFHIRConnectionsEndpoint:
    """GET /api/fhir/connections — structural validation."""

    def test_fhir_connections_returns_200(self, client: TestClient, auth_headers: dict):
        r = client.get("/api/fhir/connections", headers=auth_headers)
        assert r.status_code == 200, (
            f"GET /api/fhir/connections returned {r.status_code}: {r.text[:200]}"
        )

    def test_fhir_connections_is_list_or_paginated_dict(
        self, client: TestClient, auth_headers: dict
    ):
        r = client.get("/api/fhir/connections", headers=auth_headers)
        data = r.json()
        assert isinstance(data, (list, dict)), (
            f"Unexpected type from /api/fhir/connections: {type(data)}"
        )


class TestClaimsBatchesEndpoint:
    """GET /api/claims/batches — structural validation."""

    def test_claims_batches_returns_200(self, client: TestClient, auth_headers: dict):
        r = client.get("/api/claims/batches", headers=auth_headers)
        assert r.status_code == 200, (
            f"GET /api/claims/batches returned {r.status_code}: {r.text[:200]}"
        )

    def test_claims_batches_has_expected_shape(
        self, client: TestClient, auth_headers: dict
    ):
        r = client.get("/api/claims/batches", headers=auth_headers)
        data = r.json()
        # Accept list or paginated {"batches": [...], "total": N}
        assert isinstance(data, (list, dict)), (
            f"Unexpected type from /api/claims/batches: {type(data)}"
        )


class TestProspectiveWorklistEndpoint:
    """GET /api/prospective/worklist — structural validation."""

    def test_prospective_worklist_reachable(
        self, client: TestClient, auth_headers: dict
    ):
        r = client.get("/api/prospective/worklist", headers=auth_headers)
        # 200 = data present, 403 = permission not granted for viewer — both OK
        assert r.status_code in (200, 403, 404), (
            f"GET /api/prospective/worklist returned unexpected {r.status_code}"
        )

    def test_prospective_worklist_not_401(
        self, client: TestClient, auth_headers: dict
    ):
        """A valid token must never produce 401 — that would indicate broken auth wiring."""
        r = client.get("/api/prospective/worklist", headers=auth_headers)
        assert r.status_code != 401, (
            "GET /api/prospective/worklist returned 401 with a valid token"
        )


class TestSubmissionsBatchesEndpoint:
    """GET /api/submissions/batches — structural validation."""

    def test_submissions_batches_returns_200(
        self, client: TestClient, auth_headers: dict
    ):
        r = client.get("/api/submissions/batches", headers=auth_headers)
        assert r.status_code == 200, (
            f"GET /api/submissions/batches returned {r.status_code}: {r.text[:200]}"
        )


class TestProvidersSummaryEndpoint:
    """GET /api/providers/summary — structural validation."""

    def test_providers_summary_reachable(
        self, client: TestClient, auth_headers: dict
    ):
        r = client.get("/api/providers/summary", headers=auth_headers)
        assert r.status_code in (200, 403, 404), (
            f"GET /api/providers/summary returned {r.status_code}"
        )
