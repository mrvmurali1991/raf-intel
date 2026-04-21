"""
Auth domain package.

Re-exports from the flat services layer so that new code can import from
``app.services.auth`` while existing imports continue to work.

Domain responsibilities:
- JWT token creation and validation
- Password hashing and verification
- User session management
- Audit logging
- MFA flows
"""
from app.services.auth_service import (  # noqa: F401
    create_access_token,
    create_refresh_token,
    create_user,
    decode_refresh_token,
    decode_token,
    hash_password,
    log_audit,
    validate_password_strength,
    verify_password,
)

__all__ = [
    "create_access_token",
    "create_refresh_token",
    "decode_token",
    "decode_refresh_token",
    "hash_password",
    "verify_password",
    "validate_password_strength",
    "create_user",
    "log_audit",
]
