import pytest
from pydantic import ValidationError

from src.knowledge_extension.mcp_registry.models import (
    McpCapability,
    McpCapabilityType,
    McpRiskLevel,
    McpServer,
    McpServerStatus,
    McpTransportType,
)


def test_mcp_server_masks_secret_values():
    server = McpServer(
        server_id="srv-policy",
        name="医保政策 MCP",
        endpoint="https://mcp.example.test/sse",
        transport=McpTransportType.SSE,
        status=McpServerStatus.ENABLED,
        auth_headers={"Authorization": "Bearer secret-token", "X-Tenant": "H001"},
    )

    public_view = server.to_public_dict()

    assert public_view["auth_headers"]["Authorization"] == "***"
    assert public_view["auth_headers"]["X-Tenant"] == "H001"


def test_mcp_capability_requires_identity_type_and_risk():
    capability = McpCapability(
        capability_id="cap-policy-search",
        server_id="srv-policy",
        name="医保政策检索",
        capability_type=McpCapabilityType.TOOL,
        description="检索医保政策条款",
        supported_scenarios={"settlement_exception"},
        required_roles={"medical_insurance_officer"},
        required_permissions={"mcp:invoke:read"},
        risk_level=McpRiskLevel.LOW,
        input_schema={"type": "object", "properties": {"keyword": {"type": "string"}}},
    )

    assert capability.capability_id == "cap-policy-search"
    assert capability.requires_human_confirmation is False


def test_high_risk_capability_requires_human_confirmation():
    capability = McpCapability(
        capability_id="cap-refund",
        server_id="srv-billing",
        name="退费执行",
        capability_type=McpCapabilityType.TOOL,
        description="执行退费",
        risk_level=McpRiskLevel.HIGH,
        has_external_side_effects=True,
    )

    assert capability.requires_human_confirmation is True


def test_missing_capability_id_fails_validation():
    with pytest.raises(ValidationError):
        McpCapability(
            capability_id="",
            server_id="srv-policy",
            name="医保政策检索",
            capability_type=McpCapabilityType.TOOL,
            description="检索医保政策条款",
            risk_level=McpRiskLevel.LOW,
        )
