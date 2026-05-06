from src.data_platform.cache.in_memory import InMemoryCacheClient
from src.data_platform.cache.models import CacheBackend, CacheHealthStatus


def test_in_memory_cache_stores_json_deep_copies():
    cache = InMemoryCacheClient()
    value = {"items": [{"id": "cap-1"}]}
    cache.set_json("capabilities", value, ttl_seconds=60)
    value["items"][0]["id"] = "mutated"

    loaded = cache.get_json("capabilities")
    loaded["items"][0]["id"] = "changed"

    assert cache.get_json("capabilities")["items"][0]["id"] == "cap-1"


def test_in_memory_cache_health():
    health = InMemoryCacheClient().health()
    assert health.status == CacheHealthStatus.HEALTHY
    assert health.backend == CacheBackend.IN_MEMORY
    assert health.available is True


def test_in_memory_cache_delete_and_exists():
    cache = InMemoryCacheClient()
    cache.set_json("k", {"v": 1}, ttl_seconds=60)

    assert cache.exists("k") is True
    cache.delete("k")
    assert cache.exists("k") is False
    assert cache.get_json("k") is None
