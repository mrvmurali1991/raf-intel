"""
Tests for the OpenEMR embed-token handshake.

Covers both layers:

  Service layer (`auth_service.create_embed_token` / `authenticate_embed_token`)
    - roundtrip with a mocked user
    - expired token rejected
    - tampered signature rejected
    - non-embed `type` claim rejected
    - tenant-id mismatch rejected

  Route layer (`POST /api/auth/embed/exchange` and `/embed/mint`)
    - 200 with access_token + user on a valid token
    - 401 on invalid signature
    - /embed/mint requires admin
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import jwt
import pytest
from app.config import settings
from app.services import auth_service

from tests.conftest import MOCK_ADMIN_USER, MOCK_VIEWER_USER

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mint_with(secret: str, payload_overrides: dict | None = None) -> str:
    """Build an embed-shaped JWT signed with the given secret."""
    now = datetime.now(timezone.utc)
    payload = {
        "sub": MOCK_ADMIN_USER["email"],
        "pid": 12345,
        "iat": now,
        "exp": now + timedelta(minutes=5),
        "type": "embed",
    }
    if payload_overrides:
        payload.update(payload_overrides)
    return jwt.encode(payload, secret, algorithm=settings.jwt_algorithm)


@pytest.fixture(autouse=True)
def _patch_embed_db():
    """Stub out DB calls inside authenticate_embed_token.

    `authenticate_embed_token` does:
      - _ensure_tables() → best-effort, already try/except
      - get_user_by_email → autouse-patched in conftest._patch_auth_resolution
      - raf_cursor().execute(INSERT INTO user_sessions ...) → noop cursor
    """
    from tests.conftest import make_cursor_cm

    noop_cm, _ = make_cursor_cm()
    with patch("app.services.auth_service.raf_cursor", noop_cm):
        yield


# ---------------------------------------------------------------------------
# Service-layer roundtrip
# ---------------------------------------------------------------------------


def test_create_and_authenticate_embed_token_roundtrip():
    token = auth_service.create_embed_token(
        user_email=MOCK_ADMIN_USER["email"],
        pid=12345,
        tenant_id=str(MOCK_ADMIN_USER["tenant_id"]),
        ttl_seconds=300,
    )
    result = auth_service.authenticate_embed_token(
        embed_token=token,
        ip_address="127.0.0.1",
        user_agent="pytest",
    )
    assert result["access_token"]
    assert result["refresh_token"]
    assert result["user"]["email"] == MOCK_ADMIN_USER["email"]
    assert result["embed_pid"] == 12345
    assert result["expires_in"] == settings.embed_access_token_expire_minutes * 60


def test_authenticate_embed_token_emits_embed_claim_in_access():
    token = auth_service.create_embed_token(
        user_email=MOCK_ADMIN_USER["email"],
        pid=99,
        tenant_id=str(MOCK_ADMIN_USER["tenant_id"]),
    )
    result = auth_service.authenticate_embed_token(
        embed_token=token, ip_address="1.1.1.1", user_agent="ua"
    )
    decoded = jwt.decode(
        result["access_token"],
        settings.jwt_secret,
        algorithms=[settings.jwt_algorithm],
    )
    assert decoded["embed"] is True
    assert decoded["embed_pid"] == 99
    assert decoded["type"] == "access"
    assert decoded["email"] == MOCK_ADMIN_USER["email"]


# ---------------------------------------------------------------------------
# Rejection paths
# ---------------------------------------------------------------------------


def test_expired_embed_token_rejected():
    now = datetime.now(timezone.utc)
    expired = jwt.encode(
        {
            "sub": MOCK_ADMIN_USER["email"],
            "pid": 1,
            "iat": now - timedelta(minutes=30),
            "exp": now - timedelta(minutes=5),
            "type": "embed",
        },
        auth_service._embed_signing_secret(),
        algorithm=settings.jwt_algorithm,
    )
    with pytest.raises(ValueError, match="expired"):
        auth_service.authenticate_embed_token(embed_token=expired)


def test_tampered_signature_rejected():
    bogus = _mint_with("completely-wrong-secret")
    with pytest.raises(ValueError, match="Invalid embed token"):
        auth_service.authenticate_embed_token(embed_token=bogus)


def test_non_embed_type_rejected():
    good_secret = auth_service._embed_signing_secret()
    not_embed = _mint_with(good_secret, {"type": "access"})
    with pytest.raises(ValueError, match="not an embed token"):
        auth_service.authenticate_embed_token(embed_token=not_embed)


def test_missing_sub_rejected():
    good_secret = auth_service._embed_signing_secret()
    no_sub = _mint_with(good_secret, {"sub": ""})
    with pytest.raises(ValueError, match="missing sub"):
        auth_service.authenticate_embed_token(embed_token=no_sub)


def test_unknown_user_rejected():
    token = auth_service.create_embed_token(
        user_email="not-a-real-user@example.com",
        pid=1,
        tenant_id=None,
    )
    with pytest.raises(ValueError, match="unknown or inactive user"):
        auth_service.authenticate_embed_token(embed_token=token)


def test_tenant_mismatch_rejected():
    """token.tenant_id != user.tenant_id must be rejected."""
    token = auth_service.create_embed_token(
        user_email=MOCK_ADMIN_USER["email"],
        pid=1,
        tenant_id="some-other-tenant",
    )
    with pytest.raises(ValueError, match="does not match"):
        auth_service.authenticate_embed_token(embed_token=token)


# ---------------------------------------------------------------------------
# Route: POST /api/auth/embed/exchange
# ---------------------------------------------------------------------------


def test_embed_exchange_endpoint_success(client):
    token = auth_service.create_embed_token(
        user_email=MOCK_ADMIN_USER["email"],
        pid=54321,
        tenant_id=str(MOCK_ADMIN_USER["tenant_id"]),
    )
    resp = client.post(
        "/api/auth/embed/exchange",
        json={"embed_token": token},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["access_token"]
    assert body["user"]["email"] == MOCK_ADMIN_USER["email"]
    assert body["embed_pid"] == 54321
    # refresh_token must NOT be in the JSON (it's set as an httpOnly cookie)
    assert "refresh_token" not in body
    # Refresh cookie is set
    assert any(
        c.name == "raf_refresh_token" for c in resp.cookies.jar
    ), "refresh cookie missing"


def test_embed_exchange_endpoint_invalid_signature(client):
    bogus = _mint_with("completely-wrong-secret")
    resp = client.post(
        "/api/auth/embed/exchange",
        json={"embed_token": bogus},
    )
    assert resp.status_code == 401
    assert "Invalid embed token" in resp.json()["detail"]


def test_embed_exchange_endpoint_expired(client):
    now = datetime.now(timezone.utc)
    expired = jwt.encode(
        {
            "sub": MOCK_ADMIN_USER["email"],
            "pid": 1,
            "iat": now - timedelta(minutes=30),
            "exp": now - timedelta(minutes=5),
            "type": "embed",
        },
        auth_service._embed_signing_secret(),
        algorithm=settings.jwt_algorithm,
    )
    resp = client.post(
        "/api/auth/embed/exchange",
        json={"embed_token": expired},
    )
    assert resp.status_code == 401
    assert "expired" in resp.json()["detail"].lower()


def test_embed_exchange_requires_body(client):
    resp = client.post("/api/auth/embed/exchange", json={})
    assert resp.status_code == 422  # Pydantic validation error


# ---------------------------------------------------------------------------
# Route: POST /api/auth/embed/mint  (admin/developer only)
# ---------------------------------------------------------------------------


def test_embed_mint_requires_admin(client, viewer_headers):
    resp = client.post(
        "/api/auth/embed/mint",
        headers=viewer_headers,
        json={"user_email": MOCK_VIEWER_USER["email"], "pid": 1},
    )
    assert resp.status_code == 403


def test_embed_mint_returns_token_for_admin(client, admin_headers):
    resp = client.post(
        "/api/auth/embed/mint",
        headers=admin_headers,
        json={
            "user_email": MOCK_ADMIN_USER["email"],
            "pid": 77,
            "tenant_id": str(MOCK_ADMIN_USER["tenant_id"]),
            "ttl_seconds": 300,
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["embed_token"]
    assert body["expires_in"] == 300
    assert "/embed/raf-central/77?t=" in body["iframe_url"]

    # And the minted token must verify cleanly
    decoded = jwt.decode(
        body["embed_token"],
        auth_service._embed_signing_secret(),
        algorithms=[settings.jwt_algorithm],
    )
    assert decoded["type"] == "embed"
    assert decoded["pid"] == 77
    assert decoded["tenant_id"] == str(MOCK_ADMIN_USER["tenant_id"])
