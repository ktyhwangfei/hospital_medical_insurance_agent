import os

os.environ["USE_MEMORY_STORAGE"] = "1"

import pytest

from src.domain.tool.models import (
    ToolContractKind,
    ToolDefinition,
    ToolStatus,
    ToolVersion,
)
from src.runtime.tool_registry.service import ToolInvocationError, ToolRegistryService


def _version(*, status: ToolStatus = ToolStatus.MATERIALIZED) -> ToolVersion:
    return ToolVersion(
        version_id="tv-1",
        tool_id="demo_tool",
        semantic_version="1.0.0",
        definition=ToolDefinition(
            tool_id="demo_tool",
            name="示例 Tool",
            description="用于测试的示例 Tool",
            contract_kind=ToolContractKind.FUNCTION,
            target_ref="src.runtime.policy_qa.settlement_data_provider.create_settlement_data_provider",
        ),
        status=status,
    )


@pytest.mark.asyncio
async def test_invoke_calls_bound_sync_implementation() -> None:
    registry = ToolRegistryService()
    registry.register(_version(), implementation=lambda **kwargs: {"echo": kwargs})

    result = await registry.invoke("demo_tool", settlement_id="S001")

    assert result == {"echo": {"settlement_id": "S001"}}


@pytest.mark.asyncio
async def test_invoke_awaits_async_implementation() -> None:
    async def _impl(**kwargs):
        return {"ok": True, **kwargs}

    registry = ToolRegistryService()
    registry.register(_version(), implementation=_impl)

    result = await registry.invoke("demo_tool", settlement_id="S001")

    assert result == {"ok": True, "settlement_id": "S001"}


@pytest.mark.asyncio
async def test_invoke_raises_when_unbound() -> None:
    registry = ToolRegistryService()
    registry.register(_version())

    with pytest.raises(ToolInvocationError, match="未绑定可调用实现"):
        await registry.invoke("demo_tool")


@pytest.mark.asyncio
async def test_invoke_raises_when_not_materialized() -> None:
    registry = ToolRegistryService()
    registry.register(_version(status=ToolStatus.DRAFT), implementation=lambda **_: {})

    with pytest.raises(ToolInvocationError, match="未物化"):
        await registry.invoke("demo_tool")


@pytest.mark.asyncio
async def test_invoke_raises_for_unknown_tool() -> None:
    registry = ToolRegistryService()

    with pytest.raises(ToolInvocationError):
        await registry.invoke("unknown_tool")
