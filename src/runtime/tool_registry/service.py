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


class ToolRegistryService:
    """Tool 注册与调用服务，单例由 factory 函数持有。

    storage 可注入（测试隔离 seam）；缺省走进程级存储工厂单例。
    """

    def __init__(self, storage=None) -> None:
        self._storage = storage or get_tool_version_storage()
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

        result = implementation(**kwargs)
        if inspect.isawaitable(result):
            result = await result
        return result
