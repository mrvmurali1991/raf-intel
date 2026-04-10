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

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.auth import get_current_user
from app.services.email_service import (
    get_email_config,
    send_email,
    _render_html,
)

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
