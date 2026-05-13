"""
知识资产存储工厂 — create_knowledge_asset_storage()

用法::

    from src.data_platform.storage.knowledge.factory import create_knowledge_asset_storage
    storage = create_knowledge_asset_storage()

默认使用 PostgreSQL（PostgresKnowledgeStorage），
当 USE_MEMORY_STORAGE=1 或 PostgreSQL 不可用时回退到内存实现。

当缓存可用且 CACHE_ENABLED_ASSET=1 时，
自动使用 CachedKnowledgeAssetStorage 包装 PostgreSQL 实现。
"""
import logging
import os
from typing import Any

logger = logging.getLogger(__name__)


class InMemoryKnowledgeAssetStorage:
    """内存版知识资产存储（回退实现）

    支持与 CachedKnowledgeAssetStorage 相同的接口方法，
    在工厂中作为 USE_MEMORY_STORAGE 或 PostgreSQL 不可用时的降级方案。
    """

    def __init__(self) -> None:
        self._assets: dict[str, dict[str, Any]] = {}
        self._chunks: dict[str, list[dict[str, Any]]] = {}

    def list_assets(
        self, asset_type: str | None = None
    ) -> list[dict[str, Any]]:
        if asset_type is not None:
            return [
                a
                for a in self._assets.values()
                if a.get("asset_type") == asset_type
            ]
        return list(self._assets.values())

    def get_asset(self, asset_id: str) -> dict[str, Any] | None:
        return self._assets.get(asset_id)

    def get_asset_chunks(self, asset_id: str) -> list[dict[str, Any]]:
        return self._chunks.get(asset_id, [])

    def save_asset(self, asset: dict[str, Any]) -> str:
        asset_id = asset["asset_id"]
        self._assets[asset_id] = dict(asset)  # 浅拷贝
        return asset_id

    def update_asset(self, asset_id: str, data: dict[str, Any]) -> None:
        if asset_id in self._assets:
            self._assets[asset_id].update(data)

    def delete_asset(self, asset_id: str) -> bool:
        existed = asset_id in self._assets
        self._assets.pop(asset_id, None)
        self._chunks.pop(asset_id, None)
        return existed

    def save_chunk(self, chunk: dict[str, Any]) -> str:
        asset_id = chunk["asset_id"]
        if asset_id not in self._chunks:
            self._chunks[asset_id] = []
        self._chunks[asset_id].append(dict(chunk))
        return chunk["chunk_id"]

    def health(self) -> dict[str, Any]:
        return {"status": "healthy", "backend": "in_memory"}


def create_knowledge_asset_storage() -> Any:
    """创建知识资产存储实例

    策略:
      1. USE_MEMORY_STORAGE=1 → 直接返回 InMemoryKnowledgeAssetStorage
      2. 尝试创建 PostgresKnowledgeStorage
         a. 缓存可用且 CACHE_ENABLED_ASSET=1 → CachedKnowledgeAssetStorage
         b. 缓存不可用 → 裸 PostgresKnowledgeStorage
      3. 失败 → 回退到 InMemoryKnowledgeAssetStorage
    """
    use_memory = os.getenv("USE_MEMORY_STORAGE", "").lower() in (
        "1",
        "true",
        "yes",
    )

    if not use_memory:
        try:
            from src.data_platform.storage.knowledge.postgres import (
                PostgresKnowledgeStorage,
            )

            storage = PostgresKnowledgeStorage()

            from src.data_platform.cache import create_cache_client_optional
            from src.data_platform.cache.config import (
                CACHE_ENABLED_ASSET,
                CACHE_TTL_ASSET,
            )

            cache = create_cache_client_optional()
            if cache is not None and CACHE_ENABLED_ASSET == "1":
                from src.data_platform.storage.knowledge.cached import (
                    CachedKnowledgeAssetStorage,
                )

                logger.info(
                    "Using CachedKnowledgeAssetStorage wrapping PostgreSQL"
                )
                return CachedKnowledgeAssetStorage(
                    storage, cache, CACHE_TTL_ASSET
                )

            logger.info("Using PostgresKnowledgeStorage (no cache)")
            return storage

        except Exception as e:
            logger.warning(
                "Failed to create PostgreSQL knowledge asset "
                "storage, falling back to in-memory: %s",
                e,
            )

    logger.info("Using InMemoryKnowledgeAssetStorage")
    return InMemoryKnowledgeAssetStorage()
