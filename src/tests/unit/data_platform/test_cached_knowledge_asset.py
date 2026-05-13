"""
测试 CachedKnowledgeAssetStorage 的缓存读穿透与写入失效行为
"""
import os
from typing import Any

import pytest

from src.data_platform.cache.in_memory import InMemoryCacheClient
from src.data_platform.storage.knowledge.cached import (
    CachedKnowledgeAssetStorage,
)
from src.data_platform.storage.knowledge.factory import (
    InMemoryKnowledgeAssetStorage,
    create_knowledge_asset_storage,
)


# ── Mock underlying storage with call tracking ───────────────────────


class _MockStore:
    """dict-based mock for underlying knowledge asset storage.

    Tracks call counts per method so tests can verify
    whether the cached storage actually hit the underlying store.
    """

    def __init__(self) -> None:
        self._assets: dict[str, dict[str, Any]] = {}
        self._chunks: dict[str, list[dict[str, Any]]] = {}
        self.calls: dict[str, int] = {}

    def _count(self, method: str) -> None:
        self.calls[method] = self.calls.get(method, 0) + 1

    def list_assets(
        self, asset_type: str | None = None
    ) -> list[dict[str, Any]]:
        self._count("list_assets")
        if asset_type is not None:
            return [
                a
                for a in self._assets.values()
                if a.get("asset_type") == asset_type
            ]
        return list(self._assets.values())

    def get_asset(self, asset_id: str) -> dict[str, Any] | None:
        self._count("get_asset")
        return self._assets.get(asset_id)

    def get_asset_chunks(self, asset_id: str) -> list[dict[str, Any]]:
        self._count("get_asset_chunks")
        return self._chunks.get(asset_id, [])

    def save_asset(self, asset: dict[str, Any]) -> str:
        self._count("save_asset")
        asset_id = asset["asset_id"]
        self._assets[asset_id] = dict(asset)
        return asset_id

    def update_asset(self, asset_id: str, data: dict[str, Any]) -> None:
        self._count("update_asset")
        if asset_id in self._assets:
            self._assets[asset_id].update(data)

    def delete_asset(self, asset_id: str) -> bool:
        self._count("delete_asset")
        existed = asset_id in self._assets
        self._assets.pop(asset_id, None)
        self._chunks.pop(asset_id, None)
        return existed

    def save_chunk(self, chunk: dict[str, Any]) -> str:
        self._count("save_chunk")
        asset_id = chunk["asset_id"]
        if asset_id not in self._chunks:
            self._chunks[asset_id] = []
        self._chunks[asset_id].append(dict(chunk))
        return chunk["chunk_id"]


# ── Fixtures ─────────────────────────────────────────────────────────


@pytest.fixture
def mock_store() -> _MockStore:
    return _MockStore()


@pytest.fixture
def cache() -> InMemoryCacheClient:
    return InMemoryCacheClient()


@pytest.fixture
def cached_storage(
    mock_store: _MockStore, cache: InMemoryCacheClient
) -> CachedKnowledgeAssetStorage:
    return CachedKnowledgeAssetStorage(mock_store, cache, ttl=300)


@pytest.fixture
def sample_asset() -> dict[str, Any]:
    return {
        "asset_id": "ast-001",
        "title": "Test Asset",
        "asset_type": "policy",
        "status": "active",
        "summary": "A test asset",
    }


@pytest.fixture
def sample_chunk() -> dict[str, Any]:
    return {
        "chunk_id": "chk-001",
        "asset_id": "ast-001",
        "text": "Sample chunk content",
        "section": "introduction",
    }


# ── Tests: list_assets caching ───────────────────────────────────────


class TestListAssetsCaching:
    def test_list_assets_caches_result(
        self,
        cached_storage: CachedKnowledgeAssetStorage,
        mock_store: _MockStore,
        sample_asset: dict[str, Any],
    ):
        """首次调用走底层，第二次命中缓存"""
        mock_store.save_asset(sample_asset)

        result1 = cached_storage.list_assets()
        result2 = cached_storage.list_assets()

        assert result1 == result2 == [sample_asset]
        # list_assets called once on underlying; second hit cache
        assert mock_store.calls.get("list_assets") == 1

    def test_list_assets_cache_invalidated_after_save(
        self,
        cached_storage: CachedKnowledgeAssetStorage,
        mock_store: _MockStore,
        sample_asset: dict[str, Any],
    ):
        """save_asset 后重新读取走底层（非缓存）"""
        mock_store.save_asset(sample_asset)

        # Warm cache
        cached_storage.list_assets()
        # Save new asset
        new_asset = {
            "asset_id": "ast-002",
            "title": "New Asset",
            "asset_type": "policy",
        }
        cached_storage.save_asset(new_asset)

        # Should refetch from store after invalidation
        result = cached_storage.list_assets()
        assert len(result) == 2
        # Underlying called twice: initial warm + after invalidation
        assert mock_store.calls.get("list_assets") == 2

    def test_list_assets_with_type(
        self,
        cached_storage: CachedKnowledgeAssetStorage,
        mock_store: _MockStore,
    ):
        """按 asset_type 过滤的列表缓存独立"""
        mock_store.save_asset(
            {"asset_id": "a1", "title": "Policy A", "asset_type": "policy"}
        )
        mock_store.save_asset(
            {"asset_id": "a2", "title": "Guide B", "asset_type": "guide"}
        )

        r1 = cached_storage.list_assets(asset_type="policy")
        r2 = cached_storage.list_assets(asset_type="policy")
        r3 = cached_storage.list_assets(asset_type="guide")

        assert len(r1) == 1
        assert r1 == r2
        assert len(r3) == 1
        # list_assets called once for "policy" (r2 hit cache),
        # and once for "guide"
        assert mock_store.calls.get("list_assets") == 2


# ── Tests: get_asset caching ─────────────────────────────────────────


class TestGetAssetCaching:
    def test_get_asset_caches_result(
        self,
        cached_storage: CachedKnowledgeAssetStorage,
        mock_store: _MockStore,
        sample_asset: dict[str, Any],
    ):
        """get_asset 第二次命中缓存"""
        mock_store.save_asset(sample_asset)

        r1 = cached_storage.get_asset("ast-001")
        r2 = cached_storage.get_asset("ast-001")

        assert r1 == r2 == sample_asset
        assert mock_store.calls.get("get_asset") == 1

    def test_get_asset_cache_invalidated_after_update(
        self,
        cached_storage: CachedKnowledgeAssetStorage,
        mock_store: _MockStore,
        sample_asset: dict[str, Any],
    ):
        """update_asset 后 get_asset 重新走底层"""
        mock_store.save_asset(sample_asset)

        # Warm cache
        cached_storage.get_asset("ast-001")
        # Update
        cached_storage.update_asset("ast-001", {"title": "Updated Title"})

        result = cached_storage.get_asset("ast-001")
        assert result["title"] == "Updated Title"
        # get_asset called twice: initial warm + after invalidation
        assert mock_store.calls.get("get_asset") == 2

    def test_get_asset_cache_invalidated_after_delete(
        self,
        cached_storage: CachedKnowledgeAssetStorage,
        mock_store: _MockStore,
        sample_asset: dict[str, Any],
    ):
        """delete_asset 后 get_asset 返回 None """
        mock_store.save_asset(sample_asset)

        # Warm cache
        cached_storage.get_asset("ast-001")
        # Delete
        cached_storage.delete_asset("ast-001")

        result = cached_storage.get_asset("ast-001")
        assert result is None
        # Underlying call: initial warm + after invalidation
        assert mock_store.calls.get("get_asset") == 2


# ── Tests: get_asset_chunks caching ──────────────────────────────────


class TestGetAssetChunksCaching:
    def test_get_asset_chunks_caches(
        self,
        cached_storage: CachedKnowledgeAssetStorage,
        mock_store: _MockStore,
        sample_asset: dict[str, Any],
        sample_chunk: dict[str, Any],
    ):
        """get_asset_chunks 第二次命中缓存"""
        mock_store.save_asset(sample_asset)
        mock_store.save_chunk(sample_chunk)

        r1 = cached_storage.get_asset_chunks("ast-001")
        r2 = cached_storage.get_asset_chunks("ast-001")

        assert r1 == r2 == [sample_chunk]
        assert mock_store.calls.get("get_asset_chunks") == 1

    def test_get_asset_chunks_invalidated_after_save_chunk(
        self,
        cached_storage: CachedKnowledgeAssetStorage,
        mock_store: _MockStore,
        sample_asset: dict[str, Any],
        sample_chunk: dict[str, Any],
    ):
        """save_chunk 后 get_asset_chunks 重新走底层"""
        mock_store.save_asset(sample_asset)

        # Warm cache (empty chunks)
        cached_storage.get_asset_chunks("ast-001")
        # Save chunk
        cached_storage.save_chunk(sample_chunk)

        result = cached_storage.get_asset_chunks("ast-001")
        assert len(result) == 1
        # get_asset_chunks called twice: warm + after invalidation
        assert mock_store.calls.get("get_asset_chunks") == 2

    def test_get_asset_chunks_invalidated_after_delete(
        self,
        cached_storage: CachedKnowledgeAssetStorage,
        mock_store: _MockStore,
        sample_asset: dict[str, Any],
        sample_chunk: dict[str, Any],
    ):
        """delete_asset 后 get_asset_chunks 返回空列表"""
        mock_store.save_asset(sample_asset)
        mock_store.save_chunk(sample_chunk)

        # Warm cache (has chunks)
        cached_storage.get_asset_chunks("ast-001")
        # Delete asset
        cached_storage.delete_asset("ast-001")

        result = cached_storage.get_asset_chunks("ast-001")
        assert result == []
        # get_asset_chunks called again after invalidation
        assert mock_store.calls.get("get_asset_chunks") == 2


# ── Tests: save_chunk invalidates list_assets ────────────────────────


class TestSaveChunkInvalidation:
    def test_save_chunk_invalidates_list(
        self,
        cached_storage: CachedKnowledgeAssetStorage,
        mock_store: _MockStore,
        sample_asset: dict[str, Any],
        sample_chunk: dict[str, Any],
    ):
        """save_chunk 使 list 缓存失效"""
        mock_store.save_asset(sample_asset)

        # Warm list cache
        cached_storage.list_assets()
        # Save chunk
        cached_storage.save_chunk(sample_chunk)

        # After invalidation, list should re-fetch
        result = cached_storage.list_assets()
        assert len(result) == 1
        # list_assets called: initial warm + after invalidation
        assert mock_store.calls.get("list_assets") == 2


# ── Tests: cache disabled ────────────────────────────────────────────


class TestCacheDisabled:
    def test_cache_disabled_always_hits_underlying(
        self,
        mock_store: _MockStore,
        cache: InMemoryCacheClient,
        sample_asset: dict[str, Any],
    ):
        """enabled=False 时不缓存，每次都走底层"""
        mock_store.save_asset(sample_asset)
        storage = CachedKnowledgeAssetStorage(
            mock_store, cache, ttl=300, enabled=False
        )

        storage.get_asset("ast-001")
        storage.get_asset("ast-001")

        assert mock_store.calls.get("get_asset") == 2


# ── Tests: factory ───────────────────────────────────────────────────


class TestFactory:
    def test_factory_returns_in_memory_when_env_set(self):
        """USE_MEMORY_STORAGE=1 时返回 InMemoryKnowledgeAssetStorage"""
        os.environ["USE_MEMORY_STORAGE"] = "1"
        try:
            storage = create_knowledge_asset_storage()
            assert isinstance(storage, InMemoryKnowledgeAssetStorage)
        finally:
            os.environ.pop("USE_MEMORY_STORAGE", None)

    def test_factory_returns_something(self):
        """默认环境下工厂返回有效存储实例"""
        storage = create_knowledge_asset_storage()
        # Should be either InMemory (if no PG) or something callable
        assert storage is not None
        assert hasattr(storage, "list_assets")
        assert hasattr(storage, "get_asset")
        assert hasattr(storage, "get_asset_chunks")
        assert hasattr(storage, "save_asset")
        assert hasattr(storage, "update_asset")
        assert hasattr(storage, "delete_asset")
        assert hasattr(storage, "save_chunk")
