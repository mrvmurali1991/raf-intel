"""
Tests for POST /api/suspects/{suspect_id}/feedback.

Covers:
  - 201 happy path (helpful / incorrect / irrelevant)
  - 409 duplicate same user+suspect same day
  - 422 invalid sentiment value
  - 401 unauthenticated (no token)

All DB calls are mocked — no database connection required.
"""

from __future__ import annotations

from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from tests.conftest import (
    MOCK_ADMIN_USER,
    _make_access_token,
    make_cursor_cm,
)

# ---------------------------------------------------------------------------
# App fixture
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def client():
    from app.main import app
    return TestClient(app, raise_server_exceptions=True)


# ---------------------------------------------------------------------------
# Auth helpers
# ---------------------------------------------------------------------------


def _auth_headers(user: dict) -> dict[str, str]:
    token = _make_access_token(user)
    return {"Authorization": f"Bearer {token}"}


@contextmanager
def _auth_patch(user: dict):
    session_row = {"session_id": user["session_id"], "is_revoked": 0}
    with (
        patch("app.auth.get_user", return_value=user),
        patch("app.auth.validate_session", return_value=session_row),
    ):
        yield


# ---------------------------------------------------------------------------
# Happy-path tests
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("sentiment", ["helpful", "incorrect", "irrelevant"])
def test_submit_feedback_201(client, sentiment) -> None:
    """201 returned for each valid sentiment value."""
    # no duplicate row → fetchone returns None; INSERT returns id=42
    cur_cm, _ = make_cursor_cm(rows=[], lastrowid=42)

    with (
        _auth_patch(MOCK_ADMIN_USER),
        patch("app.routers.suspect_feedback.raf_cursor", cur_cm),
    ):
        resp = client.post(
            "/api/suspects/suspect-abc-123/feedback",
            json={"sentiment": sentiment, "comment": "looks right"},
            headers=_auth_headers(MOCK_ADMIN_USER),
        )

    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data["id"] == 42


def test_submit_feedback_no_comment(client) -> None:
    """comment is optional — omitting it still returns 201."""
    cur_cm, _ = make_cursor_cm(rows=[], lastrowid=7)

    with (
        _auth_patch(MOCK_ADMIN_USER),
        patch("app.routers.suspect_feedback.raf_cursor", cur_cm),
    ):
        resp = client.post(
            "/api/suspects/suspect-xyz/feedback",
            json={"sentiment": "helpful"},
            headers=_auth_headers(MOCK_ADMIN_USER),
        )

    assert resp.status_code == 201
    assert resp.json()["id"] == 7


# ---------------------------------------------------------------------------
# 409 duplicate
# ---------------------------------------------------------------------------


def test_submit_feedback_409_duplicate(client) -> None:
    """409 when user already submitted feedback for this suspect today."""
    # fetchone returns an existing row → duplicate detected
    existing_row = {"id": 5}
    cur_cm, _ = make_cursor_cm(rows=[existing_row], lastrowid=0)

    with (
        _auth_patch(MOCK_ADMIN_USER),
        patch("app.routers.suspect_feedback.raf_cursor", cur_cm),
    ):
        resp = client.post(
            "/api/suspects/suspect-dup/feedback",
            json={"sentiment": "incorrect"},
            headers=_auth_headers(MOCK_ADMIN_USER),
        )

    assert resp.status_code == 409
    assert "already submitted" in resp.json()["detail"].lower()


# ---------------------------------------------------------------------------
# 422 invalid sentiment
# ---------------------------------------------------------------------------


def test_submit_feedback_422_invalid_sentiment(client) -> None:
    """422 for a sentiment value that is not in the allowed enum."""
    with _auth_patch(MOCK_ADMIN_USER):
        resp = client.post(
            "/api/suspects/suspect-abc/feedback",
            json={"sentiment": "dunno"},
            headers=_auth_headers(MOCK_ADMIN_USER),
        )

    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# 401 unauthenticated
# ---------------------------------------------------------------------------


def test_submit_feedback_401_unauthenticated(client) -> None:
    """401 when no Authorization header is provided."""
    resp = client.post(
        "/api/suspects/suspect-abc/feedback",
        json={"sentiment": "helpful"},
    )
    assert resp.status_code == 401
