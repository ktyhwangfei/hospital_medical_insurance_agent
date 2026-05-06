from typing import Protocol

from src.knowledge_extension.mcp_registry.models import (
    McpCapability,
    McpCapabilitySelectionRequest,
    McpCapabilitySelectionResult,
    McpServer,
)


class McpRegistry(Protocol):
    def register_server(self, server: McpServer) -> McpServer: ...

    def register_capability(self, capability: McpCapability) -> McpCapability: ...

    def select_capabilities(self, request: McpCapabilitySelectionRequest) -> McpCapabilitySelectionResult: ...
