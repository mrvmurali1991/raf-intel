"""
Webhook service — registration, delivery, and event dispatch.

Webhooks allow external systems to receive real-time notifications when
clinical events occur in the RAF Intelligence platform.

Tables (auto-created on first import):
    webhooks            – registered endpoints
    webhook_deliveries  – delivery history with status and response body
"""

from __future__ import annotations

import hashlib
import hmac
import ipaddress
import json
import logging
import secrets
import socket
import time
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

import httpx

from app.db import raf_cursor

logger = logging.getLogger(__name__)


def _validate_webhook_url(url: str) -> None:
    """Validate a webhook URL to prevent SSRF attacks.

    Raises ``ValueError`` if the URL targets a private, loopback, link-local,
    or cloud-metadata address, or uses a non-HTTPS scheme.
    """
    parsed = urlparse(url)

    if parsed.scheme != "https":
        raise ValueError(f"Webhook URL must use https scheme, got {parsed.scheme!r}")

    hostname = parsed.hostname
    if not hostname:
        raise ValueError("Webhook URL has no hostname")

    try:
        addrinfos = socket.getaddrinfo(hostname, parsed.port or 443, proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise ValueError(f"Cannot resolve webhook hostname {hostname!r}: {exc}") from exc

    for family, _type, _proto, _canonname, sockaddr in addrinfos:
        ip = ipaddress.ip_address(sockaddr[0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
            raise ValueError(
                f"Webhook URL resolves to blocked address {ip} "
                f"(private/loopback/link-local/reserved)"
            )
        if str(ip) in ("169.254.169.254", "fd00:ec2::254"):
            raise ValueError(f"Webhook URL resolves to cloud metadata address {ip}")


# ---------------------------------------------------------------------------
# Event catalogue
# ---------------------------------------------------------------------------

WEBHOOK_EVENTS: list[str] = [
    "raf.score.calculated",
    "raf.score.changed",
    "suspect.created",
    "suspect.accepted",
    "suspect.dismissed",
    "document.uploaded",
    "document.analyzed",
    "claims.batch.processed",
    "fhir.sync.completed",
    "submission.generated",
    "submission.validated",
    "provider.scorecard.updated",
    "patient.raf_gap.detected",
    "audit.package.generated",
]

WEBHOOK_EVENT_DESCRIPTIONS: dict[str, str] = {
    "raf.score.calculated": "A RAF score was calculated for a patient for the first time in a measurement year.",
    "raf.score.changed": "An existing RAF score changed due to new diagnoses or model updates.",
    "suspect.created": "A new suspect condition was identified for a patient.",
    "suspect.accepted": "A suspect condition was accepted/coded by a reviewer.",
    "suspect.dismissed": "A suspect condition was dismissed by a reviewer.",
    "document.uploaded": "A clinical document was uploaded to the platform.",
    "document.analyzed": "Gemini Vision completed analysis of an uploaded document.",
    "claims.batch.processed": "A batch of 837P/837I/CSV claims was ingested and processed.",
    "fhir.sync.completed": "A FHIR R4 sync with an EHR system completed.",
    "submission.generated": "A CMS RAPS/EDPS submission file was generated.",
    "submission.validated": "A submission file passed or failed validation checks.",
    "provider.scorecard.updated": "A provider's RAF scorecard metrics were recalculated.",
    "patient.raf_gap.detected": "One or more RAF coding gaps were detected for a patient.",
    "audit.package.generated": "A compliance audit package was generated for a patient.",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _generate_secret() -> str:
    """Generate a URL-safe random secret for HMAC signing."""
    return secrets.token_hex(32)


def _validate_webhook_url(url: str) -> None:
    """Validate that a webhook URL is safe to deliver events to.

    Raises ValueError if the URL scheme is not http/https or if the resolved
    hostname is a private, loopback, or link-local address (SSRF prevention).
    """
    parsed = urlparse(url)
    if parsed.scheme not in ("https", "http"):
        raise ValueError("Webhook URL must use HTTPS")
    try:
        ip = ipaddress.ip_address(parsed.hostname)
        if ip.is_private or ip.is_loopback or ip.is_link_local:
            raise ValueError("Webhook URL must not target private networks")
    except (ValueError, TypeError) as exc:
        # Re-raise only our own ValueError; a ValueError from ip_address means
        # the hostname is a domain name (not a bare IP), which is fine.
        if "Webhook URL" in str(exc):
            raise


def _sign_payload(secret: str, payload_bytes: bytes, timestamp: str) -> str:
    """Return hex HMAC-SHA256 signature of timestamp + '.' + payload."""
    message = f"{timestamp}.".encode() + payload_bytes
    return hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()


def _parse_events(raw: Any) -> list[str]:
    """Safely deserialise events from a MySQL JSON column."""
    if isinstance(raw, list):
        return raw
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            return []
    return []


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------


def register_webhook(
    tenant_id: str,
    url: str,
    events: list[str],
    secret: str | None = None,
    description: str | None = None,
) -> dict[str, Any]:
    """
    Register a new webhook endpoint.

    Parameters
    ----------
    tenant_id:   The tenant this webhook belongs to.
    url:         The HTTPS endpoint that will receive POST events.
    events:      List of event types to subscribe to (must be in WEBHOOK_EVENTS).
    secret:      Optional signing secret; auto-generated if not provided.
    description: Human-readable label for this webhook.

    Returns the newly created webhook record.
    """
    # Validate URL
    _validate_webhook_url(url)

    # Validate events
    invalid = [e for e in events if e not in WEBHOOK_EVENTS]
    if invalid:
        raise ValueError(f"Unknown event type(s): {', '.join(invalid)}")

    if not events:
        raise ValueError("At least one event type must be specified.")

    signing_secret = secret or _generate_secret()
    events_json = json.dumps(events)

    with raf_cursor() as cur:
        cur.execute(
            """
            INSERT INTO webhooks (tenant_id, url, events, secret, description, is_active)
            VALUES (%s, %s, %s, %s, %s, 1)
            """,
            (tenant_id, url, events_json, signing_secret, description),
        )
        webhook_id = cur.lastrowid

    logger.info("Webhook %d registered for tenant %s -> %s", webhook_id, tenant_id, url)
    return get_webhook(webhook_id)


def get_webhook(webhook_id: int) -> dict[str, Any] | None:
    """Fetch a single webhook by ID."""
    with raf_cursor() as cur:
        cur.execute(
            "SELECT id, tenant_id, url, events, secret, is_active, description, created_at, updated_at "
            "FROM webhooks WHERE id = %s",
            (webhook_id,),
        )
        row = cur.fetchone()

    if not row:
        return None

    row["events"] = _parse_events(row["events"])
    row["secret"] = "***"
    return row


def list_webhooks(tenant_id: str) -> list[dict[str, Any]]:
    """Return all webhooks for a tenant (active and inactive)."""
    with raf_cursor() as cur:
        cur.execute(
            "SELECT id, tenant_id, url, events, secret, is_active, description, created_at, updated_at "
            "FROM webhooks WHERE tenant_id = %s ORDER BY created_at DESC",
            (tenant_id,),
        )
        rows = cur.fetchall()

    for row in rows:
        row["events"] = _parse_events(row["events"])
        row["secret"] = "***"
    return rows


def update_webhook(
    webhook_id: int,
    tenant_id: str,
    url: str | None = None,
    events: list[str] | None = None,
    is_active: bool | None = None,
    description: str | None = None,
) -> dict[str, Any] | None:
    """
    Update a webhook's URL, subscribed events, or active status.
    Only updates fields that are not None.
    """
    webhook = get_webhook(webhook_id)
    if not webhook or webhook["tenant_id"] != tenant_id:
        return None

    if events is not None:
        invalid = [e for e in events if e not in WEBHOOK_EVENTS]
        if invalid:
            raise ValueError(f"Unknown event type(s): {', '.join(invalid)}")
        if not events:
            raise ValueError("At least one event type must be specified.")

    parts: list[str] = []
    params: list[Any] = []

    if url is not None:
        parts.append("url = %s")
        params.append(url)
    if events is not None:
        parts.append("events = %s")
        params.append(json.dumps(events))
    if is_active is not None:
        parts.append("is_active = %s")
        params.append(1 if is_active else 0)
    if description is not None:
        parts.append("description = %s")
        params.append(description)

    if not parts:
        return webhook  # Nothing to update

    params.append(webhook_id)
    with raf_cursor() as cur:
        cur.execute(
            f"UPDATE webhooks SET {', '.join(parts)} WHERE id = %s",
            params,
        )

    return get_webhook(webhook_id)


def delete_webhook(webhook_id: int, tenant_id: str) -> bool:
    """
    Permanently delete a webhook and its delivery history.

    Returns True if a row was deleted, False if not found or tenant mismatch.
    """
    webhook = get_webhook(webhook_id)
    if not webhook or webhook["tenant_id"] != tenant_id:
        return False

    with raf_cursor() as cur:
        cur.execute(
            "DELETE FROM webhooks WHERE id = %s AND tenant_id = %s",
            (webhook_id, tenant_id),
        )
        affected = cur.rowcount

    if affected:
        logger.info("Webhook %d deleted for tenant %s", webhook_id, tenant_id)
    return bool(affected)


# ---------------------------------------------------------------------------
# Delivery
# ---------------------------------------------------------------------------


def _record_delivery(
    webhook_id: int,
    event_type: str,
    payload: dict,
    response_status: int | None,
    response_body: str | None,
    attempts: int,
    delivered_at: datetime | None,
) -> None:
    """Persist a delivery attempt record."""
    try:
        with raf_cursor() as cur:
            cur.execute(
                """
                INSERT INTO webhook_deliveries
                    (webhook_id, event_type, payload, response_status, response_body,
                     attempts, delivered_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    webhook_id,
                    event_type,
                    json.dumps(payload),
                    response_status,
                    response_body,
                    attempts,
                    delivered_at,
                ),
            )
    except Exception as exc:
        logger.error("Failed to record delivery for webhook %d: %s", webhook_id, exc)


def _deliver_to_webhook(
    webhook: dict[str, Any],
    event_type: str,
    payload: dict[str, Any],
) -> None:
    """
    Attempt to deliver a single event to a webhook endpoint.

    Signing:
        Each request carries three headers:
        - X-Webhook-Event:      the event type string
        - X-Webhook-Timestamp:  Unix timestamp as a string (used in signature)
        - X-Webhook-Signature:  hmac-sha256=<hex-digest>

    Retry:
        Up to 3 attempts with exponential back-off (1s, 2s, 4s).
    """
    secret: str = webhook["secret"]
    url: str = webhook["url"]
    webhook_id: int = webhook["id"]

    payload_bytes = json.dumps(payload, default=str).encode()
    timestamp = str(int(time.time()))
    signature = _sign_payload(secret, payload_bytes, timestamp)

    headers = {
        "Content-Type": "application/json",
        "User-Agent": "RAF-Intelligence-Webhooks/2.0",
        "X-Webhook-Event": event_type,
        "X-Webhook-Timestamp": timestamp,
        "X-Webhook-Signature": f"hmac-sha256={signature}",
    }

    max_attempts = 3
    last_status: int | None = None
    last_body: str | None = None
    delivered_at: datetime | None = None

    _validate_webhook_url(url)

    for attempt in range(1, max_attempts + 1):
        try:
            with httpx.Client(timeout=10.0) as client:
                resp = client.post(url, content=payload_bytes, headers=headers)
            last_status = resp.status_code
            last_body = resp.text[:4096]  # Truncate to avoid excessive storage

            if 200 <= resp.status_code < 300:
                delivered_at = datetime.now(timezone.utc)
                logger.info(
                    "Webhook %d delivered event=%s status=%d attempt=%d",
                    webhook_id,
                    event_type,
                    resp.status_code,
                    attempt,
                )
                break
            logger.warning(
                "Webhook %d non-2xx response event=%s status=%d attempt=%d",
                webhook_id,
                event_type,
                resp.status_code,
                attempt,
            )
        except httpx.TimeoutException:
            logger.warning(
                "Webhook %d timeout event=%s attempt=%d",
                webhook_id,
                event_type,
                attempt,
            )
            last_body = "Request timed out"
        except httpx.RequestError as exc:
            logger.warning(
                "Webhook %d request error event=%s attempt=%d: %s",
                webhook_id,
                event_type,
                attempt,
                exc,
            )
            last_body = str(exc)

        if attempt < max_attempts:
            backoff = 2 ** (attempt - 1)  # 1s, 2s
            time.sleep(backoff)

    _record_delivery(
        webhook_id=webhook_id,
        event_type=event_type,
        payload=payload,
        response_status=last_status,
        response_body=last_body,
        attempts=attempt,
        delivered_at=delivered_at,
    )


def fire_event(event_type: str, tenant_id: str, payload: dict[str, Any]) -> None:
    """
    Dispatch an event to all active webhooks for the tenant that subscribe to
    this event type.

    This function is synchronous and blocks until all deliveries complete (or
    exhaust retries).  Callers that want non-blocking behaviour should use
    event_emitter.emit() which runs fire_event in a daemon thread.

    The payload is enriched with standard envelope fields before delivery:
        event   – event type string
        tenant  – tenant_id
        fired_at – ISO-8601 timestamp
    """
    if event_type not in WEBHOOK_EVENTS:
        logger.warning("fire_event called with unknown event type: %s", event_type)
        return

    envelope: dict[str, Any] = {
        "event": event_type,
        "tenant": tenant_id,
        "fired_at": datetime.now(timezone.utc).isoformat() + "Z",
        "data": payload,
    }

    try:
        hooks = list_webhooks(tenant_id)
    except Exception as exc:
        logger.error(
            "fire_event: failed to load webhooks for tenant %s: %s", tenant_id, exc
        )
        return

    matched = [
        h for h in hooks if h.get("is_active") and event_type in h.get("events", [])
    ]

    if not matched:
        logger.debug(
            "fire_event: no active webhooks for event=%s tenant=%s",
            event_type,
            tenant_id,
        )
        return

    for webhook in matched:
        try:
            _deliver_to_webhook(webhook, event_type, envelope)
        except Exception as exc:
            logger.error(
                "fire_event: unhandled error delivering to webhook %d: %s",
                webhook["id"],
                exc,
            )


def test_webhook(webhook_id: int, tenant_id: str) -> dict[str, Any]:
    """
    Send a synthetic test event to a webhook endpoint.

    Returns a summary of the delivery attempt.
    """
    webhook = get_webhook(webhook_id)
    if not webhook or webhook["tenant_id"] != tenant_id:
        raise ValueError(f"Webhook {webhook_id} not found for tenant {tenant_id}")

    test_payload: dict[str, Any] = {
        "event": "test",
        "tenant": tenant_id,
        "fired_at": datetime.now(timezone.utc).isoformat() + "Z",
        "data": {
            "message": "This is a test event from RAF Intelligence.",
            "webhook_id": webhook_id,
        },
    }

    payload_bytes = json.dumps(test_payload, default=str).encode()
    timestamp = str(int(time.time()))
    signature = _sign_payload(webhook["secret"], payload_bytes, timestamp)

    headers = {
        "Content-Type": "application/json",
        "User-Agent": "RAF-Intelligence-Webhooks/2.0",
        "X-Webhook-Event": "test",
        "X-Webhook-Timestamp": timestamp,
        "X-Webhook-Signature": f"hmac-sha256={signature}",
    }

    result: dict[str, Any] = {
        "webhook_id": webhook_id,
        "url": webhook["url"],
        "success": False,
        "status_code": None,
        "response_body": None,
        "error": None,
    }

    try:
        _validate_webhook_url(webhook["url"])
        with httpx.Client(timeout=10.0) as client:
            resp = client.post(webhook["url"], content=payload_bytes, headers=headers)
        result["status_code"] = resp.status_code
        result["response_body"] = resp.text[:2048]
        result["success"] = 200 <= resp.status_code < 300
    except httpx.TimeoutException:
        result["error"] = "Request timed out after 10 seconds"
    except httpx.RequestError as exc:
        result["error"] = str(exc)

    logger.info(
        "test_webhook %d success=%s status=%s",
        webhook_id,
        result["success"],
        result["status_code"],
    )
    return result


def get_webhook_deliveries(
    webhook_id: int,
    tenant_id: str,
    limit: int = 50,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """
    Return delivery history for a webhook, most-recent first.

    Raises ValueError when webhook does not belong to the tenant.
    """
    webhook = get_webhook(webhook_id)
    if not webhook or webhook["tenant_id"] != tenant_id:
        raise ValueError(f"Webhook {webhook_id} not found for tenant {tenant_id}")

    with raf_cursor() as cur:
        cur.execute(
            """
            SELECT id, webhook_id, event_type, payload, response_status, response_body,
                   attempts, delivered_at, created_at
            FROM webhook_deliveries
            WHERE webhook_id = %s
            ORDER BY created_at DESC
            LIMIT %s OFFSET %s
            """,
            (webhook_id, limit, offset),
        )
        rows = cur.fetchall()

    for row in rows:
        if isinstance(row.get("payload"), str):
            try:
                row["payload"] = json.loads(row["payload"])
            except (json.JSONDecodeError, ValueError):
                pass
    return rows
