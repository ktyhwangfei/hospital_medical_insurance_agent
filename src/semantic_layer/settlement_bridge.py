"""A-重：settlement_explain_skill 语义层数据桥接。

把 settlement_data_provider 的 SettlementContext（SQL 查询结果）桥接到
BusinessFactsBuilder，让 skill 数据消费经过语义层版本锁定。

数据源不变（settlement_data_provider 的 SQL），但经 BusinessFactsBuilder 的
get_metric_mapping（只读已发布版本快照），实现"skill 只能引用已发布指标"。
对象未发布时对应 facts 为空（锁定生效）。
"""
from __future__ import annotations

from typing import Any

from src.semantic_layer.models import BusinessFactsRequest, ObjectMetricRequest

# SettlementContext 语义名字段 → 物理表.列（与 seed 的 source_field 一致）
_SETTLEMENT_FIELD_TO_SOURCE: dict[str, tuple[str, str]] = {
    "deductible": ("yb_dyxxzy", "bcqfje"),
    "medical_insurance_inner_amount": ("yb_dyxxzy", "bcybnje"),
    "basic_pooling_payment": ("yb_zyfdxx", "bdtczfje"),
    "basic_pooling_self_pay": ("yb_zyfdxx", "bdtczf"),
    "large_amount_payment": ("yb_zyfdxx", "bddegwyzfje"),
    "large_amount_self_pay": ("yb_zyfdxx", "bddegwyzf"),
    "personal_total_pay": ("yb_zyfdxx", "bdgryf"),
    "person_type": ("yb_zyjyxx", "PER_TYPE"),
    "insurance_type": ("yb_brdjxx", "FUND_TYPE"),
    "service_type": ("yb_brdjxx", "yllb"),
}

# skill 声明消费的对象+指标（与 skill_manifest needed_objects 对齐）
_SKILL_OBJECTS = [
    ObjectMetricRequest(object_code="zydyxx", metric_codes=["bcqfje", "bcybnje"]),
    ObjectMetricRequest(object_code="zyfdxx",
                        metric_codes=["bdtczfje", "bdtczf", "bddezfje", "bddezf", "bdgryf"]),
    ObjectMetricRequest(object_code="zyjyxx", metric_codes=["rylb"]),
    ObjectMetricRequest(object_code="djxx", metric_codes=["fund_type", "yllb"]),
]


def settlement_context_to_adapter_data(ctx: Any) -> dict:
    """把 SettlementContext（语义名字段）转成嵌套 adapter data（表.列）。"""
    data: dict[str, dict[str, Any]] = {}
    for field_name, (table, col) in _SETTLEMENT_FIELD_TO_SOURCE.items():
        value = getattr(ctx, field_name, None)
        if value is None or value == "":
            continue
        data.setdefault(table, {})[col] = value
    return data


class PrefilledInsuranceAdapter:
    """预填数据的语义层适配器（复用 settlement_data_provider 查询结果）。

    实现 query_transaction，返回预填的嵌套 data，供 BusinessFactsBuilder._extract_field
    按 source_field（表.列）分层取值。
    """

    def __init__(self, data: dict):
        self._data = data

    def query_transaction(self, patient_id: str = "", encounter_id: str = ""):
        return type("Result", (), {
            "status": type("Status", (), {"value": "success"})(),
            "data": self._data,
        })()


def build_settlement_facts(ctx: Any) -> dict:
    """把 SettlementContext 经语义层 BusinessFactsBuilder 转成 facts。

    facts 结构：{object_code: {metric_short_name: value}}，经已发布版本锁定。
    对象未发布时对应对象 facts 为空（锁定生效）。
    """
    from src.semantic_layer.builder import BusinessFactsBuilder
    from src.semantic_layer.registry import get_semantic_registry

    data = settlement_context_to_adapter_data(ctx)
    adapter = PrefilledInsuranceAdapter(data)
    registry = get_semantic_registry()
    builder = BusinessFactsBuilder(registry, {"InsuranceInterfacePort": adapter})

    request = BusinessFactsRequest(
        objects=_SKILL_OBJECTS,
        context={
            "patient_id": getattr(ctx, "patient_id", "") or "",
            "encounter_id": getattr(ctx, "encounter_id", "") or "",
            "settlement_id": getattr(ctx, "settlement_id", "") or "",
        },
    )
    response = builder.build(request)
    return response.facts
