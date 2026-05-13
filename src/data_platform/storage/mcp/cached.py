"""
MCP 缓存存储代理 — CachedMcpStorage

提供 MCP 服务器与能力的读穿透缓存（read-through cache）代理层。

集成策略:
  - 本类仅替换 RedisMcpCache 的"能力列表缓存"职责（responsibility 1）。
  - RedisMcpCache 仍用于幂等性（reserve_invocation）和分布式锁
    （acquire/release_invocation_lock），保持不变。
"""
import logging
from typing import Any

from src.data_platform.cache.cached_base import CachedStorageBase
from src.data_platform.cache.config import CACHE_TTL_MCP
from src.data_platform.cache.ports import CacheClient
from src.data_platform.storage.mcp.models import McpStorageHealth
from src.data_platform.storage.mcp.ports import McpStorage
from src.knowledge_extension.mcp_registry.models import McpCapability, McpServer

logger = logging.getLogger(__name__)


class CachedMcpStorage(CachedStorageBase):
    """MCP 存储的读穿透缓存代理。

    包装一个 McpStorage 实现，为读操作提供缓存，写操作同时写入
    底层存储并失效相关缓存键。

    示例::

        underlying = PostgresMcpStorage(...)
        cache = RedisCacheClient(...)
        cached = CachedMcpStorage(underlying=underlying, cache=cache)

        # 读走缓存
        servers = cached.list_servers()

        # 写穿透到底层 + 失效缓存
        cached.save_server(new_server)
    """

    def __init__(
        self,
        underlying: McpStorage,
        cache: CacheClient,
        ttl: int = CACHE_TTL_MCP,
        enabled: bool = True,
    ):
        super().__init__(cache, "mcp", ttl, enabled)
        self._store = underlying

    # ── 内部工具：将缓存 dict 恢复为领域模型 ──────────────────────

    @staticmethod
    def _model_or_none(data: Any, model_cls: type) -> Any:
        """将缓存 dict 恢复为 Pydantic 模型，或透传已有模型。"""
        if data is None:
            return None
        if isinstance(data, dict):
            return model_cls(**data)
        return data

    @staticmethod
    def _model_list(data: Any, model_cls: type) -> list:
        """将缓存 dict 列表恢复为 Pydantic 模型列表。"""
        if data is None:
            return []
        if isinstance(data, list):
            return [
                model_cls(**item) if isinstance(item, dict) else item
                for item in data
            ]
        return data

    # ── 读方法（读穿透缓存） ────────────────────────────────────────

    def get_server(self, server_id: str) -> McpServer | None:
        key = self._make_key("get", server_id)
        result = self._cached_read(
            key, lambda: self._store.get_server(server_id)
        )
        return self._model_or_none(result, McpServer)

    def list_servers(self) -> list[McpServer]:
        key = self._make_key("list", "servers")
        result = self._cached_read(key, lambda: self._store.list_servers())
        return self._model_list(result, McpServer)

    def get_capability(self, capability_id: str) -> McpCapability | None:
        key = self._make_key("get", "cap", capability_id)
        result = self._cached_read(
            key, lambda: self._store.get_capability(capability_id)
        )
        return self._model_or_none(result, McpCapability)

    def list_capabilities(self) -> list[McpCapability]:
        key = self._make_key("list", "capabilities")
        result = self._cached_read(
            key, lambda: self._store.list_capabilities()
        )
        return self._model_list(result, McpCapability)

    # ── 写方法（写入底层 + 失效关联缓存） ──────────────────────────

    def save_server(self, server: McpServer) -> None:
        self._store.save_server(server)
        self._invalidate_keys(
            ("get", server.server_id),
            ("list", "servers"),
            ("list", "capabilities"),
        )

    def save_capability(self, capability: McpCapability) -> None:
        self._store.save_capability(capability)
        self._invalidate_keys(
            ("get", "cap", capability.capability_id),
            ("list", "capabilities"),
        )

    def delete_capability(self, capability_id: str) -> bool:
        result = self._store.delete_capability(capability_id)
        self._invalidate_keys(
            ("get", "cap", capability_id),
            ("list", "capabilities"),
        )
        return result

    # ── 健康检查 ────────────────────────────────────────────────────

    def health(self) -> McpStorageHealth:
        return self._store.health()
