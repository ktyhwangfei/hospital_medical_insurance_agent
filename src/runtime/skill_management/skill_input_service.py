"""Skill 输入指标语义服务（P4）。

实现设计 §5 核心：Skill 只声明输入指标，语义层决定查询方式。
- 输入指标校验门禁（§5.4）
- 只读查询计划预览（§5.2，不可被 Skill 覆盖）
- 样例取数测试（§5.4，复用 BusinessFactsBuilder）
- 输入选择器级联数据（§5.3：业务域→语义对象→指标）
"""

from __future__ import annotations

from typing import Any

from src.domain.skill.draft_models import (
    InputSpec,
    ValidationIssue,
    ValidationReport,
    ValidationSeverity,
)
from src.semantic_layer.registry import SemanticRegistry


class SkillInputService:
    """封装 SemanticRegistry，为 Skill 编辑器提供输入指标语义能力。"""

    def __init__(self, registry: SemanticRegistry) -> None:
        self._registry = registry

    # ── 校验门禁（§5.4）──────────────────────────────────────────

    def validate_inputs(self, specs: list[InputSpec]) -> ValidationReport:
        issues: list[ValidationIssue] = []
        seen: set[str] = set()
        for spec in specs:
            if spec.metric_code in seen:
                issues.append(self._blocking(
                    "DUPLICATE_INPUT", f"重复的输入指标: {spec.metric_code}",
                ))
                continue
            seen.add(spec.metric_code)
            metric = self._registry.get_metric(spec.metric_code)
            if metric is None:
                issues.append(self._blocking(
                    "METRIC_NOT_FOUND", f"指标不存在: {spec.metric_code}",
                    f"inputs.{spec.metric_code}",
                ))
                continue
            obj = self._registry.get_object(metric.object_code)
            if metric.status != "published" or (
                obj is not None and obj.current_version is None
            ):
                issues.append(self._blocking(
                    "METRIC_NOT_PUBLISHED",
                    f"指标未发布: {spec.metric_code}（status={metric.status}）",
                    f"inputs.{spec.metric_code}",
                ))
            # 对象未配置查询实现：无 adapter 且无 default_value
            if not metric.source_adapter_port and metric.default_value is None:
                issues.append(self._blocking(
                    "OBJECT_NO_QUERY_IMPLEMENTATION",
                    f"指标 {spec.metric_code} 所属对象未配置查询实现（无 adapter 且无默认值）",
                    f"inputs.{spec.metric_code}",
                ))
            # 结构化指标（有 adapter）无字段映射
            if (
                metric.source_adapter_port
                and not metric.source_field
                and metric.default_value is None
            ):
                issues.append(self._blocking(
                    "STRUCTURED_METRIC_NO_FIELD_MAPPING",
                    f"结构化指标 {spec.metric_code} 缺少字段映射（source_field）",
                    f"inputs.{spec.metric_code}",
                ))
        return ValidationReport(issues=issues)

    # ── 查询计划（§5.2，只读）────────────────────────────────────

    def build_query_plan(self, specs: list[InputSpec]) -> list[dict[str, Any]]:
        """按语义对象分组生成只读查询计划。"""
        groups: dict[str, dict[str, Any]] = {}
        for spec in specs:
            metric = self._registry.get_metric(spec.metric_code)
            if metric is None:
                groups.setdefault(
                    spec.metric_code,
                    {"object_code": spec.metric_code, "source_type": "unknown",
                     "status": "not_found", "metrics": []},
                )["metrics"].append(
                    {"metric_code": spec.metric_code, "alias": spec.alias,
                     "required": spec.required, "available": False}
                )
                continue
            obj = self._registry.get_object(metric.object_code)
            source_type = self._classify_source(metric, obj)
            group = groups.setdefault(
                metric.object_code,
                {
                    "object_code": metric.object_code,
                    "object_name": obj.name if obj else metric.object_code,
                    "object_status": obj.status if obj else "unknown",
                    "object_current_version": obj.current_version if obj else None,
                    "source_type": source_type,
                    "metrics": [],
                },
            )
            group["metrics"].append({
                "metric_code": metric.metric_code,
                "alias": spec.alias,
                "required": spec.required,
                "purpose": spec.purpose,
                "available": True,
                "source_adapter_port": metric.source_adapter_port,
                "source_field": metric.source_field,
                "default_value": metric.default_value,
            })
        return list(groups.values())

    @staticmethod
    def _classify_source(metric: Any, obj: Any) -> str:
        if metric.default_value is not None and not metric.source_adapter_port:
            return "constant"
        if metric.source_adapter_port:
            return "structured"  # 结构化数据库查询（adapter）
        # 无 adapter 无 default：政策知识/外部系统（运行时确定）
        return "policy_or_external"

    # ── 样例取数（§5.4）──────────────────────────────────────────

    def test_query(
        self, specs: list[InputSpec], context: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """样例取数测试。返回 facts（按对象分组）+ warnings，失败返回错误。"""
        from src.semantic_layer.builder import BusinessFactsBuilder
        from src.semantic_layer.models import (
            BusinessFactsRequest,
            ObjectMetricRequest,
        )

        # 按对象分组
        by_object: dict[str, list[str]] = {}
        for spec in specs:
            metric = self._registry.get_metric(spec.metric_code)
            object_code = metric.object_code if metric else spec.metric_code
            by_object.setdefault(object_code, []).append(
                metric.metric_code if metric else spec.metric_code
            )
        request = BusinessFactsRequest(
            objects=[
                ObjectMetricRequest(object_code=o, metric_codes=sorted(set(cs)))
                for o, cs in by_object.items()
            ],
            context=context or {},
        )
        builder = BusinessFactsBuilder(
            self._registry,
            adapter_builders=self._registry._adapter_builders  # noqa: SLF001
            if hasattr(self._registry, "_adapter_builders")
            else {},
        )
        try:
            response = builder.build(request)
            return {
                "facts": response.facts,
                "warnings": response.meta.warnings,
                "ok": True,
            }
        except Exception as exc:  # 样例取数失败不阻塞编辑，返回错误信息
            return {"facts": {}, "warnings": [str(exc)], "ok": False, "error": str(exc)}

    # ── 输入选择器级联数据（§5.3）────────────────────────────────

    def input_selector_tree(self) -> list[dict[str, Any]]:
        """业务域→语义对象→指标 的级联树，供前端输入选择器。"""
        domains = self._registry.list_domains()
        objects_by_domain: dict[str, list[Any]] = {}
        for obj in self._registry.list_objects():
            objects_by_domain.setdefault(obj.domain_code, []).append(obj)
        tree: list[dict[str, Any]] = []
        for domain in domains:
            domain_node: dict[str, Any] = {
                "domain_code": domain.domain_code,
                "name": domain.name,
                "objects": [],
            }
            for obj in objects_by_domain.get(domain.domain_code, []):
                metrics = self._registry.list_metrics(obj.object_code)
                metric_nodes = [
                    {
                        "metric_code": m.metric_code,
                        "name": m.name,
                        "definition": m.definition,
                        "source_type": self._classify_source(m, obj),
                        "source_adapter_port": m.source_adapter_port,
                        "source_field": m.source_field,
                        "status": m.status,
                        "importance": m.importance,
                        "quality_score": m.quality_score,
                        "current_version": obj.current_version,
                        "usage_count": m.usage_count,
                        "unit": m.unit,
                        "semantic_type": m.semantic_type,
                    }
                    for m in metrics
                ]
                domain_node["objects"].append({
                    "object_code": obj.object_code,
                    "name": obj.name,
                    "definition": obj.definition,
                    "status": obj.status,
                    "current_version": obj.current_version,
                    "metrics": metric_nodes,
                })
            tree.append(domain_node)
        return tree

    # ── 辅助 ──────────────────────────────────────────────────────

    @staticmethod
    def _blocking(code: str, message: str, path: str | None = None) -> ValidationIssue:
        return ValidationIssue(
            code=code, message=message, severity=ValidationSeverity.BLOCKING, path=path
        )
