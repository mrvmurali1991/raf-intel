"""
Optional Redis caching layer.

Redis is not required — if REDIS_URL is unset or the server is unreachable,
every cache_get returns None and cache_set/cache_delete_pattern are no-ops.
The application continues to work correctly without any caching.
"""

import json
import logging
import os
from functools import wraps
from typing import Any, Callable

logger = logging.getLogger(__name__)

# Module-level sentinel.
#   None  — not yet attempted
#   False — attempted and failed (skip retries)
#   redis.Redis instance — connected and healthy
_redis = None


def _get_redis():
    global _redis
    if _redis is not None:
        return _redis  # False (disabled) or live client
    redis_url = os.getenv("REDIS_URL")
    if not redis_url:
        _redis = False  # no URL configured — disable permanently
        return None
    try:
        import redis

        client = redis.from_url(redis_url, decode_responses=True)
        client.ping()
        _redis = client
        logger.info("Redis cache connected: %s", redis_url)
        return _redis
    except Exception as exc:
        logger.warning("Redis unavailable, caching disabled: %s", exc)
        _redis = False  # sentinel — avoid retrying on every request
        return None


def cache_get(key: str) -> Any | None:
    """Return the cached value for *key*, or None on miss / unavailability."""
    r = _get_redis()
    if not r:
        return None
    try:
        val = r.get(key)
        return json.loads(val) if val else None
    except Exception:
        return None


def cache_set(key: str, value: Any, ttl: int = 300) -> None:
    """Store *value* under *key* with an expiry of *ttl* seconds."""
    r = _get_redis()
    if not r:
        return
    try:
        r.setex(key, ttl, json.dumps(value, default=str))
    except Exception:
        pass


def cache_delete_pattern(pattern: str) -> None:
    """Delete all keys matching *pattern* (glob-style, e.g. ``raf:breakdown:42:*``)."""
    r = _get_redis()
    if not r:
        return
    try:
        for key in r.scan_iter(match=pattern):
            r.delete(key)
    except Exception:
        pass


def cached(prefix: str, ttl: int = 300):
    """
    Decorator that caches the return value of a function in Redis.

    The cache key is built from *prefix* plus all positional and keyword
    arguments, so different call signatures produce different keys.

    Usage::

        @cached("my:prefix", ttl=120)
        def expensive_fn(a, b, *, c=1):
            ...
    """

    def decorator(func: Callable):
        @wraps(func)
        def wrapper(*args, **kwargs):
            key_parts = (
                [prefix]
                + [str(a) for a in args]
                + [f"{k}={v}" for k, v in sorted(kwargs.items())]
            )
            cache_key = ":".join(key_parts)

            result = cache_get(cache_key)
            if result is not None:
                return result

            result = func(*args, **kwargs)
            cache_set(cache_key, result, ttl)
            return result

        return wrapper

    return decorator
