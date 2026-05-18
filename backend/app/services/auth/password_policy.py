"""
Password hashing, strength validation, history, and lockout helpers.

All password-related logic that was scattered in auth_service.py lives here.
"""
from __future__ import annotations

import logging
from typing import Any

from passlib.context import CryptContext

from app.db import raf_cursor

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Common-password blocklist (top-100 — rejected regardless of complexity)
# ---------------------------------------------------------------------------

_COMMON_PASSWORDS: frozenset[str] = frozenset(
    {
        "password", "123456", "12345678", "1234", "qwerty", "12345", "dragon",
        "pussy", "baseball", "football", "letmein", "monkey", "696969", "abc123",
        "mustang", "michael", "shadow", "master", "jennifer", "111111", "2000",
        "jordan", "superman", "harley", "1234567", "fuckme", "hunter", "fuckyou",
        "trustno1", "ranger", "batman", "test", "pass", "killer", "soccer",
        "hockey", "maggie", "iloveyou", "purple", "sunshine", "princess",
        "welcome", "123123", "654321", "qazwsx", "password1", "password123",
        "admin", "admin123", "root", "toor", "pass123", "test123", "guest",
        "changeme", "secret", "hello", "1111", "1234567890", "00000000",
        "password2", "qwerty123", "abc1234", "Login", "login", "default",
        "user", "letmein1", "welcome1", "monkey123", "dragon123", "master123",
        "sunshine1", "princess1", "baseball1", "football1", "soccer123",
        "hockey123", "liverpool", "chelsea", "arsenal", "rangers", "cowboys",
        "steelers", "yankees", "manchester", "barcelona", "madrid", "summer",
        "winter", "spring", "autumn", "access", "access123", "pass1", "pass12",
        "pass1234", "mypass", "mypassword", "temp", "temp123", "test1", "test12",
    }
)

# ---------------------------------------------------------------------------
# Passlib context
# ---------------------------------------------------------------------------

_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(plain: str) -> str:
    """Bcrypt-hash a plaintext password."""
    return _pwd_context.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    """Constant-time bcrypt verification."""
    return _pwd_context.verify(plain, hashed)


# ---------------------------------------------------------------------------
# Strength validation
# ---------------------------------------------------------------------------

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
# Password history
# ---------------------------------------------------------------------------

_PASSWORD_HISTORY_DEPTH = 5


def check_password_history(user_id: int, new_password: str) -> None:
    """Raise ValueError if new_password matches any of the last N stored hashes."""
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


def record_password_history(user_id: int, old_hash: str) -> None:
    """Store old_hash in password_history and prune beyond depth limit."""
    with raf_cursor() as cur:
        cur.execute(
            "INSERT INTO password_history (user_id, password_hash) VALUES (%s, %s)",
            (user_id, old_hash),
        )
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


# ---------------------------------------------------------------------------
# Public aliases matching the private names used inside auth_service.py
# so that the compat shim can re-export without renaming.
# ---------------------------------------------------------------------------
_check_password_history = check_password_history
_record_password_history = record_password_history
