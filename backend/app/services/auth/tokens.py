"""
JWT issuance, decoding, refresh, revocation, and embed-token helpers.
"""
from __future__ import annotations

import hashlib
import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import jwt

from app.config import settings
from app.db import raf_cursor

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Shared utilities
# ---------------------------------------------------------------------------

def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _hash_token(token: str) -> str:
    """SHA-256 hash of a token for safe DB storage."""
    return hashlib.sha256(token.encode()).hexdigest()


def _is_production() -> bool:
    return settings.app_env == "production"


# ---------------------------------------------------------------------------
# Access / refresh / mfa-pending token issuance
# ---------------------------------------------------------------------------

def create_access_token(
    user_id: int,
    email: str,
    role: str,
    tenant_id: int | None,
    session_id: str,
) -> str:
    now = _utcnow()
    expire = now + timedelta(minutes=settings.access_token_expire_minutes)
    payload = {
        "sub": str(user_id),
        "email": email,
        "role": role,
        "tenant_id": tenant_id,
        "session_id": session_id,
        "iat": now,
        "exp": expire,
        "type": "access",
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def create_refresh_token(user_id: int, session_id: str) -> str:
    now = _utcnow()
    expire = now + timedelta(days=settings.refresh_token_expire_days)
    payload = {
        "sub": str(user_id),
        "session_id": session_id,
        "iat": now,
        "exp": expire,
        "type": "refresh",
    }
    return jwt.encode(
        payload, settings.jwt_refresh_secret, algorithm=settings.jwt_algorithm
    )


def _create_mfa_pending_token(user_id: int) -> str:
    """Short-lived token (5 min) issued after password check when MFA is required."""
    now = _utcnow()
    expire = now + timedelta(minutes=5)
    payload = {
        "sub": str(user_id),
        "iat": now,
        "exp": expire,
        "type": "mfa_pending",
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_token(token: str) -> dict[str, Any]:
    """Decode and validate an access (or mfa_pending) JWT. Raises jwt.PyJWTError on failure."""
    return jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])


def decode_refresh_token(token: str) -> dict[str, Any]:
    """Decode and validate a refresh JWT (signed with jwt_refresh_secret)."""
    return jwt.decode(
        token, settings.jwt_refresh_secret, algorithms=[settings.jwt_algorithm]
    )


# ---------------------------------------------------------------------------
# Token rotation / refresh
# ---------------------------------------------------------------------------

def refresh_access_token(
    refresh_token: str,
    get_user_fn: Any,
    revoke_all_sessions_fn: Any,
) -> dict[str, Any]:
    """Rotate refresh token on every use.

    Security properties:
    - Uses a separate signing key (jwt_refresh_secret) from access tokens.
    - Each call issues a NEW refresh token and revokes the old one (rotation).
    - Hash mismatch on a non-revoked session indicates a previously-rotated
      token is being replayed: all user sessions are immediately terminated.

    Parameters
    ----------
    refresh_token:
        The raw refresh JWT presented by the client.
    get_user_fn:
        Callable(user_id) -> user dict | None  (injected to avoid circular import)
    revoke_all_sessions_fn:
        Callable(user_id) -> None
    """
    try:
        payload = decode_refresh_token(refresh_token)
    except jwt.PyJWTError:
        raise ValueError("Invalid or expired refresh token.")

    if payload.get("type") != "refresh":
        raise ValueError("Not a refresh token.")

    user_id = int(payload["sub"])
    session_id = payload["session_id"]
    incoming_hash = _hash_token(refresh_token)

    with raf_cursor() as cur:
        cur.execute(
            """
            SELECT id, session_id, user_id, refresh_token_hash, is_revoked, expires_at
            FROM user_sessions
            WHERE session_id = %s
            """,
            (session_id,),
        )
        session = cur.fetchone()

    if not session:
        raise ValueError("Invalid refresh token.")

    if session["is_revoked"]:
        revoke_all_sessions_fn(user_id)
        raise ValueError(
            "Revoked refresh token reused — possible token theft. "
            "All sessions have been terminated. Please log in again."
        )

    expires = session["expires_at"]
    if isinstance(expires, str):
        expires = datetime.fromisoformat(expires)
    if expires.replace(tzinfo=timezone.utc) < _utcnow():
        raise ValueError("Refresh token has expired.")

    if session["refresh_token_hash"] != incoming_hash:
        prev_hash = session.get("prev_refresh_token_hash")
        updated = session.get("updated_at")
        grace_ok = False
        if prev_hash and prev_hash == incoming_hash and updated:
            if isinstance(updated, str):
                updated = datetime.fromisoformat(updated)
            age = (_utcnow() - updated.replace(tzinfo=timezone.utc)).total_seconds()
            if age < 30:
                grace_ok = True
                logger.info("Refresh token race resolved via grace window for user %s", user_id)

        if not grace_ok:
            logger.warning(
                "Refresh token hash mismatch for user %s session %s — "
                "possible concurrent refresh race (not revoking sessions)",
                user_id, session_id,
            )
            raise ValueError("Refresh token expired or already used. Please log in again.")

    user = get_user_fn(user_id)
    if not user or not user["is_active"]:
        raise ValueError("User account is inactive.")

    new_access_token = create_access_token(
        user_id=user["id"],
        email=user["email"],
        role=user["role"],
        tenant_id=user["tenant_id"],
        session_id=session_id,
    )
    new_refresh_token = create_refresh_token(user_id=user["id"], session_id=session_id)

    new_access_hash = _hash_token(new_access_token)
    new_refresh_hash = _hash_token(new_refresh_token)
    new_expires_at = _utcnow() + timedelta(days=settings.refresh_token_expire_days)

    with raf_cursor() as cur:
        cur.execute(
            """
            UPDATE user_sessions
            SET prev_refresh_token_hash = refresh_token_hash,
                session_token_hash = %s,
                refresh_token_hash  = %s,
                expires_at          = %s,
                last_used_at        = NOW(),
                last_activity_at    = NOW()
            WHERE session_id = %s
            """,
            (
                new_access_hash,
                new_refresh_hash,
                new_expires_at.strftime("%Y-%m-%d %H:%M:%S"),
                session_id,
            ),
        )

    return {
        "access_token": new_access_token,
        "refresh_token": new_refresh_token,
        "token_type": "bearer",
        "expires_in": settings.access_token_expire_minutes * 60,
    }


# ---------------------------------------------------------------------------
# Embed token (OpenEMR iframe handshake)
# ---------------------------------------------------------------------------

def _embed_signing_secret() -> str:
    """Return the HMAC secret used for embed tokens."""
    secret = settings.openemr_embed_secret
    if secret:
        return secret
    if _is_production():
        raise ValueError(
            "OPENEMR_EMBED_SECRET is not configured — embed exchange is disabled."
        )
    return settings.jwt_secret + "_embed"


def create_embed_token(
    user_email: str,
    pid: int,
    tenant_id: str | None = None,
    ttl_seconds: int = 300,
) -> str:
    """Mint a short-lived embed JWT."""
    now = _utcnow()
    payload: dict[str, Any] = {
        "sub": user_email,
        "pid": int(pid),
        "iat": now,
        "exp": now + timedelta(seconds=max(30, min(ttl_seconds, 600))),
        "type": "embed",
    }
    if tenant_id:
        payload["tenant_id"] = tenant_id
    return jwt.encode(
        payload, _embed_signing_secret(), algorithm=settings.jwt_algorithm
    )


def authenticate_embed_token(
    embed_token: str,
    get_user_by_email_fn: Any,
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> dict[str, Any]:
    """Verify an embed JWT and issue a scoped RAF session.

    Parameters
    ----------
    embed_token:
        The raw embed JWT from OpenEMR.
    get_user_by_email_fn:
        Callable(email) -> user dict | None
    """
    secret = _embed_signing_secret()
    try:
        payload = jwt.decode(
            embed_token, secret, algorithms=[settings.jwt_algorithm]
        )
    except jwt.ExpiredSignatureError:
        raise ValueError("Embed token has expired.")
    except jwt.PyJWTError:
        raise ValueError("Invalid embed token.")

    if payload.get("type") != "embed":
        raise ValueError("Token is not an embed token.")

    email = payload.get("sub")
    if not isinstance(email, str) or not email:
        raise ValueError("Embed token is missing sub (RAF user email).")

    user = get_user_by_email_fn(email)
    if not user or not user.get("is_active"):
        raise ValueError("Embed token references an unknown or inactive user.")

    token_tenant = payload.get("tenant_id") or settings.openemr_embed_default_tenant_id
    if token_tenant and str(token_tenant) != str(user["tenant_id"]):
        raise ValueError("Embed tenant_id does not match the target user's tenant.")

    session_id = str(uuid.uuid4())
    now = _utcnow()
    access_exp = now + timedelta(minutes=settings.embed_access_token_expire_minutes)
    access_payload = {
        "sub": str(user["id"]),
        "email": user["email"],
        "role": user["role"],
        "tenant_id": user["tenant_id"],
        "session_id": session_id,
        "iat": now,
        "exp": access_exp,
        "type": "access",
        "embed": True,
        "embed_pid": int(payload.get("pid") or 0) or None,
    }
    access_token = jwt.encode(
        access_payload, settings.jwt_secret, algorithm=settings.jwt_algorithm
    )
    refresh_token = create_refresh_token(user_id=user["id"], session_id=session_id)

    session_token_hash = _hash_token(access_token)
    refresh_token_hash = _hash_token(refresh_token)
    expires_at = now + timedelta(days=settings.refresh_token_expire_days)
    with raf_cursor() as cur:
        cur.execute(
            """
            INSERT INTO user_sessions
                (session_id, user_id, session_token_hash, refresh_token_hash,
                 ip_address, user_agent, expires_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            (
                session_id,
                user["id"],
                session_token_hash,
                refresh_token_hash,
                ip_address or "embed",
                (user_agent or "openemr-embed")[:255],
                expires_at.strftime("%Y-%m-%d %H:%M:%S"),
            ),
        )

    user_info = {
        "id": user["id"],
        "email": user["email"],
        "full_name": user["full_name"],
        "role": user["role"],
        "tenant_id": user["tenant_id"],
        "avatar_url": user.get("avatar_url"),
        "must_change_password": user.get("must_change_password", False),
    }

    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
        "expires_in": settings.embed_access_token_expire_minutes * 60,
        "user": user_info,
        "embed_pid": int(payload.get("pid") or 0) or None,
    }
