"""
数据查询服务 — 根据指标映射从数据源获取实际值

职责:
1. 接收指标编码列表 → 解析 source_table + source_field
2. 按表分组 → 调用 adapter 查询 → 返回结构化数据
3. 作为 Skill 执行前/中的数据获取通道

设计理由:
- metric.source_field = table.field 本身就是查询指令，无需额外映射层
- 按表分组减少 adapter 调用次数（一次查询拿整行）
- adapter 层负责对接具体数据源（HIS/EMR/医保接口），服务层只做编排
"""

import logging
from typing import Any

from src.semantic_layer.registry import get_semantic_registry

logger = logging.getLogger(__name__)


class MetricDataQueryService:
    """
    指标数据查询服务

    使用方式:
        svc = MetricDataQueryService()
        data = svc.query(["Settlement.total_fee", "Settlement.self_pay"],
                         patient_id="P001", encounter_id="E001")
        # data = {"Settlement.total_fee": 12586.40, "Settlement.self_pay": 3120.80}
    """

    def __init__(self):
        self._registry = get_semantic_registry()

    def resolve_metrics(self, metric_codes: list[str]) -> dict[str, dict[str, Any]]:
        """
        将指标编码解析为查询指令。

        Returns:
            {metric_code: {table, field, object_code, metric_name}}
        """
        resolved: dict[str, dict[str, Any]] = {}
        for code in metric_codes:
            metric = self._registry.get_metric(code)
            if metric and metric.source_field:
                table = ""
                field = metric.source_field
                if "." in metric.source_field:
                    parts = metric.source_field.split(".", 1)
                    table = parts[0]
                    field = parts[1]
                elif metric.source_object:
                    table = metric.source_object
                resolved[code] = {
                    "table": table,
                    "field": field,
                    "source_field": metric.source_field,
                    "object_code": metric.object_code,
                    "metric_name": metric.name,
                }
            else:
                resolved[code] = {
                    "table": "",
                    "field": "",
                    "source_field": None,
                    "object_code": metric.object_code if metric else "",
                    "metric_name": metric.name if metric else code,
                    "unmapped": True,
                }
        return resolved

    def group_by_table(
        self, resolved: dict[str, dict[str, Any]]
    ) -> dict[str, list[tuple[str, str, str]]]:
        """
        按 source_table 分组，每组的 field 列表。

        Returns:
            {table_name: [(metric_code, field_name, source_field), ...]}
        """
        groups: dict[str, list[tuple[str, str, str]]] = {}
        for code, info in resolved.items():
            table = info["table"]
            if table:
                groups.setdefault(table, []).append(
                    (code, info["field"], info["source_field"])
                )
        return groups

    def query(
        self,
        metric_codes: list[str],
        patient_id: str = "",
        encounter_id: str = "",
        raw_data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """
        查询指标对应的实际数据值。

        当前 MVP 版本：从 raw_data 字典中提取（由调用方从 adapter 层获取）。
        生产版本：直接调用 adapter 的 query_table 方法。

        Args:
            metric_codes: 指标编码列表
            patient_id: 患者 ID
            encounter_id: 就诊 ID
            raw_data: 原始数据字典（MVP 阶段由调用方提供）

        Returns:
            {metric_code: value} 字典
        """
        resolved = self.resolve_metrics(metric_codes)
        results: dict[str, Any] = {}

        if raw_data:
            # MVP: 从已获取的原始数据中提取
            for code, info in resolved.items():
                sf = info.get("source_field")
                if sf and sf in raw_data:
                    results[code] = raw_data[sf]
                elif code in raw_data:
                    results[code] = raw_data[code]
                elif info.get("unmapped"):
                    results[code] = None
                    logger.debug("metric '%s' is unmapped, no value", code)
        else:
            # 生产路径：调用 SemanticDataSource 真实取数（复用 discovery 的 SQL Server 通道）
            # 组装 context：把所有可用标识符（patient_id/encounter_id/raw_data）交给 source，
            # source 按配置的 filter_context_key（默认 djh）从 context 取过滤值。
            try:
                from src.runtime.discovery.semantic_source import get_semantic_data_source

                context: dict[str, Any] = {}
                if patient_id:
                    context["patient_id"] = patient_id
                if encounter_id:
                    context["encounter_id"] = encounter_id
                if isinstance(raw_data, dict):
                    context.update(raw_data)
                source = get_semantic_data_source()
                results = source.query(metric_codes, context=context)
            except Exception:
                logger.warning(
                    "query: SemanticDataSource 取数失败，降级返回空结果",
                    exc_info=True,
                )

        return results

    def build_query_plan(self, metric_codes: list[str]) -> dict[str, Any]:
        """
        生成数据查询计划（供 Skill 执行决策使用）。

        Returns:
            {tables: [...], unmapped: [...], total_metrics: N}
        """
        resolved = self.resolve_metrics(metric_codes)
        groups = self.group_by_table(resolved)
        unmapped = [c for c, i in resolved.items() if i.get("unmapped")]
        return {
            "tables": list(groups.keys()),
            "unmapped": unmapped,
            "total_metrics": len(metric_codes),
            "mapped_count": len(metric_codes) - len(unmapped),
            "groups": {
                t: [{"metric_code": mc, "field": f} for mc, f, _ in flist]
                for t, flist in groups.items()
            },
        }


# 全局单例
_instance: MetricDataQueryService | None = None


def get_data_query_service() -> MetricDataQueryService:
    global _instance
    if _instance is None:
        _instance = MetricDataQueryService()
    return _instance
