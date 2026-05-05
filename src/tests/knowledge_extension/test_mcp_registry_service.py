from src.data_platform.storage.mcp.in_memory import InMemoryMcpStorage
from src.knowledge_extension.common.models import KnowledgeExtensionStatus
from src.knowledge_extension.mcp_registry.models import (
    McpCapability,
    McpCapabilitySelectionRequest,
    McpCapabilityType,
    McpRiskLevel,
    McpServer,
    McpServerStatus,
    McpTransportType,
)
from src.knowledge_extension.mcp_registry.service import McpRegistryService


def _service() -> McpRegistryService:
    storage = InMemoryMcpStorage()
    storage.save_server(
        McpServer(
            server_id="srv-policy",
            name="医保政策 MCP",
            endpoint="https://mcp.example.test/sse",
            transport=McpTransportType.SSE,
            status=McpServerStatus.ENABLED,
        )
    )
    storage.save_capability(
        McpCapability(
            capability_id="cap-policy-search",
            server_id="srv-policy",
            name="医保政策检索",
            capability_type=McpCapabilityType.TOOL,
            description="检索医保政策条款",
            supported_scenarios={"settlement_exception"},
            required_roles={"medical_insurance_officer"},
            required_permissions={"mcp:invoke:read"},
            risk_level=McpRiskLevel.LOW,
        )
    )
    storage.save_capability(
        McpCapability(
            capability_id="cap-refund",
            server_id="srv-policy",
            name="退费执行",
            capability_type=McpCapabilityType.TOOL,
            description="执行退费",
            supported_scenarios={"settlement_exception"},
            required_roles={"medical_insurance_officer"},
            required_permissions={"mcp:invoke:write"},
            risk_level=McpRiskLevel.HIGH,
            has_external_side_effects=True,
        )
    )
    return McpRegistryService(storage)


def test_selects_low_risk_authorized_capability():
    service = _service()

    result = service.select_capabilities(
        McpCapabilitySelectionRequest(
            scenario="settlement_exception",
            role="medical_insurance_officer",
            permissions={"mcp:invoke:read"},
            capability_type=McpCapabilityType.TOOL,
        )
    )

    assert result.status is KnowledgeExtensionStatus.SUCCESS
    assert [item.capability_id for item in result.selected_capabilities] == ["cap-policy-search"]
    assert result.excluded_capabilities["cap-refund"] == "permission_denied"


def test_high_risk_capability_is_risk_blocked_when_authorized():
    service = _service()

    result = service.select_capabilities(
        McpCapabilitySelectionRequest(
            scenario="settlement_exception",
            role="medical_insurance_officer",
            permissions={"mcp:invoke:read", "mcp:invoke:write"},
            capability_type=McpCapabilityType.TOOL,
        )
    )

    assert result.status is KnowledgeExtensionStatus.SUCCESS
    assert [item.capability_id for item in result.selected_capabilities] == ["cap-policy-search"]
    assert result.excluded_capabilities["cap-refund"] == "risk_blocked"


def test_denies_missing_permission():
    service = _service()

    result = service.select_capabilities(
        McpCapabilitySelectionRequest(
            scenario="settlement_exception",
            role="medical_insurance_officer",
            permissions=set(),
            capability_type=McpCapabilityType.TOOL,
        )
    )

    assert result.status is KnowledgeExtensionStatus.PERMISSION_DENIED
    assert result.selected_capabilities == []
    assert result.excluded_capabilities["cap-policy-search"] == "permission_denied"


def test_no_hit_has_uncertainty():
    service = _service()

    result = service.select_capabilities(
        McpCapabilitySelectionRequest(
            scenario="unknown",
            role="medical_insurance_officer",
            permissions={"mcp:invoke:read"},
        )
    )

    assert result.status is KnowledgeExtensionStatus.NO_HIT
    assert result.uncertainties == ["未找到满足当前场景、角色、权限和风险约束的 MCP 能力"]
