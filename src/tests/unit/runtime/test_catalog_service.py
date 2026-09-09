"""数据目录服务单测 — issue #38：搜索/详情/血缘/SLA 的只读聚合语义。"""
from datetime import datetime, timedelta, timezone

import pytest

from src.data_platform.outpatient_governance import (
    CdcEnablementStatus,
    ConnectionStatus,
    OutpatientDataSource,
    OutpatientSourceMode,
    OutpatientSyncAttempt,
    OutpatientSyncJob,
    SyncJobStatus,
)
from src.data_platform.storage.postgresql.outpatient_store import (
    OutpatientSyncStatus,
    RecentOutpatientBatch,
)
from src.runtime.catalog.service import (
    CatalogAssetNotFoundError,
    CatalogConsumerInfo,
    CatalogService,
)
from src.semantic_layer.models import (
    BusinessObject,
    BusinessObjectVersion,
    Metric,
    SemanticDataset,
    SemanticField,
    ValueDomain,
    ValueDomainMapping,
)
from src.semantic_layer.registry import InMemoryRegistryStore, SemanticRegistry

NOW = datetime(2026, 9, 9, 6, 0, 0, tzinfo=timezone.utc)


# ── 装配 ───────────────────────────────────────────────────────────


def _source() -> OutpatientDataSource:
    return OutpatientDataSource(
        source_id="bjybdb",
        hospital_code="H001",
        hospital_name="示例医院",
        name="门诊医保库",
        host="db.example",
        database="bjybdb",
        username="readonly",
        credential_id="credential.bjybdb",
        connection_status=ConnectionStatus.HEALTHY,
        cdc_status=CdcEnablementStatus.WAITING_DBA,
        created_at=NOW,
        updated_at=NOW,
    )


def _job(status: SyncJobStatus) -> OutpatientSyncJob:
    return OutpatientSyncJob(
        source_id="bjybdb",
        source_mode=OutpatientSourceMode.CDC,
        status=status,
        schedule_interval_minutes=5,
        next_run_at=NOW + timedelta(minutes=5),
        created_at=NOW,
        updated_at=NOW,
    )


def _batch(batch_id: str, row_count: int, committed: datetime | None) -> RecentOutpatientBatch:
    return RecentOutpatientBatch(
        batch_id=batch_id,
        source_id="bjybdb",
        mode="incremental",
        semantic_version="1",
        published_at=NOW,
        source_committed_at=committed,
        row_count=row_count,
        quality_summary={"status": "passed"},
    )


def _attempt(attempt_id: str, status: str, started: datetime, error: str | None = None):
    return OutpatientSyncAttempt(
        attempt_id=attempt_id,
        source_id="bjybdb",
        source_mode=OutpatientSourceMode.CDC,
        run_kind="incremental",
        status=status,
        started_at=started,
        finished_at=started + timedelta(minutes=2),
        safe_error_code=error,
        safe_message="连接超时" if error else None,
        row_count=10 if status == "succeeded" else 0,
    )


class FakeSyncReader:
    """目录同步侧假实现：批次/尝试/任务状态可注入。"""

    def __init__(self, *, batches=None, attempts=None, job=None):
        self._batches = batches or []
        self._attempts = attempts or []
        self._job = job
        self._status = OutpatientSyncStatus(
            source_id="bjybdb",
            last_batch_id=self._batches[0].batch_id if self._batches else None,
            last_mode="incremental" if self._batches else None,
            checkpoint_kind=None,
            checkpoint_value=None,
            last_published_at=NOW if self._batches else None,
            last_non_empty_latency_seconds=42.0 if self._batches else None,
            non_empty_sample_count=len(self._batches),
            p95_latency_seconds=61.5 if self._batches else None,
            quality_status="passed" if self._batches else None,
            semantic_version="1" if self._batches else None,
        )

    def list_sources(self):
        return [_source()]

    def get_job(self, source_id):
        if source_id != "bjybdb" or self._job is None:
            raise LookupError(source_id)
        return self._job

    def get_sync_status(self, source_id):
        return self._status

    def list_recent_batches(self, source_id=None, limit=10):
        rows = [b for b in self._batches if source_id in (None, b.source_id)]
        return rows[:limit]

    def list_attempts(self, source_id, limit=20):
        return [a for a in self._attempts if a.source_id == source_id][:limit]


def _build_service(reader: FakeSyncReader) -> CatalogService:
    store = InMemoryRegistryStore()
    registry = SemanticRegistry(store)

    store.save_object(BusinessObject(
        object_code="Settlement",
        domain_code="ybjs",
        name="门诊结算单",
        definition="参保人一次门诊就诊的医保结算记录",
        identifier="settlement_id",
        status="published",
        current_version="1",
    ))
    store.save_dataset(SemanticDataset(
        dataset_code="mz_trade",
        object_code="Settlement",
        datasource_id="outpatient_postgres",
        schema_name="public",
        table_name="mz_trade",
        name="门诊结算投影表",
        status="published",
    ))
    store.save_field(SemanticField(
        field_code="mz_trade.djh",
        dataset_code="mz_trade",
        column_name="djh",
        name="单据号",
        field_role="identifier",
        semantic_type="String",
    ))
    store.save_field(SemanticField(
        field_code="mz_trade.xjzfqk",
        dataset_code="mz_trade",
        column_name="xjzfqk",
        name="现金自付金额",
        field_role="fact",
        semantic_type="Amount",
    ))
    store.save_field(SemanticField(
        field_code="mz_trade.zt",
        dataset_code="mz_trade",
        column_name="zt",
        name="结算状态",
        field_role="dimension",
        semantic_type="Enum",
        value_domain="XJZT",
    ))
    store.save_metric(Metric(
        metric_code="Settlement.cash_pay",
        object_code="Settlement",
        name="现金自付金额",
        definition="患者本次结算现金自付金额",
        semantic_type="Amount",
        source_field="outpatient_postgres.mz_trade.xjzfqk",
        synonyms=["自付金额"],
        owner="医保数据组",
        reviewer="医保业务组",
        refresh_frequency="每批次",
        status="published",
        subkind="policy_rate",
        policy_carrier={
            "doc_number": "医保发〔2024〕1号",
            "region_scope": "北京市",
            "effective_start": "2024-01-01",
            "policy_rule_ref": "zcgz-row-123",
        },
    ))
    store.save_metric(Metric(
        metric_code="Settlement.trade_count",
        object_code="Settlement",
        name="结算单数",
        definition="结算单总笔数",
        source_field=None,
        status="published",
    ))
    store.save_value_domain(ValueDomain(
        domain_code="XJZT", name="现金状态", standard_values=["已结算", "已退费"],
    ))
    store.save_value_mapping(ValueDomainMapping(
        domain_code="XJZT", source_value="1", standard_value="已结算",
    ))
    store.save_object_version(BusinessObjectVersion(
        version_id="ver-1",
        object_code="Settlement",
        version="1",
        snapshot={"object_code": "Settlement"},
        changelog="首次发布",
        published_by="semantic-admin",
    ))

    consumer = CatalogConsumerInfo(
        consumer_id="demo_skill",
        name="示例结算技能",
        consumed_objects=["Settlement"],
        consumed_metrics=["Settlement.cash_pay"],
    )
    descriptions = {
        "mz_trade:djh": {"description": "结算单据编号", "is_primary_key": True},
    }
    return CatalogService(
        registry,
        reader,
        consumers=[consumer],
        field_descriptions=lambda: descriptions,
    )


def _default_reader() -> FakeSyncReader:
    committed = NOW - timedelta(seconds=42)
    return FakeSyncReader(
        batches=[
            _batch("b-new", 12, committed),
            _batch("b-old", 8, committed - timedelta(minutes=5)),
        ],
        attempts=[
            _attempt("a3", "succeeded", NOW),
            _attempt("a2", "failed", NOW - timedelta(minutes=10), error="SYNC_TIMEOUT"),
            _attempt("a1", "succeeded", NOW - timedelta(minutes=20)),
        ],
        job=_job(SyncJobStatus.READY),
    )


# ── 搜索 ───────────────────────────────────────────────────────────


class TestSearch:
    def test_field_hit_by_source_description(self):
        service = _build_service(_default_reader())
        result = service.search("单据编号")
        field_hits = [i for i in result.items if i.asset_type == "field"]
        assert [i.asset_id for i in field_hits] == ["mz_trade.djh"]
        assert field_hits[0].matched_on == ["结算单据编号"]

    def test_metric_hit_by_synonym(self):
        service = _build_service(_default_reader())
        result = service.search("自付金额")
        metric_hits = [i for i in result.items if i.asset_type == "metric"]
        assert "Settlement.cash_pay" in [i.asset_id for i in metric_hits]

    def test_dataset_hit_by_table_name(self):
        service = _build_service(_default_reader())
        result = service.search("mz_trade")
        assert any(i.asset_type == "dataset" and i.asset_id == "mz_trade" for i in result.items)

    def test_consumer_hit_by_skill_name(self):
        service = _build_service(_default_reader())
        result = service.search("示例结算技能")
        assert [(i.asset_type, i.asset_id) for i in result.items if i.asset_type == "consumer"] == [
            ("consumer", "demo_skill"),
        ]

    def test_filter_by_asset_type(self):
        service = _build_service(_default_reader())
        result = service.search("结算", asset_type="metric")
        assert result.items and all(i.asset_type == "metric" for i in result.items)

    def test_no_hit_returns_empty(self):
        service = _build_service(_default_reader())
        result = service.search("不存在的关键词")
        assert result.total == 0 and result.items == []

    def test_limit_truncates_but_total_keeps(self):
        service = _build_service(_default_reader())
        result = service.search("结算", limit=1)
        assert result.total >= 2
        assert len(result.items) == 1


# ── 详情 ───────────────────────────────────────────────────────────


class TestAssetDetail:
    def test_dataset_detail_aggregates_all_levels(self):
        service = _build_service(_default_reader())
        detail = service.get_asset("dataset", "mz_trade")
        assert detail.asset.title == "门诊结算投影表"
        assert [f.field_code for f in detail.fields] == [
            "mz_trade.djh", "mz_trade.xjzfqk", "mz_trade.zt",
        ]
        # object_code 挂接 + source_field 三段式挂接都命中
        assert {m.metric_code for m in detail.metrics} == {
            "Settlement.cash_pay", "Settlement.trade_count",
        }
        assert [c.consumer_id for c in detail.consumers] == ["demo_skill"]
        assert [b.batch_id for b in detail.batches] == ["b-new", "b-old"]
        assert [v.version for v in detail.versions] == ["1"]

    def test_field_detail_with_description_and_value_mappings(self):
        service = _build_service(_default_reader())
        detail = service.get_asset("field", "mz_trade.djh")
        summary = {kv.key: kv.value for kv in detail.summary}
        assert summary["源表释义"] == "结算单据编号"
        assert summary["主键"] == "是"
        assert detail.datasets[0].dataset_code == "mz_trade"
        assert detail.metrics == []  # djh 未被指标直接引用

        zt = service.get_asset("field", "mz_trade.zt")
        assert zt.value_mappings == [
            {"source_value": "1", "standard_value": "已结算", "description": None},
        ]

    def test_object_detail(self):
        service = _build_service(_default_reader())
        detail = service.get_asset("object", "Settlement")
        summary = {kv.key: kv.value for kv in detail.summary}
        assert summary["业务口径"] == "参保人一次门诊就诊的医保结算记录"
        assert summary["当前发布版本"] == "1"
        assert len(detail.metrics) == 2
        assert [d.dataset_code for d in detail.datasets] == ["mz_trade"]
        assert [v.version for v in detail.versions] == ["1"]

    def test_metric_detail_carries_policy_carrier(self):
        service = _build_service(_default_reader())
        detail = service.get_asset("metric", "Settlement.cash_pay")
        summary = {kv.key: kv.value for kv in detail.summary}
        assert summary["负责人"] == "医保数据组"
        assert summary["政策类别"] == "A 政策绑定·比例金额"
        assert summary["政策文号"] == "医保发〔2024〕1号"
        assert summary["生效期"] == "2024-01-01 起现行"  # effective_end 为空 = 现行
        assert detail.datasets[0].table_name == "mz_trade"
        assert detail.fields[0].column_name == "xjzfqk"
        assert [c.consumer_id for c in detail.consumers] == ["demo_skill"]

    def test_metric_detail_effective_range_with_end(self):
        store = InMemoryRegistryStore()
        store.save_metric(Metric(
            metric_code="X.a", object_code="X", name="甲",
            subkind="policy_elig",
            policy_carrier={"effective_start": "2023-01-01", "effective_end": "2024-12-31"},
        ))
        service = CatalogService(SemanticRegistry(store), FakeSyncReader(), consumers=[])
        summary = {kv.key: kv.value for kv in service.get_asset("metric", "X.a").summary}
        assert summary["生效期"] == "2023-01-01 ~ 2024-12-31"

    def test_consumer_detail(self):
        service = _build_service(_default_reader())
        detail = service.get_asset("consumer", "demo_skill")
        assert [m.metric_code for m in detail.metrics] == ["Settlement.cash_pay"]
        assert [d.dataset_code for d in detail.datasets] == ["mz_trade"]
        assert [b.batch_id for b in detail.batches] == ["b-new", "b-old"]

    @pytest.mark.parametrize("asset_type,asset_id", [
        ("dataset", "nope"), ("field", "nope"), ("object", "nope"),
        ("metric", "nope"), ("consumer", "nope"),
    ])
    def test_unknown_asset_raises(self, asset_type, asset_id):
        service = _build_service(_default_reader())
        with pytest.raises(CatalogAssetNotFoundError):
            service.get_asset(asset_type, asset_id)


# ── 血缘 ───────────────────────────────────────────────────────────


class TestLineage:
    def test_metric_lineage_full_chain(self):
        service = _build_service(_default_reader())
        lineage = service.get_lineage("metric", "Settlement.cash_pay")
        assert lineage.sources == ["outpatient_postgres"]
        assert [b.batch_id for b in lineage.batches] == ["b-new", "b-old"]
        assert [d.table_name for d in lineage.datasets] == ["mz_trade"]
        assert [m.metric_code for m in lineage.metrics] == ["Settlement.cash_pay"]
        assert [f.column_name for f in lineage.fields] == ["xjzfqk"]
        assert [c.consumer_id for c in lineage.consumers] == ["demo_skill"]
        assert [v.version for v in lineage.versions] == ["1"]

    def test_dataset_lineage_lists_fields_only_referenced_by_metrics(self):
        service = _build_service(_default_reader())
        lineage = service.get_lineage("dataset", "mz_trade")
        assert {f.column_name for f in lineage.fields} == {"xjzfqk"}
        assert {m.metric_code for m in lineage.metrics} == {
            "Settlement.cash_pay", "Settlement.trade_count",
        }

    def test_field_lineage_includes_self_and_downstream(self):
        service = _build_service(_default_reader())
        lineage = service.get_lineage("field", "mz_trade.djh")
        assert [f.field_code for f in lineage.fields] == ["mz_trade.djh"]
        assert [b.batch_id for b in lineage.batches] == ["b-new", "b-old"]

    def test_consumer_lineage_upstream_to_batches(self):
        service = _build_service(_default_reader())
        lineage = service.get_lineage("consumer", "demo_skill")
        assert lineage.consumers[0].consumer_id == "demo_skill"
        assert [m.metric_code for m in lineage.metrics] == ["Settlement.cash_pay"]
        assert [b.batch_id for b in lineage.batches] == ["b-new", "b-old"]
        assert [v.version for v in lineage.versions] == ["1"]

    def test_non_projection_dataset_has_no_batches(self):
        store = InMemoryRegistryStore()
        store.save_object(BusinessObject(object_code="O", domain_code="d", name="对象"))
        store.save_dataset(SemanticDataset(
            dataset_code="raw", object_code="O", datasource_id="bjybdb",
            table_name="o_Trade", name="源表",
        ))
        service = CatalogService(SemanticRegistry(store), _default_reader(), consumers=[])
        detail = service.get_asset("dataset", "raw")
        assert detail.batches == []

    def test_unknown_lineage_asset_raises(self):
        service = _build_service(_default_reader())
        with pytest.raises(CatalogAssetNotFoundError):
            service.get_lineage("metric", "nope")


# ── SLA ────────────────────────────────────────────────────────────


class TestSlaBoard:
    def test_sla_reflects_batches_and_attempts(self):
        service = _build_service(_default_reader())
        board = service.get_sla()
        assert len(board.sources) == 1
        sla = board.sources[0]
        assert sla.source_id == "bjybdb"
        assert sla.job_status == "ready"
        assert sla.p95_latency_seconds == 61.5
        assert sla.quality_status == "passed"
        assert sla.last_batch.batch_id == "b-new"
        assert sla.last_batch.row_count == 12
        assert sla.last_batch.latency_seconds == 42.0
        assert (sla.recent_runs_total, sla.recent_runs_succeeded, sla.recent_runs_failed) == (3, 2, 1)
        assert sla.last_error_code == "SYNC_TIMEOUT"
        assert [b.batch_id for b in board.recent_batches] == ["b-new", "b-old"]

    def test_sla_tolerates_missing_job(self):
        service = _build_service(FakeSyncReader(
            batches=[_batch("b1", 5, NOW - timedelta(seconds=10))],
        ))
        sla = service.get_sla().sources[0]
        assert sla.job_status is None
        assert sla.recent_runs_total == 0

    def test_sla_empty_when_no_sources(self):
        class EmptyReader(FakeSyncReader):
            def list_sources(self):
                return []

        service = _build_service(EmptyReader())
        board = service.get_sla()
        assert board.sources == [] and board.recent_batches == []


class TestOverview:
    def test_overview_counts(self):
        service = _build_service(_default_reader())
        overview = service.overview()
        assert overview.counts == {
            "dataset": 1, "field": 3, "object": 1, "metric": 2, "consumer": 1,
        }
        assert overview.sla_sources == 1
