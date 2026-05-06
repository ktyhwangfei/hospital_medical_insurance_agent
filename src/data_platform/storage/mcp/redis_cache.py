from src.data_platform.storage.mcp.models import McpStorageHealth, McpStorageHealthStatus


class RedisMcpCache:
    def __init__(self, redis_url: str):
        self._redis_url = redis_url

    def health(self) -> McpStorageHealth:
        return McpStorageHealth(
            status=McpStorageHealthStatus.UNHEALTHY,
            postgres_available=False,
            redis_available=False,
            details={"backend": "redis", "reason": "driver_not_configured", "unchecked_dependencies": "postgresql"},
        )
