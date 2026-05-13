"""
错误码知识库缓存代理 — CachedKnowledgeStore

将 CachedStorageBase 应用于错误码知识库的读穿透缓存。
包裹底层知识库存储（InMemoryKnowledgeWrapper / PostgresKnowledgeStore），
对 get_error_code / list_error_codes 实现读穿透缓存。

Cache key 约定:
    get_error_code("E-UPLOAD-001") → knowledge:ec/E-UPLOAD-001
    list_error_codes()             → knowledge:ec/all
"""
import logging
from typing import Any

from src.data_platform.cache.cached_base import CachedStorageBase
from src.data_platform.cache.ports import CacheClient

logger = logging.getLogger(__name__)


class CachedKnowledgeStore(CachedStorageBase):
    """错误码知识库缓存代理"""

    def __init__(
        self,
        underlying: Any,
        cache: CacheClient,
        ttl: int,
        enabled: bool = True,
    ):
        self._store = underlying
        super().__init__(
            cache=cache,
            domain="knowledge",
            default_ttl=ttl,
            enabled=enabled,
        )

    def get_error_code(self, error_code: str) -> dict[str, Any] | None:
        """获取单个错误码信息（读穿透缓存）"""
        key = self._make_key("ec", error_code)
        return self._cached_read(key, lambda: self._store.get_error_code(error_code))

    def list_error_codes(self) -> list[dict[str, Any]]:
        """列出所有错误码（读穿透缓存）"""
        key = self._make_key("ec", "all")
        return self._cached_read(key, lambda: self._store.list_error_codes())
