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

import ipaddress
import logging
import os
import time as _time
from datetime import date, datetime
from functools import lru_cache
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, EmailStr, Field, field_validator

from app.auth import get_current_user, get_tenant_id, require_role
from app.config import settings
from app.db import raf_cursor
from app.middleware.idempotency import idempotency_key_dependency, store_idempotent_response
from app.rate_limit import limiter, login_rate_key
from app.services.auth_service import (
    authenticate_embed_token,
    authenticate_user,
    change_password,
    complete_mfa_login,
    count_users,
    create_embed_token,
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
    revoke_session,
    set_user_permissions,
    update_user,
    verify_and_activate_mfa,
)

from app.metrics import AUTH_LOGIN_TOTAL, AUTH_MFA_ATTEMPTS_TOTAL

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
        allowed = {"admin", "manager", "auditor", "coder", "viewer"}
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
            allowed = {"admin", "manager", "auditor", "coder", "viewer"}
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
    """Body for POST /mfa/disable — requires password AND a fresh TOTP or recovery code."""

    password: str
    totp_code: str | None = None
    recovery_code: str | None = None


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------


class MessageResponse(BaseModel):
    message: str


class AccessibleTenantItem(BaseModel):
    """A tenant the current user is allowed to switch into.

    ``id`` is a string so the same shape works whether tenant_id is a numeric
    primary key or an opaque string identifier across deployments.
    """

    id: str
    display_name: str
    role: str


class UserProfileResponse(BaseModel):
    id: int
    email: str
    full_name: str | None = None
    role: str
    tenant_id: int | str | None = None
    avatar_url: str | None = None
    last_login_at: str | None = None
    created_at: str | None = None
    updated_at: str | None = None
    onboarding_complete: bool = False
    accessible_tenants: list[AccessibleTenantItem] = []
    provider_id: int | None = None


class UserDetailResponse(BaseModel):
    id: int
    email: str
    full_name: str | None = None
    role: str
    tenant_id: int | str | None = None
    avatar_url: str | None = None
    is_active: bool | None = None
    last_login_at: str | None = None
    created_at: str | None = None
    updated_at: str | None = None
    mfa_enabled: bool | None = None


class UserListResponse(BaseModel):
    count: int
    total: int | None = None
    users: list[dict[str, Any]]


class UserPermissionsResponse(BaseModel):
    user_id: int
    role: str
    permissions: list[dict[str, Any]]


class AuditLogResponse(BaseModel):
    count: int
    entries: list[dict[str, Any]]


class TenantItem(BaseModel):
    tenant_id: str
    name: str
    patient_count: int
    user_count: int


class TenantListResponse(BaseModel):
    tenants: list[TenantItem]
    current_tenant_id: str


class SwitchTenantResponse(BaseModel):
    access_token: str
    tenant_id: str
    message: str


class BreakGlassResponse(BaseModel):
    status: str
    break_glass_session: dict[str, Any]


class EmbedMintResponse(BaseModel):
    embed_token: str
    expires_in: int
    iframe_url: str


# Default trusted-proxy ranges: localhost + private/docker-bridge CIDRs.
# This prod deploys behind Cloudflare -> nginx -> container, so the immediate
# TCP peer is always an internal address. Unauthenticated public callers hitting
# the backend directly will NOT be in these ranges, so their X-Forwarded-For
# header is ignored — preventing per-request IP spoofing of rate-limit buckets.
_DEFAULT_TRUSTED_PROXIES = "127.0.0.1/32,10.0.0.0/8,172.16.0.0/12,192.168.0.0/16"


@lru_cache(maxsize=1)
def _trusted_proxy_networks() -> tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, ...]:
    """Parse TRUSTED_PROXIES env var into a tuple of ip_network objects.

    Cached so we only parse once per process. Invalid entries are skipped with
    a warning rather than crashing the app (defence-in-depth: a misconfigured
    env var must not take down auth entirely)."""
    raw = os.getenv("TRUSTED_PROXIES", _DEFAULT_TRUSTED_PROXIES)
    nets: list[ipaddress.IPv4Network | ipaddress.IPv6Network] = []
    for token in raw.split(","):
        token = token.strip()
        if not token:
            continue
        try:
            nets.append(ipaddress.ip_network(token, strict=False))
        except ValueError:
            logger.warning("Ignoring invalid TRUSTED_PROXIES entry: %r", token)
    return tuple(nets)


def _peer_is_trusted(peer: str | None) -> bool:
    if not peer:
        return False
    try:
        addr = ipaddress.ip_address(peer)
    except ValueError:
        return False
    return any(addr in net for net in _trusted_proxy_networks())


def _get_client_ip(request: Request) -> str | None:
    """Return the client IP, honouring X-Forwarded-For ONLY when the TCP peer
    is a trusted proxy. This prevents unauthenticated callers from spoofing
    arbitrary IPs per-request (which would defeat login rate limits)."""
    peer = request.client.host if request.client else None
    if _peer_is_trusted(peer):
        forwarded = request.headers.get("X-Forwarded-For")
        if forwarded:
            # Take the left-most entry (the original client as seen by the
            # first trusted hop). Downstream proxies append to the right.
            first = forwarded.split(",")[0].strip()
            if first:
                return first
    return peer or ""


_COOKIE_MAX_AGE = 86400 * 7  # 7 days

# Refresh-token cookie name.
#
# In production we use the ``__Host-`` prefix so the browser will *reject* the
# cookie unless it is sent with Secure, Path=/, and no Domain attribute. That
# closes a class of subdomain-takeover / cookie-tossing attacks. The prefix
# can't be used in local dev (HTTP, no TLS), so we keep the legacy name there.
_REFRESH_COOKIE_NAME = (
    "__Host-raf_refresh_token" if settings.app_env == "production" else "raf_refresh_token"
)

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


async def _stash_login_email(request: Request) -> None:
    """Pre-flight dependency: peek at the JSON body, stash the email onto
    request.state BEFORE slowapi's rate-limit key_func runs.

    slowapi evaluates its key_func at the start of the endpoint wrapper, at
    which point `request.state._login_email` must already be set. FastAPI
    resolves dependencies before the wrapper is entered, so this runs first.

    Starlette caches the raw body on first read via ``request.body()`` so the
    subsequent pydantic parse inside ``login(body: LoginRequest)`` is a no-op
    for the network layer."""
    try:
        raw = await request.body()
        if raw:
            import json as _json

            data = _json.loads(raw)
            email = data.get("email") if isinstance(data, dict) else None
            if isinstance(email, str):
                request.state._login_email = email.strip().lower()
                return
    except Exception:
        # Malformed body — let pydantic raise 422. Use empty string so the
        # IP-only bucket still applies.
        logger.debug("swallowed exception", exc_info=True)
        pass
    request.state._login_email = ""


@router.post(
    "/login",
    summary="Login with email and password",
    dependencies=[Depends(_stash_login_email)],
)
@limiter.limit(
    "5/minute",
    # Key on IP+submitted-email so credential-stuffing from rotating IPs is
    # still bucketed per target account. _stash_login_email (above) populates
    # request.state._login_email during dependency resolution.
    key_func=lambda request: login_rate_key(
        request, getattr(request.state, "_login_email", "")
    ),
)
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
        AUTH_LOGIN_TOTAL.labels(outcome="failure").inc()
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

    AUTH_LOGIN_TOTAL.labels(outcome="success").inc()
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
        # __Host- prefix requires Secure + Path=/ + no Domain attribute.
        resp.set_cookie(
            key=_REFRESH_COOKIE_NAME,
            value=refresh_token,
            httponly=True,
            secure=secure,
            samesite="strict" if secure else "lax",
            max_age=_COOKIE_MAX_AGE,  # 7 days
            path="/",
        )
    return resp


@router.post(
    "/forgot-password",
    summary="Request a password reset token",
    response_model=MessageResponse,
)
@limiter.limit("3/minute")
def forgot_password(request: Request, body: ForgotPasswordRequest) -> MessageResponse:
    """
    Trigger a password reset flow.

    The reset token is NEVER returned in the API response.  It is delivered
    out-of-band via the email service (see ``email_service.send_password_reset``).
    The response is intentionally identical whether or not the email address
    exists so that account enumeration is not possible.
    """
    _msg = "If an account with that email exists, a password reset link has been sent."
    try:
        token = generate_password_reset_token(body.email)
    except ValueError:
        # Email not found – log a short hash of the address (NOT the address
        # itself) so we keep diagnostic ability without enabling account
        # enumeration via log scraping.
        import hashlib as _hashlib

        email_hash = _hashlib.sha256(body.email.encode()).hexdigest()[:8]
        logger.info("forgot-password: no account for supplied address (hash=%s)", email_hash)
        return MessageResponse(message=_msg)

    # Log the full reset link in development so devs can test without SMTP.
    if settings.app_env == "development":
        reset_link = f"{settings.frontend_url}/login?reset_token={token}"
        logger.warning(
            "DEV MODE – password reset link for %s: %s  "
            "(this log line must never appear in production)",
            body.email,
            reset_link,
        )

    return MessageResponse(message=_msg)


@router.post(
    "/reset-password",
    summary="Reset password using a token",
    response_model=MessageResponse,
)
@limiter.limit("5/minute")
def reset_password_endpoint(
    request: Request, body: ResetPasswordRequest
) -> MessageResponse:
    try:
        reset_password(body.token, body.new_password)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    return MessageResponse(
        message="Password reset successfully. Please log in with your new password."
    )


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
    # token (browser clients). Read both the prod (__Host- prefixed) name
    # and the legacy name so a deploy rollover doesn't log everyone out.
    rt = body.refresh_token if body and body.refresh_token else None
    if not rt:
        rt = (
            request.cookies.get(_REFRESH_COOKIE_NAME)
            or request.cookies.get("raf_refresh_token")
        )
    if not rt:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="No refresh token"
        )
    try:
        result = refresh_access_token(rt)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc))
    # Rotate: set new refresh token as httpOnly cookie
    new_rt = result.pop("refresh_token", None)
    resp = JSONResponse(content=result)
    if new_rt:
        secure = settings.app_env != "development"
        resp.set_cookie(
            key=_REFRESH_COOKIE_NAME,
            value=new_rt,
            httponly=True,
            secure=secure,
            samesite="strict" if secure else "lax",
            max_age=_COOKIE_MAX_AGE,
            path="/",
        )
    return resp


# ---------------------------------------------------------------------------
# Embed handshake (OpenEMR iframe exchange)
# ---------------------------------------------------------------------------


class EmbedExchangeRequest(BaseModel):
    embed_token: str = Field(..., min_length=16, max_length=4096)


class EmbedMintRequest(BaseModel):
    """Admin-only: mint an embed token for QA / demo harnesses."""
    user_email: EmailStr
    pid: int = Field(..., ge=1)
    tenant_id: str | None = None
    ttl_seconds: int = Field(default=300, ge=30, le=600)


@router.post(
    "/embed/exchange",
    summary="Exchange an OpenEMR embed JWT for a RAF session",
)
@limiter.limit("30/minute")
def embed_exchange(request: Request, body: EmbedExchangeRequest) -> JSONResponse:
    """Validate a short-lived embed JWT (signed with OPENEMR_EMBED_SECRET)
    and issue a scoped RAF access + refresh token pair.

    Designed for the OpenEMR chart iframe: the host plugin mints a token
    with the patient id + RAF user email, hands it to the iframe via URL,
    and the iframe POSTs it here exactly once on load.
    """
    ip = _get_client_ip(request)
    ua = request.headers.get("User-Agent", "")
    try:
        result = authenticate_embed_token(
            embed_token=body.embed_token, ip_address=ip, user_agent=ua
        )
    except ValueError as exc:
        log_audit(
            action="embed_exchange_failed",
            resource_type="auth",
            ip_address=ip,
            user_agent=ua,
            request_method="POST",
            request_path="/api/auth/embed/exchange",
            response_status=401,
            details={"reason": str(exc)},
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)
        )

    log_audit(
        action="embed_exchange_success",
        user_id=result["user"]["id"],
        resource_type="auth",
        ip_address=ip,
        user_agent=ua,
        request_method="POST",
        request_path="/api/auth/embed/exchange",
        response_status=200,
        details={"embed_pid": result.get("embed_pid")},
    )

    refresh_token = result.pop("refresh_token", None)
    resp = JSONResponse(content=result)
    if refresh_token:
        secure = settings.app_env != "development"
        resp.set_cookie(
            key=_REFRESH_COOKIE_NAME,
            value=refresh_token,
            httponly=True,
            secure=secure,
            # Iframe embedding in a different origin (OpenEMR) needs SameSite=None
            # to send the cookie on subsequent requests. Browsers require Secure
            # with SameSite=None, which is correct for production (HTTPS only).
            samesite="none" if secure else "lax",
            max_age=_COOKIE_MAX_AGE,
            path="/",
        )
    return resp


@router.post(
    "/embed/mint",
    summary="Mint an embed token (admin/demo only)",
    response_model=EmbedMintResponse,
)
def embed_mint(
    body: EmbedMintRequest,
    current_user: dict = Depends(require_role("admin", "developer")),
) -> EmbedMintResponse:
    """Issue an embed JWT for use by QA tooling or the demo PHP widget.

    This is NOT the production path — real embedders mint tokens with the
    shared secret on their side. It only exists so the RAF demo can show the
    end-to-end flow without a live OpenEMR plugin wired up yet.
    """
    try:
        token = create_embed_token(
            user_email=body.user_email,
            pid=body.pid,
            tenant_id=body.tenant_id,
            ttl_seconds=body.ttl_seconds,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    return EmbedMintResponse(
        embed_token=token,
        expires_in=body.ttl_seconds,
        iframe_url=f"{settings.frontend_url}/embed/raf-central/{body.pid}?t={token}",
    )


# ---------------------------------------------------------------------------
# MFA endpoints
# ---------------------------------------------------------------------------


@router.post("/mfa/verify", summary="Complete MFA login")
@limiter.limit("5/minute")
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
        AUTH_MFA_ATTEMPTS_TOTAL.labels(outcome="failure").inc()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc))
    AUTH_MFA_ATTEMPTS_TOTAL.labels(outcome="success").inc()
    refresh_token = result.pop("refresh_token", None)
    resp = JSONResponse(content=result)
    if refresh_token:
        secure = settings.app_env != "development"
        resp.set_cookie(
            key=_REFRESH_COOKIE_NAME,
            value=refresh_token,
            httponly=True,
            secure=secure,
            samesite="strict" if secure else "lax",
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


@router.post(
    "/mfa/activate",
    summary="Confirm TOTP code and activate MFA",
    response_model=MessageResponse,
)
def activate_mfa(
    body: MFAActivateRequest,
    current_user: dict = Depends(get_current_user),
) -> MessageResponse:
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
    return MessageResponse(message="MFA has been activated successfully.")


@router.post(
    "/mfa/disable",
    summary="Disable MFA (requires password AND a fresh TOTP or recovery code)",
    response_model=MessageResponse,
)
@limiter.limit("5/hour")
def disable_mfa_endpoint(
    request: Request,
    body: MFADisableRequest,
    current_user: dict = Depends(get_current_user),
) -> MessageResponse:
    """Disable MFA for the current user.

    Security model (SEV-1 fix): password alone is insufficient. If the user
    currently has MFA enabled, we require a fresh second factor (TOTP from
    the authenticator app, or a one-time recovery code) in addition to the
    password. This prevents an attacker with a stolen access token plus a
    leaked/phished password from silently turning MFA off.

    If the user does not have MFA enabled, the endpoint is a 200 no-op so
    idempotent client retries do not fail.
    """
    from app.services.auth_service import verify_mfa_code, verify_password

    with raf_cursor() as cur:
        cur.execute(
            "SELECT password_hash, mfa_enabled FROM users WHERE id = %s",
            (current_user["id"],),
        )
        row = cur.fetchone()

    if not row or not verify_password(body.password, row["password_hash"]):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Incorrect password.",
        )

    # If MFA is already disabled, treat as a no-op so clients can retry safely.
    if not row.get("mfa_enabled"):
        return MessageResponse(message="MFA is already disabled.")

    # MFA is enabled → require second factor. Accept either TOTP or a
    # recovery code; verify_mfa_code() handles both paths (and consumes the
    # recovery code on use). Password alone is NOT sufficient.
    second_factor = body.totp_code or body.recovery_code
    if not second_factor:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A TOTP code or recovery code is required to disable MFA.",
        )
    if not verify_mfa_code(current_user["id"], second_factor.strip()):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid second-factor code.",
        )

    disable_mfa(current_user["id"])
    log_audit(
        action="mfa_disabled",
        user_id=current_user["id"],
        resource_type="auth",
        ip_address=_get_client_ip(request),
        request_method="POST",
        request_path="/api/auth/mfa/disable",
        response_status=200,
    )
    return MessageResponse(message="MFA has been disabled.")


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
    # Clear the httpOnly refresh token cookie. Delete BOTH the current name
    # and the legacy name so users mid-rollover are fully logged out.
    response.delete_cookie(key=_REFRESH_COOKIE_NAME, path="/")
    if _REFRESH_COOKIE_NAME != "raf_refresh_token":
        response.delete_cookie(key="raf_refresh_token", path="/")
    return JSONResponse(content={"message": "Logged out successfully."})


# Demo seed used when the user_tenant_access table doesn't exist yet.
# Matches the Edifecs multi-payer/multi-LoB pattern: each row is one
# tenant the active session may pivot into, with the role that user
# holds within that tenant. Order matters — first item is the default.
_DEMO_ACCESSIBLE_TENANTS: list[dict[str, str]] = [
    {"id": "1", "display_name": "Acme Health", "role": "admin"},
    {"id": "2", "display_name": "Beta Care", "role": "viewer"},
]


_tenant_table_exists_cache: tuple[bool, float] | None = None


def _user_tenant_access_table_exists() -> bool:
    """Return True when the optional user_tenant_access table is present.

    TTL-cached (5 min) per-process so we don't run information_schema on
    every /me hit, but we still pick up schema changes within a few minutes.
    Falls back to False (demo path) on any DB error — the switcher must
    never break login.
    """
    global _tenant_table_exists_cache
    now = _time.monotonic()
    if _tenant_table_exists_cache and now - _tenant_table_exists_cache[1] < 300:
        return _tenant_table_exists_cache[0]
    try:
        with raf_cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) AS cnt FROM information_schema.tables "
                "WHERE table_schema = DATABASE() AND table_name = 'user_tenant_access'"
            )
            row = cur.fetchone() or {}
            result = int(row.get("cnt") or 0) > 0
    except Exception as exc:
        logger.warning("user_tenant_access existence probe failed: %s", exc)
        result = False
    _tenant_table_exists_cache = (result, now)
    return result


def _load_accessible_tenants(user_id: int) -> list[dict[str, str]]:
    """Return the list of tenants this user may switch into.

    Resolution order:
      1. If the ``user_tenant_access`` table exists, read live mappings from it.
         Schema expected:
             user_id (FK -> users.id)
             tenant_id (string/int)
             display_name (optional; joined or denormalised)
             role (per-tenant role)
      2. Otherwise return the canonical demo seed used by the design partners.
    """
    if not _user_tenant_access_table_exists():
        return list(_DEMO_ACCESSIBLE_TENANTS)

    try:
        with raf_cursor() as cur:
            cur.execute(
                """
                SELECT
                    uta.tenant_id AS id,
                    COALESCE(
                        uta.display_name,
                        ec.display_name,
                        CONCAT('Tenant ', uta.tenant_id)
                    ) AS display_name,
                    COALESCE(uta.role, 'viewer') AS role
                FROM user_tenant_access uta
                LEFT JOIN emr_connections ec
                    ON ec.tenant_id = uta.tenant_id AND ec.is_active = 1
                WHERE uta.user_id = %s
                ORDER BY uta.tenant_id
                """,
                (user_id,),
            )
            rows = cur.fetchall() or []
    except Exception as exc:
        # Table exists but the query failed (likely schema drift). Don't
        # 500 — fall back to the demo seed so the switcher still renders.
        logger.warning(
            "user_tenant_access query failed for user_id=%s: %s", user_id, exc
        )
        return list(_DEMO_ACCESSIBLE_TENANTS)

    return [
        {
            "id": str(r["id"]),
            "display_name": str(r["display_name"]),
            "role": str(r["role"]),
        }
        for r in rows
    ] or list(_DEMO_ACCESSIBLE_TENANTS)


@router.get(
    "/me",
    summary="Get current user profile",
    response_model=UserProfileResponse,
    response_model_exclude_none=True,
)
def get_me(current_user: dict = Depends(get_current_user)) -> UserProfileResponse:
    user = get_user(current_user["id"])
    if not user:
        raise HTTPException(status_code=404, detail="User not found.")
    row = _serialize_row(
        {
            "id": user["id"],
            "email": user["email"],
            "full_name": user["full_name"],
            "role": user["role"],
            "tenant_id": user["tenant_id"],
            "avatar_url": user["avatar_url"],
            "last_login_at": user["last_login_at"],
            "created_at": user["created_at"],
            "provider_id": user.get("provider_id"),
        }
    )

    tid = user.get("tenant_id")
    onboarding_complete = False
    if tid is not None:
        try:
            with raf_cursor() as cur:
                cur.execute(
                    """
                    SELECT
                        (SELECT COUNT(*) FROM emr_connections
                         WHERE tenant_id = %s AND is_active = 1) AS emr_count,
                        (SELECT COUNT(*) FROM patients
                         WHERE tenant_id = %s) AS patient_count
                    """,
                    (tid, tid),
                )
                counts = cur.fetchone() or {}
            onboarding_complete = (
                int(counts.get("emr_count") or 0) > 0
                and int(counts.get("patient_count") or 0) > 0
            )
        except Exception:
            logger.debug("swallowed exception", exc_info=True)
            onboarding_complete = False

    row["onboarding_complete"] = onboarding_complete

    # Accessible tenants — for the org switcher in the header. Always present
    # (at minimum the current tenant, via the demo seed) so the frontend can
    # render the dropdown without an extra round-trip.
    try:
        row["accessible_tenants"] = _load_accessible_tenants(int(user["id"]))
    except Exception as exc:
        logger.warning("Failed to load accessible_tenants for user %s: %s", user["id"], exc)
        row["accessible_tenants"] = list(_DEMO_ACCESSIBLE_TENANTS)

    return UserProfileResponse(**row)


@router.put(
    "/me",
    summary="Update own profile (name, avatar)",
    response_model=UserProfileResponse,
    response_model_exclude_none=True,
)
def update_me(
    body: UpdateProfileRequest,
    current_user: dict = Depends(get_current_user),
) -> UserProfileResponse:
    updated = update_user(
        user_id=current_user["id"],
        full_name=body.full_name,
        avatar_url=body.avatar_url,
    )
    if not updated:
        raise HTTPException(status_code=404, detail="User not found.")
    row = _serialize_row(
        {
            "id": updated["id"],
            "email": updated["email"],
            "full_name": updated["full_name"],
            "role": updated["role"],
            "avatar_url": updated["avatar_url"],
            "updated_at": updated["updated_at"],
        }
    )
    return UserProfileResponse(**row)


@router.put(
    "/change-password",
    summary="Change own password (requires current password)",
    response_model=MessageResponse,
)
def change_own_password(
    body: ChangePasswordRequest,
    current_user: dict = Depends(get_current_user),
) -> MessageResponse:
    try:
        change_password(current_user["id"], body.old_password, body.new_password)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    return MessageResponse(
        message="Password changed successfully. All other sessions have been revoked."
    )


@router.get(
    "/sessions",
    summary="List own active sessions",
    response_model=list[dict[str, Any]],
)
def get_sessions(
    current_user: dict = Depends(get_current_user),
) -> list[dict[str, Any]]:
    sessions = list_sessions(current_user["id"])
    return [_serialize_row(s) for s in sessions]


@router.delete(
    "/sessions/{session_id}",
    summary="Revoke a specific session",
    response_model=MessageResponse,
)
def delete_session(
    session_id: str,
    current_user: dict = Depends(get_current_user),
) -> MessageResponse:
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
    return MessageResponse(message="Session revoked.")


# ---------------------------------------------------------------------------
# Admin – User management
# ---------------------------------------------------------------------------


@router.get(
    "/users",
    summary="List all users (admin/manager only)",
    response_model=UserListResponse,
)
def admin_list_users(
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    role: str | None = Query(None),
    is_active: bool | None = Query(None),
    current_user: dict = Depends(require_role("admin", "manager")),
    tenant_id: str = Depends(get_tenant_id),
) -> UserListResponse:
    users = list_users(limit=limit, offset=offset, role=role, is_active=is_active, tenant_id=tenant_id)
    serialized = [_safe_user(u) for u in users]
    total = count_users(role=role, is_active=is_active, tenant_id=tenant_id)
    return UserListResponse(count=len(serialized), total=total, users=serialized)


@router.post(
    "/users",
    summary="Create a new user (admin only)",
    status_code=201,
    response_model=UserDetailResponse,
    response_model_exclude_none=True,
)
def admin_create_user(
    request: Request,
    response: Response,
    body: CreateUserRequest,
    current_user: dict = Depends(require_role("admin")),
    _idem: None = Depends(idempotency_key_dependency()),
) -> UserDetailResponse:
    """
    Create a new user account.

    Supports Idempotency-Key header (24h replay window).
    """
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
    safe = _safe_user(user)
    store_idempotent_response(request, response, safe)
    return UserDetailResponse(**safe)


@router.get(
    "/users/{user_id}",
    summary="Get user detail",
    response_model=UserDetailResponse,
    response_model_exclude_none=True,
)
def admin_get_user(
    user_id: int,
    current_user: dict = Depends(require_role("admin", "manager")),
    tenant_id: str = Depends(get_tenant_id),
) -> UserDetailResponse:
    user = get_user(user_id)
    if not user or str(user.get("tenant_id")) != str(tenant_id):
        raise HTTPException(status_code=404, detail="User not found.")
    safe = _safe_user(user)
    return UserDetailResponse(**safe)


@router.put(
    "/users/{user_id}",
    summary="Update a user (admin only)",
    response_model=UserDetailResponse,
    response_model_exclude_none=True,
)
def admin_update_user(
    user_id: int,
    body: UpdateUserRequest,
    current_user: dict = Depends(require_role("admin")),
    tenant_id: str = Depends(get_tenant_id),
) -> UserDetailResponse:
    user = get_user(user_id)
    if not user or str(user.get("tenant_id")) != str(tenant_id):
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
    safe = _safe_user(updated)
    return UserDetailResponse(**safe)


@router.delete(
    "/users/{user_id}",
    summary="Deactivate a user (admin only)",
    response_model=UserDetailResponse,
    response_model_exclude_none=True,
)
def admin_deactivate_user(
    user_id: int,
    current_user: dict = Depends(require_role("admin")),
    tenant_id: str = Depends(get_tenant_id),
) -> UserDetailResponse:
    if user_id == current_user["id"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot deactivate your own account.",
        )
    user = get_user(user_id)
    if not user or str(user.get("tenant_id")) != str(tenant_id):
        raise HTTPException(status_code=404, detail="User not found.")
    deactivated = deactivate_user(user_id)
    log_audit(
        action="user_deactivated",
        user_id=current_user["id"],
        resource_type="user",
        resource_id=str(user_id),
    )
    safe = _safe_user(deactivated)
    return UserDetailResponse(**safe)


@router.get(
    "/users/{user_id}/permissions",
    summary="Get effective permissions for a user",
    response_model=UserPermissionsResponse,
)
def admin_get_permissions(
    user_id: int,
    current_user: dict = Depends(require_role("admin", "manager")),
    tenant_id: str = Depends(get_tenant_id),
) -> UserPermissionsResponse:
    user = get_user(user_id)
    if not user or str(user.get("tenant_id")) != str(tenant_id):
        raise HTTPException(status_code=404, detail="User not found.")
    perms = get_user_permissions(user_id)
    return UserPermissionsResponse(user_id=user_id, role=user["role"], permissions=perms)


@router.put(
    "/users/{user_id}/permissions",
    summary="Set user permission overrides (admin only)",
    response_model=UserPermissionsResponse,
)
def admin_set_permissions(
    user_id: int,
    body: SetPermissionsRequest,
    current_user: dict = Depends(require_role("admin")),
    tenant_id: str = Depends(get_tenant_id),
) -> UserPermissionsResponse:
    user = get_user(user_id)
    if not user or str(user.get("tenant_id")) != str(tenant_id):
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
    return UserPermissionsResponse(user_id=user_id, role=user["role"], permissions=perms)


# ---------------------------------------------------------------------------
# Audit log (admin/auditor only)
# ---------------------------------------------------------------------------


@router.get(
    "/audit-log",
    summary="Query the audit log (admin/auditor only)",
    response_model=AuditLogResponse,
)
def get_audit_log(
    # Legacy param — kept for backwards compat
    user_id: int | None = Query(None, description="Filter by actor user ID"),
    # Explicit alias; takes precedence over user_id when both supplied
    actor_user_id: int | None = Query(
        None,
        description="Filter by the user who performed the action (e.g. Dr. Jones' user ID)",
    ),
    # Legacy action param
    action: str | None = Query(None, description="Filter by action string"),
    # Explicit alias; takes precedence over action when both supplied
    action_type: str | None = Query(
        None,
        description=(
            "Filter by action type, e.g. 'suspect_accepted', 'hcc_withdrawn', "
            "'attest_submitted'"
        ),
    ),
    resource_type: str | None = Query(
        None,
        description=(
            "Filter by resource type, e.g. 'suspect', 'patient_hcc', "
            "'attestation', 'user'"
        ),
    ),
    patient_id: int | None = Query(None, description="Filter by patient ID"),
    # Primary date params (accept both datetime and bare date strings)
    start_date: str | None = Query(None, description="ISO date/datetime start, e.g. 2025-01-01"),
    end_date: str | None = Query(None, description="ISO date/datetime end, e.g. 2025-12-31"),
    # Preferred aliases for quarterly range queries
    date_from: date | None = Query(
        None, description="Range start (inclusive) — date only, e.g. 2025-01-01"
    ),
    date_to: date | None = Query(
        None, description="Range end (inclusive) — date only, e.g. 2025-03-31"
    ),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    current_user: dict = Depends(require_role("admin", "auditor")),
    tenant_id: str = Depends(get_tenant_id),
) -> AuditLogResponse:
    # Merge string-style date params; explicit start_date/end_date take precedence
    # over date_from/date_to when both families are provided.
    start_dt: datetime | None = None
    end_dt: datetime | None = None
    _start_raw = start_date
    _end_raw = end_date
    if _start_raw:
        try:
            start_dt = datetime.fromisoformat(_start_raw)
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid start_date format: {_start_raw!r}. Use ISO 8601, e.g. 2025-01-01.",
            )
    if _end_raw:
        try:
            end_dt = datetime.fromisoformat(_end_raw)
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid end_date format: {_end_raw!r}. Use ISO 8601, e.g. 2025-12-31.",
            )
    # date_from/date_to fill in only if the string params were not given
    if start_dt is None and date_from is not None:
        start_dt = datetime(date_from.year, date_from.month, date_from.day, 0, 0, 0)
    if end_dt is None and date_to is not None:
        end_dt = datetime(date_to.year, date_to.month, date_to.day, 23, 59, 59)

    rows = query_audit_log(
        user_id=user_id,
        actor_user_id=actor_user_id,
        action=action,
        action_type=action_type,
        resource_type=resource_type,
        patient_id=patient_id,
        start_date=start_dt,
        end_date=end_dt,
        limit=limit,
        offset=offset,
        tenant_id=tenant_id,
    )
    return AuditLogResponse(
        count=len(rows),
        entries=[_serialize_row(r) for r in rows],
    )


# ---------------------------------------------------------------------------
# Tenant switcher (super-admin only)
# ---------------------------------------------------------------------------


class SwitchTenantRequest(BaseModel):
    tenant_id: str


@router.get(
    "/tenants",
    summary="List all tenants (admin only)",
    response_model=TenantListResponse,
)
def list_tenants(
    current_user: dict = Depends(require_role("admin")),
    tenant_id: str = Depends(get_tenant_id),
) -> TenantListResponse:
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
            TenantItem(
                tenant_id=str(row["tenant_id"]),
                name=row["name"],
                patient_count=row["patient_count"],
                user_count=row["user_count"],
            )
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
                TenantItem(
                    tenant_id=str(tenant_id),
                    name=f"Tenant {tenant_id}",
                    patient_count=0,
                    user_count=int((row or {}).get("user_count", 0)),
                )
            )

    return TenantListResponse(
        tenants=tenants,
        current_tenant_id=str(tenant_id),
    )


@router.post(
    "/switch-tenant",
    summary="Switch active tenant (super-admin only)",
    response_model=SwitchTenantResponse,
)
def switch_tenant(
    body: SwitchTenantRequest,
    current_user: dict = Depends(require_role("admin", "super_admin")),
) -> SwitchTenantResponse:
    """
    Issue a new access token scoped to a different tenant.

    Restricted to super-admin (highest privilege). Regular tenant admins
    must NOT be able to cross-tenant pivot — that's a customer-data
    boundary violation. The user record stays on their original tenant —
    only the JWT tenant_id claim changes.
    """
    # Defence in depth: require_role above already filters by role, but we
    # double-check here so a future change to require_role()'s allowed list
    # does not silently re-open cross-tenant pivot to plain "admin".
    if current_user.get("role") != "super_admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only super-admin may switch tenants.",
        )
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

    return SwitchTenantResponse(
        access_token=new_token,
        tenant_id=target_tid,
        message=f"Switched to tenant {target_tid}",
    )


# ---------------------------------------------------------------------------
# Break-glass emergency access
# ---------------------------------------------------------------------------


class BreakGlassRequest(BaseModel):
    reason: str = Field(..., min_length=10, description="Clinical justification for emergency access")


@router.post(
    "/break-glass",
    response_model=BreakGlassResponse,
)
def api_break_glass(
    body: BreakGlassRequest,
    request: Request,
    current_user: dict = Depends(require_role("admin", "physician", "provider", "medical_director")),
) -> BreakGlassResponse:
    """Activate break-glass emergency access (physicians/admins only).

    Creates a time-limited (30 min) emergency session with full audit trail.
    """
    from app.services.break_glass import create_break_glass_session

    ip = _get_client_ip(request)
    try:
        session = create_break_glass_session(
            user_id=current_user["id"],
            tenant_id=current_user.get("tenant_id", "unknown"),
            reason=body.reason,
            role=current_user.get("role", ""),
            ip_address=ip,
        )
        return BreakGlassResponse(status="ok", break_glass_session=session)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
