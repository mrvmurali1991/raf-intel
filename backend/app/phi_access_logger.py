"""
HIPAA 164.312(b) — PHI Access Logger

Provides two complementary mechanisms for logging access to Protected Health
Information:

1. **PHIAccessLoggingMiddleware** — ASGI middleware that automatically logs
   every request whose path contains a patient identifier (``patient_id``,
   ``pid``, or ``{pid}``).  Runs after the response is sent so it never
   blocks request processing.

2. **log_phi_access(resource_type, action)** — A FastAPI dependency factory
   for granular, per-endpoint PHI access logging.  Add it to individual
   routes for explicit control over the logged ``resource_type`` and
   ``action``.

All PHI access records are written to:
- The ``phi_access_log`` database table (durable, queryable for audits).
- A structured file logger at ``logs/phi_access.log`` (backup / SIEM ingest).

Both writes are fire-and-forget via a background thread so the request is
never delayed by logging I/O.
"""

from __future__ import annotations

import json
import logging
import logging.handlers
import os
import re
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from fastapi import Depends, Request
from starlette.types import ASGIApp, Receive, Scope, Send

from app.audit_middleware import request_context

# ---------------------------------------------------------------------------
# Structured file logger — dedicated handler for PHI access records
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
# Core logging function — runs in a background thread
# ---------------------------------------------------------------------------

def _persist_phi_access(record: dict[str, Any]) -> None:
    """Write a PHI access record to both the database and the file logger.

    This function is designed to be called from a daemon thread so it never
    blocks the ASGI request/response cycle.
    """
    # 1. Structured file log (always succeeds if disk is available)
    try:
        _phi_file_logger.info(json.dumps(record, default=str))
    except Exception:
        _app_logger.error("Failed to write PHI access to file log", exc_info=True)

    # 2. Database insert
    try:
        from app.db import raf_cursor  # local import to avoid circular deps

        with raf_cursor() as cur:
            cur.execute(
                "INSERT INTO phi_access_log "
                "(tenant_id, user_id, user_email, action, resource_type, "
                " resource_id, ip_address, user_agent, request_path, "
                " request_method, status_code, accessed_at) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (
                    record.get("tenant_id", "unknown"),
                    record.get("user_id", "unknown"),
                    record.get("user_email"),
                    record.get("action", "READ"),
                    record.get("resource_type", "unknown"),
                    record.get("resource_id"),
                    record.get("ip_address"),
                    record.get("user_agent"),
                    record.get("request_path"),
                    record.get("request_method"),
                    record.get("status_code"),
                    record.get("timestamp"),
                ),
            )
    except Exception:
        _app_logger.error("Failed to persist PHI access log to database", exc_info=True)


def _fire_and_forget(record: dict[str, Any]) -> None:
    """Schedule persistence on a daemon thread so it never blocks the request."""
    t = threading.Thread(target=_persist_phi_access, args=(record,), daemon=True)
    t.start()


# ---------------------------------------------------------------------------
# 1. ASGI Middleware — automatic PHI access logging
# ---------------------------------------------------------------------------

class PHIAccessLoggingMiddleware:
    """
    ASGI middleware that intercepts responses to PHI-related endpoints and
    logs the access asynchronously.

    It inspects the request path against ``_PHI_PATH_RE`` and, if matched,
    extracts user identity from the JWT (best-effort, same approach as the
    existing ``AuditLoggingMiddleware``) and fires a background log write.
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

        # --- After response is sent, log the access ---
        try:
            # Extract user identity from JWT (best-effort)
            headers = dict(scope.get("headers", []))
            auth_header = headers.get(b"authorization", b"").decode("utf-8", errors="ignore")
            user_agent = headers.get(b"user-agent", b"").decode("utf-8", errors="ignore")

            user_id: str = "anonymous"
            user_email: str | None = None
            # Use tenant_id already resolved by TenantGuardMiddleware via request.state.
            # The ASGI scope carries state as a dict; TenantGuardMiddleware stores it there.
            _scope_state = scope.get("state") or {}
            tenant_id: str = str(getattr(_scope_state, "tenant_id", None) or
                                  (_scope_state.get("tenant_id") if isinstance(_scope_state, dict) else None) or
                                  "unknown")

            if auth_header.startswith("Bearer "):
                try:
                    from app.services.auth_service import decode_token
                    payload = decode_token(auth_header[len("Bearer "):])
                    user_id = str(payload.get("sub", "anonymous"))
                    user_email = payload.get("email")
                    # Do NOT read tenant_id from JWT payload; rely on TenantGuardMiddleware state.
                except Exception:
                    pass

            client = scope.get("client")
            ip_address = client[0] if client else None

            # Derive resource_type from path
            resource_type = "patient"  # default for PHI endpoints
            for segment in ("encounter", "diagnos", "raf", "submission",
                            "suspect", "attestation", "care.gap", "document",
                            "ccda", "chart.chase", "awv", "cohort", "analysis"):
                if segment in path:
                    resource_type = segment.replace(".", "_").rstrip("s")
                    break

            # Extract resource_id if present
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

            _fire_and_forget(record)

        except Exception:
            _app_logger.error("PHI access middleware logging failed", exc_info=True)


# ---------------------------------------------------------------------------
# 2. FastAPI Dependency — granular per-endpoint PHI access logging
# ---------------------------------------------------------------------------

def log_phi_access(resource_type: str, action: str = "READ") -> Callable:
    """
    Return a FastAPI dependency that logs PHI access for the decorated endpoint.

    Usage::

        @router.get("/{pid}")
        def get_patient(
            pid: int,
            current_user: dict = Depends(get_current_user),
            _phi: None = Depends(log_phi_access("patient", "READ")),
        ):
            ...

    The dependency extracts user identity from ``current_user`` (injected by
    ``get_current_user``) and request metadata from the ``Request`` object.
    Logging is fire-and-forget on a daemon thread.
    """

    def _dependency(request: Request, current_user: dict = Depends(_get_current_user_safe)):
        # Extract resource_id from path params
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

        record = {
            "timestamp": datetime.now(tz=timezone.utc).isoformat(),
            "user_id": str(current_user.get("id", "unknown")) if current_user else "anonymous",
            "user_email": current_user.get("email") if current_user else None,
            "tenant_id": str(current_user.get("tenant_id", "unknown")) if current_user else "unknown",
            "action": action,
            "resource_type": resource_type,
            "resource_id": resource_id,
            "ip_address": ip,
            "user_agent": (request.headers.get("User-Agent") or "")[:500] or None,
            "request_path": request.url.path,
            "request_method": request.method,
            "status_code": None,  # not yet known at dependency resolution time
        }

        _fire_and_forget(record)
        return None

    return _dependency


async def _get_current_user_safe(request: Request) -> dict[str, Any] | None:
    """Best-effort user resolution — returns None instead of raising 401.

    This avoids duplicating the ``get_current_user`` dependency (which would
    decode the JWT twice) by reusing the already-resolved user if present
    on ``request.state``, or falling back to a lightweight decode.
    """
    # If get_current_user already ran, the user dict is on request.state
    user = getattr(request.state, "_current_user", None)
    if user is not None:
        return user

    # Fallback: lightweight JWT decode (no DB round-trip) for user identity only.
    # Do NOT read tenant_id from JWT; use request.state.tenant_id set by TenantGuardMiddleware.
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
    except Exception:
        return None
