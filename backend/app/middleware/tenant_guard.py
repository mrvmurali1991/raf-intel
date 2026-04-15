"""
Tenant Guard Middleware — enforces tenant isolation on all /api/ requests.

Every authenticated request to /api/* (except exempt paths) must carry a
valid tenant_id derived from the authenticated user's DB record.  The
tenant_id is stored in ``request.state.tenant_id`` for downstream use.

Requests without a valid tenant_id receive HTTP 403.

This middleware also provides cross-tenant leak detection: if a downstream
handler accidentally sets ``request.state._tenant_leak_detected``, the
middleware logs a CRITICAL security alert.
"""

from __future__ import annotations

import logging
import time

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

logger = logging.getLogger(__name__)

# Paths that are exempt from tenant enforcement
_EXEMPT_EXACT = {"/", "/health", "/api/health"}
_EXEMPT_PREFIXES = (
    "/api/auth/login",
    "/api/auth/register",
    "/api/auth/refresh",
    "/api/auth/forgot-password",
    "/api/health",
    "/health",
    "/docs",
    "/redoc",
    "/openapi.json",
)


def _is_exempt(path: str) -> bool:
    if path in _EXEMPT_EXACT:
        return True
    for prefix in _EXEMPT_PREFIXES:
        if path == prefix or path.startswith(prefix + "/") or path.startswith(prefix + "?"):
            return True
    # Non-API paths (static assets, etc.) are exempt
    if not path.startswith("/api/"):
        return True
    return False


class TenantGuardMiddleware(BaseHTTPMiddleware):
    """
    Intercepts all /api/ requests and enforces tenant_id presence.

    After the response is generated, checks for cross-tenant leak indicators
    and logs CRITICAL alerts if detected.
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        path = request.url.path

        if _is_exempt(path):
            return await call_next(request)

        # Resolve tenant_id from the authenticated user.
        # We import here to avoid circular imports at module load time.
        from app.auth import _resolve_user

        try:
            user = await _resolve_user(request)
        except Exception:
            user = None

        if user is None:
            # Let downstream auth dependencies handle 401
            return await call_next(request)

        tenant_id = user.get("tenant_id")
        if not tenant_id:
            logger.warning(
                "TENANT GUARD: Blocked request to %s — user %s has no tenant_id.",
                path,
                user.get("id", "unknown"),
            )
            return JSONResponse(
                status_code=403,
                content={
                    "detail": "Access denied. No tenant assignment found for this user."
                },
            )

        # Store tenant_id in request state for downstream handlers
        request.state.tenant_id = str(tenant_id)

        response = await call_next(request)

        # Cross-tenant leak detection
        leak_detected = getattr(request.state, "_tenant_leak_detected", None)
        if leak_detected:
            logger.critical(
                "CROSS-TENANT DATA LEAK DETECTED: user=%s tenant=%s "
                "accessed data belonging to tenant=%s on path=%s. "
                "Immediate investigation required.",
                user.get("id"),
                tenant_id,
                leak_detected,
                path,
            )

        return response
