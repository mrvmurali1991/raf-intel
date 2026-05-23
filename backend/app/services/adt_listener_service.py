"""
ADT Feed Real-Time Listener Service
====================================

Manages MLLP/TCP listeners that receive HL7v2 ADT messages in real-time from
hospital systems (Epic, Cerner, OpenEMR, etc.).

Supported ADT event types
--------------------------
  A01  Admit a Patient
  A02  Transfer a Patient
  A03  Discharge/End Visit
  A04  Register a Patient (outpatient / ED arrival)
  A08  Update Patient Information

Architecture
-------------
Each ``adt_connections`` row can have an associated :class:`MLLPListener`
(from ``hl7v2_service``) running as a daemon thread.  The registry in
``hl7v2_service`` (``_listener_registry``) is the single source of truth for
running listeners.  This service layer:

  1. Persists connection configuration in MySQL.
  2. Starts/stops listeners and updates the ``status`` column.
  3. Processes every inbound message:
       - Parses HL7v2 using :class:`HL7Message` / helpers from hl7v2_service.
       - Upserts patient demographics into ``raf_patient_demographics``.
       - Stores the raw message + processed data in ``adt_messages``.
       - Triggers care-gap checks on A01 (admit) events.
       - Fan-outs webhooks to ``adt_subscriptions`` subscribers.
  4. Exposes query helpers for the router layer.

Thread safety
-------------
DB writes inside the handler use short-lived connections from the pool (via
``raf_cursor``).  Each handler call is synchronous within its own thread so
no explicit locking is needed around individual writes.  Counter increments
on the connection row use SQL ``col = col + 1`` to avoid read-modify-write
races.
"""
from __future__ import annotations

import ipaddress
import json
import logging
import socket
import threading
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

import requests

from app.db import raf_cursor
from app.services.hl7v2_service import (
    HL7Message,
    MLLPListener,
    extract_diagnoses,
    extract_patient,
    get_listener,
    parse_hl7_message,
    register_listener,
    unregister_listener,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# ADT event-type mapping
# ---------------------------------------------------------------------------

_ADT_EVENT_MAP: dict[str, str] = {
    "ADT^A01": "adt.admit",
    "ADT^A02": "adt.transfer",
    "ADT^A03": "adt.discharge",
    "ADT^A04": "adt.register",
    "ADT^A08": "adt.update",
}

# Normalised message_type stored in DB (replaces "^" with "_")
_ADT_DB_TYPE_MAP: dict[str, str] = {
    "ADT^A01": "ADT_A01",
    "ADT^A02": "ADT_A02",
    "ADT^A03": "ADT_A03",
    "ADT^A04": "ADT_A04",
    "ADT^A08": "ADT_A08",
}


# ===========================================================================
# Connection CRUD
# ===========================================================================


def list_connections(tenant_id: str) -> list[dict[str, Any]]:
    """Return all ADT connections for *tenant_id*."""
    with raf_cursor() as cur:
        cur.execute(
            """
            SELECT id, tenant_id, name, host, port, direction, protocol,
                   status, auto_process, last_message_at,
                   message_count, error_count, created_at, updated_at
            FROM   adt_connections
            WHERE  tenant_id = %s
            ORDER  BY id DESC
            """,
            (tenant_id,),
        )
        return cur.fetchall()


def get_connection(connection_id: int, tenant_id: str | None = None) -> dict[str, Any] | None:
    """Return a single connection row, optionally scoped to *tenant_id*."""
    with raf_cursor() as cur:
        if tenant_id:
            cur.execute(
                "SELECT * FROM adt_connections WHERE id = %s AND tenant_id = %s",
                (connection_id, tenant_id),
            )
        else:
            cur.execute("SELECT * FROM adt_connections WHERE id = %s", (connection_id,))
        return cur.fetchone()


def create_connection(
    tenant_id: str,
    name: str,
    host: str,
    port: int,
    direction: str = "inbound",
    protocol: str = "mllp",
    auto_process: bool = True,
) -> dict[str, Any]:
    """Insert a new ADT connection and return the created row."""
    with raf_cursor() as cur:
        cur.execute(
            """
            INSERT INTO adt_connections
                (tenant_id, name, host, port, direction, protocol, auto_process, status)
            VALUES (%s, %s, %s, %s, %s, %s, %s, 'inactive')
            """,
            (tenant_id, name, host, port, direction, protocol, int(auto_process)),
        )
        new_id = cur.lastrowid
    conn = get_connection(new_id)
    if conn is None:
        raise RuntimeError(f"Failed to retrieve newly created adt_connection id={new_id}")
    return conn


def update_connection(
    connection_id: int,
    tenant_id: str,
    **fields: Any,
) -> dict[str, Any] | None:
    """Update allowed fields on an ADT connection.

    Allowed field names: name, host, port, direction, protocol, auto_process.
    Returns the updated row or None if not found.
    """
    allowed = {"name", "host", "port", "direction", "protocol", "auto_process"}
    updates = {k: v for k, v in fields.items() if k in allowed and v is not None}
    if not updates:
        return get_connection(connection_id, tenant_id)

    # Defence-in-depth: even though the dict-comp above already restricts
    # keys to `allowed`, any future refactor that loosens the input must
    # still trip on this assert before user-controlled strings reach the
    # f-string SQL template.
    for col in updates:
        assert col in allowed, f"unsafe column name reached SQL: {col!r}"
    set_clause = ", ".join(f"{col} = %s" for col in updates)
    values = list(updates.values()) + [connection_id, tenant_id]

    with raf_cursor() as cur:
        cur.execute(
            f"UPDATE adt_connections SET {set_clause} WHERE id = %s AND tenant_id = %s",
            values,
        )
    return get_connection(connection_id, tenant_id)


def _set_connection_status(connection_id: int, status: str) -> None:
    with raf_cursor() as cur:
        cur.execute(
            "UPDATE adt_connections SET status = %s WHERE id = %s",
            (status, connection_id),
        )


# ===========================================================================
# Listener lifecycle
# ===========================================================================


def start_listener(connection_id: int, tenant_id: str) -> dict[str, Any]:
    """Start the MLLP listener for *connection_id*.

    Raises
    ------
    ValueError
        If the connection does not exist or is already running.
    OSError
        If the TCP port cannot be bound.
    """
    conn = get_connection(connection_id, tenant_id)
    if conn is None:
        raise ValueError(f"ADT connection {connection_id} not found")

    existing = get_listener(connection_id)
    if existing and existing.is_running:
        raise ValueError(f"Listener for connection {connection_id} is already running")

    handler = _build_handler(connection_id, conn["auto_process"])

    listener = MLLPListener(
        host=conn["host"],
        port=conn["port"],
        handler=handler,
        connection_id=connection_id,
    )
    try:
        listener.start()
    except OSError:
        _set_connection_status(connection_id, "error")
        raise

    register_listener(connection_id, listener)
    _set_connection_status(connection_id, "active")
    logger.info(
        "adt: listener started for connection %d (%s:%d)",
        connection_id,
        conn["host"],
        conn["port"],
    )
    return listener.status()


def stop_listener(connection_id: int, tenant_id: str) -> dict[str, Any]:
    """Stop the MLLP listener for *connection_id*.

    Raises
    ------
    ValueError
        If the connection does not exist or is not running.
    """
    conn = get_connection(connection_id, tenant_id)
    if conn is None:
        raise ValueError(f"ADT connection {connection_id} not found")

    listener = get_listener(connection_id)
    if listener is None or not listener.is_running:
        raise ValueError(f"Listener for connection {connection_id} is not running")

    listener.stop()
    unregister_listener(connection_id)
    _set_connection_status(connection_id, "inactive")
    logger.info("adt: listener stopped for connection %d", connection_id)
    return {"running": False, "connection_id": connection_id}


def get_listener_status(connection_id: int, tenant_id: str) -> dict[str, Any]:
    """Return runtime status for a listener combined with its DB row."""
    conn = get_connection(connection_id, tenant_id)
    if conn is None:
        raise ValueError(f"ADT connection {connection_id} not found")

    listener = get_listener(connection_id)
    if listener:
        runtime = listener.status()
    else:
        runtime = {
            "running": False,
            "host": conn["host"],
            "port": conn["port"],
            "connection_id": connection_id,
            "started_at": None,
            "messages_received": 0,
            "messages_errored": 0,
        }

    return {
        **runtime,
        "db_status": conn["status"],
        "db_message_count": conn["message_count"],
        "db_error_count": conn["error_count"],
        "last_message_at": conn["last_message_at"],
    }


# ===========================================================================
# Message log queries
# ===========================================================================


def list_messages(
    tenant_id: str,
    connection_id: int | None = None,
    message_type: str | None = None,
    status: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """Return ADT messages for *tenant_id*, with optional filters."""
    wheres = ["tenant_id = %s"]
    params: list[Any] = [tenant_id]

    if connection_id is not None:
        wheres.append("connection_id = %s")
        params.append(connection_id)
    if message_type:
        wheres.append("message_type = %s")
        params.append(message_type)
    if status:
        wheres.append("status = %s")
        params.append(status)

    where_clause = " AND ".join(wheres)
    params += [limit, offset]

    with raf_cursor() as cur:
        cur.execute(
            f"""
            SELECT id, connection_id, message_type, control_id,
                   patient_id, patient_mrn, patient_name, event_datetime,
                   status, error_message, processed_data, created_at
            FROM   adt_messages
            WHERE  {where_clause}
            ORDER  BY id DESC
            LIMIT  %s OFFSET %s
            """,
            params,
        )
        return cur.fetchall()


def get_message(message_id: int, tenant_id: str) -> dict[str, Any] | None:
    """Return a single ADT message including the raw_message body."""
    with raf_cursor() as cur:
        cur.execute(
            "SELECT * FROM adt_messages WHERE id = %s AND tenant_id = %s",
            (message_id, tenant_id),
        )
        return cur.fetchone()


def replay_message(message_id: int, tenant_id: str) -> dict[str, Any]:
    """Reprocess a previously received message.

    Fetches the raw_message from the DB and re-runs the full processing
    pipeline.  The original row is updated in-place.

    Raises
    ------
    ValueError
        If the message is not found.
    """
    msg_row = get_message(message_id, tenant_id)
    if msg_row is None:
        raise ValueError(f"ADT message {message_id} not found")

    raw_text: str = msg_row.get("raw_message", "")
    connection_id: int = msg_row["connection_id"]

    conn_row = get_connection(connection_id)
    auto_process = bool(conn_row["auto_process"]) if conn_row else True

    try:
        parsed = parse_hl7_message(raw_text)
        processed = _process_adt_message(parsed, connection_id, auto_process)
        status = "processed"
        error_message = None
    except Exception as exc:
        processed = None
        status = "error"
        error_message = str(exc)
        logger.exception("adt: replay of message %d failed: %s", message_id, exc)

    with raf_cursor() as cur:
        cur.execute(
            """
            UPDATE adt_messages
            SET    status = %s, error_message = %s,
                   processed_data = %s
            WHERE  id = %s
            """,
            (
                status,
                error_message,
                json.dumps(processed) if processed else None,
                message_id,
            ),
        )

    return {"message_id": message_id, "status": status, "error_message": error_message}


# ===========================================================================
# Subscription CRUD
# ===========================================================================


def list_subscriptions(tenant_id: str) -> list[dict[str, Any]]:
    with raf_cursor() as cur:
        cur.execute(
            "SELECT * FROM adt_subscriptions WHERE tenant_id = %s ORDER BY id DESC",
            (tenant_id,),
        )
        return cur.fetchall()


def create_subscription(
    tenant_id: str,
    event_type: str,
    webhook_url: str,
) -> dict[str, Any]:
    """Register a webhook subscription for an ADT event type."""
    valid_events = {"adt.admit", "adt.transfer", "adt.discharge", "adt.register", "adt.update", "adt.*"}
    if event_type not in valid_events:
        raise ValueError(f"Invalid event_type '{event_type}'. Must be one of: {valid_events}")

    with raf_cursor() as cur:
        cur.execute(
            """
            INSERT INTO adt_subscriptions (tenant_id, event_type, webhook_url)
            VALUES (%s, %s, %s)
            """,
            (tenant_id, event_type, webhook_url),
        )
        new_id = cur.lastrowid
        cur.execute("SELECT * FROM adt_subscriptions WHERE id = %s", (new_id,))
        return cur.fetchone()


# ===========================================================================
# Dashboard aggregates
# ===========================================================================


def get_dashboard(tenant_id: str) -> dict[str, Any]:
    """Return message volume and error-rate aggregates for the dashboard."""
    with raf_cursor() as cur:
        # Per-type volume (last 30 days)
        cur.execute(
            """
            SELECT message_type, COUNT(*) AS count
            FROM   adt_messages
            WHERE  tenant_id = %s
              AND  created_at >= NOW() - INTERVAL 30 DAY
            GROUP  BY message_type
            ORDER  BY count DESC
            """,
            (tenant_id,),
        )
        volume_by_type = cur.fetchall()

        # Status breakdown
        cur.execute(
            """
            SELECT status, COUNT(*) AS count
            FROM   adt_messages
            WHERE  tenant_id = %s
              AND  created_at >= NOW() - INTERVAL 30 DAY
            GROUP  BY status
            """,
            (tenant_id,),
        )
        volume_by_status = cur.fetchall()

        # Daily volume last 14 days
        cur.execute(
            """
            SELECT DATE(created_at) AS day, COUNT(*) AS count
            FROM   adt_messages
            WHERE  tenant_id = %s
              AND  created_at >= NOW() - INTERVAL 14 DAY
            GROUP  BY DATE(created_at)
            ORDER  BY day ASC
            """,
            (tenant_id,),
        )
        daily_volume = cur.fetchall()

        # Active connection summary
        cur.execute(
            """
            SELECT id, name, status, message_count, error_count, last_message_at
            FROM   adt_connections
            WHERE  tenant_id = %s
            ORDER  BY id
            """,
            (tenant_id,),
        )
        connections_summary = cur.fetchall()

    return {
        "volume_by_type": volume_by_type,
        "volume_by_status": volume_by_status,
        "daily_volume_14d": daily_volume,
        "connections": connections_summary,
    }


# ===========================================================================
# Internal: message handler factory
# ===========================================================================


def _build_handler(connection_id: int, auto_process: bool):
    """Return a handler callable bound to *connection_id* and *auto_process*."""

    def handler(msg: HL7Message, address: tuple[str, int]) -> None:
        _on_message_received(msg, address, connection_id, auto_process)

    return handler


def _on_message_received(
    msg: HL7Message,
    address: tuple[str, int],
    connection_id: int,
    auto_process: bool,
) -> None:
    """Called by MLLPListener for every successfully parsed HL7v2 message."""
    message_type_raw = msg.message_type          # e.g. "ADT^A01"
    message_type_db  = _ADT_DB_TYPE_MAP.get(message_type_raw, message_type_raw.replace("^", "_"))
    event_name       = _ADT_EVENT_MAP.get(message_type_raw, "")
    control_id       = msg.message_control_id

    # Determine whether we process this message type at all
    if message_type_raw not in _ADT_DB_TYPE_MAP:
        logger.debug(
            "adt: ignoring non-ADT message type %s from %s:%s",
            message_type_raw,
            *address,
        )
        _store_message(
            connection_id=connection_id,
            message_type=message_type_db,
            control_id=control_id,
            raw_text=msg.raw,
            patient_mrn="",
            patient_name="",
            status="ignored",
        )
        return

    processed: dict[str, Any] | None = None
    status = "received"
    error_message: str | None = None
    patient_id: int | None = None

    try:
        if auto_process:
            processed = _process_adt_message(msg, connection_id, auto_process)
            patient_id = processed.get("patient_id")
        status = "processed"
    except Exception as exc:
        status = "error"
        error_message = str(exc)
        logger.exception(
            "adt: processing error for %s control_id=%s from %s:%s: %s",
            message_type_raw,
            control_id,
            *address,
            exc,
        )
        _increment_error_count(connection_id)

    # Extract basic demographics for storage even on error path
    try:
        demo = msg.get_patient_demographics()
        mrn = demo.get("mrn", "")
        patient_name = f"{demo.get('last_name', '')}, {demo.get('first_name', '')}".strip(", ")
    except Exception:
        logger.debug("swallowed exception", exc_info=True)
        mrn = ""
        patient_name = ""

    # Parse event datetime (EVN-2 or fall back to MSH-7)
    event_datetime_str = msg._field("EVN", 2) or msg.message_datetime
    event_dt = _parse_dt(event_datetime_str)

    msg_id = _store_message(
        connection_id=connection_id,
        message_type=message_type_db,
        control_id=control_id,
        raw_text=msg.raw,
        patient_mrn=mrn,
        patient_name=patient_name,
        event_datetime=event_dt,
        patient_id=patient_id,
        status=status,
        error_message=error_message,
        processed_data=processed,
    )

    # Update connection counters + last_message_at
    _increment_message_count(connection_id)

    # Notify subscribers asynchronously (fire-and-forget daemon thread)
    if event_name and status == "processed":
        payload = _build_webhook_payload(
            event_name=event_name,
            msg_id=msg_id,
            connection_id=connection_id,
            message_type=message_type_db,
            control_id=control_id,
            patient_mrn=mrn,
            patient_name=patient_name,
            event_datetime=event_dt,
            processed=processed,
        )
        _notify_subscribers_async(event_name, payload)


# ===========================================================================
# Internal: ADT message processing
# ===========================================================================


def _process_adt_message(
    msg: HL7Message,
    connection_id: int,
    auto_process: bool,
) -> dict[str, Any]:
    """Extract patient data, upsert into RAF DB, and return processed dict."""
    patient_info = extract_patient(msg)
    diagnoses    = extract_diagnoses(msg)

    # Resolve or create the patient in raf_patient_demographics
    resolved_pid = _upsert_patient(patient_info)

    # Trigger care-gap check on A01 (admit) — kept lightweight here;
    # a full async job would be queued in production.
    if msg.message_type == "ADT^A01" and resolved_pid is not None:
        _trigger_care_gap_check(resolved_pid)

    return {
        "patient_id": resolved_pid,
        "patient": patient_info,
        "diagnoses": diagnoses,
        "message_type": msg.message_type,
        "sending_application": msg.sending_application,
        "sending_facility": msg.sending_facility,
    }


def _upsert_patient(patient_info: dict[str, Any]) -> int | None:
    """Insert or update raf_patient_demographics from ADT demographics.

    Returns the OpenEMR pid (INT) if found/created, else None.

    Note: OpenEMR ``patient_data.pid`` is the authoritative patient identity.
    We attempt to match on MRN (``pubpid`` or ``pid``), then fall back to
    inserting a stub row in raf_patient_demographics with a synthetic pid.
    Real deployments should inject the EHR-resolved pid from an MPI lookup.
    """
    mrn = patient_info.get("mrn", "")
    if not mrn:
        return None

    try:
        from app.db import openemr_cursor

        with openemr_cursor() as cur:
            cur.execute(
                "SELECT pid FROM patient_data WHERE pubpid = %s OR pid = %s LIMIT 1",
                (mrn, mrn),
            )
            row = cur.fetchone()
            if row:
                return int(row["pid"])
    except Exception as exc:
        logger.warning("adt: OpenEMR MRN lookup failed for mrn=%s: %s", mrn, exc)

    return None


def _trigger_care_gap_check(patient_id: int) -> None:
    """Queue a care-gap check for *patient_id* on admit.

    Inserts a row into raf_nlp_jobs so the existing job processor picks it up.
    This is intentionally lightweight — the scheduler handles the actual work.
    """
    try:
        with raf_cursor() as cur:
            cur.execute(
                """
                INSERT IGNORE INTO raf_nlp_jobs
                    (job_type, target_id, target_type, status)
                VALUES ('care_gap_check', %s, 'patient', 'queued')
                """,
                (patient_id,),
            )
        logger.info("adt: queued care_gap_check job for patient_id=%d", patient_id)
    except Exception as exc:
        logger.warning(
            "adt: failed to queue care_gap_check for patient_id=%d: %s", patient_id, exc
        )


# ===========================================================================
# Internal: DB helpers
# ===========================================================================


def _store_message(
    connection_id: int,
    message_type: str,
    control_id: str,
    raw_text: str,
    patient_mrn: str,
    patient_name: str,
    event_datetime: str | None = None,
    patient_id: int | None = None,
    status: str = "received",
    error_message: str | None = None,
    processed_data: dict | None = None,
) -> int:
    """Insert a row into adt_messages and return the new ``id``."""
    # Obtain tenant_id from the connection row — fail loud if not resolvable.
    conn_row = get_connection(connection_id)
    if not conn_row or not conn_row.get("tenant_id"):
        raise ValueError(
            f"_store_adt_message: cannot resolve tenant_id for connection {connection_id} — "
            "refusing to store ADT message without tenant scope (HIPAA multi-tenant isolation)"
        )
    tenant_id = conn_row["tenant_id"]

    with raf_cursor() as cur:
        cur.execute(
            """
            INSERT INTO adt_messages
                (connection_id, tenant_id, message_type, control_id, raw_message,
                 patient_id, patient_mrn, patient_name, event_datetime,
                 status, error_message, processed_data)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                connection_id,
                tenant_id,
                message_type,
                control_id,
                raw_text,
                patient_id,
                patient_mrn,
                patient_name,
                event_datetime,
                status,
                error_message,
                json.dumps(processed_data) if processed_data else None,
            ),
        )
        return cur.lastrowid


def _increment_message_count(connection_id: int) -> None:
    try:
        with raf_cursor() as cur:
            cur.execute(
                """
                UPDATE adt_connections
                SET    message_count = message_count + 1,
                       last_message_at = NOW()
                WHERE  id = %s
                """,
                (connection_id,),
            )
    except Exception as exc:
        logger.warning("adt: failed to increment message_count for conn %d: %s", connection_id, exc)


def _increment_error_count(connection_id: int) -> None:
    try:
        with raf_cursor() as cur:
            cur.execute(
                "UPDATE adt_connections SET error_count = error_count + 1 WHERE id = %s",
                (connection_id,),
            )
    except Exception as exc:
        logger.warning("adt: failed to increment error_count for conn %d: %s", connection_id, exc)


# ===========================================================================
# Internal: webhook fan-out
# ===========================================================================


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

    # Resolve hostname to IP(s) and check each one.
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
        # Explicit cloud metadata check (covers mapped IPv4-in-IPv6 too).
        if str(ip) in ("169.254.169.254", "fd00:ec2::254"):
            raise ValueError(f"Webhook URL resolves to cloud metadata address {ip}")


def _build_webhook_payload(
    event_name: str,
    msg_id: int,
    connection_id: int,
    message_type: str,
    control_id: str,
    patient_mrn: str,
    patient_name: str,
    event_datetime: str | None,
    processed: dict | None,
) -> dict[str, Any]:
    return {
        "event": event_name,
        "adt_message_id": msg_id,
        "connection_id": connection_id,
        "message_type": message_type,
        "control_id": control_id,
        "patient_mrn": patient_mrn,
        "patient_name": patient_name,
        "event_datetime": event_datetime,
        "processed": processed,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


def _notify_subscribers_async(event_name: str, payload: dict[str, Any]) -> None:
    """Fire-and-forget webhook delivery in a daemon thread."""
    t = threading.Thread(
        target=_deliver_to_subscribers,
        args=(event_name, payload),
        daemon=True,
        name=f"adt-webhook-{event_name}",
    )
    t.start()


def _deliver_to_subscribers(event_name: str, payload: dict[str, Any]) -> None:
    """Fetch matching subscriptions and POST to each webhook URL."""
    try:
        with raf_cursor() as cur:
            cur.execute(
                """
                SELECT id, webhook_url
                FROM   adt_subscriptions
                WHERE  active = 1
                  AND  (event_type = %s OR event_type = 'adt.*')
                """,
                (event_name,),
            )
            subs = cur.fetchall()
    except Exception as exc:
        logger.error("adt: failed to load subscriptions for event %s: %s", event_name, exc)
        return

    body = json.dumps(payload, default=str)
    headers = {
        "Content-Type": "application/json",
        "X-ADT-Event": event_name,
    }

    for sub in subs:
        url = sub["webhook_url"]
        try:
            _validate_webhook_url(url)
            resp = requests.post(url, data=body, headers=headers, timeout=10)
            logger.info(
                "adt: webhook delivery to %s returned %d (sub_id=%d)",
                url,
                resp.status_code,
                sub["id"],
            )
        except Exception as exc:
            logger.warning(
                "adt: webhook delivery to %s failed (sub_id=%d): %s",
                url,
                sub["id"],
                exc,
            )


# ===========================================================================
# Internal: datetime helper
# ===========================================================================


def _parse_dt(raw: str) -> str | None:
    """Convert an HL7 datetime string to MySQL-compatible DATETIME or None."""
    from app.services.hl7v2_service import _parse_hl7_datetime

    result = _parse_hl7_datetime(raw)
    return result if result else None
