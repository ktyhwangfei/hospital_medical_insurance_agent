import json
from typing import Any

from src.data_platform.cache.models import CacheBackend, CacheHealth, CacheHealthStatus


class RedisCacheClient:
    def __init__(self, redis_url: str | None = None, redis_client: Any | None = None, backend: CacheBackend = CacheBackend.REDIS):
        self._backend = backend
        self._redis = redis_client or self._create_client(redis_url)

    def get_json(self, key: str) -> dict[str, Any] | None:
        value = self._redis.get(key)
        if value is None:
            return None
        if isinstance(value, bytes):
            value = value.decode("utf-8")
        return json.loads(value)

    def set_json(self, key: str, value: dict[str, Any], ttl_seconds: int) -> None:
        self._redis.setex(key, ttl_seconds, json.dumps(value, ensure_ascii=False, sort_keys=True))

    def delete(self, key: str) -> None:
        self._redis.delete(key)

    def exists(self, key: str) -> bool:
        return bool(self._redis.exists(key))

    def health(self) -> CacheHealth:
        try:
            self._redis.ping()
        except Exception as exc:
            return CacheHealth(status=CacheHealthStatus.UNHEALTHY, backend=self._backend, available=False, details={"reason": "connection_failed", "error": exc.__class__.__name__})
        return CacheHealth(status=CacheHealthStatus.HEALTHY, backend=self._backend, available=True, details={"reason": "connected"})

    def _create_client(self, redis_url: str | None):
        if redis_url is None:
            raise RuntimeError("redis_url_required")
        import redis
        return redis.Redis.from_url(redis_url)
