"""数据目录构建器单元测试（Issue #38 Slice 2）。"""

from __future__ import annotations

from src.data_platform.storage.postgresql.outpatient_store import OutpatientSyncStatus
from src.domain.data_catalog.models import CatalogAssetType
from src.runtime.data_catalog.builder import (
    PORTAL_PAGE_CONSUMERS,
    _asset_id,
    build_catalog_assets,
)
from src.semantic_layer.models import (
    BusinessObject,
    BusinessObjectVersion,
    ObjectVersionMetric,
    SemanticDataset,
)


def _object() -> BusinessObject:
    return BusinessObject.model_construct(
        object_code="mzjyxx",
        domain_code="outpatient",
        name="门诊交易信息",
        definition="门诊结算交易主对象",
        identifier="trade_no",
        status="draft",  # 对象行为 draft，已发布内容在版本快照上
        current_version=None,
    )


def _metric() -> ObjectVersionMetric:
    return ObjectVersionMetric.model_construct(
        metric_code="mzjyxx.T_FundPay",
        name="统筹基金支付",
        definition="门诊统筹基金支付金额",
        metric_type="Atomic",
        semantic_type="Amount",
        unit="元",
        source_object="mz_trade",
        source_field="mz_trade.T_FundPay",
        fact_field_code="mz_trade.T_FundPay",
        owner="医保办",
        refresh_frequency=None,
    )


def _dataset() -> SemanticDataset:
    return SemanticDataset(
        dataset_code="mz_trade",
        object_code="mzjyxx",
        datasource_id="bjybdb",
        schema_name="dbo",
        table_name="o_Trade",
        name="门诊交易表",
        status="published",
    )


def _version() -> BusinessObjectVersion:
    return BusinessObjectVersion(
        version_id="v4-id",
        object_code="mzjyxx",
        version="4",
        snapshot={},
        metrics=[_metric()],
        datasets=[_dataset()],
        keys=[],
        fields=[],
    )


def _sync_status() -> OutpatientSyncStatus:
    return OutpatientSyncStatus(
        source_id="bjybdb",
        last_batch_id="5d56bfaa",
        last_mode=None,
        checkpoint_kind=None,
        checkpoint_value=None,
        last_published_at=None,
        last_non_empty_latency_seconds=None,
        non_empty_sample_count=0,
        p95_latency_seconds=None,
        quality_status="ok",
        semantic_version=None,
    )


class TestBuildCatalogAssets:
    def test_three_tier_assets(self) -> None:
        """三级资产 + 源表全覆盖：对象 / 指标 / 投影表 / 消费方。"""
        assets = build_catalog_assets(
            objects=[_object()],
            versions_by_object={"mzjyxx": _version()},
            outpatient_dataset_codes={"mz_trade"},
            sync_status=_sync_status(),
            table_row_counts={"mz_trade": 3350},
            skills=[
                {
                    "skill_id": "settlement_explain_skill",
                    "skill_name": "结算费用解释",
                    "include_keywords": ["起付线"],
                    "business_action": "explain",
                    "business_object": "settlement",
                }
            ],
        )
        by_type: dict[CatalogAssetType, list] = {}
        for a in assets:
            by_type.setdefault(a.asset_type, []).append(a)

        assert len(by_type[CatalogAssetType.SEMANTIC_OBJECT]) == 1
        assert len(by_type[CatalogAssetType.METRIC]) == 1
        assert len(by_type[CatalogAssetType.SOURCE_TABLE]) == 1
        # 消费方 = 1 skill + 静态页面清单
        assert len(by_type[CatalogAssetType.CONSUMER]) == 1 + len(PORTAL_PAGE_CONSUMERS)

    def test_traceability_fields_populated(self) -> None:
        """验收口径：资产可溯源到数据批次与语义版本。"""
        assets = build_catalog_assets(
            objects=[_object()],
            versions_by_object={"mzjyxx": _version()},
            outpatient_dataset_codes={"mz_trade"},
            sync_status=_sync_status(),
        )
        table = next(a for a in assets if a.asset_type == CatalogAssetType.SOURCE_TABLE)
        assert table.last_batch_id == "5d56bfaa"
        assert table.semantic_version == "4"
        assert table.source_ref["table_name"] == "o_Trade"
        assert table.source_ref["outpatient_pg_projection"] is True

        metric = next(a for a in assets if a.asset_type == CatalogAssetType.METRIC)
        assert metric.semantic_version == "4"
        assert metric.owner == "医保办"

    def test_sync_status_scoped_to_outpatient_datasets_only(self) -> None:
        """门诊同步状态不得错贴到其他数据源的表（回归：首次实现曾全量错贴）。"""
        assets = build_catalog_assets(
            objects=[_object()],
            versions_by_object={"mzjyxx": _version()},
            outpatient_dataset_codes=set(),  # mz_trade 不在门诊投影集
            sync_status=_sync_status(),
        )
        table = next(a for a in assets if a.asset_type == CatalogAssetType.SOURCE_TABLE)
        assert table.last_batch_id is None
        assert table.refresh_freq == ""
        assert table.sample_summary == {}

    def test_sample_summary_desensitized_counts_only(self) -> None:
        """样例摘要只含计数与质量状态，无行级数据。"""
        assets = build_catalog_assets(
            objects=[_object()],
            versions_by_object={"mzjyxx": _version()},
            outpatient_dataset_codes={"mz_trade"},
            sync_status=_sync_status(),
            table_row_counts={"mz_trade": 3350},
        )
        table = next(a for a in assets if a.asset_type == CatalogAssetType.SOURCE_TABLE)
        assert table.sample_summary == {"row_count": 3350, "quality_status": "ok"}

    def test_object_without_queryable_version_still_listed(self) -> None:
        """无可查询版本的对象也入目录（可发现），但无指标/表资产。"""
        assets = build_catalog_assets(
            objects=[_object()],
            versions_by_object={},
        )
        obj_assets = [
            a for a in assets if a.asset_type == CatalogAssetType.SEMANTIC_OBJECT
        ]
        assert len(obj_assets) == 1
        assert obj_assets[0].semantic_version is None
        assert not any(a.asset_type == CatalogAssetType.METRIC for a in assets)
        assert not any(a.asset_type == CatalogAssetType.SOURCE_TABLE for a in assets)

    def test_deterministic_asset_id(self) -> None:
        assert _asset_id("metric:mzjyxx.T_FundPay") == _asset_id("metric:mzjyxx.T_FundPay")
        assert _asset_id("metric:a") != _asset_id("metric:b")
