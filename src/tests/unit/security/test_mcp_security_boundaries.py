from src.data_platform.storage.mcp.in_memory import InMemoryMcpStorage
from src.knowledge_extension.common.models import KnowledgeExtensionStatus
from src.knowledge_extension.mcp_registry.models import McpCapability, McpCapabilitySelectionRequest, McpCapabilityType, McpRiskLevel, McpServer, McpServerStatus, McpTransportType
from src.knowledge_extension.mcp_registry.service import McpRegistryService
from src.runtime.orchestration.mcp_integration import McpRuntimeIntegration


def test_runtime_blocks_high_risk_mcp_capability():
    storage = InMemoryMcpStorage()
    storage.save_server(McpServer(server_id="srv-billing", name="收费 MCP", endpoint="memory://billing", transport=McpTransportType.STREAMABLE_HTTP, status=McpServerStatus.ENABLED))
    storage.save_capability(McpCapability(capability_id="cap-refund", server_id="srv-billing", name="退费执行", capability_type=McpCapabilityType.TOOL, description="执行退费", supported_scenarios={"settlement_exception"}, required_roles={"medical_insurance_officer"}, required_permissions={"mcp:invoke:write"}, risk_level=McpRiskLevel.HIGH, has_external_side_effects=True))
    integration = McpRuntimeIntegration(McpRegistryService(storage))
    result = integration.select_for_step(McpCapabilitySelectionRequest(scenario="settlement_exception", role="medical_insurance_officer", permissions={"mcp:invoke:write"}, capability_type=McpCapabilityType.TOOL))
    assert result.status is KnowledgeExtensionStatus.NO_HIT
    assert result.excluded_capabilities["cap-refund"] == "risk_blocked"
