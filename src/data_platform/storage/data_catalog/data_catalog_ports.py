"""数据目录资产存储端口（port/adapter 模式）。

遵循项目统一存储约定：默认 PostgreSQL，``USE_MEMORY_STORAGE=1`` 回退内存实现。
资产为目录构建器刷新的快照：按 ``asset_key`` 幂等 upsert，无乐观锁与状态机。
列与血缘边随资产刷新整体替换（replace_*），与资产同刷同新。
"""

from __future__ import annotations

from typing import Protocol

from src.domain.data_catalog.models import (
    CatalogAsset,
    CatalogAssetType,
    CatalogColumn,
    CatalogLineageEdge,
)

__all__ = [
    "CatalogAssetNotFoundError",
    "DataCatalogStorage",
]


class CatalogAssetNotFoundError(LookupError):
    """数据资产不存在。"""


class DataCatalogStorage(Protocol):
    def upsert_asset(self, asset: CatalogAsset) -> CatalogAsset:
        """按 asset_key 幂等写入（存在则整体替换内容、保留 created_at 并刷新 updated_at）。"""
        ...

    def get_asset(self, asset_id: str) -> CatalogAsset | None:
        """按 asset_id 取资产；不存在返回 None。"""
        ...

    def list_assets(
        self,
        *,
        asset_type: CatalogAssetType | None = None,
        keyword: str | None = None,
        owner: str | None = None,
        tag: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[CatalogAsset]:
        """列出资产；keyword 匹配 name/description/asset_key，按 asset_type+name 排序。

        owner 精确匹配；tag 匹配 tags 数组包含该标签的资产。
        """
        ...

    def count_assets(
        self,
        *,
        asset_type: CatalogAssetType | None = None,
        keyword: str | None = None,
        owner: str | None = None,
        tag: str | None = None,
    ) -> int:
        """与 list_assets 同过滤条件的总数（前端真分页用）。"""
        ...

    def delete_assets_except(self, keep_keys: list[str]) -> int:
        """删除 asset_key 不在 keep_keys 中的资产（构建器全量刷新后清理失效资产），返回删除条数。"""
        ...

    # ── 列级元数据 ──────────────────────────────────────────────

    def replace_columns(self, columns: list[CatalogColumn]) -> None:
        """整体替换列快照（构建器全量刷新时重建）。"""
        ...

    def list_columns(self, asset_id: str) -> list[CatalogColumn]:
        """按资产取列清单，按 ordinal 排序。"""
        ...

    # ── 血缘边（刷新时推导落表）─────────────────────────────────

    def replace_lineage_edges(self, edges: list[CatalogLineageEdge]) -> None:
        """整体重建血缘边表（构建器全量刷新时推导落表）。"""
        ...

    def list_lineage_edges(self) -> list[CatalogLineageEdge]:
        """取全量血缘边（查询期 BFS 用）。"""
        ...
