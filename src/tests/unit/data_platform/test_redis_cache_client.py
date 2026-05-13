from src.data_platform.cache.models import CacheBackend, CacheHealthStatus
from src.data_platform.cache.redis_cache import RedisCacheClient


class FakeRedis:
    def __init__(self):
        self.values: dict[str, str] = {}
        self.expirations: dict[str, int] = {}

    def setex(self, key: str, ttl: int, value: str):
        self.values[key] = value
        self.expirations[key] = ttl

    def get(self, key: str):
        return self.values.get(key)

    def delete(self, key: str):
        self.values.pop(key, None)

    def exists(self, key: str):
        return 1 if key in self.values else 0

    def ping(self):
        return True


def test_redis_cache_client_stores_json():
    redis = FakeRedis()
    cache = RedisCacheClient(redis_client=redis, backend=CacheBackend.REDIS)

    cache.set_json("k", {"v": 1}, ttl_seconds=30)

    assert cache.get_json("k") == {"v": 1}
    assert redis.expirations["k"] == 30


def test_redis_cache_client_health_uses_backend():
    cache = RedisCacheClient(redis_client=FakeRedis(), backend=CacheBackend.VALKEY)

    health = cache.health()

    assert health.status == CacheHealthStatus.HEALTHY
    assert health.backend == CacheBackend.VALKEY
    assert health.available is True
