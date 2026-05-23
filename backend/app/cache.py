"""
Optional Redis caching layer.

Redis is not required — if REDIS_URL is unset or the server is unreachable,
every cache_get returns None and cache_set/cache_delete_pattern are no-ops.
The application continues to work correctly without any caching.

High-availability (Sentinel) mode
----------------------------------
Set REDIS_SENTINEL_HOSTS to a comma-separated list of ``host:port`` pairs,
e.g. ``sentinel1:26379,sentinel2:26379,sentinel3:26379``, and optionally
set REDIS_SENTINEL_MASTER (default ``mymaster``) and REDIS_SENTINEL_PASSWORD.
When REDIS_SENTINEL_HOSTS is present, the cache layer connects via
redis.sentinel.Sentinel and transparently follows master failovers.
Falls back to standalone REDIS_URL mode if Sentinel is not configured.
"""

import json
import logging
import os
from collections.abc import Callable
from functools import wraps
from typing import Any

logger = logging.getLogger(__name__)

# Module-level sentinel.
#   None  — not yet attempted
#   False — attempted and failed (skip retries)
#   redis.Redis instance — connected and healthy
_redis = None

# Sentinel configuration env vars
_SENTINEL_HOSTS_RAW: str | None = os.getenv("REDIS_SENTINEL_HOSTS")
_SENTINEL_MASTER: str = os.getenv("REDIS_SENTINEL_MASTER", "mymaster")
_SENTINEL_PASSWORD: str | None = os.getenv("REDIS_SENTINEL_PASSWORD") or os.getenv("REDIS_PASSWORD")


def _parse_sentinel_hosts(raw: str) -> list[tuple[str, int]]:
    """Parse ``"host:port,host:port"`` into a list of ``(host, port)`` tuples."""
    hosts = []
    for entry in raw.split(","):
        entry = entry.strip()
        if not entry:
            continue
        if ":" in entry:
            h, p = entry.rsplit(":", 1)
            hosts.append((h.strip(), int(p.strip())))
        else:
            hosts.append((entry, 26379))
    return hosts


def _build_sentinel_client():
    """Return a Redis master client obtained through Sentinel, or None on failure."""
    try:
        from redis.sentinel import Sentinel

        hosts = _parse_sentinel_hosts(_SENTINEL_HOSTS_RAW)
        if not hosts:
            logger.warning("REDIS_SENTINEL_HOSTS is set but empty — falling back to standalone.")
            return None

        sentinel_kwargs: dict = {"socket_timeout": 5}
        if _SENTINEL_PASSWORD:
            sentinel_kwargs["password"] = _SENTINEL_PASSWORD

        sentinel = Sentinel(hosts, sentinel_kwargs=sentinel_kwargs)
        # Resolve the master and issue a ping to confirm connectivity.
        master = sentinel.master_for(
            _SENTINEL_MASTER,
            socket_timeout=5,
            decode_responses=True,
            password=_SENTINEL_PASSWORD,
        )
        master.ping()
        logger.info(
            "Redis Sentinel connected — master=%s sentinels=%s",
            _SENTINEL_MASTER,
            hosts,
        )
        return master
    except Exception as exc:
        logger.warning("Redis Sentinel connection failed: %s", exc)
        return None


def _get_redis():
    global _redis
    if _redis is not None:
        return _redis  # False (disabled) or live client

    # ---- Sentinel mode takes priority when configured ----
    if _SENTINEL_HOSTS_RAW:
        client = _build_sentinel_client()
        if client is not None:
            _redis = client
            return _redis
        # Sentinel failed — fall through to standalone mode.
        logger.warning(
            "Redis Sentinel unavailable — falling back to standalone REDIS_URL."
        )

    # ---- Standalone mode ----
    redis_url = os.getenv("REDIS_URL")
    if not redis_url:
        _redis = False  # no URL configured — disable permanently
        return None
    try:
        import redis

        client = redis.from_url(redis_url, decode_responses=True)
        client.ping()
        _redis = client
        logger.info("Redis cache connected (standalone): %s", redis_url)
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
    except Exception:  # noqa: BLE001 — best-effort guard
        logger.debug("swallowed exception", exc_info=True)
        return None


def cache_set(key: str, value: Any, ttl: int = 300) -> None:
    """Store *value* under *key* with an expiry of *ttl* seconds."""
    r = _get_redis()
    if not r:
        return
    try:
        r.setex(key, ttl, json.dumps(value, default=str))
    except Exception:  # noqa: BLE001 — best-effort guard
        logger.debug("swallowed exception", exc_info=True)


def cache_delete_pattern(pattern: str) -> None:
    """Delete all keys matching *pattern* (glob-style, e.g. ``raf:breakdown:42:*``)."""
    r = _get_redis()
    if not r:
        return
    try:
        for key in r.scan_iter(match=pattern):
            r.delete(key)
    except Exception:  # noqa: BLE001 — best-effort guard
        logger.debug("swallowed exception", exc_info=True)


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
