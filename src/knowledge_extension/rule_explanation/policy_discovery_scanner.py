"""policy_rules 发现扫描器（设计文档 §8.1）。

扫描已结构化的 policy_rules，统计高频实体类型/值、高频关系模式、值域候选，
产出候选指标列表（draft），供人工确认后回写语义层 zcgz 对象。

与语义层 discovery（扫 SQLServer 表发现字段）产物相似（都产出候选指标），
但数据源不同：本扫描器扫 policy_rules（Milvus），discovery 扫 SQLServer。

[来源: docs/steering/政策知识管线设计.md §8.1；开发计划 P7.3]
"""
from __future__ import annotations

from typing import Any

# 参与值域候选统计的详情字段（枚举/数值型；排除 source_text/entities/relations）
_VALUE_FIELDS = (
    "payment_ratio", "deductible_amount", "cap_amount",
    "rule_value", "amount_band",
)


def _unpack(field_val: Any) -> Any:
    """FieldTrace dict → value；裸值原样返回（兼容两种输入）。"""
    if isinstance(field_val, dict) and "value" in field_val:
        return field_val["value"]
    return field_val


def scan_rules_for_candidates(
    rules: list[dict[str, Any]], min_count: int = 2
) -> dict[str, Any]:
    """扫描 rules 的高频信号，产出候选指标列表。

    Args:
        rules: policy_rules_v2 entity 列表（详情字段可为 FieldTrace dict 或裸值）。
        min_count: entity type / relation pattern 进入候选的最低出现次数。
                   值域候选只要有值即提（用于发现新字典标准值）。

    Returns:
        {"candidates": [...], "total_rules": N}
        candidate.kind ∈ {entity, relation, value_domain}
    """
    entity_type_count: dict[str, int] = {}
    entity_name_count: dict[str, int] = {}
    relation_count: dict[str, int] = {}
    value_domain: dict[str, list[str]] = {}

    for rule in rules:
        for e in (_unpack(rule.get("entities")) or []):
            t = (e.get("type") or "").strip()
            n = (e.get("name") or "").strip()
            if t:
                entity_type_count[t] = entity_type_count.get(t, 0) + 1
            if n:
                entity_name_count[n] = entity_name_count.get(n, 0) + 1

        for r in (_unpack(rule.get("relations")) or []):
            pattern = f"{r.get('subject', '')}-{r.get('predicate', '')}-{r.get('object', '')}"
            relation_count[pattern] = relation_count.get(pattern, 0) + 1

        for field in _VALUE_FIELDS:
            v = _unpack(rule.get(field))
            if v not in (None, ""):
                value_domain.setdefault(field, []).append(str(v))

    candidates: list[dict[str, Any]] = []
    for t, c in sorted(entity_type_count.items(), key=lambda x: -x[1]):
        if c >= min_count:
            candidates.append({"kind": "entity", "value": t, "count": c, "suggested_name": t})
    for pattern, c in sorted(relation_count.items(), key=lambda x: -x[1]):
        if c >= min_count:
            candidates.append({"kind": "relation", "value": pattern, "count": c})
    for field, values in value_domain.items():
        distinct = sorted(set(values))
        if distinct:
            candidates.append({
                "kind": "value_domain", "field": field,
                "values": distinct, "count": len(values),
            })

    return {"candidates": candidates, "total_rules": len(rules)}
