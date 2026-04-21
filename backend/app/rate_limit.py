"""
Shared slowapi Limiter instance.

Import this module in any router that needs per-endpoint rate limiting.
The limiter is keyed by the client's remote IP address, falling back to
a combination of IP and authenticated user ID when available.

main.py attaches this limiter to app.state and registers the
RateLimitExceeded exception handler so slowapi can intercept
limit violations and return a 429 response automatically.
"""

import os

from fastapi import Request
from slowapi import Limiter
from slowapi.util import get_remote_address


def _rate_limit_key(request: Request) -> str:
    """Rate limit key combining IP address with user ID when authenticated."""
    ip = get_remote_address(request) or "0.0.0.0"
    user_id = getattr(request.state, "user_id", None)
    if user_id:
        return f"{ip}:{user_id}"
    return ip


is_enabled = (
    os.getenv("RATE_LIMITING_ENABLED", "true").lower() in ("true", "1", "yes")
    and os.getenv("APP_ENV", "production") != "testing"
)

limiter = Limiter(
    key_func=_rate_limit_key,
    default_limits=["120/minute"],
    enabled=is_enabled,
)
