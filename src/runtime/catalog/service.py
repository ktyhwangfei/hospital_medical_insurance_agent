"""数据目录服务 — issue #38（资产清单 / 统一搜索 / 血缘 / SLA，只读聚合）。

不建新表：三级资产（源表字段 → 语义对象/指标 → 消费方 skill）从既有
semantic_* 注册表、discovery 字段释义、outpatient 批次/尝试表与
skill_manifest.yaml 聚合；血缘与 SLA 直接读批次表（验收：与批次表实测一致）。
语义口径：任一资产可搜索、可详情、可溯源到数据批次与语义版本。
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Literal, Protocol

from pydantic import BaseModel, Field

from src.data_platform.outpatient_governance import (
    OutpatientDataSource,
    OutpatientSyncAttempt,
    OutpatientSyncJob,
)
from src.data_platform.storage.postgresql.outpatient_store import (
    OutpatientSyncStatus,
    RecentOutpatientBatch,
)
from src.semantic_layer.models import Metric, SemanticDataset, SemanticField
from src.semantic_layer.registry import SemanticRegistry

CatalogAssetType = Literal["dataset", "field", "object", "metric", "consumer"]

# 目录资产类型全集（搜索过滤 + 路由校验共用）
ASSET_TYPES: tuple[str, ...] = ("dataset", "field", "object", "metric", "consumer")

# 落地库数据源标识：该数据源下的数据集由门诊同步批次写入（血缘批次挂接判据）
PROJECTION_DATASOURCE_ID = "outpatient_postgres"


class CatalogAssetNotFoundError(Exception):
    """目录资产不存在（API 404 CATALOG_ASSET_NOT_FOUND）。"""

    def __init__(self, asset_type: str, asset_id: str):
        self.asset_type = asset_type
        self.asset_id = asset_id
        super().__init__(f"目录资产不存在：{asset_type}/{asset_id}")


# ── 目录 DTO ───────────────────────────────────────────────────────


class CatalogAsset(BaseModel):
    """搜索命中 / 血缘节点 — 三级资产的统一引用。"""

    asset_type: CatalogAssetType
    asset_id: str
    title: str
    subtitle: str | None = None
    matched_on: list[str] = Field(default_factory=list)


class CatalogSearchResult(BaseModel):
    query: str
    total: int
    items: list[CatalogAsset]


class CatalogOverview(BaseModel):
    counts: dict[str, int]
    sla_sources: int


class CatalogKV(BaseModel):
    key: str
    value: str | None = None


class CatalogDatasetLite(BaseModel):
    dataset_code: str
    object_code: str
    datasource_id: str
    table_name: str
    name: str
    status: str


class CatalogFieldInfo(BaseModel):
    field_code: str
    dataset_code: str
    column_name: str
    name: str
    field_role: str
    semantic_type: str
    value_domain: str | None = None
    nullable: bool = True
    status: str
    description: str | None = None
    is_primary_key: bool = False


class CatalogMetricLite(BaseModel):
    metric_code: str
    name: str
    object_code: str
    status: str
    owner: str | None = None
    definition: str | None = None


class CatalogConsumerInfo(BaseModel):
    consumer_id: str
    name: str
    kind: str = "skill"
    consumed_objects: list[str] = Field(default_factory=list)
    consumed_metrics: list[str] = Field(default_factory=list)


class CatalogBatchInfo(BaseModel):
    batch_id: str
    source_id: str
    mode: str
    semantic_version: str | None = None
    published_at: datetime
    source_committed_at: datetime | None = None
    row_count: int
    quality_status: str | None = None
    latency_seconds: float | None = None


class CatalogVersionInfo(BaseModel):
    version: str
    published_at: datetime
    published_by: str | None = None
    changelog: str | None = None
    metric_count: int = 0


class CatalogAssetDetail(BaseModel):
    """资产详情 — 各类型共用的分节返回体（未涉及的节为空列表）。"""

    asset: CatalogAsset
    summary: list[CatalogKV] = Field(default_factory=list)
    fields: list[CatalogFieldInfo] = Field(default_factory=list)
    metrics: list[CatalogMetricLite] = Field(default_factory=list)
    datasets: list[CatalogDatasetLite] = Field(default_factory=list)
    consumers: list[CatalogConsumerInfo] = Field(default_factory=list)
    batches: list[CatalogBatchInfo] = Field(default_factory=list)
    versions: list[CatalogVersionInfo] = Field(default_factory=list)
    value_mappings: list[dict[str, Any]] = Field(default_factory=list)


class CatalogLineage(BaseModel):
    """血缘 — 数据源 → 批次 → 投影表/字段 → 指标 → 消费方 + 语义版本。"""

    asset: CatalogAsset
    sources: list[str] = Field(default_factory=list)
    batches: list[CatalogBatchInfo] = Field(default_factory=list)
    datasets: list[CatalogDatasetLite] = Field(default_factory=list)
    fields: list[CatalogFieldInfo] = Field(default_factory=list)
    metrics: list[CatalogMetricLite] = Field(default_factory=list)
    consumers: list[CatalogConsumerInfo] = Field(default_factory=list)
    versions: list[CatalogVersionInfo] = Field(default_factory=list)


class CatalogSourceSla(BaseModel):
    """单数据源 SLA — 同步时延 P95 + 最近批次质量门 + 运行统计。"""

    source_id: str
    source_name: str
    connection_status: str
    job_status: str | None = None
    p95_latency_seconds: float | None = None
    last_non_empty_latency_seconds: float | None = None
    non_empty_sample_count: int = 0
    quality_status: str | None = None
    semantic_version: str | None = None
    last_batch: CatalogBatchInfo | None = None
    recent_runs_total: int = 0
    recent_runs_succeeded: int = 0
    recent_runs_failed: int = 0
    last_run_at: datetime | None = None
    last_error_code: str | None = None


class CatalogSlaBoard(BaseModel):
    generated_at: datetime
    sources: list[CatalogSourceSla] = Field(default_factory=list)
    recent_batches: list[CatalogBatchInfo] = Field(default_factory=list)


# ── 端口 ───────────────────────────────────────────────────────────


class CatalogSyncReader(Protocol):
    """目录对同步/批次侧的最小只读依赖（治理控制面 + 落地库的组合面）。"""

    def list_sources(self) -> list[OutpatientDataSource]: ...

    def get_job(self, source_id: str) -> OutpatientSyncJob: ...

    def get_sync_status(self, source_id: str) -> OutpatientSyncStatus: ...

    def list_recent_batches(
        self, source_id: str | None = None, limit: int = 10
    ) -> list[RecentOutpatientBatch]: ...

    def list_attempts(self, source_id: str, limit: int = 20) -> list[OutpatientSyncAttempt]: ...


class CatalogFieldDescriptionLoader(Protocol):
    """discovery 字段释义加载（可选增强，取数失败不影响目录）。"""

    def __call__(self) -> dict[str, dict[str, Any]]: ...


# ── 消费方装载 ─────────────────────────────────────────────────────


def load_skill_consumers(skills_dir: str | Path) -> list[CatalogConsumerInfo]:
    """从 skill_manifest.yaml 的 needed_objects 枚举消费方（与 semantic 路由同口径）。"""
    import yaml

    consumers: list[CatalogConsumerInfo] = []
    root = Path(skills_dir)
    if not root.is_dir():
        return consumers
    for manifest_path in sorted(root.glob("*/skill_manifest.yaml")):
        try:
            with open(manifest_path, "r", encoding="utf-8") as f:
                manifest = yaml.safe_load(f) or {}
        except (OSError, yaml.YAMLError):
            continue
        objects: list[str] = []
        metrics: list[str] = []
        for obj_decl in manifest.get("needed_objects", []) or []:
            object_code = str(obj_decl.get("object_code", "")).strip()
            if not object_code:
                continue
            objects.append(object_code)
            metrics.extend(
                f"{object_code}.{m}" for m in (obj_decl.get("metrics", []) or [])
            )
        consumers.append(CatalogConsumerInfo(
            consumer_id=manifest_path.parent.name,
            name=str(manifest.get("name") or manifest_path.parent.name),
            consumed_objects=objects,
            consumed_metrics=metrics,
        ))
    return consumers


# ── 服务 ───────────────────────────────────────────────────────────


class CatalogService:
    """数据目录 — 只读聚合三级资产，不写任何表。"""

    def __init__(
        self,
        registry: SemanticRegistry,
        sync_reader: CatalogSyncReader,
        *,
        consumers: list[CatalogConsumerInfo] | None = None,
        field_descriptions: Callable[[], dict[str, dict[str, Any]]] | None = None,
        batch_limit: int = 5,
    ):
        self._registry = registry
        self._sync = sync_reader
        self._consumers = consumers if consumers is not None else _default_consumers()
        self._field_descriptions = field_descriptions
        self._batch_limit = batch_limit
        self._desc_cache: dict[str, dict[str, Any]] | None = None

    # ── 搜索与总览 ────────────────────────────────────────────

    def search(
        self, query: str, *, asset_type: str | None = None, limit: int = 20
    ) -> CatalogSearchResult:
        q = query.strip().casefold()
        tokens: dict[str, list[tuple[str, list[str]]]] = {
            "dataset": [], "field": [], "object": [], "metric": [], "consumer": [],
        }
        for dataset in self._registry.list_datasets():
            tokens["dataset"].append((dataset.dataset_code, [
                dataset.dataset_code, dataset.table_name, dataset.name,
                f"{dataset.schema_name}.{dataset.table_name}", dataset.object_code,
            ]))
        table_names = {
            d.dataset_code: f"{d.table_name}".casefold()
            for d in self._registry.list_datasets()
        }
        for field in self._registry.list_fields():
            table = table_names.get(field.dataset_code, "")
            hint = self._descriptions().get(f"{table}:{field.column_name}".casefold(), {})
            tokens["field"].append((field.field_code, [
                field.field_code, field.column_name, field.name,
                hint.get("description") or "", field.dataset_code,
            ]))
        for obj in self._registry.list_objects():
            tokens["object"].append((obj.object_code, [
                obj.object_code, obj.name, obj.definition or "",
            ]))
        for metric in self._registry.list_metrics():
            tokens["metric"].append((metric.metric_code, [
                metric.metric_code, metric.name, metric.definition or "",
                *metric.synonyms, metric.object_code,
            ]))
        for consumer in self._consumers:
            tokens["consumer"].append((consumer.consumer_id, [
                consumer.consumer_id, consumer.name,
                *consumer.consumed_objects, *consumer.consumed_metrics,
            ]))

        items: list[CatalogAsset] = []
        for type_ in ASSET_TYPES:
            if asset_type and type_ != asset_type:
                continue
            for asset_id, candidates in tokens[type_]:
                matched = [c for c in candidates if c and q in c.casefold()]
                if matched:
                    items.append(self._asset_ref(type_, asset_id, matched))
        return CatalogSearchResult(query=query, total=len(items), items=items[:limit])

    def overview(self) -> CatalogOverview:
        return CatalogOverview(
            counts={
                "dataset": len(self._registry.list_datasets()),
                "field": len(self._registry.list_fields()),
                "object": len(self._registry.list_objects()),
                "metric": len(self._registry.list_metrics()),
                "consumer": len(self._consumers),
            },
            sla_sources=len(self._safe_sources()),
        )

    # ── 详情 ──────────────────────────────────────────────────

    def get_asset(self, asset_type: str, asset_id: str) -> CatalogAssetDetail:
        if asset_type == "dataset":
            return self._dataset_detail(asset_id)
        if asset_type == "field":
            return self._field_detail(asset_id)
        if asset_type == "object":
            return self._object_detail(asset_id)
        if asset_type == "metric":
            return self._metric_detail(asset_id)
        if asset_type == "consumer":
            return self._consumer_detail(asset_id)
        raise CatalogAssetNotFoundError(asset_type, asset_id)

    # ── 血缘 ──────────────────────────────────────────────────

    def get_lineage(self, asset_type: str, asset_id: str) -> CatalogLineage:
        detail = self.get_asset(asset_type, asset_id)  # 校验存在性
        datasets = detail.datasets or self._datasets_for(asset_type, asset_id)
        metrics = detail.metrics
        if not metrics and asset_type == "metric":
            metric = self._registry.get_metric(asset_id)
            if metric is not None:
                metrics = [self._metric_lite(metric)]
        if asset_type == "consumer":
            object_codes = sorted(self._consumer_info(asset_id).consumed_objects)
        else:
            object_codes = sorted({m.object_code for m in metrics}) or [
                d.object_code for d in datasets
            ]
            if asset_type == "object" and asset_id not in object_codes:
                object_codes = sorted(set(object_codes) | {asset_id})
        consumers = self._consumers_of_objects(object_codes)
        if asset_type == "consumer":
            consumers = [self._consumer_info(asset_id)]
        batches = self._batches_for_datasets(datasets)
        fields = self._lineage_fields(asset_type, asset_id, datasets, metrics)
        versions: list[CatalogVersionInfo] = []
        for object_code in object_codes:
            versions.extend(self._versions_of(object_code))
        return CatalogLineage(
            asset=detail.asset,
            sources=sorted({d.datasource_id for d in datasets}),
            batches=batches,
            datasets=datasets,
            fields=fields,
            metrics=metrics,
            consumers=consumers,
            versions=versions,
        )

    # ── SLA 看板 ──────────────────────────────────────────────

    def get_sla(self) -> CatalogSlaBoard:
        per_source: list[CatalogSourceSla] = []
        for source in self._safe_sources():
            status = self._sync_status(source.source_id)
            try:
                job_status = self._sync.get_job(source.source_id).status.value
            except Exception:
                job_status = None
            attempts = self._safe_attempts(source.source_id)
            source_batches = self._safe_batches(source_id=source.source_id, limit=1)
            last_batch = self._batch_infos(source_batches)[0] if source_batches else None
            per_source.append(CatalogSourceSla(
                source_id=source.source_id,
                source_name=source.name,
                connection_status=source.connection_status.value,
                job_status=job_status,
                p95_latency_seconds=status.p95_latency_seconds if status else None,
                last_non_empty_latency_seconds=(
                    status.last_non_empty_latency_seconds if status else None
                ),
                non_empty_sample_count=status.non_empty_sample_count if status else 0,
                quality_status=status.quality_status if status else None,
                semantic_version=status.semantic_version if status else None,
                last_batch=last_batch,
                recent_runs_total=len(attempts),
                recent_runs_succeeded=sum(1 for a in attempts if a.status == "succeeded"),
                recent_runs_failed=sum(1 for a in attempts if a.status == "failed"),
                last_run_at=max((a.started_at for a in attempts), default=None),
                last_error_code=next(
                    (a.safe_error_code for a in reversed(attempts) if a.safe_error_code),
                    None,
                ),
            ))
        return CatalogSlaBoard(
            generated_at=_now(),
            sources=per_source,
            recent_batches=self._batch_infos(self._safe_batches(limit=10)),
        )

    # ── 内部：详情分类型 ─────────────────────────────────────

    def _dataset_detail(self, dataset_code: str) -> CatalogAssetDetail:
        dataset = next(
            (d for d in self._registry.list_datasets() if d.dataset_code == dataset_code),
            None,
        )
        if dataset is None:
            raise CatalogAssetNotFoundError("dataset", dataset_code)
        obj = self._registry.get_object(dataset.object_code)
        lite = self._dataset_lite(dataset)
        metrics = self._metrics_for_dataset(dataset)
        batches = self._batches_for_datasets([lite])
        summary = [
            CatalogKV(key="数据表", value=f"{dataset.schema_name}.{dataset.table_name}"),
            CatalogKV(key="数据源", value=dataset.datasource_id),
            CatalogKV(key="所属对象", value=(
                f"{obj.name}（{dataset.object_code}）" if obj else dataset.object_code
            )),
            CatalogKV(key="状态", value=dataset.status),
            CatalogKV(key="血缘批次", value=(
                f"近 {len(batches)} 个（门诊同步投影产出）" if batches else "无（非落地库数据集）"
            )),
        ]
        return CatalogAssetDetail(
            asset=CatalogAsset(
                asset_type="dataset", asset_id=dataset.dataset_code,
                title=dataset.name, subtitle=f"{dataset.datasource_id}.{dataset.table_name}",
            ),
            summary=summary,
            fields=self._fields_of_datasets([lite]),
            metrics=[self._metric_lite(m) for m in metrics],
            consumers=self._consumers_of_objects([dataset.object_code]),
            batches=batches,
            versions=self._versions_of(dataset.object_code),
        )

    def _field_detail(self, field_code: str) -> CatalogAssetDetail:
        field = next(
            (f for f in self._registry.list_fields() if f.field_code == field_code), None
        )
        if field is None:
            raise CatalogAssetNotFoundError("field", field_code)
        dataset = next(
            (d for d in self._registry.list_datasets() if d.dataset_code == field.dataset_code),
            None,
        )
        hint = self._field_hint(field, dataset)
        value_domain_name, value_mappings = self._value_domain_of(field.value_domain)
        metrics: list[Metric] = []
        if dataset is not None:
            target = (dataset.datasource_id, dataset.table_name, field.column_name)
            metrics = [
                m for m in self._registry.list_metrics()
                if _source_field_parts(m.source_field or "") == target
            ]
        return CatalogAssetDetail(
            asset=CatalogAsset(
                asset_type="field", asset_id=field.field_code,
                title=field.name, subtitle=field.field_code,
            ),
            summary=[
                CatalogKV(key="物理列", value=field.column_name),
                CatalogKV(key="数据集", value=field.dataset_code),
                CatalogKV(key="字段角色", value=field.field_role),
                CatalogKV(key="语义类型", value=field.semantic_type),
                CatalogKV(key="值域", value=value_domain_name or field.value_domain),
                CatalogKV(key="源表释义", value=hint.get("description")),
                CatalogKV(key="主键", value="是" if hint.get("is_primary_key") else None),
                CatalogKV(key="状态", value=field.status),
            ],
            datasets=[self._dataset_lite(dataset)] if dataset else [],
            metrics=[self._metric_lite(m) for m in metrics],
            value_mappings=value_mappings,
        )

    def _object_detail(self, object_code: str) -> CatalogAssetDetail:
        obj = self._registry.get_object(object_code)
        if obj is None:
            raise CatalogAssetNotFoundError("object", object_code)
        metrics = self._registry.list_metrics(object_code)
        datasets = [self._dataset_lite(d) for d in self._registry.list_datasets(object_code)]
        return CatalogAssetDetail(
            asset=CatalogAsset(
                asset_type="object", asset_id=obj.object_code,
                title=obj.name, subtitle=obj.object_code,
            ),
            summary=[
                CatalogKV(key="业务口径", value=obj.definition),
                CatalogKV(key="业务域", value=obj.domain_code),
                CatalogKV(key="业务标识", value=obj.identifier),
                CatalogKV(key="状态", value=obj.status),
                CatalogKV(key="当前发布版本", value=obj.current_version),
                CatalogKV(key="指标数", value=str(len(metrics))),
            ],
            metrics=[self._metric_lite(m) for m in metrics],
            datasets=datasets,
            consumers=self._consumers_of_objects([object_code]),
            batches=self._batches_for_datasets(datasets),
            versions=self._versions_of(object_code),
        )

    def _metric_detail(self, metric_code: str) -> CatalogAssetDetail:
        metric = self._registry.get_metric(metric_code)
        if metric is None:
            raise CatalogAssetNotFoundError("metric", metric_code)
        obj = self._registry.get_object(metric.object_code)
        dataset, field = self._resolve_metric_source(metric)
        value_domain_name, value_mappings = self._value_domain_of(metric.value_domain)
        datasets = [self._dataset_lite(dataset)] if dataset else []
        summary = [
            CatalogKV(key="业务口径", value=metric.definition),
            CatalogKV(key="所属对象", value=(
                f"{obj.name}（{metric.object_code}）" if obj else metric.object_code
            )),
            CatalogKV(key="负责人", value=metric.owner),
            CatalogKV(key="审核人", value=metric.reviewer),
            CatalogKV(key="更新频率", value=metric.refresh_frequency),
            CatalogKV(key="权限级别", value=metric.permission_level),
            CatalogKV(key="计量单位", value=metric.unit),
            CatalogKV(key="物理来源", value=metric.source_field),
            CatalogKV(key="值域", value=value_domain_name or metric.value_domain),
            CatalogKV(key="指标类型", value=f"{metric.metric_type}/{metric.metric_kind}"),
            CatalogKV(key="政策类别", value=_policy_subkind_label(metric.subkind)),
        ]
        if metric.subkind in ("policy_rate", "policy_elig") and metric.policy_carrier:
            carrier = metric.policy_carrier
            summary.extend([
                CatalogKV(key="政策文号", value=carrier.get("doc_number")),
                CatalogKV(key="地域适用", value=carrier.get("region_scope")),
                CatalogKV(key="生效期", value=_effective_range(
                    carrier.get("effective_start"), carrier.get("effective_end"),
                )),
                CatalogKV(key="政策规则引用", value=carrier.get("policy_rule_ref")),
            ])
        return CatalogAssetDetail(
            asset=CatalogAsset(
                asset_type="metric", asset_id=metric.metric_code,
                title=metric.name, subtitle=metric.metric_code,
            ),
            summary=summary,
            fields=[field] if field else [],
            datasets=datasets,
            consumers=self._consumers_of_metrics([metric.metric_code]),
            batches=self._batches_for_datasets(datasets),
            versions=self._versions_of(metric.object_code),
            value_mappings=value_mappings,
        )

    def _consumer_detail(self, consumer_id: str) -> CatalogAssetDetail:
        consumer = next((c for c in self._consumers if c.consumer_id == consumer_id), None)
        if consumer is None:
            raise CatalogAssetNotFoundError("consumer", consumer_id)
        metrics = [
            m for m in self._registry.list_metrics()
            if m.metric_code in consumer.consumed_metrics
        ]
        datasets = self._datasets_of_metrics(metrics)
        return CatalogAssetDetail(
            asset=CatalogAsset(
                asset_type="consumer", asset_id=consumer.consumer_id,
                title=consumer.name, subtitle=f"skill · {consumer.consumer_id}",
            ),
            summary=[
                CatalogKV(key="类型", value="Skill（skill_manifest.yaml 声明）"),
                CatalogKV(key="消费对象", value="、".join(consumer.consumed_objects) or None),
                CatalogKV(key="消费指标数", value=str(len(consumer.consumed_metrics))),
                CatalogKV(key="已登记指标数", value=str(len(metrics))),
            ],
            metrics=[self._metric_lite(m) for m in metrics],
            datasets=datasets,
            batches=self._batches_for_datasets(datasets),
        )

    # ── 内部：血缘辅助 ───────────────────────────────────────

    def _datasets_for(self, asset_type: str, asset_id: str) -> list[CatalogDatasetLite]:
        if asset_type == "dataset":
            ds = next(
                (d for d in self._registry.list_datasets() if d.dataset_code == asset_id),
                None,
            )
            return [self._dataset_lite(ds)] if ds else []
        if asset_type == "object":
            return [self._dataset_lite(d) for d in self._registry.list_datasets(asset_id)]
        if asset_type == "metric":
            metric = self._registry.get_metric(asset_id)
            if metric is None:
                return []
            dataset, _ = self._resolve_metric_source(metric)
            return [self._dataset_lite(dataset)] if dataset else []
        if asset_type == "consumer":
            consumer = next(
                (c for c in self._consumers if c.consumer_id == asset_id), None,
            )
            if consumer is None:
                return []
            metrics = [
                m for m in self._registry.list_metrics()
                if m.metric_code in consumer.consumed_metrics
            ]
            return self._datasets_of_metrics(metrics)
        return []

    def _lineage_fields(
        self,
        asset_type: str,
        asset_id: str,
        datasets: list[CatalogDatasetLite],
        metrics: list[CatalogMetricLite],
    ) -> list[CatalogFieldInfo]:
        """血缘字段：资产本身是字段则只列该字段，否则列血缘指标实际引用的物理列。"""
        if asset_type == "field":
            field = next(
                (f for f in self._registry.list_fields() if f.field_code == asset_id),
                None,
            )
            return [self._field_info(field)] if field else []
        metric_codes = {m.metric_code for m in metrics}
        columns: set[str] = set()
        for metric in self._registry.list_metrics():
            if metric.metric_code in metric_codes:
                parts = _source_field_parts(metric.source_field or "")
                if len(parts) == 3:
                    columns.add(parts[2])
        if not columns:
            return []
        return [
            f for f in self._fields_of_datasets(datasets)
            if f.column_name in columns
        ]

    def _metrics_for_dataset(self, dataset: SemanticDataset) -> list[Metric]:
        """指标与数据集挂接：object_code 相同，或 source_field 三段式指向该表。"""
        result: list[Metric] = []
        for metric in self._registry.list_metrics():
            if metric.object_code == dataset.object_code:
                result.append(metric)
                continue
            parts = _source_field_parts(metric.source_field or "")
            if len(parts) == 3 and parts[:2] == (dataset.datasource_id, dataset.table_name):
                result.append(metric)
        return result

    def _resolve_metric_source(
        self, metric: Metric
    ) -> tuple[SemanticDataset | None, CatalogFieldInfo | None]:
        parts = _source_field_parts(metric.source_field or "")
        if len(parts) != 3:
            return None, None
        datasource_id, table_name, column_name = parts
        dataset = next(
            (d for d in self._registry.list_datasets()
             if d.datasource_id == datasource_id and d.table_name == table_name),
            None,
        )
        if dataset is None:
            return None, None
        field = next(
            (f for f in self._registry.list_fields(dataset_code=dataset.dataset_code)
             if f.column_name == column_name),
            None,
        )
        return dataset, (self._field_info(field) if field else None)

    def _datasets_of_metrics(self, metrics: list[Metric]) -> list[CatalogDatasetLite]:
        by_object: dict[str, SemanticDataset] = {}
        for d in self._registry.list_datasets():
            by_object.setdefault(d.object_code, d)
        datasets: dict[str, SemanticDataset] = {}
        for metric in metrics:
            dataset, _ = self._resolve_metric_source(metric)
            if dataset is not None:
                datasets[dataset.dataset_code] = dataset
            elif metric.object_code in by_object:
                fallback = by_object[metric.object_code]
                datasets[fallback.dataset_code] = fallback
        return [self._dataset_lite(d) for d in datasets.values()]

    def _batches_for_datasets(
        self, datasets: list[CatalogDatasetLite]
    ) -> list[CatalogBatchInfo]:
        """落地库数据集挂最近批次（批次由门诊同步写入投影表，其他数据源无批次）。"""
        if not any(d.datasource_id == PROJECTION_DATASOURCE_ID for d in datasets):
            return []
        return self._batch_infos(self._safe_batches(limit=self._batch_limit))

    def _fields_of_datasets(
        self, datasets: list[CatalogDatasetLite]
    ) -> list[CatalogFieldInfo]:
        result: list[CatalogFieldInfo] = []
        for lite in datasets:
            for field in self._registry.list_fields(dataset_code=lite.dataset_code):
                result.append(self._field_info(field))
        return result

    def _field_info(self, field: SemanticField) -> CatalogFieldInfo:
        dataset = next(
            (d for d in self._registry.list_datasets() if d.dataset_code == field.dataset_code),
            None,
        )
        hint = self._field_hint(field, dataset)
        return CatalogFieldInfo(
            field_code=field.field_code,
            dataset_code=field.dataset_code,
            column_name=field.column_name,
            name=field.name,
            field_role=field.field_role,
            semantic_type=field.semantic_type,
            value_domain=field.value_domain,
            nullable=field.nullable,
            status=field.status,
            description=hint.get("description"),
            is_primary_key=bool(hint.get("is_primary_key")),
        )

    def _field_hint(
        self, field: SemanticField, dataset: SemanticDataset | None
    ) -> dict[str, Any]:
        table = dataset.table_name.casefold() if dataset else ""
        return self._descriptions().get(f"{table}:{field.column_name}".casefold(), {})

    def _value_domain_of(
        self, domain_code: str | None
    ) -> tuple[str | None, list[dict[str, Any]]]:
        if not domain_code:
            return None, []
        vd = self._registry.get_value_domain(domain_code)
        mappings = [
            {
                "source_value": m.source_value,
                "standard_value": m.standard_value,
                "description": m.description,
            }
            for m in self._registry.get_value_mappings(domain_code)
        ]
        return (vd.name if vd else None), mappings

    def _asset_ref(self, asset_type: str, asset_id: str, matched: list[str]) -> CatalogAsset:
        title, subtitle = asset_id, None
        if asset_type == "dataset":
            for d in self._registry.list_datasets():
                if d.dataset_code == asset_id:
                    title, subtitle = d.name, f"{d.datasource_id}.{d.table_name}"
                    break
        elif asset_type == "field":
            for f in self._registry.list_fields():
                if f.field_code == asset_id:
                    title, subtitle = f.name, f.field_code
                    break
        elif asset_type == "object":
            for o in self._registry.list_objects():
                if o.object_code == asset_id:
                    title, subtitle = o.name, o.object_code
                    break
        elif asset_type == "metric":
            for m in self._registry.list_metrics():
                if m.metric_code == asset_id:
                    title, subtitle = m.name, m.metric_code
                    break
        else:
            for c in self._consumers:
                if c.consumer_id == asset_id:
                    title, subtitle = c.name, f"skill · {c.consumer_id}"
                    break
        return CatalogAsset(
            asset_type=asset_type, asset_id=asset_id,
            title=title, subtitle=subtitle, matched_on=matched,
        )

    def _dataset_lite(self, dataset: SemanticDataset) -> CatalogDatasetLite:
        return CatalogDatasetLite(
            dataset_code=dataset.dataset_code,
            object_code=dataset.object_code,
            datasource_id=dataset.datasource_id,
            table_name=dataset.table_name,
            name=dataset.name,
            status=dataset.status,
        )

    def _metric_lite(self, metric: Metric) -> CatalogMetricLite:
        return CatalogMetricLite(
            metric_code=metric.metric_code,
            name=metric.name,
            object_code=metric.object_code,
            status=metric.status,
            owner=metric.owner,
            definition=metric.definition,
        )

    def _consumer_info(self, consumer_id: str) -> CatalogConsumerInfo:
        return next(
            (c for c in self._consumers if c.consumer_id == consumer_id),
            CatalogConsumerInfo(consumer_id=consumer_id, name=consumer_id),
        )

    def _consumers_of_objects(self, object_codes: list[str]) -> list[CatalogConsumerInfo]:
        wanted = set(object_codes)
        return [
            c for c in self._consumers
            if c.consumed_objects and set(c.consumed_objects) & wanted
        ]

    def _consumers_of_metrics(self, metric_codes: list[str]) -> list[CatalogConsumerInfo]:
        wanted = set(metric_codes)
        return [c for c in self._consumers if set(c.consumed_metrics) & wanted]

    def _versions_of(self, object_code: str) -> list[CatalogVersionInfo]:
        try:
            versions = self._registry.list_object_versions(object_code)
        except Exception:
            return []
        return [
            CatalogVersionInfo(
                version=v.version,
                published_at=v.published_at,
                published_by=v.published_by,
                changelog=v.changelog,
                metric_count=len(v.metrics),
            )
            for v in versions
        ]

    # ── 内部：同步侧容错读取 ─────────────────────────────────

    def _safe_sources(self) -> list[OutpatientDataSource]:
        try:
            return self._sync.list_sources()
        except Exception:
            return []

    def _sync_status(self, source_id: str) -> OutpatientSyncStatus | None:
        try:
            return self._sync.get_sync_status(source_id)
        except Exception:
            return None

    def _safe_attempts(self, source_id: str) -> list[OutpatientSyncAttempt]:
        try:
            return self._sync.list_attempts(source_id)
        except Exception:
            return []

    def _safe_batches(
        self, *, source_id: str | None = None, limit: int = 10
    ) -> list[RecentOutpatientBatch]:
        try:
            return self._sync.list_recent_batches(source_id=source_id, limit=limit)
        except Exception:
            return []

    def _batch_infos(self, batches: list[RecentOutpatientBatch]) -> list[CatalogBatchInfo]:
        return [
            CatalogBatchInfo(
                batch_id=b.batch_id,
                source_id=b.source_id,
                mode=b.mode,
                semantic_version=b.semantic_version,
                published_at=b.published_at,
                source_committed_at=b.source_committed_at,
                row_count=b.row_count,
                quality_status=b.quality_summary.get("status"),
                latency_seconds=(
                    (b.published_at - b.source_committed_at).total_seconds()
                    if b.source_committed_at else None
                ),
            )
            for b in batches
        ]

    def _descriptions(self) -> dict[str, dict[str, Any]]:
        if self._desc_cache is None:
            if self._field_descriptions is None:
                self._desc_cache = {}
            else:
                try:
                    self._desc_cache = self._field_descriptions()
                except Exception:
                    self._desc_cache = {}
        return self._desc_cache


# ── 工具函数 ───────────────────────────────────────────────────────


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _source_field_parts(source_field: str) -> tuple[str, ...]:
    """解析三段式 `datasource.table.column` 编码。"""
    return tuple(part for part in source_field.split("."))


def _policy_subkind_label(subkind: str | None) -> str:
    if subkind == "policy_rate":
        return "A 政策绑定·比例金额"
    if subkind == "policy_elig":
        return "A 政策绑定·待遇资格"
    return "B 运营事实"


def _effective_range(start: Any, end: Any) -> str | None:
    if start is None:
        return None
    return f"{start} ~ {end}" if end else f"{start} 起现行"


def _default_consumers() -> list[CatalogConsumerInfo]:
    from src.config.production import SKILLS_DIR

    return load_skill_consumers(SKILLS_DIR)


# ── 生产装配 ───────────────────────────────────────────────────────


class PgCatalogSyncReader:
    """治理控制面 + 落地库的组合只读面（目录专用，PG 实现）。"""

    def __init__(self) -> None:
        from src.data_platform.storage.postgresql.outpatient_governance_store import (
            OutpatientGovernanceStore,
        )
        from src.data_platform.storage.postgresql.outpatient_store import (
            OutpatientPostgresStore,
        )

        self._governance = OutpatientGovernanceStore()
        self._outpatient = OutpatientPostgresStore()

    def list_sources(self) -> list[OutpatientDataSource]:
        return self._governance.list_sources()

    def get_job(self, source_id: str) -> OutpatientSyncJob:
        return self._governance.get_job(source_id)

    def get_sync_status(self, source_id: str) -> OutpatientSyncStatus:
        return self._outpatient.get_sync_status(source_id)

    def list_recent_batches(
        self, source_id: str | None = None, limit: int = 10
    ) -> list[RecentOutpatientBatch]:
        return self._outpatient.list_recent_batches(source_id=source_id, limit=limit)

    def list_attempts(self, source_id: str, limit: int = 20) -> list[OutpatientSyncAttempt]:
        return self._governance.list_attempts(source_id, limit)


def build_default_catalog_service() -> CatalogService:
    """生产装配：语义注册表 + 治理/落地库只读面 + discovery 字段释义。"""
    from src.data_platform.storage.postgresql.discovery_store import DiscoveryStore
    from src.semantic_layer.registry import get_semantic_registry

    return CatalogService(
        get_semantic_registry(),
        PgCatalogSyncReader(),
        field_descriptions=DiscoveryStore().get_all_field_descriptions,
    )
