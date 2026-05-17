"""
Unit tests for CDS Hooks dedup, card-cap, feedback endpoint, and hookInstance
rate-limit (fix/round2-cds-hooks-dedup).

All DB interactions are mocked — no live MySQL required.

Covers:
  1. Max 3 cards returned even when _fetch_open_suspects returns 10 rows.
  2. Suspect shown/dismissed within 24 h is suppressed (not returned as a card).
  3. Feedback endpoint updates row status and returns ok.
  4. hookInstance rate-limit blocks second invocation within 60 s.
"""
from __future__ import annotations

import os
import time
from contextlib import contextmanager
from unittest.mock import MagicMock, call, patch

import pytest

# Ensure env vars are set before app imports.
os.environ.setdefault("APP_ENV", "development")
os.environ.setdefault("JWT_SECRET", "test-jwt-secret-for-pytest-do-not-use-in-prod")
os.environ.setdefault("JWT_REFRESH_SECRET", "test-refresh-secret-for-pytest")
os.environ.setdefault("RAF_DB_USER", "test_user")
os.environ.setdefault("RAF_DB_PASSWORD", "test_password")
os.environ.setdefault("DB_SSL_ENABLED", "false")

CDS_SECRET = "test-cds-shared-secret-xxx"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_suspects(n: int) -> list[dict]:
    return [
        {
            "id": i + 1,
            "suspect_hcc": 100 + i,
            "suspect_icd10": f"E{i:02d}.9",
            "evidence_type": "rule",
            "confidence_score": 0.90 - i * 0.01,
        }
        for i in range(n)
    ]


@contextmanager
def _patch_cds(
    suspects: list[dict],
    recently_shown_ids: set[int] | None = None,
    record_shown_side_effect=None,
):
    """Patch all external collaborators for hcc-suggestions-realtime."""
    if recently_shown_ids is None:
        recently_shown_ids = set()

    with (
        patch("app.routers.cds_hooks._resolve_internal_pid", return_value=42),
        patch("app.routers.cds_hooks._patient_exists", return_value=True),
        patch("app.routers.cds_hooks._fetch_open_suspects", return_value=suspects),
        patch(
            "app.routers.cds_hooks._get_recently_shown_suspect_ids",
            return_value=recently_shown_ids,
        ),
        patch(
            "app.routers.cds_hooks._record_shown",
            side_effect=record_shown_side_effect,
        ),
        patch("app.routers.cds_hooks._emit_audit"),
        patch("app.routers.cds_hooks._emit_suppressed_dup_audit") as mock_sup,
    ):
        yield mock_sup


# ---------------------------------------------------------------------------
# Fixture: FastAPI TestClient
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def client():
    from fastapi.testclient import TestClient

    from app.main import app

    return TestClient(app)


@pytest.fixture(autouse=True)
def _set_cds_secret(monkeypatch):
    monkeypatch.setenv("CDS_HOOKS_SHARED_SECRET", CDS_SECRET)


@pytest.fixture(autouse=True)
def _reset_hook_instance_state():
    """Clear the in-memory hookInstance dedup cache between tests."""
    import app.routers.cds_hooks as mod

    mod._hook_instance_seen.clear()
    yield
    mod._hook_instance_seen.clear()


# ---------------------------------------------------------------------------
# Test 1: Max 3 cards returned even when _fetch_open_suspects returns 10 rows
# ---------------------------------------------------------------------------


def test_max_3_cards_returned_for_10_suspects(client):
    """Even if 10 suspects are open, at most 3 cards are returned."""
    suspects = _make_suspects(10)

    with _patch_cds(suspects, recently_shown_ids=set()):
        resp = client.post(
            "/cds-services/hcc-suggestions-realtime",
            json={
                "hook": "patient-view",
                "hookInstance": "inst-cap-test-001",
                "context": {"patientId": "42"},
            },
            headers={"Authorization": f"Bearer {CDS_SECRET}"},
        )

    assert resp.status_code == 200, resp.text
    cards = resp.json()["cards"]
    assert len(cards) <= 3, f"Expected at most 3 cards, got {len(cards)}"


# ---------------------------------------------------------------------------
# Test 2: Dismissed/shown suspects within 24 h are suppressed
# ---------------------------------------------------------------------------


def test_recently_shown_suspect_is_suppressed(client):
    """A suspect with shown/dismissed status in last 24 h must not appear as a card."""
    suspects = _make_suspects(3)
    # suspects[0].id == 1 — mark as recently shown
    recently_shown = {1}

    with _patch_cds(suspects, recently_shown_ids=recently_shown) as mock_sup:
        resp = client.post(
            "/cds-services/hcc-suggestions-realtime",
            json={
                "hook": "patient-view",
                "hookInstance": "inst-dedup-test-001",
                "context": {"patientId": "42"},
            },
            headers={"Authorization": f"Bearer {CDS_SECRET}"},
        )

    assert resp.status_code == 200, resp.text
    cards = resp.json()["cards"]
    # Only 2 of 3 suspects should appear (one suppressed).
    assert len(cards) == 2, f"Expected 2 cards after dedup, got {len(cards)}"
    # Suppressed-dup audit should have been emitted once.
    mock_sup.assert_called_once()
    call_kwargs = mock_sup.call_args.kwargs
    assert call_kwargs["suspect_id"] == 1


def test_all_suspects_suppressed_returns_empty_cards(client):
    """If all suspects are recently shown, return empty card list."""
    suspects = _make_suspects(2)
    recently_shown = {1, 2}

    with _patch_cds(suspects, recently_shown_ids=recently_shown):
        resp = client.post(
            "/cds-services/hcc-suggestions-realtime",
            json={
                "hook": "patient-view",
                "hookInstance": "inst-dedup-all-001",
                "context": {"patientId": "42"},
            },
            headers={"Authorization": f"Bearer {CDS_SECRET}"},
        )

    assert resp.status_code == 200, resp.text
    assert resp.json()["cards"] == []


# ---------------------------------------------------------------------------
# Test 3: Feedback endpoint updates row status
# ---------------------------------------------------------------------------


def test_feedback_endpoint_updates_status_accepted(client):
    """POST feedback with outcome=accepted should update status and return ok."""
    card_uuid = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
    fake_row = {"id": 99, "patient_id": 42, "suspect_id": 1}

    with patch(
        "app.routers.cds_hooks._update_feedback_status", return_value=fake_row
    ) as mock_update, patch(
        "app.routers.cds_hooks._emit_feedback_audit"
    ) as mock_audit:
        resp = client.post(
            "/cds-services/hcc-suggestions-realtime/feedback",
            json={
                "feedback": [
                    {
                        "card": card_uuid,
                        "outcome": "accepted",
                        "outcomeTimestamp": "2026-05-17T10:00:00Z",
                    }
                ]
            },
            headers={"Authorization": f"Bearer {CDS_SECRET}"},
        )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["processed"] == 1
    result = body["results"][0]
    assert result["status"] == "ok"
    assert result["outcome"] == "accepted"

    mock_update.assert_called_once_with(card_uuid, "accepted")
    mock_audit.assert_called_once()
    audit_kwargs = mock_audit.call_args.kwargs
    assert audit_kwargs["outcome"] == "accepted"
    assert audit_kwargs["card_uuid"] == card_uuid


def test_feedback_endpoint_returns_not_found_for_unknown_card(client):
    """Feedback for an unknown card uuid should return status not_found."""
    with patch(
        "app.routers.cds_hooks._update_feedback_status", return_value=None
    ):
        resp = client.post(
            "/cds-services/hcc-suggestions-realtime/feedback",
            json={
                "feedback": [
                    {
                        "card": "no-such-uuid",
                        "outcome": "overridden",
                    }
                ]
            },
            headers={"Authorization": f"Bearer {CDS_SECRET}"},
        )

    assert resp.status_code == 200, resp.text
    result = resp.json()["results"][0]
    assert result["status"] == "not_found"


def test_feedback_endpoint_requires_auth(client):
    """Feedback endpoint must reject requests without the shared secret."""
    resp = client.post(
        "/cds-services/hcc-suggestions-realtime/feedback",
        json={"feedback": []},
        headers={"Authorization": "Bearer wrong-secret"},
    )
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Test 4: hookInstance rate-limit blocks 2nd invocation within 60 s
# ---------------------------------------------------------------------------


def test_hook_instance_rate_limit_blocks_second_invocation(client):
    """A second call with the same hookInstance for the same patient within
    60 s must return 429."""
    suspects = _make_suspects(3)
    hook_inst = "inst-ratelimit-unique-001"

    with _patch_cds(suspects):
        first = client.post(
            "/cds-services/hcc-suggestions-realtime",
            json={
                "hook": "patient-view",
                "hookInstance": hook_inst,
                "context": {"patientId": "42"},
            },
            headers={"Authorization": f"Bearer {CDS_SECRET}"},
        )
        second = client.post(
            "/cds-services/hcc-suggestions-realtime",
            json={
                "hook": "patient-view",
                "hookInstance": hook_inst,
                "context": {"patientId": "42"},
            },
            headers={"Authorization": f"Bearer {CDS_SECRET}"},
        )

    assert first.status_code == 200, first.text
    assert second.status_code == 429, (
        f"Expected 429 on second hookInstance invocation, got {second.status_code}"
    )


def test_hook_instance_allows_new_instance(client):
    """A different hookInstance UUID for the same patient must be allowed."""
    suspects = _make_suspects(2)

    with _patch_cds(suspects):
        r1 = client.post(
            "/cds-services/hcc-suggestions-realtime",
            json={
                "hook": "patient-view",
                "hookInstance": "inst-new-a",
                "context": {"patientId": "42"},
            },
            headers={"Authorization": f"Bearer {CDS_SECRET}"},
        )
        r2 = client.post(
            "/cds-services/hcc-suggestions-realtime",
            json={
                "hook": "patient-view",
                "hookInstance": "inst-new-b",
                "context": {"patientId": "42"},
            },
            headers={"Authorization": f"Bearer {CDS_SECRET}"},
        )

    assert r1.status_code == 200, r1.text
    assert r2.status_code == 200, r2.text


# ---------------------------------------------------------------------------
# Test 5: Discovery endpoint still works (no regression)
# ---------------------------------------------------------------------------


def test_cds_discovery_still_lists_both_services(client):
    r = client.get("/cds-services")
    assert r.status_code == 200
    ids = {svc["id"] for svc in r.json()["services"]}
    assert "raf-suspects" in ids
    assert "hcc-suggestions-realtime" in ids
