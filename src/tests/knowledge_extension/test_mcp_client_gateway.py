from src.knowledge_extension.common.models import KnowledgeExtensionStatus
from src.knowledge_extension.mcp_registry.client_gateway import InMemoryMcpClientGateway
from src.knowledge_extension.mcp_registry.models import (
    McpCapability,
    McpCapabilityType,
    McpRiskLevel,
    McpServer,
    McpServerStatus,
    McpTransportType,
)


def _server() -> McpServer:
    return McpServer(
        server_id="srv-policy",
        name="医保政策 MCP",
        endpoint="memory://policy",
        transport=McpTransportType.STREAMABLE_HTTP,
        status=McpServerStatus.ENABLED,
    )


def _capability(risk_level: McpRiskLevel = McpRiskLevel.LOW) -> McpCapability:
    return McpCapability(
        capability_id="cap-policy-search",
        server_id="srv-policy",
        name="医保政策检索",
        capability_type=McpCapabilityType.TOOL,
        description="检索医保政策条款",
        risk_level=risk_level,
    )


def test_handshake_discovers_capabilities():
    gateway = InMemoryMcpClientGateway(discovered_capabilities=[_capability()])

    result = gateway.handshake(_server())

    assert result.status is KnowledgeExtensionStatus.SUCCESS
    assert result.discovered_capabilities[0].capability_id == "cap-policy-search"


def test_low_risk_tool_invocation_succeeds():
    gateway = InMemoryMcpClientGateway(tool_results={"cap-policy-search": {"answer": "政策条款"}})

    result = gateway.invoke_tool(_server(), _capability(), {"keyword": "结算"})

    assert result.status is KnowledgeExtensionStatus.SUCCESS
    assert result.output == {"answer": "政策条款"}


def test_high_risk_tool_invocation_blocked():
    gateway = InMemoryMcpClientGateway()

    result = gateway.invoke_tool(_server(), _capability(McpRiskLevel.HIGH), {"patient_id": "P001"})

    assert result.status is KnowledgeExtensionStatus.HIGH_RISK_BLOCKED
    assert result.output == {}


def test_discovered_capabilities_deep_copy_on_handshake():
    gateway = InMemoryMcpClientGateway(discovered_capabilities=[_capability()])

    result1 = gateway.handshake(_server())
    result1.discovered_capabilities[0].name = "被篡改的名字"

    result2 = gateway.handshake(_server())
    assert result2.discovered_capabilities[0].name == "医保政策检索"


def test_tool_results_constructor_deep_copy():
    external_results: dict = {"cap-policy-search": {"answer": "原始答案", "nested": {"key": "value"}}}
    gateway = InMemoryMcpClientGateway(tool_results=external_results)

    external_results["cap-policy-search"]["answer"] = "被篡改的答案"
    external_results["cap-policy-search"]["nested"]["key"] = "被篡改"

    result = gateway.invoke_tool(_server(), _capability(), {"keyword": "结算"})
    assert result.output["answer"] == "原始答案"
    assert result.output["nested"]["key"] == "value"


def test_tool_results_return_deep_copy():
    gateway = InMemoryMcpClientGateway(
        tool_results={"cap-policy-search": {"answer": "政策条款", "nested": {"key": "value"}}}
    )

    result = gateway.invoke_tool(_server(), _capability(), {"keyword": "结算"})
    result.output["answer"] = "被篡改的答案"
    result.output["nested"]["key"] = "被篡改"

    result2 = gateway.invoke_tool(_server(), _capability(), {"keyword": "结算"})
    assert result2.output["answer"] == "政策条款"
    assert result2.output["nested"]["key"] == "value"


def test_success_audit_summary_no_sensitive_argument_keys():
    gateway = InMemoryMcpClientGateway(tool_results={"cap-policy-search": {"answer": "政策条款"}})

    result = gateway.invoke_tool(
        _server(),
        _capability(),
        {"patient_id": "P001", "id_card": "110101199001011234", "phone": "13800138000"},
    )

    assert result.status is KnowledgeExtensionStatus.SUCCESS
    summary = result.audit_events[0].summary
    assert "argument_keys" not in summary
    assert "argument_count" in summary
    assert summary["argument_count"] == 3
    assert "patient_id" not in summary
    assert "id_card" not in summary
    assert "phone" not in summary


def test_high_risk_blocked_audit_summary_no_argument_info():
    gateway = InMemoryMcpClientGateway()

    result = gateway.invoke_tool(
        _server(),
        _capability(McpRiskLevel.HIGH),
        {"patient_id": "P001", "id_card": "110101199001011234"},
    )

    assert result.status is KnowledgeExtensionStatus.HIGH_RISK_BLOCKED
    summary = result.audit_events[0].summary
    assert "argument_keys" not in summary
    assert "argument_count" not in summary
    assert "patient_id" not in summary
    assert "id_card" not in summary
    assert "arguments" not in summary
