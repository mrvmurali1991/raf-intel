"""
Authentication and authorization service for RAF Intelligence — compatibility shim.

The implementation has been decomposed into focused modules under
``app.services.auth``:

  - auth/password_policy.py  — hashing, strength validation, history
  - auth/tokens.py           — JWT issuance, decoding, refresh, embed
  - auth/mfa.py              — TOTP + recovery codes
  - auth/permissions.py      — RBAC helpers + seeding
  - auth/sessions.py         — session lifecycle

This file re-exports every public symbol so that existing callers
(``from app.services.auth_service import X``) keep working unchanged.

Per PEP 562, a module-level ``__getattr__`` emits a DeprecationWarning
so gradual migration to ``from app.services.auth import X`` can be tracked.
"""
from __future__ import annotations

import json
import logging
import os
import secrets
import uuid
import warnings
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import jwt

from app.config import settings
from app.db import raf_cursor

# ---------------------------------------------------------------------------
# Sub-module imports — the real implementations live here
# ---------------------------------------------------------------------------
from app.services.auth.password_policy import (
    _COMMON_PASSWORDS,
    _PASSWORD_HISTORY_DEPTH,
    _check_password_history,
    _pwd_context,
    _record_password_history,
    check_password_history,
    hash_password,
    record_password_history,
    validate_password_strength,
    verify_password,
)
from app.services.auth.tokens import (
    _create_mfa_pending_token,
    _embed_signing_secret,
    _hash_token,
    _is_production,
    _utcnow,
    authenticate_embed_token as _auth_embed_token_impl,
    create_access_token,
    create_embed_token,
    create_refresh_token,
    decode_refresh_token,
    decode_token,
    refresh_access_token as _refresh_access_token_impl,
)
from app.services.auth.sessions import (
    create_session,
    issue_tokens as _issue_tokens_impl,
    list_sessions,
    revoke_all_sessions,
    revoke_session,
    validate_session,
)
from app.services.auth.mfa import (
    complete_mfa_login as _complete_mfa_login_impl,
    disable_mfa,
    enable_mfa as _enable_mfa_impl,
    verify_and_activate_mfa,
    verify_mfa_code,
)
from app.services.auth.permissions import (
    check_permission as _check_permission_impl,
    get_user_permissions as _get_user_perms_impl,
    seed_default_permissions,
    set_user_permissions,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# PEP 562 deprecation shim — fires when callers import from THIS module
# ---------------------------------------------------------------------------

_PUBLIC_NAMES: frozenset[str] = frozenset(
    {
        # password_policy
        "hash_password", "verify_password", "validate_password_strength",
        "_check_password_history", "_record_password_history",
        "check_password_history", "record_password_history",
        "_COMMON_PASSWORDS", "_PASSWORD_HISTORY_DEPTH", "_pwd_context",
        # tokens
        "create_access_token", "create_refresh_token",
        "decode_token", "decode_refresh_token",
        "create_embed_token", "authenticate_embed_token",
        "refresh_access_token",
        "_create_mfa_pending_token", "_hash_token", "_utcnow",
        "_embed_signing_secret", "_is_production",
        # sessions
        "create_session", "validate_session", "revoke_session",
        "revoke_all_sessions", "list_sessions",
        # mfa
        "enable_mfa", "verify_and_activate_mfa", "verify_mfa_code",
        "disable_mfa", "complete_mfa_login",
        # permissions
        "seed_default_permissions", "get_user_permissions",
        "check_permission", "set_user_permissions",
        # orchestrators that live here
        "authenticate_user", "create_user", "get_user", "get_user_by_email",
        "list_users", "update_user", "deactivate_user",
        "change_password", "generate_password_reset_token", "reset_password",
        "log_audit", "query_audit_log",
        "_ensure_tables", "_seed_default_permissions", "_seed_dev_admin_user",
        "_issue_tokens", "_attach_must_change_password",
        "_tables_ensured",
    }
)


def __getattr__(name: str) -> Any:
    """PEP 562: emit DeprecationWarning on access to public symbols.

    This fires only when a caller does ``from app.services.auth_service import X``
    at runtime (i.e., when the attribute is resolved through this module's
    ``__getattr__``).  Direct ``import app.services.auth_service`` then
    attribute access on the module object also triggers it.
    """
    if name in _PUBLIC_NAMES:
        warnings.warn(
            f"Importing '{name}' from 'app.services.auth_service' is deprecated. "
            f"Use 'from app.services.auth import {name}' instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        return globals()[name]
    raise AttributeError(f"module 'app.services.auth_service' has no attribute {name!r}")


# ---------------------------------------------------------------------------
# Backward-compatible bootstrap flag
# ---------------------------------------------------------------------------

_tables_ensured = False


def _ensure_tables() -> None:
    """One-time auth bootstrap after centralized migrations."""
    global _tables_ensured
    if _tables_ensured:
        return
    try:
        seed_default_permissions()
    except Exception as exc:
        logger.warning("auth bootstrap: default permissions not seeded: %s", exc)
    try:
        _seed_dev_admin_user()
    except Exception as exc:
        logger.warning("auth bootstrap: dev admin seed skipped: %s", exc)
    _tables_ensured = True


def _seed_default_permissions() -> None:
    """Backward-compat alias — delegates to permissions module."""
    seed_default_permissions()


def _seed_dev_admin_user() -> None:
    """Seed a local admin account for development environments only."""
    if settings.app_env != "development" or not settings.allow_dev_admin_seed:
        logger.info(
            "dev admin seed skipped (APP_ENV=%s, allow_dev_admin_seed=%s)",
            settings.app_env,
            settings.allow_dev_admin_seed,
        )
        return

    email = os.getenv("DEV_ADMIN_EMAIL", "admin@raf.health")
    password = os.getenv("DEV_ADMIN_PASSWORD")
    full_name = os.getenv("DEV_ADMIN_FULL_NAME", "Development Admin")
    if not password:
        logger.warning(
            "DEV_ADMIN_PASSWORD not set; skipping dev admin seed for %s", email
        )
        return
    password_hash = hash_password(password)

    with raf_cursor() as cur:
        cur.execute("SELECT id FROM users WHERE email = %s", (email,))
        if cur.fetchone():
            return
        cur.execute(
            """
            INSERT INTO users
                (email, password_hash, full_name, role, tenant_id, is_active, password_changed_at)
            VALUES
                (%s, %s, %s, 'admin', 1, 1, NOW())
            """,
            (email, password_hash, full_name),
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _attach_must_change_password(user: dict[str, Any]) -> dict[str, Any]:
    pca = user.get("password_changed_at")
    user["must_change_password"] = pca is None
    return user


# ---------------------------------------------------------------------------
# User CRUD
# ---------------------------------------------------------------------------

def create_user(
    email: str,
    password: str,
    full_name: str | None = None,
    role: str = "viewer",
    tenant_id: int | None = None,
    initial_permissions: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    _ensure_tables()
    valid, err = validate_password_strength(password)
    if not valid:
        raise ValueError(err)
    with raf_cursor() as cur:
        cur.execute("SELECT id FROM users WHERE email = %s", (email,))
        if cur.fetchone():
            raise ValueError(f"User with email {email!r} already exists.")
        password_hash = hash_password(password)
        cur.execute(
            """
            INSERT INTO users (email, password_hash, full_name, role, tenant_id)
            VALUES (%s, %s, %s, %s, %s)
            """,
            (email, password_hash, full_name, role, tenant_id),
        )
        user_id = cur.lastrowid
        if initial_permissions:
            cur.executemany(
                """
                INSERT INTO user_permissions (user_id, resource, action, granted)
                VALUES (%s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE granted = VALUES(granted)
                """,
                [
                    (
                        user_id,
                        perm["resource"],
                        perm["action"],
                        1 if perm.get("granted", True) else 0,
                    )
                    for perm in initial_permissions
                ],
            )
    return get_user(user_id)


def get_user(user_id: int) -> dict[str, Any] | None:
    _ensure_tables()
    with raf_cursor() as cur:
        cur.execute(
            """
            SELECT id, email, full_name, role, tenant_id, is_active, avatar_url,
                   failed_login_attempts, locked_until, last_login_at,
                   password_changed_at, created_at, updated_at,
                   mfa_enabled, mfa_secret, mfa_recovery_codes
            FROM users WHERE id = %s
            """,
            (user_id,),
        )
        row = cur.fetchone()
    if row is None:
        return None
    return _attach_must_change_password(row)


def get_user_by_email(email: str) -> dict[str, Any] | None:
    _ensure_tables()
    with raf_cursor() as cur:
        cur.execute(
            """
            SELECT id, email, full_name, role, tenant_id, is_active, avatar_url,
                   failed_login_attempts, locked_until, last_login_at,
                   password_hash, password_changed_at, created_at, updated_at
            FROM users WHERE email = %s
            """,
            (email,),
        )
        row = cur.fetchone()
    if row is None:
        return None
    return _attach_must_change_password(row)


def list_users(
    limit: int = 100,
    offset: int = 0,
    role: str | None = None,
    is_active: bool | None = None,
    tenant_id: str = "",
) -> list[dict[str, Any]]:
    if not tenant_id:
        raise ValueError("list_users: tenant_id is required")
    _ensure_tables()
    conditions = ["tenant_id = %s"]
    params: list[Any] = [tenant_id]
    if role is not None:
        conditions.append("role = %s")
        params.append(role)
    if is_active is not None:
        conditions.append("is_active = %s")
        params.append(1 if is_active else 0)
    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    params.extend([limit, offset])
    with raf_cursor() as cur:
        cur.execute(
            f"""
            SELECT id, email, full_name, role, tenant_id, is_active, avatar_url,
                   failed_login_attempts, last_login_at, created_at, updated_at
            FROM users {where}
            ORDER BY created_at DESC
            LIMIT %s OFFSET %s
            """,
            params,
        )
        return cur.fetchall()


def update_user(
    user_id: int,
    full_name: str | None = None,
    role: str | None = None,
    avatar_url: str | None = None,
    tenant_id: int | None = None,
) -> dict[str, Any] | None:
    _ensure_tables()
    fields: list[str] = []
    params: list[Any] = []
    if full_name is not None:
        fields.append("full_name = %s")
        params.append(full_name)
    if role is not None:
        fields.append("role = %s")
        params.append(role)
    if avatar_url is not None:
        fields.append("avatar_url = %s")
        params.append(avatar_url)
    if tenant_id is not None:
        fields.append("tenant_id = %s")
        params.append(tenant_id)
    if not fields:
        return get_user(user_id)
    params.append(user_id)
    with raf_cursor() as cur:
        cur.execute(
            f"UPDATE users SET {', '.join(fields)} WHERE id = %s",
            params,
        )
    return get_user(user_id)


def deactivate_user(user_id: int) -> dict[str, Any] | None:
    _ensure_tables()
    with raf_cursor() as cur:
        cur.execute("UPDATE users SET is_active = 0 WHERE id = %s", (user_id,))
    revoke_all_sessions(user_id)
    return get_user(user_id)


# ---------------------------------------------------------------------------
# Password management
# ---------------------------------------------------------------------------

def change_password(user_id: int, old_password: str, new_password: str) -> None:
    _ensure_tables()
    valid, err = validate_password_strength(new_password)
    if not valid:
        raise ValueError(err)
    with raf_cursor() as cur:
        cur.execute("SELECT password_hash FROM users WHERE id = %s", (user_id,))
        row = cur.fetchone()
    if not row:
        raise ValueError("User not found.")
    if not verify_password(old_password, row["password_hash"]):
        raise ValueError("Current password is incorrect.")
    old_hash = row["password_hash"]
    _check_password_history(user_id, new_password)
    new_hash = hash_password(new_password)
    with raf_cursor() as cur:
        cur.execute(
            "UPDATE users SET password_hash = %s, password_changed_at = NOW() WHERE id = %s",
            (new_hash, user_id),
        )
    _record_password_history(user_id, old_hash)
    revoke_all_sessions(user_id)


def generate_password_reset_token(email: str) -> str:
    """Create a password reset token stored (hashed) on the user record."""
    _ensure_tables()
    token = secrets.token_urlsafe(32)
    token_hash = _hash_token(token)
    expires = _utcnow() + timedelta(hours=1)
    with raf_cursor() as cur:
        cur.execute(
            "UPDATE users SET password_reset_token = %s, password_reset_expires = %s WHERE email = %s",
            (token_hash, expires.strftime("%Y-%m-%d %H:%M:%S"), email),
        )
        if cur.rowcount == 0:
            raise ValueError("No user with that email address.")

    from app.services import email_service

    reset_url = f"{settings.frontend_url}/login?reset_token={token}"
    email_service.send_password_reset(email, reset_url, expires_minutes=30)

    return token


def reset_password(token: str, new_password: str) -> None:
    """Reset password using a token previously issued by generate_password_reset_token."""
    _ensure_tables()
    valid, err = validate_password_strength(new_password)
    if not valid:
        raise ValueError(err)
    token_hash = _hash_token(token)
    with raf_cursor() as cur:
        cur.execute(
            """
            SELECT id, password_hash, password_reset_expires
            FROM users
            WHERE password_reset_token = %s AND is_active = 1
            """,
            (token_hash,),
        )
        row = cur.fetchone()
    if not row:
        raise ValueError("Invalid or expired reset token.")
    expires = row["password_reset_expires"]
    if isinstance(expires, str):
        expires = datetime.fromisoformat(expires)
    if expires.replace(tzinfo=timezone.utc) < _utcnow():
        raise ValueError("Reset token has expired.")
    old_hash = row["password_hash"]
    _check_password_history(row["id"], new_password)
    new_hash = hash_password(new_password)
    with raf_cursor() as cur:
        cur.execute(
            """
            UPDATE users
            SET password_hash = %s, password_reset_token = NULL, password_reset_expires = NULL,
                failed_login_attempts = 0, locked_until = NULL, password_changed_at = NOW()
            WHERE id = %s
            """,
            (new_hash, row["id"]),
        )
    _record_password_history(row["id"], old_hash)
    revoke_all_sessions(row["id"])


# ---------------------------------------------------------------------------
# Token refresh (public wrapper with injected dependencies)
# ---------------------------------------------------------------------------

def refresh_access_token(refresh_token: str) -> dict[str, Any]:
    """Rotate refresh token on every use — delegates to tokens module."""
    _ensure_tables()
    return _refresh_access_token_impl(
        refresh_token,
        get_user_fn=get_user,
        revoke_all_sessions_fn=revoke_all_sessions,
    )


# ---------------------------------------------------------------------------
# Embed token exchange
# ---------------------------------------------------------------------------

def authenticate_embed_token(
    embed_token: str,
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> dict[str, Any]:
    """Verify an embed JWT and issue a scoped RAF session."""
    _ensure_tables()
    return _auth_embed_token_impl(
        embed_token,
        get_user_by_email_fn=get_user_by_email,
        ip_address=ip_address,
        user_agent=user_agent,
    )


# ---------------------------------------------------------------------------
# Authentication orchestrator
# ---------------------------------------------------------------------------

def _issue_tokens(
    user: dict[str, Any],
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> dict[str, Any]:
    """Backward-compat wrapper — delegates to sessions.issue_tokens."""
    return _issue_tokens_impl(user, ip_address=ip_address, user_agent=user_agent)


def authenticate_user(
    email: str,
    password: str,
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> dict[str, Any]:
    """Authenticate by email + password.

    Returns a dict with access_token, refresh_token, token_type, and user.
    Raises ValueError with user-safe messages on failure.
    """
    _ensure_tables()

    with raf_cursor() as cur:
        cur.execute(
            """
            SELECT id, email, full_name, role, tenant_id, is_active, avatar_url,
                   failed_login_attempts, locked_until, password_hash,
                   password_changed_at, created_at, mfa_enabled
            FROM users WHERE email = %s
            """,
            (email,),
        )
        user = cur.fetchone()
    if user:
        _attach_must_change_password(user)

    if not user:
        _pwd_context.verify(
            "dummy", "$2b$12$LJ3m4ys3Lgxmx4XRSG5H8OjG5OhHWLBDhtNBCjw.XMJkRiQHJKo6"
        )
        raise ValueError("Invalid email or password.")

    if not user["is_active"]:
        raise ValueError("Account is inactive. Contact your administrator.")

    locked_until = user.get("locked_until")
    if locked_until and isinstance(locked_until, (str, datetime)):
        if isinstance(locked_until, str):
            locked_until = datetime.fromisoformat(locked_until)
        if locked_until.replace(tzinfo=timezone.utc) > _utcnow():
            remaining = (
                int(
                    (
                        locked_until.replace(tzinfo=timezone.utc) - _utcnow()
                    ).total_seconds()
                    / 60
                )
                + 1
            )
            raise ValueError(
                f"Account locked due to too many failed login attempts. "
                f"Try again in {remaining} minute(s)."
            )

    if not verify_password(password, user["password_hash"]):
        attempts = user["failed_login_attempts"] + 1
        if attempts >= settings.max_failed_logins:
            lock_until = _utcnow() + timedelta(minutes=settings.lockout_duration_minutes)
            with raf_cursor() as cur:
                cur.execute(
                    """
                    UPDATE users
                    SET failed_login_attempts = %s, locked_until = %s
                    WHERE id = %s
                    """,
                    (attempts, lock_until.strftime("%Y-%m-%d %H:%M:%S"), user["id"]),
                )
            raise ValueError(
                f"Invalid email or password. Account locked for {settings.lockout_duration_minutes} minutes."
            )
        with raf_cursor() as cur:
            cur.execute(
                "UPDATE users SET failed_login_attempts = %s WHERE id = %s",
                (attempts, user["id"]),
            )
        raise ValueError("Invalid email or password.")

    with raf_cursor() as cur:
        cur.execute(
            """
            UPDATE users
            SET failed_login_attempts = 0, locked_until = NULL, last_login_at = NOW()
            WHERE id = %s
            """,
            (user["id"],),
        )

    if user.get("mfa_enabled"):
        mfa_token = _create_mfa_pending_token(user["id"])
        return {
            "mfa_required": True,
            "mfa_token": mfa_token,
            "token_type": "bearer",
        }

    return _issue_tokens(user, ip_address=ip_address, user_agent=user_agent)


# ---------------------------------------------------------------------------
# MFA wrappers (inject get_user / _issue_tokens)
# ---------------------------------------------------------------------------

def enable_mfa(user_id: int) -> dict[str, Any]:
    _ensure_tables()
    return _enable_mfa_impl(user_id, get_user_fn=get_user)


def complete_mfa_login(
    mfa_token: str,
    totp_code: str,
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> dict[str, Any]:
    _ensure_tables()
    return _complete_mfa_login_impl(
        mfa_token,
        totp_code,
        get_user_fn=get_user,
        issue_tokens_fn=_issue_tokens,
        ip_address=ip_address,
        user_agent=user_agent,
    )


# ---------------------------------------------------------------------------
# Permission wrappers
# ---------------------------------------------------------------------------

def get_user_permissions(user_id: int) -> list[dict[str, Any]]:
    _ensure_tables()
    return _get_user_perms_impl(user_id, get_user_fn=get_user)


def check_permission(user_id: int, resource: str, action: str) -> bool:
    _ensure_tables()
    return _check_permission_impl(user_id, resource, action, get_user_fn=get_user)


# ---------------------------------------------------------------------------
# Audit logging
# ---------------------------------------------------------------------------

def _write_fallback_audit(
    user_id: int | None,
    action: str,
    resource_type: str | None,
    resource_id: str | None,
    patient_id: int | None,
    details: dict[str, Any] | None,
    error: Exception,
) -> None:
    """Fallback audit log when database is unavailable. HIPAA requires continuous audit trail."""
    fallback_path = (
        Path(__file__).parent.parent.parent / "logs" / "audit_fallback.jsonl"
    )
    fallback_path.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "user_id": user_id,
        "action": action,
        "resource_type": resource_type,
        "resource_id": resource_id,
        "patient_id": patient_id,
        "details": details,
        "db_error": str(error),
    }
    with open(fallback_path, "a") as f:
        f.write(json.dumps(entry) + "\n")


def log_audit(
    action: str,
    user_id: int | None = None,
    resource_type: str | None = None,
    resource_id: str | None = None,
    patient_id: int | None = None,
    ip_address: str | None = None,
    user_agent: str | None = None,
    request_method: str | None = None,
    request_path: str | None = None,
    response_status: int | None = None,
    details: dict[str, Any] | None = None,
) -> None:
    """Write one row to audit_log. On failure, escalates to CRITICAL and writes a fallback file."""
    try:
        _ensure_tables()
        details_json = json.dumps(details) if details else None
        with raf_cursor() as cur:
            cur.execute(
                """
                INSERT INTO audit_log
                    (user_id, action, resource_type, resource_id, patient_id,
                     ip_address, user_agent, request_method, request_path,
                     response_status, details)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    user_id,
                    action,
                    resource_type,
                    resource_id,
                    patient_id,
                    ip_address,
                    user_agent,
                    request_method,
                    request_path,
                    response_status,
                    details_json,
                ),
            )
    except Exception as exc:
        logger.critical(
            "AUDIT LOG FAILURE - HIPAA VIOLATION: action=%s resource=%s user=%s error=%s",
            action,
            resource_type,
            user_id,
            exc,
        )
        if settings.app_env != "development":
            _write_fallback_audit(
                user_id, action, resource_type, resource_id, patient_id, details, exc
            )


def query_audit_log(
    user_id: int | None = None,
    action: str | None = None,
    resource_type: str | None = None,
    patient_id: int | None = None,
    start_date: datetime | None = None,
    end_date: datetime | None = None,
    limit: int = 100,
    offset: int = 0,
    tenant_id: str | None = None,
    actor_user_id: int | None = None,
    action_type: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
) -> list[dict[str, Any]]:
    """Query the audit_log table with optional filters."""
    _ensure_tables()

    effective_user_id: int | None = actor_user_id if actor_user_id is not None else user_id
    effective_action: str | None = action_type if action_type else action

    if date_from is not None and start_date is None:
        start_date = datetime(date_from.year, date_from.month, date_from.day, 0, 0, 0)
    if date_to is not None and end_date is None:
        end_date = datetime(date_to.year, date_to.month, date_to.day, 23, 59, 59)

    conditions: list[str] = []
    params: list[Any] = []

    if tenant_id is not None:
        conditions.append(
            "al.user_id IN (SELECT id FROM users WHERE tenant_id = %s)"
        )
        params.append(tenant_id)
    if effective_user_id is not None:
        conditions.append("al.user_id = %s")
        params.append(effective_user_id)
    if effective_action:
        conditions.append("al.action = %s")
        params.append(effective_action)
    if resource_type:
        conditions.append("al.resource_type = %s")
        params.append(resource_type)
    if patient_id is not None:
        conditions.append("al.patient_id = %s")
        params.append(patient_id)
    if start_date:
        conditions.append("al.created_at >= %s")
        params.append(start_date.strftime("%Y-%m-%d %H:%M:%S"))
    if end_date:
        conditions.append("al.created_at <= %s")
        params.append(end_date.strftime("%Y-%m-%d %H:%M:%S"))

    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    params.extend([limit, offset])

    _primary_sql = f"""
        SELECT al.id, al.user_id, al.action, al.resource_type, al.resource_id,
               al.patient_id, al.ip_address, al.request_method, al.request_path,
               al.response_status, al.details, al.created_at,
               u.email AS reviewer_email,
               CONCAT(COALESCE(u.first_name, ''), ' ', COALESCE(u.last_name, '')) AS reviewer_name
        FROM audit_log al
        LEFT JOIN users u ON u.id = al.user_id
        {where}
        ORDER BY al.created_at DESC
        LIMIT %s OFFSET %s
    """
    _fallback_sql = f"""
        SELECT id, user_id, action, resource_type, resource_id, patient_id,
               ip_address, request_method, request_path, response_status,
               details, created_at
        FROM audit_log
        {where.replace('al.', '')}
        ORDER BY created_at DESC
        LIMIT %s OFFSET %s
    """
    try:
        with raf_cursor() as cur:
            cur.execute(_primary_sql, params)
            return cur.fetchall()
    except Exception as exc:
        _msg = str(exc)
        if "1054" in _msg or "Unknown column" in _msg:
            logger.warning(
                "query_audit_log: schema mismatch (migration 023 not applied?), "
                "falling back to bare audit_log query. Error: %s",
                exc,
            )
            fallback_params: list[Any] = list(params)
            with raf_cursor() as cur:
                cur.execute(_fallback_sql, fallback_params)
                return cur.fetchall()
        raise
