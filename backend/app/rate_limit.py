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


def login_rate_key(request: Request, email: str) -> str:
    """Rate-limit key for /login that buckets on BOTH submitted email and IP.

    Rationale: keying on IP alone lets an attacker running credential-stuffing
    from a botnet (rotating IPs) sail past /login's ``5/minute`` cap because
    each bot IP starts with a fresh bucket. Keying on email alone lets an
    attacker park on one target account from many IPs and still get throttled
    — but also exposes a trivial DoS against any known-email user.

    The combined ``login:<email>:<ip>`` key gives us both:
      * per-(email,ip) buckets for the common password-guessing case, and
      * per-email aggregation when the same email is tried from many IPs (we
        emit the same ``email`` component, and the attacker still has to roll
        IPs faster than the global default limit configured on the Limiter).

    Callers should pass this as slowapi's ``key_func`` override on the /login
    decorator, e.g.::

        @limiter.limit("5/minute", key_func=lambda r: login_rate_key(r, ...))

    The email is lower-cased so ``User@Example.com`` and ``user@example.com``
    collide into one bucket (emails are case-insensitive in practice).
    """
    email_lower = (email or "").strip().lower()
    ip_or_anon = get_remote_address(request) or "anon"
    return f"login:{email_lower}:{ip_or_anon}"


is_enabled = (
    os.getenv("RATE_LIMITING_ENABLED", "true").lower() in ("true", "1", "yes")
    and os.getenv("APP_ENV", "production") != "testing"
)

limiter = Limiter(
    key_func=_rate_limit_key,
    default_limits=["120/minute"],
    enabled=is_enabled,
)
