from src.data_platform.storage.mcp.in_memory import InMemoryMcpStorage
from src.knowledge_extension.mcp_registry.config_import import import_mcp_servers_config
from src.knowledge_extension.mcp_registry.discovery import FakeMcpDiscoveryClient, McpToolDiscoveryService


def test_mcp_tool_discovery_saves_tools_list_result():
    storage = InMemoryMcpStorage()
    server = import_mcp_servers_config({"mcpServers": {"drawio": {"command": "npx", "args": ["@next-ai-drawio/mcp-server@latest"]}}}).servers[0]
    storage.save_server(server)
    discovery = McpToolDiscoveryService(storage, FakeMcpDiscoveryClient(tools=[{"name": "create_diagram", "description": "Create draw.io diagram", "inputSchema": {"type": "object", "properties": {"xml": {"type": "string"}}}}]))

    result = discovery.discover_tools("drawio")

    assert result.server_id == "drawio"
    assert result.discovered_count == 1
    capability = storage.list_capabilities()[0]
    assert capability.name == "create_diagram"
    assert capability.input_schema["properties"]["xml"]["type"] == "string"
    assert capability.discovery_source == "auto_tools_list"
    assert capability.discovery_payload["name"] == "create_diagram"
