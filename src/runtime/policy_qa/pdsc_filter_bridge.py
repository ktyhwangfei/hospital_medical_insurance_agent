"""PDSC 政策过滤桥（设计 §10.3）：业务事实 → 政策适用条件 → Milvus 标量过滤。

Skill 不保存数据库字段、SQL 或关系值映射；本桥只在检索时把业务事实值
经已发布 PolicyApplicabilityRelation 转换为 zcgz 政策过滤条件。
无已发布关系时返回空 dict，检索行为与旧路径完全一致（渐进接入）。
"""
from __future__ import annotations

from typing import Any

# 结算上下文语义字段 → 业务指标编码（与 seed registry 对齐）
_CONTEXT_FIELD_TO_METRIC = {
    "hosp_lv": "djxx.hospital_level",
    "psn_type": "zyjyxx.rylb",
    "insu_type": "djxx.fund_type",
}


def build_pdsc_filters(
    settlement_context: dict[str, Any],
    service: Any | None = None,
) -> dict[str, str]:
    """把结算上下文中的业务事实值转换为政策标量过滤条件。

    返回 {zcgz 字段短名: 政策条件值}；仅包含能经已发布关系解析的条目。
    service 参数供测试注入；默认懒加载全局 PDSC 服务。
    """
    if service is None:
        try:
            from src.knowledge_extension.rule_explanation.pdsc import get_pdsc_service
            service = get_pdsc_service()
        except Exception:
            # PDSC 初始化失败不得阻断政策问答（信任边界）：退回旧路径
            return {}

    filters: dict[str, str] = {}
    for context_field, metric_code in _CONTEXT_FIELD_TO_METRIC.items():
        value = str(settlement_context.get(context_field, "")).strip()
        if not value:
            continue
        try:
            resolved = service.resolve_policy_filters(metric_code, value)
        except Exception:
            continue  # PDSC 不可用时退回旧路径，不阻断政策问答
        for policy_filter in resolved:
            field = policy_filter.policy_metric_code.split(".", 1)[-1]
            filters[field] = policy_filter.policy_value
    return filters
