"""把结构化核验结果渲染为 Portal 可展示文本。"""
from __future__ import annotations

from ..models import ContextCheck, OutpatientVerificationResult


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
        lines.extend(("", "结算金额已按结算单原始字段列示。"))
    if result.anomalies:
        lines.extend(("", "异常项：", *(f"- {item}" for item in result.anomalies)))
    return "\n".join(lines)
