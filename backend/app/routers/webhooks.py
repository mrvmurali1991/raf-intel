"""
Webhooks router — register, manage, and monitor webhook subscriptions.

Endpoints
---------
POST   /api/webhooks                    – Register a new webhook
GET    /api/webhooks                    – List webhooks for the current tenant
GET    /api/webhooks/events             – Available event types with descriptions
GET    /api/webhooks/{id}               – Webhook detail
PUT    /api/webhooks/{id}               – Update a webhook
DELETE /api/webhooks/{id}               – Delete a webhook
POST   /api/webhooks/{id}/test          – Send a test event
GET    /api/webhooks/{id}/deliveries    – Delivery history

Authentication: all endpoints require a valid Bearer JWT.
"""
# Removed: from __future__ import annotations (breaks FastAPI schema generation)

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from pydantic import BaseModel, Field, HttpUrl

from app.auth import get_current_user, get_tenant_id, require_permission
from app.rate_limit import limiter
from app.services.webhook_service import (
    WEBHOOK_EVENT_DESCRIPTIONS,
    WEBHOOK_EVENTS,
    delete_webhook,
    get_webhook,
    get_webhook_deliveries,
    list_webhooks,
    register_webhook,
    test_webhook,
    update_webhook,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/webhooks", tags=["webhooks"])


# ---------------------------------------------------------------------------
# Pydantic request / response models
# ---------------------------------------------------------------------------

class WebhookCreateRequest(BaseModel):
    url: HttpUrl = Field(..., description="HTTPS endpoint that will receive POST events")
    events: list[str] = Field(
        ...,
        min_length=1,
        description="List of event types to subscribe to. See GET /api/webhooks/events.",
    )
    secret: str | None = Field(
        default=None,
        min_length=16,
        description="Optional HMAC-SHA256 signing secret. Auto-generated if omitted.",
    )
    description: str | None = Field(
        default=None,
        max_length=255,
        description="Human-readable label for this webhook.",
    )


class WebhookUpdateRequest(BaseModel):
    url: HttpUrl | None = Field(default=None, description="New endpoint URL")
    events: list[str] | None = Field(
        default=None,
        min_length=1,
        description="Replacement list of subscribed event types",
    )
    is_active: bool | None = Field(default=None, description="Enable or disable this webhook")
    description: str | None = Field(default=None, max_length=255)


class WebhookResponse(BaseModel):
    id: int
    tenant_id: str
    url: str
    events: list[str]
    secret: str
    is_active: bool
    description: str | None
    created_at: Any
    updated_at: Any

    model_config = {"from_attributes": True}


class WebhookDeliveryResponse(BaseModel):
    id: int
    webhook_id: int
    event_type: str
    payload: Any
    response_status: int | None
    response_body: str | None
    attempts: int
    delivered_at: Any
    created_at: Any

    model_config = {"from_attributes": True}


class EventTypeResponse(BaseModel):
    event_type: str
    event: str
    description: str


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_webhook_or_404(webhook_id: int, tenant_id: str) -> dict[str, Any]:
    """Load a webhook and enforce tenant ownership; raise 404 if not found."""
    hook = get_webhook(webhook_id)
    if not hook or str(hook.get("tenant_id", "")) != str(tenant_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Webhook not found.")
    return hook


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get(
    "/events",
    summary="List available webhook event types",
    response_model=list[EventTypeResponse],
)
@limiter.limit("60/minute")
def list_event_types(
    request: Request,
    _current_user: dict = Depends(get_current_user),
    _perm: None = Depends(require_permission("webhooks", "read")),
) -> list[dict[str, str]]:
    """
    Return all event types that can be subscribed to via webhooks, together
    with a human-readable description of when each event fires.
    """
    return [
        {
            "event_type": evt,
            "event": evt,
            "description": WEBHOOK_EVENT_DESCRIPTIONS.get(evt, ""),
        }
        for evt in WEBHOOK_EVENTS
    ]


@router.post(
    "",
    summary="Register a webhook",
    status_code=status.HTTP_201_CREATED,
    response_model=WebhookResponse,
)
@limiter.limit("30/minute")
def create_webhook(
    request: Request,
    body: WebhookCreateRequest,
    tenant_id: str = Depends(get_tenant_id),
    _current_user: dict = Depends(get_current_user),
    _perm: None = Depends(require_permission("webhooks", "write")),
) -> dict[str, Any]:
    """
    Register a new webhook endpoint for the current tenant.

    The returned ``secret`` value is the HMAC-SHA256 signing key.  Store it
    securely — it is shown here only once and cannot be retrieved later
    (only rotated by deleting and re-registering the webhook).

    **Signature verification**

    Each delivery includes these headers:

    ```
    X-Webhook-Event:     raf.score.calculated
    X-Webhook-Timestamp: 1711900000
    X-Webhook-Signature: hmac-sha256=<hex>
    ```

    To verify: `HMAC-SHA256(secret, f"{timestamp}.{body_bytes}")`.
    """
    try:
        hook = register_webhook(
            tenant_id=tenant_id,
            url=str(body.url),
            events=body.events,
            secret=body.secret,
            description=body.description,
        )
    except ValueError as exc:
        logger.error("Unexpected error: %s", exc)
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid input")

    logger.info("Webhook %d created for tenant %s", hook["id"], tenant_id)
    return hook


@router.get(
    "",
    summary="List webhooks for the current tenant",
    response_model=list[WebhookResponse],
)
@limiter.limit("60/minute")
def read_webhooks(
    request: Request,
    tenant_id: str = Depends(get_tenant_id),
    _current_user: dict = Depends(get_current_user),
    _perm: None = Depends(require_permission("webhooks", "read")),
) -> list[dict[str, Any]]:
    """Return all registered webhooks (active and inactive) for the caller's tenant."""
    return list_webhooks(tenant_id)


@router.get(
    "/{webhook_id}",
    summary="Get webhook detail",
    response_model=WebhookResponse,
)
@limiter.limit("60/minute")
def read_webhook(
    request: Request,
    webhook_id: int,
    tenant_id: str = Depends(get_tenant_id),
    _current_user: dict = Depends(get_current_user),
    _perm: None = Depends(require_permission("webhooks", "read")),
) -> dict[str, Any]:
    """Fetch full detail for a single webhook. The signing secret is masked."""
    hook = _get_webhook_or_404(webhook_id, tenant_id)
    response = dict(hook)
    # Mask the signing secret — it was shown once on creation and must not be
    # retrievable via the API to limit exposure if tokens are leaked.
    response["secret"] = "***"
    return response


@router.put(
    "/{webhook_id}",
    summary="Update a webhook",
    response_model=WebhookResponse,
)
@limiter.limit("30/minute")
def update_webhook_endpoint(
    request: Request,
    webhook_id: int,
    body: WebhookUpdateRequest,
    tenant_id: str = Depends(get_tenant_id),
    _current_user: dict = Depends(get_current_user),
    _perm: None = Depends(require_permission("webhooks", "write")),
) -> dict[str, Any]:
    """
    Update the URL, subscribed events, active status, or description of a
    webhook.  Only fields present in the request body are changed.
    """
    _get_webhook_or_404(webhook_id, tenant_id)

    try:
        updated = update_webhook(
            webhook_id=webhook_id,
            tenant_id=tenant_id,
            url=str(body.url) if body.url is not None else None,
            events=body.events,
            is_active=body.is_active,
            description=body.description,
        )
    except ValueError as exc:
        logger.error("Unexpected error: %s", exc)
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid input")

    if not updated:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Webhook not found.")

    return updated


@router.delete(
    "/{webhook_id}",
    summary="Delete a webhook",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
@limiter.limit("30/minute")
def remove_webhook(
    request: Request,
    webhook_id: int,
    tenant_id: str = Depends(get_tenant_id),
    _current_user: dict = Depends(get_current_user),
    _perm: None = Depends(require_permission("webhooks", "write")),
):
    """
    Permanently delete a webhook and all of its delivery history.
    This action is irreversible.
    """
    _get_webhook_or_404(webhook_id, tenant_id)

    deleted = delete_webhook(webhook_id, tenant_id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Webhook not found.")


@router.post(
    "/{webhook_id}/test",
    summary="Send a test event",
)
@limiter.limit("30/minute")
def send_test_event(
    request: Request,
    webhook_id: int,
    tenant_id: str = Depends(get_tenant_id),
    _current_user: dict = Depends(get_current_user),
    _perm: None = Depends(require_permission("webhooks", "write")),
) -> dict[str, Any]:
    """
    Deliver a synthetic ``test`` event to the webhook endpoint.

    Useful for verifying that the endpoint is reachable and that your
    signature verification logic is working correctly.

    Returns the HTTP status code and response body from the target URL.
    """
    _get_webhook_or_404(webhook_id, tenant_id)

    try:
        result = test_webhook(webhook_id, tenant_id)
    except ValueError as exc:
        logger.error("Unexpected error: %s", exc)
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Resource not found")

    return result


@router.get(
    "/{webhook_id}/deliveries",
    summary="Webhook delivery history",
    response_model=list[WebhookDeliveryResponse],
)
@limiter.limit("60/minute")
def read_deliveries(
    request: Request,
    webhook_id: int,
    limit: int = Query(default=50, ge=1, le=200, description="Max records to return"),
    offset: int = Query(default=0, ge=0, description="Pagination offset"),
    tenant_id: str = Depends(get_tenant_id),
    _current_user: dict = Depends(get_current_user),
    _perm: None = Depends(require_permission("webhooks", "read")),
) -> list[dict[str, Any]]:
    """
    Return the delivery history for a webhook, most-recent first.

    Each record shows the HTTP status code, truncated response body, number
    of delivery attempts, and the timestamp of the first successful delivery
    (if any).
    """
    _get_webhook_or_404(webhook_id, tenant_id)

    try:
        deliveries = get_webhook_deliveries(
            webhook_id=webhook_id,
            tenant_id=tenant_id,
            limit=limit,
            offset=offset,
        )
    except ValueError as exc:
        logger.error("Unexpected error: %s", exc)
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Resource not found")

    return deliveries
