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


def _capability(
    capability_id: str,
    *,
    server_id: str = "srv-policy",
    required_roles: set[str] | None = None,
    required_permissions: set[str] | None = None,
    risk_level: McpRiskLevel = McpRiskLevel.LOW,
    has_external_side_effects: bool = False,
) -> McpCapability:
    return McpCapability(
        capability_id=capability_id,
        server_id=server_id,
        name=f"能力 {capability_id}",
        capability_type=McpCapabilityType.TOOL,
        description=f"测试能力 {capability_id}",
        supported_scenarios={"settlement_exception"},
        required_roles=required_roles or set(),
        required_permissions=required_permissions or set(),
        risk_level=risk_level,
        has_external_side_effects=has_external_side_effects,
    )


def _storage_with_enabled_server() -> InMemoryMcpStorage:
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
    return storage


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


def test_all_role_denied_exclusions_return_permission_denied_status():
    storage = _storage_with_enabled_server()
    storage.save_capability(_capability("cap-audit", required_roles={"auditor"}))
    storage.save_capability(_capability("cap-doctor", required_roles={"doctor"}))
    service = McpRegistryService(storage)

    result = service.select_capabilities(
        McpCapabilitySelectionRequest(
            scenario="settlement_exception",
            role="medical_insurance_officer",
            permissions={"mcp:invoke:read"},
            capability_type=McpCapabilityType.TOOL,
        )
    )

    assert result.status is KnowledgeExtensionStatus.PERMISSION_DENIED
    assert result.selected_capabilities == []
    assert set(result.excluded_capabilities.values()) == {"role_denied"}


def test_mixed_authorization_exclusions_return_permission_denied_status():
    storage = _storage_with_enabled_server()
    storage.save_capability(_capability("cap-role", required_roles={"auditor"}))
    storage.save_capability(_capability("cap-permission", required_permissions={"mcp:invoke:write"}))
    service = McpRegistryService(storage)

    result = service.select_capabilities(
        McpCapabilitySelectionRequest(
            scenario="settlement_exception",
            role="medical_insurance_officer",
            permissions={"mcp:invoke:read"},
            capability_type=McpCapabilityType.TOOL,
        )
    )

    assert result.status is KnowledgeExtensionStatus.PERMISSION_DENIED
    assert result.selected_capabilities == []
    assert set(result.excluded_capabilities.values()) == {"role_denied", "permission_denied"}


def test_all_high_risk_exclusions_return_high_risk_blocked_status():
    storage = _storage_with_enabled_server()
    storage.save_capability(_capability("cap-refund", risk_level=McpRiskLevel.HIGH))
    storage.save_capability(_capability("cap-write", has_external_side_effects=True))
    service = McpRegistryService(storage)

    result = service.select_capabilities(
        McpCapabilitySelectionRequest(
            scenario="settlement_exception",
            role="medical_insurance_officer",
            permissions={"mcp:invoke:read"},
            capability_type=McpCapabilityType.TOOL,
        )
    )

    assert result.status is KnowledgeExtensionStatus.HIGH_RISK_BLOCKED
    assert result.selected_capabilities == []
    assert set(result.excluded_capabilities.values()) == {"risk_blocked"}


def test_server_unavailable_exclusion_keeps_no_hit_status():
    storage = InMemoryMcpStorage()
    storage.save_server(
        McpServer(
            server_id="srv-policy",
            name="医保政策 MCP",
            endpoint="https://mcp.example.test/sse",
            transport=McpTransportType.SSE,
            status=McpServerStatus.DISABLED,
        )
    )
    storage.save_capability(_capability("cap-policy-search"))
    service = McpRegistryService(storage)

    result = service.select_capabilities(
        McpCapabilitySelectionRequest(
            scenario="settlement_exception",
            role="medical_insurance_officer",
            permissions={"mcp:invoke:read"},
            capability_type=McpCapabilityType.TOOL,
        )
    )

    assert result.status is KnowledgeExtensionStatus.NO_HIT
    assert result.selected_capabilities == []
    assert result.excluded_capabilities == {"cap-policy-search": "server_unavailable"}


def test_selected_capabilities_are_sorted_by_capability_id():
    storage = _storage_with_enabled_server()
    storage.save_capability(_capability("cap-z"))
    storage.save_capability(_capability("cap-a"))
    storage.save_capability(_capability("cap-m"))
    service = McpRegistryService(storage)

    result = service.select_capabilities(
        McpCapabilitySelectionRequest(
            scenario="settlement_exception",
            role="medical_insurance_officer",
            permissions={"mcp:invoke:read"},
            capability_type=McpCapabilityType.TOOL,
        )
    )

    assert result.status is KnowledgeExtensionStatus.SUCCESS
    assert [item.capability_id for item in result.selected_capabilities] == ["cap-a", "cap-m", "cap-z"]


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
