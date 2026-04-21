"""
Real-Time Dashboard router.

Endpoints
---------
GET  /api/realtime/events             – SSE stream for live dashboard updates
WS   /api/realtime/ws                 – WebSocket bidirectional connection
GET  /api/realtime/alerts             – list persisted alerts for current user
PUT  /api/realtime/alerts/{id}/read   – mark a single alert as read
PUT  /api/realtime/alerts/read-all    – mark all alerts as read
GET  /api/realtime/alerts/unread-count – badge count
POST /api/realtime/dashboards         – save a dashboard layout config
GET  /api/realtime/dashboards         – list user's saved dashboard configs
PUT  /api/realtime/dashboards/{id}    – update a dashboard config
DELETE /api/realtime/dashboards/{id}  – delete a dashboard config
GET  /api/realtime/kpi                – live KPI snapshot

Authentication
--------------
Standard JWT Bearer via Depends(get_current_user) on HTTP endpoints.

SSE and WebSocket endpoints cannot use the Authorization header once the
connection is upgraded (browsers do not support custom headers on
EventSource or WebSocket).  Instead they accept a short-lived JWT via
the ``token`` query parameter and validate it with the same decode_token /
get_user / validate_session chain that auth.py uses.
"""
# Do NOT use 'from __future__ import annotations' — breaks FastAPI schema
# generation.

import asyncio
import json
import logging
import uuid
from collections.abc import AsyncGenerator
from datetime import datetime, timezone
from typing import Any

import jwt
from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
    WebSocket,
    WebSocketDisconnect,
    status,
)
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.auth import get_current_user
from app.services.auth_service import decode_token, get_user, validate_session
from app.services.realtime_service import (
    connection_manager,
    delete_dashboard_config,
    get_alerts,
    get_live_kpi,
    get_unread_count,
    list_dashboard_configs,
    mark_alert_read,
    mark_all_alerts_read,
    save_dashboard_config,
    update_dashboard_config,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/realtime", tags=["realtime"])


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class DashboardConfigCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200, description="Human-readable dashboard name")
    layout: dict[str, Any] = Field(default_factory=dict, description="Grid layout descriptor")
    widgets: list[dict[str, Any]] = Field(default_factory=list, description="Widget definitions")
    is_default: bool = Field(default=False, description="Set as the user's default dashboard")


class DashboardConfigUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=200)
    layout: dict[str, Any] | None = None
    widgets: list[dict[str, Any]] | None = None
    is_default: bool | None = None


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_CREDENTIALS_EXCEPTION = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Could not validate credentials.",
    headers={"WWW-Authenticate": "Bearer"},
)


async def _resolve_token_param(token: str) -> dict[str, Any]:
    """
    Validate a JWT supplied as a query parameter.

    Used by SSE and WebSocket endpoints where the browser cannot send the
    Authorization header.  Applies the same validation chain as auth.py:
    decode → type check → load user → validate session.
    """
    try:
        payload = decode_token(token)
    except jwt.PyJWTError:
        raise _CREDENTIALS_EXCEPTION

    if payload.get("type") != "access":
        raise _CREDENTIALS_EXCEPTION

    try:
        user_id = int(payload["sub"])
    except (KeyError, ValueError, TypeError):
        raise _CREDENTIALS_EXCEPTION

    session_id = payload.get("session_id")
    if not session_id:
        raise _CREDENTIALS_EXCEPTION

    user = get_user(user_id)
    if not user or not user.get("is_active"):
        raise _CREDENTIALS_EXCEPTION

    session = validate_session(session_id)
    if not session:
        raise _CREDENTIALS_EXCEPTION

    user["session_id"] = session_id
    user["token_role"] = payload.get("role", user.get("role"))
    if user.get("tenant_id") is None:
        user["tenant_id"] = payload.get("tenant_id")
    return user


def _tenant_id(user: dict[str, Any]) -> str:
    tid = user.get("tenant_id")
    return str(tid) if tid is not None else "default"


async def _sse_generator(
    queue: asyncio.Queue,
    connection_id: str,
) -> AsyncGenerator[str, None]:
    """
    Async generator that yields SSE-formatted strings from a connection queue.

    SSE wire format:
        data: <json>\n\n

    Heartbeat comments (": ping") are emitted every 25 s to keep the TCP
    connection alive through proxies and load balancers.
    """
    try:
        while True:
            try:
                event: dict[str, Any] = await asyncio.wait_for(queue.get(), timeout=25.0)
                yield f"data: {json.dumps(event)}\n\n"
            except asyncio.TimeoutError:
                # Heartbeat — SSE comment lines keep the connection open
                yield ": ping\n\n"
    except asyncio.CancelledError:
        pass
    finally:
        await connection_manager.disconnect(connection_id)


# ---------------------------------------------------------------------------
# SSE endpoint
# ---------------------------------------------------------------------------

@router.get(
    "/events",
    summary="SSE stream — subscribe to live dashboard events",
    response_class=StreamingResponse,
    responses={
        200: {"description": "text/event-stream; events emitted as JSON"},
        401: {"description": "Invalid or missing token"},
    },
)
async def sse_stream(
    token: str = Query(..., description="JWT access token (same value as Bearer token)"),
) -> StreamingResponse:
    """
    Server-Sent Events endpoint for one-way server-to-client push.

    Connect with the browser's native EventSource API:

    ```js
    const es = new EventSource(`/api/realtime/events?token=${accessToken}`);
    es.onmessage = (e) => {
        const event = JSON.parse(e.data);
        // handle event.event_type, event.data, event.alert_id ...
    };
    ```

    The stream emits a `: ping` heartbeat comment every 25 seconds to keep
    the connection alive through load balancers.  Reconnect automatically
    on disconnect using the browser's built-in EventSource retry logic.
    """
    user = await _resolve_token_param(token)
    user_id: int = user["id"]
    tenant_id: str = _tenant_id(user)

    connection_id = f"sse-{user_id}-{uuid.uuid4().hex[:8]}"
    queue = await connection_manager.connect(connection_id, user_id, tenant_id)

    logger.info("realtime: SSE connection opened [%s] user=%s", connection_id, user_id)

    return StreamingResponse(
        _sse_generator(queue, connection_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",   # disable Nginx proxy buffering
            "Connection": "keep-alive",
        },
    )


# ---------------------------------------------------------------------------
# WebSocket endpoint
# ---------------------------------------------------------------------------

@router.websocket("/ws")
async def websocket_endpoint(
    websocket: WebSocket,
    token: str = Query(..., description="JWT access token"),
) -> None:
    """
    Bidirectional WebSocket connection for real-time dashboard updates.

    Authentication: pass the JWT as a query parameter:
        ws://host/api/realtime/ws?token=<access_token>

    Incoming messages from the client are expected to be JSON with a
    ``type`` field.  Currently supported client → server message types:

    - ``{"type": "ping"}`` → server replies ``{"type": "pong"}``
    - ``{"type": "subscribe", "events": ["raf_score_updated", ...]}``
      (stored but not yet filtered; included for forward compatibility)

    All server → client messages are the same event envelope used by SSE.
    """
    try:
        user = await _resolve_token_param(token)
    except HTTPException:
        await websocket.close(code=4001)
        return

    user_id: int = user["id"]
    tenant_id: str = _tenant_id(user)

    await websocket.accept()
    connection_id = f"ws-{user_id}-{uuid.uuid4().hex[:8]}"
    queue = await connection_manager.connect(connection_id, user_id, tenant_id)

    logger.info("realtime: WebSocket connection opened [%s] user=%s", connection_id, user_id)

    # Send a connected acknowledgement
    await websocket.send_text(json.dumps({
        "type": "connected",
        "connection_id": connection_id,
        "user_id": user_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }))

    # Pump outbound events from the queue while also listening for inbound
    # messages from the client (both in parallel via asyncio.wait).
    receive_task = asyncio.create_task(websocket.receive_text())
    queue_task = asyncio.create_task(queue.get())

    try:
        while True:
            done, pending = await asyncio.wait(
                {receive_task, queue_task},
                return_when=asyncio.FIRST_COMPLETED,
            )

            for task in done:
                if task is receive_task:
                    # Handle inbound client message
                    try:
                        raw = task.result()
                        msg = json.loads(raw)
                    except Exception:
                        msg = {}

                    if msg.get("type") == "ping":
                        await websocket.send_text(json.dumps({"type": "pong"}))
                    # Future: handle "subscribe" / "unsubscribe" here

                    # Re-arm the receive listener
                    receive_task = asyncio.create_task(websocket.receive_text())

                elif task is queue_task:
                    # Push queued event to client
                    event = task.result()
                    await websocket.send_text(json.dumps(event))

                    # Re-arm the queue listener
                    queue_task = asyncio.create_task(queue.get())

    except (WebSocketDisconnect, Exception) as exc:
        if not isinstance(exc, WebSocketDisconnect):
            logger.warning("realtime: WebSocket error [%s]: %s", connection_id, exc)
    finally:
        receive_task.cancel()
        queue_task.cancel()
        await connection_manager.disconnect(connection_id)
        logger.info("realtime: WebSocket connection closed [%s]", connection_id)


# ---------------------------------------------------------------------------
# Alert endpoints
# ---------------------------------------------------------------------------

@router.get(
    "/alerts",
    summary="List persisted alerts for the current user",
)
def list_alerts(
    unread_only: bool = Query(default=False, description="Return only unread alerts"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    current_user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    """Return paginated alerts, newest first."""
    user_id: int = current_user["id"]
    tenant_id = _tenant_id(current_user)
    alerts = get_alerts(user_id, tenant_id, unread_only=unread_only, limit=limit, offset=offset)
    return {
        "alerts": alerts,
        "count": len(alerts),
        "unread_count": get_unread_count(user_id, tenant_id),
    }


@router.get(
    "/alerts/unread-count",
    summary="Unread alert count for badge display",
)
def unread_count(
    current_user: dict = Depends(get_current_user),
) -> dict[str, int]:
    """Returns the integer count of unread alerts for the current user."""
    user_id: int = current_user["id"]
    tenant_id = _tenant_id(current_user)
    return {"unread_count": get_unread_count(user_id, tenant_id)}


@router.put(
    "/alerts/read-all",
    summary="Mark all alerts as read",
)
def read_all_alerts(
    current_user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    """Mark every unread alert for the current user as read."""
    user_id: int = current_user["id"]
    tenant_id = _tenant_id(current_user)
    updated = mark_all_alerts_read(user_id, tenant_id)
    logger.info("realtime: mark_all_read for user=%s, rows=%s", user_id, updated)
    return {"updated": updated, "unread_count": 0}


@router.put(
    "/alerts/{alert_id}/read",
    summary="Mark a single alert as read",
)
def read_alert(
    alert_id: int,
    current_user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    """Mark a specific alert as read.  Returns 404 if the alert is not found or
    does not belong to the current user."""
    user_id: int = current_user["id"]
    tenant_id = _tenant_id(current_user)
    ok = mark_alert_read(alert_id, user_id, tenant_id)
    if not ok:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Alert not found.")
    return {
        "alert_id": alert_id,
        "is_read": True,
        "read_at": datetime.now(timezone.utc).isoformat(),
    }


# ---------------------------------------------------------------------------
# Dashboard config endpoints
# ---------------------------------------------------------------------------

@router.post(
    "/dashboards",
    status_code=status.HTTP_201_CREATED,
    summary="Save a new dashboard layout configuration",
)
def create_dashboard(
    body: DashboardConfigCreate,
    current_user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    """Persist a dashboard layout and widget configuration for the current user."""
    user_id: int = current_user["id"]
    tenant_id = _tenant_id(current_user)

    try:
        new_id = save_dashboard_config(
            user_id=user_id,
            tenant_id=tenant_id,
            name=body.name,
            layout=body.layout,
            widgets=body.widgets,
            is_default=body.is_default,
        )
    except Exception as exc:
        logger.error("realtime: create_dashboard error: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to save dashboard configuration.")

    logger.info("realtime: dashboard config created id=%s user=%s", new_id, user_id)
    return {"id": new_id, "name": body.name, "is_default": body.is_default}


@router.get(
    "/dashboards",
    summary="List saved dashboard configurations for the current user",
)
def list_dashboards(
    current_user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    """Return all saved dashboard configs, default layout first."""
    user_id: int = current_user["id"]
    tenant_id = _tenant_id(current_user)
    configs = list_dashboard_configs(user_id, tenant_id)
    return {"dashboards": configs, "count": len(configs)}


@router.put(
    "/dashboards/{dashboard_id}",
    summary="Update a dashboard layout configuration",
)
def update_dashboard(
    dashboard_id: int,
    body: DashboardConfigUpdate,
    current_user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    """Partially update a saved dashboard config.  Only provided fields are changed."""
    user_id: int = current_user["id"]
    tenant_id = _tenant_id(current_user)

    ok = update_dashboard_config(
        dashboard_id,
        user_id,
        tenant_id,
        name=body.name,
        layout=body.layout,
        widgets=body.widgets,
        is_default=body.is_default,
    )
    if not ok:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Dashboard configuration not found.",
        )
    logger.info("realtime: dashboard config updated id=%s user=%s", dashboard_id, user_id)
    return {"id": dashboard_id, "updated": True}


@router.delete(
    "/dashboards/{dashboard_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a dashboard configuration",
)
def remove_dashboard(
    dashboard_id: int,
    current_user: dict = Depends(get_current_user),
) -> None:
    """Delete a saved dashboard config.  Returns 404 if not found."""
    user_id: int = current_user["id"]
    tenant_id = _tenant_id(current_user)
    ok = delete_dashboard_config(dashboard_id, user_id, tenant_id)
    if not ok:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Dashboard configuration not found.",
        )
    logger.info("realtime: dashboard config deleted id=%s user=%s", dashboard_id, user_id)


# ---------------------------------------------------------------------------
# Live KPI snapshot
# ---------------------------------------------------------------------------

@router.get(
    "/kpi",
    summary="Live KPI snapshot for the current tenant",
)
def live_kpi(
    current_user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    """
    Return a real-time snapshot of key performance indicators.

    Values are computed on-the-fly from indexed COUNT / AVG queries.
    Intended to seed dashboard widgets on initial page load; subsequent
    updates arrive via the SSE / WebSocket stream (event_type = kpi_refresh).
    """
    tenant_id = _tenant_id(current_user)
    return get_live_kpi(tenant_id)
