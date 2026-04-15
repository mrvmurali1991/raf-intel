"""
Authentication router.

Public endpoints (no auth required):
    POST /api/auth/login
    POST /api/auth/forgot-password
    POST /api/auth/reset-password

Authenticated endpoints:
    POST /api/auth/logout
    POST /api/auth/refresh
    GET  /api/auth/me
    PUT  /api/auth/me
    PUT  /api/auth/change-password
    GET  /api/auth/sessions
    DELETE /api/auth/sessions/{session_id}

Admin / manager endpoints:
    GET  /api/auth/users
    POST /api/auth/users
    GET  /api/auth/users/{id}
    PUT  /api/auth/users/{id}
    DELETE /api/auth/users/{id}
    GET  /api/auth/users/{id}/permissions
    PUT  /api/auth/users/{id}/permissions
    GET  /api/auth/audit-log
"""
# Removed: from __future__ import annotations (breaks FastAPI schema generation)

import logging
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, EmailStr, Field, field_validator

from app.auth import get_current_user, get_tenant_id, require_role
from app.config import settings
from app.db import raf_cursor
from app.rate_limit import limiter
from app.services.auth_service import (
    authenticate_user,
    change_password,
    complete_mfa_login,
    create_user,
    deactivate_user,
    disable_mfa,
    enable_mfa,
    generate_password_reset_token,
    get_user,
    get_user_permissions,
    list_sessions,
    list_users,
    log_audit,
    query_audit_log,
    refresh_access_token,
    reset_password,
    revoke_all_sessions,
    revoke_session,
    set_user_permissions,
    update_user,
    verify_and_activate_mfa,
    validate_password_strength,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/auth", tags=["auth"])


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class RefreshRequest(BaseModel):
    refresh_token: str


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str

    @field_validator("new_password")
    @classmethod
    def password_strength(cls, v: str) -> str:
        # Full HIPAA complexity is enforced inside reset_password() in auth_service.
        # A lightweight pre-check here surfaces errors early via Pydantic (422 response).
        from app.services.auth_service import validate_password_strength as _vps

        valid, err = _vps(v)
        if not valid:
            raise ValueError(err)
        return v


class ChangePasswordRequest(BaseModel):
    old_password: str
    new_password: str

    @field_validator("new_password")
    @classmethod
    def password_strength(cls, v: str) -> str:
        from app.services.auth_service import validate_password_strength as _vps

        valid, err = _vps(v)
        if not valid:
            raise ValueError(err)
        return v


class UpdateProfileRequest(BaseModel):
    full_name: str | None = None
    avatar_url: str | None = None


class CreateUserRequest(BaseModel):
    email: EmailStr
    password: str
    full_name: str | None = None
    role: str = "viewer"
    tenant_id: int | None = None

    @field_validator("password")
    @classmethod
    def password_strength(cls, v: str) -> str:
        from app.services.auth_service import validate_password_strength as _vps

        valid, err = _vps(v)
        if not valid:
            raise ValueError(err)
        return v

    @field_validator("role")
    @classmethod
    def valid_role(cls, v: str) -> str:
        allowed = {"admin", "manager", "auditor", "viewer"}
        if v not in allowed:
            raise ValueError(f"Role must be one of: {', '.join(sorted(allowed))}")
        return v


class UpdateUserRequest(BaseModel):
    full_name: str | None = None
    role: str | None = None
    avatar_url: str | None = None
    tenant_id: int | None = None

    @field_validator("role")
    @classmethod
    def valid_role(cls, v: str | None) -> str | None:
        if v is not None:
            allowed = {"admin", "manager", "auditor", "viewer"}
            if v not in allowed:
                raise ValueError(f"Role must be one of: {', '.join(sorted(allowed))}")
        return v


class PermissionItem(BaseModel):
    resource: str
    action: str
    granted: bool = True


class SetPermissionsRequest(BaseModel):
    permissions: list[PermissionItem]


class MFAVerifyRequest(BaseModel):
    """Body for POST /mfa/verify — complete login after password step returned mfa_required."""

    mfa_token: str
    code: str


class MFAActivateRequest(BaseModel):
    """Body for POST /mfa/activate — confirm TOTP enrolment."""

    code: str


class MFADisableRequest(BaseModel):
    """Body for POST /mfa/disable — requires current password as confirmation."""

    password: str


def _get_client_ip(request: Request) -> str | None:
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    if request.client:
        return request.client.host
    return None


_COOKIE_MAX_AGE = 86400 * 7  # 7 days

_SENSITIVE_USER_FIELDS = frozenset({
    "password_hash",
    "mfa_secret",
    "mfa_recovery_codes",
    "reset_token",
    "reset_token_expires_at",
})


def _serialize_row(row: dict[str, Any] | None) -> dict[str, Any] | None:
    """Convert datetime objects to ISO strings for JSON serialisation."""
    if not row:
        return row
    result = {}
    for k, v in row.items():
        if isinstance(v, datetime):
            result[k] = v.isoformat()
        else:
            result[k] = v
    return result


def _safe_user(row: dict[str, Any] | None) -> dict[str, Any] | None:
    """Serialize a user row, stripping sensitive fields."""
    if not row:
        return row
    return _serialize_row({k: v for k, v in row.items() if k not in _SENSITIVE_USER_FIELDS})


# ---------------------------------------------------------------------------
# Public endpoints
# ---------------------------------------------------------------------------


@router.post("/login", summary="Login with email and password")
@limiter.limit("5/minute")
def login(request: Request, body: LoginRequest) -> dict[str, Any]:
    """
    Authenticate with email + password.
    Returns access_token, refresh_token, and user info on success.
    """
    ip = _get_client_ip(request)
    ua = request.headers.get("User-Agent", "")
    try:
        result = authenticate_user(
            email=body.email,
            password=body.password,
            ip_address=ip,
            user_agent=ua,
        )
    except ValueError as exc:
        log_audit(
            action="login_failed",
            resource_type="auth",
            ip_address=ip,
            user_agent=ua,
            request_method="POST",
            request_path="/api/auth/login",
            response_status=401,
            details={"email": body.email, "reason": str(exc)},
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password"
        )

    log_audit(
        action="login_success",
        user_id=result["user"]["id"],
        resource_type="auth",
        ip_address=ip,
        user_agent=ua,
        request_method="POST",
        request_path="/api/auth/login",
        response_status=200,
    )
    # Strip refresh_token from body — it belongs only in the httpOnly cookie.
    refresh_token = result.pop("refresh_token", None)
    resp = JSONResponse(content=result)
    if refresh_token:
        secure = settings.app_env != "development"
        resp.set_cookie(
            key="raf_refresh_token",
            value=refresh_token,
            httponly=True,
            secure=secure,
            samesite="lax",
            max_age=_COOKIE_MAX_AGE,  # 7 days
            path="/",
        )
    return resp


@router.post("/forgot-password", summary="Request a password reset token")
@limiter.limit("3/minute")
def forgot_password(request: Request, body: ForgotPasswordRequest) -> dict[str, Any]:
    """
    Trigger a password reset flow.

    The reset token is NEVER returned in the API response.  It is delivered
    out-of-band via the email service (see ``email_service.send_password_reset``).
    The response is intentionally identical whether or not the email address
    exists so that account enumeration is not possible.
    """
    _generic_response: dict[str, Any] = {
        "message": "If an account with that email exists, a password reset link has been sent."
    }
    try:
        token = generate_password_reset_token(body.email)
    except ValueError as exc:
        # Email not found – log silently and return generic response.
        logger.info("forgot-password: no account for supplied address (%s)", exc)
        return _generic_response

    # Log the full reset link in development so devs can test without SMTP.
    if settings.app_env == "development":
        reset_link = f"{settings.frontend_url}/login?reset_token={token}"
        logger.warning(
            "DEV MODE – password reset link for %s: %s  "
            "(this log line must never appear in production)",
            body.email,
            reset_link,
        )

    return _generic_response


@router.post("/reset-password", summary="Reset password using a token")
@limiter.limit("5/minute")
def reset_password_endpoint(
    request: Request, body: ResetPasswordRequest
) -> dict[str, Any]:
    try:
        reset_password(body.token, body.new_password)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    return {
        "message": "Password reset successfully. Please log in with your new password."
    }


# ---------------------------------------------------------------------------
# Token refresh (with rotation)
# ---------------------------------------------------------------------------


@router.post("/refresh", summary="Refresh access token (returns new refresh token too)")
def refresh_token_endpoint(
    request: Request,
    body: RefreshRequest | None = None,
) -> dict[str, Any]:
    """Issue a new access token and a rotated refresh token.

    The refresh token is read from the httpOnly ``raf_refresh_token`` cookie.
    The new refresh token is set as a new httpOnly cookie.
    The client MUST NOT store refresh tokens in JavaScript-accessible storage.
    """
    # Prefer explicit body token (API clients/tests), fall back to cookie
    # token (browser clients).
    rt = body.refresh_token if body and body.refresh_token else None
    if not rt:
        rt = request.cookies.get("raf_refresh_token")
    if not rt:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="No refresh token"
        )
    try:
        result = refresh_access_token(rt)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc))
    # Rotate: set new refresh token as httpOnly cookie
    new_rt = result.get("refresh_token")
    resp = JSONResponse(content=result)
    if new_rt:
        secure = settings.app_env != "development"
        resp.set_cookie(
            key="raf_refresh_token",
            value=new_rt,
            httponly=True,
            secure=secure,
            samesite="lax",
            max_age=_COOKIE_MAX_AGE,
            path="/",
        )
    return resp


# ---------------------------------------------------------------------------
# MFA endpoints
# ---------------------------------------------------------------------------


@router.post("/mfa/verify", summary="Complete MFA login")
def verify_mfa(body: MFAVerifyRequest, request: Request) -> JSONResponse:
    """After /login returns mfa_required=true, submit the mfa_token + TOTP code here.

    On success returns access_token and user — the refresh_token is set as
    an httpOnly cookie (never exposed to JavaScript).
    """
    ip = _get_client_ip(request)
    ua = request.headers.get("User-Agent", "")
    try:
        result = complete_mfa_login(
            mfa_token=body.mfa_token,
            totp_code=body.code,
            ip_address=ip,
            user_agent=ua,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc))
    refresh_token = result.pop("refresh_token", None)
    resp = JSONResponse(content=result)
    if refresh_token:
        secure = settings.app_env != "development"
        resp.set_cookie(
            key="raf_refresh_token",
            value=refresh_token,
            httponly=True,
            secure=secure,
            samesite="lax",
            max_age=_COOKIE_MAX_AGE,
            path="/",
        )
    return resp


@router.post(
    "/mfa/setup", summary="Begin MFA enrolment — generates QR code and recovery codes"
)
def setup_mfa(current_user: dict = Depends(get_current_user)) -> dict[str, Any]:
    """Generate a TOTP secret and QR code PNG (base64).

    The secret is stored but MFA is NOT active until the user calls
    POST /mfa/activate with a valid TOTP code to confirm enrolment.
    """
    try:
        return enable_mfa(current_user["id"])
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.post("/mfa/activate", summary="Confirm TOTP code and activate MFA")
def activate_mfa(
    body: MFAActivateRequest,
    current_user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    """Verify the TOTP code from the authenticator app and enable MFA.

    Must be called after /mfa/setup before MFA takes effect at login.
    """
    if not verify_and_activate_mfa(current_user["id"], body.code):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid TOTP code. Please try again.",
        )
    log_audit(
        action="mfa_activated",
        user_id=current_user["id"],
        resource_type="auth",
        request_method="POST",
        request_path="/api/auth/mfa/activate",
        response_status=200,
    )
    return {"message": "MFA has been activated successfully."}


@router.post("/mfa/disable", summary="Disable MFA (requires current password)")
def disable_mfa_endpoint(
    body: MFADisableRequest,
    current_user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    """Disable MFA for the current user.

    Requires the user's current password as confirmation to prevent
    an attacker with a stolen access token from disabling MFA.
    """
    from app.services.auth_service import verify_password

    with raf_cursor() as cur:
        cur.execute(
            "SELECT password_hash FROM users WHERE id = %s", (current_user["id"],)
        )
        row = cur.fetchone()

    if not row or not verify_password(body.password, row["password_hash"]):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Incorrect password.",
        )

    disable_mfa(current_user["id"])
    log_audit(
        action="mfa_disabled",
        user_id=current_user["id"],
        resource_type="auth",
        request_method="POST",
        request_path="/api/auth/mfa/disable",
        response_status=200,
    )
    return {"message": "MFA has been disabled."}


# ---------------------------------------------------------------------------
# Authenticated user endpoints
# ---------------------------------------------------------------------------


@router.post("/logout", summary="Logout and revoke current session")
def logout(
    request: Request,
    response: Response,
    current_user: dict = Depends(get_current_user),
) -> JSONResponse:
    session_id = current_user.get("session_id")
    if session_id:
        revoke_session(session_id)
    log_audit(
        action="logout",
        user_id=current_user["id"],
        resource_type="auth",
        ip_address=_get_client_ip(request),
        request_method="POST",
        request_path="/api/auth/logout",
        response_status=200,
    )
    # Clear the httpOnly refresh token cookie
    response.delete_cookie(
        key="raf_refresh_token",
        path="/",
    )
    return JSONResponse(content={"message": "Logged out successfully."})


@router.get("/me", summary="Get current user profile")
def get_me(current_user: dict = Depends(get_current_user)) -> dict[str, Any]:
    user = get_user(current_user["id"])
    if not user:
        raise HTTPException(status_code=404, detail="User not found.")
    return _serialize_row(
        {
            "id": user["id"],
            "email": user["email"],
            "full_name": user["full_name"],
            "role": user["role"],
            "tenant_id": user["tenant_id"],
            "avatar_url": user["avatar_url"],
            "last_login_at": user["last_login_at"],
            "created_at": user["created_at"],
        }
    )


@router.put("/me", summary="Update own profile (name, avatar)")
def update_me(
    body: UpdateProfileRequest,
    current_user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    updated = update_user(
        user_id=current_user["id"],
        full_name=body.full_name,
        avatar_url=body.avatar_url,
    )
    if not updated:
        raise HTTPException(status_code=404, detail="User not found.")
    return _serialize_row(
        {
            "id": updated["id"],
            "email": updated["email"],
            "full_name": updated["full_name"],
            "role": updated["role"],
            "avatar_url": updated["avatar_url"],
            "updated_at": updated["updated_at"],
        }
    )


@router.put(
    "/change-password", summary="Change own password (requires current password)"
)
def change_own_password(
    body: ChangePasswordRequest,
    current_user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    try:
        change_password(current_user["id"], body.old_password, body.new_password)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    return {
        "message": "Password changed successfully. All other sessions have been revoked."
    }


@router.get("/sessions", summary="List own active sessions")
def get_sessions(
    current_user: dict = Depends(get_current_user),
) -> list[dict[str, Any]]:
    sessions = list_sessions(current_user["id"])
    return [_serialize_row(s) for s in sessions]


@router.delete("/sessions/{session_id}", summary="Revoke a specific session")
def delete_session(
    session_id: str,
    current_user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    # Only allow revoking own sessions (admins could revoke others via user management)
    sessions = list_sessions(current_user["id"])
    own_ids = {s["session_id"] for s in sessions}
    # Also allow revoking current session
    own_ids.add(current_user.get("session_id", ""))
    if session_id not in own_ids:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cannot revoke another user's session.",
        )
    revoke_session(session_id)
    return {"message": "Session revoked."}


# ---------------------------------------------------------------------------
# Admin – User management
# ---------------------------------------------------------------------------


@router.get("/users", summary="List all users (admin/manager only)")
def admin_list_users(
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    role: str | None = Query(None),
    is_active: bool | None = Query(None),
    current_user: dict = Depends(require_role("admin", "manager")),
    tenant_id: str = Depends(get_tenant_id),
) -> dict[str, Any]:
    users = list_users(limit=limit, offset=offset, role=role, is_active=is_active, tenant_id=tenant_id)
    serialized = [_safe_user(u) for u in users]
    return {"count": len(serialized), "users": serialized}


@router.post("/users", summary="Create a new user (admin only)", status_code=201)
def admin_create_user(
    body: CreateUserRequest,
    current_user: dict = Depends(require_role("admin")),
) -> dict[str, Any]:
    try:
        user = create_user(
            email=body.email,
            password=body.password,
            full_name=body.full_name,
            role=body.role,
            tenant_id=current_user["tenant_id"],
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    log_audit(
        action="user_created",
        user_id=current_user["id"],
        resource_type="user",
        resource_id=str(user["id"]),
        details={"email": body.email, "role": body.role},
    )
    return _safe_user(user)


@router.get("/users/{user_id}", summary="Get user detail")
def admin_get_user(
    user_id: int,
    current_user: dict = Depends(require_role("admin", "manager")),
) -> dict[str, Any]:
    user = get_user(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found.")
    return _safe_user(user)


@router.put("/users/{user_id}", summary="Update a user (admin only)")
def admin_update_user(
    user_id: int,
    body: UpdateUserRequest,
    current_user: dict = Depends(require_role("admin")),
) -> dict[str, Any]:
    user = get_user(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found.")
    updated = update_user(
        user_id=user_id,
        full_name=body.full_name,
        role=body.role,
        avatar_url=body.avatar_url,
        tenant_id=current_user["tenant_id"],
    )
    log_audit(
        action="user_updated",
        user_id=current_user["id"],
        resource_type="user",
        resource_id=str(user_id),
        details=body.model_dump(exclude_none=True),
    )
    return _safe_user(updated)


@router.delete("/users/{user_id}", summary="Deactivate a user (admin only)")
def admin_deactivate_user(
    user_id: int,
    current_user: dict = Depends(require_role("admin")),
) -> dict[str, Any]:
    if user_id == current_user["id"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot deactivate your own account.",
        )
    user = get_user(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found.")
    deactivated = deactivate_user(user_id)
    log_audit(
        action="user_deactivated",
        user_id=current_user["id"],
        resource_type="user",
        resource_id=str(user_id),
    )
    return _safe_user(deactivated)


@router.get(
    "/users/{user_id}/permissions", summary="Get effective permissions for a user"
)
def admin_get_permissions(
    user_id: int,
    current_user: dict = Depends(require_role("admin", "manager")),
) -> dict[str, Any]:
    user = get_user(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found.")
    perms = get_user_permissions(user_id)
    return {"user_id": user_id, "role": user["role"], "permissions": perms}


@router.put(
    "/users/{user_id}/permissions", summary="Set user permission overrides (admin only)"
)
def admin_set_permissions(
    user_id: int,
    body: SetPermissionsRequest,
    current_user: dict = Depends(require_role("admin")),
) -> dict[str, Any]:
    user = get_user(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found.")
    perm_dicts = [p.model_dump() for p in body.permissions]
    set_user_permissions(user_id, perm_dicts)
    log_audit(
        action="permissions_updated",
        user_id=current_user["id"],
        resource_type="user",
        resource_id=str(user_id),
        details={"permission_count": len(perm_dicts)},
    )
    perms = get_user_permissions(user_id)
    return {"user_id": user_id, "role": user["role"], "permissions": perms}


# ---------------------------------------------------------------------------
# Audit log (admin/auditor only)
# ---------------------------------------------------------------------------


@router.get("/audit-log", summary="Query the audit log (admin/auditor only)")
def get_audit_log(
    user_id: int | None = Query(None, description="Filter by user ID"),
    action: str | None = Query(None, description="Filter by action"),
    resource_type: str | None = Query(None, description="Filter by resource type"),
    patient_id: int | None = Query(None, description="Filter by patient ID"),
    start_date: str | None = Query(None, description="ISO date start, e.g. 2025-01-01"),
    end_date: str | None = Query(None, description="ISO date end, e.g. 2025-12-31"),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    current_user: dict = Depends(require_role("admin", "auditor")),
    tenant_id: str = Depends(get_tenant_id),
) -> dict[str, Any]:
    try:
        start_dt = datetime.fromisoformat(start_date) if start_date else None
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid start_date format: {start_date!r}. Use ISO 8601, e.g. 2025-01-01.",
        )
    try:
        end_dt = datetime.fromisoformat(end_date) if end_date else None
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid end_date format: {end_date!r}. Use ISO 8601, e.g. 2025-12-31.",
        )
    rows = query_audit_log(
        user_id=user_id,
        action=action,
        resource_type=resource_type,
        patient_id=patient_id,
        start_date=start_dt,
        end_date=end_dt,
        limit=limit,
        offset=offset,
        tenant_id=tenant_id,
    )
    return {
        "count": len(rows),
        "entries": [_serialize_row(r) for r in rows],
    }


# ---------------------------------------------------------------------------
# Tenant switcher (super-admin only)
# ---------------------------------------------------------------------------


class SwitchTenantRequest(BaseModel):
    tenant_id: str


@router.get("/tenants", summary="List all tenants (admin only)")
def list_tenants(
    current_user: dict = Depends(require_role("admin")),
    tenant_id: str = Depends(get_tenant_id),
) -> dict[str, Any]:
    """Return tenant metadata for the caller's own tenant only."""
    with raf_cursor() as cur:
        cur.execute(
            """
            SELECT
                p.tenant_id,
                COALESCE(e.display_name, CONCAT('Tenant ', p.tenant_id)) AS name,
                COUNT(DISTINCT p.id) AS patient_count,
                COUNT(DISTINCT u.id) AS user_count
            FROM patients p
            LEFT JOIN emr_connections e ON e.tenant_id = p.tenant_id AND e.is_active = 1
            LEFT JOIN users u ON u.tenant_id = p.tenant_id AND u.is_active = 1
            WHERE p.tenant_id = %s
            GROUP BY p.tenant_id, e.display_name
            ORDER BY p.tenant_id
            """,
            (tenant_id,),
        )
        rows = cur.fetchall()

    tenants = []
    for row in rows:
        tenants.append(
            {
                "tenant_id": str(row["tenant_id"]),
                "name": row["name"],
                "patient_count": row["patient_count"],
                "user_count": row["user_count"],
            }
        )

    # If no patients exist yet for this tenant, still return the tenant entry via users
    if not tenants:
        with raf_cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) AS user_count FROM users WHERE tenant_id = %s AND is_active = 1",
                (tenant_id,),
            )
            row = cur.fetchone()
            tenants.append(
                {
                    "tenant_id": str(tenant_id),
                    "name": f"Tenant {tenant_id}",
                    "patient_count": 0,
                    "user_count": int((row or {}).get("user_count", 0)),
                }
            )

    return {
        "tenants": tenants,
        "current_tenant_id": str(tenant_id),
    }


@router.post("/switch-tenant", summary="Switch active tenant (admin only)")
def switch_tenant(
    body: SwitchTenantRequest,
    current_user: dict = Depends(require_role("admin")),
) -> dict[str, Any]:
    """
    Issue a new access token scoped to a different tenant.
    Only admins can switch tenants. The user record stays on their
    original tenant — only the JWT tenant_id claim changes.
    """
    target_tid = body.tenant_id

    # Verify target tenant exists
    with raf_cursor() as cur:
        cur.execute(
            "SELECT COUNT(*) AS cnt FROM users WHERE tenant_id = %s AND is_active = 1",
            (target_tid,),
        )
        if cur.fetchone()["cnt"] == 0:
            # Also check patients table
            cur.execute(
                "SELECT COUNT(*) AS cnt FROM patients WHERE tenant_id = %s",
                (target_tid,),
            )
            if cur.fetchone()["cnt"] == 0:
                raise HTTPException(
                    status_code=404, detail=f"Tenant {target_tid} not found"
                )

    from app.services.auth_service import create_access_token

    # Issue new token with switched tenant
    new_token = create_access_token(
        user_id=current_user["id"],
        email=current_user["email"],
        role=current_user["role"],
        tenant_id=target_tid,
        session_id=current_user.get("session_id", ""),
    )

    log_audit(
        user_id=current_user["id"],
        action="switch_tenant",
        resource_type="tenant",
        resource_id=target_tid,
        details=f"Switched from tenant {current_user.get('tenant_id')} to {target_tid}",
    )

    return {
        "access_token": new_token,
        "tenant_id": target_tid,
        "message": f"Switched to tenant {target_tid}",
    }


# ---------------------------------------------------------------------------
# Break-glass emergency access
# ---------------------------------------------------------------------------


class BreakGlassRequest(BaseModel):
    reason: str = Field(..., min_length=10, description="Clinical justification for emergency access")


@router.post("/break-glass")
def api_break_glass(
    body: BreakGlassRequest,
    request: Request,
    current_user: dict = Depends(require_role("admin", "physician", "provider", "medical_director")),
):
    """Activate break-glass emergency access (physicians/admins only).

    Creates a time-limited (30 min) emergency session with full audit trail.
    """
    from app.services.break_glass import create_break_glass_session

    forwarded = request.headers.get("X-Forwarded-For")
    ip = (
        forwarded.split(",")[0].strip()
        if forwarded
        else (request.client.host if request.client else None)
    )
    try:
        session = create_break_glass_session(
            user_id=current_user["id"],
            tenant_id=current_user.get("tenant_id", "unknown"),
            reason=body.reason,
            role=current_user.get("role", ""),
            ip_address=ip,
        )
        return {"status": "ok", "break_glass_session": session}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
