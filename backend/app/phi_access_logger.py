"""
HIPAA 164.312(b) — PHI Access Logger
======================================

IMMUTABILITY NOTICE
-------------------
The ``phi_access_log`` table is an append-only audit log required by HIPAA
§164.312(b).  DELETE and UPDATE statements against this table are FORBIDDEN.
No application code should ever modify rows after insertion.  Enforcement is
by policy; a DDL trigger is out of scope for this sprint.

Architecture — durable queue writer
-------------------------------------
Records are placed on an in-process ``queue.Queue`` (bounded at 10 000 items).
A single non-daemon background thread drains the queue in micro-batches of up
to 100 rows every 500 ms and writes them to MySQL.

Durability guarantees
~~~~~~~~~~~~~~~~~~~~~
* **atexit handler** — registered once at module import; calls ``_flush_pending``
  so rows queued before a normal interpreter shutdown are written.
* **SIGTERM / SIGINT handlers** — registered once; flush then re-raise so the
  process exits cleanly under Docker / Kubernetes.
* **MySQL-unavailable fallback** — if the INSERT fails, rows are appended to
  ``/tmp/phi_access_overflow.jsonl`` (append-only, one JSON object per line).
  A WARN is emitted so ops can detect the fallback via log scraping.

Metrics (in-memory gauges, exported via ``phi_metrics()``)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
* ``phi_access_log_pending``  — items currently in the queue
* ``phi_access_log_dropped``  — items lost because the queue was full
"""

from __future__ import annotations

import atexit
import json
import logging
import logging.handlers
import os
import queue
import re
import signal
import sys
import threading
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import Depends, Request
from starlette.types import ASGIApp, Receive, Scope, Send

# ---------------------------------------------------------------------------
# Structured file logger — dedicated rotating handler for PHI access records
# ---------------------------------------------------------------------------

_LOG_DIR = Path(__file__).resolve().parent.parent / "logs"
_LOG_DIR.mkdir(exist_ok=True)

_phi_file_logger = logging.getLogger("phi_access_file")
_phi_file_logger.setLevel(logging.INFO)
_phi_file_logger.propagate = False

if not _phi_file_logger.handlers:
    _handler = logging.handlers.RotatingFileHandler(
        _LOG_DIR / "phi_access.log",
        maxBytes=50 * 1024 * 1024,  # 50 MB
        backupCount=12,             # ~600 MB total retention
        encoding="utf-8",
    )
    _handler.setFormatter(logging.Formatter("%(message)s"))
    _phi_file_logger.addHandler(_handler)

_app_logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Overflow fallback file — written when MySQL is unreachable
# ---------------------------------------------------------------------------

_OVERFLOW_PATH = Path(os.getenv("PHI_OVERFLOW_PATH", "/tmp/phi_access_overflow.jsonl"))

# ---------------------------------------------------------------------------
# In-memory metrics gauges
# ---------------------------------------------------------------------------

_metrics: dict[str, int] = {
    "phi_access_log_pending": 0,
    "phi_access_log_dropped": 0,
}


def phi_metrics() -> dict[str, int]:
    """Return a snapshot of PHI logger metrics for ops / health-check endpoints."""
    return dict(_metrics)


# ---------------------------------------------------------------------------
# Bounded in-process queue
# ---------------------------------------------------------------------------

_QUEUE_MAX = 10_000
_BATCH_SIZE = 100
_DRAIN_INTERVAL_S = 0.5

_record_queue: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=_QUEUE_MAX)

# ---------------------------------------------------------------------------
# Low-level write helpers
# ---------------------------------------------------------------------------

# Column mapping note: the production schema stores the user-agent as a
# SHA-256 hash (user_agent_hash CHAR(64)) for HIPAA-minimum-necessary
# compliance — the raw header value is never persisted. The prior INSERT
# referenced a non-existent `user_agent` column, which silently failed
# with `Unknown column 'user_agent' in 'field list'` on every PHI write
# and forced the logger into its overflow-file fallback. The endpoint-side
# symptom was PUT /api/suspects/{id}/accept and /dismiss returning 500
# because the audit-log write happened in the request path. Now we hash
# upstream and persist the hash, matching the live schema.

_INSERT_SQL = (
    "INSERT INTO phi_access_log "
    "(tenant_id, user_id, user_email, action, resource_type, "
    " resource_id, ip_address, user_agent_hash, request_path, "
    " http_method, status_code, occurred_at, request_id) "
    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)"
)


def _hash_user_agent(ua: str | None) -> str | None:
    """SHA-256 of the user-agent string, or None when the UA is missing.
    Hashing rather than storing the raw value matches the schema
    `user_agent_hash CHAR(64)` and avoids persisting potentially
    fingerprintable client metadata."""
    if not ua:
        return None
    import hashlib
    return hashlib.sha256(ua.encode("utf-8", errors="ignore")).hexdigest()


def _record_to_row(r: dict[str, Any]) -> tuple:
    return (
        r.get("tenant_id", "unknown"),
        r.get("user_id", "unknown"),
        r.get("user_email"),
        r.get("action", "READ"),
        r.get("resource_type", "unknown"),
        r.get("resource_id"),
        r.get("ip_address"),
        _hash_user_agent(r.get("user_agent")),
        r.get("request_path"),
        r.get("request_method"),
        r.get("status_code"),
        r.get("timestamp"),
        r.get("request_id") or "00000000-0000-0000-0000-000000000000",
    )


def _write_to_file_log(records: list[dict[str, Any]]) -> None:
    """Always-on write to the rotating file log (SIEM / backup)."""
    for rec in records:
        try:
            _phi_file_logger.info(json.dumps(rec, default=str))
        except Exception:
            logger.debug("swallowed exception", exc_info=True)
            _app_logger.error("PHI file logger write failed", exc_info=True)


def _write_to_db(records: list[dict[str, Any]]) -> bool:
    """Attempt a batch INSERT.  Returns True on success, False on failure."""
    try:
        from app.db import raf_cursor  # local import — avoids circular dep at module load

        rows = [_record_to_row(r) for r in records]
        with raf_cursor() as cur:
            cur.executemany(_INSERT_SQL, rows)
        return True
    except Exception:
        logger.debug("swallowed exception", exc_info=True)
        _app_logger.error(
            "PHI DB write failed (%d rows), falling back to overflow file", len(records),
            exc_info=True,
        )
        return False


def _write_overflow(records: list[dict[str, Any]]) -> None:
    """Append records to the overflow JSONL file when MySQL is unreachable."""
    _app_logger.warning(
        "PHI access logger: MySQL unavailable — writing %d record(s) to overflow file %s",
        len(records),
        _OVERFLOW_PATH,
    )
    try:
        with _OVERFLOW_PATH.open("a", encoding="utf-8") as fh:
            for rec in records:
                fh.write(json.dumps(rec, default=str) + "\n")
    except Exception:
        logger.debug("swallowed exception", exc_info=True)
        _app_logger.error("PHI overflow file write failed — records may be lost!", exc_info=True)


def _write_batch(records: list[dict[str, Any]]) -> None:
    """Write one micro-batch: file log always, DB with overflow fallback."""
    _write_to_file_log(records)
    if not _write_to_db(records):
        _write_overflow(records)


# ---------------------------------------------------------------------------
# Background drain worker (persistent, non-daemon thread)
# ---------------------------------------------------------------------------

def _drain_worker() -> None:
    """Drain the queue in micro-batches until _shutdown_event is set."""
    while not _shutdown_event.is_set():
        _drain_once()
        _shutdown_event.wait(timeout=_DRAIN_INTERVAL_S)
    # Final drain after shutdown signal
    _drain_once(drain_all=True)


def _drain_once(*, drain_all: bool = False) -> None:
    """Pull up to _BATCH_SIZE items (or all remaining if drain_all) and write them."""
    limit = _record_queue.qsize() if drain_all else _BATCH_SIZE
    batch: list[dict[str, Any]] = []
    for _ in range(max(limit, _BATCH_SIZE) if drain_all else _BATCH_SIZE):
        try:
            batch.append(_record_queue.get_nowait())
        except queue.Empty:
            break
    if batch:
        _metrics["phi_access_log_pending"] = max(0, _metrics["phi_access_log_pending"] - len(batch))
        _write_batch(batch)


# ---------------------------------------------------------------------------
# Flush helper — public API for tests and atexit/signal handlers
# ---------------------------------------------------------------------------

def _flush_pending() -> None:
    """Block until the queue is empty and all records are written.

    Safe to call from atexit handlers, signal handlers, and unit tests.
    """
    _drain_once(drain_all=True)


# ---------------------------------------------------------------------------
# Shutdown coordination
# ---------------------------------------------------------------------------

_shutdown_event = threading.Event()

_worker_thread = threading.Thread(
    target=_drain_worker,
    name="phi-access-logger",
    daemon=False,  # NOT a daemon — survives SIGTERM long enough to flush
)
_worker_thread.start()


def _shutdown(*, reraised_signal: int | None = None) -> None:
    """Signal the worker to stop, flush remaining rows, then optionally re-raise."""
    _shutdown_event.set()
    _worker_thread.join(timeout=10)
    if reraised_signal is not None:
        # Re-raise as default signal behaviour so the process actually exits
        signal.signal(reraised_signal, signal.SIG_DFL)
        os.kill(os.getpid(), reraised_signal)


atexit.register(_shutdown)


def _sigterm_handler(signum: int, frame: Any) -> None:  # noqa: ARG001
    _shutdown(reraised_signal=signum)


# Register SIGTERM/SIGINT only from the main thread to avoid ValueError in workers
if threading.current_thread() is threading.main_thread():
    for _sig in (signal.SIGTERM, signal.SIGINT):
        try:
            signal.signal(_sig, _sigterm_handler)
        except (OSError, ValueError):
            pass  # Can't override in some test harnesses — safe to skip

# ---------------------------------------------------------------------------
# Path patterns that indicate PHI access
# ---------------------------------------------------------------------------

_PHI_PATH_RE = re.compile(
    r"/api/"
    r"(?:"
    r"patients"
    r"|encounters"
    r"|diagnos"
    r"|raf"
    r"|submissions"
    r"|analysis"
    r"|suspects"
    r"|attestations"
    r"|care.gaps"
    r"|documents"
    r"|ccda"
    r"|chart.chase"
    r"|awv"
    r"|cohorts"
    r")"
)

# Map HTTP methods to semantic actions
_METHOD_ACTION_MAP = {
    "GET": "READ",
    "POST": "CREATE",
    "PUT": "UPDATE",
    "PATCH": "UPDATE",
    "DELETE": "DELETE",
}

# Extract resource_id from common path patterns like /api/patients/123
_RESOURCE_ID_RE = re.compile(r"/api/patients/(\d+)")


# ---------------------------------------------------------------------------
# Core enqueue function — replaces _fire_and_forget
# ---------------------------------------------------------------------------

def _enqueue(record: dict[str, Any]) -> None:
    """Place a record on the bounded queue.  Drops and counts if full."""
    try:
        _record_queue.put_nowait(record)
        _metrics["phi_access_log_pending"] += 1
    except queue.Full:
        _metrics["phi_access_log_dropped"] += 1
        _app_logger.warning(
            "PHI access queue full (%d capacity) — record dropped for user=%s path=%s",
            _QUEUE_MAX,
            record.get("user_id"),
            record.get("request_path"),
        )


# ---------------------------------------------------------------------------
# 1. ASGI Middleware — automatic PHI access logging
# ---------------------------------------------------------------------------

class PHIAccessLoggingMiddleware:
    """
    ASGI middleware that intercepts responses to PHI-related endpoints and
    logs the access via the durable queue writer.

    It inspects the request path against ``_PHI_PATH_RE`` and, if matched,
    extracts user identity from the JWT (best-effort) and enqueues a log record.
    """

    _SKIP_PREFIXES = ("/health", "/docs", "/redoc", "/openapi.json", "/favicon")

    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path: str = scope.get("path", "")

        # Skip non-PHI and noise endpoints
        for prefix in self._SKIP_PREFIXES:
            if path.startswith(prefix):
                await self.app(scope, receive, send)
                return

        if not _PHI_PATH_RE.search(path):
            await self.app(scope, receive, send)
            return

        # Capture status code from the response
        status_code: int | None = None

        async def send_wrapper(message):
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message.get("status")
            await send(message)

        await self.app(scope, receive, send_wrapper)

        # --- After response is sent, enqueue the access record ---
        try:
            headers = dict(scope.get("headers", []))
            auth_header = headers.get(b"authorization", b"").decode("utf-8", errors="ignore")
            user_agent = headers.get(b"user-agent", b"").decode("utf-8", errors="ignore")

            user_id: str = "anonymous"
            user_email: str | None = None
            _scope_state = scope.get("state") or {}
            tenant_id: str = str(
                getattr(_scope_state, "tenant_id", None)
                or (_scope_state.get("tenant_id") if isinstance(_scope_state, dict) else None)
                or "unknown"
            )

            if auth_header.startswith("Bearer "):
                try:
                    from app.services.auth_service import decode_token
                    payload = decode_token(auth_header[len("Bearer "):])
                    user_id = str(payload.get("sub", "anonymous"))
                    user_email = payload.get("email")
                except Exception:  # noqa: BLE001 — best-effort guard
                    logger.debug("swallowed exception", exc_info=True)

            client = scope.get("client")
            ip_address = client[0] if client else None

            resource_type = "patient"
            for segment in ("encounter", "diagnos", "raf", "submission",
                            "suspect", "attestation", "care.gap", "document",
                            "ccda", "chart.chase", "awv", "cohort", "analysis"):
                if segment in path:
                    resource_type = segment.replace(".", "_").rstrip("s")
                    break

            resource_id: str | None = None
            m = _RESOURCE_ID_RE.search(path)
            if m:
                resource_id = m.group(1)

            method = scope.get("method", "GET")

            record = {
                "timestamp": datetime.now(tz=timezone.utc).isoformat(),
                "user_id": user_id,
                "user_email": user_email,
                "tenant_id": tenant_id,
                "action": _METHOD_ACTION_MAP.get(method, "READ"),
                "resource_type": resource_type,
                "resource_id": resource_id,
                "ip_address": ip_address,
                "user_agent": user_agent[:500] if user_agent else None,
                "request_path": path,
                "request_method": method,
                "status_code": status_code,
            }

            _enqueue(record)

        except Exception:
            logger.debug("swallowed exception", exc_info=True)
            _app_logger.error("PHI access middleware logging failed", exc_info=True)


# ---------------------------------------------------------------------------
# 2. FastAPI Dependency — granular per-endpoint PHI access logging
# ---------------------------------------------------------------------------

def log_phi_access(
    user_id: int | str | None = None,
    patient_id: int | str | None = None,
    action: str = "READ",
    resource: str = "unknown",
    tenant_id: int | str | None = None,
    resource_type: str | None = None,
) -> Callable:
    """
    Return a FastAPI dependency that logs PHI access for the decorated endpoint,
    **or** be called directly with explicit kwargs for programmatic logging.

    FastAPI dependency usage::

        @router.get("/{pid}")
        def get_patient(
            pid: int,
            current_user: dict = Depends(get_current_user),
            _phi: None = Depends(log_phi_access("patient", "READ")),
        ):
            ...

    Direct call usage (e.g. from services or tests)::

        log_phi_access(user_id=1, patient_id=42, action="READ",
                       resource="patient", tenant_id=3)

    When called with keyword arguments instead of positional ``resource_type``
    /``action`` strings, the function enqueues the record immediately and
    returns ``None`` (not a dependency callable).
    """
    # --- Direct programmatic call path (all kwargs provided) ---
    if user_id is not None or patient_id is not None or tenant_id is not None:
        record = {
            "timestamp": datetime.now(tz=timezone.utc).isoformat(),
            "user_id": str(user_id) if user_id is not None else "unknown",
            "user_email": None,
            "tenant_id": str(tenant_id) if tenant_id is not None else "unknown",
            "action": action.upper(),
            "resource_type": resource_type or resource,
            "resource_id": str(patient_id) if patient_id is not None else None,
            "ip_address": None,
            "user_agent": None,
            "request_path": None,
            "request_method": None,
            "status_code": None,
        }
        _enqueue(record)
        return None  # type: ignore[return-value]

    # --- FastAPI dependency factory path (positional resource_type / action) ---
    _resource_type: str = resource_type or resource or "unknown"
    _action: str = action

    def _dependency(request: Request, current_user: dict = Depends(_get_current_user_safe)):
        resource_id: str | None = None
        path_params = request.path_params
        for key in ("pid", "patient_id", "id"):
            if key in path_params:
                resource_id = str(path_params[key])
                break

        forwarded = request.headers.get("X-Forwarded-For")
        ip = (
            forwarded.split(",")[0].strip()
            if forwarded
            else (request.client.host if request.client else None)
        )

        rec = {
            "timestamp": datetime.now(tz=timezone.utc).isoformat(),
            "user_id": str(current_user.get("id", "unknown")) if current_user else "anonymous",
            "user_email": current_user.get("email") if current_user else None,
            "tenant_id": str(current_user.get("tenant_id", "unknown")) if current_user else "unknown",
            "action": _action,
            "resource_type": _resource_type,
            "resource_id": resource_id,
            "ip_address": ip,
            "user_agent": (request.headers.get("User-Agent") or "")[:500] or None,
            "request_path": request.url.path,
            "request_method": request.method,
            "status_code": None,
        }

        _enqueue(rec)

    return _dependency


async def _get_current_user_safe(request: Request) -> dict[str, Any] | None:
    """Best-effort user resolution — returns None instead of raising 401."""
    user = getattr(request.state, "_current_user", None)
    if user is not None:
        return user

    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return None
    try:
        from app.services.auth_service import decode_token
        payload = decode_token(auth_header[len("Bearer "):])
        return {
            "id": payload.get("sub"),
            "email": payload.get("email"),
            "tenant_id": getattr(request.state, "tenant_id", None),
        }
    except Exception:  # noqa: BLE001 — best-effort guard
        logger.debug("swallowed exception", exc_info=True)
        return None
