"""
Authentication and authorization service for RAF Intelligence.

Handles:
- Password hashing with bcrypt via passlib
- JWT access and refresh tokens via PyJWT
- Session management stored in raf_intelligence DB
- Account lockout on repeated failures
- Permission checking (role-based with per-user overrides)
- Audit logging to audit_log table
- Auto-DDL for auth tables on first use
"""

from __future__ import annotations

import base64
import hashlib
import io
import json
import logging
import os
import secrets
import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import jwt
import pyotp
import qrcode
from passlib.context import CryptContext

from app.config import settings
from app.db import raf_cursor
from app.services.encryption_service import decrypt as _decrypt_field
from app.services.encryption_service import encrypt as _encrypt_field

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Password complexity
# ---------------------------------------------------------------------------

# Top-100 most common passwords – rejected regardless of length/character mix.
_COMMON_PASSWORDS: frozenset[str] = frozenset(
    {
        "password",
        "123456",
        "12345678",
        "1234",
        "qwerty",
        "12345",
        "dragon",
        "pussy",
        "baseball",
        "football",
        "letmein",
        "monkey",
        "696969",
        "abc123",
        "mustang",
        "michael",
        "shadow",
        "master",
        "jennifer",
        "111111",
        "2000",
        "jordan",
        "superman",
        "harley",
        "1234567",
        "fuckme",
        "hunter",
        "fuckyou",
        "trustno1",
        "ranger",
        "batman",
        "test",
        "pass",
        "killer",
        "soccer",
        "hockey",
        "maggie",
        "iloveyou",
        "purple",
        "sunshine",
        "princess",
        "welcome",
        "123123",
        "654321",
        "qazwsx",
        "password1",
        "password123",
        "admin",
        "admin123",
        "root",
        "toor",
        "pass123",
        "test123",
        "guest",
        "changeme",
        "secret",
        "hello",
        "1111",
        "1234567890",
        "00000000",
        "password2",
        "qwerty123",
        "abc1234",
        "Login",
        "login",
        "default",
        "user",
        "letmein1",
        "welcome1",
        "monkey123",
        "dragon123",
        "master123",
        "sunshine1",
        "princess1",
        "baseball1",
        "football1",
        "soccer123",
        "hockey123",
        "liverpool",
        "chelsea",
        "arsenal",
        "rangers",
        "cowboys",
        "steelers",
        "yankees",
        "manchester",
        "barcelona",
        "madrid",
        "summer",
        "winter",
        "spring",
        "autumn",
        "access",
        "access123",
        "pass1",
        "pass12",
        "pass1234",
        "mypass",
        "mypassword",
        "temp",
        "temp123",
        "test1",
        "test12",
    }
)


def validate_password_strength(password: str) -> tuple[bool, str]:
    """
    Validate password meets HIPAA-recommended complexity:
    - Minimum 12 characters
    - At least 1 uppercase letter
    - At least 1 lowercase letter
    - At least 1 digit
    - At least 1 special character (!@#$%^&*...)
    - Not a common password (check top 100)
    - Maximum 128 characters (prevent bcrypt DoS)
    Returns (is_valid, error_message)
    """
    if len(password) > 128:
        return False, "Password must not exceed 128 characters."
    if len(password) < 12:
        return False, "Password must be at least 12 characters long."
    if not any(c.isupper() for c in password):
        return False, "Password must contain at least one uppercase letter."
    if not any(c.islower() for c in password):
        return False, "Password must contain at least one lowercase letter."
    if not any(c.isdigit() for c in password):
        return False, "Password must contain at least one digit."
    special_chars = set("!@#$%^&*()_+-=[]{}|;':\",./<>?`~\\")
    if not any(c in special_chars for c in password):
        return (
            False,
            "Password must contain at least one special character (!@#$%^&* etc.).",
        )
    if password.lower() in _COMMON_PASSWORDS:
        return False, "Password is too common. Please choose a more unique password."
    return True, ""


# ---------------------------------------------------------------------------
# Password hashing
# ---------------------------------------------------------------------------

_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(plain: str) -> str:
    return _pwd_context.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    return _pwd_context.verify(plain, hashed)


# ---------------------------------------------------------------------------
# Token helpers
# ---------------------------------------------------------------------------


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _hash_token(token: str) -> str:
    """SHA-256 hash of a token for safe DB storage."""
    return hashlib.sha256(token.encode()).hexdigest()


def create_access_token(
    user_id: int,
    email: str,
    role: str,
    tenant_id: int | None,
    session_id: str,
) -> str:
    now = _utcnow()
    expire = now + timedelta(minutes=settings.access_token_expire_minutes)
    payload = {
        "sub": str(user_id),
        "email": email,
        "role": role,
        "tenant_id": tenant_id,
        "session_id": session_id,
        "iat": now,
        "exp": expire,
        "type": "access",
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def create_refresh_token(user_id: int, session_id: str) -> str:
    now = _utcnow()
    expire = now + timedelta(days=settings.refresh_token_expire_days)
    payload = {
        "sub": str(user_id),
        "session_id": session_id,
        "iat": now,
        "exp": expire,
        "type": "refresh",
    }
    return jwt.encode(
        payload, settings.jwt_refresh_secret, algorithm=settings.jwt_algorithm
    )


def _create_mfa_pending_token(user_id: int) -> str:
    """Short-lived token (5 min) issued after password check when MFA is required."""
    now = _utcnow()
    expire = now + timedelta(minutes=5)
    payload = {
        "sub": str(user_id),
        "iat": now,
        "exp": expire,
        "type": "mfa_pending",
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_token(token: str) -> dict[str, Any]:
    """Decode and validate an access (or mfa_pending) JWT. Raises jwt.PyJWTError on failure."""
    return jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])


def decode_refresh_token(token: str) -> dict[str, Any]:
    """Decode and validate a refresh JWT (signed with jwt_refresh_secret)."""
    return jwt.decode(
        token, settings.jwt_refresh_secret, algorithms=[settings.jwt_algorithm]
    )


# ---------------------------------------------------------------------------
# Centralized migrations — replaces auto-DDL
# ---------------------------------------------------------------------------

_tables_ensured = False  # kept for backward-compat; no longer used for DDL


def _ensure_tables() -> None:
    """One-time auth bootstrap after centralized migrations."""
    global _tables_ensured
    if _tables_ensured:
        return
    try:
        _seed_default_permissions()
    except Exception as exc:
        logger.warning("auth bootstrap: default permissions not seeded: %s", exc)
    try:
        _seed_dev_admin_user()
    except Exception as exc:
        logger.warning("auth bootstrap: dev admin seed skipped: %s", exc)
    _tables_ensured = True


def _seed_default_permissions() -> None:
    """Insert/backfill default role permissions idempotently."""
    with raf_cursor() as cur:
        default_perms = [
            # admin – full access
            ("admin", "patients", "read"),
            ("admin", "patients", "write"),
            ("admin", "patients", "delete"),
            ("admin", "raf", "read"),
            ("admin", "raf", "write"),
            ("admin", "analysis", "read"),
            ("admin", "analysis", "write"),
            ("admin", "suspects", "read"),
            ("admin", "suspects", "write"),
            ("admin", "reports", "read"),
            ("admin", "reports", "write"),
            ("admin", "audit", "read"),
            ("admin", "audit", "write"),
            ("admin", "providers", "read"),
            ("admin", "providers", "write"),
            ("admin", "claims", "read"),
            ("admin", "claims", "write"),
            ("admin", "fhir", "read"),
            ("admin", "fhir", "write"),
            ("admin", "submissions", "read"),
            ("admin", "submissions", "write"),
            ("admin", "jobs", "read"),
            ("admin", "jobs", "write"),
            ("admin", "webhooks", "read"),
            ("admin", "webhooks", "write"),
            ("admin", "documents", "read"),
            ("admin", "documents", "write"),
            ("admin", "worklist", "read"),
            ("admin", "worklist", "write"),
            ("admin", "worklist", "manage"),
            ("admin", "users", "read"),
            ("admin", "users", "write"),
            # manager – no user management
            ("manager", "patients", "read"),
            ("manager", "patients", "write"),
            ("manager", "raf", "read"),
            ("manager", "raf", "write"),
            ("manager", "analysis", "read"),
            ("manager", "analysis", "write"),
            ("manager", "suspects", "read"),
            ("manager", "suspects", "write"),
            ("manager", "reports", "read"),
            ("manager", "reports", "write"),
            ("manager", "audit", "read"),
            ("manager", "providers", "read"),
            ("manager", "providers", "write"),
            ("manager", "claims", "read"),
            ("manager", "claims", "write"),
            ("manager", "fhir", "read"),
            ("manager", "fhir", "write"),
            ("manager", "submissions", "read"),
            ("manager", "submissions", "write"),
            ("manager", "jobs", "read"),
            ("manager", "jobs", "write"),
            ("manager", "webhooks", "read"),
            ("manager", "webhooks", "write"),
            ("manager", "documents", "read"),
            ("manager", "documents", "write"),
            ("manager", "worklist", "read"),
            ("manager", "worklist", "write"),
            ("manager", "worklist", "manage"),
            # auditor – read-only + audit access
            ("auditor", "patients", "read"),
            ("auditor", "raf", "read"),
            ("auditor", "analysis", "read"),
            ("auditor", "suspects", "read"),
            ("auditor", "reports", "read"),
            ("auditor", "audit", "read"),
            ("auditor", "providers", "read"),
            ("auditor", "claims", "read"),
            ("auditor", "fhir", "read"),
            ("auditor", "submissions", "read"),
            ("auditor", "jobs", "read"),
            ("auditor", "webhooks", "read"),
            ("auditor", "documents", "read"),
            ("auditor", "worklist", "read"),
            # coder – worklist access + limited clinical read
            ("coder", "worklist", "read"),
            ("coder", "worklist", "write"),
            ("coder", "patients", "read"),
            ("coder", "raf", "read"),
            ("coder", "analysis", "read"),
            ("coder", "suspects", "read"),
            ("coder", "documents", "read"),
            ("coder", "documents", "write"),
            ("coder", "claims", "read"),
            ("coder", "providers", "read"),
            ("coder", "reports", "read"),
            # viewer – read-only clinical data
            ("viewer", "patients", "read"),
            ("viewer", "raf", "read"),
            ("viewer", "analysis", "read"),
            ("viewer", "suspects", "read"),
            ("viewer", "reports", "read"),
            ("viewer", "providers", "read"),
            ("viewer", "claims", "read"),
            ("viewer", "fhir", "read"),
            ("viewer", "submissions", "read"),
            ("viewer", "jobs", "read"),
            ("viewer", "webhooks", "read"),
        ]
        cur.executemany(
            "INSERT IGNORE INTO role_default_permissions (role, resource, action) VALUES (%s, %s, %s)",
            default_perms,
        )


def _seed_dev_admin_user() -> None:
    """Seed a local admin account for development environments only.

    Both gates must pass:
    1. app_env == "development"
    2. allow_dev_admin_seed == True (explicit opt-in, defaults False)
    Production instances therefore never seed a dev admin even if APP_ENV is
    accidentally omitted and falls through to the "production" default.
    """
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
    # User INSERT and any initial permission rows share a single cursor so that
    # both writes are committed (or rolled back) atomically.  A crash between a
    # separate user-insert cursor and a permissions-insert cursor would leave
    # the new account with no permissions, blocking every subsequent login.
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


def _attach_must_change_password(user: dict[str, Any]) -> dict[str, Any]:
    """
    Compute must_change_password and attach it to the user dict (mutates in-place).
    True when password_changed_at is NULL or equals created_at, meaning the user
    has never changed their password from the initial value set by an admin.
    """
    pca = user.get("password_changed_at")
    # must_change_password is True when password_changed_at IS NULL — meaning
    # the user has never changed their password from the initial admin-set value.
    user["must_change_password"] = pca is None
    return user


def get_user(user_id: int) -> dict[str, Any] | None:
    _ensure_tables()
    with raf_cursor() as cur:
        cur.execute(
            """
            SELECT id, email, full_name, role, tenant_id, is_active, avatar_url,
                   failed_login_attempts, locked_until, last_login_at,
                   password_changed_at, created_at, updated_at,
                   mfa_enabled, mfa_secret, mfa_recovery_codes, provider_id
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
# Password history helpers
# ---------------------------------------------------------------------------

_PASSWORD_HISTORY_DEPTH = 5  # number of previous hashes to check


def _check_password_history(user_id: int, new_password: str) -> None:
    """Raise ValueError if new_password matches any of the last N stored hashes.

    Compares against the most recent ``_PASSWORD_HISTORY_DEPTH`` entries in the
    ``password_history`` table.  Does nothing (silently passes) when the table
    is empty or has fewer entries than the depth limit.
    """
    with raf_cursor() as cur:
        cur.execute(
            """
            SELECT password_hash FROM password_history
            WHERE user_id = %s
            ORDER BY created_at DESC
            LIMIT %s
            """,
            (user_id, _PASSWORD_HISTORY_DEPTH),
        )
        rows = cur.fetchall()
    for r in rows:
        if verify_password(new_password, r["password_hash"]):
            raise ValueError(
                f"Cannot reuse recent passwords. "
                f"Please choose a password not used in your last {_PASSWORD_HISTORY_DEPTH} changes."
            )


def _record_password_history(user_id: int, old_hash: str) -> None:
    """Store old_hash in password_history and prune entries beyond the depth limit."""
    with raf_cursor() as cur:
        cur.execute(
            "INSERT INTO password_history (user_id, password_hash) VALUES (%s, %s)",
            (user_id, old_hash),
        )
        # Keep only the most recent N entries to bound table growth
        cur.execute(
            """
            DELETE FROM password_history
            WHERE user_id = %s
              AND id NOT IN (
                  SELECT id FROM (
                      SELECT id FROM password_history
                      WHERE user_id = %s
                      ORDER BY created_at DESC
                      LIMIT %s
                  ) AS _keep
              )
            """,
            (user_id, user_id, _PASSWORD_HISTORY_DEPTH),
        )


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
    """Create a password reset token stored (hashed) on the user record.

    Also sends a password-reset email to the user with a link that expires in
    30 minutes.  The token itself is valid for 1 hour in the DB; the email
    copy states 30 minutes to encourage prompt use.
    """
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
# Session management
# ---------------------------------------------------------------------------


def create_session(
    user_id: int,
    access_token: str,
    refresh_token: str,
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> str:
    """Persist a new session and return the session_id."""
    _ensure_tables()
    session_id = str(uuid.uuid4())
    session_token_hash = _hash_token(access_token)
    refresh_token_hash = _hash_token(refresh_token)
    expires_at = _utcnow() + timedelta(days=settings.refresh_token_expire_days)
    with raf_cursor() as cur:
        cur.execute(
            """
            INSERT INTO user_sessions
                (session_id, user_id, session_token_hash, refresh_token_hash,
                 ip_address, user_agent, expires_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            (
                session_id,
                user_id,
                session_token_hash,
                refresh_token_hash,
                ip_address or "unknown",
                user_agent,
                expires_at.strftime("%Y-%m-%d %H:%M:%S"),
            ),
        )
    return session_id


def validate_session(session_id: str) -> dict[str, Any] | None:
    """Return session row if active and not expired, else None.

    HIPAA idle timeout: if last_activity_at is older than settings.idle_timeout_minutes
    the session is automatically revoked and None is returned so the caller treats it
    as an invalid/expired session.
    """
    _ensure_tables()
    with raf_cursor() as cur:
        cur.execute(
            """
            SELECT id, session_id, user_id, is_revoked, expires_at, last_activity_at
            FROM user_sessions
            WHERE session_id = %s AND is_revoked = 0
            """,
            (session_id,),
        )
        row = cur.fetchone()
    if not row:
        return None
    expires = row["expires_at"]
    if isinstance(expires, str):
        expires = datetime.fromisoformat(expires)
    if expires.replace(tzinfo=timezone.utc) < _utcnow():
        return None

    # HIPAA idle timeout: revoke session if inactive too long
    last_activity = row.get("last_activity_at")
    if last_activity is not None:
        if isinstance(last_activity, str):
            last_activity = datetime.fromisoformat(last_activity)
        idle_seconds = (
            _utcnow() - last_activity.replace(tzinfo=timezone.utc)
        ).total_seconds()
        if idle_seconds > settings.idle_timeout_minutes * 60:
            revoke_session(session_id)
            logger.info(
                "Session %s revoked due to idle timeout (%.0f s idle, limit %d min)",
                session_id,
                idle_seconds,
                settings.idle_timeout_minutes,
            )
            return None

    # Touch last_used_at and last_activity_at on every successful validation
    with raf_cursor() as cur:
        cur.execute(
            "UPDATE user_sessions SET last_used_at = NOW(), last_activity_at = NOW() WHERE session_id = %s",
            (session_id,),
        )
    return row


def revoke_session(session_id: str) -> None:
    _ensure_tables()
    with raf_cursor() as cur:
        cur.execute(
            "UPDATE user_sessions SET is_revoked = 1 WHERE session_id = %s",
            (session_id,),
        )


def revoke_all_sessions(user_id: int) -> None:
    _ensure_tables()
    with raf_cursor() as cur:
        cur.execute(
            "UPDATE user_sessions SET is_revoked = 1 WHERE user_id = %s",
            (user_id,),
        )


def list_sessions(user_id: int) -> list[dict[str, Any]]:
    _ensure_tables()
    with raf_cursor() as cur:
        cur.execute(
            """
            SELECT id, session_id, ip_address, user_agent, created_at, last_used_at, expires_at, is_revoked
            FROM user_sessions
            WHERE user_id = %s AND is_revoked = 0
            ORDER BY last_used_at DESC
            """,
            (user_id,),
        )
        return cur.fetchall()


# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------


def authenticate_user(
    email: str,
    password: str,
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> dict[str, Any]:
    """
    Authenticate by email + password.

    Returns a dict with access_token, refresh_token, token_type, and user.
    Raises ValueError with user-safe messages on failure.
    """
    _ensure_tables()

    with raf_cursor() as cur:
        cur.execute(
            """
            SELECT id, email, full_name, role, tenant_id, is_active, avatar_url,
                   failed_login_attempts, locked_until, password_hash,
                   password_changed_at, created_at, mfa_enabled, provider_id
            FROM users WHERE email = %s
            """,
            (email,),
        )
        user = cur.fetchone()
    if user:
        _attach_must_change_password(user)

    if not user:
        # Run dummy hash to prevent timing attack (user enumeration)
        _pwd_context.verify(
            "dummy", "$2b$12$LJ3m4ys3Lgxmx4XRSG5H8OjG5OhHWLBDhtNBCjw.XMJkRiQHJKo6"
        )
        raise ValueError("Invalid email or password.")

    if not user["is_active"]:
        raise ValueError("Account is inactive. Contact your administrator.")

    # Check lockout
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

    # Verify password
    if not verify_password(password, user["password_hash"]):
        # Increment failure counter
        attempts = user["failed_login_attempts"] + 1
        if attempts >= settings.max_failed_logins:
            lock_until = _utcnow() + timedelta(
                minutes=settings.lockout_duration_minutes
            )
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

    # Success – reset counters, update last_login_at
    with raf_cursor() as cur:
        cur.execute(
            """
            UPDATE users
            SET failed_login_attempts = 0, locked_until = NULL, last_login_at = NOW()
            WHERE id = %s
            """,
            (user["id"],),
        )

    # MFA check — if enabled, issue a short-lived mfa_pending token instead of a full session.
    # The client must POST to /api/auth/mfa/verify with this token + TOTP code.
    if user.get("mfa_enabled"):
        mfa_token = _create_mfa_pending_token(user["id"])
        return {
            "mfa_required": True,
            "mfa_token": mfa_token,
            "token_type": "bearer",
        }

    return _issue_tokens(user, ip_address=ip_address, user_agent=user_agent)


def _issue_tokens(
    user: dict[str, Any],
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> dict[str, Any]:
    """Create session, access token, and refresh token for a fully-authenticated user."""
    session_id = str(uuid.uuid4())

    access_token = create_access_token(
        user_id=user["id"],
        email=user["email"],
        role=user["role"],
        tenant_id=user["tenant_id"],
        session_id=session_id,
    )
    refresh_token = create_refresh_token(user_id=user["id"], session_id=session_id)

    session_token_hash = _hash_token(access_token)
    refresh_token_hash = _hash_token(refresh_token)
    expires_at = _utcnow() + timedelta(days=settings.refresh_token_expire_days)
    with raf_cursor() as cur:
        cur.execute(
            """
            INSERT INTO user_sessions
                (session_id, user_id, session_token_hash, refresh_token_hash,
                 ip_address, user_agent, expires_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            (
                session_id,
                user["id"],
                session_token_hash,
                refresh_token_hash,
                ip_address or "unknown",
                user_agent,
                expires_at.strftime("%Y-%m-%d %H:%M:%S"),
            ),
        )

    user_info = {
        "id": user["id"],
        "email": user["email"],
        "full_name": user["full_name"],
        "role": user["role"],
        "tenant_id": user["tenant_id"],
        "avatar_url": user["avatar_url"],
        "provider_id": user.get("provider_id"),
        "must_change_password": user.get("must_change_password", False),
    }

    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
        "expires_in": settings.access_token_expire_minutes * 60,
        "user": user_info,
    }


# ---------------------------------------------------------------------------
# Embed token exchange (OpenEMR iframe handshake)
#
# OpenEMR (or any trusted embedding host) mints a short-lived HMAC-signed JWT
# with a shared secret (OPENEMR_EMBED_SECRET) and hands it to the iframe via
# URL. The iframe POSTs it to /api/auth/embed/exchange which verifies and
# trades it for a real RAF access + refresh token pair scoped to the tenant.
#
# Payload contract:
#   {
#     "sub": "<raf-user-email>",   # RAF user to impersonate
#     "pid": 12345,                 # patient id (informational — not enforced here)
#     "tenant_id": "demo-tenant",   # optional; overrides openemr_embed_default_tenant_id
#     "iat": ..., "exp": ...,       # required, TTL enforced ≤ 10 min
#     "type": "embed"
#   }
# ---------------------------------------------------------------------------


def _embed_signing_secret() -> str:
    """Return the HMAC secret used for embed tokens.

    In production OPENEMR_EMBED_SECRET must be set explicitly. In development
    we fall back to jwt_secret + '_embed' so local demos work without extra
    configuration.
    """
    secret = settings.openemr_embed_secret
    if secret:
        return secret
    if _is_production():
        raise ValueError(
            "OPENEMR_EMBED_SECRET is not configured — embed exchange is disabled."
        )
    # Dev-only fallback; deterministic so embed tokens minted by the admin
    # route can be verified by the exchange route within one process.
    return settings.jwt_secret + "_embed"


def _is_production() -> bool:
    return settings.app_env == "production"


def create_embed_token(
    user_email: str,
    pid: int,
    tenant_id: str | None = None,
    ttl_seconds: int = 300,
) -> str:
    """Mint a short-lived embed JWT. Used by tests and admin tooling.

    In real deployments OpenEMR mints these tokens itself using the shared
    secret; this helper exists so RAF ships a working demo harness.
    """
    now = _utcnow()
    payload: dict[str, Any] = {
        "sub": user_email,
        "pid": int(pid),
        "iat": now,
        "exp": now + timedelta(seconds=max(30, min(ttl_seconds, 600))),
        "type": "embed",
    }
    if tenant_id:
        payload["tenant_id"] = tenant_id
    return jwt.encode(
        payload, _embed_signing_secret(), algorithm=settings.jwt_algorithm
    )


def authenticate_embed_token(
    embed_token: str,
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> dict[str, Any]:
    """Verify an embed JWT and issue a scoped RAF session.

    The issued access token uses the RAF user's role and tenant. The refresh
    token follows the same rotation model as regular logins, so the iframe
    can silently refresh while it stays open.
    """
    _ensure_tables()
    secret = _embed_signing_secret()
    try:
        payload = jwt.decode(
            embed_token, secret, algorithms=[settings.jwt_algorithm]
        )
    except jwt.ExpiredSignatureError:
        raise ValueError("Embed token has expired.")
    except jwt.PyJWTError:
        raise ValueError("Invalid embed token.")

    if payload.get("type") != "embed":
        raise ValueError("Token is not an embed token.")

    email = payload.get("sub")
    if not isinstance(email, str) or not email:
        raise ValueError("Embed token is missing sub (RAF user email).")

    user = get_user_by_email(email)
    if not user or not user.get("is_active"):
        raise ValueError("Embed token references an unknown or inactive user.")

    # Tenant binding — prefer the tenant_id baked into the token, fall back
    # to the deployment default, and finally to the user's own tenant. We
    # refuse if the chosen tenant doesn't match the user's.
    token_tenant = payload.get("tenant_id") or settings.openemr_embed_default_tenant_id
    if token_tenant and str(token_tenant) != str(user["tenant_id"]):
        raise ValueError(
            "Embed tenant_id does not match the target user's tenant."
        )

    # Issue tokens. We override the access-token TTL so the iframe session
    # is shorter than the regular app session.
    session_id = str(uuid.uuid4())
    now = _utcnow()
    access_exp = now + timedelta(
        minutes=settings.embed_access_token_expire_minutes
    )
    access_payload = {
        "sub": str(user["id"]),
        "email": user["email"],
        "role": user["role"],
        "tenant_id": user["tenant_id"],
        "session_id": session_id,
        "iat": now,
        "exp": access_exp,
        "type": "access",
        "embed": True,
        "embed_pid": int(payload.get("pid") or 0) or None,
    }
    access_token = jwt.encode(
        access_payload, settings.jwt_secret, algorithm=settings.jwt_algorithm
    )
    refresh_token = create_refresh_token(user_id=user["id"], session_id=session_id)

    session_token_hash = _hash_token(access_token)
    refresh_token_hash = _hash_token(refresh_token)
    expires_at = now + timedelta(days=settings.refresh_token_expire_days)
    with raf_cursor() as cur:
        cur.execute(
            """
            INSERT INTO user_sessions
                (session_id, user_id, session_token_hash, refresh_token_hash,
                 ip_address, user_agent, expires_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            (
                session_id,
                user["id"],
                session_token_hash,
                refresh_token_hash,
                ip_address or "embed",
                (user_agent or "openemr-embed")[:255],
                expires_at.strftime("%Y-%m-%d %H:%M:%S"),
            ),
        )

    user_info = {
        "id": user["id"],
        "email": user["email"],
        "full_name": user["full_name"],
        "role": user["role"],
        "tenant_id": user["tenant_id"],
        "avatar_url": user.get("avatar_url"),
        "must_change_password": user.get("must_change_password", False),
    }

    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
        "expires_in": settings.embed_access_token_expire_minutes * 60,
        "user": user_info,
        "embed_pid": int(payload.get("pid") or 0) or None,
    }


def refresh_access_token(refresh_token: str) -> dict[str, Any]:
    """Rotate refresh token on every use.

    Security properties:
    - Uses a separate signing key (jwt_refresh_secret) from access tokens.
    - Each call issues a NEW refresh token and revokes the old one (rotation).
    - Hash mismatch on a non-revoked session indicates a previously-rotated
      token is being replayed: all user sessions are immediately terminated.
    """
    _ensure_tables()

    # Decode using the dedicated refresh-token signing key.
    try:
        payload = decode_refresh_token(refresh_token)
    except jwt.PyJWTError:
        raise ValueError("Invalid or expired refresh token.")

    if payload.get("type") != "refresh":
        raise ValueError("Not a refresh token.")

    user_id = int(payload["sub"])
    session_id = payload["session_id"]
    incoming_hash = _hash_token(refresh_token)

    # Fetch full session row so we can inspect is_revoked and the stored hash.
    with raf_cursor() as cur:
        cur.execute(
            """
            SELECT id, session_id, user_id, refresh_token_hash, is_revoked, expires_at
            FROM user_sessions
            WHERE session_id = %s
            """,
            (session_id,),
        )
        session = cur.fetchone()

    if not session:
        raise ValueError("Invalid refresh token.")

    if session["is_revoked"]:
        # A revoked session's token was just presented — definite replay / token theft.
        revoke_all_sessions(user_id)
        raise ValueError(
            "Revoked refresh token reused — possible token theft. "
            "All sessions have been terminated. Please log in again."
        )

    # Belt-and-suspenders expiry check beyond JWT exp claim.
    expires = session["expires_at"]
    if isinstance(expires, str):
        expires = datetime.fromisoformat(expires)
    if expires.replace(tzinfo=timezone.utc) < _utcnow():
        raise ValueError("Refresh token has expired.")

    if session["refresh_token_hash"] != incoming_hash:
        # Hash mismatch — check if the previous token hash matches (grace window
        # for concurrent refresh races common in SPAs / React strict-mode).
        prev_hash = session.get("prev_refresh_token_hash")
        updated = session.get("updated_at")
        grace_ok = False
        if prev_hash and prev_hash == incoming_hash and updated:
            if isinstance(updated, str):
                updated = datetime.fromisoformat(updated)
            age = (_utcnow() - updated.replace(tzinfo=timezone.utc)).total_seconds()
            if age < 30:  # 30-second grace window
                grace_ok = True
                logger.info("Refresh token race resolved via grace window for user %s", user_id)

        if not grace_ok:
            logger.warning(
                "Refresh token hash mismatch for user %s session %s — "
                "possible concurrent refresh race (not revoking sessions)",
                user_id, session_id,
            )
            raise ValueError("Refresh token expired or already used. Please log in again.")

    user = get_user(user_id)
    if not user or not user["is_active"]:
        raise ValueError("User account is inactive.")

    # Generate new token pair.
    new_access_token = create_access_token(
        user_id=user["id"],
        email=user["email"],
        role=user["role"],
        tenant_id=user["tenant_id"],
        session_id=session_id,
    )
    new_refresh_token = create_refresh_token(user_id=user["id"], session_id=session_id)

    new_access_hash = _hash_token(new_access_token)
    new_refresh_hash = _hash_token(new_refresh_token)
    new_expires_at = _utcnow() + timedelta(days=settings.refresh_token_expire_days)

    # Rotate: replace both hashes in the existing session row atomically.
    with raf_cursor() as cur:
        cur.execute(
            """
            UPDATE user_sessions
            SET prev_refresh_token_hash = refresh_token_hash,
                session_token_hash = %s,
                refresh_token_hash  = %s,
                expires_at          = %s,
                last_used_at        = NOW(),
                last_activity_at    = NOW()
            WHERE session_id = %s
            """,
            (
                new_access_hash,
                new_refresh_hash,
                new_expires_at.strftime("%Y-%m-%d %H:%M:%S"),
                session_id,
            ),
        )

    return {
        "access_token": new_access_token,
        "refresh_token": new_refresh_token,
        "token_type": "bearer",
        "expires_in": settings.access_token_expire_minutes * 60,
    }


# ---------------------------------------------------------------------------
# MFA (TOTP) management
# ---------------------------------------------------------------------------


def enable_mfa(user_id: int) -> dict[str, Any]:
    """Generate a TOTP secret and QR code for the user.

    The secret is stored immediately but MFA is NOT activated until the user
    verifies with a valid TOTP code via verify_and_activate_mfa().
    Returns the secret, a base64-encoded QR code PNG, the provisioning URI,
    and 10 one-time recovery codes.
    """
    _ensure_tables()
    user = get_user(user_id)
    if not user:
        raise ValueError("User not found.")

    secret = pyotp.random_base32()
    totp = pyotp.TOTP(secret)
    provisioning_uri = totp.provisioning_uri(
        name=user["email"],
        issuer_name="RAF Intelligence",
    )

    # Generate QR code as a base64-encoded PNG.
    qr = qrcode.make(provisioning_uri)
    buffer = io.BytesIO()
    qr.save(buffer, format="PNG")
    qr_base64 = base64.b64encode(buffer.getvalue()).decode()

    # Ten 8-character alphanumeric recovery codes.
    recovery_codes = [pyotp.random_base32()[:8].upper() for _ in range(10)]

    # Hash each recovery code before storage — plaintext codes are returned to
    # the user once and never persisted.  We use the same bcrypt context as
    # password hashing so the work factor matches the security policy.
    hashed_recovery_codes = [hash_password(code) for code in recovery_codes]

    # Persist secret (encrypted) + hashed recovery codes; MFA remains disabled until verified.
    encrypted_secret = _encrypt_field(secret)
    with raf_cursor() as cur:
        cur.execute(
            "UPDATE users SET mfa_secret = %s, mfa_recovery_codes = %s WHERE id = %s",
            (encrypted_secret, json.dumps(hashed_recovery_codes), user_id),
        )

    return {
        "qr_code": f"data:image/png;base64,{qr_base64}",
        "provisioning_uri": provisioning_uri,
        # Plaintext codes are shown to the user exactly once — they are NOT
        # stored in the database (only bcrypt hashes are).
        "recovery_codes": recovery_codes,
    }


def verify_and_activate_mfa(user_id: int, totp_code: str) -> bool:
    """Verify a TOTP code and flip mfa_enabled = 1 if valid.

    Returns True on success, False if the code is invalid or no secret is stored.
    On successful activation also sends a confirmation email to the user.
    """
    _ensure_tables()
    with raf_cursor() as cur:
        cur.execute("SELECT mfa_secret, email FROM users WHERE id = %s", (user_id,))
        row = cur.fetchone()
    if not row or not row["mfa_secret"]:
        return False
    try:
        plain_secret = _decrypt_field(row["mfa_secret"])
    except Exception:
        logger.error("Failed to decrypt MFA secret for user %s", user_id)
        return False
    totp = pyotp.TOTP(plain_secret)
    if totp.verify(totp_code, valid_window=1):
        with raf_cursor() as cur:
            cur.execute("UPDATE users SET mfa_enabled = 1 WHERE id = %s", (user_id,))
        from app.services import email_service

        email_service.send_mfa_enabled(row["email"])
        return True
    return False


def verify_mfa_code(user_id: int, code: str) -> bool:
    """Verify a TOTP code or a one-time recovery code.

    Recovery codes are consumed on use (removed from the stored list).
    Returns True on success, False on failure.
    """
    _ensure_tables()
    with raf_cursor() as cur:
        cur.execute(
            "SELECT mfa_secret, mfa_recovery_codes FROM users WHERE id = %s",
            (user_id,),
        )
        row = cur.fetchone()
    if not row or not row["mfa_secret"]:
        return False

    # Try TOTP first.
    try:
        plain_secret = _decrypt_field(row["mfa_secret"])
    except Exception:
        logger.error("Failed to decrypt MFA secret for user %s", user_id)
        return False
    totp = pyotp.TOTP(plain_secret)
    if totp.verify(code, valid_window=1):
        return True

    # Try recovery codes.
    # Codes generated after the hashing migration are stored as bcrypt hashes;
    # legacy plaintext codes (from before the migration) are handled by the
    # plain string fallback so existing users are not locked out.
    raw = row.get("mfa_recovery_codes")
    stored_codes: list[str] = json.loads(raw) if raw else []
    code_upper = code.upper()

    matched_index: int | None = None
    for i, stored in enumerate(stored_codes):
        # Hashed codes start with the bcrypt identifier "$2b$" / "$2a$".
        if stored.startswith("$2"):
            # verify_password() is constant-time via passlib; short-circuit
            # only after a definitive match to avoid timing leaks.
            if verify_password(code_upper, stored):
                matched_index = i
                break
        else:
            # Legacy plaintext recovery code detected — reject and force
            # the user to re-enroll MFA so codes are stored hashed.
            logger.warning(
                "Rejecting plaintext MFA recovery code for user %s. "
                "User must re-enroll MFA to generate hashed codes.",
                user_id,
            )
            continue

    if matched_index is not None:
        stored_codes.pop(matched_index)
        with raf_cursor() as cur:
            cur.execute(
                "UPDATE users SET mfa_recovery_codes = %s WHERE id = %s",
                (json.dumps(stored_codes), user_id),
            )
        return True

    return False


def disable_mfa(user_id: int) -> None:
    """Disable MFA and clear stored secret / recovery codes."""
    _ensure_tables()
    with raf_cursor() as cur:
        cur.execute(
            """
            UPDATE users
            SET mfa_enabled = 0, mfa_secret = NULL, mfa_recovery_codes = NULL
            WHERE id = %s
            """,
            (user_id,),
        )


def complete_mfa_login(
    mfa_token: str,
    totp_code: str,
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> dict[str, Any]:
    """Exchange an mfa_pending token + TOTP code for a full session.

    Raises ValueError if the mfa_token is invalid/expired or the TOTP code
    is wrong.
    """
    _ensure_tables()
    try:
        payload = decode_token(mfa_token)
    except jwt.PyJWTError:
        raise ValueError("Invalid or expired MFA token.")

    if payload.get("type") != "mfa_pending":
        raise ValueError("Not an MFA pending token.")

    user_id = int(payload["sub"])
    user = get_user(user_id)
    if not user or not user["is_active"]:
        raise ValueError("User account is inactive.")

    if not verify_mfa_code(user_id, totp_code):
        raise ValueError("Invalid MFA code.")

    return _issue_tokens(user, ip_address=ip_address, user_agent=user_agent)


# ---------------------------------------------------------------------------
# Permissions
# ---------------------------------------------------------------------------


def get_user_permissions(user_id: int) -> list[dict[str, Any]]:
    """
    Return effective permissions for a user:
    role defaults merged with per-user overrides.
    """
    _ensure_tables()
    user = get_user(user_id)
    if not user:
        return []
    role = user["role"]

    with raf_cursor() as cur:
        # Role defaults
        cur.execute(
            "SELECT resource, action, 1 AS granted FROM role_default_permissions WHERE role = %s",
            (role,),
        )
        role_perms = {(r["resource"], r["action"]): True for r in cur.fetchall()}

        # Per-user overrides
        cur.execute(
            "SELECT resource, action, granted FROM user_permissions WHERE user_id = %s",
            (user_id,),
        )
        for r in cur.fetchall():
            role_perms[(r["resource"], r["action"])] = bool(r["granted"])

    return [
        {"resource": res, "action": act, "granted": granted}
        for (res, act), granted in role_perms.items()
    ]


def check_permission(user_id: int, resource: str, action: str) -> bool:
    """Return True if user has the given resource+action permission."""
    _ensure_tables()
    user = get_user(user_id)
    if not user:
        return False

    # admin role bypasses permission checks
    if user["role"] == "admin":
        return True

    with raf_cursor() as cur:
        # Check explicit user-level override first
        cur.execute(
            "SELECT granted FROM user_permissions WHERE user_id = %s AND resource = %s AND action = %s",
            (user_id, resource, action),
        )
        override = cur.fetchone()
        if override is not None:
            return bool(override["granted"])

        # Fall back to role default
        cur.execute(
            """
            SELECT COUNT(*) AS cnt FROM role_default_permissions
            WHERE role = %s AND resource = %s AND action = %s
            """,
            (user["role"], resource, action),
        )
        row = cur.fetchone()
        return bool(row and row["cnt"] > 0)


def set_user_permissions(user_id: int, permissions: list[dict[str, Any]]) -> None:
    """
    Replace all per-user permission overrides.
    Each item: {"resource": str, "action": str, "granted": bool}
    """
    _ensure_tables()
    with raf_cursor() as cur:
        cur.execute("DELETE FROM user_permissions WHERE user_id = %s", (user_id,))
        for perm in permissions:
            cur.execute(
                """
                INSERT INTO user_permissions (user_id, resource, action, granted)
                VALUES (%s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE granted = VALUES(granted)
                """,
                (
                    user_id,
                    perm["resource"],
                    perm["action"],
                    1 if perm.get("granted", True) else 0,
                ),
            )


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
        # HIPAA: Audit log failure is a compliance violation
        # Log at CRITICAL level so alerting systems can pick it up
        logger.critical(
            "AUDIT LOG FAILURE - HIPAA VIOLATION: action=%s resource=%s user=%s error=%s",
            action,
            resource_type,
            user_id,
            exc,
        )
        if settings.app_env != "development":
            # In production, audit failures should alert but not block the request
            # (blocking could cause availability issues, which is also a HIPAA concern)
            # Instead, write to a fallback file-based audit log
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
    # Extended filter params (migration 023 adds reviewed_by_user_id columns)
    actor_user_id: int | None = None,
    action_type: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
) -> list[dict[str, Any]]:
    """Query the audit_log table with optional filters.

    ``actor_user_id`` is a clearer alias for ``user_id`` (who performed the
    action).  ``action_type`` is an alias for ``action``.  ``date_from`` /
    ``date_to`` accept ``datetime.date`` objects and are inclusive.

    The response rows include ``reviewer_email`` (joined from ``users``) so the
    frontend can display "accepted by Dr. Jones" without a second round-trip.

    If the ``reviewed_by_user_id`` column has not yet been added (migration 023
    not applied), the query degrades gracefully: a WARNING is logged and results
    are returned without that filter applied.
    """
    _ensure_tables()

    # Resolve aliases — explicit params win over legacy names
    effective_user_id: int | None = actor_user_id if actor_user_id is not None else user_id
    effective_action: str | None = action_type if action_type else action

    # Convert date_from / date_to to datetime strings if supplied
    if date_from is not None and start_date is None:
        start_date = datetime(date_from.year, date_from.month, date_from.day, 0, 0, 0)
    if date_to is not None and end_date is None:
        end_date = datetime(date_to.year, date_to.month, date_to.day, 23, 59, 59)

    conditions: list[str] = []
    params: list[Any] = []

    # Restrict to users in the caller's tenant (audit_log has no tenant_id column)
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

    # Primary query — includes reviewer_email / reviewer_name via users JOIN.
    # If migration 023 hasn't run yet and a schema mismatch causes an
    # "Unknown column" error (MySQL errno 1054), fall back to the bare
    # audit_log query so the endpoint keeps working.
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
        # MySQL errno 1054 = ER_BAD_FIELD_ERROR (Unknown column).
        # Any column-schema mismatch from a pending migration falls here.
        _msg = str(exc)
        if "1054" in _msg or "Unknown column" in _msg:
            logger.warning(
                "query_audit_log: schema mismatch (migration 023 not applied?), "
                "falling back to bare audit_log query. Error: %s",
                exc,
            )
            # Strip the al. table alias since the fallback hits audit_log directly
            fallback_params: list[Any] = [
                p for p in params
            ]
            with raf_cursor() as cur:
                cur.execute(_fallback_sql, fallback_params)
                return cur.fetchall()
        raise
