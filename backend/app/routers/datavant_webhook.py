"""
Datavant inbound webhook receiver.

Datavant calls this endpoint when a chart request is fulfilled and documents
are available for download.  The endpoint verifies the HMAC-SHA256 signature
carried in the ``X-Datavant-Signature`` header before any processing.

Routes
------
POST /api/webhooks/datavant  — receive "chart ready" notification from Datavant
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import os

from fastapi import APIRouter, Header, HTTPException, Request, status

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/webhooks", tags=["datavant-webhook"])

_WEBHOOK_SECRET_ENV = "DATAVANT_WEBHOOK_SECRET"


def _verify_signature(body: bytes, signature_header: str | None) -> bool:
    """Return True when the request body matches the HMAC-SHA256 signature.

    The Datavant Switchboard signs requests with::

        X-Datavant-Signature: sha256=<hex-digest>

    The signing key is read from the ``DATAVANT_WEBHOOK_SECRET`` environment
    variable at call time so tests can set it before each request.

    Args:
        body: Raw request body bytes.
        signature_header: Value of the ``X-Datavant-Signature`` header.

    Returns:
        True when the computed HMAC matches the provided digest.
    """
    if not signature_header:
        return False
    secret = os.getenv(_WEBHOOK_SECRET_ENV, "")
    if not secret:
        logger.warning("datavant_webhook: %s is not configured; all webhooks rejected", _WEBHOOK_SECRET_ENV)
        return False
    # Header format: "sha256=<hex>"
    try:
        algo, provided_digest = signature_header.split("=", 1)
    except ValueError:
        return False
    if algo != "sha256":
        return False
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, provided_digest)


@router.post("/datavant", status_code=status.HTTP_200_OK)
async def receive_datavant_webhook(
    request: Request,
    x_datavant_signature: str | None = Header(default=None),
) -> dict[str, bool]:
    """Receive a Datavant Switchboard "chart ready" notification.

    The endpoint:

    1. Reads the raw body for HMAC verification.
    2. Returns **403** if the signature is absent or invalid.
    3. On a verified payload, enqueues a Celery task
       ``raf.partners.datavant_ingest`` with the ``document_id`` from the
       notification body.
    4. Returns ``{"accepted": true}`` immediately (Datavant expects a fast 200).

    Args:
        request: FastAPI request object (used to read the raw body).
        x_datavant_signature: HMAC-SHA256 signature from Datavant.

    Returns:
        ``{"accepted": true}`` on success.

    Raises:
        HTTPException 403: When the signature is missing or invalid.
    """
    body = await request.body()

    if not _verify_signature(body, x_datavant_signature):
        logger.warning("datavant_webhook: invalid or missing signature — request rejected")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid webhook signature",
        )

    try:
        import json  # noqa: PLC0415
        payload = json.loads(body)
    except Exception as exc:
        logger.error("datavant_webhook: failed to parse JSON body: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid JSON payload",
        ) from exc

    document_id: str = payload.get("document_id", "")
    request_id: str = payload.get("request_id", "")

    if not document_id:
        logger.warning("datavant_webhook: payload missing document_id; skipping enqueue")
    else:
        try:
            from app.services.celery_tasks import task_datavant_ingest  # noqa: PLC0415
            task_datavant_ingest.delay(document_id=document_id, request_id=request_id)
            logger.info(
                "datavant_webhook: enqueued datavant_ingest document_id=%s request_id=%s",
                document_id,
                request_id,
            )
        except Exception as exc:
            # Never crash the webhook response — Datavant requires a 200 to
            # prevent retries.  Log the failure and proceed.
            logger.error("datavant_webhook: failed to enqueue task: %s", exc)

    return {"accepted": True}
