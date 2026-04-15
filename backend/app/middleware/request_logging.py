"""
Structured request logging middleware and audit logging middleware.
"""
import logging
import time
import uuid
from typing import Any

import jwt

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware

from app.services.auth_service import decode_token, log_audit

logger = logging.getLogger(__name__)

_PHI_KEYS = {
    "ssn",
    "dob",
    "DOB",
    "date_of_birth",
    "fname",
    "lname",
    "first_name",
    "last_name",
    "address",
    "phone",
    "email",
    "mbi",
    "medicare_id",
}


def _scrub_phi(data: dict) -> dict:
    """Return a copy of *data* with PHI-sensitive keys replaced by '***REDACTED***'."""
    if not isinstance(data, dict):
        return data
    return {
        k: "***REDACTED***" if k.lower() in _PHI_KEYS else v for k, v in data.items()
    }


class RequestIDMiddleware(BaseHTTPMiddleware):
    """
    Generate a unique request ID for every request and inject it into:
    - The response headers as ``X-Request-ID``
    - The request state as ``request.state.request_id``

    This enables end-to-end tracing across the entire stack.
    """

    async def dispatch(self, request: Request, call_next):
        request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response


class AuditLoggingMiddleware(BaseHTTPMiddleware):
    """
    Lightweight request audit middleware.

    Writes one row per API request to audit_log (path, method, user_id,
    status code, timestamp). Skips health/docs/static endpoints to keep
    the log focused on clinical and auth activity.
    """

    _SKIP_PREFIXES = ("/health", "/docs", "/redoc", "/openapi.json", "/favicon")

    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        for prefix in self._SKIP_PREFIXES:
            if path.startswith(prefix):
                return await call_next(request)

        response = await call_next(request)

        # Best-effort — never let audit failure break a request
        try:
            user_id: int | None = None
            auth_header = request.headers.get("Authorization", "")
            if auth_header.startswith("Bearer "):
                try:
                    payload = decode_token(auth_header[len("Bearer "):])
                    user_id = int(payload.get("sub", 0)) or None
                except (jwt.PyJWTError, Exception):
                    pass

            forwarded = request.headers.get("X-Forwarded-For")
            ip = (
                forwarded.split(",")[0].strip()
                if forwarded
                else (request.client.host if request.client else None)
            )

            raw_details: dict[str, Any] = {
                "query_params": dict(request.query_params),
            }
            log_audit(
                action="http_request",
                user_id=user_id,
                resource_type="http",
                ip_address=ip,
                user_agent=request.headers.get("User-Agent"),
                request_method=request.method,
                request_path=path,
                response_status=response.status_code,
                details=_scrub_phi(raw_details),
            )
        except Exception as exc:
            logger.error("Audit log write failed: %s", exc, exc_info=True)

        return response


class StructuredLoggingMiddleware(BaseHTTPMiddleware):
    """
    Attach structured request context to every log record during a request.

    Injects ``request_id``, ``method``, ``path``, and ``user_id`` into the
    Python logging context so that all log messages emitted during request
    processing automatically include these fields.

    After the response is sent, emits a single structured access log line
    suitable for ingestion by ELK / Datadog / CloudWatch.
    """

    async def dispatch(self, request: Request, call_next):
        request_id = getattr(request.state, "request_id", "unknown")
        method = request.method
        path = request.url.path

        user_id: str | None = None
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            try:
                payload = decode_token(auth_header[len("Bearer "):])
                user_id = str(payload.get("sub", "")) or None
            except Exception:
                pass

        extra = {
            "request_id": request_id,
            "method": method,
            "path": path,
            "user_id": user_id,
        }

        start = time.perf_counter()
        response = await call_next(request)
        elapsed_ms = (time.perf_counter() - start) * 1000

        logger.info(
            "http_access",
            extra={
                **extra,
                "status_code": response.status_code,
                "duration_ms": round(elapsed_ms, 1),
                "client_ip": request.client.host if request.client else None,
            },
        )

        return response
