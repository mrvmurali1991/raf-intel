"""
ADT Feed Real-Time Listener Router
====================================

Endpoints
---------
GET    /api/adt/connections                    — List ADT connections
POST   /api/adt/connections                    — Create a connection config
PUT    /api/adt/connections/{id}               — Update a connection config
POST   /api/adt/connections/{id}/start         — Start the MLLP listener
POST   /api/adt/connections/{id}/stop          — Stop the MLLP listener
GET    /api/adt/connections/{id}/status        — Listener runtime health
GET    /api/adt/messages                       — List received ADT messages
GET    /api/adt/messages/{id}                  — Single message detail (includes raw)
POST   /api/adt/messages/replay/{id}           — Reprocess a stored message
GET    /api/adt/subscriptions                  — List webhook subscriptions
POST   /api/adt/subscriptions                  — Subscribe to ADT events
GET    /api/adt/dashboard                      — Volume + error-rate aggregates

Authentication: all endpoints require a valid Bearer JWT.
"""
# Removed: from __future__ import annotations (breaks FastAPI schema generation)

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field, HttpUrl

from app.auth import get_current_user, get_tenant_id, require_permission
from app.services.adt_listener_service import (
    create_connection,
    create_subscription,
    get_connection,
    get_dashboard,
    get_listener_status,
    get_message,
    list_connections,
    list_messages,
    list_subscriptions,
    replay_message,
    start_listener,
    stop_listener,
    update_connection,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/adt", tags=["adt"])


# ---------------------------------------------------------------------------
# Pydantic request / response models
# ---------------------------------------------------------------------------


class ConnectionCreateRequest(BaseModel):
    name: str = Field(..., max_length=255, description="Human-readable label")
    host: str = Field(
        default="0.0.0.0",
        max_length=255,
        description="Bind address (inbound) or remote host (outbound)",
    )
    port: int = Field(
        default=2575,
        ge=1,
        le=65535,
        description="TCP port number. MLLP default is 2575.",
    )
    direction: str = Field(
        default="inbound",
        pattern="^(inbound|outbound)$",
        description="inbound = we listen; outbound = we connect to remote",
    )
    protocol: str = Field(
        default="mllp",
        pattern="^(mllp|tcp)$",
        description="Message framing protocol",
    )
    auto_process: bool = Field(
        default=True,
        description="Automatically parse messages and upsert patient records",
    )


class ConnectionUpdateRequest(BaseModel):
    name: str | None = Field(default=None, max_length=255)
    host: str | None = Field(default=None, max_length=255)
    port: int | None = Field(default=None, ge=1, le=65535)
    direction: str | None = Field(default=None, pattern="^(inbound|outbound)$")
    protocol: str | None = Field(default=None, pattern="^(mllp|tcp)$")
    auto_process: bool | None = Field(default=None)


class ConnectionResponse(BaseModel):
    id: int
    tenant_id: str
    name: str
    host: str
    port: int
    direction: str
    protocol: str
    status: str
    auto_process: bool
    last_message_at: Any
    message_count: int
    error_count: int
    created_at: Any
    updated_at: Any

    model_config = {"from_attributes": True}


class SubscriptionCreateRequest(BaseModel):
    event_type: str = Field(
        ...,
        description=(
            "ADT event to subscribe to. One of: "
            "adt.admit, adt.transfer, adt.discharge, adt.register, adt.update, adt.*"
        ),
    )
    webhook_url: HttpUrl = Field(..., description="HTTPS endpoint for event delivery")


class SubscriptionResponse(BaseModel):
    id: int
    tenant_id: str
    event_type: str
    webhook_url: str
    active: bool
    created_at: Any

    model_config = {"from_attributes": True}


class MessageSummaryResponse(BaseModel):
    id: int
    connection_id: int
    message_type: str
    control_id: str
    patient_id: int | None
    patient_mrn: str
    patient_name: str
    event_datetime: Any
    status: str
    error_message: str | None
    created_at: Any

    model_config = {"from_attributes": True}


class MessageDetailResponse(MessageSummaryResponse):
    raw_message: str
    processed_data: Any

    model_config = {"from_attributes": True}


class ReplayResponse(BaseModel):
    message_id: int
    status: str
    error_message: str | None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_connection_or_404(connection_id: int, tenant_id: str) -> dict[str, Any]:
    conn = get_connection(connection_id, tenant_id)
    if conn is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"ADT connection {connection_id} not found.",
        )
    return conn


# ---------------------------------------------------------------------------
# Connection endpoints
# ---------------------------------------------------------------------------


@router.get(
    "/connections",
    summary="List ADT connections",
    response_model=list[ConnectionResponse],
)
def read_connections(
    tenant_id: str = Depends(get_tenant_id),
    _current_user: dict = Depends(get_current_user),
    _perm: None = Depends(require_permission("adt", "read")),
) -> list[dict[str, Any]]:
    """Return all ADT connection configurations for the caller's tenant."""
    return list_connections(tenant_id)


@router.post(
    "/connections",
    summary="Create ADT connection",
    status_code=status.HTTP_201_CREATED,
    response_model=ConnectionResponse,
)
def create_adt_connection(
    body: ConnectionCreateRequest,
    tenant_id: str = Depends(get_tenant_id),
    _current_user: dict = Depends(get_current_user),
    _perm: None = Depends(require_permission("adt", "write")),
) -> dict[str, Any]:
    """
    Create a new MLLP/TCP listener configuration.

    The listener is **not** started automatically.  Call
    ``POST /api/adt/connections/{id}/start`` to activate it.
    """
    try:
        conn = create_connection(
            tenant_id=tenant_id,
            name=body.name,
            host=body.host,
            port=body.port,
            direction=body.direction,
            protocol=body.protocol,
            auto_process=body.auto_process,
        )
    except Exception as exc:
        logger.error("create_adt_connection error: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Invalid input",
        )
    logger.info("ADT connection %d created for tenant %s", conn["id"], tenant_id)
    return conn


@router.put(
    "/connections/{connection_id}",
    summary="Update ADT connection",
    response_model=ConnectionResponse,
)
def update_adt_connection(
    connection_id: int,
    body: ConnectionUpdateRequest,
    tenant_id: str = Depends(get_tenant_id),
    _current_user: dict = Depends(get_current_user),
    _perm: None = Depends(require_permission("adt", "write")),
) -> dict[str, Any]:
    """
    Update configuration fields for an ADT connection.

    You must stop the listener before changing ``host`` or ``port``.
    Only fields present in the request body are modified.
    """
    _get_connection_or_404(connection_id, tenant_id)

    updated = update_connection(
        connection_id=connection_id,
        tenant_id=tenant_id,
        **body.model_dump(exclude_none=True),
    )
    if updated is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="ADT connection not found.",
        )
    return updated


@router.post(
    "/connections/{connection_id}/start",
    summary="Start ADT listener",
)
def start_adt_listener(
    connection_id: int,
    tenant_id: str = Depends(get_tenant_id),
    _current_user: dict = Depends(get_current_user),
    _perm: None = Depends(require_permission("adt", "write")),
) -> dict[str, Any]:
    """
    Start the MLLP TCP listener for a connection.

    Binds to the configured ``host:port`` and begins accepting inbound HL7v2
    messages in a background daemon thread.  The connection ``status`` is
    updated to ``active`` on success.

    Returns the runtime status dict from the listener.
    """
    try:
        result = start_listener(connection_id, tenant_id)
    except ValueError as exc:
        logger.error("Unexpected error: %s", exc)
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Conflict")
    except OSError as exc:
        logger.error("Unexpected error: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Service unavailable",
        )
    return result


@router.post(
    "/connections/{connection_id}/stop",
    summary="Stop ADT listener",
)
def stop_adt_listener(
    connection_id: int,
    tenant_id: str = Depends(get_tenant_id),
    _current_user: dict = Depends(get_current_user),
    _perm: None = Depends(require_permission("adt", "write")),
) -> dict[str, Any]:
    """
    Gracefully shut down the MLLP listener for a connection.

    In-flight connections are allowed to finish before the server socket is
    closed (up to 5 seconds).  Connection ``status`` is set to ``inactive``.
    """
    try:
        result = stop_listener(connection_id, tenant_id)
    except ValueError as exc:
        logger.error("Unexpected error: %s", exc)
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Conflict")
    return result


@router.get(
    "/connections/{connection_id}/status",
    summary="Listener health status",
)
def connection_status(
    connection_id: int,
    tenant_id: str = Depends(get_tenant_id),
    _current_user: dict = Depends(get_current_user),
    _perm: None = Depends(require_permission("adt", "read")),
) -> dict[str, Any]:
    """
    Return real-time runtime health for a listener.

    Combines in-process thread counters (``messages_received``,
    ``messages_errored``, ``started_at``) with the persisted DB counters
    (``message_count``, ``error_count``, ``last_message_at``).
    """
    try:
        return get_listener_status(connection_id, tenant_id)
    except ValueError as exc:
        logger.error("Unexpected error: %s", exc)
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Resource not found")


# ---------------------------------------------------------------------------
# Message endpoints
# ---------------------------------------------------------------------------


@router.get(
    "/messages",
    summary="List ADT messages",
    response_model=list[MessageSummaryResponse],
)
def read_messages(
    connection_id: int | None = Query(default=None, description="Filter by connection"),
    message_type: str | None = Query(default=None, description="Filter by type e.g. ADT_A01"),
    msg_status: str | None = Query(
        default=None,
        alias="status",
        description="Filter by status: received|processed|error|ignored",
    ),
    limit: int = Query(default=50, ge=1, le=500, description="Max rows"),
    offset: int = Query(default=0, ge=0, description="Pagination offset"),
    tenant_id: str = Depends(get_tenant_id),
    _current_user: dict = Depends(get_current_user),
    _perm: None = Depends(require_permission("adt", "read")),
) -> list[dict[str, Any]]:
    """
    Return received ADT messages newest-first.

    The ``raw_message`` body is excluded from list responses for performance;
    use ``GET /api/adt/messages/{id}`` to retrieve it.
    """
    return list_messages(
        tenant_id=tenant_id,
        connection_id=connection_id,
        message_type=message_type,
        status=msg_status,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/messages/{message_id}",
    summary="ADT message detail",
    response_model=MessageDetailResponse,
)
def read_message(
    message_id: int,
    tenant_id: str = Depends(get_tenant_id),
    _current_user: dict = Depends(get_current_user),
    _perm: None = Depends(require_permission("adt", "read")),
) -> dict[str, Any]:
    """
    Return full detail for a single ADT message including the original
    ``raw_message`` HL7v2 text and the ``processed_data`` JSON extract.
    """
    msg = get_message(message_id, tenant_id)
    if msg is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"ADT message {message_id} not found.",
        )
    return msg


@router.post(
    "/messages/replay/{message_id}",
    summary="Replay / reprocess an ADT message",
    response_model=ReplayResponse,
)
def replay_adt_message(
    message_id: int,
    tenant_id: str = Depends(get_tenant_id),
    _current_user: dict = Depends(get_current_user),
    _perm: None = Depends(require_permission("adt", "write")),
) -> dict[str, Any]:
    """
    Re-run the full processing pipeline on a previously received message.

    Useful for recovering from transient errors (e.g. database outage at
    ingestion time) or after business-logic fixes.  The original row is
    updated in-place with the new ``status`` and ``processed_data``.

    This endpoint is idempotent — replaying an already-processed message
    simply re-parses and re-upserts patient data without duplicating records.
    """
    try:
        result = replay_message(message_id, tenant_id)
    except ValueError as exc:
        logger.error("Unexpected error: %s", exc)
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Resource not found")
    return result


# ---------------------------------------------------------------------------
# Subscription endpoints
# ---------------------------------------------------------------------------


@router.get(
    "/subscriptions",
    summary="List ADT webhook subscriptions",
    response_model=list[SubscriptionResponse],
)
def read_subscriptions(
    tenant_id: str = Depends(get_tenant_id),
    _current_user: dict = Depends(get_current_user),
    _perm: None = Depends(require_permission("adt", "read")),
) -> list[dict[str, Any]]:
    """Return all ADT webhook subscriptions for the caller's tenant."""
    return list_subscriptions(tenant_id)


@router.post(
    "/subscriptions",
    summary="Subscribe to ADT events",
    status_code=status.HTTP_201_CREATED,
    response_model=SubscriptionResponse,
)
def create_adt_subscription(
    body: SubscriptionCreateRequest,
    tenant_id: str = Depends(get_tenant_id),
    _current_user: dict = Depends(get_current_user),
    _perm: None = Depends(require_permission("adt", "write")),
) -> dict[str, Any]:
    """
    Subscribe a webhook URL to one or all ADT event types.

    **Supported event_type values**

    | Value           | Triggered by           |
    |-----------------|------------------------|
    | ``adt.admit``   | A01 — Admit a Patient  |
    | ``adt.transfer``| A02 — Transfer         |
    | ``adt.discharge``| A03 — Discharge       |
    | ``adt.register``| A04 — Register         |
    | ``adt.update``  | A08 — Update Patient   |
    | ``adt.*``       | All of the above       |

    **Delivery format** — POST to your URL with JSON body:
    ```json
    {
      "event":         "adt.admit",
      "adt_message_id": 1234,
      "connection_id":  1,
      "message_type":  "ADT_A01",
      "control_id":    "MSG0001",
      "patient_mrn":   "12345",
      "patient_name":  "Smith, John",
      "event_datetime": "2026-04-02T14:30:00",
      "processed":     { ... },
      "timestamp":     "2026-04-02T14:30:01.234Z"
    }
    ```
    """
    try:
        sub = create_subscription(
            tenant_id=tenant_id,
            event_type=body.event_type,
            webhook_url=str(body.webhook_url),
        )
    except ValueError as exc:
        logger.error("Unexpected error: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Invalid input",
        )
    logger.info(
        "ADT subscription %d created (event=%s) for tenant %s",
        sub["id"],
        body.event_type,
        tenant_id,
    )
    return sub


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------


@router.get(
    "/dashboard",
    summary="ADT feed dashboard",
)
def adt_dashboard(
    tenant_id: str = Depends(get_tenant_id),
    _current_user: dict = Depends(get_current_user),
    _perm: None = Depends(require_permission("adt", "read")),
) -> dict[str, Any]:
    """
    Return aggregate metrics for the ADT feed dashboard.

    **Response fields**

    - ``volume_by_type`` — message counts per ADT type (last 30 days)
    - ``volume_by_status`` — counts per processing status (last 30 days)
    - ``daily_volume_14d`` — daily message counts (last 14 days)
    - ``connections`` — summary row for each configured connection
    """
    return get_dashboard(tenant_id)
