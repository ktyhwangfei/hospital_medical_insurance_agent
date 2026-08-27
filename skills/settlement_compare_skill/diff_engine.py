"""
diff_engine.py — 结算上下文的确定性逐字段 diff（纯函数，无 IO）。

对两个 SettlementContext（基准 vs 对比单）逐字段比对，
仅产出有差异字段的 FieldDiff。所有比较逻辑确定、可测试，
不包含任何业务归因规则（归因规则见 strategies/compare/attribution_rules.yaml）。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# ── 参与对比的字段集 ──────────────────────────────────────────

# 数值字段：产出 delta 与 delta_ratio
NUMERIC_FIELDS: tuple[str, ...] = (
    "deductible",
    "medical_insurance_inner_amount",
    "basic_pooling_payment",
    "basic_pooling_self_pay",
    "large_amount_payment",
    "large_amount_self_pay",
    "personal_total_pay",
    "total_amount",
)

# 类别字段：仅比对是否一致（不产出 delta）
# 注意：settlement_year / cycle_no / yearly_cycle_count 是归因规则的「条件输入」
# （跨年、二次住院等规则的判定依据），不作为独立差异项展示——否则跨年对比时
# 这些字段永远触发 fallback，partial 永远无法收敛。规则条件仍可通过
# get_field_value 直接读取它们。
CATEGORICAL_FIELDS: tuple[str, ...] = (
    "person_type",
    "insurance_type",
    "service_type",
    "hospital_level",
)

DEFAULT_FIELDS: tuple[str, ...] = NUMERIC_FIELDS + CATEGORICAL_FIELDS

# 字段中文名（展示用）
FIELD_LABELS: dict[str, str] = {
    "deductible": "起付线",
    "medical_insurance_inner_amount": "医保内费用",
    "basic_pooling_payment": "统筹支付",
    "basic_pooling_self_pay": "统筹自付",
    "large_amount_payment": "大额支付",
    "large_amount_self_pay": "大额自付",
    "personal_total_pay": "个人总支付",
    "total_amount": "费用总额",
    "person_type": "人员类别",
    "insurance_type": "险种类型",
    "service_type": "医疗类别",
    "hospital_level": "医院等级",
    "cycle_no": "住院次数",
    "yearly_cycle_count": "年度累计住院次数",
    "settlement_year": "结算年份",
}


@dataclass(frozen=True)
class FieldDiff:
    """单字段差异（Value Object）。"""

    field: str
    label: str
    baseline_value: float | str | None
    current_value: float | str | None
    delta: float | None = None
    delta_ratio: float | None = None


def get_field_value(ctx: Any, field: str) -> Any:
    """解析上下文字段值，支持虚拟字段 settlement_year（由 settlement_date 派生）。"""
    if field == "settlement_year":
        date = str(getattr(ctx, "settlement_date", "") or "")
        return date[:4] if len(date) >= 4 and date[:4].isdigit() else ""
    return getattr(ctx, field, None)


def coerce_number(value: Any) -> float | None:
    """将数值型字符串（如 cycle_no）转为 float 参与比较；失败返回 None。"""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None


def diff_contexts(
    baseline: Any,
    current: Any,
    fields: list[str] | None = None,
) -> list[FieldDiff]:
    """逐字段比对基准与对比单，仅返回有差异的字段。

    Args:
        baseline: 基准 SettlementContext（属性式访问）
        current: 对比 SettlementContext
        fields: 指定对比字段子集；None 表示全字段对比

    Returns:
        FieldDiff 列表（零差异字段不产出），按 DEFAULT_FIELDS 声明顺序
    """
    target_fields = tuple(fields) if fields else DEFAULT_FIELDS
    diffs: list[FieldDiff] = []
    for field in target_fields:
        base_val = get_field_value(baseline, field)
        cur_val = get_field_value(current, field)
        base_num = coerce_number(base_val)
        cur_num = coerce_number(cur_val)

        if base_num is not None and cur_num is not None:
            # 双方均可数值化 → 数值比较
            if base_num == cur_num:
                continue
            delta = cur_num - base_num
            ratio = (cur_num / base_num) if base_num != 0 else None
            diffs.append(FieldDiff(
                field=field,
                label=FIELD_LABELS.get(field, field),
                baseline_value=base_num,
                current_value=cur_num,
                delta=delta,
                delta_ratio=ratio,
            ))
        else:
            # 类别比较（字符串/缺失值）
            base_norm = "" if base_val is None else str(base_val)
            cur_norm = "" if cur_val is None else str(cur_val)
            if base_norm == cur_norm:
                continue
            diffs.append(FieldDiff(
                field=field,
                label=FIELD_LABELS.get(field, field),
                baseline_value=base_norm,
                current_value=cur_norm,
            ))
    return diffs
