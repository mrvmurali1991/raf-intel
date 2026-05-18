"""
Session lifecycle: create, validate (with HIPAA idle timeout), revoke, list.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from app.config import settings
from app.db import raf_cursor
from app.services.auth.tokens import _hash_token, _utcnow, create_access_token, create_refresh_token

logger = logging.getLogger(__name__)


def create_session(
    user_id: int,
    access_token: str,
    refresh_token: str,
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> str:
    """Persist a new session and return the session_id."""
    session_id = str(uuid.uuid4())
    session_token_hash = _hash_token(access_token)
    refresh_token_hash = _hash_token(refresh_token)
    expires_at = _utcnow() + timedelta(days=settings.refresh_token_expire_days)
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
                user_id,
                session_token_hash,
                refresh_token_hash,
                ip_address or "unknown",
                user_agent,
                expires_at.strftime("%Y-%m-%d %H:%M:%S"),
            ),
        )
    return session_id


def validate_session(session_id: str) -> dict[str, Any] | None:
    """Return session row if active and not expired, else None.

    HIPAA idle timeout: if last_activity_at is older than settings.idle_timeout_minutes
    the session is automatically revoked and None is returned.
    """
    with raf_cursor() as cur:
        cur.execute(
            """
            SELECT id, session_id, user_id, is_revoked, expires_at, last_activity_at
            FROM user_sessions
            WHERE session_id = %s AND is_revoked = 0
            """,
            (session_id,),
        )
        row = cur.fetchone()
    if not row:
        return None
    expires = row["expires_at"]
    if isinstance(expires, str):
        expires = datetime.fromisoformat(expires)
    if expires.replace(tzinfo=timezone.utc) < _utcnow():
        return None

    last_activity = row.get("last_activity_at")
    if last_activity is not None:
        if isinstance(last_activity, str):
            last_activity = datetime.fromisoformat(last_activity)
        idle_seconds = (
            _utcnow() - last_activity.replace(tzinfo=timezone.utc)
        ).total_seconds()
        if idle_seconds > settings.idle_timeout_minutes * 60:
            revoke_session(session_id)
            logger.info(
                "Session %s revoked due to idle timeout (%.0f s idle, limit %d min)",
                session_id,
                idle_seconds,
                settings.idle_timeout_minutes,
            )
            return None

    with raf_cursor() as cur:
        cur.execute(
            "UPDATE user_sessions SET last_used_at = NOW(), last_activity_at = NOW() WHERE session_id = %s",
            (session_id,),
        )
    return row


def revoke_session(session_id: str) -> None:
    with raf_cursor() as cur:
        cur.execute(
            "UPDATE user_sessions SET is_revoked = 1 WHERE session_id = %s",
            (session_id,),
        )


def revoke_all_sessions(user_id: int) -> None:
    with raf_cursor() as cur:
        cur.execute(
            "UPDATE user_sessions SET is_revoked = 1 WHERE user_id = %s",
            (user_id,),
        )


def list_sessions(user_id: int) -> list[dict[str, Any]]:
    with raf_cursor() as cur:
        cur.execute(
            """
            SELECT id, session_id, ip_address, user_agent, created_at, last_used_at, expires_at, is_revoked
            FROM user_sessions
            WHERE user_id = %s AND is_revoked = 0
            ORDER BY last_used_at DESC
            """,
            (user_id,),
        )
        return cur.fetchall()


def issue_tokens(
    user: dict[str, Any],
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> dict[str, Any]:
    """Create session, access token, and refresh token for a fully-authenticated user."""
    session_id = str(uuid.uuid4())

    access_token = create_access_token(
        user_id=user["id"],
        email=user["email"],
        role=user["role"],
        tenant_id=user["tenant_id"],
        session_id=session_id,
    )
    refresh_token = create_refresh_token(user_id=user["id"], session_id=session_id)

    session_token_hash = _hash_token(access_token)
    refresh_token_hash = _hash_token(refresh_token)
    expires_at = _utcnow() + timedelta(days=settings.refresh_token_expire_days)
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
                ip_address or "unknown",
                user_agent,
                expires_at.strftime("%Y-%m-%d %H:%M:%S"),
            ),
        )

    user_info = {
        "id": user["id"],
        "email": user["email"],
        "full_name": user["full_name"],
        "role": user["role"],
        "tenant_id": user["tenant_id"],
        "avatar_url": user["avatar_url"],
        "must_change_password": user.get("must_change_password", False),
    }

    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
        "expires_in": settings.access_token_expire_minutes * 60,
        "user": user_info,
    }
