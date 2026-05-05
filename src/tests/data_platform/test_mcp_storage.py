from src.data_platform.storage.mcp.in_memory import InMemoryMcpStorage
from src.data_platform.storage.mcp.models import McpStorageHealth, McpStorageHealthStatus
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
        endpoint="https://mcp.example.test/sse",
        transport=McpTransportType.SSE,
        status=McpServerStatus.ENABLED,
    )


def _capability() -> McpCapability:
    return McpCapability(
        capability_id="cap-policy-search",
        server_id="srv-policy",
        name="医保政策检索",
        capability_type=McpCapabilityType.TOOL,
        description="检索医保政策条款",
        supported_scenarios={"settlement_exception"},
        required_roles={"medical_insurance_officer"},
        risk_level=McpRiskLevel.LOW,
    )


def test_in_memory_storage_saves_and_loads_deep_copies():
    storage = InMemoryMcpStorage()
    storage.save_server(_server())
    storage.save_capability(_capability())

    loaded = storage.get_capability("cap-policy-search")
    assert loaded is not None
    loaded.name = "被调用方修改"

    reloaded = storage.get_capability("cap-policy-search")
    assert reloaded is not None
    assert reloaded.name == "医保政策检索"


def test_in_memory_storage_lists_capabilities_in_stable_order():
    storage = InMemoryMcpStorage()
    storage.save_server(_server())
    second = _capability().model_copy(update={"capability_id": "cap-b", "name": "B"})
    first = _capability().model_copy(update={"capability_id": "cap-a", "name": "A"})
    storage.save_capability(second)
    storage.save_capability(first)

    assert [item.capability_id for item in storage.list_capabilities()] == ["cap-a", "cap-b"]


def test_in_memory_health_is_healthy():
    storage = InMemoryMcpStorage()

    health = storage.health()

    assert isinstance(health, McpStorageHealth)
    assert health.status is McpStorageHealthStatus.HEALTHY
