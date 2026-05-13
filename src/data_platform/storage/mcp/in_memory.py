from src.data_platform.storage.mcp.models import McpStorageHealth, McpStorageHealthStatus
from src.knowledge_extension.mcp_registry.models import McpCapability, McpServer


class InMemoryMcpStorage:
    def __init__(self) -> None:
        self._servers: dict[str, McpServer] = {}
        self._capabilities: dict[str, McpCapability] = {}

    def save_server(self, server: McpServer) -> None:
        self._servers[server.server_id] = server.model_copy(deep=True)

    def get_server(self, server_id: str) -> McpServer | None:
        server = self._servers.get(server_id)
        return None if server is None else server.model_copy(deep=True)

    def list_servers(self) -> list[McpServer]:
        return [self._servers[key].model_copy(deep=True) for key in sorted(self._servers)]

    def save_capability(self, capability: McpCapability) -> None:
        self._capabilities[capability.capability_id] = capability.model_copy(deep=True)

    def get_capability(self, capability_id: str) -> McpCapability | None:
        capability = self._capabilities.get(capability_id)
        return None if capability is None else capability.model_copy(deep=True)

    def list_capabilities(self) -> list[McpCapability]:
        return [self._capabilities[key].model_copy(deep=True) for key in sorted(self._capabilities)]

    def delete_capability(self, capability_id: str) -> bool:
        if capability_id in self._capabilities:
            del self._capabilities[capability_id]
            return True
        return False

    def health(self) -> McpStorageHealth:
        return McpStorageHealth(
            status=McpStorageHealthStatus.HEALTHY,
            postgres_available=True,
            redis_available=True,
            details={"backend": "in_memory"},
        )
