"""Test RedisCacheClient implements all 4 missing Protocols.

Tests cover:
- ShortStateStore (save_state, load_state, delete_state)
- IdempotencyStore (reserve, complete, get_result)
- RateLimiter (increment_and_check)
- DistributedLock (acquire, release)

Uses fakeredis.FakeRedis() for isolated in-memory Redis simulation — no real Redis needed.
"""
import pytest
from fakeredis import FakeRedis

from src.data_platform.cache.models import CacheBackend
from src.data_platform.cache.redis_cache import RedisCacheClient


# ────────────────────────────────────────────────────────────
# Fixtures
# ────────────────────────────────────────────────────────────

@pytest.fixture
def cache():
    """Create RedisCacheClient backed by fakeredis for isolated testing."""
    return RedisCacheClient(redis_client=FakeRedis(), backend=CacheBackend.REDIS)


# ────────────────────────────────────────────────────────────
# ShortStateStore Protocol
# ────────────────────────────────────────────────────────────

class TestShortStateStore:
    def test_save_and_load_state(self, cache: RedisCacheClient):
        cache.save_state("ns1", "key1", {"step": "check", "status": "ok"}, ttl_seconds=60)
        result = cache.load_state("ns1", "key1")
        assert result == {"step": "check", "status": "ok"}

    def test_load_state_returns_none_for_missing(self, cache: RedisCacheClient):
        assert cache.load_state("ns1", "nonexistent") is None

    def test_delete_state_removes_data(self, cache: RedisCacheClient):
        cache.save_state("ns1", "key1", {"data": 123}, ttl_seconds=60)
        cache.delete_state("ns1", "key1")
        assert cache.load_state("ns1", "key1") is None

    def test_state_namespace_isolation(self, cache: RedisCacheClient):
        cache.save_state("ns1", "key", {"from": "ns1"}, ttl_seconds=60)
        cache.save_state("ns2", "key", {"from": "ns2"}, ttl_seconds=60)
        assert cache.load_state("ns1", "key") == {"from": "ns1"}
        assert cache.load_state("ns2", "key") == {"from": "ns2"}
        cache.delete_state("ns1", "key")
        assert cache.load_state("ns1", "key") is None
        assert cache.load_state("ns2", "key") == {"from": "ns2"}

    def test_state_ttl_is_set(self, cache: RedisCacheClient):
        """Verify TTL is set on the underlying Redis key."""
        cache.save_state("ns", "k", {"v": 1}, ttl_seconds=30)
        ttl = cache._redis.ttl("state:ns:k")
        assert 0 < ttl <= 30  # TTL should be set (positive, ≤ requested)


# ────────────────────────────────────────────────────────────
# IdempotencyStore Protocol
# ────────────────────────────────────────────────────────────

class TestIdempotencyStore:
    def test_reserve_first_call_returns_true(self, cache: RedisCacheClient):
        assert cache.reserve("op-1", ttl_seconds=60) is True

    def test_reserve_second_call_returns_false(self, cache: RedisCacheClient):
        cache.reserve("op-1", ttl_seconds=60)
        assert cache.reserve("op-1", ttl_seconds=60) is False

    def test_complete_stores_result(self, cache: RedisCacheClient):
        cache.reserve("op-1", ttl_seconds=60)
        cache.complete("op-1", {"result": "success", "code": 200}, ttl_seconds=120)
        result = cache.get_result("op-1")
        assert result == {"result": "success", "code": 200}

    def test_get_result_returns_none_before_complete(self, cache: RedisCacheClient):
        cache.reserve("op-1", ttl_seconds=60)
        assert cache.get_result("op-1") is None

    def test_get_result_returns_none_for_unknown(self, cache: RedisCacheClient):
        assert cache.get_result("unknown-op") is None

    def test_reserve_sets_ttl(self, cache: RedisCacheClient):
        cache.reserve("op-ttl", ttl_seconds=30)
        ttl = cache._redis.ttl("idempotency:op-ttl")
        assert 0 < ttl <= 30

    def test_complete_overwrites_reserved(self, cache: RedisCacheClient):
        """complete() should work even without a prior reserve() call."""
        cache.complete("op-direct", {"done": True}, ttl_seconds=60)
        assert cache.get_result("op-direct") == {"done": True}


# ────────────────────────────────────────────────────────────
# RateLimiter Protocol
# ────────────────────────────────────────────────────────────

class TestRateLimiter:
    def test_first_request_allowed(self, cache: RedisCacheClient):
        result = cache.increment_and_check("api:user1", limit=10, window_seconds=60)
        assert result.allowed is True
        assert result.current_count == 1
        assert result.limit == 10
        assert result.window_seconds == 60

    def test_under_limit_allowed(self, cache: RedisCacheClient):
        for _ in range(5):
            result = cache.increment_and_check("api:user2", limit=10, window_seconds=60)
        assert result.allowed is True
        assert result.current_count == 5  # INCR starts at 1, 5 calls → count=5

    def test_over_limit_blocked(self, cache: RedisCacheClient):
        for _ in range(3):
            cache.increment_and_check("api:user3", limit=3, window_seconds=60)
        # 4th call should be blocked
        result = cache.increment_and_check("api:user3", limit=3, window_seconds=60)
        assert result.allowed is False
        assert result.current_count == 4

    def test_rate_limit_keys_are_independent(self, cache: RedisCacheClient):
        for _ in range(5):
            cache.increment_and_check("api:burst1", limit=10, window_seconds=60)
        result = cache.increment_and_check("api:burst2", limit=10, window_seconds=60)
        assert result.allowed is True
        assert result.current_count == 1

    def test_rate_limit_sets_ttl_on_first_call(self, cache: RedisCacheClient):
        cache.increment_and_check("api:ttl-check", limit=5, window_seconds=30)
        ttl = cache._redis.ttl("rate:api:ttl-check")
        assert 0 < ttl <= 30


# ────────────────────────────────────────────────────────────
# DistributedLock Protocol
# ────────────────────────────────────────────────────────────

class TestDistributedLock:
    def test_acquire_returns_true(self, cache: RedisCacheClient):
        assert cache.acquire("resource-1", ttl_seconds=30, owner="worker-1") is True

    def test_acquire_exclusive_by_owner(self, cache: RedisCacheClient):
        cache.acquire("resource-1", ttl_seconds=30, owner="worker-1")
        # Second acquire with different owner should fail
        assert cache.acquire("resource-1", ttl_seconds=30, owner="worker-2") is False

    def test_release_by_correct_owner_succeeds(self, cache: RedisCacheClient):
        cache.acquire("resource-1", ttl_seconds=30, owner="worker-1")
        assert cache.release("resource-1", owner="worker-1") is True

    def test_release_by_wrong_owner_fails(self, cache: RedisCacheClient):
        cache.acquire("resource-1", ttl_seconds=30, owner="worker-1")
        assert cache.release("resource-1", owner="worker-2") is False

    def test_release_of_unlocked_key_fails(self, cache: RedisCacheClient):
        assert cache.release("nonexistent-lock", owner="worker-1") is False

    def test_lock_becomes_available_after_release(self, cache: RedisCacheClient):
        cache.acquire("resource-2", ttl_seconds=30, owner="worker-1")
        cache.release("resource-2", owner="worker-1")
        assert cache.acquire("resource-2", ttl_seconds=30, owner="worker-2") is True

    def test_lock_ttl_is_set(self, cache: RedisCacheClient):
        cache.acquire("resource-ttl", ttl_seconds=30, owner="worker-1")
        ttl = cache._redis.ttl("lock:resource-ttl")
        assert 0 < ttl <= 30
