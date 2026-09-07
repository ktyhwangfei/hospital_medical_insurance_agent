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
from src.domain.data_catalog.models import CatalogAsset, CatalogAssetType


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

    def test_create_columns_covered_by_alter(self) -> None:
        create_block = DATA_CATALOG_TABLE_SCHEMA.split("(", 1)[1].split(");")[0]
        create_columns = {
            line.strip().split()[0]
            for line in create_block.splitlines()
            if line.strip() and not line.strip().startswith("--")
        }
        alter_columns = set(
            re.findall(r"ADD COLUMN IF NOT EXISTS (\w+)", DATA_CATALOG_COLUMNS_DDL)
        )
        assert create_columns == alter_columns
