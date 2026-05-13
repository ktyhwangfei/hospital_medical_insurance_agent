"""TDD tests for CachedStorageBase — test FIRST, then implement.

Covers: key building, JSON-safe conversion, circuit breaker,
cache read/write/invalidation, and monitoring counters.
"""
import time
from datetime import date, datetime
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

from src.data_platform.cache.cached_base import CachedStorageBase
from src.data_platform.cache.in_memory import InMemoryCacheClient


# ── Fixtures ──────────────────────────────────────────────────────────────


@pytest.fixture
def cache():
    return InMemoryCacheClient()


@pytest.fixture
def base(cache):
    return CachedStorageBase(cache=cache, domain="test", default_ttl=3600, enabled=True)


# ── _make_key ─────────────────────────────────────────────────────────────


class TestMakeKey:
    def test_basic_key(self, base: CachedStorageBase):
        assert base._make_key("get", "sk-001") == "test:get/sk-001"

    def test_multi_part_key(self, base: CachedStorageBase):
        assert base._make_key("by_owner", "user1") == "test:by_owner/user1"

    def test_single_part_key(self, base: CachedStorageBase):
        assert base._make_key("list") == "test:list"

    def test_prefix_key(self):
        with patch("src.data_platform.cache.cached_base.CACHE_KEY_PREFIX", "tenant1:"):
            base = CachedStorageBase(InMemoryCacheClient(), "skill", 3600)
            assert base._make_key("get", "sk-001") == "tenant1:skill:get/sk-001"

    def test_empty_prefix(self):
        with patch("src.data_platform.cache.cached_base.CACHE_KEY_PREFIX", ""):
            base = CachedStorageBase(InMemoryCacheClient(), "skill", 3600)
            assert base._make_key("get", "sk-001") == "skill:get/sk-001"


# ── _json_safe_deep ───────────────────────────────────────────────────────


class TestJsonSafeDeep:
    def test_date_conversion(self, base: CachedStorageBase):
        result = base._json_safe_deep(date(2026, 5, 13))
        assert result == "2026-05-13"

    def test_datetime_conversion(self, base: CachedStorageBase):
        d = datetime(2026, 5, 13, 10, 30, 0)
        result = base._json_safe_deep(d)
        assert result == "2026-05-13T10:30:00"

    def test_decimal_conversion(self, base: CachedStorageBase):
        result = base._json_safe_deep(Decimal("99.99"))
        assert result == 99.99

    def test_decimal_zero(self, base: CachedStorageBase):
        result = base._json_safe_deep(Decimal("0"))
        assert result == 0.0

    def test_bytes_conversion(self, base: CachedStorageBase):
        result = base._json_safe_deep(b"hello")
        assert result == "hello"

    def test_bytes_binary(self, base: CachedStorageBase):
        """Non-UTF-8 bytes are decoded with 'replace' error handler."""
        result = base._json_safe_deep(b"\xff\xfe")
        assert isinstance(result, str)

    def test_set_to_list(self, base: CachedStorageBase):
        result = base._json_safe_deep({1, 2, 3})
        assert sorted(result) == [1, 2, 3]

    def test_empty_set(self, base: CachedStorageBase):
        result = base._json_safe_deep(set())
        assert result == []

    def test_nested_dict(self, base: CachedStorageBase):
        obj = {"date": date(2026, 1, 1), "nested": {"amount": Decimal("50")}}
        result = base._json_safe_deep(obj)
        assert result["date"] == "2026-01-01"
        assert result["nested"]["amount"] == 50.0

    def test_list_with_dates(self, base: CachedStorageBase):
        obj = [date(2026, 1, 1), Decimal("10.5")]
        result = base._json_safe_deep(obj)
        assert result == ["2026-01-01", 10.5]

    def test_none_preserved(self, base: CachedStorageBase):
        assert base._json_safe_deep(None) is None

    def test_int_preserved(self, base: CachedStorageBase):
        assert base._json_safe_deep(42) == 42

    def test_str_preserved(self, base: CachedStorageBase):
        assert base._json_safe_deep("hello") == "hello"

    def test_float_preserved(self, base: CachedStorageBase):
        assert base._json_safe_deep(3.14) == 3.14

    def test_bool_preserved(self, base: CachedStorageBase):
        assert base._json_safe_deep(True) is True
        assert base._json_safe_deep(False) is False


# ── _to_cache_value ──────────────────────────────────────────────────────


class TestToCacheValue:
    def test_pydantic_model(self, base: CachedStorageBase):
        """A dict-like object with model_dump is treated as Pydantic."""
        obj = MagicMock()
        obj.model_dump.return_value = {"name": "test", "amount": Decimal("10")}
        result = base._to_cache_value(obj)
        obj.model_dump.assert_called_once_with(mode="json")
        assert result == {"name": "test", "amount": Decimal("10")}

    def test_list_of_pydantic(self, base: CachedStorageBase):
        m1 = MagicMock()
        m1.model_dump.return_value = {"id": 1}
        m2 = MagicMock()
        m2.model_dump.return_value = {"id": 2}
        result = base._to_cache_value([m1, m2])
        assert result == [{"id": 1}, {"id": 2}]

    def test_dict_with_dates(self, base: CachedStorageBase):
        result = base._to_cache_value({"created": date(2026, 5, 13)})
        assert result == {"created": "2026-05-13"}

    def test_dict_with_decimals(self, base: CachedStorageBase):
        result = base._to_cache_value({"amount": Decimal("19.99")})
        assert result == {"amount": 19.99}

    def test_plain_value(self, base: CachedStorageBase):
        assert base._to_cache_value("hello") == "hello"
        assert base._to_cache_value(42) == 42
        assert base._to_cache_value(None) is None


# ── Circuit breaker ──────────────────────────────────────────────────────


class TestCircuitBreaker:
    def test_starts_closed(self, base: CachedStorageBase):
        assert base._circuit_open is False
        assert base._failure_count == 0

    def test_record_failure_increments_count(self, base: CachedStorageBase):
        base._record_failure()
        assert base._failure_count == 1
        assert base._circuit_open is False  # not yet open

    def test_opens_after_threshold_failures(self, base: CachedStorageBase):
        for _ in range(5):
            base._record_failure()
        assert base._circuit_open is True
        assert base._failure_count == 5

    def test_bypasses_cache_when_open(self, base: CachedStorageBase):
        base._failure_count = 5
        base._last_failure_time = time.time()  # recent failure, within window
        base._circuit_open = True
        assert base._should_try_cache() is False

    def test_disabled_when_enabled_false(self, base: CachedStorageBase):
        base._enabled = False
        assert base._should_try_cache() is False

    def test_auto_recovers_after_window(self, base: CachedStorageBase):
        base._failure_count = 5
        base._last_failure_time = time.time() - 120  # 2 min ago, window=60s
        base._circuit_open = True
        assert base._should_try_cache() is True  # auto-recover
        assert base._circuit_open is False
        assert base._failure_count == 0

    def test_auto_recover_resets_counters(self, base: CachedStorageBase):
        base._failure_count = 5
        base._last_failure_time = time.time() - 120
        base._circuit_open = True
        base._should_try_cache()
        assert base._failure_count == 0
        assert base._circuit_open is False

    def test_not_yet_recovered_within_window(self, base: CachedStorageBase):
        base._failure_count = 5
        base._last_failure_time = time.time() - 10  # 10s ago, window=60s
        base._circuit_open = True
        assert base._should_try_cache() is False
        assert base._circuit_open is True  # still open

    def test_record_success_resets(self, base: CachedStorageBase):
        base._failure_count = 3
        base._circuit_open = True
        base._record_success()
        assert base._failure_count == 0
        assert base._circuit_open is False

    def test_safe_get_triggers_failure_on_exception(self, base: CachedStorageBase):
        broken_cache = MagicMock()
        broken_cache.get_json.side_effect = RuntimeError("cache down")
        base._cache = broken_cache
        result = base._safe_get("some_key")
        assert result is None
        assert base._failure_count == 1
        assert base._last_failure_time > 0


# ── _safe_get / _safe_set / _safe_delete ─────────────────────────────────


class TestSafeOps:
    def test_safe_set_and_get(self, base: CachedStorageBase, cache: InMemoryCacheClient):
        base._safe_set("test:k", {"data": "value"}, 60)
        cached = cache.get_json("test:k")
        assert cached == {"data": "value"}

    def test_safe_get_miss(self, base: CachedStorageBase):
        result = base._safe_get("nonexistent")
        assert result is None

    def test_safe_get_hit(self, base: CachedStorageBase):
        base._safe_set("test:k", {"x": 1}, 60)
        result = base._safe_get("test:k")
        assert result == {"x": 1}

    def test_safe_set_noop_when_disabled(self, cache: InMemoryCacheClient):
        base = CachedStorageBase(cache=cache, domain="test", default_ttl=3600, enabled=False)
        base._safe_set("test:k", {"x": 1})
        assert cache.get_json("test:k") is None

    def test_safe_get_noop_when_disabled(self, cache: InMemoryCacheClient):
        cache.set_json("test:k", {"x": 1}, 60)
        base = CachedStorageBase(cache=cache, domain="test", default_ttl=3600, enabled=False)
        # Even though cache has the value, disabled base won't read it
        assert base._safe_get("test:k") is None

    def test_safe_delete(self, base: CachedStorageBase, cache: InMemoryCacheClient):
        cache.set_json("test:k", {"x": 1}, 60)
        base._safe_delete("test:k")
        assert cache.get_json("test:k") is None

    def test_safe_delete_noop_when_disabled(self, cache: InMemoryCacheClient):
        cache.set_json("test:k", {"x": 1}, 60)
        base = CachedStorageBase(cache=cache, domain="test", default_ttl=3600, enabled=False)
        base._safe_delete("test:k")
        assert cache.get_json("test:k") == {"x": 1}  # not deleted

    def test_safe_delete_nonexistent(self, base: CachedStorageBase):
        # Should not raise
        base._safe_delete("nonexistent")

    def test_safe_set_without_ttl_uses_default(self, base: CachedStorageBase, cache: InMemoryCacheClient):
        base._safe_set("test:k", {"x": 1})  # no ttl passed
        cached = cache.get_json("test:k")
        assert cached == {"x": 1}

    def test_safe_set_exception_does_not_propagate(self, base: CachedStorageBase):
        broken_cache = MagicMock()
        broken_cache.set_json.side_effect = RuntimeError("cache down")
        base._cache = broken_cache
        # Should not raise
        base._safe_set("test:k", {"x": 1}, 60)
        assert base._failure_count == 1


# ── _safe_delete_pattern ──────────────────────────────────────────────────


class TestSafeDeletePattern:
    def test_delete_pattern(self, base: CachedStorageBase, cache: InMemoryCacheClient):
        cache.set_json("test:list/a", {"x": 1}, 60)
        cache.set_json("test:list/b", {"y": 2}, 60)
        cache.set_json("test:other/c", {"z": 3}, 60)
        base._safe_delete_pattern("test:list")
        assert cache.get_json("test:list/a") is None
        assert cache.get_json("test:list/b") is None
        assert cache.get_json("test:other/c") == {"z": 3}  # preserved

    def test_delete_pattern_noop_when_disabled(self, cache: InMemoryCacheClient):
        cache.set_json("test:k", {"x": 1}, 60)
        base = CachedStorageBase(cache=cache, domain="test", default_ttl=3600, enabled=False)
        base._safe_delete_pattern("test")
        assert cache.get_json("test:k") == {"x": 1}

    def test_delete_pattern_nonexistent(self, base: CachedStorageBase):
        # Should not raise
        base._safe_delete_pattern("nonexistent")

    def test_delete_pattern_exception_does_not_propagate(self, base: CachedStorageBase):
        broken_cache = MagicMock()
        broken_cache.delete_pattern.side_effect = RuntimeError("cache down")
        base._cache = broken_cache
        # Should not raise
        base._safe_delete_pattern("test:")


# ── _cached_read (read-through) ──────────────────────────────────────────


class TestCachedRead:
    def test_hit_returns_cached_value(self, base: CachedStorageBase):
        base._safe_set("test:k", {"data": "cached"}, 60)
        call_count = 0

        def fetch():
            nonlocal call_count
            call_count += 1
            return {"data": "fresh"}

        result = base._cached_read("test:k", fetch)
        assert result == {"data": "cached"}  # from cache
        assert call_count == 0  # fetch NOT called
        assert base._hits == 1

    def test_miss_calls_fetch(self, base: CachedStorageBase):
        call_count = 0

        def fetch():
            nonlocal call_count
            call_count += 1
            return {"data": "fresh"}

        result = base._cached_read("test:new", fetch)
        assert result == {"data": "fresh"}  # from fetch
        assert call_count == 1
        assert base._misses == 1

    def test_miss_caches_fresh_value(self, base: CachedStorageBase, cache: InMemoryCacheClient):
        def fetch():
            return {"data": "fresh"}

        base._cached_read("test:new", fetch)
        cached = cache.get_json("test:new")
        assert cached == {"data": "fresh"}

    def test_none_not_cached(self, base: CachedStorageBase, cache: InMemoryCacheClient):
        def fetch_none():
            return None

        result = base._cached_read("test:none", fetch_none)
        assert result is None
        # Verify nothing was cached
        cached = cache.get_json("test:none")
        assert cached is None  # None result never cached

    def test_disabled_skips_cache_reads(self, cache: InMemoryCacheClient):
        cache.set_json("test:k", {"data": "cached"}, 60)
        base = CachedStorageBase(cache=cache, domain="test", default_ttl=3600, enabled=False)

        def fetch():
            return {"data": "fresh"}

        result = base._cached_read("test:k", fetch)
        # Should skip cache and call fetch directly
        assert result == {"data": "fresh"}
        assert base._hits == 0  # hit not counted via disabled cache

    def test_hit_updates_hit_counter(self, base: CachedStorageBase):
        base._safe_set("test:k", {"x": 1}, 60)
        base._cached_read("test:k", lambda: {"x": 2})
        assert base._hits == 1
        # Another hit
        base._cached_read("test:k", lambda: {"x": 2})
        assert base._hits == 2

    def test_miss_updates_miss_counter(self, base: CachedStorageBase):
        base._cached_read("test:m1", lambda: {"x": 1})
        assert base._misses == 1
        base._cached_read("test:m2", lambda: {"x": 2})
        assert base._misses == 2

    def test_none_fetch_also_counts_as_miss(self, base: CachedStorageBase):
        base._cached_read("test:none", lambda: None)
        assert base._misses == 1

    def test_fetch_exception_propagates(self, base: CachedStorageBase):
        """Exceptions from fetch_fn should propagate - caller handles them."""

        def failing_fetch():
            raise ValueError("fetch error")

        with pytest.raises(ValueError, match="fetch error"):
            base._cached_read("test:fail", failing_fetch)


# ── _invalidate_keys ──────────────────────────────────────────────────────


class TestInvalidateKeys:
    def test_single_key_invalidation(self, base: CachedStorageBase, cache: InMemoryCacheClient):
        base._safe_set("test:get/sk-1", {"data": 1}, 60)
        base._invalidate_keys(("get", "sk-1"))
        assert cache.get_json("test:get/sk-1") is None

    def test_multiple_keys_invalidation(self, base: CachedStorageBase, cache: InMemoryCacheClient):
        base._safe_set("test:get/sk-1", {"data": 1}, 60)
        base._safe_set("test:get/sk-2", {"data": 2}, 60)
        base._invalidate_keys(("get", "sk-1"), ("get", "sk-2"))
        assert cache.get_json("test:get/sk-1") is None
        assert cache.get_json("test:get/sk-2") is None

    def test_pattern_invalidation(self, base: CachedStorageBase, cache: InMemoryCacheClient):
        base._safe_set("test:list/all", {"items": [1]}, 60)
        base._safe_set("test:list/recent", {"items": [2]}, 60)
        base._invalidate_keys(("list", "*"))  # trailing * means delete_pattern
        assert cache.get_json("test:list/all") is None
        assert cache.get_json("test:list/recent") is None

    def test_mixed_pattern_and_single(self, base: CachedStorageBase, cache: InMemoryCacheClient):
        base._safe_set("test:get/sk-1", {"data": 1}, 60)
        base._safe_set("test:list/all", {"items": [1]}, 60)
        base._safe_set("test:other/x", {"keep": True}, 60)
        base._invalidate_keys(("get", "sk-1"), ("list", "*"))
        assert cache.get_json("test:get/sk-1") is None
        assert cache.get_json("test:list/all") is None
        assert cache.get_json("test:other/x") == {"keep": True}  # preserved

    def test_noop_when_disabled(self, cache: InMemoryCacheClient):
        cache.set_json("test:get/sk-1", {"data": 1}, 60)
        base = CachedStorageBase(cache=cache, domain="test", default_ttl=3600, enabled=False)
        base._invalidate_keys(("get", "sk-1"))
        assert cache.get_json("test:get/sk-1") == {"data": 1}  # not deleted

    def test_nonexistent_key_no_error(self, base: CachedStorageBase):
        """Should not raise when key doesn't exist."""
        base._invalidate_keys(("get", "nonexistent"))

    def test_nonexistent_pattern_no_error(self, base: CachedStorageBase):
        """Should not raise when pattern doesn't match anything."""
        base._invalidate_keys(("nonexistent", "*"))


# ── health() ──────────────────────────────────────────────────────────────


class TestHealth:
    def test_health_returns_counters(self, base: CachedStorageBase):
        health = base.health()
        assert "hits" in health
        assert "misses" in health
        assert "errors" in health
        assert "circuit_open" in health
        assert "enabled" in health

    def test_health_initial_values(self, base: CachedStorageBase):
        health = base.health()
        assert health["hits"] == 0
        assert health["misses"] == 0
        assert health["errors"] == 0
        assert health["circuit_open"] is False
        assert health["enabled"] is True

    def test_health_tracks_hits(self, base: CachedStorageBase):
        base._hits = 5
        assert base.health()["hits"] == 5

    def test_health_tracks_misses(self, base: CachedStorageBase):
        base._misses = 3
        assert base.health()["misses"] == 3

    def test_health_tracks_errors(self, base: CachedStorageBase):
        base._errors = 2
        assert base.health()["errors"] == 2

    def test_health_tracks_circuit(self, base: CachedStorageBase):
        base._circuit_open = True
        assert base.health()["circuit_open"] is True

    def test_health_tracks_disabled(self, base: CachedStorageBase):
        base._enabled = False
        assert base.health()["enabled"] is False


# ── Integration: read-through with invalidate ────────────────────────────


class TestIntegration:
    """End-to-end scenarios combining multiple methods."""

    def test_read_then_invalidate_then_read_fresh(
        self, base: CachedStorageBase, cache: InMemoryCacheClient
    ):
        """After invalidation, next read should fetch fresh data."""
        # Seed cache
        base._safe_set("test:get/item-1", {"version": 1}, 60)
        call_count = 0

        def fetch():
            nonlocal call_count
            call_count += 1
            return {"version": 2}

        # First read hits cache
        result = base._cached_read("test:get/item-1", fetch)
        assert result == {"version": 1}
        assert call_count == 0

        # Invalidate
        base._invalidate_keys(("get", "item-1"))
        assert cache.get_json("test:get/item-1") is None

        # Second read should fetch fresh
        result = base._cached_read("test:get/item-1", fetch)
        assert result == {"version": 2}
        assert call_count == 1

    def test_circuit_breaker_skips_cache_on_failures(
        self, cache: InMemoryCacheClient
    ):
        """After circuit opens, reads bypass cache and go directly to fetch."""
        base = CachedStorageBase(cache=cache, domain="test", default_ttl=3600, enabled=True)
        # Seed cache
        base._safe_set("test:get/item", {"data": "cached"}, 60)

        # Trip the circuit breaker by making safe_get fail
        broken_cache = MagicMock()
        broken_cache.get_json.side_effect = RuntimeError("cache down")
        base._cache = broken_cache

        # Trigger failures to open circuit
        for _ in range(5):
            base._safe_get("test:get/item")

        assert base._circuit_open is True

        # Now cached_read should bypass cache and call fetch directly
        call_count = 0

        def fetch():
            nonlocal call_count
            call_count += 1
            return {"data": "fresh"}

        result = base._cached_read("test:get/item", fetch)
        assert result == {"data": "fresh"}  # from fetch, not cache
        assert call_count == 1

    def test_miss_then_write_then_hit(self, base: CachedStorageBase, cache: InMemoryCacheClient):
        """First read (miss) populates cache, second read (hit) returns cached."""
        call_count = 0

        def fetch():
            nonlocal call_count
            call_count += 1
            return {"counter": call_count}

        # First call: miss + fetch + cache
        r1 = base._cached_read("test:counter", fetch)
        assert r1 == {"counter": 1}
        assert base._misses == 1

        # Second call: hit, no fetch
        r2 = base._cached_read("test:counter", fetch)
        assert r2 == {"counter": 1}  # still first value from cache
        assert base._hits == 1
        assert call_count == 1  # fetch not called again
