from src.data_platform.storage.mcp.in_memory import InMemoryMcpStorage
from src.knowledge_extension.common.models import KnowledgeExtensionStatus
from src.knowledge_extension.mcp_registry.models import McpCapability, McpCapabilitySelectionRequest, McpCapabilityType, McpRiskLevel, McpServer, McpServerStatus, McpTransportType
from src.knowledge_extension.mcp_registry.service import McpRegistryService
from src.runtime.orchestration.mcp_integration import McpRuntimeIntegration


def test_runtime_selects_mcp_capability_and_records_audit():
    storage = InMemoryMcpStorage()
    storage.save_server(McpServer(server_id="srv-policy", name="医保政策 MCP", endpoint="memory://policy", transport=McpTransportType.STREAMABLE_HTTP, status=McpServerStatus.ENABLED))
    storage.save_capability(McpCapability(capability_id="cap-policy-search", server_id="srv-policy", name="医保政策检索", capability_type=McpCapabilityType.TOOL, description="检索医保政策条款", supported_scenarios={"settlement_exception"}, required_roles={"medical_insurance_officer"}, required_permissions={"mcp:invoke:read"}, risk_level=McpRiskLevel.LOW))
    integration = McpRuntimeIntegration(McpRegistryService(storage))
    result = integration.select_for_step(McpCapabilitySelectionRequest(scenario="settlement_exception", role="medical_insurance_officer", permissions={"mcp:invoke:read"}, capability_type=McpCapabilityType.TOOL))
    assert result.status is KnowledgeExtensionStatus.SUCCESS
    assert result.audit_events[0].event_type == "mcp_runtime_selection"
