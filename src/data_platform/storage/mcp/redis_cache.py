from src.data_platform.cache.in_memory import InMemoryCacheClient
from src.data_platform.cache.ports import CacheClient
from src.data_platform.storage.mcp.models import McpStorageHealth, McpStorageHealthStatus
from src.knowledge_extension.mcp_registry.models import McpCapability


class RedisMcpCache:
    def __init__(self, redis_url: str | None = None, cache_client: CacheClient | None = None):
        self._cache = cache_client or InMemoryCacheClient()
        self._redis_url = redis_url

    def save_capability_list(self, scenario: str, capabilities: list[McpCapability], ttl_seconds: int) -> None:
        self._cache.set_json(f"mcp:capabilities:{scenario}", {"items": [item.model_dump(mode="json") for item in capabilities]}, ttl_seconds)

    def load_capability_list(self, scenario: str) -> list[McpCapability] | None:
        payload = self._cache.get_json(f"mcp:capabilities:{scenario}")
        if payload is None:
            return None
        return [McpCapability(**item) for item in payload["items"]]

    def reserve_invocation(self, request_id: str, ttl_seconds: int) -> bool:
        return self._cache.reserve(f"mcp:{request_id}", ttl_seconds)

    def acquire_invocation_lock(self, capability_id: str, owner: str, ttl_seconds: int) -> bool:
        return self._cache.acquire(f"mcp:capability:{capability_id}", ttl_seconds, owner)

    def release_invocation_lock(self, capability_id: str, owner: str) -> bool:
        return self._cache.release(f"mcp:capability:{capability_id}", owner)

    def health(self) -> McpStorageHealth:
        cache_health = self._cache.health()
        status = McpStorageHealthStatus.HEALTHY if cache_health.available else McpStorageHealthStatus.UNHEALTHY
        return McpStorageHealth(status=status, postgres_available=False, redis_available=cache_health.available, details={"backend": cache_health.backend.value, **cache_health.details})
