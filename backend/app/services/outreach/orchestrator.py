"""Multi-channel patient outreach orchestrator.

Lazy-imports Twilio / SendGrid so the test suite doesn't need them. When
provider credentials are missing the message is recorded with
status='failed' and a distinctive failure_reason so SRE can grep and the
funnel shows a real failure instead of silently hiding messages in 'queued'.
Use POST /api/outreach/replay/{message_id} to re-attempt after credentials
are wired.
"""
from __future__ import annotations

import logging
import os
import re
from datetime import datetime
from typing import Any

from app.db import raf_cursor
from app.services.audit_logger import log_phi_access
from app.services.outreach.templates import (
    get_email_subject,
    get_template,
    render,
)

logger = logging.getLogger(__name__)

MAX_ATTEMPTS_PER_MEASURE_PER_90D = 3
PHONE_RE = re.compile(r"^\+?[1-9]\d{7,14}$")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


# ---------- Consent ----------

def get_consent(tenant_id: str, patient_id: int, channel: str) -> str:
    with raf_cursor() as cur:
        cur.execute(
            """SELECT consent_status FROM outreach_consents
               WHERE tenant_id=%s AND patient_id=%s AND channel=%s""",
            (tenant_id, patient_id, channel),
        )
        row = cur.fetchone()
        if not row:
            return "unknown"
        return str(row["consent_status"] if isinstance(row, dict) else row[0])


def record_opt_out(
    tenant_id: str,
    patient_id: int,
    channel: str,
    reason: str = "",
) -> None:
    with raf_cursor() as cur:
        cur.execute(
            """INSERT INTO outreach_consents
                 (tenant_id, patient_id, channel, consent_status,
                  opt_out_at, opt_out_reason)
               VALUES (%s,%s,%s,'opted_out', NOW(), %s)
               ON DUPLICATE KEY UPDATE
                 consent_status='opted_out',
                 opt_out_at=NOW(),
                 opt_out_reason=VALUES(opt_out_reason)""",
            (tenant_id, patient_id, channel, reason[:255]),
        )


def record_opt_in(
    tenant_id: str,
    patient_id: int,
    channel: str,
    method: str = "portal_checkbox",
) -> None:
    with raf_cursor() as cur:
        cur.execute(
            """INSERT INTO outreach_consents
                 (tenant_id, patient_id, channel, consent_status,
                  consent_method, consent_recorded_at)
               VALUES (%s,%s,%s,'opted_in',%s,NOW())
               ON DUPLICATE KEY UPDATE
                 consent_status='opted_in',
                 consent_method=VALUES(consent_method),
                 consent_recorded_at=NOW()""",
            (tenant_id, patient_id, channel, method),
        )


# ---------- Caps ----------

def _recent_attempt_count(
    tenant_id: str, patient_id: int, measure_id: str
) -> int:
    with raf_cursor() as cur:
        cur.execute(
            """SELECT COUNT(*) AS n FROM outreach_messages
               WHERE tenant_id=%s AND patient_id=%s AND measure_id=%s
                 AND queued_at > NOW() - INTERVAL 90 DAY""",
            (tenant_id, patient_id, measure_id),
        )
        row = cur.fetchone()
        if not row:
            return 0
        return int(row["n"] if isinstance(row, dict) else row[0])


# ---------- Lazy provider clients ----------

def _twilio_client():
    sid = os.getenv("TWILIO_ACCOUNT_SID")
    tok = os.getenv("TWILIO_AUTH_TOKEN")
    if not sid or not tok:
        return None
    try:
        from twilio.rest import Client  # type: ignore
        return Client(sid, tok)
    except Exception as e:
        logger.warning("Twilio unavailable: %s", e)
        return None


def _sendgrid_client():
    key = os.getenv("SENDGRID_API_KEY")
    if not key:
        return None
    try:
        from sendgrid import SendGridAPIClient  # type: ignore
        return SendGridAPIClient(key)
    except Exception as e:
        logger.warning("SendGrid unavailable: %s", e)
        return None


# ---------- Send ----------

def _validate_phone(num: str) -> str:
    n = re.sub(r"[^\d+]", "", num or "")
    if not n.startswith("+"):
        # Assume US if 10 digits
        if len(n) == 10:
            n = "+1" + n
    if not PHONE_RE.match(n):
        raise ValueError(f"Invalid phone: {num}")
    return n


def _validate_email(addr: str) -> str:
    a = (addr or "").strip()
    if not EMAIL_RE.match(a):
        raise ValueError(f"Invalid email: {addr}")
    return a


def _record_message(
    *,
    tenant_id: str,
    patient_id: int,
    measure_id: str,
    channel: str,
    language: str,
    template_id: str,
    to_address: str,
    status: str,
    provider_message_id: str | None = None,
    failure_reason: str | None = None,
    campaign_id: int | None = None,
) -> int:
    with raf_cursor() as cur:
        cur.execute(
            """INSERT INTO outreach_messages
                 (tenant_id, campaign_id, patient_id, measure_id,
                  channel, language, status, template_id, to_address,
                  provider_message_id, sent_at, failed_at, failure_reason)
               VALUES
                 (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
                  CASE WHEN %s IN ('sent','delivered') THEN NOW() ELSE NULL END,
                  CASE WHEN %s='failed' THEN NOW() ELSE NULL END,
                  %s)""",
            (
                tenant_id, campaign_id, patient_id, measure_id,
                channel, language, status, template_id, to_address[:255],
                provider_message_id, status, status, failure_reason,
            ),
        )
        return int(cur.lastrowid)


def enqueue_outreach(
    *,
    tenant_id: str,
    patient_id: int,
    measure_id: str,
    channel: str,
    language: str = "en",
    to_address: str,
    first_name: str,
    clinic: str = "your clinic",
    phone_callback: str = "",
    schedule_url: str = "",
    unsubscribe_url: str = "",
    campaign_id: int | None = None,
    actor_user_id: int | None = None,
) -> dict[str, Any]:
    """Send an outreach message; return {message_id, status}."""
    # Consent gate
    consent = get_consent(tenant_id, patient_id, channel)
    if consent == "opted_out":
        mid = _record_message(
            tenant_id=tenant_id, patient_id=patient_id,
            measure_id=measure_id, channel=channel, language=language,
            template_id=f"{measure_id}.{channel}.{language}",
            to_address=to_address, status="opted_out",
            failure_reason="patient_opted_out",
            campaign_id=campaign_id,
        )
        return {"message_id": mid, "status": "opted_out"}

    # Attempt cap
    if _recent_attempt_count(tenant_id, patient_id, measure_id) >= \
            MAX_ATTEMPTS_PER_MEASURE_PER_90D:
        mid = _record_message(
            tenant_id=tenant_id, patient_id=patient_id,
            measure_id=measure_id, channel=channel, language=language,
            template_id=f"{measure_id}.{channel}.{language}",
            to_address=to_address, status="failed",
            failure_reason="max_attempts_reached_90d",
            campaign_id=campaign_id,
        )
        return {"message_id": mid, "status": "failed"}

    # Validate destination
    try:
        if channel in ("sms", "voice"):
            to_address = _validate_phone(to_address)
        elif channel == "email":
            to_address = _validate_email(to_address)
    except ValueError as e:
        mid = _record_message(
            tenant_id=tenant_id, patient_id=patient_id,
            measure_id=measure_id, channel=channel, language=language,
            template_id=f"{measure_id}.{channel}.{language}",
            to_address=to_address, status="failed",
            failure_reason=str(e)[:500],
            campaign_id=campaign_id,
        )
        return {"message_id": mid, "status": "failed"}

    # Render template
    body = render(
        get_template(measure_id, channel, language),
        first_name=first_name or "there",
        clinic=clinic or "your clinic",
        phone=phone_callback or "",
        schedule_url=schedule_url or "",
        unsubscribe_url=unsubscribe_url or "",
    )

    # Dispatch
    provider_id = None
    status = "queued"
    failure_reason = None

    if channel == "sms":
        cl = _twilio_client()
        if cl:
            try:
                msg = cl.messages.create(
                    body=body,
                    from_=os.getenv("TWILIO_FROM_NUMBER"),
                    to=to_address,
                )
                provider_id = getattr(msg, "sid", None)
                status = "sent"
            except Exception as e:
                logger.debug("swallowed exception", exc_info=True)
                status, failure_reason = "failed", str(e)[:500]
        else:
            status, failure_reason = "failed", "twilio_unconfigured"
    elif channel == "email":
        cl = _sendgrid_client()
        if cl:
            try:
                from sendgrid.helpers.mail import Mail  # type: ignore
                mail = Mail(
                    from_email=os.getenv("SENDGRID_FROM_EMAIL"),
                    to_emails=to_address,
                    subject=get_email_subject(measure_id, language),
                    html_content=body,
                )
                resp = cl.send(mail)
                provider_id = resp.headers.get("X-Message-Id") if hasattr(resp, "headers") else None
                status = "sent"
            except Exception as e:
                logger.debug("swallowed exception", exc_info=True)
                status, failure_reason = "failed", str(e)[:500]
        else:
            status, failure_reason = "failed", "sendgrid_unconfigured"
    elif channel == "voice":
        # TwiML voice — same Twilio client
        cl = _twilio_client()
        if cl:
            try:
                import html as _html
                call = cl.calls.create(
                    twiml=f"<Response><Say>{_html.escape(body)}</Say></Response>",
                    from_=os.getenv("TWILIO_FROM_NUMBER"),
                    to=to_address,
                )
                provider_id = getattr(call, "sid", None)
                status = "sent"
            except Exception as e:
                logger.debug("swallowed exception", exc_info=True)
                status, failure_reason = "failed", str(e)[:500]
        else:
            status, failure_reason = "failed", "twilio_unconfigured"
    elif channel == "letter":
        # Queue for batch print; mark as 'queued' (printer worker picks up)
        status = "queued"

    mid = _record_message(
        tenant_id=tenant_id, patient_id=patient_id,
        measure_id=measure_id, channel=channel, language=language,
        template_id=f"{measure_id}.{channel}.{language}",
        to_address=to_address, status=status,
        provider_message_id=provider_id,
        failure_reason=failure_reason,
        campaign_id=campaign_id,
    )

    log_phi_access(
        action="OUTREACH_MESSAGE_SENT",
        resource="outreach_messages",
        patient_id=patient_id,
        user=str(actor_user_id or "system"),
        tenant_id=tenant_id,
    )

    return {"message_id": mid, "status": status, "provider_id": provider_id}


# ---------- Funnel ----------

def funnel_counts(
    tenant_id: str,
    campaign_id: int | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
) -> dict[str, int]:
    where = ["tenant_id=%s"]
    params: list = [tenant_id]
    if campaign_id is not None:
        where.append("campaign_id=%s")
        params.append(campaign_id)
    if date_from:
        where.append("queued_at >= %s")
        params.append(date_from)
    if date_to:
        where.append("queued_at <= %s")
        params.append(date_to)
    wsql = " AND ".join(where)
    out: dict[str, int] = {
        s: 0 for s in (
            "queued", "sent", "delivered", "opened", "clicked",
            "scheduled", "completed", "failed", "opted_out",
        )
    }
    with raf_cursor() as cur:
        cur.execute(
            f"""SELECT status, COUNT(*) AS n FROM outreach_messages
                WHERE {wsql}
                GROUP BY status""",
            tuple(params),
        )
        for row in (cur.fetchall() or []):
            if isinstance(row, dict):
                out[str(row["status"])] = int(row["n"])
            else:
                out[str(row[0])] = int(row[1])
    return out


def update_status_by_provider_id(
    provider_id: str, new_status: str, when: datetime | None = None
) -> bool:
    """Webhook updates: flip message status by Twilio/SendGrid message id."""
    if new_status not in {
        "delivered", "opened", "clicked", "scheduled",
        "completed", "failed",
    }:
        raise ValueError(f"Invalid status: {new_status}")

    col_map = {
        "delivered": "delivered_at",
        "opened": "opened_at",
        "clicked": "clicked_at",
        "scheduled": "scheduled_at",
        "completed": "completed_at",
        "failed": "failed_at",
    }
    ts_col = col_map[new_status]
    with raf_cursor() as cur:
        cur.execute(
            f"""UPDATE outreach_messages
                SET status=%s, {ts_col}=COALESCE(%s, NOW())
                WHERE provider_message_id=%s""",
            (new_status, when, provider_id),
        )
        return cur.rowcount > 0


# ---------- Replay + health (DLQ surface) ----------

def get_message_for_replay(tenant_id: str, message_id: int) -> dict | None:
    """Fetch a single message row for replay. Returns None if not found
    or not in a replayable state."""
    with raf_cursor() as cur:
        cur.execute(
            """SELECT id, tenant_id, patient_id, measure_id, channel, language,
                      template_id, to_address, status, failure_reason,
                      campaign_id
               FROM outreach_messages
               WHERE id=%s AND tenant_id=%s""",
            (message_id, tenant_id),
        )
        row = cur.fetchone()
        if not row:
            return None
        rec = dict(row) if isinstance(row, dict) else {
            "id": row[0], "tenant_id": row[1], "patient_id": row[2],
            "measure_id": row[3], "channel": row[4], "language": row[5],
            "template_id": row[6], "to_address": row[7], "status": row[8],
            "failure_reason": row[9], "campaign_id": row[10],
        }
        if rec.get("status") not in ("failed", "queued"):
            return None
        return rec


def replay_message(
    tenant_id: str,
    message_id: int,
    actor_user_id: int,
    first_name: str = "",
    clinic: str = "your clinic",
    phone_callback: str = "",
    schedule_url: str = "",
    unsubscribe_url: str = "",
) -> dict:
    """Re-attempt a failed message via the orchestrator. Re-runs consent +
    cap checks; updates the SAME row (status + failure_reason)."""
    rec = get_message_for_replay(tenant_id, message_id)
    if not rec:
        return {"message_id": message_id, "status": "not_replayable",
                "reason": "row not found or not in failed/queued state"}

    result = enqueue_outreach(
        tenant_id=tenant_id,
        patient_id=int(rec["patient_id"]),
        measure_id=str(rec["measure_id"]),
        channel=str(rec["channel"]),
        language=str(rec.get("language") or "en"),
        to_address=str(rec["to_address"]),
        first_name=first_name,
        clinic=clinic,
        phone_callback=phone_callback,
        schedule_url=schedule_url,
        unsubscribe_url=unsubscribe_url,
        campaign_id=rec.get("campaign_id"),
        actor_user_id=actor_user_id,
    )
    # enqueue_outreach inserts a NEW row. Mark the OLD row as superseded.
    with raf_cursor() as cur:
        cur.execute(
            """UPDATE outreach_messages
               SET failure_reason = CONCAT(COALESCE(failure_reason,''),' | replayed_as=', %s)
               WHERE id=%s AND tenant_id=%s""",
            (str(result.get("message_id", "")), message_id, tenant_id),
        )
    return {
        "original_message_id": message_id,
        "replayed_message_id": result.get("message_id"),
        "status": result.get("status"),
    }


def outreach_health(tenant_id: str) -> dict:
    """SRE / status-page surface for outreach pipeline health."""
    import os
    twilio = bool(os.getenv("TWILIO_ACCOUNT_SID") and os.getenv("TWILIO_AUTH_TOKEN"))
    sendgrid = bool(os.getenv("SENDGRID_API_KEY"))

    failed_unconfigured_24h = 0
    failed_unconfigured_total = 0
    failed_other_24h = 0
    queued_oldest_minutes: float | None = None

    with raf_cursor() as cur:
        cur.execute(
            """SELECT COUNT(*) AS n FROM outreach_messages
               WHERE tenant_id=%s AND status='failed'
                 AND failure_reason IN ('twilio_unconfigured','sendgrid_unconfigured')
                 AND queued_at > NOW() - INTERVAL 24 HOUR""",
            (tenant_id,),
        )
        r = cur.fetchone()
        failed_unconfigured_24h = int(r["n"] if isinstance(r, dict) else r[0]) if r else 0

        cur.execute(
            """SELECT COUNT(*) AS n FROM outreach_messages
               WHERE tenant_id=%s AND status='failed'
                 AND failure_reason IN ('twilio_unconfigured','sendgrid_unconfigured')""",
            (tenant_id,),
        )
        r = cur.fetchone()
        failed_unconfigured_total = int(r["n"] if isinstance(r, dict) else r[0]) if r else 0

        cur.execute(
            """SELECT COUNT(*) AS n FROM outreach_messages
               WHERE tenant_id=%s AND status='failed'
                 AND (failure_reason IS NULL OR failure_reason NOT IN
                      ('twilio_unconfigured','sendgrid_unconfigured'))
                 AND queued_at > NOW() - INTERVAL 24 HOUR""",
            (tenant_id,),
        )
        r = cur.fetchone()
        failed_other_24h = int(r["n"] if isinstance(r, dict) else r[0]) if r else 0

        cur.execute(
            """SELECT TIMESTAMPDIFF(MINUTE, MIN(queued_at), NOW()) AS m
               FROM outreach_messages
               WHERE tenant_id=%s AND status='queued'""",
            (tenant_id,),
        )
        r = cur.fetchone()
        if r:
            v = r["m"] if isinstance(r, dict) else r[0]
            queued_oldest_minutes = float(v) if v is not None else None

    return {
        "tenant_id": tenant_id,
        "twilio_configured": twilio,
        "sendgrid_configured": sendgrid,
        "failed_provider_unconfigured_24h": failed_unconfigured_24h,
        "failed_provider_unconfigured_total": failed_unconfigured_total,
        "failed_other_24h": failed_other_24h,
        "queued_age_oldest_minutes": queued_oldest_minutes,
    }
