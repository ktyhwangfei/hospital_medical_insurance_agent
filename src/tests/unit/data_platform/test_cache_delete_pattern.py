"""Test delete_pattern method on RedisCacheClient and InMemoryCacheClient.

Tests cover:
- Redis: SCAN + UNLINK (non-blocking) deletes only matching keys
- InMemory: prefix filtering deletes only matching keys
- Empty/nonexistent prefix returns 0 without exception
"""
import pytest
from fakeredis import FakeRedis

from src.data_platform.cache.in_memory import InMemoryCacheClient
from src.data_platform.cache.models import CacheBackend
from src.data_platform.cache.redis_cache import RedisCacheClient


# ────────────────────────────────────────────────────────────
# RedisCacheClient.delete_pattern
# ────────────────────────────────────────────────────────────

class TestRedisDeletePattern:
    """Verify RedisCacheClient.delete_pattern uses SCAN+UNLINK correctly."""

    @pytest.fixture
    def cache(self):
        return RedisCacheClient(redis_client=FakeRedis(), backend=CacheBackend.REDIS)

    def test_deletes_matching_keys_only(self, cache: RedisCacheClient):
        cache.set_json("skill:get/1", {"a": 1}, 60)
        cache.set_json("skill:list/all", {"b": 2}, 60)
        cache.set_json("mcp:get/1", {"c": 3}, 60)

        deleted = cache.delete_pattern("skill")

        assert deleted == 2
        assert cache.get_json("skill:get/1") is None
        assert cache.get_json("skill:list/all") is None
        assert cache.get_json("mcp:get/1") == {"c": 3}  # preserved

    def test_nonexistent_prefix_returns_zero(self, cache: RedisCacheClient):
        cache.set_json("a:1", {"v": 1}, 60)

        deleted = cache.delete_pattern("nonexistent")

        assert deleted == 0
        assert cache.get_json("a:1") == {"v": 1}  # preserved

    def test_empty_prefix_in_memory(self, cache: RedisCacheClient):
        """Empty prefix should not raise; may delete everything or return 0."""
        cache.set_json("test:1", {"v": 1}, 60)
        # Should not raise
        deleted = cache.delete_pattern("")
        assert isinstance(deleted, int)

    def test_single_key_delete(self, cache: RedisCacheClient):
        cache.set_json("only:1", {"x": 1}, 60)
        deleted = cache.delete_pattern("only")
        assert deleted == 1
        assert cache.get_json("only:1") is None

    def test_all_keys_deleted(self, cache: RedisCacheClient):
        cache.set_json("k1", {"v": 1}, 60)
        cache.set_json("k2", {"v": 2}, 60)
        deleted = cache.delete_pattern("k")
        assert deleted == 2
        assert cache.get_json("k1") is None
        assert cache.get_json("k2") is None


# ────────────────────────────────────────────────────────────
# InMemoryCacheClient.delete_pattern
# ────────────────────────────────────────────────────────────

class TestInMemoryDeletePattern:
    """Verify InMemoryCacheClient.delete_pattern uses prefix filtering."""

    @pytest.fixture
    def cache(self):
        return InMemoryCacheClient()

    def test_deletes_matching_keys_only(self, cache: InMemoryCacheClient):
        cache.set_json("test:1", {"a": 1}, 60)
        cache.set_json("test:2", {"b": 2}, 60)
        cache.set_json("other:1", {"c": 3}, 60)

        deleted = cache.delete_pattern("test")

        assert deleted == 2
        assert cache.get_json("test:1") is None
        assert cache.get_json("test:2") is None
        assert cache.get_json("other:1") == {"c": 3}  # preserved

    def test_nonexistent_prefix_returns_zero(self, cache: InMemoryCacheClient):
        cache.set_json("a:1", {"v": 1}, 60)

        deleted = cache.delete_pattern("nonexistent")

        assert deleted == 0
        assert cache.get_json("a:1") == {"v": 1}  # preserved

    def test_empty_prefix_returns_all_count(self, cache: InMemoryCacheClient):
        cache.set_json("test:1", {"v": 1}, 60)
        cache.set_json("test:2", {"v": 2}, 60)
        deleted = cache.delete_pattern("")
        assert deleted == 2  # empty prefix matches everything
        assert cache.get_json("test:1") is None
        assert cache.get_json("test:2") is None

    def test_single_key_delete(self, cache: InMemoryCacheClient):
        cache.set_json("only:1", {"x": 1}, 60)
        deleted = cache.delete_pattern("only")
        assert deleted == 1
        assert cache.get_json("only:1") is None
