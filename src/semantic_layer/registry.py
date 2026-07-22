from __future__ import annotations

import os

"""
指标注册表 - 扫描 indicators/ 目录加载指标定义和字典

功能:
1. 扫描 indicators/_from_datamodel1/policy_fields.yaml 加载指标定义
2. 扫描 indicators/dictionaries/ 加载标准化字典
3. 按需扫描 indicators/fee/（如存在）加载费用类指标
4. 提供全局单例 get_registry() 供其他模块使用
"""
import logging
from pathlib import Path
from typing import Optional

import yaml

from src.config.semantic_layer import AUTO_GENERATED_DIR, DICTIONARIES_DIR
from src.domain.indicator.models import DictionaryEntry, IndicatorDefinition

logger = logging.getLogger(__name__)


class IndicatorRegistry:
    """
    指标注册表

    管理所有指标定义和字典的注册与查询。
    支持按 indicator_id、category、semantic tag 检索。
    """

    def __init__(self) -> None:
        # 指标定义: indicator_id → IndicatorDefinition
        self._definitions: dict[str, IndicatorDefinition] = {}
        # 字典: category_name → list[DictionaryEntry]
        self._dictionaries: dict[str, list[DictionaryEntry]] = {}
        # 语义标签 → indicator_id 列表的索引
        self._tag_index: dict[str, list[str]] = {}
        # 是否已初始化
        self._initialized: bool = False

    # ============================================================
    # 初始化与加载
    # ============================================================

    def initialize(self) -> None:
        """初始化注册表：扫描所有 YAML 文件并加载"""
        if self._initialized:
            return

        self._load_policy_fields()
        self._load_dictionaries()
        self._load_fee_indicators()
        self._build_tag_index()

        self._initialized = True
        logger.info(
            "指标注册表初始化完成: %d 个指标, %d 个字典类别",
            len(self._definitions),
            len(self._dictionaries),
        )

    def _load_policy_fields(self) -> None:
        """从 policy_fields.yaml 加载指标定义"""
        policy_path = Path(AUTO_GENERATED_DIR) / "policy_fields.yaml"
        if not policy_path.exists():
            logger.warning("policy_fields.yaml 不存在，请先运行 datamodel1_importer")
            return

        with open(policy_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)

        if not data or "indicators" not in data:
            logger.warning("policy_fields.yaml 格式无效或无指标定义")
            return

        for item in data["indicators"]:
            try:
                definition = IndicatorDefinition(**item)
                self._definitions[definition.indicator_id] = definition
            except Exception as e:
                logger.warning("跳过无效指标定义 %s: %s", item.get("indicator_id", "?"), e)

        logger.info("已加载 %d 个政策字段指标", len(data.get("indicators", [])))

    def _load_dictionaries(self) -> None:
        """扫描 dictionaries/ 目录加载所有字典 YAML"""
        dict_dir = Path(DICTIONARIES_DIR)
        if not dict_dir.exists():
            logger.warning("字典目录不存在: %s", dict_dir)
            return

        for yaml_file in sorted(dict_dir.glob("*.yaml")):
            try:
                with open(yaml_file, "r", encoding="utf-8") as f:
                    data = yaml.safe_load(f)

                if not data or "entries" not in data:
                    continue

                category = data.get("category", yaml_file.stem)
                entries = []
                for entry_data in data["entries"]:
                    entry = DictionaryEntry(
                        category=category,
                        standard_value=entry_data.get("standard_value", ""),
                        synonyms=entry_data.get("synonyms", []),
                        description=entry_data.get("description", ""),
                        code=entry_data.get("code"),
                    )
                    entries.append(entry)

                self._dictionaries[category] = entries
                logger.debug("已加载字典: %s (%d 条)", category, len(entries))
            except Exception as e:
                logger.warning("加载字典文件 %s 失败: %s", yaml_file, e)

        logger.info("已加载 %d 个字典类别", len(self._dictionaries))

    def _load_fee_indicators(self) -> None:
        """扫描 indicators/fee/ 目录（如存在）加载费用类指标"""
        from src.config.semantic_layer import INDICATORS_DIR

        fee_dir = Path(INDICATORS_DIR) / "fee"
        if not fee_dir.exists():
            logger.debug("费用指标目录不存在，跳过: %s", fee_dir)
            return

        for yaml_file in sorted(fee_dir.glob("*.yaml")):
            try:
                with open(yaml_file, "r", encoding="utf-8") as f:
                    data = yaml.safe_load(f)

                if not data or "indicators" not in data:
                    # 可能是单指标文件
                    if "indicator_id" in data:
                        data = {"indicators": [data]}
                    else:
                        continue

                for item in data["indicators"]:
                    try:
                        definition = IndicatorDefinition(**item)
                        self._definitions[definition.indicator_id] = definition
                    except Exception as e:
                        logger.warning("跳过无效费用指标 %s: %s", item.get("indicator_id", "?"), e)
            except Exception as e:
                logger.warning("加载费用指标文件 %s 失败: %s", yaml_file, e)

    def _build_tag_index(self) -> None:
        """构建语义标签 → indicator_id 的索引"""
        self._tag_index.clear()
        for def_id, definition in self._definitions.items():
            for tag in definition.semantic_tags:
                if tag not in self._tag_index:
                    self._tag_index[tag] = []
                self._tag_index[tag].append(def_id)

    # ============================================================
    # 指标查询
    # ============================================================

    def get(self, indicator_id: str) -> Optional[IndicatorDefinition]:
        """按 ID 获取指标定义"""
        self.initialize()
        return self._definitions.get(indicator_id)

    def list_all(self) -> list[IndicatorDefinition]:
        """获取全部指标定义"""
        self.initialize()
        return list(self._definitions.values())

    def list_by_category(self, category: str) -> list[IndicatorDefinition]:
        """按分类获取指标列表
        
        Args:
            category: "dimension" | "numeric" | "condition" | "meta"
        """
        self.initialize()
        return [d for d in self._definitions.values() if d.category == category]

    def search_by_tag(self, tag: str) -> list[IndicatorDefinition]:
        """按语义标签搜索指标
        
        Args:
            tag: 语义标签（如 "险种", "起付线"）

        Returns:
            匹配该标签的所有指标定义
        """
        self.initialize()
        ids = self._tag_index.get(tag, [])
        return [self._definitions[i] for i in ids if i in self._definitions]

    def search_by_keyword(self, keyword: str) -> list[IndicatorDefinition]:
        """按关键词在名称、描述、标签中搜索指标
        
        Args:
            keyword: 搜索关键词

        Returns:
            匹配的所有指标定义
        """
        self.initialize()
        keyword_lower = keyword.lower()
        results = []
        for definition in self._definitions.values():
            if (keyword_lower in definition.name.lower()
                    or keyword_lower in definition.description.lower()
                    or keyword_lower in definition.indicator_id.lower()
                    or any(keyword_lower in tag.lower() for tag in definition.semantic_tags)):
                results.append(definition)
        return results

    def list_dimensions(self) -> list[IndicatorDefinition]:
        """获取所有维度指标（用于 Milvus 过滤）"""
        return self.list_by_category("dimension")

    # ============================================================
    # 字典查询
    # ============================================================

    def get_dictionary(self, category: str) -> list[DictionaryEntry]:
        """按类别获取字典条目"""
        self.initialize()
        return self._dictionaries.get(category, [])

    def list_dictionary_categories(self) -> list[dict]:
        """获取所有字典分类及条目计数"""
        self.initialize()
        return [
            {"category": cat, "entry_count": len(entries)}
            for cat, entries in self._dictionaries.items()
        ]

    def get_dictionary_entries(self, category: str) -> list[DictionaryEntry] | None:
        """获取指定字典分类的条目，不存在返回 None"""
        self.initialize()
        if category not in self._dictionaries:
            return None
        return self._dictionaries[category]

    def get_importer_status(self) -> str:
        """获取导入器状态"""
        self.initialize()
        if self._definitions:
            return f"loaded_{len(self._definitions)}_indicators"
        return "no_data"

    def normalize_value(self, category: str, raw_value: str) -> Optional[str]:
        """使用字典将原始值标准化为标准值

        匹配策略:
        1. 完全匹配 standard_value
        2. 完全匹配 synonyms 列表
        3. 模糊匹配（raw_value 包含/被包含于 standard_value 或 synonyms）

        Args:
            category: 字典类别（如"险种类别"）
            raw_value: 原始值（如"310"或"职工医保"）

        Returns:
            标准化后的标准值，未匹配则返回 None
        """
        self.initialize()
        entries = self._dictionaries.get(category, [])
        if not entries:
            return None

        raw_lower = raw_value.strip().lower()

        # 1. 精确匹配 standard_value
        for entry in entries:
            if entry.standard_value.lower() == raw_lower:
                return entry.standard_value

        # 2. 精确匹配 synonyms
        for entry in entries:
            if any(s.lower() == raw_lower for s in entry.synonyms):
                return entry.standard_value

        # 3. 模糊匹配：raw_value 包含于 standard_value
        for entry in entries:
            if raw_lower in entry.standard_value.lower():
                return entry.standard_value

        # 4. 模糊匹配：raw_value 包含于某个 synonym
        for entry in entries:
            if any(raw_lower in s.lower() for s in entry.synonyms):
                return entry.standard_value

        return None


# ============================================================
# 全局单例
# ============================================================

_registry_instance: Optional[IndicatorRegistry] = None


def get_registry() -> IndicatorRegistry:
    """获取全局指标注册表单例"""
    global _registry_instance
    if _registry_instance is None:
        _registry_instance = IndicatorRegistry()
    _registry_instance.initialize()
    return _registry_instance


# ── Semantic Registry (Phase-1 Entity/Metric/ValueDomain CRUD) ──
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Protocol

from src.semantic_layer.models import (
    BusinessDomain, BusinessObject, Metric,
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


@dataclass
class InMemoryRegistryStore:
    """In-memory storage for development and testing. Use `USE_MEMORY_STORAGE=1`."""

    _domains: dict[str, BusinessDomain] = field(default_factory=dict)
    _objects: dict[str, BusinessObject] = field(default_factory=dict)
    _metrics: dict[str, Metric] = field(default_factory=dict)
    _value_domains: dict[str, ValueDomain] = field(default_factory=dict)
    _value_mappings: dict[str, list[ValueDomainMapping]] = field(default_factory=lambda: defaultdict(list))

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


class SemanticRegistry:
    """Semantic Registry — business-facing CRUD + query operations."""

    def __init__(self, store: RegistryStore):
        self._store = store

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

    def get_metric_mapping(
        self, object_code: str, metric_codes: list[str]
    ) -> list[Metric]:
        """Get Metric objects for Builder — skips nonexistent metrics silently."""
        result: list[Metric] = []
        for code in metric_codes:
            full_code = (
                code if "." in code
                else f"{object_code}.{code}"
            )
            metric = self._store.get_metric(full_code)
            if metric is not None:
                result.append(metric)
        return result

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


def create_registry(use_memory: bool = False) -> SemanticRegistry:
    """Create SemanticRegistry with appropriate backend."""
    if use_memory or os.environ.get("USE_MEMORY_STORAGE") == "1":
        return SemanticRegistry(InMemoryRegistryStore())
    from src.data_platform.storage.postgresql.semantic_registry_store import (
        PostgresRegistryStore,
    )
    return SemanticRegistry(PostgresRegistryStore())
