"""
缓存知识资产存储 — CachedKnowledgeAssetStorage

读穿透（read-through）缓存模式包装 PostgresKnowledgeStorage。
为 list_assets / get_asset / get_asset_chunks 提供缓存，
写入操作（save/update/delete）同步失效相关缓存键。
"""
import logging
from typing import Any

from src.data_platform.cache.cached_base import CachedStorageBase
from src.data_platform.cache.config import CACHE_TTL_ASSET
from src.data_platform.cache.ports import CacheClient

logger = logging.getLogger(__name__)


class CachedKnowledgeAssetStorage(CachedStorageBase):
    """知识资产+切片的缓存代理存储

    读穿透模式：
      - 读取时先查缓存，未命中则委托底层存储并回填缓存
      - 写入时同步失效相关缓存键（get/list/chunks）

    底层存储可以是 PostgresKnowledgeStorage 或 InMemoryKnowledgeAssetStorage。
    """

    def __init__(
        self,
        underlying: Any,
        cache: CacheClient,
        ttl: int = CACHE_TTL_ASSET,
        enabled: bool = True,
    ):
        super().__init__(cache, "knowledge_asset", ttl, enabled)
        self._store = underlying

    # ── 读方法（带缓存读穿透）───────────────────────────────────────

    def list_assets(
        self, asset_type: str | None = None
    ) -> list[dict[str, Any]]:
        """列出知识资产，按 asset_type 过滤（可选），结果缓存"""
        return self._cached_read(
            self._make_key("list", asset_type or ""),
            lambda: self._store.list_assets(asset_type),
        )

    def get_asset(self, asset_id: str) -> dict[str, Any] | None:
        """获取单个知识资产，结果缓存"""
        return self._cached_read(
            self._make_key("get", asset_id),
            lambda: self._store.get_asset(asset_id),
        )

    def get_asset_chunks(self, asset_id: str) -> list[dict[str, Any]]:
        """获取指定资产的所有切片，结果缓存"""
        return self._cached_read(
            self._make_key("chunks", asset_id),
            lambda: self._store.get_asset_chunks(asset_id),
        )

    # ── 写方法（写透传 + 缓存失效）──────────────────────────────────

    def save_asset(self, asset: dict[str, Any]) -> Any:
        """保存知识资产，失效 get/list/chunks 缓存"""
        result = self._store.save_asset(asset)
        self._invalidate_keys(
            ("get", asset.get("asset_id", "")),
            ("list", "*"),
            ("chunks", asset.get("asset_id", "")),
        )
        return result

    def update_asset(self, asset_id: str, data: dict[str, Any]) -> None:
        """更新知识资产，失效 get/list 缓存"""
        self._store.update_asset(asset_id, data)
        self._invalidate_keys(
            ("get", asset_id),
            ("list", "*"),
        )

    def delete_asset(self, asset_id: str) -> Any:
        """删除知识资产，失效 get/list/chunks 缓存"""
        result = self._store.delete_asset(asset_id)
        self._invalidate_keys(
            ("get", asset_id),
            ("list", "*"),
            ("chunks", asset_id),
        )
        return result

    def save_chunk(self, chunk: dict[str, Any]) -> Any:
        """保存知识切片，失效 get/list/chunks 缓存"""
        result = self._store.save_chunk(chunk)
        self._invalidate_keys(
            ("get", chunk.get("asset_id", "")),
            ("list", "*"),
            ("chunks", chunk.get("asset_id", "")),
        )
        return result
