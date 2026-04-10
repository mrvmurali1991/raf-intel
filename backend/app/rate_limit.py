"""
Shared slowapi Limiter instance.

Import this module in any router that needs per-endpoint rate limiting.
The limiter is keyed by the client's remote IP address.

main.py attaches this limiter to app.state and registers the
RateLimitExceeded exception handler so slowapi can intercept
limit violations and return a 429 response automatically.
"""
from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address, default_limits=["120/minute"])
