"""数据目录血缘单元测试（Issue #38 Slice 4 / 落表化）。

边由 ``derive_edges`` 纯函数推导（构建器刷新时落表）；
``derive_lineage`` 从存储读取边表做双向 BFS。
"""

from __future__ import annotations

from src.data_platform.storage.data_catalog.data_catalog_in_memory import (
    InMemoryDataCatalogStorage,
)
from src.domain.data_catalog.models import CatalogAsset, CatalogAssetType
from src.runtime.data_catalog.lineage import derive_edges, derive_lineage


def _asset(
    asset_id: str,
    asset_type: CatalogAssetType,
    asset_key: str,
    **kwargs,
) -> CatalogAsset:
    return CatalogAsset(
        asset_id=asset_id,
        asset_type=asset_type,
        asset_key=asset_key,
        name=asset_key,
        **kwargs,
    )


def _triples(edges) -> set[tuple[str, str, str]]:
    return {(e.upstream_asset_id, e.downstream_asset_id, e.relation) for e in edges}


def _seeded_store(with_edges: bool = True) -> InMemoryDataCatalogStorage:
    store = InMemoryDataCatalogStorage()
    store.upsert_asset(
        _asset(
            "t1",
            CatalogAssetType.SOURCE_TABLE,
            "source_table:mz_trade",
            semantic_object_code="mzjyxx",
            semantic_version="4",
            last_batch_id="batch-x",
            source_ref={"dataset_code": "mz_trade"},
        )
    )
    store.upsert_asset(
        _asset(
            "m1",
            CatalogAssetType.METRIC,
            "metric:mzjyxx.T_FundPay",
            semantic_object_code="mzjyxx",
            semantic_version="4",
            source_ref={"fact_field_code": "mz_trade.T_FundPay"},
        )
    )
    store.upsert_asset(
        _asset(
            "o1",
            CatalogAssetType.SEMANTIC_OBJECT,
            "semantic_object:mzjyxx",
            semantic_object_code="mzjyxx",
            source_ref={"domain_code": "outpatient"},
        )
    )
    store.upsert_asset(
        _asset(
            "c1",
            CatalogAssetType.CONSUMER,
            "consumer:skill:settlement_explain_skill",
            source_ref={
                "kind": "skill",
                "skill_id": "settlement_explain_skill",
                "business_object": "mzjyxx",
            },
        )
    )
    if with_edges:
        # 与构建器刷新路径一致：推导后落表
        store.replace_lineage_edges(derive_edges(store.list_assets(limit=100)))
    return store


class TestDeriveEdges:
    def test_full_chain_edges(self) -> None:
        """四跳链路：源表 feeds 指标 belongs_to 对象 consumed_by 消费方。"""
        store = _seeded_store(with_edges=False)
        edges = derive_edges(store.list_assets(limit=100))
        triples = _triples(edges)
        assert ("t1", "m1", "feeds") in triples
        assert ("m1", "o1", "belongs_to") in triples
        assert ("o1", "c1", "consumed_by") in triples

    def test_edge_id_deterministic(self) -> None:
        """edge_id 由三元组确定性派生，跨推导稳定（幂等重建）。"""
        store = _seeded_store(with_edges=False)
        first = derive_edges(store.list_assets(limit=100))
        second = derive_edges(store.list_assets(limit=100))
        assert {e.edge_id for e in first} == {e.edge_id for e in second}

    def test_consumer_matched_by_domain_code(self) -> None:
        """skill business_object 也可匹配对象 domain_code。"""
        store = _seeded_store(with_edges=False)
        c2 = _asset(
            "c2",
            CatalogAssetType.CONSUMER,
            "consumer:skill:other",
            source_ref={"kind": "skill", "skill_id": "other", "business_object": "outpatient"},
        )
        store.upsert_asset(c2)
        triples = _triples(derive_edges(store.list_assets(limit=100)))
        assert ("o1", "c2", "consumed_by") in triples

    def test_metric_without_known_table_no_feeds_edge(self) -> None:
        """指标引用的数据集不在目录中时，不产生 feeds 边（不臆造）。"""
        metric = _asset(
            "m2",
            CatalogAssetType.METRIC,
            "metric:x.Y",
            source_ref={"fact_field_code": "unknown_ds.Y"},
        )
        assert derive_edges([metric]) == []


class TestDeriveLineage:
    def test_bidirectional_subgraph(self) -> None:
        """以指标为根：上游到源表、下游到对象与消费方，节点携带批次溯源。"""
        lineage = derive_lineage(_seeded_store(), "m1")
        assert lineage is not None
        ids = {n.asset_id for n in lineage.nodes}
        assert ids == {"t1", "m1", "o1", "c1"}
        table = next(n for n in lineage.nodes if n.asset_id == "t1")
        assert table.last_batch_id == "batch-x"
        assert table.semantic_version == "4"

    def test_reads_persisted_edges_not_snapshot(self) -> None:
        """查询走边表：未落表时即使快照字段齐全也推不出边。"""
        lineage = derive_lineage(_seeded_store(with_edges=False), "m1")
        assert lineage is not None
        assert [n.asset_id for n in lineage.nodes] == ["m1"]
        assert lineage.edges == []

    def test_unlinked_consumer_isolated(self) -> None:
        """无匹配对象的消费方血缘只有自己。"""
        store = _seeded_store()
        store.upsert_asset(
            _asset(
                "c9",
                CatalogAssetType.CONSUMER,
                "consumer:page:/other",
                source_ref={"kind": "portal_page", "route": "/other"},
            )
        )
        lineage = derive_lineage(store, "c9")
        assert lineage is not None
        assert [n.asset_id for n in lineage.nodes] == ["c9"]
        assert lineage.edges == []

    def test_missing_asset_returns_none(self) -> None:
        assert derive_lineage(_seeded_store(), "ca_missing") is None
