from __future__ import annotations

"""
Semantic Registry — 业务对象 / Metric / 值域的 CRUD 与运行时查询入口。

设计时（Design Time）：通过 RegistryStore 持久化 Domain/Object/Metric/ValueDomain。
运行时（Run Time）：get_metric_mapping 从对象已发布版本快照取指标（版本锁定）。
全局单例 get_semantic_registry() 供路由层 / 服务层消费，依赖方向单向向下。

说明：历史上本文件还并存过 A 系 IndicatorRegistry（扫描 indicators/*.yaml）与
get_registry() 单例，服务于已退役的 IndicatorContext 增强路径。双注册表收敛时
整体移除，统一以 SemanticRegistry（B 系，PostgreSQL 持久化 + 版本发布）为唯一注册表。
"""
import os
from collections import defaultdict
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import dataclass, field
from threading import RLock
from typing import Optional, Protocol

from src.semantic_layer.models import (
    BusinessDomain, BusinessObject, Metric,
    SemanticDataset, DatasetKey, SemanticField, DatasetRelation, DataQualityRule,
    ObjectVersionMetric, BusinessObjectVersion,
    ValueDomain, ValueDomainMapping,
)

_DEFERRED_OUTPATIENT_METRICS = {
    "mzjyxx.average_fee", "mzjyxx.insured_encounter_count",
}
_DEFERRED_OUTPATIENT_REASON = "就诊人次口径未定，门诊医保就诊人次和门诊次均费用暂缓发布"


class RegistryStore(Protocol):
    """Storage backend interface for Semantic Registry."""
    def save_domain(self, domain: BusinessDomain) -> None: ...
    def get_domain(self, domain_code: str) -> Optional[BusinessDomain]: ...
    def list_domains(self) -> list[BusinessDomain]: ...
    def delete_domain(self, domain_code: str) -> None: ...
    def save_object(self, obj: BusinessObject) -> None: ...
    def get_object(self, object_code: str) -> Optional[BusinessObject]: ...
    def list_objects(self, domain_code: Optional[str] = None) -> list[BusinessObject]: ...
    def delete_object(self, object_code: str) -> None: ...
    def save_metric(self, metric: Metric) -> None: ...
    def increment_metric_usage(self, metric_code: str, delta: int = 1) -> int: ...
    def update_metric_quality(self, metric_code: str, score: float) -> None: ...
    def get_metric(self, metric_code: str) -> Optional[Metric]: ...
    def list_metrics(self, object_code: Optional[str] = None) -> list[Metric]: ...
    def delete_metric(self, metric_code: str) -> None: ...
    def save_dataset(self, dataset: SemanticDataset) -> None: ...
    def get_dataset(self, dataset_code: str) -> Optional[SemanticDataset]: ...
    def list_datasets(self, object_code: Optional[str] = None) -> list[SemanticDataset]: ...
    def delete_dataset(self, dataset_code: str) -> None: ...
    def save_dataset_key(self, key: DatasetKey) -> None: ...
    def get_dataset_key(self, key_code: str) -> Optional[DatasetKey]: ...
    def list_dataset_keys(self, dataset_code: Optional[str] = None, object_code: Optional[str] = None) -> list[DatasetKey]: ...
    def delete_dataset_key(self, key_code: str) -> None: ...
    def save_field(self, field: SemanticField) -> None: ...
    def get_field(self, field_code: str) -> Optional[SemanticField]: ...
    def list_fields(self, dataset_code: Optional[str] = None, object_code: Optional[str] = None) -> list[SemanticField]: ...
    def delete_field(self, field_code: str) -> None: ...
    def save_dataset_relation(self, relation: DatasetRelation) -> None: ...
    def get_dataset_relation(self, relation_code: str) -> Optional[DatasetRelation]: ...
    def list_dataset_relations(self, object_code: Optional[str] = None) -> list[DatasetRelation]: ...
    def delete_dataset_relation(self, relation_code: str) -> None: ...
    def save_quality_rule(self, rule: DataQualityRule) -> None: ...
    def get_quality_rule(self, rule_code: str) -> Optional[DataQualityRule]: ...
    def list_quality_rules(self, object_code: Optional[str] = None) -> list[DataQualityRule]: ...
    def delete_quality_rule(self, rule_code: str) -> None: ...
    def save_value_domain(self, vd: ValueDomain) -> None: ...
    def get_value_domain(self, domain_code: str) -> Optional[ValueDomain]: ...
    def save_value_mapping(self, vm: ValueDomainMapping) -> None: ...
    def get_value_mappings(self, domain_code: str) -> list[ValueDomainMapping]: ...
    def delete_value_mapping(self, domain_code: str, source_value: str) -> None: ...
    def delete_value_domain(self, domain_code: str) -> None: ...
    # Object Version Snapshot
    def save_object_version(self, version: BusinessObjectVersion) -> None: ...
    def get_object_version(self, object_code: str, version: str) -> Optional[BusinessObjectVersion]: ...
    def list_object_versions(self, object_code: str) -> list[BusinessObjectVersion]: ...


@dataclass
class InMemoryRegistryStore:
    """In-memory storage for development and testing. Use `USE_MEMORY_STORAGE=1`."""

    _domains: dict[str, BusinessDomain] = field(default_factory=dict)
    _objects: dict[str, BusinessObject] = field(default_factory=dict)
    _metrics: dict[str, Metric] = field(default_factory=dict)
    _datasets: dict[str, SemanticDataset] = field(default_factory=dict)
    _dataset_keys: dict[str, DatasetKey] = field(default_factory=dict)
    _fields: dict[str, SemanticField] = field(default_factory=dict)
    _dataset_relations: dict[str, DatasetRelation] = field(default_factory=dict)
    _quality_rules: dict[str, DataQualityRule] = field(default_factory=dict)
    _value_domains: dict[str, ValueDomain] = field(default_factory=dict)
    _value_mappings: dict[str, list[ValueDomainMapping]] = field(default_factory=lambda: defaultdict(list))
    _object_versions: dict[str, list[BusinessObjectVersion]] = field(
        default_factory=lambda: defaultdict(list))
    _transaction_lock: RLock = field(default_factory=RLock, repr=False)

    @contextmanager
    def transaction(self):
        """为内存发布提供与 PostgreSQL 一致的失败回滚语义。"""
        with self._transaction_lock:
            snapshot = deepcopy((
                self._domains,
                self._objects,
                self._metrics,
                self._datasets,
                self._dataset_keys,
                self._fields,
                self._dataset_relations,
                self._quality_rules,
                self._value_domains,
                self._value_mappings,
                self._object_versions,
            ))
            try:
                yield
            except Exception:
                (
                    self._domains,
                    self._objects,
                    self._metrics,
                    self._datasets,
                    self._dataset_keys,
                    self._fields,
                    self._dataset_relations,
                    self._quality_rules,
                    self._value_domains,
                    self._value_mappings,
                    self._object_versions,
                ) = snapshot
                raise

    # Domain
    def save_domain(self, domain: BusinessDomain) -> None:
        self._domains[domain.domain_code] = domain

    def get_domain(self, domain_code: str) -> Optional[BusinessDomain]:
        return self._domains.get(domain_code)

    def list_domains(self) -> list[BusinessDomain]:
        return list(self._domains.values())

    def delete_domain(self, domain_code: str) -> None:
        self._domains.pop(domain_code, None)

    # Object
    def save_object(self, obj: BusinessObject) -> None:
        self._objects[obj.object_code] = obj

    def get_object(self, object_code: str) -> Optional[BusinessObject]:
        return self._objects.get(object_code)

    def list_objects(self, domain_code: Optional[str] = None) -> list[BusinessObject]:
        objs = list(self._objects.values())
        if domain_code:
            objs = [o for o in objs if o.domain_code == domain_code]
        return objs

    def delete_object(self, object_code: str) -> None:
        self._objects.pop(object_code, None)

    # Metric
    def save_metric(self, metric: Metric) -> None:
        current = self._metrics.get(metric.metric_code)
        if current is not None and metric.schema_version < current.schema_version:
            metric = current.model_copy(update={
                "usage_count": metric.usage_count,
                "quality_score": metric.quality_score,
                "updated_at": metric.updated_at,
            })
        self._metrics[metric.metric_code] = metric

    def increment_metric_usage(self, metric_code: str, delta: int = 1) -> int:
        with self._transaction_lock:
            metric = self._metrics.get(metric_code)
            if metric is None:
                raise ValueError(f"指标 '{metric_code}' 不存在")
            metric.usage_count += delta
            return metric.usage_count

    def update_metric_quality(self, metric_code: str, score: float) -> None:
        with self._transaction_lock:
            metric = self._metrics.get(metric_code)
            if metric is None:
                raise ValueError(f"指标 '{metric_code}' 不存在")
            metric.quality_score = score

    def get_metric(self, metric_code: str) -> Optional[Metric]:
        return self._metrics.get(metric_code)

    def list_metrics(self, object_code: Optional[str] = None) -> list[Metric]:
        metrics = list(self._metrics.values())
        if object_code:
            metrics = [m for m in metrics if m.object_code == object_code]
        return metrics

    def delete_metric(self, metric_code: str) -> None:
        self._metrics.pop(metric_code, None)

    # Query model metadata
    def save_dataset(self, dataset: SemanticDataset) -> None:
        self._datasets[dataset.dataset_code] = dataset

    def get_dataset(self, dataset_code: str) -> Optional[SemanticDataset]:
        return self._datasets.get(dataset_code)

    def list_datasets(self, object_code: Optional[str] = None) -> list[SemanticDataset]:
        values = list(self._datasets.values())
        return [item for item in values if item.object_code == object_code] if object_code else values

    def delete_dataset(self, dataset_code: str) -> None:
        self._datasets.pop(dataset_code, None)

    def save_dataset_key(self, key: DatasetKey) -> None:
        self._dataset_keys[key.key_code] = key

    def get_dataset_key(self, key_code: str) -> Optional[DatasetKey]:
        return self._dataset_keys.get(key_code)

    def list_dataset_keys(self, dataset_code: Optional[str] = None, object_code: Optional[str] = None) -> list[DatasetKey]:
        values = list(self._dataset_keys.values())
        if dataset_code:
            values = [item for item in values if item.dataset_code == dataset_code]
        if object_code:
            dataset_codes = {item.dataset_code for item in self.list_datasets(object_code)}
            values = [item for item in values if item.dataset_code in dataset_codes]
        return values

    def delete_dataset_key(self, key_code: str) -> None:
        self._dataset_keys.pop(key_code, None)

    def save_field(self, field: SemanticField) -> None:
        self._fields[field.field_code] = field

    def get_field(self, field_code: str) -> Optional[SemanticField]:
        return self._fields.get(field_code)

    def list_fields(self, dataset_code: Optional[str] = None, object_code: Optional[str] = None) -> list[SemanticField]:
        values = list(self._fields.values())
        if dataset_code:
            values = [item for item in values if item.dataset_code == dataset_code]
        if object_code:
            dataset_codes = {item.dataset_code for item in self.list_datasets(object_code)}
            values = [item for item in values if item.dataset_code in dataset_codes]
        return values

    def delete_field(self, field_code: str) -> None:
        self._fields.pop(field_code, None)

    def save_dataset_relation(self, relation: DatasetRelation) -> None:
        self._dataset_relations[relation.relation_code] = relation

    def get_dataset_relation(self, relation_code: str) -> Optional[DatasetRelation]:
        return self._dataset_relations.get(relation_code)

    def list_dataset_relations(self, object_code: Optional[str] = None) -> list[DatasetRelation]:
        values = list(self._dataset_relations.values())
        return [item for item in values if item.object_code == object_code] if object_code else values

    def delete_dataset_relation(self, relation_code: str) -> None:
        self._dataset_relations.pop(relation_code, None)

    def save_quality_rule(self, rule: DataQualityRule) -> None:
        self._quality_rules[rule.rule_code] = rule

    def get_quality_rule(self, rule_code: str) -> Optional[DataQualityRule]:
        return self._quality_rules.get(rule_code)

    def list_quality_rules(self, object_code: Optional[str] = None) -> list[DataQualityRule]:
        values = list(self._quality_rules.values())
        return [item for item in values if item.object_code == object_code] if object_code else values

    def delete_quality_rule(self, rule_code: str) -> None:
        self._quality_rules.pop(rule_code, None)

    # Value Domain
    def save_value_domain(self, vd: ValueDomain) -> None:
        self._value_domains[vd.domain_code] = vd

    def get_value_domain(self, domain_code: str) -> Optional[ValueDomain]:
        return self._value_domains.get(domain_code)

    def save_value_mapping(self, vm: ValueDomainMapping) -> None:
        mappings = self._value_mappings[vm.domain_code]
        self._value_mappings[vm.domain_code] = [
            item for item in mappings if item.source_value != vm.source_value
        ] + [vm]

    def get_value_mappings(self, domain_code: str) -> list[ValueDomainMapping]:
        return self._value_mappings.get(domain_code, [])

    def delete_value_mapping(self, domain_code: str, source_value: str) -> None:
        mappings = self._value_mappings.get(domain_code, [])
        self._value_mappings[domain_code] = [m for m in mappings if m.source_value != source_value]

    def delete_value_domain(self, domain_code: str) -> None:
        self._value_domains.pop(domain_code, None)
        self._value_mappings.pop(domain_code, None)

    # Object Version Snapshot
    def save_object_version(self, version: BusinessObjectVersion) -> None:
        versions = self._object_versions[version.object_code]
        if any(v.version == version.version for v in versions):
            raise ValueError(
                f"版本 {version.object_code}@{version.version} 已存在，版本快照不可变")
        versions.append(version)
        versions.sort(key=lambda v: int(v.version))

    def get_object_version(self, object_code: str, version: str) -> Optional[BusinessObjectVersion]:
        for v in self._object_versions.get(object_code, []):
            if v.version == version:
                return v
        return None

    def list_object_versions(self, object_code: str) -> list[BusinessObjectVersion]:
        return list(self._object_versions.get(object_code, []))


class SemanticRegistry:
    """Semantic Registry — business-facing CRUD + query operations."""

    def __init__(self, store: RegistryStore):
        self._store = store

    # Domain queries
    def list_domains(self) -> list[BusinessDomain]:
        return self._store.list_domains()

    # Object queries
    def get_object(self, object_code: str) -> Optional[BusinessObject]:
        return self._store.get_object(object_code)

    def list_objects(self, domain_code: Optional[str] = None) -> list[BusinessObject]:
        return self._store.list_objects(domain_code)

    # Metric queries
    def get_metric(self, metric_code: str) -> Optional[Metric]:
        return self._store.get_metric(metric_code)

    def get_metrics_by_object(self, object_code: str) -> list[Metric]:
        return self._store.list_metrics(object_code=object_code)

    def list_metrics(self, object_code: Optional[str] = None) -> list[Metric]:
        """列全部指标，或按 object_code 过滤（object_code=None 返回全部）。"""
        return self._store.list_metrics(object_code=object_code)

    # Query model queries
    def list_datasets(self, object_code: Optional[str] = None) -> list[SemanticDataset]:
        return self._store.list_datasets(object_code)

    def list_dataset_keys(self, dataset_code: Optional[str] = None, object_code: Optional[str] = None) -> list[DatasetKey]:
        return self._store.list_dataset_keys(dataset_code, object_code)

    def list_fields(self, dataset_code: Optional[str] = None, object_code: Optional[str] = None) -> list[SemanticField]:
        return self._store.list_fields(dataset_code, object_code)

    def list_dataset_relations(self, object_code: Optional[str] = None) -> list[DatasetRelation]:
        return self._store.list_dataset_relations(object_code)

    def list_quality_rules(self, object_code: Optional[str] = None) -> list[DataQualityRule]:
        return self._store.list_quality_rules(object_code)

    def save_metric_draft(self, metric: Metric) -> None:
        """通过公开边界保存草稿指标，禁止调用方直接访问私有 store。"""
        if metric.status != "draft":
            raise ValueError("新建指标必须先保存为 draft")
        if self._store.get_object(metric.object_code) is None:
            raise ValueError(f"对象 '{metric.object_code}' 不存在")
        self._store.save_metric(metric)

    def save_published_metric(self, metric: Metric) -> None:
        """保存已通过人工审核的指标，供提议发布路径使用。"""
        if metric.status != "published":
            raise ValueError("发布指标状态必须为 published")
        if metric.metric_code in _DEFERRED_OUTPATIENT_METRICS:
            raise ValueError(_DEFERRED_OUTPATIENT_REASON)
        if self._store.get_object(metric.object_code) is None:
            raise ValueError(f"对象 '{metric.object_code}' 不存在")
        self._store.save_metric(metric)

    def get_value_domain(self, domain_code: str) -> Optional[ValueDomain]:
        return self._store.get_value_domain(domain_code)

    def save_value_domain(self, value_domain: ValueDomain) -> None:
        self._store.save_value_domain(value_domain)

    def save_value_mapping(self, mapping: ValueDomainMapping) -> None:
        self._store.save_value_mapping(mapping)

    def get_value_mappings(self, domain_code: str) -> list[ValueDomainMapping]:
        """只读获取值域全局映射，供发布冲突校验。"""
        return self._store.get_value_mappings(domain_code)

    def get_metric_mapping(
        self, object_code: str, metric_codes: list[str],
        version: Optional[str] = None,
    ) -> list[Metric]:
        """从对象已发布版本快照取指标（运行时锁定）。

        - version=None：读最新已发布版本（follow latest published）。
        - version='1'：读指定版本（skill locked_version pin）。
        - 未发布/版本不存在返回空列表：skill 只能消费已发布的指标。
        """
        if version is not None:
            target = self._store.get_object_version(object_code, version)
            if target is None:
                return []
        else:
            versions = self._store.list_object_versions(object_code)
            if not versions:
                return []
            target = versions[-1]  # 已按版本号升序排序
        wanted = {
            code if "." in code else f"{object_code}.{code}"
            for code in metric_codes
        }
        return [
            self._version_metric_to_metric(vm, object_code)
            for vm in target.metrics if vm.metric_code in wanted
        ]

    @staticmethod
    def _version_metric_to_metric(
        vm: ObjectVersionMetric, object_code: str
    ) -> Metric:
        """把快照指标重建为 Metric（Builder 按 Metric 类型消费）。"""
        return Metric(
            metric_code=vm.metric_code, object_code=object_code, name=vm.name,
            definition=vm.definition, metric_type=vm.metric_type,
            semantic_type=vm.semantic_type, unit=vm.unit, required=vm.required,
            source_object=vm.source_object, source_field=vm.source_field,
            source_adapter_port=vm.source_adapter_port,
            value_domain=vm.value_domain, importance=vm.importance,
            default_value=vm.default_value,
            fact_field_code=vm.fact_field_code, aggregation=vm.aggregation,
            expression=vm.expression, dependencies=vm.dependencies,
            non_additive_dimensions=vm.non_additive_dimensions,
        )

    # Value Domain resolution
    def resolve_value(self, domain_code: str, source_value: str) -> str:
        """Resolve a source value to its standard value. Returns original if no mapping found."""
        mappings = self._store.get_value_mappings(domain_code)
        for m in mappings:
            if m.source_value == source_value:
                return m.standard_value
        return source_value

    def has_value_domain(self, domain_code: str) -> bool:
        return self._store.get_value_domain(domain_code) is not None

    # ── Object Version Snapshot (publish) ──
    def publish_object(
        self, object_code: str, changelog: Optional[str] = None,
        published_by: Optional[str] = None,
    ) -> BusinessObjectVersion:
        """发布对象：冻结当前草稿指标为不可变版本快照。

        新版本号 = 已有版本数 + 1（递增整数 str）。快照生成后不可修改。
        """
        import uuid
        obj = self._store.get_object(object_code)
        if obj is None:
            raise ValueError(f"对象 '{object_code}' 不存在")
        metrics = self._store.list_metrics(object_code=object_code)
        if not metrics:
            raise ValueError(f"对象 '{object_code}' 无指标，不能发布（§5：空指标不能发布）")
        deferred_codes = _DEFERRED_OUTPATIENT_METRICS if object_code == "mzjyxx" else set()
        publish_metrics = [m for m in metrics if m.metric_code not in deferred_codes]
        if any(m.status == "published" for m in metrics if m.metric_code in deferred_codes):
            raise ValueError(_DEFERRED_OUTPATIENT_REASON)
        governed_metrics = [
            m for m in publish_metrics
            if object_code == "mzjyxx" and (
                any((m.synonyms, m.compatible_dimensions, m.default_time_role,
                        m.refresh_frequency, m.permission_level, m.owner,
                        m.reviewer, m.precision is not None))
            )
        ]
        incomplete = {
            m.metric_code: m.governance_missing_fields()
            for m in governed_metrics if m.governance_missing_fields()
        }
        if incomplete:
            raise ValueError(f"治理字段不完整: {incomplete}")
        datasets = self._store.list_datasets(object_code)
        keys = self._store.list_dataset_keys(object_code=object_code)
        fields = self._store.list_fields(object_code=object_code)
        relations = self._store.list_dataset_relations(object_code)
        quality_rules = self._store.list_quality_rules(object_code)
        if datasets or any(m.fact_field_code or m.expression for m in publish_metrics):
            issues = self.validate_query_model(object_code)
            if issues:
                raise ValueError("; ".join(issues))
        existing = self._store.list_object_versions(object_code)
        datasets = self._store.list_datasets(object_code)
        keys = self._store.list_dataset_keys(object_code=object_code)
        fields = self._store.list_fields(object_code=object_code)
        relations = self._store.list_dataset_relations(object_code)
        quality_rules = self._store.list_quality_rules(object_code)
        query_metrics = [m for m in publish_metrics if m.fact_field_code or m.expression]
        if datasets or query_metrics:
            issues = self.validate_query_model(object_code)
            if issues:
                raise ValueError("; ".join(issues))
        next_version = str(len(existing) + 1)
        snapshot = BusinessObjectVersion(
            version_id=str(uuid.uuid4()),
            object_code=object_code,
            version=next_version,
            snapshot={
                "object_code": obj.object_code, "name": obj.name,
                "definition": obj.definition, "domain_code": obj.domain_code,
                "identifier": obj.identifier, "source_object": obj.source_object,
                "source_adapter_port": obj.source_adapter_port,
                "preferred_relation_paths": [p.model_dump() for p in obj.preferred_relation_paths],
                "queryable": bool(datasets),
            },
            metrics=[ObjectVersionMetric.from_metric(m) for m in publish_metrics],
            datasets=[item.model_copy(update={"status": "published"}) for item in datasets],
            keys=keys,
            fields=[item.model_copy(update={"status": "published"}) for item in fields],
            relations=[item.model_copy(update={"status": "published"}) for item in relations],
            quality_rules=[item.model_copy(update={"status": "published"}) for item in quality_rules],
            changelog=changelog,
            published_by=published_by,
        )
        if query_metrics:
            from src.semantic_layer.query_planner import (
                QueryAnchor,
                QueryScope,
                SemanticQuery,
                SemanticQueryPlanner,
                SemanticQueryPlanningError,
            )
            anchor_field_code = next(
                (
                    rule.parameters.get("field_code")
                    for rule in quality_rules
                    if rule.rule_type == "not_null" and rule.parameters.get("field_code")
                ),
                None,
            )
            anchor_field = next(
                (field for field in fields if field.field_code == anchor_field_code),
                next((field for field in fields if field.field_role == "identifier"), None),
            )
            anchor_key = next(
                (
                    key for key in keys
                    if anchor_field
                    and key.dataset_code == anchor_field.dataset_code
                    and anchor_field.column_name in key.columns
                ),
                None,
            )
            if anchor_field is None or anchor_key is None:
                raise ValueError("查询模型缺少可编译的实体锚点")
            temporary_store = InMemoryRegistryStore()
            temporary_store.save_object_version(snapshot)
            try:
                planner = SemanticQueryPlanner(SemanticRegistry(temporary_store))
                if anchor_key.entity_code == "inpatient_admission":
                    groups = [("whole_admission", query_metrics)]
                else:
                    field_dataset = {field.field_code: field.dataset_code for field in fields}
                    by_scope: dict[str, list[ObjectVersionMetric]] = defaultdict(list)
                    for metric in query_metrics:
                        dataset_code = field_dataset.get(metric.fact_field_code or "")
                        scope = (
                            "whole_settlement"
                            if dataset_code == anchor_field.dataset_code
                            else "fee_item"
                        )
                        by_scope[scope].append(ObjectVersionMetric.from_metric(metric))
                    groups = list(by_scope.items())
                for query_scope, group in groups:
                    planner.compile(SemanticQuery(
                        object_code=object_code,
                        scope=QueryScope(
                            entity_code=anchor_key.entity_code,
                            anchor=QueryAnchor(
                                field_code=anchor_field.field_code,
                                value="__publish_check__",
                            ),
                            query_scope=query_scope,
                        ),
                        metrics=[metric.metric_code for metric in group],
                    ))
            except SemanticQueryPlanningError as exc:
                raise ValueError(f"查询模型不可编译: {exc}") from exc
        self._store.save_object_version(snapshot)
        obj.current_version = next_version
        obj.status = "published"
        self._store.save_object(obj)
        # 同步 metric.status → published（解锁 build_extraction_schema / 契约，§5 发布）
        for m in publish_metrics:
            m.status = "published"
            self._store.save_metric(m)
        for dataset in datasets:
            self._store.save_dataset(dataset.model_copy(update={"status": "published"}))
        for item in fields:
            self._store.save_field(item.model_copy(update={"status": "published"}))
        for item in relations:
            self._store.save_dataset_relation(item.model_copy(update={"status": "published"}))
        for item in quality_rules:
            self._store.save_quality_rule(item.model_copy(update={"status": "published"}))
        return snapshot

    def validate_query_model(self, object_code: str) -> list[str]:
        """返回阻断发布的查询模型结构问题。"""
        datasets = self._store.list_datasets(object_code)
        keys = self._store.list_dataset_keys(object_code=object_code)
        fields = self._store.list_fields(object_code=object_code)
        relations = self._store.list_dataset_relations(object_code)
        metrics = self._store.list_metrics(object_code)
        dataset_codes = {item.dataset_code for item in datasets}
        field_codes = {item.field_code for item in fields}
        key_by_code = {item.key_code: item for item in keys}
        issues: list[str] = []
        if len({item.datasource_id for item in datasets}) > 1:
            issues.append("query model cannot span multiple datasources")
        columns_by_dataset: dict[str, set[str]] = defaultdict(set)
        nullable_by_column: dict[tuple[str, str], bool] = {}
        for field in fields:
            columns_by_dataset[field.dataset_code].add(field.column_name)
            nullable_by_column[(field.dataset_code, field.column_name)] = field.nullable
        for dataset in datasets:
            primary_keys = [key for key in keys if key.dataset_code == dataset.dataset_code and key.key_type == "primary"]
            if len(primary_keys) != 1:
                issues.append(f"dataset '{dataset.dataset_code}' must have exactly one primary key")
        for key in keys:
            if set(key.columns) - columns_by_dataset[key.dataset_code]:
                issues.append(f"key '{key.key_code}' references unknown columns")
            if key.key_type == "primary" and any(
                nullable_by_column.get((key.dataset_code, column), True) for column in key.columns
            ):
                issues.append(f"primary key '{key.key_code}' contains nullable columns")
        for field in fields:
            if field.dataset_code not in dataset_codes:
                issues.append(f"field '{field.field_code}' references unknown dataset")
        for relation in relations:
            from_key = key_by_code.get(relation.from_key)
            to_key = key_by_code.get(relation.to_key)
            if not from_key or from_key.dataset_code != relation.from_dataset:
                issues.append(f"relation '{relation.relation_code}' has invalid from_key")
            if not to_key or to_key.dataset_code != relation.to_dataset:
                issues.append(f"relation '{relation.relation_code}' has invalid to_key")
            if from_key and to_key and len(from_key.columns) != len(to_key.columns):
                issues.append(f"relation '{relation.relation_code}' key width mismatch")
            if from_key and to_key and from_key.entity_code != to_key.entity_code:
                issues.append(f"relation '{relation.relation_code}' joins different entities")
        for metric in metrics:
            if metric.fact_field_code and metric.fact_field_code not in field_codes:
                issues.append(f"metric '{metric.metric_code}' references unknown fact field")
            if metric.fact_field_code and not metric.aggregation:
                issues.append(f"metric '{metric.metric_code}' missing aggregation")
        metric_by_code = {item.metric_code: item for item in metrics}
        query_metrics = [item for item in metrics if item.fact_field_code or item.expression]
        if datasets and not query_metrics:
            issues.append("query model has no queryable metrics")
        dependency_graph: dict[str, list[str]] = {}
        for metric in metrics:
            if not metric.expression:
                continue
            from src.semantic_layer.query_planner import SemanticQueryPlanner, SemanticQueryPlanningError
            try:
                SemanticQueryPlanner._validate_expression(ObjectVersionMetric.from_metric(metric))
            except SemanticQueryPlanningError as exc:
                issues.append(str(exc))
            dependencies = [
                code if "." in code else f"{object_code}.{code}"
                for code in metric.dependencies
            ]
            dependency_graph[metric.metric_code] = dependencies
            for code in dependencies:
                if code not in metric_by_code:
                    issues.append(f"metric '{metric.metric_code}' depends on unknown metric '{code}'")

        def visit(code: str, visiting: set[str], visited: set[str]) -> None:
            if code in visiting:
                issues.append(f"metric '{code}' has cyclic dependencies")
                return
            if code in visited:
                return
            for dependency in dependency_graph.get(code, []):
                visit(dependency, {*visiting, code}, visited)
            visited.add(code)

        visited: set[str] = set()
        for code in dependency_graph:
            visit(code, set(), visited)
        quality_rules = self._store.list_quality_rules(object_code)
        if datasets and not any(rule.rule_type == "coverage" for rule in quality_rules):
            issues.append("query model missing coverage rule")
        obj = self._store.get_object(object_code)
        relation_codes = {item.relation_code for item in relations}
        if obj:
            for path in obj.preferred_relation_paths:
                if any(code not in relation_codes for code in path.relation_codes):
                    issues.append("preferred relation path references unknown relation")
        return issues

    def get_object_version(self, object_code: str, version: str) -> Optional[BusinessObjectVersion]:
        return self._store.get_object_version(object_code, version)

    def list_object_versions(self, object_code: str) -> list[BusinessObjectVersion]:
        return self._store.list_object_versions(object_code)


def create_registry(use_memory: bool = False) -> SemanticRegistry:
    """Create SemanticRegistry with appropriate backend."""
    if use_memory or os.environ.get("USE_MEMORY_STORAGE") == "1":
        return SemanticRegistry(InMemoryRegistryStore())
    from src.data_platform.storage.postgresql.semantic_registry_store import (
        PostgresRegistryStore,
    )
    return SemanticRegistry(PostgresRegistryStore())


# ============================================================
# 全局 SemanticRegistry 单例（业务对象/Metric/值域的 CRUD 入口）
# ============================================================
# 集中在语义层维护，避免服务层（data_query、discovery）反向依赖 API 路由层。
_semantic_registry_instance: Optional[SemanticRegistry] = None


def get_semantic_registry() -> SemanticRegistry:
    """获取全局 SemanticRegistry 单例（项目唯一注册表）。

    依赖方向：路由层 / 服务层 → 语义层。
    """
    global _semantic_registry_instance
    if _semantic_registry_instance is not None:
        return _semantic_registry_instance
    if os.environ.get("USE_MEMORY_STORAGE") == "1":
        from src.semantic_layer.seed import (
            publish_seed_outpatient_query_object,
            publish_seed_policy_object,
            publish_seed_query_object,
            seed_settlement_domain,
        )
        store = InMemoryRegistryStore()
        seed_settlement_domain(store)
        reg = SemanticRegistry(store)
        # P8.3：种子后发布 zcgz，解锁提取契约（build_extraction_schema 只收 published）
        publish_seed_policy_object(reg)
        publish_seed_query_object(reg)
        publish_seed_outpatient_query_object(reg)
        _semantic_registry_instance = reg
    else:
        from src.data_platform.storage.postgresql.semantic_registry_store import (
            PostgresRegistryStore,
        )
        _semantic_registry_instance = SemanticRegistry(PostgresRegistryStore())
    return _semantic_registry_instance
