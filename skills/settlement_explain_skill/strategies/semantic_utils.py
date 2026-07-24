"""
semantic_utils.py — 语义工具函数

提供 make_llm_readable：将结算上下文转换为 LLM 可读的自然语言描述，
用于增强 AI 对当前业务上下文的感知能力。

说明：历史上本模块还承载过 IndicatorContext 语义层增强路径
（validate_fee_composition、extract_dimension_filters、build_structured_query_from_context、
ContextProxy 等），这些依赖 A 系语义层引擎，且仅在已退役的 execute_with_context
路径下被调用。双注册表收敛时整体移除，统一只保留面向原始结算上下文的自包含实现。
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

_DEFAULT_LLM_READABLE = (
    "患者为退休人员，参保城镇职工基本医疗保险，三级医院住院。"
    "本次住院起付线未获取，统筹自付未获取，大额自付未获取。"
)


def make_llm_readable(context_or_indicators: Any) -> str:
    """将结算上下文转换为 LLM 可读的自然语言描述。

    接收原始结算上下文（含 insurance_type/person_type 等属性），自行组装为
    可直接嵌入 LLM prompt 的自然语言描述。

    Args:
        context_or_indicators: 结算上下文对象（属性式访问）

    Returns:
        自然语言描述
    """
    ctx = context_or_indicators
    if ctx is None:
        return _DEFAULT_LLM_READABLE

    parts: list[str] = []

    # 基础参保信息
    insu_type = str(getattr(ctx, "insurance_type", "") or "")
    psn_type = str(getattr(ctx, "person_type", "") or "")
    hosp_lv = str(getattr(ctx, "hospital_level", "") or "")
    service_type = str(getattr(ctx, "service_type", "") or "")

    # 人员类型映射
    _psn_map: dict[str, str] = {
        "1": "退休人员",
        "2": "在职人员",
        "3": "城乡居民",
    }
    psn_label = _psn_map.get(psn_type, psn_type) if psn_type else "未知"
    parts.append(f"患者为{psn_label}")

    if insu_type:
        parts.append(f"参保{insu_type}")
    else:
        parts.append("参保城镇职工基本医疗保险")

    if hosp_lv:
        parts.append(f"{hosp_lv}")
    else:
        parts.append("三级医院")

    if service_type:
        parts.append(f"{service_type}")
    parts.append(f"本次住院。")

    # 关键金额字段
    fee_fields = [
        ("deductible", "起付线"),
        ("basic_pooling_self_pay", "统筹自付"),
        ("large_amount_self_pay", "大额自付"),
        ("basic_pooling_payment", "统筹支付"),
        ("large_amount_payment", "大额支付"),
        ("personal_total_pay", "个人总支付"),
    ]

    fee_parts: list[str] = []
    for field, label in fee_fields:
        val = getattr(ctx, field, None)
        if val is not None and val != "" and val != 0:
            try:
                fmt_val = f"{float(val):,.2f}"
                fee_parts.append(f"{label}{fmt_val}元")
            except (ValueError, TypeError):
                fee_parts.append(f"{label}未获取")
        else:
            fee_parts.append(f"{label}未获取")

    if fee_parts:
        parts.append("费用构成：" + "，".join(fee_parts) + "。")

    # 患者/结算ID
    pid = getattr(ctx, "patient_id", "") or ""
    sid = getattr(ctx, "settlement_id", "") or ""
    if pid or sid:
        ids: list[str] = []
        if pid:
            ids.append(f"患者编号{pid}")
        if sid:
            ids.append(f"结算单号{sid}")
        parts.append("。".join(ids) + "。")

    return "".join(parts)
