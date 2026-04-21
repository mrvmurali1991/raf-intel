"""
Unit tests for app.services.cache_strategy and app.cache primitives.

All tests run without a real Redis instance.  The cache layer in app.cache
degrades gracefully when Redis is unreachable — _get_redis() returns None,
so cache_get always returns None and cache_set / cache_delete_pattern are
no-ops.  These tests patch the internal _get_redis() helper with an
in-process dict-backed fake to exercise the full decorator and invalidation
logic in isolation.

Test coverage:
  - Cache hit returns cached data without re-calling the wrapped function.
  - Cache miss calls the function and stores the result.
  - Cache invalidation removes the correct keys.
  - Tenant isolation: tenant_1 cache keys do not leak to tenant_2.
"""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest

# ---------------------------------------------------------------------------
# In-process fake Redis backed by a plain dict
# ---------------------------------------------------------------------------


class FakeRedis:
    """Minimal synchronous Redis fake sufficient to exercise cache_strategy."""

    def __init__(self):
        self._store: dict[str, str] = {}

    # ---- basic ops ----

    def get(self, key: str) -> str | None:
        return self._store.get(key)

    def setex(self, key: str, ttl: int, value: str) -> None:
        # TTL is ignored in the fake — all entries persist for the test lifetime.
        self._store[key] = value

    def delete(self, *keys: str) -> int:
        deleted = 0
        for k in keys:
            if k in self._store:
                del self._store[k]
                deleted += 1
        return deleted

    def scan_iter(self, match: str = "*"):
        """Yield keys matching a glob pattern (only * wildcard supported)."""
        import fnmatch

        for key in list(self._store.keys()):
            if fnmatch.fnmatch(key, match):
                yield key

    def ping(self) -> bool:
        return True

    # ---- introspection helpers (not part of Redis API — used in tests) ----

    def keys_snapshot(self) -> list[str]:
        return list(self._store.keys())

    def flush(self) -> None:
        self._store.clear()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def fake_redis() -> FakeRedis:
    """Fresh FakeRedis instance for each test."""
    return FakeRedis()


@pytest.fixture(autouse=True)
def _patch_redis(fake_redis):
    """
    Replace app.cache._get_redis with a function that always returns the
    fake.  Also reset the module-level _redis sentinel so that each test
    starts from a clean slate.
    """
    import app.cache as cache_mod

    original_redis = cache_mod._redis

    # Patch the module-level singleton and the resolver
    with patch.object(cache_mod, "_redis", fake_redis), patch.object(
        cache_mod, "_get_redis", return_value=fake_redis
    ):
        yield

    # Restore original state after test
    cache_mod._redis = original_redis


# ---------------------------------------------------------------------------
# Helper: import decorators fresh (after the patch is in place)
# ---------------------------------------------------------------------------


def _make_tenant_cached_fn(entity: str = "test_entity", ttl: int = 300):
    """Return a freshly decorated dummy function for use in tests."""
    from app.services.cache_strategy import tenant_cached

    @tenant_cached(entity=entity, ttl=ttl)
    def _fn(value: str, *, tenant_id: str) -> dict:
        return {"value": value, "tenant": tenant_id}

    return _fn


# ---------------------------------------------------------------------------
# Tests: cache hit / miss on the @tenant_cached decorator
# ---------------------------------------------------------------------------


class TestTenantCachedDecorator:
    def test_cache_miss_calls_function(self, fake_redis):
        """First call with no cached entry must invoke the wrapped function."""
        call_count = 0

        from app.services.cache_strategy import tenant_cached

        @tenant_cached("entity_miss", ttl=300)
        def expensive(x: int, *, tenant_id: str) -> dict:
            nonlocal call_count
            call_count += 1
            return {"x": x, "tenant": tenant_id}

        result = expensive(42, tenant_id="tenant_1")

        assert call_count == 1, "Function must be called exactly once on cache miss"
        assert result == {"x": 42, "tenant": "tenant_1"}

    def test_cache_miss_stores_result(self, fake_redis):
        """A cache miss must persist the result so the next call is a hit."""
        from app.services.cache_strategy import tenant_cached

        @tenant_cached("entity_store", ttl=300)
        def fn(x: int, *, tenant_id: str) -> dict:
            return {"x": x}

        fn(7, tenant_id="t1")

        assert len(fake_redis.keys_snapshot()) >= 1, "At least one key must be stored after a miss"

    def test_cache_hit_does_not_call_function_again(self, fake_redis):
        """Subsequent calls with the same args must be served from cache."""
        call_count = 0

        from app.services.cache_strategy import tenant_cached

        @tenant_cached("entity_hit", ttl=300)
        def expensive(x: int, *, tenant_id: str) -> dict:
            nonlocal call_count
            call_count += 1
            return {"x": x}

        expensive(1, tenant_id="t1")   # cold — cache miss
        expensive(1, tenant_id="t1")   # warm — cache hit
        expensive(1, tenant_id="t1")   # warm — cache hit

        assert call_count == 1, "Wrapped function must only be called once across three identical calls"

    def test_cache_hit_returns_identical_data(self, fake_redis):
        """Cached result must be equal to the original return value."""
        from app.services.cache_strategy import tenant_cached

        @tenant_cached("entity_eq", ttl=300)
        def fn(name: str, *, tenant_id: str) -> dict:
            return {"name": name, "tenant": tenant_id}

        first = fn("alice", tenant_id="t1")
        second = fn("alice", tenant_id="t1")

        assert first == second

    def test_different_args_produce_different_cache_entries(self, fake_redis):
        """Different argument values must generate separate cache entries."""
        call_count = 0

        from app.services.cache_strategy import tenant_cached

        @tenant_cached("entity_diff_args", ttl=300)
        def fn(x: int, *, tenant_id: str) -> dict:
            nonlocal call_count
            call_count += 1
            return {"x": x}

        fn(1, tenant_id="t1")
        fn(2, tenant_id="t1")  # different x — must call function again

        assert call_count == 2

    def test_none_result_not_cached(self, fake_redis):
        """A None return value must not be written to cache (pass-through)."""
        call_count = 0

        from app.services.cache_strategy import tenant_cached

        @tenant_cached("entity_none", ttl=300)
        def fn(*, tenant_id: str):
            nonlocal call_count
            call_count += 1

        fn(tenant_id="t1")
        fn(tenant_id="t1")
        fn(tenant_id="t1")

        # Three calls, three misses — None is never stored
        assert call_count == 3


# ---------------------------------------------------------------------------
# Tests: cache invalidation
# ---------------------------------------------------------------------------


class TestCacheInvalidation:
    def test_invalidate_wrapper_clears_entity_keys(self, fake_redis):
        """Calling wrapper.invalidate(tenant_id) must remove that tenant's keys."""
        from app.services.cache_strategy import tenant_cached

        @tenant_cached("inv_entity", ttl=300)
        def fn(x: int, *, tenant_id: str) -> dict:
            return {"x": x}

        fn(10, tenant_id="t1")
        fn(20, tenant_id="t1")

        keys_before = [k for k in fake_redis.keys_snapshot() if "inv_entity" in k]
        assert len(keys_before) >= 1, "Expected cached entries before invalidation"

        fn.invalidate("t1")

        keys_after = [k for k in fake_redis.keys_snapshot() if "t1" in k and "inv_entity" in k]
        assert len(keys_after) == 0, "All tenant-scoped keys must be removed after invalidation"

    def test_invalidate_raf_scores_removes_raf_keys(self, fake_redis):
        """invalidate_raf_scores() must remove raf_breakdown keys for the target tenant."""
        from app.services.cache_strategy import invalidate_raf_scores

        # Manually seed cache keys to simulate a warm cache
        fake_redis._store["t1:raf_breakdown:1:2025:t1"] = json.dumps({"score": 1.5})
        fake_redis._store["t1:raf_breakdown:2:2025:t1"] = json.dumps({"score": 2.0})
        fake_redis._store["t2:raf_breakdown:3:2025:t2"] = json.dumps({"score": 3.0})

        invalidate_raf_scores("t1")

        remaining = fake_redis.keys_snapshot()
        assert not any("t1:raf_breakdown" in k for k in remaining), (
            "raf_breakdown keys for t1 must be gone after invalidation"
        )
        # Tenant 2 entries must be unaffected
        assert any("t2:raf_breakdown" in k for k in remaining), (
            "raf_breakdown keys for t2 must survive t1 invalidation"
        )

    def test_invalidate_patient_list(self, fake_redis):
        """invalidate_patient_list() must clear patient_list keys for the tenant."""
        from app.services.cache_strategy import invalidate_patient_list

        fake_redis._store["t1:patient_list:page=1"] = json.dumps([{"pid": 1}])
        fake_redis._store["t1:patient_list:page=2"] = json.dumps([{"pid": 2}])
        fake_redis._store["t2:patient_list:page=1"] = json.dumps([{"pid": 9}])

        invalidate_patient_list("t1")

        remaining = fake_redis.keys_snapshot()
        assert not any("t1:patient_list" in k for k in remaining)
        assert "t2:patient_list:page=1" in remaining

    def test_invalidate_worklist(self, fake_redis):
        """invalidate_worklist() must clear both worklist and coder_worklist keys."""
        from app.services.cache_strategy import invalidate_worklist

        fake_redis._store["t1:worklist:provider=dr_smith"] = json.dumps({"count": 5})
        fake_redis._store["t1:coder_worklist:all"] = json.dumps({"count": 3})
        fake_redis._store["t2:worklist:provider=other"] = json.dumps({"count": 1})

        invalidate_worklist("t1")

        remaining = fake_redis.keys_snapshot()
        assert not any(
            ("t1:worklist" in k or "t1:coder_worklist" in k) for k in remaining
        )
        assert "t2:worklist:provider=other" in remaining

    def test_invalidate_all_for_tenant(self, fake_redis):
        """invalidate_all_for_tenant() must wipe every key for that tenant only."""
        from app.services.cache_strategy import invalidate_all_for_tenant

        fake_redis._store["t1:raf_breakdown:1"] = json.dumps({"score": 1.0})
        fake_redis._store["t1:patient_list:all"] = json.dumps([])
        fake_redis._store["t1:dashboard:summary"] = json.dumps({"gaps": 0})
        fake_redis._store["t2:raf_breakdown:9"] = json.dumps({"score": 9.0})

        invalidate_all_for_tenant("t1")

        remaining = fake_redis.keys_snapshot()
        assert not any(k.startswith("t1:") for k in remaining)
        assert "t2:raf_breakdown:9" in remaining


# ---------------------------------------------------------------------------
# Tests: tenant isolation
# ---------------------------------------------------------------------------


class TestTenantIsolation:
    def test_tenant_1_cache_does_not_leak_to_tenant_2(self, fake_redis):
        """Cache entries for tenant_1 must not be returned for tenant_2 lookups."""
        call_results: list[dict] = []

        from app.services.cache_strategy import tenant_cached

        @tenant_cached("isolation_entity", ttl=300)
        def fn(x: int, *, tenant_id: str) -> dict:
            result = {"x": x, "tenant": tenant_id}
            call_results.append(result)
            return result

        r1 = fn(5, tenant_id="tenant_1")
        r2 = fn(5, tenant_id="tenant_2")

        # Both calls must invoke the function (separate cache namespaces)
        assert len(call_results) == 2, (
            "Each tenant must produce its own cache miss, not share entries"
        )
        assert r1["tenant"] == "tenant_1"
        assert r2["tenant"] == "tenant_2"

    def test_tenant_2_key_distinct_from_tenant_1_key(self, fake_redis):
        """The cache keys for tenant_1 and tenant_2 with identical args must differ."""
        from app.services.cache_strategy import _make_key

        key_t1 = _make_key("tenant_1", "scores", "patient=42", "year=2025")
        key_t2 = _make_key("tenant_2", "scores", "patient=42", "year=2025")

        assert key_t1 != key_t2
        assert key_t1.startswith("tenant_1:")
        assert key_t2.startswith("tenant_2:")

    def test_invalidating_tenant_1_does_not_clear_tenant_2(self, fake_redis):
        """Invalidating tenant_1 must leave tenant_2's cached entries intact."""
        from app.services.cache_strategy import tenant_cached

        call_count_t2 = 0

        @tenant_cached("cross_tenant_entity", ttl=300)
        def fn(x: int, *, tenant_id: str) -> dict:
            nonlocal call_count_t2
            if tenant_id == "tenant_2":
                call_count_t2 += 1
            return {"x": x, "tenant": tenant_id}

        fn(1, tenant_id="tenant_1")
        fn(1, tenant_id="tenant_2")

        # Invalidate only tenant_1
        fn.invalidate("tenant_1")

        # Re-call for tenant_2 — must be served from cache (no additional invocation)
        fn(1, tenant_id="tenant_2")
        assert call_count_t2 == 1, (
            "tenant_2 cache must not be evicted when tenant_1 is invalidated"
        )

    def test_warm_cache_for_one_tenant_not_visible_to_another(self, fake_redis):
        """Explicitly written cache entries for tenant_1 must not be readable by tenant_2."""
        import app.cache as cache_mod

        # Write a value for tenant_1
        cache_mod.cache_set("tenant_1:dashboard:summary", {"gaps": 3}, ttl=300)

        # Attempt to read it under tenant_2's namespace
        hit = cache_mod.cache_get("tenant_2:dashboard:summary")
        assert hit is None, "tenant_2 must not be able to read tenant_1's cache entry"

        # Confirm tenant_1 can still read it
        hit_t1 = cache_mod.cache_get("tenant_1:dashboard:summary")
        assert hit_t1 == {"gaps": 3}


# ---------------------------------------------------------------------------
# Tests: app.cache primitives (cache_get / cache_set / cache_delete_pattern)
# ---------------------------------------------------------------------------


class TestCachePrimitives:
    def test_cache_get_miss_returns_none(self, fake_redis):
        from app.cache import cache_get

        result = cache_get("nonexistent:key")
        assert result is None

    def test_cache_set_then_get_roundtrip(self, fake_redis):
        from app.cache import cache_get, cache_set

        data = {"hcc": 96, "score": 1.234}
        cache_set("test:key:roundtrip", data, ttl=60)

        result = cache_get("test:key:roundtrip")
        assert result == data

    def test_cache_set_handles_various_types(self, fake_redis):
        from app.cache import cache_get, cache_set

        for payload in (
            42,
            3.14,
            "hello",
            [1, 2, 3],
            {"nested": {"a": 1}},
            True,
        ):
            cache_set(f"type_test:{type(payload).__name__}", payload, ttl=60)
            result = cache_get(f"type_test:{type(payload).__name__}")
            assert result == payload

    def test_cache_delete_pattern_removes_matching_keys(self, fake_redis):
        from app.cache import cache_delete_pattern, cache_get, cache_set

        cache_set("t1:raf:1", {"score": 1.0}, ttl=60)
        cache_set("t1:raf:2", {"score": 2.0}, ttl=60)
        cache_set("t1:other:key", {"data": True}, ttl=60)

        cache_delete_pattern("t1:raf:*")

        assert cache_get("t1:raf:1") is None
        assert cache_get("t1:raf:2") is None
        # Non-matching key must survive
        assert cache_get("t1:other:key") is not None

    def test_cache_delete_pattern_noop_on_no_match(self, fake_redis):
        """Deleting a pattern with no matches must not raise or corrupt the store."""
        from app.cache import cache_delete_pattern, cache_get, cache_set

        cache_set("safe:key", {"ok": True}, ttl=60)
        cache_delete_pattern("nonexistent:*")

        assert cache_get("safe:key") == {"ok": True}

    def test_cache_get_with_redis_disabled_returns_none(self):
        """When _get_redis() returns None, cache_get must return None gracefully."""
        with patch("app.cache._get_redis", return_value=None):
            from app.cache import cache_get

            result = cache_get("any:key")
            assert result is None

    def test_cache_set_with_redis_disabled_is_noop(self):
        """When _get_redis() returns None, cache_set must not raise."""
        with patch("app.cache._get_redis", return_value=None):
            from app.cache import cache_set

            # Must complete without exception
            cache_set("any:key", {"data": 1}, ttl=60)
