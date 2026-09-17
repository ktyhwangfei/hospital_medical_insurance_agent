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


@pytest.mark.asyncio
async def test_invoke_filters_extra_context_kwargs_for_fixed_signature() -> None:
    """缺陷回归：WorkflowExecutor 未声明 input_mapping 的步骤整包透传上下文，
    固定签名实现不得因多余 kwargs（如 question）抛 TypeError；
    缺必填参数时降级为 ToolInvocationError（fail-closed），不静默吞掉。
    """

    def _impl(settlement_id: str) -> dict:
        return {"settlement_id": settlement_id}

    registry = ToolRegistryService()
    registry.register(_version(), implementation=_impl)

    # 多余的 question 不报错，仅裁剪。
    result = await registry.invoke("demo_tool", question="退费核验", settlement_id="S001")
    assert result == {"settlement_id": "S001"}

    # 缺必填参数 → ToolInvocationError 而非 TypeError。
    with pytest.raises(ToolInvocationError, match="缺少必填参数"):
        await registry.invoke("demo_tool", question="退费核验")
