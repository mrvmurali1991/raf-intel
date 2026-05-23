"""
Systematic cache-aside strategy for hot queries.

Provides tenant-scoped caching decorators and invalidation helpers for
the most expensive database operations: RAF scores, patient lists,
provider worklists, and dashboard analytics.

Cache key format: ``{tenant_id}:{entity}:{discriminator}``

All functions degrade gracefully — if Redis is unavailable, every
decorator becomes a transparent pass-through.
"""

from __future__ import annotations

import functools
import hashlib
import logging
from collections.abc import Callable
from typing import Any

from app.cache import _get_redis, cache_delete_pattern, cache_get, cache_set
from app.metrics import CACHE_HITS, CACHE_MISSES

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Active-connection scoping — ensures cache keys change on EMR switch
# ---------------------------------------------------------------------------

def get_active_connection_id(tenant_id: str | None = None) -> int:
    """Return the active EMR connection id for cache-key scoping.

    When a user switches from OpenEMR-A to OpenEMR-B, the connection id
    changes and every cache key that includes it becomes a miss — exactly
    what we want so stale data from the old connection is never served.
    """
    try:
        from app.db import raf_cursor
        with raf_cursor() as cur:
            if tenant_id:
                cur.execute(
                    "SELECT id FROM emr_connections WHERE is_active = 1 AND tenant_id = %s LIMIT 1",
                    (tenant_id,),
                )
            else:
                cur.execute("SELECT id FROM emr_connections WHERE is_active = 1 LIMIT 1")
            row = cur.fetchone()
            return row["id"] if row else 0
    except Exception:  # noqa: BLE001 — best-effort guard
        logger.debug("swallowed exception", exc_info=True)
        return 0

# ---------------------------------------------------------------------------
# Stampede protection (thundering-herd lock)
# ---------------------------------------------------------------------------

_LOCK_TTL = 5  # seconds — short enough that a crashed worker doesn't block long


def _acquire_lock(key: str) -> bool:
    """Attempt to acquire a short-lived Redis lock using SETNX.

    Returns True when the lock is obtained (caller must recompute and fill the
    cache), False when another worker already holds the lock (caller should
    return a cache miss and let the caller retry or serve stale data).
    """
    r = _get_redis()
    if not r:
        return True  # no Redis — always allow recompute
    lock_key = f"__lock__:{key}"
    try:
        return bool(r.set(lock_key, "1", nx=True, ex=_LOCK_TTL))
    except Exception:
        logger.debug("swallowed exception", exc_info=True)
        return True  # on error, allow recompute


def _release_lock(key: str) -> None:
    """Release a previously acquired lock early (after cache is populated)."""
    r = _get_redis()
    if not r:
        return
    try:
        r.delete(f"__lock__:{key}")
    except Exception:  # noqa: BLE001 — best-effort guard
        logger.debug("swallowed exception", exc_info=True)

# ---------------------------------------------------------------------------
# TTL constants (seconds)
# ---------------------------------------------------------------------------

TTL_RAF_SCORE = 300       # 5 min — invalidated on recalculation
TTL_PATIENT_LIST = 120    # 2 min — invalidated on sync / upload
TTL_WORKLIST = 180        # 3 min — invalidated on gap changes
TTL_DASHBOARD = 300       # 5 min — invalidated on pipeline completion

# ---------------------------------------------------------------------------
# Key builders
# ---------------------------------------------------------------------------


def _make_key(tenant_id: str, entity: str, *parts: Any) -> str:
    """Build a tenant-scoped cache key that includes the active connection id.

    Including the connection id means switching EMR connections automatically
    produces different cache keys, preventing stale data from a previous
    connection from being served.
    """
    conn_id = get_active_connection_id(tenant_id)
    tail = ":".join(str(p) for p in parts)
    if len(tail) > 128:
        tail = hashlib.md5(tail.encode(), usedforsecurity=False).hexdigest()
    return f"{tenant_id}:c{conn_id}:{entity}:{tail}"


# ---------------------------------------------------------------------------
# Generic tenant-scoped caching decorator
# ---------------------------------------------------------------------------


def tenant_cached(
    entity: str,
    ttl: int = 300,
    tenant_arg: str = "tenant_id",
):
    """Decorator that caches a function's return value scoped to a tenant.

    The decorated function **must** accept a keyword (or positional) argument
    named *tenant_arg* (default ``"tenant_id"``).  All arguments are folded
    into the cache key so different call signatures produce different entries.

    Usage::

        @tenant_cached("raf_breakdown", ttl=TTL_RAF_SCORE)
        def get_raf_breakdown(patient_id, year, tenant_id):
            ...
    """

    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            # Resolve tenant_id from args/kwargs
            import inspect

            sig = inspect.signature(func)
            bound = sig.bind(*args, **kwargs)
            bound.apply_defaults()
            tid = str(bound.arguments.get(tenant_arg, ""))

            # Build cache key from all arguments
            key_parts = [str(v) for v in bound.arguments.values()]
            cache_key = _make_key(tid, entity, *key_parts)

            hit = cache_get(cache_key)
            if hit is not None:
                logger.debug("cache HIT  %s", cache_key)
                CACHE_HITS.labels(entity=entity).inc()
                return hit

            logger.debug("cache MISS %s", cache_key)
            CACHE_MISSES.labels(entity=entity).inc()

            # Stampede protection: only one worker recomputes on miss.
            # If the lock is not acquired, another worker is already computing
            # the value — return None and let the caller handle the miss
            # (it will be populated shortly by the lock holder).
            if not _acquire_lock(cache_key):
                logger.debug("cache LOCK held by another worker %s", cache_key)
                return func(*args, **kwargs)

            try:
                result = func(*args, **kwargs)
                if result is not None:
                    cache_set(cache_key, result, ttl)
            finally:
                _release_lock(cache_key)

            return result

        # Expose invalidation helper on the wrapper
        wrapper.invalidate = lambda tid, *extra: cache_delete_pattern(  # type: ignore[attr-defined]
            _make_key(tid, entity, "*")
        )
        return wrapper

    return decorator


# ---------------------------------------------------------------------------
# Targeted invalidation helpers
# ---------------------------------------------------------------------------


def invalidate_raf_scores(tenant_id: str, patient_id: int | None = None) -> None:
    """Invalidate cached RAF scores for a tenant (optionally a single patient)."""
    if patient_id is not None:
        cache_delete_pattern(f"{tenant_id}:*:raf_breakdown:*{patient_id}*")
        cache_delete_pattern(f"{tenant_id}:raf_breakdown:*{patient_id}*")
        cache_delete_pattern(f"raf:breakdown:{patient_id}:*:{tenant_id}")
    else:
        cache_delete_pattern(f"{tenant_id}:*:raf_breakdown:*")
        cache_delete_pattern(f"{tenant_id}:raf_breakdown:*")
        cache_delete_pattern(f"raf:breakdown:*:*:{tenant_id}")
    logger.debug(
        "invalidated raf_scores cache tenant=%s patient=%s", tenant_id, patient_id
    )


def invalidate_patient_list(tenant_id: str) -> None:
    """Invalidate cached patient lists for a tenant."""
    cache_delete_pattern(f"{tenant_id}:*:patient_list:*")
    cache_delete_pattern(f"{tenant_id}:patient_list:*")
    logger.debug("invalidated patient_list cache tenant=%s", tenant_id)


def invalidate_worklist(tenant_id: str) -> None:
    """Invalidate cached worklist data for a tenant."""
    cache_delete_pattern(f"{tenant_id}:*:worklist:*")
    cache_delete_pattern(f"{tenant_id}:worklist:*")
    cache_delete_pattern(f"{tenant_id}:*:coder_worklist:*")
    cache_delete_pattern(f"{tenant_id}:coder_worklist:*")
    logger.debug("invalidated worklist cache tenant=%s", tenant_id)


def invalidate_dashboard(tenant_id: str) -> None:
    """Invalidate cached dashboard stats for a tenant."""
    cache_delete_pattern(f"{tenant_id}:*:dashboard:*")
    cache_delete_pattern(f"{tenant_id}:dashboard:*")
    logger.debug("invalidated dashboard cache tenant=%s", tenant_id)


def invalidate_all_for_tenant(tenant_id: str) -> None:
    """Nuclear option — drop every cached value for a tenant."""
    cache_delete_pattern(f"{tenant_id}:*")
    logger.debug("invalidated ALL caches for tenant=%s", tenant_id)


# ---------------------------------------------------------------------------
# Cache warming helpers (called after pipeline stages)
# ---------------------------------------------------------------------------


def warm_raf_scores(tenant_id: str) -> int:
    """Pre-warm RAF breakdown cache for all active patients in a tenant.

    Returns the number of patients warmed.
    """
    try:
        from datetime import date

        from app.db import raf_cursor
        from app.services.raf_calculator import get_raf_breakdown

        year = date.today().year
        with raf_cursor() as cur:
            cur.execute(
                "SELECT id FROM patients WHERE tenant_id = %s AND is_active = 1",
                (tenant_id,),
            )
            pids = [row["id"] for row in cur.fetchall()]

        warmed = 0
        for pid in pids:
            try:
                get_raf_breakdown(pid, year, tenant_id=tenant_id)
                warmed += 1
            except Exception:  # noqa: BLE001 — best-effort guard
                logger.debug("swallowed exception", exc_info=True)
        logger.info(
            "cache warm: raf_scores for %d/%d patients [tenant=%s]",
            warmed, len(pids), tenant_id,
        )
        return warmed
    except Exception as exc:
        logger.warning("cache warm raf_scores failed [tenant=%s]: %s", tenant_id, exc)
        return 0


def warm_dashboard(tenant_id: str) -> None:
    """Pre-warm dashboard stats caches after pipeline completion."""
    try:
        from app.services.care_gap_service import (
            get_dashboard_stats as care_gap_dashboard,
        )

        care_gap_dashboard(tenant_id)
        logger.info("cache warm: dashboard stats [tenant=%s]", tenant_id)
    except Exception as exc:
        logger.warning("cache warm dashboard failed [tenant=%s]: %s", tenant_id, exc)
