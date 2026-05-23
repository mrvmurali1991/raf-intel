"""
Real-time dashboard service — event bus, connection management, alert
persistence, and live KPI aggregation.

Architecture
------------
This module provides a purely in-process pub/sub bus built on asyncio.
It is intentionally simple: one asyncio.Queue per connected client.
For a multi-process deployment (Gunicorn with multiple uvicorn workers)
replace the in-memory bus with Redis Streams or a message broker; the
public interface (emit_event / ConnectionManager) does not change.

Public interface
----------------
    emit_event(event_type, payload, tenant_id, user_id)
        Fire-and-forget helper that other services call to push an event
        into the bus.  Safe to call from sync code via asyncio.run_coroutine_threadsafe.

    connection_manager
        Singleton ConnectionManager that owns all active SSE and WebSocket
        connections.

Alert persistence
-----------------
Alerts are written to dashboard_alerts (Migration 020).  Events that do
not map to an alert type (e.g. pure KPI refreshes) are broadcast only
to live connections and are not persisted.
"""
# Do NOT use 'from __future__ import annotations' — breaks FastAPI schema
# generation when this module's types are referenced in router signatures.

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Any

import redis.asyncio as aioredis

from app.config import settings
from app.db import raf_cursor

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Redis Pub/Sub Event Bus
# ---------------------------------------------------------------------------
# The event bus instances are scaled horizontally using Redis Pub/Sub. When
# a worker emits an event, it publishes it to a Redis channel. A background
# task in every worker listens to this channel and distributes the events
# to the local connected WebSocket clients.
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Event type catalogue
# ---------------------------------------------------------------------------

REALTIME_EVENTS = [
    "raf_score_updated",
    "suspect_flagged",
    "gap_closed",
    "attestation_submitted",
    "claim_processed",
    "awv_completed",
    "system_alert",
    "kpi_refresh",          # internal — triggers widget reload, not persisted
    # Patient pipeline events
    "patient.synced",
    "patient.scored",
    "patient.analyzed",
]

# Map from realtime event type → dashboard_alerts.alert_type ENUM value.
# Events not listed here are broadcast live only (not stored as alerts).
_EVENT_TO_ALERT_TYPE: dict[str, str] = {
    "raf_score_updated":    "raf_change",
    "suspect_flagged":      "new_suspect",
    "gap_closed":           "gap_closed",
    "attestation_submitted": "attestation_needed",
    "claim_processed":      "claim_processed",
    "awv_completed":        "awv_due",
    "system_alert":         "system",
}

_EVENT_TO_DEFAULT_SEVERITY: dict[str, str] = {
    "raf_score_updated":    "info",
    "suspect_flagged":      "warning",
    "gap_closed":           "info",
    "attestation_submitted": "warning",
    "claim_processed":      "info",
    "awv_completed":        "info",
    "system_alert":         "warning",
    "kpi_refresh":          "info",
}


# ---------------------------------------------------------------------------
# ConnectionManager
# ---------------------------------------------------------------------------

class ConnectionManager:
    """
    Tracks all live SSE and WebSocket connections.

    Uses Redis Pub/Sub to distribute events across multiple worker processes.
    When an event is broadcast, it is published to a Redis channel. A background
    task in each worker listens to the channel and distributes the event to
    its local connections. Fallback to in-memory broadcast if Redis fails.
    """

    def __init__(self) -> None:
        # {connection_id: {"queue": asyncio.Queue, "user_id": int, "tenant_id": str}}
        self._connections: dict[str, dict[str, Any]] = {}
        self._lock = asyncio.Lock()
        self._loop: asyncio.AbstractEventLoop | None = None

        self._redis: aioredis.Redis | None = None
        self._pubsub: aioredis.client.PubSub | None = None
        self._redis_task: asyncio.Task | None = None
        self._redis_channel = "raf_realtime_events"

    # ------------------------------------------------------------------
    # Redis Integration
    # ------------------------------------------------------------------

    async def _setup_redis(self) -> None:
        if self._redis is not None:
            return
        try:
            self._redis = aioredis.from_url(settings.redis_url, decode_responses=True)
            self._pubsub = self._redis.pubsub()
            await self._pubsub.subscribe(self._redis_channel)
            self._redis_task = asyncio.create_task(self._listen_redis())
            logger.info("realtime: connected to Redis Pub/Sub channel '%s'", self._redis_channel)
        except Exception as exc:
            logger.warning(
                "realtime: Redis Pub/Sub unavailable, falling back to in-process bus: %s",
                exc,
            )
            self._redis = None

    async def _listen_redis(self) -> None:
        """Background task that receives Redis events and distributes them locally."""
        try:
            async for message in self._pubsub.listen():
                if message["type"] == "message":
                    payload = json.loads(message["data"])
                    await self._local_broadcast(
                        payload["event"],
                        payload["tenant_id"],
                        payload.get("user_id"),
                    )
        except Exception as exc:
            logger.error("realtime: Redis listener failed: %s", exc)
            self._redis = None

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    async def connect(
        self,
        connection_id: str,
        user_id: int,
        tenant_id: str,
    ) -> asyncio.Queue:
        """Register a new connection and return its dedicated queue."""
        queue: asyncio.Queue = asyncio.Queue(maxsize=256)
        async with self._lock:
            self._connections[connection_id] = {
                "queue": queue,
                "user_id": user_id,
                "tenant_id": tenant_id,
                "connected_at": datetime.now(timezone.utc).isoformat(),
            }
        if self._loop is None:
            self._loop = asyncio.get_running_loop()
            await self._setup_redis()

        logger.info(
            "realtime: connection registered [%s] user=%s tenant=%s",
            connection_id, user_id, tenant_id,
        )
        return queue

    async def disconnect(self, connection_id: str) -> None:
        """Remove a connection on client disconnect."""
        async with self._lock:
            self._connections.pop(connection_id, None)
        logger.info("realtime: connection removed [%s]", connection_id)

    # ------------------------------------------------------------------
    # Broadcast
    # ------------------------------------------------------------------

    async def broadcast(
        self,
        event: dict[str, Any],
        tenant_id: str,
        user_id: int | None = None,
    ) -> None:
        """Push an event to all matching connections across all workers via Redis."""
        if self._redis:
            try:
                payload = {
                    "event": event,
                    "tenant_id": tenant_id,
                    "user_id": user_id,
                }
                await self._redis.publish(self._redis_channel, json.dumps(payload))
                return
            except Exception as exc:
                logger.error("realtime: Redis publish failed: %s", exc)

        # Fallback to local broadcast if Redis is unavailable
        await self._local_broadcast(event, tenant_id, user_id)

    async def _local_broadcast(
        self,
        event: dict[str, Any],
        tenant_id: str,
        user_id: int | None = None,
    ) -> None:
        """Distribute an event to local connections inside this worker process."""
        async with self._lock:
            targets = [
                meta
                for meta in self._connections.values()
                if meta["tenant_id"] == tenant_id
                and (user_id is None or meta["user_id"] == user_id)
            ]

        for meta in targets:
            q: asyncio.Queue = meta["queue"]
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                logger.warning(
                    "realtime: queue full for user=%s, dropping event %s",
                    meta["user_id"], event.get("event_type"),
                )

    def broadcast_sync(
        self,
        event: dict[str, Any],
        tenant_id: str,
        user_id: int | None = None,
    ) -> None:
        """
        Sync-safe wrapper around broadcast().

        Call this from thread-pool / webhook threads that do not have access
        to a running event loop.  It schedules the coroutine on the event loop
        that processed the most recent ``connect()`` call.
        """
        if self._loop is None or self._loop.is_closed():
            logger.debug("realtime: no event loop — broadcast_sync skipped for %s", event.get("event_type"))
            return
        asyncio.run_coroutine_threadsafe(
            self.broadcast(event, tenant_id, user_id),
            self._loop,
        )

    # ------------------------------------------------------------------
    # Diagnostics
    # ------------------------------------------------------------------

    async def active_count(self) -> int:
        async with self._lock:
            return len(self._connections)

    async def active_connections_info(self) -> list[dict[str, Any]]:
        async with self._lock:
            return [
                {
                    "connection_id": cid,
                    "user_id": meta["user_id"],
                    "tenant_id": meta["tenant_id"],
                    "connected_at": meta["connected_at"],
                }
                for cid, meta in self._connections.items()
            ]


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

connection_manager = ConnectionManager()


# ---------------------------------------------------------------------------
# Alert persistence
# ---------------------------------------------------------------------------

def persist_alert(
    *,
    event_type: str,
    title: str,
    message: str | None,
    user_id: int,
    tenant_id: str,
    severity: str | None = None,
    patient_id: str | None = None,
    provider_npi: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> int | None:
    """
    Write an alert row to dashboard_alerts and return the new id.

    Returns None on error (non-fatal — live push is independent of
    persistence).
    """
    alert_type = _EVENT_TO_ALERT_TYPE.get(event_type)
    if alert_type is None:
        # Event type is not meant to produce a persistent alert.
        return None

    resolved_severity = severity or _EVENT_TO_DEFAULT_SEVERITY.get(event_type, "info")

    try:
        with raf_cursor() as cur:
            cur.execute(
                """
                INSERT INTO dashboard_alerts
                    (alert_type, severity, title, message, patient_id,
                     provider_npi, metadata, is_read, user_id, tenant_id, created_at)
                VALUES
                    (%s, %s, %s, %s, %s, %s, %s, 0, %s, %s, NOW(3))
                """,
                (
                    alert_type,
                    resolved_severity,
                    title[:300],
                    message,
                    patient_id,
                    provider_npi,
                    json.dumps(metadata) if metadata else None,
                    user_id,
                    tenant_id,
                ),
            )
            return cur.lastrowid
    except Exception as exc:
        logger.error("realtime: failed to persist alert: %s", exc)
        return None


def get_alerts(
    user_id: int,
    tenant_id: str,
    unread_only: bool = False,
    limit: int = 50,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """Return paginated alerts for a user, newest first."""
    where_clauses = ["user_id = %s", "tenant_id = %s"]
    params: list[Any] = [user_id, tenant_id]

    if unread_only:
        where_clauses.append("is_read = 0")

    where = " AND ".join(where_clauses)

    try:
        with raf_cursor() as cur:
            cur.execute(
                f"""
                SELECT id, alert_type, severity, title, message,
                       patient_id, provider_npi, metadata,
                       is_read, created_at, read_at
                FROM dashboard_alerts
                WHERE {where}
                ORDER BY created_at DESC
                LIMIT %s OFFSET %s
                """,
                (*params, limit, offset),
            )
            rows = cur.fetchall()
    except Exception as exc:
        logger.error("realtime: get_alerts error: %s", exc)
        return []

    results = []
    for row in rows:
        d = dict(row)
        if isinstance(d.get("metadata"), str):
            try:
                d["metadata"] = json.loads(d["metadata"])
            except Exception:  # noqa: BLE001 — best-effort guard
                logger.debug("swallowed exception", exc_info=True)
        # Serialize datetimes
        for key in ("created_at", "read_at"):
            if isinstance(d.get(key), datetime):
                d[key] = d[key].isoformat()
        results.append(d)
    return results


def get_unread_count(user_id: int, tenant_id: str) -> int:
    if not tenant_id:
        raise ValueError(
            "get_unread_count: tenant_id is required — "
            "refusing to operate without tenant scope (HIPAA multi-tenant isolation)"
        )
    """Return count of unread alerts for badge display."""
    try:
        with raf_cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) AS cnt FROM dashboard_alerts "
                "WHERE user_id = %s AND tenant_id = %s AND is_read = 0",
                (user_id, tenant_id),
            )
            row = cur.fetchone()
            return int(row["cnt"] if row else 0)
    except Exception as exc:
        logger.error("realtime: get_unread_count error: %s", exc)
        return 0


def mark_alert_read(alert_id: int, user_id: int, tenant_id: str) -> bool:
    if not tenant_id:
        raise ValueError(
            "mark_alert_read: tenant_id is required — "
            "refusing to operate without tenant scope (HIPAA multi-tenant isolation)"
        )
    """Mark a single alert as read. Returns True if a row was updated."""
    try:
        with raf_cursor() as cur:
            cur.execute(
                """
                UPDATE dashboard_alerts
                SET is_read = 1, read_at = NOW(3)
                WHERE id = %s AND user_id = %s AND tenant_id = %s
                """,
                (alert_id, user_id, tenant_id),
            )
            return cur.rowcount > 0
    except Exception as exc:
        logger.error("realtime: mark_alert_read error: %s", exc)
        return False


def mark_all_alerts_read(user_id: int, tenant_id: str) -> int:
    if not tenant_id:
        raise ValueError(
            "mark_all_alerts_read: tenant_id is required — "
            "refusing to operate without tenant scope (HIPAA multi-tenant isolation)"
        )
    """Mark all unread alerts as read. Returns count of updated rows."""
    try:
        with raf_cursor() as cur:
            cur.execute(
                """
                UPDATE dashboard_alerts
                SET is_read = 1, read_at = NOW(3)
                WHERE user_id = %s AND tenant_id = %s AND is_read = 0
                """,
                (user_id, tenant_id),
            )
            return cur.rowcount
    except Exception as exc:
        logger.error("realtime: mark_all_alerts_read error: %s", exc)
        return 0


# ---------------------------------------------------------------------------
# Dashboard config persistence
# ---------------------------------------------------------------------------

def save_dashboard_config(
    *,
    user_id: int,
    tenant_id: str,
    name: str,
    layout: dict[str, Any],
    widgets: list[dict[str, Any]],
    is_default: bool = False,
) -> int:
    """
    Insert a new dashboard config row.

    If is_default is True, clears the is_default flag on all other rows for
    this user first (exactly-one-default invariant).
    """
    try:
        with raf_cursor() as cur:
            if is_default:
                cur.execute(
                    "UPDATE dashboard_configs SET is_default = 0 "
                    "WHERE user_id = %s AND tenant_id = %s",
                    (user_id, tenant_id),
                )
            cur.execute(
                """
                INSERT INTO dashboard_configs
                    (user_id, name, layout, widgets, is_default, tenant_id)
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (
                    user_id,
                    name[:200],
                    json.dumps(layout),
                    json.dumps(widgets),
                    1 if is_default else 0,
                    tenant_id,
                ),
            )
            return cur.lastrowid
    except Exception as exc:
        logger.error("realtime: save_dashboard_config error: %s", exc)
        raise


def list_dashboard_configs(user_id: int, tenant_id: str) -> list[dict[str, Any]]:
    if not tenant_id:
        raise ValueError(
            "list_dashboard_configs: tenant_id is required — "
            "refusing to operate without tenant scope (HIPAA multi-tenant isolation)"
        )
    """Return all saved dashboard configs for a user, default first."""
    try:
        with raf_cursor() as cur:
            cur.execute(
                """
                SELECT id, name, layout, widgets, is_default, created_at, updated_at
                FROM dashboard_configs
                WHERE user_id = %s AND tenant_id = %s
                ORDER BY is_default DESC, updated_at DESC
                """,
                (user_id, tenant_id),
            )
            rows = cur.fetchall()
    except Exception as exc:
        logger.error("realtime: list_dashboard_configs error: %s", exc)
        return []

    results = []
    for row in rows:
        d = dict(row)
        for key in ("layout", "widgets"):
            if isinstance(d.get(key), str):
                try:
                    d[key] = json.loads(d[key])
                except Exception:  # noqa: BLE001 — best-effort guard
                    logger.debug("swallowed exception", exc_info=True)
        for key in ("created_at", "updated_at"):
            if isinstance(d.get(key), datetime):
                d[key] = d[key].isoformat()
        results.append(d)
    return results


def update_dashboard_config(
    config_id: int,
    user_id: int,
    tenant_id: str,
    *,
    name: str | None = None,
    layout: dict[str, Any] | None = None,
    widgets: list[dict[str, Any]] | None = None,
    is_default: bool | None = None,
) -> bool:
    """Partial update of a dashboard config. Returns True if a row was updated."""
    sets: list[str] = []
    params: list[Any] = []

    if name is not None:
        sets.append("name = %s")
        params.append(name[:200])
    if layout is not None:
        sets.append("layout = %s")
        params.append(json.dumps(layout))
    if widgets is not None:
        sets.append("widgets = %s")
        params.append(json.dumps(widgets))
    if is_default is not None:
        sets.append("is_default = %s")
        params.append(1 if is_default else 0)

    if not sets:
        return False

    params.extend([config_id, user_id, tenant_id])
    sql = f"UPDATE dashboard_configs SET {', '.join(sets)} WHERE id = %s AND user_id = %s AND tenant_id = %s"

    try:
        with raf_cursor() as cur:
            if is_default:
                cur.execute(
                    "UPDATE dashboard_configs SET is_default = 0 "
                    "WHERE user_id = %s AND tenant_id = %s",
                    (user_id, tenant_id),
                )
            cur.execute(sql, params)
            return cur.rowcount > 0
    except Exception as exc:
        logger.error("realtime: update_dashboard_config error: %s", exc)
        return False


def delete_dashboard_config(config_id: int, user_id: int, tenant_id: str) -> bool:
    if not tenant_id:
        raise ValueError(
            "delete_dashboard_config: tenant_id is required — "
            "refusing to operate without tenant scope (HIPAA multi-tenant isolation)"
        )
    """Delete a dashboard config. Returns True if a row was deleted."""
    try:
        with raf_cursor() as cur:
            cur.execute(
                "DELETE FROM dashboard_configs WHERE id = %s AND user_id = %s AND tenant_id = %s",
                (config_id, user_id, tenant_id),
            )
            return cur.rowcount > 0
    except Exception as exc:
        logger.error("realtime: delete_dashboard_config error: %s", exc)
        return False


# ---------------------------------------------------------------------------
# Live KPI aggregation
# ---------------------------------------------------------------------------

def get_live_kpi(tenant_id: str) -> dict[str, Any]:
    if not tenant_id:
        raise ValueError(
            "get_live_kpi: tenant_id is required — "
            "refusing to operate without tenant scope (HIPAA multi-tenant isolation)"
        )
    """
    Aggregate live KPI values for the dashboard.

    Queries are intentionally lightweight (COUNT / AVG on indexed columns).
    Returns a dict suitable for direct JSON serialisation.
    """
    kpi: dict[str, Any] = {
        "tenant_id": tenant_id,
        "as_of": datetime.now(timezone.utc).isoformat(),
        "total_patients": 0,
        "patients_with_raf": 0,
        "average_raf": 0.0,
        "open_gaps": 0,
        "pending_attestations": 0,
        "suspects_unreviewed": 0,
        "claims_last_30d": 0,
        "awv_due_this_month": 0,
        "unread_alerts": 0,
        "error": False,
    }

    try:
        from app.db import openemr_cursor

        with openemr_cursor() as cur:
            cur.execute("SELECT COUNT(*) AS cnt FROM patient_data")
            kpi["total_patients"] = int((cur.fetchone() or {}).get("cnt", 0))

        with _raf_cursor() as cur:
            # RAF scores
            cur.execute(
                "SELECT COUNT(DISTINCT patient_id) AS cnt, AVG(final_raf) AS avg_raf "
                "FROM raf_scores"
            )
            row = cur.fetchone() or {}
            kpi["patients_with_raf"] = int(row.get("cnt") or 0)
            kpi["average_raf"] = round(float(row.get("avg_raf") or 0), 4)

            # Open care gaps
            try:
                cur.execute(
                    "SELECT COUNT(*) AS cnt FROM care_gap_tasks WHERE status NOT IN ('closed','resolved')"
                )
                kpi["open_gaps"] = int((cur.fetchone() or {}).get("cnt", 0))
            except Exception:  # noqa: BLE001 — best-effort guard
                logger.debug("swallowed exception", exc_info=True)

            # Pending provider attestations
            try:
                cur.execute(
                    "SELECT COUNT(*) AS cnt FROM provider_attestations WHERE status = 'pending'"
                )
                kpi["pending_attestations"] = int((cur.fetchone() or {}).get("cnt", 0))
            except Exception:  # noqa: BLE001 — best-effort guard
                logger.debug("swallowed exception", exc_info=True)

            # Unreviewed suspects
            try:
                cur.execute(
                    "SELECT COUNT(*) AS cnt FROM suspect_conditions WHERE status = 'pending'"
                )
                kpi["suspects_unreviewed"] = int((cur.fetchone() or {}).get("cnt", 0))
            except Exception:  # noqa: BLE001 — best-effort guard
                logger.debug("swallowed exception", exc_info=True)

            # Claims last 30 days
            try:
                cur.execute(
                    "SELECT COUNT(*) AS cnt FROM claims "
                    "WHERE service_date >= DATE_SUB(CURDATE(), INTERVAL 30 DAY)"
                )
                kpi["claims_last_30d"] = int((cur.fetchone() or {}).get("cnt", 0))
            except Exception:  # noqa: BLE001 — best-effort guard
                logger.debug("swallowed exception", exc_info=True)

            # AWV due this calendar month
            try:
                cur.execute(
                    "SELECT COUNT(*) AS cnt FROM awv_appointments "
                    "WHERE scheduled_date >= DATE_FORMAT(CURDATE(), '%Y-%m-01') "
                    "  AND scheduled_date < DATE_FORMAT(DATE_ADD(CURDATE(), INTERVAL 1 MONTH), '%Y-%m-01') "
                    "  AND status NOT IN ('completed','cancelled')"
                )
                kpi["awv_due_this_month"] = int((cur.fetchone() or {}).get("cnt", 0))
            except Exception:  # noqa: BLE001 — best-effort guard
                logger.debug("swallowed exception", exc_info=True)

            # Unread alerts (across all users for the tenant — aggregate metric)
            try:
                cur.execute(
                    "SELECT COUNT(*) AS cnt FROM dashboard_alerts "
                    "WHERE tenant_id = %s AND is_read = 0",
                    (tenant_id,),
                )
                kpi["unread_alerts"] = int((cur.fetchone() or {}).get("cnt", 0))
            except Exception:  # noqa: BLE001 — best-effort guard
                logger.debug("swallowed exception", exc_info=True)

    except Exception as exc:
        logger.error("realtime: get_live_kpi error: %s", exc)
        kpi["error"] = True

    return kpi


# ---------------------------------------------------------------------------
# Public emit helper — the single entry point for other services
# ---------------------------------------------------------------------------

def emit_event(
    event_type: str,
    payload: dict[str, Any],
    *,
    tenant_id: str,
    user_id: int | None = None,
    title: str | None = None,
    message: str | None = None,
    severity: str | None = None,
    patient_id: str | None = None,
    provider_npi: str | None = None,
    persist: bool = True,
) -> None:
    """
    Emit a real-time event to connected SSE/WebSocket clients.

    This is the single entry point that all other services should call.
    It is intentionally synchronous so it can be called from both async
    and sync contexts without ceremony.

    Parameters
    ----------
    event_type : str
        One of REALTIME_EVENTS.
    payload : dict
        Arbitrary event data that will appear under the ``data`` key.
    tenant_id : str
        Routes the event only to connections belonging to this tenant.
    user_id : int | None
        When set, restricts delivery to a single user's connections.
    title : str | None
        Short human-readable summary used when persisting an alert row.
    message : str | None
        Longer detail for the alert drawer.
    severity : str | None
        'info' | 'warning' | 'critical'  (defaults per event type).
    patient_id : str | None
        Patient context for the alert, used for deep-linking.
    provider_npi : str | None
        Provider context for the alert.
    persist : bool
        Set False to suppress writing to dashboard_alerts (e.g. for pure
        KPI refresh pings that do not need to appear in the alert list).
    """
    alert_id: int | None = None

    # Persist before broadcast so the id is available in the event payload
    if persist and user_id is not None and event_type in _EVENT_TO_ALERT_TYPE:
        alert_id = persist_alert(
            event_type=event_type,
            title=title or event_type.replace("_", " ").title(),
            message=message,
            user_id=user_id,
            tenant_id=tenant_id,
            severity=severity,
            patient_id=patient_id,
            provider_npi=provider_npi,
            metadata=payload,
        )

    event_envelope: dict[str, Any] = {
        "event_type": event_type,
        "tenant_id": tenant_id,
        "user_id": user_id,
        "alert_id": alert_id,
        "severity": severity or _EVENT_TO_DEFAULT_SEVERITY.get(event_type, "info"),
        "title": title,
        "data": payload,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    # Broadcast to live connections (sync-safe path)
    connection_manager.broadcast_sync(event_envelope, tenant_id, user_id)

    logger.debug(
        "realtime: emit_event type=%s tenant=%s user=%s alert_id=%s",
        event_type, tenant_id, user_id, alert_id,
    )


# ---------------------------------------------------------------------------
# RAF score publish helpers — called by the RAF inbox worker
# ---------------------------------------------------------------------------

def _build_raf_updated_event(
    pid: int, tenant_id: str, raf_score: float | None
) -> dict[str, Any]:
    return {
        "type": "raf_updated",
        "pid": int(pid),
        "tenant_id": str(tenant_id),
        "raf_score": float(raf_score) if raf_score is not None else None,
        "ts": datetime.now(timezone.utc).isoformat(),
    }


async def publish_raf_updated(
    pid: int,
    tenant_id: str,
    raf_score: float | None,
) -> None:
    """
    Push a ``raf_updated`` event to every SSE client in the given tenant
    (backend-side, async context). Uses the in-process ConnectionManager
    which itself routes through Redis pub/sub when configured.
    """
    event = _build_raf_updated_event(pid, tenant_id, raf_score)
    try:
        await connection_manager.broadcast(event, str(tenant_id))
        logger.info(
            "realtime: publish_raf_updated pid=%s tenant=%s raf_score=%s",
            pid, tenant_id, raf_score,
        )
    except Exception as exc:
        logger.error(
            "realtime: publish_raf_updated failed pid=%s tenant=%s: %s",
            pid, tenant_id, exc,
        )


def publish_raf_updated_sync(
    pid: int,
    tenant_id: str,
    raf_score: float | None,
) -> None:
    """
    Publish a ``raf_updated`` event from a worker process (no event loop,
    no local SSE clients). Writes the event to the same Redis pub/sub
    channel that the backend's ConnectionManager subscribes to, so the
    event fans out to all SSE clients attached to the backend processes.

    Never raises — errors are logged and swallowed.
    """
    import json as _json

    import redis as _redis

    event = _build_raf_updated_event(pid, tenant_id, raf_score)
    payload = {
        "event": event,
        "tenant_id": str(tenant_id),
        "user_id": None,
    }
    try:
        client = _redis.from_url(settings.redis_url, decode_responses=True)
        client.publish(connection_manager._redis_channel, _json.dumps(payload))
        logger.info(
            "realtime: publish_raf_updated_sync pid=%s tenant=%s raf_score=%s (redis)",
            pid, tenant_id, raf_score,
        )
    except Exception as exc:
        logger.error(
            "realtime: publish_raf_updated_sync failed pid=%s tenant=%s: %s",
            pid, tenant_id, exc,
        )


# ---------------------------------------------------------------------------
# broadcast_patient_event — public async API for patient pipeline events
# ---------------------------------------------------------------------------

_PATIENT_EVENT_TYPES = frozenset({"patient.synced", "patient.scored", "patient.analyzed"})


async def broadcast_patient_event(event_type: str, payload: dict[str, Any]) -> None:
    """
    Push a patient-pipeline event to every SSE client in the payload's tenant.

    Parameters
    ----------
    event_type : str
        One of "patient.synced", "patient.scored", "patient.analyzed".
    payload : dict
        Must include ``pid`` and ``tenant_id``.  Additional fields such as
        ``raf_score``, ``suspects_count``, and ``hcc_count`` are passed
        through verbatim to the SSE ``data`` field.

    Behaviour
    ---------
    - Validates ``event_type`` and ``tenant_id`` / ``pid`` presence.
    - Attaches an ISO-8601 ``timestamp`` if the caller omitted one.
    - Routes through ``connection_manager.broadcast`` which uses Redis
      pub/sub when available, falling back to the in-process asyncio.Queue.
    - Slow consumers are protected by the per-connection ``maxsize=256``
      queue: ``put_nowait`` drops the event and logs a warning rather than
      blocking.
    - Never raises — errors are logged and swallowed so callers are not
      interrupted.

    Example
    -------
    ::

        await broadcast_patient_event(
            "patient.scored",
            {"pid": 42, "tenant_id": "1", "raf_score": 1.87},
        )
    """
    if event_type not in _PATIENT_EVENT_TYPES:
        logger.warning(
            "broadcast_patient_event: unknown event_type=%r (expected one of %s)",
            event_type, sorted(_PATIENT_EVENT_TYPES),
        )

    tenant_id = str(payload.get("tenant_id", ""))
    if not tenant_id:
        logger.error("broadcast_patient_event: missing tenant_id in payload, dropping event")
        return

    pid = payload.get("pid")
    if pid is None:
        logger.error("broadcast_patient_event: missing pid in payload, dropping event")
        return

    envelope: dict[str, Any] = {
        "event_type": event_type,
        "pid": int(pid),
        "tenant_id": tenant_id,
        "timestamp": payload.get("timestamp") or datetime.now(timezone.utc).isoformat(),
        **{k: v for k, v in payload.items() if k not in {"event_type", "tenant_id", "pid", "timestamp"}},
    }

    try:
        await connection_manager.broadcast(envelope, tenant_id)
        logger.info(
            "realtime: broadcast_patient_event type=%s pid=%s tenant=%s",
            event_type, pid, tenant_id,
        )
    except Exception as exc:
        logger.error(
            "realtime: broadcast_patient_event failed type=%s pid=%s tenant=%s: %s",
            event_type, pid, tenant_id, exc,
        )
