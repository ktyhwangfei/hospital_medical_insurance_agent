"""
解释模式识别 — 统一「费用构成总览」与「单项费用项解释」的意图判定。

设计背景（C 方案）：
    原先 stream 端点与 settlement-explanation 端点各自硬编码
    ``target_fee_item = "pooling_self_pay"`` 作为默认值，导致任何未命中
    具体费用项关键词的问题（如「查询住院费用」）都被静默归入「统筹自付」单项，
    整条解释链只围绕统筹自付，与用户「要看整体费用构成」的预期错位。

    本模块把判定收敛为两类：
      - OVERVIEW      费用构成总览（默认 / 兜底，fail-safe 到总览而非单项）
      - SINGLE_ITEM   单项费用项解释（命中具体费用项关键词）

    两处端点（_policy_qa_stream / _process_single_settlement）统一调用
    ``detect_explanation_mode``，消除「有毒默认值」与重复判定逻辑。
"""

from __future__ import annotations

from enum import Enum


class ExplanationMode(str, Enum):
    """解释模式

    OVERVIEW:     费用构成总览 —— 展示整张结算单的费用结构（起付线/统筹支付/
                  统筹自付/大额支付/大额自付/个人总支付），不聚焦单项。
    SINGLE_ITEM:  单项费用项解释 —— 聚焦某个具体费用项（如「统筹自付为什么这么多」）。
    """

    OVERVIEW = "overview"
    SINGLE_ITEM = "single_item"


# 单项费用项关键词表（与 BenefitPoolingSelfPayAssembler._FEE_ITEM_MAP 对齐）。
# 顺序无关 —— 命中任一即判为 SINGLE_ITEM；关键词互斥，无歧义。
# 保持与原 _policy_qa_stream / _process_single_settlement 判定一致，仅收敛默认值。
SINGLE_ITEM_KEYWORDS: list[tuple[str, list[str]]] = [
    ("deductible", ["起付线", "起付标准", "门槛费"]),
    ("large_amount_self_pay", ["大额自付", "大额互助"]),
    ("pooling_payment", ["统筹支付", "统筹报销"]),
    ("personal_total_pay", ["个人总支付", "个人负担", "个人应负", "自己要付", "总共自己付"]),
    ("pooling_self_pay", ["统筹自付", "统筹自费", "基本统筹自付", "统筹段个人承担", "统筹个人自付"]),
    ("out_of_scope", ["医保外", "目录外", "丙类", "自费项目"]),
]

# 单项费用项 → 中文展示名（供 step public_message / 前端标识使用）
SINGLE_ITEM_LABELS: dict[str, str] = {
    "deductible": "起付线",
    "large_amount_self_pay": "大额自付",
    "pooling_payment": "统筹支付",
    "personal_total_pay": "个人总支付",
    "pooling_self_pay": "统筹自付",
    "out_of_scope": "医保外费用",
}


def fee_item_label(fee_item: str | None) -> str:
    """费用项编码 → 中文展示名；未知项回退到「费用」。"""
    return SINGLE_ITEM_LABELS.get(fee_item or "", "费用")


def detect_explanation_mode(question: str) -> tuple[ExplanationMode, str | None]:
    """问题 → (解释模式, 目标费用项)。

    Args:
        question: 用户原始问题

    Returns:
        (ExplanationMode, target_fee_item | None)
        - 命中具体费用项关键词 → (SINGLE_ITEM, fee_item)
        - 否则 → (OVERVIEW, None)

    设计原则：fail-safe 到 OVERVIEW（展示完整构成），而非静默退化到单项。
    「查询住院费用」「这单花了多少钱」等总览类问题天然落入 OVERVIEW。
    """
    if not question:
        return (ExplanationMode.OVERVIEW, None)

    for fee_item, keywords in SINGLE_ITEM_KEYWORDS:
        if any(kw in question for kw in keywords):
            return (ExplanationMode.SINGLE_ITEM, fee_item)

    return (ExplanationMode.OVERVIEW, None)
