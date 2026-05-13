from src.knowledge_extension.mcp_registry.config_import import import_mcp_servers_config
from src.knowledge_extension.mcp_registry.models import McpTransportType


def test_import_mcp_servers_config_converts_stdio_server():
    result = import_mcp_servers_config(
        {
            "mcpServers": {
                "drawio": {
                    "command": "npx",
                    "args": ["@next-ai-drawio/mcp-server@latest"],
                }
            }
        }
    )

    assert len(result.servers) == 1
    server = result.servers[0]
    assert server.server_id == "drawio"
    assert server.name == "drawio"
    assert server.endpoint == "stdio://drawio"
    assert server.transport is McpTransportType.STDIO
    assert server.connection_config["command"] == "npx"
    assert server.connection_config["args"] == ["@next-ai-drawio/mcp-server@latest"]


def test_import_mcp_servers_config_with_supported_scenarios():
    result = import_mcp_servers_config(
        {
            "mcpServers": {
                "drawio": {
                    "command": "npx",
                    "args": ["@next-ai-drawio/mcp-server@latest"],
                    "supported_scenarios": ["mcp_tool_invocation"],
                    "required_roles": ["cashier", "medical_office"],
                }
            }
        }
    )

    assert len(result.servers) == 1
    server = result.servers[0]
    assert server.metadata.get("supported_scenarios") == ["mcp_tool_invocation"]
    assert set(server.metadata.get("required_roles", [])) == {"cashier", "medical_office"}


def test_import_mcp_servers_config_with_comma_separated_scenarios():
    result = import_mcp_servers_config(
        {
            "mcpServers": {
                "multi": {
                    "command": "npx",
                    "args": ["some-mcp@1.0"],
                    "supported_scenarios": "mcp_tool_invocation, settlement_exception_guidance",
                }
            }
        }
    )

    assert len(result.servers) == 1
    server = result.servers[0]
    assert set(server.metadata.get("supported_scenarios", [])) == {"mcp_tool_invocation", "settlement_exception_guidance"}


def test_import_mcp_servers_config_with_http_server():
    result = import_mcp_servers_config(
        {
            "mcpServers": {
                "knowledge": {
                    "url": "https://mcp.example.test/sse",
                    "supported_scenarios": ["settlement_exception_guidance"],
                }
            }
        }
    )

    assert len(result.servers) == 1
    server = result.servers[0]
    assert server.endpoint == "https://mcp.example.test/sse"
    assert server.metadata.get("supported_scenarios") == ["settlement_exception_guidance"]
