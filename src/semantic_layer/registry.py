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
from dataclasses import dataclass, field
from typing import Optional, Protocol

from src.semantic_layer.models import (
    BusinessDomain, BusinessObject, Metric,
    ObjectVersionMetric, BusinessObjectVersion,
    ValueDomain, ValueDomainMapping,
)


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
    def get_metric(self, metric_code: str) -> Optional[Metric]: ...
    def list_metrics(self, object_code: Optional[str] = None) -> list[Metric]: ...
    def delete_metric(self, metric_code: str) -> None: ...
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
    _value_domains: dict[str, ValueDomain] = field(default_factory=dict)
    _value_mappings: dict[str, list[ValueDomainMapping]] = field(default_factory=lambda: defaultdict(list))
    _object_versions: dict[str, list[BusinessObjectVersion]] = field(
        default_factory=lambda: defaultdict(list))

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
        self._metrics[metric.metric_code] = metric

    def get_metric(self, metric_code: str) -> Optional[Metric]:
        return self._metrics.get(metric_code)

    def list_metrics(self, object_code: Optional[str] = None) -> list[Metric]:
        metrics = list(self._metrics.values())
        if object_code:
            metrics = [m for m in metrics if m.object_code == object_code]
        return metrics

    def delete_metric(self, metric_code: str) -> None:
        self._metrics.pop(metric_code, None)

    # Value Domain
    def save_value_domain(self, vd: ValueDomain) -> None:
        self._value_domains[vd.domain_code] = vd

    def get_value_domain(self, domain_code: str) -> Optional[ValueDomain]:
        return self._value_domains.get(domain_code)

    def save_value_mapping(self, vm: ValueDomainMapping) -> None:
        self._value_mappings[vm.domain_code].append(vm)

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

    def save_metric_draft(self, metric: Metric) -> None:
        """通过公开边界保存草稿指标，禁止调用方直接访问私有 store。"""
        if metric.status != "draft":
            raise ValueError("新建指标必须先保存为 draft")
        if self._store.get_object(metric.object_code) is None:
            raise ValueError(f"对象 '{metric.object_code}' 不存在")
        self._store.save_metric(metric)

    def get_value_domain(self, domain_code: str) -> Optional[ValueDomain]:
        return self._store.get_value_domain(domain_code)

    def save_value_domain(self, value_domain: ValueDomain) -> None:
        self._store.save_value_domain(value_domain)

    def save_value_mapping(self, mapping: ValueDomainMapping) -> None:
        self._store.save_value_mapping(mapping)

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
        existing = self._store.list_object_versions(object_code)
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
            },
            metrics=[ObjectVersionMetric.from_metric(m) for m in metrics],
            changelog=changelog,
            published_by=published_by,
        )
        self._store.save_object_version(snapshot)
        obj.current_version = next_version
        obj.status = "published"
        self._store.save_object(obj)
        # 同步 metric.status → published（解锁 build_extraction_schema / 契约，§5 发布）
        for m in metrics:
            m.status = "published"
            self._store.save_metric(m)
        return snapshot

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
            seed_settlement_domain, publish_seed_policy_object,
        )
        store = InMemoryRegistryStore()
        seed_settlement_domain(store)
        reg = SemanticRegistry(store)
        # P8.3：种子后发布 zcgz，解锁提取契约（build_extraction_schema 只收 published）
        publish_seed_policy_object(reg)
        _semantic_registry_instance = reg
    else:
        from src.data_platform.storage.postgresql.semantic_registry_store import (
            PostgresRegistryStore,
        )
        _semantic_registry_instance = SemanticRegistry(PostgresRegistryStore())
    return _semantic_registry_instance
