"""
Auth domain package — re-exports the full public surface of auth_service.py
so that both old-style and new-style imports work:

    from app.services.auth_service import create_access_token   # legacy shim
    from app.services.auth import create_access_token           # preferred
    from app.services.auth.tokens import create_access_token    # direct module
"""
from app.services.auth.password_policy import (  # noqa: F401
    hash_password,
    verify_password,
    validate_password_strength,
    check_password_history,
    record_password_history,
)
from app.services.auth.tokens import (  # noqa: F401
    create_access_token,
    create_refresh_token,
    decode_token,
    decode_refresh_token,
    create_embed_token,
    authenticate_embed_token,
    refresh_access_token,
    _create_mfa_pending_token,
    _hash_token,
    _utcnow,
    _embed_signing_secret,
    _is_production,
)
from app.services.auth.sessions import (  # noqa: F401
    create_session,
    validate_session,
    revoke_session,
    revoke_all_sessions,
    list_sessions,
    issue_tokens,
)
from app.services.auth.mfa import (  # noqa: F401
    enable_mfa,
    verify_and_activate_mfa,
    verify_mfa_code,
    disable_mfa,
    complete_mfa_login,
)
from app.services.auth.permissions import (  # noqa: F401
    seed_default_permissions,
    get_user_permissions,
    check_permission,
    set_user_permissions,
)

__all__ = [
    # password_policy
    "hash_password",
    "verify_password",
    "validate_password_strength",
    "check_password_history",
    "record_password_history",
    # tokens
    "create_access_token",
    "create_refresh_token",
    "decode_token",
    "decode_refresh_token",
    "create_embed_token",
    "authenticate_embed_token",
    "refresh_access_token",
    # sessions
    "create_session",
    "validate_session",
    "revoke_session",
    "revoke_all_sessions",
    "list_sessions",
    "issue_tokens",
    # mfa
    "enable_mfa",
    "verify_and_activate_mfa",
    "verify_mfa_code",
    "disable_mfa",
    "complete_mfa_login",
    # permissions
    "seed_default_permissions",
    "get_user_permissions",
    "check_permission",
    "set_user_permissions",
]
