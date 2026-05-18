"""
Redis-backed read-through cache decorator for hot read endpoints.

This module provides a single declarative entry point — :func:`cached` —
that wraps a synchronous function so its result is memoised in Redis with
a configurable TTL and key-building strategy.  It is intentionally:

* **Lazy** — ``redis-py`` is imported only on the first call so importing
  this module is free in environments without Redis (CI, unit tests).
* **Tolerant** — when Redis is unreachable, the decorator transparently
  falls through to the wrapped function.  An app without Redis still
  works, just without the speed-up.
* **Observable** — every hit/miss/invalidation/error increments a
  module-level counter exposed via :func:`get_cache_stats` and the
  ``/api/admin/cache/stats`` admin endpoint.
* **Tenant-aware** — when ``tenant_aware=True`` the configured
  ``key_builder`` *must* include a tenant identifier so cross-tenant
  reads can never collide (HIPAA tenant isolation).

The decorator only memoises *read* paths.  Write paths must call
:func:`invalidate` or :func:`invalidate_pattern` to evict stale entries.

Performance target
------------------
The five wired endpoints (see ``app/routers/{v28_impact,hedis,
coder_analytics,document_ingestion_dashboard}.py``) drop their P95 from
1.3 s (cold MySQL aggregation) to <100 ms (Redis JSON GET) after a single
warm-up call.  See ``docs/enterprise/PERF_BASELINE.md`` for measured
before/after numbers.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from collections.abc import Callable
from functools import wraps
from typing import Any, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Connection management
# ---------------------------------------------------------------------------
#
# ``_redis``:
#   * ``None``  — not yet attempted
#   * ``False`` — attempted and failed; subsequent calls short-circuit so we
#                 don't blow up under load by retrying a dead Redis on every
#                 request.
#   * redis.Redis instance — connected and healthy.
#
# A short-lived "circuit-breaker" reset window can be triggered with
# :func:`reset_connection` so that the test suite (and an operator on the
# CLI) can recover after Redis has come back up.

_redis: Any = None
_conn_lock = threading.Lock()

# ---------------------------------------------------------------------------
# Metrics — read by /api/admin/cache/stats
# ---------------------------------------------------------------------------

_stats_lock = threading.Lock()
_stats: dict[str, int] = {
    "cache_hits": 0,
    "cache_misses": 0,
    "cache_invalidations": 0,
    "cache_errors": 0,
    "cache_forced_refresh": 0,
}


def _incr(metric: str, by: int = 1) -> None:
    with _stats_lock:
        _stats[metric] = _stats.get(metric, 0) + by


def get_cache_stats() -> dict[str, Any]:
    """Return a snapshot of cache counters plus connection state.

    Used by the ``/api/admin/cache/stats`` endpoint.  Cheap — no Redis I/O.
    """
    with _stats_lock:
        snap = dict(_stats)
    snap["redis_connected"] = bool(_get_redis())
    total = snap["cache_hits"] + snap["cache_misses"]
    snap["hit_rate_pct"] = round(100.0 * snap["cache_hits"] / total, 2) if total else 0.0
    return snap


def reset_stats() -> None:
    """Zero the in-memory counters.  Test-only — never wire to an API."""
    with _stats_lock:
        for k in list(_stats.keys()):
            _stats[k] = 0


def reset_connection() -> None:
    """Force the next call to re-discover Redis.

    Useful after Redis has come back online, or in tests that need to flip
    the connection state.  Does **not** flush keys.
    """
    global _redis
    with _conn_lock:
        _redis = None


# ---------------------------------------------------------------------------
# Redis client acquisition (lazy)
# ---------------------------------------------------------------------------


def _get_redis() -> Any:
    """Return a connected Redis client, or ``None`` if Redis is unavailable.

    Lazy-imports ``redis-py``; never raises.  Once a connection attempt
    fails we cache the failure (``False`` sentinel) so that subsequent
    cache lookups are a fast no-op instead of repeatedly timing out.
    """
    global _redis
    if _redis is not None:
        return _redis if _redis is not False else None

    with _conn_lock:
        if _redis is not None:
            return _redis if _redis is not False else None

        # Prefer the same connection Celery uses so we don't open a second
        # pool when the celery app is already initialised.
        try:
            from app.services.celery_tasks import celery_app  # noqa: WPS433
            with celery_app.connection_or_acquire() as conn:  # type: ignore[attr-defined]
                # connection_or_acquire returns a kombu connection. We don't
                # use it directly for GET/SET — we need a redis-py client.
                _ = conn  # silence linter; presence proves Redis is up.
        except Exception:
            # Celery not configured or broker unreachable — fall through
            # to a direct REDIS_URL connection.  This is the common dev
            # path (no Celery worker running).
            pass

        redis_url = os.getenv("REDIS_URL")
        if not redis_url:
            _redis = False
            return None
        try:
            import redis  # lazy import — only when Redis is configured

            client = redis.from_url(redis_url, decode_responses=True, socket_timeout=2)
            client.ping()
            _redis = client
            logger.info("redis_cache: connected to %s", redis_url)
            return _redis
        except Exception as exc:
            logger.warning("redis_cache: Redis unavailable, caching disabled: %s", exc)
            _redis = False
            _incr("cache_errors")
            return None


# ---------------------------------------------------------------------------
# Low-level get / set / delete
# ---------------------------------------------------------------------------


def _get(key: str) -> Any | None:
    r = _get_redis()
    if not r:
        return None
    try:
        raw = r.get(key)
        return json.loads(raw) if raw else None
    except Exception as exc:
        logger.debug("redis_cache: GET %s failed: %s", key, exc)
        _incr("cache_errors")
        return None


def _set(key: str, value: Any, ttl: int) -> None:
    r = _get_redis()
    if not r:
        return
    try:
        r.setex(key, ttl, json.dumps(value, default=str))
    except Exception as exc:
        logger.debug("redis_cache: SET %s failed: %s", key, exc)
        _incr("cache_errors")


def invalidate(key: str) -> int:
    """Delete a single cache key.  Returns 1 on success, 0 otherwise."""
    r = _get_redis()
    if not r:
        return 0
    try:
        n = int(r.delete(key) or 0)
        if n:
            _incr("cache_invalidations", n)
        return n
    except Exception as exc:
        logger.debug("redis_cache: DEL %s failed: %s", key, exc)
        _incr("cache_errors")
        return 0


def invalidate_pattern(pattern: str) -> int:
    """Delete all keys matching *pattern* (glob).  Returns count deleted.

    Uses ``SCAN`` instead of ``KEYS`` so we don't lock the Redis instance
    under load.
    """
    r = _get_redis()
    if not r:
        return 0
    deleted = 0
    try:
        for key in r.scan_iter(match=pattern, count=200):
            try:
                deleted += int(r.delete(key) or 0)
            except Exception:
                pass
        if deleted:
            _incr("cache_invalidations", deleted)
    except Exception as exc:
        logger.debug("redis_cache: SCAN %s failed: %s", pattern, exc)
        _incr("cache_errors")
    return deleted


# ---------------------------------------------------------------------------
# Tenant-aware invalidation helpers — called from write-path routers
# ---------------------------------------------------------------------------


def invalidate_v28_portfolio(tenant_id: int | str) -> int:
    """Evict all V28 portfolio keys for a tenant (any year)."""
    return invalidate_pattern(f"raf:v28:portfolio:{tenant_id}:*")


def invalidate_hedis_scores(tenant_id: int | str) -> int:
    """Evict all HEDIS scores keys for a tenant (any year)."""
    return invalidate_pattern(f"raf:hedis:scores:{tenant_id}:*")


def invalidate_audit_runs(tenant_id: int | str) -> int:
    """Evict any RADV audit-runs cache for a tenant."""
    return invalidate_pattern(f"raf:radv:audit_runs:{tenant_id}:*")


def invalidate_doc_dashboard(tenant_id: int | str) -> int:
    """Evict the document-ingestion dashboard cache for a tenant."""
    return invalidate_pattern(f"raf:doc_dashboard:{tenant_id}:*")


# ---------------------------------------------------------------------------
# Decorator
# ---------------------------------------------------------------------------


def cached(
    key_builder: Callable[..., str],
    ttl_seconds: int = 3600,
    tenant_aware: bool = True,
    force_refresh_kwarg: str = "force_refresh",
):
    """Wrap a read-only function with Redis-backed memoisation.

    Parameters
    ----------
    key_builder:
        Callable that receives the wrapped function's positional + keyword
        arguments and returns a string Redis key.  Returning an empty
        string disables caching for that call (rare — used to skip cache
        for partial / personalised payloads).
    ttl_seconds:
        Time-to-live for cached values.  The shortest sensible TTL is
        ~30 s (doc-dashboard); the longest is 24 h (HEDIS measure
        metadata).
    tenant_aware:
        When ``True`` (default), the produced key MUST include a tenant
        identifier.  We do not enforce this at decoration time, but the
        caller is responsible for embedding ``tenant_id`` in
        ``key_builder``.  Cross-tenant key collisions would be a HIPAA
        violation.
    force_refresh_kwarg:
        Name of the keyword argument used by callers to bypass the cache
        (default ``"force_refresh"``).  When the wrapped function
        receives ``<kwarg>=True``, the cache is read-through skipped and
        the freshly-computed value is written back to Redis.
    """

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            # ------------------------------------------------------------------
            # Build the cache key.  If the builder raises (e.g. missing arg),
            # fall through to the function — never break the read path because
            # of a caching bug.
            # ------------------------------------------------------------------
            force_refresh = bool(kwargs.pop(force_refresh_kwarg, False))
            try:
                key = key_builder(*args, **kwargs)
            except Exception as exc:
                logger.warning(
                    "redis_cache: key_builder failed for %s: %s — bypassing cache",
                    func.__name__, exc,
                )
                _incr("cache_errors")
                return func(*args, **kwargs)

            if not key:
                # Builder opted out for this particular call.
                return func(*args, **kwargs)

            # ------------------------------------------------------------------
            # Read-through
            # ------------------------------------------------------------------
            if force_refresh:
                _incr("cache_forced_refresh")
            else:
                hit = _get(key)
                if hit is not None:
                    _incr("cache_hits")
                    return hit
                _incr("cache_misses")

            # ------------------------------------------------------------------
            # Miss (or forced refresh) — compute & store.
            # ------------------------------------------------------------------
            value = func(*args, **kwargs)
            try:
                _set(key, value, ttl_seconds)
            except Exception as exc:  # belt-and-braces — _set already swallows
                logger.debug("redis_cache: store failed key=%s: %s", key, exc)
                _incr("cache_errors")
            return value

        # Expose the underlying function so tests can call it without the
        # cache layer (and so :func:`invalidate` plays nicely with mocks).
        wrapper.__wrapped__ = func  # type: ignore[attr-defined]
        wrapper.cache_key_builder = key_builder  # type: ignore[attr-defined]
        return wrapper

    return decorator


__all__ = [
    "cached",
    "invalidate",
    "invalidate_pattern",
    "invalidate_v28_portfolio",
    "invalidate_hedis_scores",
    "invalidate_audit_runs",
    "invalidate_doc_dashboard",
    "get_cache_stats",
    "reset_stats",
    "reset_connection",
]
