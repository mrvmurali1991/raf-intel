"""
TOTP-based MFA: enable, verify-and-activate, verify code, disable, complete login.
"""
from __future__ import annotations

import base64
import io
import json
import logging
from typing import Any

import pyotp
import qrcode

from app.db import raf_cursor
from app.services.encryption_service import decrypt as _decrypt_field
from app.services.encryption_service import encrypt as _encrypt_field
from app.services.auth.password_policy import hash_password, verify_password
from app.services.auth.tokens import _create_mfa_pending_token

logger = logging.getLogger(__name__)


def enable_mfa(user_id: int, get_user_fn: Any) -> dict[str, Any]:
    """Generate a TOTP secret and QR code for the user.

    The secret is stored immediately but MFA is NOT activated until the user
    verifies with a valid TOTP code via verify_and_activate_mfa().

    Parameters
    ----------
    get_user_fn:
        Callable(user_id) -> user dict | None  (injected to avoid circular import)
    """
    user = get_user_fn(user_id)
    if not user:
        raise ValueError("User not found.")

    secret = pyotp.random_base32()
    totp = pyotp.TOTP(secret)
    provisioning_uri = totp.provisioning_uri(
        name=user["email"],
        issuer_name="RAF Intelligence",
    )

    qr = qrcode.make(provisioning_uri)
    buffer = io.BytesIO()
    qr.save(buffer, format="PNG")
    qr_base64 = base64.b64encode(buffer.getvalue()).decode()

    recovery_codes = [pyotp.random_base32()[:8].upper() for _ in range(10)]
    hashed_recovery_codes = [hash_password(code) for code in recovery_codes]

    encrypted_secret = _encrypt_field(secret)
    with raf_cursor() as cur:
        cur.execute(
            "UPDATE users SET mfa_secret = %s, mfa_recovery_codes = %s WHERE id = %s",
            (encrypted_secret, json.dumps(hashed_recovery_codes), user_id),
        )

    return {
        "qr_code": f"data:image/png;base64,{qr_base64}",
        "provisioning_uri": provisioning_uri,
        "recovery_codes": recovery_codes,
    }


def verify_and_activate_mfa(user_id: int, totp_code: str) -> bool:
    """Verify a TOTP code and flip mfa_enabled = 1 if valid.

    Returns True on success, False if the code is invalid or no secret is stored.
    """
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
    with raf_cursor() as cur:
        cur.execute(
            "SELECT mfa_secret, mfa_recovery_codes FROM users WHERE id = %s",
            (user_id,),
        )
        row = cur.fetchone()
    if not row or not row["mfa_secret"]:
        return False

    try:
        plain_secret = _decrypt_field(row["mfa_secret"])
    except Exception:
        logger.error("Failed to decrypt MFA secret for user %s", user_id)
        return False
    totp = pyotp.TOTP(plain_secret)
    if totp.verify(code, valid_window=1):
        return True

    raw = row.get("mfa_recovery_codes")
    stored_codes: list[str] = json.loads(raw) if raw else []
    code_upper = code.upper()

    matched_index: int | None = None
    for i, stored in enumerate(stored_codes):
        if stored.startswith("$2"):
            if verify_password(code_upper, stored):
                matched_index = i
                break
        else:
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
    get_user_fn: Any,
    issue_tokens_fn: Any,
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> dict[str, Any]:
    """Exchange an mfa_pending token + TOTP code for a full session.

    Parameters
    ----------
    get_user_fn:
        Callable(user_id) -> user dict | None
    issue_tokens_fn:
        Callable(user, ip_address, user_agent) -> token dict
    """
    import jwt as _jwt
    from app.services.auth.tokens import decode_token

    try:
        payload = decode_token(mfa_token)
    except _jwt.PyJWTError:
        raise ValueError("Invalid or expired MFA token.")

    if payload.get("type") != "mfa_pending":
        raise ValueError("Not an MFA pending token.")

    user_id = int(payload["sub"])
    user = get_user_fn(user_id)
    if not user or not user["is_active"]:
        raise ValueError("User account is inactive.")

    if not verify_mfa_code(user_id, totp_code):
        raise ValueError("Invalid MFA code.")

    return issue_tokens_fn(user, ip_address=ip_address, user_agent=user_agent)
