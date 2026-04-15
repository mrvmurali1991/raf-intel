"""
Break-Glass Emergency Access — HIPAA-compliant emergency override.

Provides time-limited emergency access when normal authorization is
insufficient but patient care requires immediate data access.

Every break-glass event creates a HIGH-PRIORITY immutable audit entry
and triggers admin notification via webhook.

Usage:
    from app.services.break_glass import create_break_glass_session, validate_break_glass

    session = create_break_glass_session(
        user_id=42, tenant_id="1", reason="Patient in cardiac arrest — need med history"
    )
"""
from __future__ import annotations

import json
import logging
import os
import secrets
import threading
from datetime import datetime, timedelta, timezone
from typing import Any

import requests

from app.services.immutable_audit import append_audit_entry

logger = logging.getLogger(__name__)

# In-memory store.  For production, persist to DB.
_sessions: dict[str, dict[str, Any]] = {}
_sessions_lock = threading.Lock()

_EXPIRY_MINUTES = 30
_ALLOWED_ROLES = {"admin", "physician", "provider", "medical_director"}

# Webhook URL for admin notifications (optional)
_ADMIN_WEBHOOK_URL = os.getenv("BREAK_GLASS_WEBHOOK_URL", "")


def create_break_glass_session(
    *,
    user_id: int | str,
    tenant_id: int | str,
    reason: str,
    role: str,
    ip_address: str | None = None,
) -> dict[str, Any]:
    """Create a time-limited emergency access session.

    Raises ValueError if the role is not authorized for break-glass access
    or the reason is too short.
    """
    if role not in _ALLOWED_ROLES:
        raise ValueError(
            f"Role '{role}' is not authorized for break-glass access. "
            f"Allowed: {', '.join(sorted(_ALLOWED_ROLES))}"
        )
    if not reason or len(reason.strip()) < 10:
        raise ValueError("Break-glass reason must be at least 10 characters.")

    session_id = secrets.token_urlsafe(32)
    now = datetime.now(tz=timezone.utc)
    expires_at = now + timedelta(minutes=_EXPIRY_MINUTES)

    session = {
        "session_id": session_id,
        "user_id": str(user_id),
        "tenant_id": str(tenant_id),
        "reason": reason.strip(),
        "role": role,
        "ip_address": ip_address,
        "created_at": now.isoformat(),
        "expires_at": expires_at.isoformat(),
        "is_active": True,
    }

    with _sessions_lock:
        _sessions[session_id] = session

    # Immutable audit entry — HIGH PRIORITY
    append_audit_entry(
        event_type="break_glass_activated",
        user_id=user_id,
        tenant_id=tenant_id,
        resource_type="emergency_access",
        resource_id=session_id,
        action="break_glass_create",
        details={
            "reason": reason.strip(),
            "role": role,
            "ip_address": ip_address,
            "expires_at": expires_at.isoformat(),
            "priority": "HIGH",
        },
    )

    # Also persist to DB for durability
    try:
        from app.db import raf_cursor
        with raf_cursor() as cur:
            cur.execute(
                "INSERT INTO audit_log (user_id, action, resource_type, resource_id, "
                "ip_address, details, created_at) "
                "VALUES (%s, %s, %s, %s, %s, %s, NOW())",
                (
                    int(user_id) if str(user_id).isdigit() else None,
                    "break_glass_activated",
                    "emergency_access",
                    session_id,
                    ip_address,
                    json.dumps({
                        "reason": reason.strip(),
                        "role": role,
                        "expires_at": expires_at.isoformat(),
                        "priority": "HIGH",
                    }),
                ),
            )
    except Exception:
        logger.error("Failed to persist break-glass to DB", exc_info=True)

    # Notify admins
    _notify_admins(session)

    logger.warning(
        "BREAK-GLASS ACTIVATED: user=%s tenant=%s reason=%s expires=%s",
        user_id, tenant_id, reason.strip()[:50], expires_at.isoformat(),
    )

    return session


def validate_break_glass(session_id: str) -> dict[str, Any] | None:
    """Check if a break-glass session is still active and not expired."""
    with _sessions_lock:
        session = _sessions.get(session_id)
    if not session or not session.get("is_active"):
        return None
    expires_at = datetime.fromisoformat(session["expires_at"])
    if datetime.now(tz=timezone.utc) > expires_at:
        revoke_break_glass(session_id, revoked_by="system_expiry")
        return None
    return session


def revoke_break_glass(session_id: str, *, revoked_by: str = "system") -> bool:
    """Revoke a break-glass session."""
    with _sessions_lock:
        session = _sessions.get(session_id)
        if not session:
            return False
        session["is_active"] = False
        session["revoked_at"] = datetime.now(tz=timezone.utc).isoformat()
        session["revoked_by"] = revoked_by

    append_audit_entry(
        event_type="break_glass_revoked",
        user_id=session.get("user_id"),
        tenant_id=session.get("tenant_id"),
        resource_type="emergency_access",
        resource_id=session_id,
        action="break_glass_revoke",
        details={"revoked_by": revoked_by},
    )
    return True


def list_break_glass_events(
    tenant_id: str | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """Return all break-glass sessions, optionally filtered by tenant."""
    with _sessions_lock:
        events = list(_sessions.values())
    if tenant_id:
        events = [e for e in events if e.get("tenant_id") == str(tenant_id)]
    events.sort(key=lambda e: e.get("created_at", ""), reverse=True)
    return events[:limit]


def _notify_admins(session: dict[str, Any]) -> None:
    """Send webhook notification to admins about break-glass activation."""
    if not _ADMIN_WEBHOOK_URL:
        logger.debug("No BREAK_GLASS_WEBHOOK_URL configured — skipping admin notification")
        return
    try:
        payload = {
            "event": "break_glass_activated",
            "user_id": session["user_id"],
            "tenant_id": session["tenant_id"],
            "reason": session["reason"],
            "expires_at": session["expires_at"],
            "session_id": session["session_id"],
        }
        resp = requests.post(
            _ADMIN_WEBHOOK_URL,
            json=payload,
            timeout=5,
            headers={"Content-Type": "application/json"},
        )
        if resp.status_code >= 400:
            logger.warning("Break-glass webhook returned %d", resp.status_code)
    except Exception:
        logger.error("Failed to send break-glass webhook", exc_info=True)
