from src.knowledge_extension.mcp_registry.models import McpTransportType
from src.knowledge_extension.mcp_registry.stdio_client import StdioMcpClient
from src.knowledge_extension.mcp_registry.storage_provider import get_shared_mcp_storage
from src.runtime.api.schemas import AgentResponse

_stdio_client = StdioMcpClient(timeout_seconds=30)

_SESSION_TOOL_PATTERNS = ("start_session", "init_session", "create_session")


def _get_storage():
    return get_shared_mcp_storage()


def invoke_mcp_tool_for_message(message: str) -> AgentResponse:
    storage = _get_storage()
    capability = _match_capability(message, storage)
    if capability is None:
        return AgentResponse(
            status="no_matching_tool",
            uncertainties=["未找到与当前请求匹配的 MCP 工具"],
            citations=[{"source_type": "mcp_registry", "source_id": "capability_lookup", "summary": "未找到匹配的 MCP 能力"}],
        )

    server = storage.get_server(capability.server_id)
    if server is None:
        return AgentResponse(
            status="server_not_found",
            uncertainties=[f"MCP 服务 {capability.server_id} 未注册"],
            citations=[{"source_type": "mcp_registry", "source_id": capability.server_id, "summary": "服务未注册"}],
        )

    if server.transport != McpTransportType.STDIO:
        return AgentResponse(
            status="unsupported_transport",
            uncertainties=[f"不支持的传输类型: {server.transport.value}"],
            citations=[{"source_type": "mcp_registry", "source_id": server.server_id, "summary": "传输类型不支持"}],
        )

    requires_session = _server_requires_session(storage, server.server_id)
    arguments = _extract_arguments(message, capability)
    tool_calls = []
    if requires_session:
        tool_calls.append({"name": "start_session", "arguments": {}})
    tool_calls.append({"name": capability.name, "arguments": arguments})

    try:
        sequence_results = _stdio_client.call_tool_sequence_sync(server, tool_calls)
    except Exception as exc:
        return AgentResponse(
            status="invocation_failed",
            uncertainties=[f"调用 MCP 工具序列失败: {exc}"],
            citations=[{"source_type": "mcp_tool", "source_id": capability.capability_id, "summary": "工具调用失败"}],
        )

    session_result = sequence_results[0] if requires_session and len(sequence_results) > 1 else None
    tool_result = sequence_results[-1] if sequence_results else {}

    has_error = isinstance(tool_result, dict) and tool_result.get("isError") is True
    if has_error:
        error_text = _extract_error_text(tool_result)
        return AgentResponse(
            status="tool_error",
            uncertainties=[f"MCP 工具 {capability.name} 返回错误: {error_text}"],
            citations=[{"source_type": "mcp_tool", "source_id": capability.capability_id, "summary": f"工具返回错误: {error_text}"}],
        )

    response_result = _sanitize_result(tool_result)
    if session_result is not None and isinstance(session_result, dict) and not session_result.get("isError"):
        response_result["session"] = _sanitize_result(session_result)

    return AgentResponse(
        status="success",
        result=response_result,
        citations=[{"source_type": "mcp_tool", "source_id": capability.capability_id, "summary": f"已调用 MCP 工具: {capability.name}"}],
    )


def _match_capability(message: str, storage):
    capabilities = storage.list_capabilities()
    if not capabilities:
        return None

    keywords = _extract_keywords(message)
    scored = []
    for cap in capabilities:
        if not cap.enabled:
            continue
        score = _score_capability(cap, keywords, message)
        if score > 0:
            scored.append((score, cap))

    if not scored:
        return None

    scored.sort(key=lambda x: x[0], reverse=True)
    return scored[0][1]


def _extract_keywords(message: str) -> set[str]:
    tool_keywords = {"画图", "画一下", "画个", "创建图表", "diagram", "draw", "导出", "export", "图表", "架构图", "流程图"}
    return {kw for kw in tool_keywords if kw in message}


def _score_capability(cap, keywords: set[str], message: str) -> int:
    score = 0
    if keywords & {"画图", "draw", "diagram", "架构图", "流程图", "画一下", "画个", "图表"}:
        if any(kw in cap.name.lower() for kw in ("diagram", "draw", "create_new_diagram")):
            score += 10
        if any(kw in cap.description.lower() for kw in ("diagram", "draw")):
            score += 5
    if keywords & {"导出", "export"}:
        if "export" in cap.name.lower():
            score += 10
    if cap.name in message:
        score += 20
    words = [w for w in message.split() if len(w) > 2]
    if any(word in cap.name.lower() for word in words):
        score += 3
    if cap.name.startswith(_SESSION_TOOL_PATTERNS):
        score = 0
    return score


def _server_requires_session(storage, server_id: str) -> bool:
    for cap in storage.list_capabilities():
        if cap.server_id == server_id and any(
            pattern in cap.name for pattern in _SESSION_TOOL_PATTERNS
        ):
            return True
    return False


def _extract_arguments(message: str, capability) -> dict:
    arguments = {}
    input_schema = capability.input_schema
    if not isinstance(input_schema, dict):
        return arguments

    required = input_schema.get("required", [])
    if "xml" in required or "xml" in input_schema.get("properties", {}):
        arguments["xml"] = _generate_simple_diagram_xml(message)
    if "path" in input_schema.get("properties", {}):
        arguments["path"] = "diagram.drawio"
    return arguments


def _generate_simple_diagram_xml(message: str) -> str:
    return (
        '<mxGraphModel><root>'
        '<mxCell id="0"/>'
        '<mxCell id="1" parent="0"/>'
        '<mxCell id="2" value="Module A" style="rounded=1;fillColor=#dae8fc;" vertex="1" parent="1">'
        '<mxGeometry x="100" y="100" width="120" height="60" as="geometry"/></mxCell>'
        '<mxCell id="3" value="Module B" style="rounded=1;fillColor=#d5e8d4;" vertex="1" parent="1">'
        '<mxGeometry x="300" y="100" width="120" height="60" as="geometry"/></mxCell>'
        '<mxCell id="4" value="" style="endArrow=classic;" edge="1" source="2" target="3" parent="1"/>'
        '</root></mxGraphModel>'
    )


def _extract_error_text(result: dict) -> str:
    content = result.get("content", [])
    if isinstance(content, list):
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                return item.get("text", "未知错误")
    return result.get("message", "未知错误")


def _sanitize_result(result: dict) -> dict:
    if not isinstance(result, dict):
        return {"raw": str(result)}
    content = result.get("content", [])
    if isinstance(content, list):
        texts = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                texts.append(item.get("text", ""))
        if texts:
            return {"tool_output": "\n".join(texts), "content_blocks": content}
    return result