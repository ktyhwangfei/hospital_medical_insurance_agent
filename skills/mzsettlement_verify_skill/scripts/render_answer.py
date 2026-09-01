"""把结构化核验结果渲染为 Portal 可展示文本。"""
from __future__ import annotations

from ..models import ContextCheck, FieldExplanation, OutpatientVerificationResult


def _render_amount_line(item: FieldExplanation) -> str:
    """一行金额：原值 + 零值/未返回时的业务提示，不出现计算过程。"""
    if item.value is None:
        amount = "未返回"
    else:
        amount = f"{item.value} 元"
    if item.state == "non_zero":
        return f"- {item.field_name}：{amount}"
    return f"- {item.field_name}：{amount}（{item.explanation}）"


def render_answer(
    headline: str,
    result: OutpatientVerificationResult,
    fact_checks: list[ContextCheck],
) -> str:
    lines = [headline, "", "结算上下文："]
    lines.extend(
        f"- {item.name}：{item.value if item.value is not None else '未返回'}"
        for item in fact_checks
    )
    if result.field_explanations:
        lines.extend(("", "费用金额（取结算单原始字段）："))
        lines.extend(
            _render_amount_line(item) for item in result.field_explanations
        )
    if result.anomalies:
        lines.extend(("", "异常项：", *(f"- {item}" for item in result.anomalies)))
    return "\n".join(lines)
