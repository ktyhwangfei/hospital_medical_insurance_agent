"""结算与政策标准的确定性对比计算。

纯函数：输入结算事实与政策证据（均为 dict），输出结构化对比结论。
计算可复现、结论可溯源到 rule_id；不调用模型、不访问外部数据源。
"""

from __future__ import annotations

from typing import Any

# 比例对比容差：统筹实际报销比例与政策分段比例的允许偏差。
RATIO_TOLERANCE = 0.02


def parse_policy_ratio(raw: Any) -> float | None:
    """把政策检索返回的比例字符串（'0.85'/'85%' 等）解析为 0~1 浮点。"""
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None
    try:
        value = float(text.rstrip("%"))
    except ValueError:
        return None
    if value > 1:
        value = value / 100
    return value if 0 < value <= 1 else None


def compare_settlement_vs_policy(
    settlement_fact: dict[str, Any], policy_evidence: dict[str, Any]
) -> dict[str, Any]:
    """对比结算事实与政策标准：实际统筹报销比例 vs 政策分段支付比例。

    比例口径：统筹支付 / 医保内金额（与 settlement_explain_skill 既有口径一致）。
    """
    inner_amount = float(settlement_fact.get("medical_insurance_inner_amount") or 0)
    pooling_payment = float(settlement_fact.get("basic_pooling_payment") or 0)
    comparisons: list[dict[str, Any]] = []

    if inner_amount > 0 and pooling_payment >= 0:
        actual_ratio = pooling_payment / inner_amount
        expected_ratios: list[float] = []
        matched_rules: list[str] = []
        for ev in policy_evidence.get("evidence", []):
            ratio = parse_policy_ratio(ev.get("payment_ratio"))
            if ratio is None:
                continue
            expected_ratios.append(ratio)
            if ev.get("rule_id"):
                matched_rules.append(ev["rule_id"])

        if expected_ratios:
            within = any(
                abs(actual_ratio - ratio) <= RATIO_TOLERANCE
                for ratio in expected_ratios
            )
            comparisons.append(
                {
                    "item": "统筹报销比例",
                    "actual": round(actual_ratio, 4),
                    "expected": sorted(round(r, 4) for r in expected_ratios),
                    "rule_ids": matched_rules,
                    "match": within,
                    "note": (
                        "实际统筹报销比例与政策分段比例一致（容差 ±2%）"
                        if within
                        else "实际统筹报销比例与政策分段比例存在差异，建议人工复核"
                    ),
                }
            )
        else:
            comparisons.append(
                {
                    "item": "统筹报销比例",
                    "actual": round(actual_ratio, 4),
                    "expected": [],
                    "rule_ids": [],
                    "match": False,
                    "note": "政策证据未携带可用支付比例，无法完成对比",
                }
            )

    all_match = bool(comparisons) and all(c["match"] for c in comparisons)
    if all_match:
        conclusion = "结算实际报销比例与政策标准一致，未发现异常。"
    elif comparisons:
        conclusion = "结算与政策标准对比存在差异或证据不足，建议人工复核。"
    else:
        conclusion = "结算事实缺少金额字段，无法完成对比。"
    return {
        "comparisons": comparisons,
        "all_match": all_match,
        "conclusion": conclusion,
        "comparison_count": len(comparisons),
    }
