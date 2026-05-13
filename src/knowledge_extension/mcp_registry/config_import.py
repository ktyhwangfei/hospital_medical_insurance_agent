from typing import Any

from pydantic import BaseModel, Field

from src.knowledge_extension.mcp_registry.models import McpAuthType, McpDiscoveryStatus, McpServer, McpServerStatus, McpTransportType


class McpServersImportResult(BaseModel):
    servers: list[McpServer] = Field(default_factory=list)


def import_mcp_servers_config(config: dict[str, Any]) -> McpServersImportResult:
    servers_config = config.get("mcpServers")
    if not isinstance(servers_config, dict):
        raise ValueError("mcpServers 必须是对象")

    servers: list[McpServer] = []
    for server_id, server_config in servers_config.items():
        if not isinstance(server_id, str) or not server_id.strip():
            raise ValueError("mcp server id 不能为空")
        if not isinstance(server_config, dict):
            raise ValueError(f"{server_id} 配置必须是对象")
        servers.append(_server_from_config(server_id, server_config))
    return McpServersImportResult(servers=servers)


def _server_from_config(server_id: str, server_config: dict[str, Any]) -> McpServer:
    command = server_config.get("command")
    args = server_config.get("args", [])
    env = server_config.get("env", {})
    cwd = server_config.get("cwd")

    metadata = server_config.get("metadata") if isinstance(server_config.get("metadata"), dict) else {}

    supported_scenarios = _parse_string_set(server_config.get("supported_scenarios"))
    required_roles = _parse_string_set(server_config.get("required_roles"))
    if supported_scenarios:
        metadata["supported_scenarios"] = sorted(supported_scenarios)
    if required_roles:
        metadata["required_roles"] = sorted(required_roles)

    if isinstance(command, str) and command.strip():
        if not isinstance(args, list) or not all(isinstance(item, str) for item in args):
            raise ValueError(f"{server_id}.args 必须是字符串数组")
        if not isinstance(env, dict):
            raise ValueError(f"{server_id}.env 必须是对象")
        if cwd is not None and not isinstance(cwd, str):
            raise ValueError(f"{server_id}.cwd 必须是字符串")
        return McpServer(
            server_id=server_id,
            name=server_config.get("name") or server_id,
            description=server_config.get("description"),
            endpoint=f"stdio://{server_id}",
            transport=McpTransportType.STDIO,
            status=McpServerStatus.ENABLED,
            protocol_version=server_config.get("protocol_version") or "2025-03-26",
            auth_type=McpAuthType.NONE,
            connection_config={"command": command, "args": args, "env": env, "cwd": cwd},
            discovery_status=McpDiscoveryStatus.NOT_DISCOVERED,
            metadata=metadata,
        )

    endpoint = server_config.get("url") or server_config.get("endpoint")
    if not isinstance(endpoint, str) or not endpoint.strip():
        raise ValueError(f"{server_id} 必须配置 command 或 endpoint/url")
    transport = server_config.get("transport") or McpTransportType.STREAMABLE_HTTP.value
    return McpServer(
        server_id=server_id,
        name=server_config.get("name") or server_id,
        description=server_config.get("description"),
        endpoint=endpoint,
        transport=transport,
        status=McpServerStatus.ENABLED,
        protocol_version=server_config.get("protocol_version") or "2025-03-26",
        auth_type=server_config.get("auth_type") or McpAuthType.NONE,
        auth_headers=server_config.get("headers") if isinstance(server_config.get("headers"), dict) else {},
        connection_config={key: value for key, value in server_config.items() if key in {"timeout_seconds", "retry", "headers"}},
        discovery_status=McpDiscoveryStatus.NOT_DISCOVERED,
        metadata=metadata,
    )


def _parse_string_set(value: Any) -> set[str]:
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