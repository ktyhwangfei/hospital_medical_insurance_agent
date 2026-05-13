from typing import Any, Protocol

from pydantic import BaseModel

from src.data_platform.storage.mcp.ports import McpStorage
from src.knowledge_extension.mcp_registry.models import McpCapability, McpCapabilityType, McpDiscoverySource, McpDiscoveryStatus, McpRiskLevel, McpServer, McpTransportType
from src.knowledge_extension.mcp_registry.stdio_client import StdioMcpClient


class McpDiscoveryResult(BaseModel):
    server_id: str
    discovered_count: int
    error: str | None = None


def _parse_set_from_metadata(metadata: dict, key: str) -> set[str]:
    value = metadata.get(key)
    if value is None:
        return set()
    if isinstance(value, set):
        return {str(v) for v in value if str(v).strip()}
    if isinstance(value, (list, tuple)):
        return {str(v) for v in value if str(v).strip()}
    if isinstance(value, str):
        items = [item.strip() for item in value.split(",")]
        return {item for item in items if item}
    return set()


class McpDiscoveryClient(Protocol):
    def list_tools(self, server: McpServer) -> list[dict[str, Any]]: ...


class FakeMcpDiscoveryClient:
    def __init__(self, tools: list[dict[str, Any]] | None = None):
        self._tools = tools or []

    def list_tools(self, server: McpServer) -> list[dict[str, Any]]:
        return self._tools


class McpToolDiscoveryService:
    def __init__(self, storage: McpStorage, client: McpDiscoveryClient | None = None):
        self._storage = storage
        self._client = client
        self._stdio_client = StdioMcpClient()

    def discover_tools(self, server_id: str) -> McpDiscoveryResult:
        server = self._storage.get_server(server_id)
        if server is None:
            raise ValueError("MCP Server 不存在")
        try:
            tools = self._resolve_tools(server)
            for tool in tools:
                self._storage.save_capability(self._capability_from_tool(server, tool))
            updated_server = server.model_copy(update={"discovery_status": McpDiscoveryStatus.SUCCESS, "last_error": None})
            self._storage.save_server(updated_server)
            return McpDiscoveryResult(server_id=server_id, discovered_count=len(tools))
        except Exception as exc:
            updated_server = server.model_copy(update={"discovery_status": McpDiscoveryStatus.FAILED, "last_error": str(exc)})
            self._storage.save_server(updated_server)
            return McpDiscoveryResult(server_id=server_id, discovered_count=0, error=str(exc))

    def _resolve_tools(self, server: McpServer) -> list[dict[str, Any]]:
        if self._client is not None:
            return self._client.list_tools(server)
        if server.transport == McpTransportType.STDIO:
            return self._stdio_client.list_tools_sync(server)
        return []

    def _capability_from_tool(self, server: McpServer, tool: dict[str, Any]) -> McpCapability:
        name = tool.get("name")
        if not isinstance(name, str) or not name.strip():
            raise ValueError("tools/list 返回缺少 name")
        description = tool.get("description") if isinstance(tool.get("description"), str) else name
        input_schema = tool.get("inputSchema") if isinstance(tool.get("inputSchema"), dict) else {}
        annotations = tool.get("annotations") if isinstance(tool.get("annotations"), dict) else {}
        metadata = server.metadata or {}
        supported_scenarios = _parse_set_from_metadata(metadata, "supported_scenarios")
        required_roles = _parse_set_from_metadata(metadata, "required_roles")
        return McpCapability(
            capability_id=f"{server.server_id}:{name}",
            server_id=server.server_id,
            name=name,
            title=tool.get("title") if isinstance(tool.get("title"), str) else None,
            capability_type=McpCapabilityType.TOOL,
            description=description,
            supported_scenarios=supported_scenarios,
            required_roles=required_roles,
            risk_level=McpRiskLevel.LOW,
            input_schema=input_schema,
            output_schema={},
            annotations=annotations,
            invocation_config={"method": "tools/call", "transport": server.transport.value},
            discovery_source=McpDiscoverySource.AUTO_TOOLS_LIST,
            discovery_payload=tool,
            enabled=True,
        )
