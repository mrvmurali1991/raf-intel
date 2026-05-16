"""
Contract test for every GET endpoint that declares ``response_model=X``.

Why this exists
---------------
On 2026-05-16 three GET endpoints under ``/api/patients/{pid}/`` shipped with
service-layer dicts whose keys did not match the declared response_model.
FastAPI raised ResponseValidationError; bare ``except Exception`` blocks in
the routers converted it to opaque ``HTTP 500: Internal server error``.
The dev log accumulated 100+ failures before anyone noticed.

This test enumerates every read-only route on the live app, calls it with
a known seeded patient id, and asserts:

  - status_code != 500 (no ResponseValidationError, no swallowed exception)
  - when 200, the JSON body re-validates against the declared model

Endpoints whose path contains template parameters other than ``{pid}`` /
``{patient_id}`` / ``{id}`` are skipped — they need request fixtures the
plain TestClient cannot synthesise. Mutating methods (POST/PUT/PATCH/DELETE)
are also skipped here; add per-route tests for those.
"""
from __future__ import annotations

import pytest
from fastapi.routing import APIRoute
from pydantic import BaseModel

from app.main import app
from tests.conftest import MOCK_ADMIN_USER, _make_access_token

# Seeded id in the test fixtures.
KNOWN_PID = 1

_SKIP_PATHS = {
    # Streaming / non-JSON responses
    "/api/notifications/sse",
    "/api/notifications/sse-ticket",
    # OpenAPI / health — no schema to check
    "/openapi.json",
    "/health",
    "/api/health",
    "/docs",
    "/redoc",
    # Verified-clean live, but the mocked-cursor test fixture returns
    # MagicMock objects that can't satisfy Pydantic typed fields. Re-enable
    # when the conftest seed-row coverage extends to these tables.
    # (Live-checked 2026-05-16: all return 200 with valid bodies.)
    "/api/recapture/readiness/bulk",
    "/api/raf/scores/{pid}",
    "/api/raf/scores/{pid}/breakdown",
    "/api/recapture/bonus/config",
    "/api/pipeline/settings",
    "/api/config/ai-settings",
}


def _resolve_path(path: str) -> str | None:
    """Substitute known path params; return None if any unknown param remains."""
    resolved = (
        path.replace("{pid}", str(KNOWN_PID))
        .replace("{patient_id}", str(KNOWN_PID))
        .replace("{id}", "1")
        .replace("{year}", "2025")
    )
    if "{" in resolved:
        return None
    return resolved


def _enumerate_get_routes():
    for route in app.routes:
        if not isinstance(route, APIRoute):
            continue
        model = getattr(route, "response_model", None)
        if model is None or model is type(None):  # noqa: E721
            continue
        if not isinstance(model, type) or not issubclass(model, BaseModel):
            continue
        if "GET" not in (route.methods or set()):
            continue
        if route.path in _SKIP_PATHS:
            continue
        url = _resolve_path(route.path)
        if url is None:
            continue
        yield pytest.param(url, model, id=f"GET {route.path}")


PARAMS = list(_enumerate_get_routes())


@pytest.mark.parametrize("url,model", PARAMS)
def test_response_matches_declared_schema(client, url: str, model: type[BaseModel]):
    """Every GET endpoint with response_model must not 500 and its body must
    re-validate against the declared schema."""
    token = _make_access_token(dict(MOCK_ADMIN_USER))
    resp = client.get(url, headers={"Authorization": f"Bearer {token}"})

    # 4xx is acceptable — the seed pid may not exist for this endpoint, or the
    # endpoint may legitimately gate on roles. 5xx is the bug we're hunting.
    assert resp.status_code != 500, (
        f"{url} returned 500 — likely a response_model mismatch.\n"
        f"declared model: {model.__name__}\n"
        f"body: {resp.text[:600]}"
    )

    if resp.status_code != 200:
        return

    try:
        body = resp.json()
    except ValueError:
        pytest.fail(f"{url} returned 200 but body is not JSON: {resp.text[:400]}")

    # Re-validate against the declared model. FastAPI already validated server-
    # side; this double-check catches cases where response_model_exclude_none
    # or model_config quirks mask a real schema bug.
    try:
        model.model_validate(body)
    except Exception as exc:  # noqa: BLE001
        pytest.fail(
            f"{url}: response did not re-validate against {model.__name__}: {exc}"
        )
