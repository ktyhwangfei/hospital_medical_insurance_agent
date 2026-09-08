"""数据目录资产存储单元测试（Issue #38 Slice 1）。"""

from __future__ import annotations

import re

import pytest

from src.data_platform.storage.data_catalog.data_catalog_in_memory import (
    InMemoryDataCatalogStorage,
)
from src.data_platform.storage.data_catalog.data_catalog_postgres import (
    DATA_CATALOG_COLUMNS_DDL,
    DATA_CATALOG_TABLE_SCHEMA,
)
from src.domain.data_catalog.models import (
    CatalogAsset,
    CatalogAssetType,
    CatalogColumn,
    CatalogLineageEdge,
)


def _asset(
    asset_id: str = "ca_01",
    asset_key: str = "metric:mzjyxx.T_FundPay",
    name: str = "统筹基金支付",
    asset_type: CatalogAssetType = CatalogAssetType.METRIC,
    **extra,
) -> CatalogAsset:
    return CatalogAsset(
        asset_id=asset_id,
        asset_type=asset_type,
        asset_key=asset_key,
        name=name,
        **extra,
    )


class TestCatalogAssetModel:
    def test_minimal_asset(self) -> None:
        asset = _asset()
        assert asset.asset_type == CatalogAssetType.METRIC
        assert asset.value_ranges == {}
        assert asset.sample_summary == {}

    def test_traceability_fields(self) -> None:
        """溯源字段：语义版本 + 数据批次。"""
        asset = _asset(semantic_version="4", last_batch_id="5d56bfaa")
        assert asset.semantic_version == "4"
        assert asset.last_batch_id == "5d56bfaa"

    def test_frozen_entity(self) -> None:
        asset = _asset()
        with pytest.raises(Exception):
            setattr(asset, "name", "改")


class TestInMemoryStorage:
    def test_upsert_insert_then_replace_by_key(self) -> None:
        store = InMemoryDataCatalogStorage()
        first = store.upsert_asset(_asset(description="旧口径"))
        second = store.upsert_asset(
            _asset(asset_id="ca_02", description="新口径", last_batch_id="b1")
        )
        # asset_key 幂等：保留原 asset_id，整体替换内容
        assert second.asset_id == first.asset_id
        assert second.description == "新口径"
        assert len(store.list_assets()) == 1

    def test_list_filter_by_type_and_keyword(self) -> None:
        store = InMemoryDataCatalogStorage()
        store.upsert_asset(_asset(asset_id="m1", asset_key="metric:a", name="基金支付"))
        store.upsert_asset(
            _asset(
                asset_id="s1",
                asset_key="source_table:outpatient_trade_current",
                name="门诊交易投影表",
                asset_type=CatalogAssetType.SOURCE_TABLE,
            )
        )
        assert len(store.list_assets(asset_type=CatalogAssetType.METRIC)) == 1
        assert store.list_assets(keyword="投影")[0].asset_id == "s1"
        assert store.list_assets(keyword="不存在") == []

    def test_get_missing_returns_none(self) -> None:
        store = InMemoryDataCatalogStorage()
        assert store.get_asset("missing") is None

    def test_delete_assets_except_prunes_stale(self) -> None:
        store = InMemoryDataCatalogStorage()
        store.upsert_asset(_asset(asset_id="a1", asset_key="metric:a"))
        store.upsert_asset(_asset(asset_id="a2", asset_key="metric:b"))
        deleted = store.delete_assets_except(["metric:a"])
        assert deleted == 1
        assert [a.asset_key for a in store.list_assets()] == ["metric:a"]

    def test_delete_assets_except_empty_keep_clears_all(self) -> None:
        store = InMemoryDataCatalogStorage()
        store.upsert_asset(_asset())
        assert store.delete_assets_except([]) == 1
        assert store.list_assets() == []


class TestDdlDoubleWrite:
    """CREATE+ALTER 双写回归：CREATE 列清单必须与 ALTER 一一对应（缺 ALTER 旧库 500）。"""

    @staticmethod
    def _create_columns(table: str) -> set[str]:
        marker = f"CREATE TABLE IF NOT EXISTS {table} ("
        block = DATA_CATALOG_TABLE_SCHEMA.split(marker, 1)[1].split(");")[0]
        return {
            line.strip().split()[0].rstrip(",")
            for line in block.splitlines()
            if line.strip()
            and not line.strip().startswith("--")
            and not line.strip().startswith(("UNIQUE", "PRIMARY KEY", "CONSTRAINT"))
        }

    @staticmethod
    def _alter_columns(table: str) -> set[str]:
        return set(
            re.findall(
                rf"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS (\w+)",
                DATA_CATALOG_COLUMNS_DDL,
            )
        )

    @pytest.mark.parametrize(
        "table",
        [
            "data_catalog_assets",
            "data_catalog_columns",
            "data_catalog_lineage_edges",
        ],
    )
    def test_create_columns_covered_by_alter(self, table: str) -> None:
        assert self._create_columns(table) == self._alter_columns(table)


class TestColumnsAndEdges:
    """列级元数据与血缘边的内存实现行为。"""

    def test_replace_columns_and_list_by_asset(self) -> None:
        store = InMemoryDataCatalogStorage()
        col_a = CatalogColumn(
            column_id="cc_a", asset_id="ca_t1", column_name="trade_id",
            name="交易ID", data_type="string", field_role="identifier",
            nullable=False, ordinal=0,
        )
        col_b = CatalogColumn(
            column_id="cc_b", asset_id="ca_t1", column_name="amount",
            name="金额", data_type="decimal", field_role="fact", ordinal=1,
        )
        col_other = CatalogColumn(
            column_id="cc_c", asset_id="ca_t2", column_name="x", ordinal=0,
        )
        store.replace_columns([col_b, col_other, col_a])
        cols = store.list_columns("ca_t1")
        assert [c.column_name for c in cols] == ["trade_id", "amount"]
        assert cols[0].nullable is False

    def test_replace_columns_replaces_previous_snapshot(self) -> None:
        store = InMemoryDataCatalogStorage()
        store.replace_columns(
            [CatalogColumn(column_id="cc_a", asset_id="ca_t1", column_name="a")]
        )
        store.replace_columns(
            [CatalogColumn(column_id="cc_b", asset_id="ca_t1", column_name="b")]
        )
        assert [c.column_name for c in store.list_columns("ca_t1")] == ["b"]

    def test_replace_lineage_edges_and_list(self) -> None:
        store = InMemoryDataCatalogStorage()
        edge = CatalogLineageEdge(
            edge_id="le_1", upstream_asset_id="t1",
            downstream_asset_id="m1", relation="feeds",
        )
        store.replace_lineage_edges([edge])
        assert [(e.upstream_asset_id, e.downstream_asset_id, e.relation)
                for e in store.list_lineage_edges()] == [("t1", "m1", "feeds")]
        # 整体重建：第二次替换后旧边消失
        store.replace_lineage_edges([])
        assert store.list_lineage_edges() == []


class TestFacetFilters:
    """owner/tag 分面过滤与 total 计数（真分页）。"""

    def test_owner_and_tag_filters(self) -> None:
        store = InMemoryDataCatalogStorage()
        store.upsert_asset(
            _asset(asset_id="a1", asset_key="metric:a", owner="zhang",
                   tags=["outpatient", "additive"])
        )
        store.upsert_asset(
            _asset(asset_id="a2", asset_key="metric:b", owner="li",
                   tags=["outpatient"])
        )
        assert [a.asset_id for a in store.list_assets(owner="zhang")] == ["a1"]
        assert {a.asset_id for a in store.list_assets(tag="outpatient")} == {"a1", "a2"}
        assert [a.asset_id for a in store.list_assets(tag="additive")] == ["a1"]
        assert store.count_assets(tag="outpatient") == 2
        assert store.count_assets(owner="zhang") == 1

    def test_count_matches_filtered_list(self) -> None:
        store = InMemoryDataCatalogStorage()
        for i in range(5):
            store.upsert_asset(_asset(asset_id=f"a{i}", asset_key=f"metric:m{i}"))
        assert store.count_assets(keyword="metric:m") == 5
        page = store.list_assets(keyword="metric:m", limit=2, offset=4)
        assert len(page) == 1
