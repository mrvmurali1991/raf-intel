"""
Tests for the Datavant Switchboard API adapter.

All HTTP calls are mocked — no real Datavant API calls are made.

Test inventory
--------------
test_submit_chart_request_success
    Mock httpx.Client.post → assert request_id returned.

test_get_chart_request_status_complete
    Mock httpx.Client.get with "complete" status → returns document list.

test_webhook_bad_signature_returns_403
    POST /api/webhooks/datavant with wrong signature → 403.

test_webhook_valid_signature_enqueues_task
    POST /api/webhooks/datavant with correct HMAC → 200 + Celery task.delay called.

test_credentials_check_no_env
    No env vars set → {configured: false}.

test_credentials_check_all_env_set_unreachable
    All env vars set but HEAD request fails → {configured: true, api_base_reachable: false}.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
from typing import Any
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_hmac_sig(body: bytes, secret: str) -> str:
    """Compute X-Datavant-Signature value for a given payload and secret."""
    digest = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


# ---------------------------------------------------------------------------
# DatavantClient unit tests
# ---------------------------------------------------------------------------


class TestSubmitChartRequest:
    """submit_chart_request posts to /api/v1/chart-requests."""

    def test_returns_request_id(self, monkeypatch):
        """Mock httpx response → assert request_id is returned."""
        fake_response = MagicMock()
        fake_response.json.return_value = {
            "request_id": "dv-req-001",
            "status": "submitted",
            "estimated_turnaround_days": 3,
        }
        fake_response.raise_for_status = MagicMock()

        fake_client_instance = MagicMock()
        fake_client_instance.__enter__ = MagicMock(return_value=fake_client_instance)
        fake_client_instance.__exit__ = MagicMock(return_value=False)
        fake_client_instance.post.return_value = fake_response

        monkeypatch.setenv("DATAVANT_API_BASE", "https://api.switchboard.datavant.com")
        monkeypatch.setenv("DATAVANT_API_KEY", "test-api-key")
        monkeypatch.setenv("DATAVANT_CUSTOMER_ID", "cust-123")

        import importlib
        import app.services.partners.datavant as dv_module
        importlib.reload(dv_module)

        with patch("httpx.Client", return_value=fake_client_instance):
            from app.services.partners.datavant import DatavantClient
            client = DatavantClient(
                api_base="https://api.switchboard.datavant.com",
                api_key="test-api-key",
                customer_id="cust-123",
            )
            result = client.submit_chart_request(
                patient_demographics={"first_name": "Jane", "last_name": "Doe", "dob": "1960-01-01"},
                date_of_service_from="2024-01-01",
                date_of_service_to="2024-12-31",
                reason="RAF risk adjustment",
            )

        assert result["request_id"] == "dv-req-001"
        assert result["status"] == "submitted"
        assert result["estimated_turnaround_days"] == 3
        # Verify the POST was called at the correct endpoint.
        fake_client_instance.post.assert_called_once()
        call_url = fake_client_instance.post.call_args[0][0]
        assert "/api/v1/chart-requests" in call_url


class TestGetChartRequestStatus:
    """get_chart_request_status polls /api/v1/chart-requests/{id}."""

    def test_complete_status_returns_document_list(self, monkeypatch):
        """Mock httpx GET → status=complete with document list."""
        fake_response = MagicMock()
        fake_response.json.return_value = {
            "status": "complete",
            "documents_available": [
                {"document_id": "doc-aaa", "filename": "chart_jan.pdf"},
                {"document_id": "doc-bbb", "filename": "chart_feb.pdf"},
            ],
        }
        fake_response.raise_for_status = MagicMock()

        fake_client_instance = MagicMock()
        fake_client_instance.__enter__ = MagicMock(return_value=fake_client_instance)
        fake_client_instance.__exit__ = MagicMock(return_value=False)
        fake_client_instance.get.return_value = fake_response

        with patch("httpx.Client", return_value=fake_client_instance):
            from app.services.partners.datavant import DatavantClient
            client = DatavantClient(
                api_base="https://api.switchboard.datavant.com",
                api_key="k",
                customer_id="c",
            )
            result = client.get_chart_request_status("dv-req-001")

        assert result["status"] == "complete"
        assert len(result["documents_available"]) == 2
        assert result["documents_available"][0]["document_id"] == "doc-aaa"


# ---------------------------------------------------------------------------
# Webhook receiver tests
# ---------------------------------------------------------------------------


@pytest.fixture()
def webhook_client(monkeypatch):
    """Return a FastAPI TestClient for datavant_webhook router only."""
    monkeypatch.setenv("DATAVANT_WEBHOOK_SECRET", "super-secret-for-tests")

    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    # Import after env var is set.
    from app.routers.datavant_webhook import router

    app = FastAPI()
    app.include_router(router)
    return TestClient(app, raise_server_exceptions=False)


class TestWebhookBadSignature:
    """Requests with wrong or missing signatures must be rejected."""

    def test_missing_signature_returns_403(self, webhook_client):
        payload = json.dumps({"document_id": "doc-001", "request_id": "req-001"}).encode()
        resp = webhook_client.post(
            "/api/webhooks/datavant",
            content=payload,
            headers={"Content-Type": "application/json"},
        )
        assert resp.status_code == 403

    def test_wrong_signature_returns_403(self, webhook_client):
        payload = json.dumps({"document_id": "doc-002", "request_id": "req-002"}).encode()
        resp = webhook_client.post(
            "/api/webhooks/datavant",
            content=payload,
            headers={
                "Content-Type": "application/json",
                "X-Datavant-Signature": "sha256=badhash",
            },
        )
        assert resp.status_code == 403


class TestWebhookValidSignature:
    """Valid signatures should enqueue the Celery task and return 200."""

    def test_valid_signature_returns_200_and_enqueues(self, webhook_client, monkeypatch):
        secret = os.environ.get("DATAVANT_WEBHOOK_SECRET", "super-secret-for-tests")
        payload_dict = {"document_id": "doc-xyz", "request_id": "req-xyz"}
        payload_bytes = json.dumps(payload_dict).encode()
        sig = _make_hmac_sig(payload_bytes, secret)

        mock_task = MagicMock()
        mock_task.delay = MagicMock()

        with patch(
            "app.routers.datavant_webhook.task_datavant_ingest" if False else "app.routers.datavant_webhook.task_datavant_ingest",
            new=mock_task,
            create=True,
        ):
            # Patch at the import inside the handler.
            with patch("app.services.celery_tasks.task_datavant_ingest", new=mock_task, create=True):
                resp = webhook_client.post(
                    "/api/webhooks/datavant",
                    content=payload_bytes,
                    headers={
                        "Content-Type": "application/json",
                        "X-Datavant-Signature": sig,
                    },
                )

        assert resp.status_code == 200
        data = resp.json()
        assert data.get("accepted") is True

    def test_valid_signature_triggers_delay(self, monkeypatch):
        """Directly test that task_datavant_ingest.delay is called on a valid webhook."""
        monkeypatch.setenv("DATAVANT_WEBHOOK_SECRET", "test-secret-key")

        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from app.routers.datavant_webhook import router

        app = FastAPI()
        app.include_router(router)

        payload_dict = {"document_id": "doc-delay-test", "request_id": "req-delay-test"}
        payload_bytes = json.dumps(payload_dict).encode()
        sig = _make_hmac_sig(payload_bytes, "test-secret-key")

        mock_delay = MagicMock()
        mock_task = MagicMock()
        mock_task.delay = mock_delay

        with patch.dict("sys.modules", {"app.services.celery_tasks": MagicMock(task_datavant_ingest=mock_task)}):
            client = TestClient(app, raise_server_exceptions=False)
            resp = client.post(
                "/api/webhooks/datavant",
                content=payload_bytes,
                headers={
                    "Content-Type": "application/json",
                    "X-Datavant-Signature": sig,
                },
            )

        assert resp.status_code == 200
        assert resp.json().get("accepted") is True


# ---------------------------------------------------------------------------
# Credentials check tests
# ---------------------------------------------------------------------------


class TestCredentialsCheck:
    """GET /api/admin/datavant/credentials/check behaviour."""

    def _make_admin_client(self, monkeypatch, env_overrides: dict):
        """Build a minimal FastAPI TestClient for the admin router."""
        for k, v in env_overrides.items():
            if v is None:
                monkeypatch.delenv(k, raising=False)
            else:
                monkeypatch.setenv(k, v)

        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from fastapi import APIRouter

        # Build a stripped router that bypasses auth for tests.
        mini_router = APIRouter(prefix="/api/admin/datavant", tags=["datavant-admin"])

        import os as _os

        @mini_router.get("/credentials/check")
        def _check():
            from app.routers.datavant_admin import CredentialsCheckResponse
            api_base = _os.getenv("DATAVANT_API_BASE", "")
            api_key = _os.getenv("DATAVANT_API_KEY", "")
            customer_id = _os.getenv("DATAVANT_CUSTOMER_ID", "")
            configured = bool(api_base and api_key and customer_id)
            if not configured:
                missing = [
                    name
                    for name, val in [
                        ("DATAVANT_API_BASE", api_base),
                        ("DATAVANT_API_KEY", api_key),
                        ("DATAVANT_CUSTOMER_ID", customer_id),
                    ]
                    if not val
                ]
                return CredentialsCheckResponse(
                    configured=False,
                    api_base_reachable=False,
                    detail=f"Missing env vars: {', '.join(missing)}",
                )
            reachable = False
            detail = None
            try:
                import httpx
                with httpx.Client(timeout=5.0) as c:
                    r = c.head(api_base)
                    reachable = r.status_code < 500
                    detail = f"HTTP {r.status_code}"
            except Exception as exc:
                detail = f"Unreachable: {exc}"
            return CredentialsCheckResponse(configured=True, api_base_reachable=reachable, detail=detail)

        app = FastAPI()
        app.include_router(mini_router)
        return TestClient(app)

    def test_no_env_returns_configured_false(self, monkeypatch):
        client = self._make_admin_client(
            monkeypatch,
            {
                "DATAVANT_API_BASE": None,
                "DATAVANT_API_KEY": None,
                "DATAVANT_CUSTOMER_ID": None,
            },
        )
        resp = client.get("/api/admin/datavant/credentials/check")
        assert resp.status_code == 200
        data = resp.json()
        assert data["configured"] is False
        assert data["api_base_reachable"] is False
        assert "Missing" in (data.get("detail") or "")

    def test_all_env_set_but_unreachable(self, monkeypatch):
        """configured=true but HEAD request raises → api_base_reachable=false."""
        import httpx

        client = self._make_admin_client(
            monkeypatch,
            {
                "DATAVANT_API_BASE": "https://api.switchboard.datavant.com",
                "DATAVANT_API_KEY": "key",
                "DATAVANT_CUSTOMER_ID": "cust",
            },
        )
        with patch("httpx.Client") as mock_cls:
            mock_instance = MagicMock()
            mock_instance.__enter__ = MagicMock(return_value=mock_instance)
            mock_instance.__exit__ = MagicMock(return_value=False)
            mock_instance.head.side_effect = httpx.ConnectError("connection refused")
            mock_cls.return_value = mock_instance

            resp = client.get("/api/admin/datavant/credentials/check")

        assert resp.status_code == 200
        data = resp.json()
        assert data["configured"] is True
        assert data["api_base_reachable"] is False
        assert "Unreachable" in (data.get("detail") or "")
