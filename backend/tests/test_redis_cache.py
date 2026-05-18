"""
Unit tests for :mod:`app.services.redis_cache`.

These tests exercise the decorator in isolation by **monkey-patching the
module-level ``_get_redis``** to a deterministic in-memory fake.  We
avoid spinning up a real Redis (``fakeredis`` would also work but adds a
dependency) so the suite stays hermetic and fast.

Coverage matrix
---------------
1. First call: cache miss, wrapped function invoked, value cached.
2. Second call: cache hit, wrapped function NOT invoked, identical value.
3. ``force_refresh=True`` bypasses the cache even when present.
4. Tenant isolation: different ``tenant_id`` arguments yield different keys.
5. Redis down: decorator transparently falls through to the function.
6. TTL expiry: a "time-travelled" key disappears and the function is
   re-invoked.
7. Metrics: hits / misses / errors counters increment correctly.
8. Invalidation helpers wipe the right keys.
"""

from __future__ import annotations

import json
import time
from typing import Any

import pytest

from app.services import redis_cache


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class FakeRedis:
    """In-memory Redis stand-in supporting GET / SETEX / DELETE / SCAN_ITER.

    Each entry is a tuple ``(value_json, expires_at_epoch_seconds_or_None)``.
    """

    def __init__(self) -> None:
        self.store: dict[str, tuple[str, float | None]] = {}
        # Counters useful for assertions.
        self.calls: dict[str, int] = {"get": 0, "setex": 0, "delete": 0, "scan_iter": 0}

    def get(self, key: str):
        self.calls["get"] += 1
        if key not in self.store:
            return None
        val, exp = self.store[key]
        if exp is not None and time.time() > exp:
            del self.store[key]
            return None
        return val

    def setex(self, key: str, ttl: int, val: str):
        self.calls["setex"] += 1
        self.store[key] = (val, time.time() + ttl if ttl > 0 else None)

    def delete(self, *keys: str) -> int:
        self.calls["delete"] += 1
        n = 0
        for k in keys:
            if k in self.store:
                del self.store[k]
                n += 1
        return n

    def scan_iter(self, match: str, count: int = 100):
        self.calls["scan_iter"] += 1
        import fnmatch
        for k in list(self.store.keys()):
            if fnmatch.fnmatch(k, match):
                yield k

    def ping(self) -> bool:
        return True


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def fake_redis(monkeypatch: pytest.MonkeyPatch) -> FakeRedis:
    """Replace the module-level Redis client with a FakeRedis."""
    fake = FakeRedis()
    monkeypatch.setattr(redis_cache, "_redis", fake, raising=False)
    redis_cache.reset_stats()
    yield fake
    redis_cache.reset_connection()
    redis_cache.reset_stats()


@pytest.fixture()
def no_redis(monkeypatch: pytest.MonkeyPatch) -> None:
    """Simulate Redis being permanently unavailable."""
    monkeypatch.setattr(redis_cache, "_redis", False, raising=False)
    redis_cache.reset_stats()
    yield
    redis_cache.reset_connection()
    redis_cache.reset_stats()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_counting_fn():
    """Return a (fn, calls_list) pair so each invocation can be counted."""
    calls: list[tuple[tuple, dict]] = []

    def fn(tenant_id: int, year: int) -> dict[str, Any]:
        calls.append((tenant_id, year))
        return {"tenant_id": tenant_id, "year": year, "raf": 1.234}

    return fn, calls


# ---------------------------------------------------------------------------
# 1. First call = miss; second call = hit
# ---------------------------------------------------------------------------


def test_first_call_misses_second_call_hits(fake_redis: FakeRedis) -> None:
    fn, calls = _make_counting_fn()
    cached_fn = redis_cache.cached(
        key_builder=lambda tenant_id, year: f"raf:v28:portfolio:{tenant_id}:{year}",
        ttl_seconds=60,
    )(fn)

    first = cached_fn(1, 2026)
    second = cached_fn(1, 2026)

    assert first == second == {"tenant_id": 1, "year": 2026, "raf": 1.234}
    assert len(calls) == 1, "wrapped fn must run exactly once across two reads"

    stats = redis_cache.get_cache_stats()
    assert stats["cache_misses"] == 1
    assert stats["cache_hits"] == 1
    assert stats["hit_rate_pct"] == 50.0


# ---------------------------------------------------------------------------
# 2. force_refresh bypasses cache
# ---------------------------------------------------------------------------


def test_force_refresh_skips_cache(fake_redis: FakeRedis) -> None:
    fn, calls = _make_counting_fn()
    cached_fn = redis_cache.cached(
        key_builder=lambda tenant_id, year: f"raf:v28:portfolio:{tenant_id}:{year}",
        ttl_seconds=60,
    )(fn)

    cached_fn(1, 2026)            # miss   — calls == 1
    cached_fn(1, 2026)            # hit    — calls == 1
    cached_fn(1, 2026, force_refresh=True)  # forced — calls == 2

    assert len(calls) == 2
    assert redis_cache.get_cache_stats()["cache_forced_refresh"] == 1


# ---------------------------------------------------------------------------
# 3. Tenant isolation
# ---------------------------------------------------------------------------


def test_tenant_isolation(fake_redis: FakeRedis) -> None:
    """Two tenants calling with the same year MUST get separate cache slots."""
    fn, calls = _make_counting_fn()
    cached_fn = redis_cache.cached(
        key_builder=lambda tenant_id, year: f"raf:v28:portfolio:{tenant_id}:{year}",
        ttl_seconds=60,
    )(fn)

    r1 = cached_fn(1, 2026)
    r2 = cached_fn(2, 2026)
    r1_again = cached_fn(1, 2026)
    r2_again = cached_fn(2, 2026)

    assert r1["tenant_id"] == 1
    assert r2["tenant_id"] == 2
    # tenant=1 was called once, tenant=2 was called once — even though year
    # was identical, the key_builder embedded the tenant id.
    assert len(calls) == 2
    assert r1 == r1_again
    assert r2 == r2_again


# ---------------------------------------------------------------------------
# 4. Redis-down fall-through
# ---------------------------------------------------------------------------


def test_falls_through_when_redis_down(no_redis: None) -> None:
    fn, calls = _make_counting_fn()
    cached_fn = redis_cache.cached(
        key_builder=lambda tenant_id, year: f"raf:v28:portfolio:{tenant_id}:{year}",
        ttl_seconds=60,
    )(fn)

    a = cached_fn(1, 2026)
    b = cached_fn(1, 2026)

    # Two reads with no cache → two calls.  The function still produces
    # the right output; the system degrades gracefully.
    assert a == b
    assert len(calls) == 2


# ---------------------------------------------------------------------------
# 5. TTL expiry (time-travel via FakeRedis internals)
# ---------------------------------------------------------------------------


def test_ttl_expiry_triggers_recompute(fake_redis: FakeRedis) -> None:
    fn, calls = _make_counting_fn()
    cached_fn = redis_cache.cached(
        key_builder=lambda tenant_id, year: f"raf:v28:portfolio:{tenant_id}:{year}",
        ttl_seconds=60,
    )(fn)

    cached_fn(1, 2026)                  # miss  → store
    assert len(calls) == 1

    # Forcibly expire the stored entry by rewriting the expiry to "yesterday".
    for key in list(fake_redis.store.keys()):
        val, _ = fake_redis.store[key]
        fake_redis.store[key] = (val, time.time() - 1)

    cached_fn(1, 2026)                  # should miss again → recompute
    assert len(calls) == 2


# ---------------------------------------------------------------------------
# 6. Invalidation helpers
# ---------------------------------------------------------------------------


def test_invalidate_v28_portfolio_wipes_tenant_keys(fake_redis: FakeRedis) -> None:
    fn, _ = _make_counting_fn()
    cached_fn = redis_cache.cached(
        key_builder=lambda tenant_id, year: f"raf:v28:portfolio:{tenant_id}:{year}",
        ttl_seconds=60,
    )(fn)

    cached_fn(1, 2026)
    cached_fn(1, 2025)
    cached_fn(2, 2026)
    assert "raf:v28:portfolio:1:2026" in fake_redis.store
    assert "raf:v28:portfolio:1:2025" in fake_redis.store
    assert "raf:v28:portfolio:2:2026" in fake_redis.store

    n = redis_cache.invalidate_v28_portfolio(1)
    assert n == 2  # both year keys for tenant=1
    assert "raf:v28:portfolio:1:2026" not in fake_redis.store
    assert "raf:v28:portfolio:1:2025" not in fake_redis.store
    # Tenant 2 untouched — proves the glob is tenant-scoped.
    assert "raf:v28:portfolio:2:2026" in fake_redis.store

    assert redis_cache.get_cache_stats()["cache_invalidations"] == 2


def test_invalidate_single_key(fake_redis: FakeRedis) -> None:
    redis_cache._set("raf:test:foo", {"a": 1}, ttl=60)
    assert redis_cache.invalidate("raf:test:foo") == 1
    assert "raf:test:foo" not in fake_redis.store


# ---------------------------------------------------------------------------
# 7. Key-builder failure falls through without crashing
# ---------------------------------------------------------------------------


def test_key_builder_exception_bypasses_cache(fake_redis: FakeRedis) -> None:
    def bad_builder(*_args, **_kwargs):
        raise RuntimeError("boom")

    fn, calls = _make_counting_fn()
    cached_fn = redis_cache.cached(key_builder=bad_builder, ttl_seconds=60)(fn)

    out = cached_fn(1, 2026)
    assert out["tenant_id"] == 1
    assert len(calls) == 1
    assert redis_cache.get_cache_stats()["cache_errors"] >= 1


# ---------------------------------------------------------------------------
# 8. JSON-roundtrip: dates and other non-JSON-natives must not crash setex
# ---------------------------------------------------------------------------


def test_non_json_native_values_are_serialised(fake_redis: FakeRedis) -> None:
    from datetime import date

    def fn(tenant_id: int) -> dict[str, Any]:
        return {"tenant_id": tenant_id, "as_of": date(2026, 1, 1)}

    cached_fn = redis_cache.cached(
        key_builder=lambda tenant_id: f"raf:test:{tenant_id}",
        ttl_seconds=60,
    )(fn)

    out = cached_fn(1)
    # First call returns the raw dict (incl. real `date`).
    assert out["as_of"].isoformat() == "2026-01-01"

    # Stored representation must round-trip through JSON.
    raw, _exp = fake_redis.store["raf:test:1"]
    parsed = json.loads(raw)
    assert parsed["as_of"] == "2026-01-01"

    # Second call returns the round-tripped (string) form — that's
    # acceptable for HTTP response bodies which are JSON-serialised
    # anyway.
    second = cached_fn(1)
    assert second["as_of"] == "2026-01-01"
