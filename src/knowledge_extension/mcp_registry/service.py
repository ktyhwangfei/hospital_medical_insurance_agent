"""MCP Registry Service — runtime essentials (admin CRUD removed)."""

import logging
from typing import Optional

from src.knowledge_extension.mcp_registry.models import McpCapability, McpServer

logger = logging.getLogger(__name__)


class McpRegistryService:
    """Lightweight MCP registry — admin CRUD endpoints removed.

    Retained for runtime scenario execution and MCP tool invocation.
    Uses an in-memory store by default.
    """

    def __init__(self):
        self._servers: dict[str, McpServer] = {}
        self._capabilities: dict[str, McpCapability] = {}

    def register_server(self, server: McpServer) -> None:
        self._servers[server.server_id] = server
        logger.info("MCP server registered: %s", server.server_id)

    def get_server(self, server_id: str) -> Optional[McpServer]:
        return self._servers.get(server_id)

    def list_servers(self) -> list[McpServer]:
        return list(self._servers.values())

    def register_capability(self, capability: McpCapability) -> None:
        self._capabilities[capability.capability_id] = capability

    def get_capability(self, capability_id: str) -> Optional[McpCapability]:
        return self._capabilities.get(capability_id)

    def list_capabilities(self, server_id: Optional[str] = None) -> list[McpCapability]:
        caps = self._capabilities.values()
        if server_id:
            caps = [c for c in caps if c.server_id == server_id]
        return list(caps)
