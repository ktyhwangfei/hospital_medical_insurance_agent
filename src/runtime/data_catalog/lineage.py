"""数据目录血缘动态推导（Issue #38 Slice 4）。

零新表：血缘边从目录快照已有字段动态推导，与资产同刷同新：
- source_table → metric：指标的 ``source_ref.fact_field_code`` 前缀（数据集编码）
- metric → semantic_object：指标的 ``semantic_object_code``
- semantic_object → consumer：skill 的 ``business_object`` 匹配对象编码/域编码

批次溯源（last_batch_id）随节点返回，前端可直接展示到数据批次。
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from src.data_platform.storage.data_catalog.data_catalog_ports import DataCatalogStorage
from src.domain.data_catalog.models import CatalogAsset, CatalogAssetType

# 血缘遍历上限：目录全量资产参与推导（v1 规模百级，2000 足够）
_LINEAGE_LOAD_LIMIT = 2000
# 遍历深度上限：防止异常数据成环时无限展开
_MAX_DEPTH = 8


class LineageNode(BaseModel):
    asset_id: str
    asset_key: str
    asset_type: CatalogAssetType
    name: str
    semantic_version: str | None = None
    last_batch_id: str | None = None


class LineageEdge(BaseModel):
    """血缘边：upstream → downstream。"""

    upstream: str  # asset_id
    downstream: str  # asset_id
    relation: str  # feeds / belongs_to / consumed_by


class AssetLineage(BaseModel):
    root: str
    nodes: list[LineageNode] = Field(default_factory=list)
    edges: list[LineageEdge] = Field(default_factory=list)


def _derive_edges(assets: list[CatalogAsset]) -> list[LineageEdge]:
    """从资产快照推导全量血缘边（纯函数，可独立单测）。"""
    by_key = {a.asset_key: a for a in assets}
    edges: list[LineageEdge] = []

    for asset in assets:
        if asset.asset_type == CatalogAssetType.METRIC:
            # 指标 → 语义对象
            if asset.semantic_object_code:
                obj = by_key.get(f"semantic_object:{asset.semantic_object_code}")
                if obj:
                    edges.append(
                        LineageEdge(
                            upstream=asset.asset_id,
                            downstream=obj.asset_id,
                            relation="belongs_to",
                        )
                    )
            # 源表 → 指标：fact_field_code 前缀即数据集编码
            fact_field = str(asset.source_ref.get("fact_field_code") or "")
            dataset_code = fact_field.split(".")[0] if "." in fact_field else ""
            if dataset_code:
                table = by_key.get(f"source_table:{dataset_code}")
                if table:
                    edges.append(
                        LineageEdge(
                            upstream=table.asset_id,
                            downstream=asset.asset_id,
                            relation="feeds",
                        )
                    )
        elif asset.asset_type == CatalogAssetType.CONSUMER:
            # 语义对象 → 消费方：skill business_object 匹配对象编码/域编码
            business_object = asset.source_ref.get("business_object")
            if not business_object:
                continue
            for obj in assets:
                if obj.asset_type != CatalogAssetType.SEMANTIC_OBJECT:
                    continue
                codes = {
                    obj.semantic_object_code,
                    str(obj.source_ref.get("domain_code") or ""),
                }
                if business_object in codes:
                    edges.append(
                        LineageEdge(
                            upstream=obj.asset_id,
                            downstream=asset.asset_id,
                            relation="consumed_by",
                        )
                    )
    return edges


def derive_lineage(storage: DataCatalogStorage, asset_id: str) -> AssetLineage | None:
    """以指定资产为根，双向遍历血缘子图；资产不存在返回 None。"""
    root = storage.get_asset(asset_id)
    if root is None:
        return None

    assets = storage.list_assets(limit=_LINEAGE_LOAD_LIMIT)
    by_id = {a.asset_id: a for a in assets}
    edges = _derive_edges(assets)

    # 邻接表（双向）
    adjacency: dict[str, list[str]] = {}
    for edge in edges:
        adjacency.setdefault(edge.upstream, []).append(edge.downstream)
        adjacency.setdefault(edge.downstream, []).append(edge.upstream)

    # BFS 双向遍历，深度受限
    visited: set[str] = {asset_id}
    frontier = [(asset_id, 0)]
    while frontier:
        current, depth = frontier.pop(0)
        if depth >= _MAX_DEPTH:
            continue
        for neighbor in adjacency.get(current, []):
            if neighbor not in visited:
                visited.add(neighbor)
                frontier.append((neighbor, depth + 1))

    nodes = [
        LineageNode(
            asset_id=a.asset_id,
            asset_key=a.asset_key,
            asset_type=a.asset_type,
            name=a.name,
            semantic_version=a.semantic_version,
            last_batch_id=a.last_batch_id,
        )
        for aid in visited
        if (a := by_id.get(aid)) is not None
    ]
    sub_edges = [
        e for e in edges if e.upstream in visited and e.downstream in visited
    ]
    return AssetLineage(root=asset_id, nodes=nodes, edges=sub_edges)
