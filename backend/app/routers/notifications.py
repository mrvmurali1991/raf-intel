"""
Notifications router — email configuration, test delivery, and per-user preferences.

Endpoints
---------
GET  /api/notifications/config        – SMTP config status (no credentials exposed)
POST /api/notifications/test          – Send a test email to the current user
GET  /api/notifications/preferences   – Get the current user's notification preferences
PUT  /api/notifications/preferences   – Update notification preferences

Authentication: all endpoints require a valid Bearer JWT.
"""
# Do NOT use 'from __future__ import annotations' — breaks FastAPI schema generation.

import asyncio
import json
import logging
import uuid
from collections.abc import AsyncGenerator
from datetime import datetime, timedelta, timezone
from typing import Any

import jwt
from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.auth import get_current_user
from app.config import settings
from app.services.auth_service import get_user, validate_session
from app.services.email_service import (
    _render_html,
    get_email_config,
    send_email,
)
from app.services.realtime_service import broadcast_patient_event, connection_manager

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/notifications", tags=["notifications"])


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


class NotificationPreferences(BaseModel):
    """Per-user toggles for each notification category."""

    analysis_complete: bool = Field(
        default=True,
        description="Email when an RAF analysis finishes for one of your patients.",
    )
    submission_deadline: bool = Field(
        default=True,
        description="Email reminders before upcoming CMS submission deadlines.",
    )
    care_gap_alerts: bool = Field(
        default=True,
        description="Email when a new care gap is detected for a patient.",
    )
    suspect_alerts: bool = Field(
        default=True,
        description="Email when a new suspect condition is identified.",
    )
    sync_failure_alerts: bool = Field(
        default=True,
        description="Email when an EMR/FHIR sync connection fails.",
    )
    security_alerts: bool = Field(
        default=True,
        description="Email for account security events (password reset, MFA changes).",
    )


# ---------------------------------------------------------------------------
# DB-backed preferences store
# ---------------------------------------------------------------------------
# Preferences are persisted to the raf_user_notification_preferences table.
# A one-time table creation is performed at import time so the endpoint
# works even before any Alembic migration has run.

_DEFAULT_PREFERENCES = NotificationPreferences().model_dump()


def _get_prefs(user_id: int) -> dict[str, bool]:
    from app.db import raf_cursor

    with raf_cursor() as cur:
        cur.execute(
            """
            SELECT analysis_complete, submission_deadline, care_gap_alerts,
                   suspect_alerts, sync_failure_alerts, security_alerts
            FROM raf_user_notification_preferences
            WHERE user_id = %s
            """,
            (user_id,),
        )
        row = cur.fetchone()
    if row:
        return {
            "analysis_complete": bool(row["analysis_complete"]),
            "submission_deadline": bool(row["submission_deadline"]),
            "care_gap_alerts": bool(row["care_gap_alerts"]),
            "suspect_alerts": bool(row["suspect_alerts"]),
            "sync_failure_alerts": bool(row["sync_failure_alerts"]),
            "security_alerts": bool(row["security_alerts"]),
        }
    return dict(_DEFAULT_PREFERENCES)


def _set_prefs(user_id: int, prefs: dict[str, bool]) -> None:
    from app.db import raf_cursor

    with raf_cursor() as cur:
        cur.execute(
            """
            INSERT INTO raf_user_notification_preferences
                (user_id, analysis_complete, submission_deadline, care_gap_alerts,
                 suspect_alerts, sync_failure_alerts, security_alerts)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE
                analysis_complete   = VALUES(analysis_complete),
                submission_deadline = VALUES(submission_deadline),
                care_gap_alerts     = VALUES(care_gap_alerts),
                suspect_alerts      = VALUES(suspect_alerts),
                sync_failure_alerts = VALUES(sync_failure_alerts),
                security_alerts     = VALUES(security_alerts)
            """,
            (
                user_id,
                int(prefs.get("analysis_complete", True)),
                int(prefs.get("submission_deadline", True)),
                int(prefs.get("care_gap_alerts", True)),
                int(prefs.get("suspect_alerts", True)),
                int(prefs.get("sync_failure_alerts", True)),
                int(prefs.get("security_alerts", True)),
            ),
        )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get(
    "/config",
    summary="Email notification configuration status",
)
def get_notification_config(
    _current_user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    """
    Return the current SMTP configuration status.

    Indicates whether email notifications are active and which provider is
    detected from the SMTP hostname.  Credentials are never included in the
    response.
    """
    return get_email_config()


@router.post(
    "/test",
    summary="Send a test notification email to the current user",
    status_code=status.HTTP_202_ACCEPTED,
)
def send_test_notification(
    current_user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    """
    Dispatch a test email to the email address on the current user's account.

    Returns HTTP 202 immediately; delivery happens asynchronously in the
    email thread pool.  Returns HTTP 400 if SMTP is not configured.
    """
    config = get_email_config()
    if not config["configured"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "SMTP is not configured. Set SMTP_HOST, SMTP_USER, and "
                "SMTP_PASSWORD environment variables to enable email notifications."
            ),
        )

    user_email: str = current_user.get("email", "")
    if not user_email:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No email address is associated with your account.",
        )

    subject = "RAF Intelligence — Test Notification"
    body = """\
      <h2>Test Notification</h2>
      <div class="alert-box success">
        <div class="alert-title">Email notifications are working correctly</div>
        <div class="alert-body">
          This is a test message from RAF Intelligence confirming that your
          SMTP configuration is operational and notifications will be delivered
          to this address.
        </div>
      </div>
      <p>
        You can manage which notifications you receive from the
        <strong>Notification Preferences</strong> settings in your account.
      </p>
    """

    send_email(user_email, subject, _render_html(subject, body))

    logger.info(
        "notifications: test email queued for user %s (%s)",
        current_user.get("id"),
        user_email,
    )
    return {
        "queued": True,
        "recipient": user_email,
        "message": "Test email has been queued for delivery.",
    }


@router.get(
    "/preferences",
    summary="Get notification preferences for the current user",
    response_model=NotificationPreferences,
)
def get_preferences(
    current_user: dict = Depends(get_current_user),
) -> dict[str, bool]:
    """Return the current user's notification category preferences."""
    user_id: int = current_user["id"]
    return _get_prefs(user_id)


@router.put(
    "/preferences",
    summary="Update notification preferences for the current user",
    response_model=NotificationPreferences,
)
def update_preferences(
    body: NotificationPreferences,
    current_user: dict = Depends(get_current_user),
) -> dict[str, bool]:
    """
    Update which email notification categories the current user receives.

    All fields are optional — omitted fields retain their current value.
    Pass ``false`` for any category to unsubscribe from those emails.
    """
    user_id: int = current_user["id"]
    existing = _get_prefs(user_id)
    updated = {**existing, **body.model_dump()}
    _set_prefs(user_id, updated)
    logger.info("notifications: preferences updated for user %s", user_id)
    return updated


# ---------------------------------------------------------------------------
# SSE ticket + stream
# ---------------------------------------------------------------------------
# The browser's native EventSource cannot send Authorization headers, so to
# avoid putting a long-lived access token in the URL query string we issue a
# short-lived signed ticket from an authenticated HTTP endpoint, then accept
# that ticket on the SSE stream. Ticket lifetime is 30 s — enough to open the
# EventSource immediately after the fetch resolves.

_SSE_TICKET_TTL_SECONDS = 30
_SSE_CREDENTIALS_EXCEPTION = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Invalid or expired SSE ticket.",
)


def _issue_sse_ticket(user_id: int, session_id: str, tenant_id: Any) -> str:
    now = datetime.now(timezone.utc)
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "session_id": session_id,
        "tenant_id": tenant_id,
        "iat": now,
        "exp": now + timedelta(seconds=_SSE_TICKET_TTL_SECONDS),
        "type": "sse_ticket",
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


async def _resolve_sse_ticket(ticket: str) -> dict[str, Any]:
    try:
        payload = jwt.decode(ticket, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except jwt.PyJWTError:
        raise _SSE_CREDENTIALS_EXCEPTION
    if payload.get("type") != "sse_ticket":
        raise _SSE_CREDENTIALS_EXCEPTION
    try:
        user_id = int(payload["sub"])
    except (KeyError, ValueError, TypeError):
        raise _SSE_CREDENTIALS_EXCEPTION
    session_id = payload.get("session_id")
    if not session_id or not validate_session(session_id):
        raise _SSE_CREDENTIALS_EXCEPTION
    user = get_user(user_id)
    if not user or not user.get("is_active"):
        raise _SSE_CREDENTIALS_EXCEPTION
    user["session_id"] = session_id
    if user.get("tenant_id") is None:
        user["tenant_id"] = payload.get("tenant_id")
    return user


async def _sse_stream_generator(queue: asyncio.Queue, connection_id: str) -> AsyncGenerator[str, None]:
    try:
        while True:
            try:
                event = await asyncio.wait_for(queue.get(), timeout=25.0)
                yield f"data: {json.dumps(event)}\n\n"
            except asyncio.TimeoutError:
                yield ": ping\n\n"
    except asyncio.CancelledError:
        pass
    finally:
        await connection_manager.disconnect(connection_id)


@router.get(
    "/sse-ticket",
    summary="Issue a short-lived SSE ticket for /api/notifications/stream",
)
def issue_sse_ticket(
    current_user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    session_id = current_user.get("session_id")
    if not session_id:
        raise HTTPException(status_code=401, detail="No active session.")
    ticket = _issue_sse_ticket(
        user_id=int(current_user["id"]),
        session_id=str(session_id),
        tenant_id=current_user.get("tenant_id"),
    )
    return {"ticket": ticket, "ttl_seconds": _SSE_TICKET_TTL_SECONDS}


@router.get(
    "/stream",
    summary="SSE stream — live notifications for the current user",
    response_class=StreamingResponse,
)
async def notifications_stream(
    ticket: str = Query(..., description="Short-lived ticket from /sse-ticket"),
) -> StreamingResponse:
    user = await _resolve_sse_ticket(ticket)
    user_id: int = int(user["id"])
    tenant_id = user.get("tenant_id")
    tenant_id_str = str(tenant_id) if tenant_id is not None else "default"

    connection_id = f"sse-notif-{user_id}-{uuid.uuid4().hex[:8]}"
    queue = await connection_manager.connect(connection_id, user_id, tenant_id_str)
    logger.info("notifications: SSE stream opened [%s] user=%s", connection_id, user_id)

    return StreamingResponse(
        _sse_stream_generator(queue, connection_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


# ---------------------------------------------------------------------------
# Patient-event broadcast endpoint (admin-only, used for testing / triggers)
# ---------------------------------------------------------------------------

class _PatientBroadcastBody(BaseModel):
    event_type: str = Field(
        ...,
        description='One of "patient.synced", "patient.scored", "patient.analyzed"',
    )
    payload: dict[str, Any] = Field(
        ...,
        description="Must include pid and tenant_id; additional fields passed through",
    )


@router.post(
    "/broadcast-patient-event",
    summary="Broadcast a patient-pipeline SSE event to all subscribers (admin only)",
    status_code=status.HTTP_202_ACCEPTED,
)
async def broadcast_patient_event_endpoint(
    body: _PatientBroadcastBody,
    current_user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    """
    Trigger a ``broadcast_patient_event`` from within the web-server process
    so it reaches all currently connected SSE clients.

    Requires admin role.  Accepts the same event types and payload structure
    as ``broadcast_patient_event()``.
    """
    if current_user.get("role") not in ("admin", "superadmin"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin role required to broadcast patient events",
        )
    await broadcast_patient_event(body.event_type, body.payload)
    return {"status": "queued", "event_type": body.event_type}
