"""
Email Notification Service

Sends transactional emails for:
- Analysis completion notifications
- CMS submission deadline reminders
- Care gap alerts
- New suspect condition alerts
- Account security (password reset, MFA changes)
- Sync failure alerts

All SMTP calls run in a background thread pool so they never block the
FastAPI event loop.  If SMTP is not configured the functions log a debug
message and return immediately without raising.
"""
from __future__ import annotations

import logging
import smtplib
from concurrent.futures import ThreadPoolExecutor
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any

from app.config import settings

logger = logging.getLogger(__name__)

_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="email")

# ---------------------------------------------------------------------------
# HTML template helpers
# ---------------------------------------------------------------------------

_BASE_HTML = """\
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{subject}</title>
  <style>
    body {{
      margin: 0; padding: 0;
      background-color: #f4f6f9;
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto,
                   Helvetica, Arial, sans-serif;
      color: #1a202c;
    }}
    .wrapper {{
      max-width: 600px;
      margin: 40px auto;
      background: #ffffff;
      border-radius: 8px;
      overflow: hidden;
      box-shadow: 0 2px 12px rgba(0,0,0,0.08);
    }}
    .header {{
      background: linear-gradient(135deg, #1a56db 0%, #0e3fa8 100%);
      padding: 28px 32px;
    }}
    .header-logo {{
      font-size: 22px;
      font-weight: 700;
      color: #ffffff;
      letter-spacing: -0.5px;
    }}
    .header-tagline {{
      font-size: 12px;
      color: rgba(255,255,255,0.75);
      margin-top: 4px;
    }}
    .content {{
      padding: 32px;
    }}
    .content h2 {{
      margin: 0 0 16px;
      font-size: 20px;
      font-weight: 600;
      color: #1a202c;
    }}
    .content p {{
      margin: 0 0 14px;
      font-size: 15px;
      line-height: 1.6;
      color: #4a5568;
    }}
    .metric-row {{
      display: flex;
      gap: 16px;
      margin: 20px 0;
    }}
    .metric-box {{
      flex: 1;
      background: #f7fafc;
      border: 1px solid #e2e8f0;
      border-radius: 6px;
      padding: 16px;
      text-align: center;
    }}
    .metric-label {{
      font-size: 11px;
      font-weight: 600;
      text-transform: uppercase;
      letter-spacing: 0.8px;
      color: #718096;
    }}
    .metric-value {{
      font-size: 28px;
      font-weight: 700;
      color: #1a56db;
      margin-top: 6px;
    }}
    .alert-box {{
      border-left: 4px solid #e53e3e;
      background: #fff5f5;
      border-radius: 0 6px 6px 0;
      padding: 14px 18px;
      margin: 20px 0;
    }}
    .alert-box.warning {{
      border-left-color: #d69e2e;
      background: #fffff0;
    }}
    .alert-box.success {{
      border-left-color: #38a169;
      background: #f0fff4;
    }}
    .alert-box.info {{
      border-left-color: #3182ce;
      background: #ebf8ff;
    }}
    .alert-title {{
      font-weight: 600;
      font-size: 14px;
      color: #1a202c;
      margin-bottom: 4px;
    }}
    .alert-body {{
      font-size: 14px;
      color: #4a5568;
    }}
    .btn {{
      display: inline-block;
      margin-top: 20px;
      padding: 12px 28px;
      background: #1a56db;
      color: #ffffff !important;
      text-decoration: none;
      border-radius: 6px;
      font-size: 15px;
      font-weight: 600;
    }}
    .detail-table {{
      width: 100%;
      border-collapse: collapse;
      margin: 18px 0;
      font-size: 14px;
    }}
    .detail-table th {{
      text-align: left;
      padding: 8px 12px;
      background: #f7fafc;
      border-bottom: 1px solid #e2e8f0;
      color: #718096;
      font-weight: 600;
      text-transform: uppercase;
      font-size: 11px;
      letter-spacing: 0.6px;
    }}
    .detail-table td {{
      padding: 10px 12px;
      border-bottom: 1px solid #edf2f7;
      color: #2d3748;
    }}
    .detail-table tr:last-child td {{
      border-bottom: none;
    }}
    .footer {{
      background: #f7fafc;
      border-top: 1px solid #e2e8f0;
      padding: 20px 32px;
      font-size: 12px;
      color: #a0aec0;
      text-align: center;
      line-height: 1.6;
    }}
    .footer a {{
      color: #718096;
    }}
  </style>
</head>
<body>
  <div class="wrapper">
    <div class="header">
      <div class="header-logo">RAF Intelligence</div>
      <div class="header-tagline">Clinical Risk Adjustment Intelligence Platform</div>
    </div>
    <div class="content">
      {body}
    </div>
    <div class="footer">
      This is an automated message from RAF Intelligence.<br>
      Please do not reply to this email. For support contact
      <a href="mailto:support@raf.health">support@raf.health</a>.
    </div>
  </div>
</body>
</html>
"""


def _render_html(subject: str, body: str) -> str:
    """Wrap a content block in the standard RAF Intelligence email shell."""
    return _BASE_HTML.format(subject=subject, body=body)


# ---------------------------------------------------------------------------
# Core send helper
# ---------------------------------------------------------------------------

def _is_configured() -> bool:
    return bool(settings.smtp_host and settings.smtp_user)


def send_email(
    to: str,
    subject: str,
    html_body: str,
    text_body: str | None = None,
) -> None:
    """
    Send an email via SMTP in a background thread pool.

    The call returns immediately.  If SMTP is not configured, the message is
    silently dropped with a debug log entry.  Delivery errors are caught inside
    the worker thread and written to the application log.

    Parameters
    ----------
    to:
        Recipient email address.
    subject:
        Email subject line.
    html_body:
        Full HTML document string (use ``_render_html`` to wrap content).
    text_body:
        Optional plain-text fallback.  A minimal one is auto-generated from
        the subject if omitted.
    """
    if not _is_configured():
        logger.debug(
            "email_service: SMTP not configured — skipping send to %s (subject: %s)",
            to, subject,
        )
        return

    if text_body is None:
        text_body = f"{subject}\n\nThis is an automated message from RAF Intelligence."

    def _send() -> None:
        try:
            msg = MIMEMultipart("alternative")
            msg["Subject"] = subject
            msg["From"] = settings.smtp_from
            msg["To"] = to

            msg.attach(MIMEText(text_body, "plain", "utf-8"))
            msg.attach(MIMEText(html_body, "html", "utf-8"))

            with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=15) as server:
                if settings.smtp_tls:
                    server.starttls()
                server.login(settings.smtp_user, settings.smtp_password)
                server.sendmail(settings.smtp_from, [to], msg.as_string())

            logger.info("email_service: delivered '%s' to %s", subject, to)
        except Exception as exc:
            logger.error(
                "email_service: failed to deliver '%s' to %s: %s",
                subject, to, exc,
            )

    _executor.submit(_send)
    logger.debug("email_service: queued '%s' for %s", subject, to)


# ---------------------------------------------------------------------------
# Transactional email functions
# ---------------------------------------------------------------------------

def send_analysis_complete(
    user_email: str,
    patient_name: str,
    pid: str | int,
    hcc_count: int,
    raf_score: float,
) -> None:
    """Notify a user that an RAF analysis has completed for a patient."""
    subject = f"Analysis Complete — {patient_name}"
    body = f"""\
      <h2>Analysis Complete</h2>
      <p>
        The RAF analysis for <strong>{patient_name}</strong> (Patient ID:&nbsp;{pid})
        has finished successfully.
      </p>
      <table style="border-spacing:0;width:100%;margin:20px 0;">
        <tr>
          <td style="width:50%;padding-right:8px;">
            <div class="metric-box">
              <div class="metric-label">HCC Conditions</div>
              <div class="metric-value">{hcc_count}</div>
            </div>
          </td>
          <td style="width:50%;padding-left:8px;">
            <div class="metric-box">
              <div class="metric-label">RAF Score</div>
              <div class="metric-value">{raf_score:.4f}</div>
            </div>
          </td>
        </tr>
      </table>
      <p>
        Log in to RAF Intelligence to review the full analysis, including
        individual HCC mappings and suspect conditions.
      </p>
    """
    text = (
        f"Analysis Complete for {patient_name} (PID: {pid})\n\n"
        f"HCC Conditions: {hcc_count}\n"
        f"RAF Score: {raf_score:.4f}\n\n"
        "Log in to RAF Intelligence for the full report."
    )
    send_email(user_email, subject, _render_html(subject, body), text)


def send_submission_deadline_reminder(
    user_email: str,
    deadline_name: str,
    days_remaining: int,
) -> None:
    """Alert a user about an upcoming CMS submission deadline."""
    urgency = "warning" if days_remaining > 7 else "alert-box"
    alert_class = "warning" if days_remaining > 7 else ""
    subject = f"Deadline Reminder: {deadline_name} — {days_remaining} day(s) remaining"
    body = f"""\
      <h2>Submission Deadline Reminder</h2>
      <p>This is a reminder about an upcoming CMS submission deadline.</p>
      <div class="alert-box {alert_class}">
        <div class="alert-title">{deadline_name}</div>
        <div class="alert-body">
          <strong>{days_remaining} day(s) remaining</strong> until this submission deadline.
        </div>
      </div>
      <p>
        Log in to RAF Intelligence to review your submission readiness, validate
        diagnoses, and generate the required output files before the deadline.
      </p>
    """
    text = (
        f"Deadline Reminder: {deadline_name}\n\n"
        f"{days_remaining} day(s) remaining.\n\n"
        "Log in to RAF Intelligence to check submission readiness."
    )
    send_email(user_email, subject, _render_html(subject, body), text)


def send_care_gap_alert(
    user_email: str,
    patient_name: str,
    measure_name: str,
    due_date: str,
) -> None:
    """Notify a user of an open HEDIS care gap for a patient."""
    subject = f"Care Gap Alert: {measure_name} — {patient_name}"
    body = f"""\
      <h2>Open Care Gap Detected</h2>
      <p>
        A care gap has been identified for patient <strong>{patient_name}</strong>.
      </p>
      <table class="detail-table">
        <thead>
          <tr><th>Field</th><th>Value</th></tr>
        </thead>
        <tbody>
          <tr><td>Patient</td><td>{patient_name}</td></tr>
          <tr><td>Measure</td><td>{measure_name}</td></tr>
          <tr><td>Due Date</td><td>{due_date}</td></tr>
        </tbody>
      </table>
      <div class="alert-box warning">
        <div class="alert-title">Action Required</div>
        <div class="alert-body">
          This gap may affect STARS ratings and quality scores.
          Schedule the required service or documentation before the due date.
        </div>
      </div>
    """
    text = (
        f"Care Gap Alert: {measure_name}\n\n"
        f"Patient: {patient_name}\n"
        f"Measure: {measure_name}\n"
        f"Due Date: {due_date}\n\n"
        "Log in to RAF Intelligence to review and close this gap."
    )
    send_email(user_email, subject, _render_html(subject, body), text)


def send_suspect_alert(
    user_email: str,
    patient_name: str,
    condition: str,
    confidence: float,
) -> None:
    """Notify a user that a new suspect condition has been identified."""
    confidence_pct = round(confidence * 100, 1)
    subject = f"New Suspect Condition — {patient_name}"
    body = f"""\
      <h2>New Suspect Condition Identified</h2>
      <p>
        RAF Intelligence has identified a potential undiagnosed condition for
        patient <strong>{patient_name}</strong>.
      </p>
      <table class="detail-table">
        <thead>
          <tr><th>Field</th><th>Value</th></tr>
        </thead>
        <tbody>
          <tr><td>Patient</td><td>{patient_name}</td></tr>
          <tr><td>Suspect Condition</td><td>{condition}</td></tr>
          <tr><td>Confidence Score</td><td>{confidence_pct}%</td></tr>
        </tbody>
      </table>
      <div class="alert-box info">
        <div class="alert-title">Clinical Review Recommended</div>
        <div class="alert-body">
          This suspect was identified by AI-assisted NLP analysis of clinical
          notes. A qualified clinician should review the source documentation
          before any coding action is taken.
        </div>
      </div>
    """
    text = (
        f"New Suspect Condition for {patient_name}\n\n"
        f"Condition: {condition}\n"
        f"Confidence: {confidence_pct}%\n\n"
        "Log in to RAF Intelligence to review and act on this suspect."
    )
    send_email(user_email, subject, _render_html(subject, body), text)


def send_sync_failure_alert(
    user_email: str,
    connection_name: str,
    error_message: str,
) -> None:
    """Alert a user that an EMR/FHIR sync connection has failed."""
    subject = f"Sync Failure Alert: {connection_name}"
    # Truncate long error messages for display
    display_error = error_message[:400] + "…" if len(error_message) > 400 else error_message
    body = f"""\
      <h2>Sync Connection Failure</h2>
      <p>
        A sync failure has been detected for the connection
        <strong>{connection_name}</strong>.
      </p>
      <div class="alert-box">
        <div class="alert-title">Error Details</div>
        <div class="alert-body" style="font-family:monospace;font-size:13px;">
          {display_error}
        </div>
      </div>
      <p>
        Automatic retries are in progress. If this alert persists, log in to
        RAF Intelligence to review the connection configuration and sync logs.
      </p>
    """
    text = (
        f"Sync Failure: {connection_name}\n\n"
        f"Error: {error_message}\n\n"
        "Log in to RAF Intelligence to review the sync connection."
    )
    send_email(user_email, subject, _render_html(subject, body), text)


def send_password_reset(
    user_email: str,
    reset_url: str,
    expires_minutes: int,
) -> None:
    """Send a password-reset link to the user."""
    subject = "Reset Your RAF Intelligence Password"
    body = f"""\
      <h2>Password Reset Request</h2>
      <p>
        We received a request to reset the password for the account associated
        with this email address.
      </p>
      <p>Click the button below to choose a new password:</p>
      <a href="{reset_url}" class="btn">Reset Password</a>
      <div class="alert-box warning" style="margin-top:24px;">
        <div class="alert-title">This link expires in {expires_minutes} minutes</div>
        <div class="alert-body">
          If you did not request a password reset, you can safely ignore this
          email. Your password will not be changed.
        </div>
      </div>
      <p style="margin-top:20px;font-size:13px;color:#718096;">
        If the button does not work, copy and paste this URL into your browser:<br>
        <span style="word-break:break-all;">{reset_url}</span>
      </p>
    """
    text = (
        "RAF Intelligence — Password Reset\n\n"
        f"Click this link to reset your password (expires in {expires_minutes} minutes):\n"
        f"{reset_url}\n\n"
        "If you did not request this, you can ignore this email."
    )
    send_email(user_email, subject, _render_html(subject, body), text)


def send_mfa_enabled(user_email: str) -> None:
    """Confirm that multi-factor authentication has been enabled for the account."""
    subject = "Two-Factor Authentication Enabled"
    body = """\
      <h2>Two-Factor Authentication Enabled</h2>
      <div class="alert-box success">
        <div class="alert-title">Your account is now more secure</div>
        <div class="alert-body">
          Multi-factor authentication (MFA) has been successfully enabled for
          your RAF Intelligence account.
        </div>
      </div>
      <p>
        From now on, you will need to provide a verification code in addition
        to your password each time you sign in.
      </p>
      <p>
        If you did not make this change, please contact your administrator or
        our support team immediately at
        <a href="mailto:support@raf.health">support@raf.health</a>.
      </p>
    """
    text = (
        "Two-Factor Authentication Enabled\n\n"
        "MFA has been successfully enabled for your RAF Intelligence account.\n\n"
        "If you did not make this change, contact support@raf.health immediately."
    )
    send_email(user_email, subject, _render_html(subject, body), text)


# ---------------------------------------------------------------------------
# Config introspection
# ---------------------------------------------------------------------------

def get_email_config() -> dict[str, Any]:
    """
    Return the current SMTP configuration status.

    Safe to expose through the API — does not reveal credentials.
    """
    configured = _is_configured()

    # Attempt to infer the email provider from the SMTP host for display.
    provider: str = "custom"
    host = settings.smtp_host.lower() if settings.smtp_host else ""
    if "gmail" in host or "google" in host:
        provider = "Google Gmail"
    elif "sendgrid" in host:
        provider = "SendGrid"
    elif "mailgun" in host:
        provider = "Mailgun"
    elif "ses" in host or "amazonaws" in host:
        provider = "Amazon SES"
    elif "postmark" in host:
        provider = "Postmark"
    elif "smtp.office365" in host or "outlook" in host:
        provider = "Microsoft 365"
    elif not host:
        provider = "not configured"

    return {
        "configured": configured,
        "provider": provider,
        "smtp_host": settings.smtp_host or None,
        "smtp_port": settings.smtp_port,
        "smtp_tls": settings.smtp_tls,
        "smtp_from": settings.smtp_from,
        # Never expose smtp_user or smtp_password
    }
