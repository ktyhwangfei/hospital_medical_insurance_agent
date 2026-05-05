from src.data_platform.storage.mcp.models import McpStorageHealth, McpStorageHealthStatus


class PostgresMcpStorage:
    def __init__(self, dsn: str):
        self._dsn = dsn

    def health(self) -> McpStorageHealth:
        return McpStorageHealth(
            status=McpStorageHealthStatus.UNHEALTHY,
            postgres_available=False,
            redis_available=True,
            details={"backend": "postgresql", "reason": "driver_not_configured"},
        )
