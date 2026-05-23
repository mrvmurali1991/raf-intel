"""Patient outreach v2 — production multi-channel orchestration.

Endpoints
---------
POST /api/outreach/enqueue                Queue a single outreach message
POST /api/outreach/consent/opt-out        Record opt-out
POST /api/outreach/consent/opt-in         Record opt-in
GET  /api/outreach/funnel                 Funnel counts (queued→completed)
POST /api/webhooks/twilio/sms             Twilio SMS delivery + STOP keyword
POST /api/webhooks/twilio/voice           Twilio voice completion
POST /api/webhooks/sendgrid               SendGrid email events
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import os
from datetime import datetime

from fastapi import APIRouter, Body, Depends, Header, HTTPException, Query, Request
from pydantic import BaseModel, Field

from app.auth import get_current_user, get_tenant_id, require_permission
from app.services.outreach import orchestrator as orch

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/outreach", tags=["outreach"])
webhook_router = APIRouter(prefix="/api/webhooks", tags=["webhooks"])


# ----------- Models -----------

class EnqueueRequest(BaseModel):
    patient_id: int
    measure_id: str = Field(..., min_length=2, max_length=16)
    channel: str = Field(..., pattern="^(sms|email|voice|letter)$")
    language: str = Field(default="en", pattern="^(en|es)$")
    to_address: str = Field(..., max_length=320)
    first_name: str = Field(default="", max_length=100)
    clinic: str = Field(default="your clinic", max_length=200)
    phone_callback: str = Field(default="", max_length=32)
    schedule_url: str = Field(default="", max_length=500)
    unsubscribe_url: str = Field(default="", max_length=500)
    campaign_id: int | None = None


class OptInRequest(BaseModel):
    patient_id: int
    channel: str = Field(..., pattern="^(sms|email|voice|letter)$")
    method: str = "portal_checkbox"


class OptOutRequest(BaseModel):
    patient_id: int
    channel: str = Field(..., pattern="^(sms|email|voice|letter)$")
    reason: str = ""


# ----------- Authed endpoints -----------

@router.post("/enqueue", summary="Queue an outreach message")
def enqueue_outreach(
    body: EnqueueRequest,
    tenant_id: str = Depends(get_tenant_id),
    current_user: dict = Depends(get_current_user),
    _perm: None = Depends(require_permission("reports", "write")),
):
    user_id = int(current_user.get("id") or current_user.get("user_id") or 0)
    result = orch.enqueue_outreach(
        tenant_id=tenant_id,
        patient_id=body.patient_id,
        measure_id=body.measure_id,
        channel=body.channel,
        language=body.language,
        to_address=body.to_address,
        first_name=body.first_name,
        clinic=body.clinic,
        phone_callback=body.phone_callback,
        schedule_url=body.schedule_url,
        unsubscribe_url=body.unsubscribe_url,
        campaign_id=body.campaign_id,
        actor_user_id=user_id,
    )
    return result


@router.post("/consent/opt-in")
def opt_in(
    body: OptInRequest,
    tenant_id: str = Depends(get_tenant_id),
    _user: dict = Depends(get_current_user),
):
    orch.record_opt_in(tenant_id, body.patient_id, body.channel, body.method)
    return {"patient_id": body.patient_id, "channel": body.channel,
            "consent": "opted_in"}


@router.post("/consent/opt-out")
def opt_out(
    body: OptOutRequest,
    tenant_id: str = Depends(get_tenant_id),
    _user: dict = Depends(get_current_user),
):
    orch.record_opt_out(tenant_id, body.patient_id, body.channel, body.reason)
    return {"patient_id": body.patient_id, "channel": body.channel,
            "consent": "opted_out"}


@router.get("/health", summary="Outreach pipeline health (SRE probe)")
def health(
    tenant_id: str = Depends(get_tenant_id),
    _user: dict = Depends(get_current_user),
):
    return orch.outreach_health(tenant_id)


@router.post("/replay/{message_id}", summary="Replay a failed outreach message")
def replay_one(
    message_id: int,
    tenant_id: str = Depends(get_tenant_id),
    current_user: dict = Depends(get_current_user),
    _perm: None = Depends(require_permission("reports", "write")),
):
    role = (current_user.get("role") or "").lower()
    if role not in {"admin", "manager"}:
        raise HTTPException(status_code=403,
                            detail="Only admin/manager may replay outreach messages")
    user_id = int(current_user.get("id") or current_user.get("user_id") or 0)
    return orch.replay_message(tenant_id, message_id, user_id)


class ReplayBatchRequest(BaseModel):
    message_ids: list[int] = Field(..., max_length=1000)
    dry_run: bool = False


@router.post("/replay-batch", summary="Replay up to 1000 failed messages")
def replay_batch(
    body: ReplayBatchRequest,
    tenant_id: str = Depends(get_tenant_id),
    current_user: dict = Depends(get_current_user),
    _perm: None = Depends(require_permission("reports", "write")),
):
    role = (current_user.get("role") or "").lower()
    if role not in {"admin", "manager"}:
        raise HTTPException(status_code=403,
                            detail="Only admin/manager may replay outreach messages")
    user_id = int(current_user.get("id") or current_user.get("user_id") or 0)

    if body.dry_run:
        replayable = sum(
            1 for mid in body.message_ids
            if orch.get_message_for_replay(tenant_id, mid) is not None
        )
        return {
            "dry_run": True,
            "requested": len(body.message_ids),
            "replayable": replayable,
            "would_skip": len(body.message_ids) - replayable,
        }

    results = {"replayed": 0, "still_failed": 0,
              "skipped_opted_out": 0, "not_replayable": 0}
    for mid in body.message_ids:
        r = orch.replay_message(tenant_id, mid, user_id)
        st = r.get("status")
        if st == "sent":
            results["replayed"] += 1
        elif st == "opted_out":
            results["skipped_opted_out"] += 1
        elif st == "not_replayable":
            results["not_replayable"] += 1
        else:
            results["still_failed"] += 1
    return results


@router.get("/funnel", summary="Outreach funnel counts")
def funnel(
    campaign_id: int | None = Query(default=None),
    date_from: str | None = Query(default=None),
    date_to: str | None = Query(default=None),
    tenant_id: str = Depends(get_tenant_id),
    _perm: None = Depends(require_permission("reports", "read")),
):
    return {
        "tenant_id": tenant_id,
        "campaign_id": campaign_id,
        "counts": orch.funnel_counts(tenant_id, campaign_id, date_from, date_to),
    }


# ----------- Webhooks (unauthenticated, signature-verified) -----------

def _verify_twilio(sig: str, url: str, params: dict) -> bool:
    tok = os.getenv("TWILIO_AUTH_TOKEN")
    if not tok or not sig:
        return False
    s = url + "".join(f"{k}{params[k]}" for k in sorted(params))
    digest = hmac.new(tok.encode(), s.encode(), hashlib.sha1).digest()
    import base64
    expected = base64.b64encode(digest).decode()
    return hmac.compare_digest(expected, sig)


def _verify_sendgrid(sig: str, ts: str, payload: bytes) -> bool:
    key = os.getenv("SENDGRID_WEBHOOK_KEY")
    if not key or not sig or not ts:
        return False
    # ECDSA signature would be ideal; demo uses HMAC-SHA256
    h = hmac.new(key.encode(), (ts + payload.decode()).encode(),
                 hashlib.sha256).hexdigest()
    return hmac.compare_digest(h, sig)


@webhook_router.post("/twilio/sms")
async def twilio_sms_webhook(
    request: Request,
    x_twilio_signature: str = Header(default=""),
):
    form = await request.form()
    params = {k: form[k] for k in form}
    url = str(request.url)
    # Skip signature check in dev when no token set
    if os.getenv("TWILIO_AUTH_TOKEN") and not _verify_twilio(
            x_twilio_signature, url, params):
        raise HTTPException(status_code=403, detail="bad signature")

    msg_sid = params.get("MessageSid", "")
    msg_body = (params.get("Body") or "").strip().upper()
    from_num = params.get("From", "")

    if msg_body in ("STOP", "STOPALL", "UNSUBSCRIBE", "CANCEL", "END", "QUIT"):
        # Find patient by phone — best-effort
        from app.db import raf_cursor
        with raf_cursor() as cur:
            cur.execute(
                """SELECT patient_id, tenant_id FROM outreach_messages
                   WHERE to_address=%s ORDER BY id DESC LIMIT 1""",
                (from_num,),
            )
            row = cur.fetchone()
            if row:
                if isinstance(row, dict):
                    pid, tid = int(row["patient_id"]), str(row["tenant_id"])
                else:
                    pid, tid = int(row[0]), str(row[1])
                orch.record_opt_out(tid, pid, "sms",
                                    reason=f"keyword:{msg_body}")
                logger.info("Recorded SMS opt-out for patient %s", pid)
        return {"status": "opt_out_recorded"}

    # Delivery status update
    status = (params.get("MessageStatus") or "").lower()
    if status in {"delivered", "failed", "undelivered"}:
        ns = "delivered" if status == "delivered" else "failed"
        orch.update_status_by_provider_id(msg_sid, ns)
    return {"status": "ok"}


@webhook_router.post("/twilio/voice")
async def twilio_voice_webhook(
    request: Request,
    x_twilio_signature: str = Header(default=""),
):
    form = await request.form()
    params = {k: form[k] for k in form}
    if os.getenv("TWILIO_AUTH_TOKEN") and not _verify_twilio(
            x_twilio_signature, str(request.url), params):
        raise HTTPException(status_code=403, detail="bad signature")
    call_sid = params.get("CallSid", "")
    call_status = (params.get("CallStatus") or "").lower()
    if call_status == "completed":
        orch.update_status_by_provider_id(call_sid, "delivered")
    elif call_status in ("failed", "busy", "no-answer"):
        orch.update_status_by_provider_id(call_sid, "failed")
    return {"status": "ok"}


@webhook_router.post("/sendgrid")
async def sendgrid_webhook(
    request: Request,
    x_twilio_email_event_webhook_signature: str = Header(default=""),
    x_twilio_email_event_webhook_timestamp: str = Header(default=""),
):
    body = await request.body()
    if os.getenv("SENDGRID_WEBHOOK_KEY") and not _verify_sendgrid(
        x_twilio_email_event_webhook_signature,
        x_twilio_email_event_webhook_timestamp,
        body,
    ):
        raise HTTPException(status_code=403, detail="bad signature")

    import json
    events = json.loads(body.decode())
    for ev in events:
        mid = ev.get("sg_message_id", "").split(".")[0] or ev.get("smtp-id", "")
        evt = (ev.get("event") or "").lower()
        ts = ev.get("timestamp")
        when = datetime.fromtimestamp(ts) if ts else None
        if evt == "delivered":
            orch.update_status_by_provider_id(mid, "delivered", when)
        elif evt in ("open", "opened"):
            orch.update_status_by_provider_id(mid, "opened", when)
        elif evt in ("click", "clicked"):
            orch.update_status_by_provider_id(mid, "clicked", when)
        elif evt in ("bounce", "dropped", "spam_report"):
            orch.update_status_by_provider_id(mid, "failed", when)
    return {"status": "ok", "events_processed": len(events)}
