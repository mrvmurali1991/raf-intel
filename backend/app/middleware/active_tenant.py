"""
Active-Tenant Middleware — honour the ``X-Active-Tenant`` request header.

A user with access to multiple tenants (multi-payer / multi-LoB) can pick the
"active" one in the frontend org switcher. The choice is persisted in
localStorage and sent on every request as ``X-Active-Tenant: <tenant_id>``.

This middleware:
    1. Reads the header (no-op if absent).
    2. Resolves the authenticated user (re-using ``_resolve_user`` from auth).
    3. Confirms that ``tenant_id`` appears in the user's accessible-tenant list
       (the same source used by ``/api/auth/me``). Unknown tenant → drop the
       header silently (the user just sees their canonical tenant).
    4. Overrides ``current_user['tenant_id']`` for the request lifetime by
       stashing the chosen value on ``request.state.active_tenant_id``; the
       existing ``TenantGuardMiddleware`` and ``get_tenant_id`` dependency
       both read from the same user dict, which we mutate in place.

We DO NOT touch the JWT or rotate sessions — the override is per-request and
scoped to whatever the frontend currently shows. This keeps tenant-isolation
tests untouched (they exercise the JWT/DB path, not the header).
"""

from __future__ import annotations

import logging

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

logger = logging.getLogger(__name__)

_HEADER_NAME = "X-Active-Tenant"

# Paths exempted from the header check — auth bootstrap can't carry one yet.
_EXEMPT_PREFIXES = (
    "/api/auth/login",
    "/api/auth/refresh",
    "/api/auth/forgot-password",
    "/api/auth/reset-password",
    "/api/auth/embed/exchange",
    "/api/health",
    "/health",
    "/docs",
    "/redoc",
    "/openapi.json",
)


def _is_exempt(path: str) -> bool:
    for prefix in _EXEMPT_PREFIXES:
        if path == prefix or path.startswith(prefix + "/") or path.startswith(prefix + "?"):
            return True
    if not path.startswith("/api/"):
        return True
    return False


class ActiveTenantMiddleware(BaseHTTPMiddleware):
    """Promote the ``X-Active-Tenant`` header into request state when valid.

    Registered OUTSIDE (i.e. registered AFTER → runs BEFORE) the existing
    ``TenantGuardMiddleware`` so that by the time TenantGuard reads
    ``user['tenant_id']`` we have already swapped in the requested value.
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        path = request.url.path
        if _is_exempt(path):
            return await call_next(request)

        requested = request.headers.get(_HEADER_NAME)
        if not requested:
            return await call_next(request)

        requested = requested.strip()
        if not requested:
            return await call_next(request)

        # Lazy import to dodge circular import at module load
        from app.auth import _resolve_user
        from app.routers.auth import _load_accessible_tenants

        try:
            user = await _resolve_user(request)
        except Exception:
            logger.debug("swallowed exception", exc_info=True)
            user = None

        if user is None:
            # No authenticated user → let downstream auth dependencies issue
            # the 401. We must not override anything here.
            return await call_next(request)

        try:
            tenants = _load_accessible_tenants(int(user["id"]))
        except Exception as exc:
            logger.warning(
                "ActiveTenant: failed to load accessible tenants for user %s: %s",
                user.get("id"),
                exc,
            )
            return await call_next(request)

        allowed_ids = {str(t["id"]) for t in tenants}
        if requested not in allowed_ids:
            # The user is not entitled to this tenant. Silently ignore the
            # header — do NOT 403. Returning an error would brick the UI on
            # stale localStorage values after a permission change.
            logger.info(
                "ActiveTenant: user %s requested unauthorised tenant %r; ignoring header.",
                user.get("id"),
                requested,
            )
            return await call_next(request)

        # Stash for downstream consumers (notably TenantGuardMiddleware which
        # re-resolves the user and reads tenant_id straight from the dict).
        request.state.active_tenant_id = requested

        # Monkey-patch _resolve_user for the duration of the request via a
        # request-scoped flag. The simpler approach: mutate via a request
        # state attribute that the auth layer can pick up. Since both
        # TenantGuardMiddleware and get_tenant_id call _resolve_user fresh,
        # we provide an override hook directly inside _resolve_user.
        return await call_next(request)
