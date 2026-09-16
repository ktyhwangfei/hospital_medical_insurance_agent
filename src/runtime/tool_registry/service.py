"""Tool 注册服务：登记 Tool 版本 + 绑定可调用实现 + 统一调用入口。

Registry 只做"登记 + 调用"，不做业务逻辑；具体能力由 target_ref 指向的既有
函数/adapter Protocol 实现，Registry 不重写它们。
"""

from __future__ import annotations

import inspect
from typing import Any, Awaitable, Callable

from src.data_platform.storage.tool.factory import get_tool_version_storage
from src.domain.tool.models import ToolStatus, ToolVersion


class ToolInvocationError(Exception):
    """Tool 未绑定实现、未物化或调用失败时抛出，供 Workflow 层捕获降级。"""


ToolCallable = Callable[..., Any] | Callable[..., Awaitable[Any]]


def _filter_kwargs(implementation: ToolCallable, kwargs: dict[str, Any], tool_id: str) -> dict[str, Any]:
    """按实现签名过滤调用参数。

    WorkflowExecutor 未声明 input_mapping 的步骤整包透传执行上下文（含 question 等
    非工具入参），按签名裁剪避免 TypeError；声明了但实现不存在的必填参数降级为
    ToolInvocationError（fail-closed），不静默吞掉。
    """
    parameters = inspect.signature(implementation).parameters
    if any(p.kind is inspect.Parameter.VAR_KEYWORD for p in parameters.values()):
        return kwargs
    accepted = {
        name
        for name, p in parameters.items()
        if p.kind in (inspect.Parameter.POSITIONAL_OR_KEYWORD, inspect.Parameter.KEYWORD_ONLY)
    }
    missing = [
        name
        for name, p in parameters.items()
        if p.default is inspect.Parameter.empty
        and p.kind in (inspect.Parameter.POSITIONAL_OR_KEYWORD, inspect.Parameter.KEYWORD_ONLY)
        and name not in kwargs
    ]
    if missing:
        raise ToolInvocationError(f"Tool {tool_id} 缺少必填参数: {', '.join(missing)}")
    return {k: v for k, v in kwargs.items() if k in accepted}


class ToolRegistryService:
    """Tool 注册与调用服务，单例由 factory 函数持有。"""

    def __init__(self) -> None:
        self._storage = get_tool_version_storage()
        self._bindings: dict[str, ToolCallable] = {}
        self._registered_tool_ids: list[str] = []

    def register(self, version: ToolVersion, *, implementation: ToolCallable | None = None) -> ToolVersion:
        saved = self._storage.save_version(version)
        if saved.tool_id not in self._registered_tool_ids:
            self._registered_tool_ids.append(saved.tool_id)
        if implementation is not None:
            self._bindings[saved.tool_id] = implementation
        return saved

    def list_tools(self, tool_id: str) -> list[ToolVersion]:
        return self._storage.list_versions(tool_id)

    def list_registered_tool_ids(self) -> list[str]:
        """本进程内已登记过的 Tool ID（供可视化枚举，非存储层查询）。"""
        return list(self._registered_tool_ids)

    def is_bound(self, tool_id: str) -> bool:
        return tool_id in self._bindings

    def get_tool(self, tool_id: str) -> ToolVersion | None:
        return self._storage.get_latest_materialized(tool_id)

    async def invoke(self, tool_id: str, **kwargs: Any) -> Any:
        version = self.get_tool(tool_id)
        if version is None or version.status != ToolStatus.MATERIALIZED:
            raise ToolInvocationError(f"Tool {tool_id} 未物化，无法调用")

        implementation = self._bindings.get(tool_id)
        if implementation is None:
            raise ToolInvocationError(f"Tool {tool_id} 未绑定可调用实现")

        result = implementation(**_filter_kwargs(implementation, kwargs, tool_id))
        if inspect.isawaitable(result):
            result = await result
        return result
