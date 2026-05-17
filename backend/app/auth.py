"""
FastAPI dependency injection for JWT authentication and authorization.

Usage:
    from app.auth import get_current_user, require_role, require_permission, optional_auth

    @router.get("/resource")
    def endpoint(current_user: dict = Depends(get_current_user)):
        ...

    @router.delete("/admin-resource")
    def admin_endpoint(current_user: dict = Depends(require_role("admin"))):
        ...

    @router.get("/patients")
    def patients(current_user: dict = Depends(require_permission("patients", "read"))):
        ...
"""

from __future__ import annotations

import logging
from typing import Any

import jwt
from fastapi import Depends, HTTPException, Request, status

from app.db import run_in_db_executor
from app.services.auth_service import (
    check_permission,
    decode_token,
    get_user,
    validate_session,
)

logger = logging.getLogger(__name__)

_CREDENTIALS_EXCEPTION = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Could not validate credentials.",
    headers={"WWW-Authenticate": "Bearer"},
)


def _extract_token(request: Request) -> str | None:
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        return auth_header[len("Bearer ") :]
    return None


async def _resolve_user(request: Request) -> dict[str, Any] | None:
    """
    Core token-validation logic shared by get_current_user and optional_auth.

    Returns the populated user dict on success, or None if the token is absent
    or invalid.  Never raises — callers decide how to handle None.
    """
    token = _extract_token(request)
    if not token:
        return None

    try:
        payload = decode_token(token)
    except jwt.PyJWTError:
        return None

    if payload.get("type") != "access":
        return None

    try:
        user_id = int(payload["sub"])
    except (KeyError, ValueError, TypeError):
        return None

    session_id = payload.get("session_id")
    if not session_id:
        return None

    # Load user from DB.
    # ``get_user`` and ``validate_session`` use the synchronous
    # mysql-connector-python library.  Running them directly inside this
    # ``async def`` would block the asyncio event loop on every authenticated
    # request.  We offload both calls to the dedicated DB thread pool
    # (``run_in_db_executor``) so the event loop remains free during I/O.
    try:
        user = await run_in_db_executor(get_user, user_id)
    except Exception as exc:
        logger.error("_resolve_user DB error (get_user): %s", exc)
        raise HTTPException(
            status_code=503,
            detail="Service temporarily unavailable. Please try again.",
        )

    if not user or not user.get("is_active"):
        return None

    # Validate session is not revoked
    try:
        session = await run_in_db_executor(validate_session, session_id)
    except Exception as exc:
        logger.error("_resolve_user DB error (validate_session): %s", exc)
        raise HTTPException(
            status_code=503,
            detail="Service temporarily unavailable. Please try again.",
        )

    if not session:
        return None

    # Attach token payload extras to user dict for convenience
    user["session_id"] = session_id
    user["token_role"] = payload.get("role", user.get("role"))
    # Tenant handling: the DB-stored value is always authoritative.
    # JWT 'tenant_id' is ignored in the base _resolve_user to prevent
    # client-side elevation.
    if user.get("tenant_id") is None:
        # SECURITY: Reject users without a tenant assignment.
        # No fallback — a missing tenant_id means the account is misconfigured.
        logger.error(
            "TENANT ISOLATION VIOLATION: User %s has no tenant assignment. "
            "Access denied. An admin must assign a tenant_id to this user.",
            user_id,
        )
        return None

    # Org switcher: ActiveTenantMiddleware has already validated that the
    # X-Active-Tenant header (if present) is in the user's accessible-tenant
    # list. Swap it in here so every downstream dependency that calls
    # _resolve_user (incl. get_tenant_id and TenantGuardMiddleware) sees
    # the chosen tenant. The validated value lives on request.state.
    active_override = getattr(request.state, "active_tenant_id", None)
    if active_override:
        user["tenant_id"] = active_override
    return user


async def get_current_user(request: Request) -> dict[str, Any]:
    """
    FastAPI dependency that extracts and validates the Bearer JWT token.

    Steps:
    1. Extract token from Authorization header.
    2. Decode and verify JWT signature + expiry.
    3. Load user from DB, verify is_active.
    4. Validate session is not revoked.
    5. Return user dict.

    Raises HTTP 401 on any failure.
    """
    user = await _resolve_user(request)
    if user is None:
        raise _CREDENTIALS_EXCEPTION
    return user


async def optional_auth(request: Request) -> dict[str, Any] | None:
    """
    Like get_current_user but returns None instead of raising 401.
    Use for endpoints that behave differently when authenticated.
    """
    return await _resolve_user(request)


def get_tenant_id(current_user: dict = Depends(get_current_user)) -> str:
    """
    FastAPI dependency — extract tenant_id from the authenticated user record.

    The user record is loaded from the database using the JWT ``sub`` claim, so
    the tenant_id is always the server-side value assigned by an administrator.
    Clients cannot influence this value by sending a different tenant_id in a
    query parameter or request body.

    Returns the string representation of tenant_id.

    Raises HTTP 403 if the authenticated user has no tenant assignment —
    never falls back to a default to prevent cross-tenant data leaks.
    """
    tid = current_user.get("tenant_id")
    if tid is None:
        # SECURITY: Never fall back to a default tenant.
        # A missing tenant_id means the user record is misconfigured.
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied. No tenant assignment found for this user. Contact your administrator.",
        )
    return str(tid)


def require_role(*roles: str):
    """
    Returns a FastAPI dependency that enforces the user has one of the given roles.

    Usage:
        Depends(require_role("admin", "manager"))
    """

    async def _check(current_user: dict = Depends(get_current_user)) -> dict[str, Any]:
        user_role = current_user.get("role", "")
        if user_role not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied. Insufficient privileges.",
            )
        return current_user

    return _check


def require_permission(resource: str, action: str):
    """
    Returns a FastAPI dependency that checks a specific resource+action permission.

    Usage:
        Depends(require_permission("patients", "write"))
    """

    async def _check(current_user: dict = Depends(get_current_user)) -> dict[str, Any]:
        user_id = current_user.get("id")
        if not user_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="Access denied."
            )
        try:
            allowed = check_permission(user_id, resource, action)
        except Exception as exc:
            logger.error("Permission check error: %s", exc)
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="Access denied."
            )
        if not allowed:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied. Insufficient privileges.",
            )
        return current_user

    return _check
