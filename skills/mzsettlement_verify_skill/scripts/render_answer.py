"""把结构化核验结果渲染为 Portal 可展示文本。"""
from __future__ import annotations

from ..models import AmountCheck, ContextCheck, FieldExplanation, OutpatientVerificationResult

# 勾稽核验状态 → 展示结论；差额行已含数值，不再单独渲染旧「异常项」段
CHECK_STATUS_LABEL = {
    "passed": "勾稽一致",
    "failed": "不一致，需人工复核",
    "not_evaluable": "数据不全，未核算",
}


def _render_amount_line(item: FieldExplanation) -> str:
    """一行金额：原值 + 零值/未返回时的业务提示，不出现计算过程。"""
    if item.value is None:
        amount = "未返回"
    else:
        amount = f"{item.value} 元"
    if item.state == "non_zero":
        return f"- {item.field_name}：{amount}"
    return f"- {item.field_name}：{amount}（{item.explanation}）"


def _render_check_line(item: AmountCheck) -> str:
    """一行勾稽算式：带数值的算式优先，缺失时回退到实际/应得金额。"""
    def fmt(value: object) -> str:
        return "未返回" if value is None else f"{value} 元"

    core = item.detail or f"实际 {fmt(item.actual)}，应得 {fmt(item.expected)}"
    difference = f"，差额 {item.difference} 元" if item.difference is not None else ""
    return f"- {item.equation}：{core}{difference}（{CHECK_STATUS_LABEL[item.status]}）"


def render_answer(
    headline: str,
    result: OutpatientVerificationResult,
    fact_checks: list[ContextCheck],
    decomposition: list[str] | None = None,
    decomposition_title: str = "费用分解（逐层勾稽，取结算单原始字段）：",
) -> str:
    lines = [headline]
    if decomposition:
        lines.extend(("", decomposition_title))
        lines.extend(f"- {item}" for item in decomposition)
    lines.extend(("", "结算上下文："))
    lines.extend(
        f"- {item.name}：{item.value if item.value is not None else '未返回'}"
        for item in fact_checks
    )
    # 有分解段的场景：金额字段已由结构化 field_explanations 供前端卡片展示，
    # 文本不再重复整段罗列；无分解段的场景照旧展示。
    if result.field_explanations and not decomposition:
        lines.extend(("", "费用金额（取结算单原始字段）："))
        lines.extend(
            _render_amount_line(item) for item in result.field_explanations
        )
    # 分解段已含全部验证过的算式，不再重复渲染勾稽段；无分解段的场景照旧展示
    if result.amount_checks and not decomposition:
        lines.extend(("", "金额勾稽（取结算单原始字段确定性核算）："))
        lines.extend(_render_check_line(item) for item in result.amount_checks)
    if result.anomalies:
        lines.extend(("", "异常项：", *(f"- {item}" for item in result.anomalies)))
    return "\n".join(lines)
