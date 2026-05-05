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
