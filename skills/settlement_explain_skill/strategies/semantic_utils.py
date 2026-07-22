"""
semantic_utils.py — 语义工具函数

提供两种能力：
1. make_llm_readable: 将结算上下文/IndicatorContext 转换为 LLM 可读的自然语言描述
2. validate_fee_composition: 使用 FormulaEvaluator 校验费用组成一致性

用于增强 AI 对当前业务上下文的感知能力，
以及自动检测费用字段的数值一致性。
"""

from __future__ import annotations

import logging
from typing import Any

from src.domain.indicator.models import IndicatorContext, MetricFormula
from src.semantic_layer.formula_evaluator import FormulaEvaluator
from src.semantic_layer.llm_readable import get_llm_readable_generator

logger = logging.getLogger(__name__)

_DEFAULT_LLM_READABLE = (
    "患者为退休人员，参保城镇职工基本医疗保险，三级医院住院。"
    "本次住院起付线未获取，统筹自付未获取，大额自付未获取。"
)


def make_llm_readable(context_or_indicators: Any) -> str:
    """将结算上下文转换为 LLM 可读的自然语言描述。

    支持两种输入：
    1. IndicatorContext 对象（含 .indicators 属性）— 使用 LLMReadableGenerator
    2. 原始结算上下文（含 insurance_type/person_type 等属性）— 自行组装

    Args:
        context_or_indicators: 结算上下文对象或 IndicatorContext 实例

    Returns:
        自然语言描述，可直接嵌入 LLM prompt
    """
    # ── 情形 A：IndicatorContext ──
    if isinstance(context_or_indicators, IndicatorContext):
        generator = get_llm_readable_generator()
        context: IndicatorContext = context_or_indicators
        if context.indicators:
            return generator.generate_policy_context(context)
        # fallback: 用 generate_indicator_summary
        return generator.generate_indicator_summary(context)

    # ── 情形 B：原始结算上下文（属性式访问） ──
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


def validate_fee_composition(ctx: Any) -> dict:
    """校验个人总支付的费用组成一致性。

    使用 FormulaEvaluator 检查：
        personal_total_pay ≈ deductible + basic_pooling_self_pay + large_amount_self_pay

    如果差值大于 1 元，说明存在其他个人负担项（如目录外自费、先行自付等）。

    Args:
        ctx: 结算上下文（需有 personal_total_pay, deductible,
             basic_pooling_self_pay, large_amount_self_pay 属性）

    Returns:
        {
            "is_consistent": bool,   # 是否一致（差值 ≤ 1 元）
            "computed": float,        # 三组件之和
            "actual": float,          # 实际 personal_total_pay
            "difference": float,      # actual - computed
            "message": str,           # 中文描述
        }
    """
    raw_amt = getattr(ctx, "personal_total_pay", 0) or 0
    raw_deductible = getattr(ctx, "deductible", 0) or 0
    raw_pool_self = getattr(ctx, "basic_pooling_self_pay", 0) or 0
    raw_large_self = getattr(ctx, "large_amount_self_pay", 0) or 0

    # 使用 FormulaEvaluator 计算组件和与总支付的差值
    evaluator = FormulaEvaluator()
    formula = MetricFormula(
        expression="personal_total_pay - (deductible + pooling_self_pay + large_amount_self_pay)",
        dependencies=["personal_total_pay", "deductible", "pooling_self_pay", "large_amount_self_pay"],
    )
    try:
        diff = evaluator.evaluate(formula, {
            "personal_total_pay": raw_amt,
            "deductible": raw_deductible,
            "pooling_self_pay": raw_pool_self,
            "large_amount_self_pay": raw_large_self,
        })
    except (ValueError, TypeError):
        diff = float("inf")

    computed = float(raw_deductible + raw_pool_self + raw_large_self)
    actual = float(raw_amt)
    is_consistent = diff != float("inf") and abs(diff) <= 1.0

    if is_consistent:
        message = (
            f"个人总支付 {actual:.2f} 元与起付线 {raw_deductible:.2f} 元 + "
            f"统筹自付 {raw_pool_self:.2f} 元 + 大额自付 {raw_large_self:.2f} 元 "
            f"之和 {computed:.2f} 元一致，费用组成完整。"
        )
    else:
        message = (
            f"注意：起付线 {raw_deductible:.2f} 元 + 统筹自付 {raw_pool_self:.2f} 元 + "
            f"大额自付 {raw_large_self:.2f} 元 = {computed:.2f} 元，"
            f"与个人总支付 {actual:.2f} 元相差 {abs(diff):.2f} 元，"
            f"表明存在其他个人负担项（如目录外自费、先行自付等）或存在舍入差异。"
        )

    return {
        "is_consistent": is_consistent,
        "computed": computed,
        "actual": actual,
        "difference": diff if diff != float("inf") else 0.0,
        "message": message,
    }


# ════════════════════════════════════════════════════════════════
# 语义层桥接工具 — 连接 semantic_layer 与 Strategy 执行
# ════════════════════════════════════════════════════════════════


class ContextProxy:
    """
    统一属性访问代理。

    同时包装 settlement_context（任意对象）和 IndicatorContext，
    让 getattr 能透明访问任一来源的值，Strategy 无需感知上下文类型。

    优先级：IndicatorContext.indicators > IndicatorContext 直接属性 > settlement_context 属性
    注意：__getattr__ 仅在常规属性查找失败时调用，因此不会干扰已有属性。
    """

    def __init__(
        self,
        settlement_ctx: Any,
        indicator_ctx: IndicatorContext | None = None,
    ) -> None:
        self._settlement_ctx = settlement_ctx
        self._indicator_ctx = indicator_ctx

    def __getattr__(self, name: str) -> Any:
        # 跳过私有/特殊属性（避免 recursion）
        if name.startswith("_"):
            raise AttributeError(name)

        # 优先从 IndicatorContext.indicators 中取值
        if self._indicator_ctx is not None:
            indicators = self._indicator_ctx.indicators
            if name in indicators:
                val = indicators[name].value
                if val is not None:
                    return val
            # 尝试 IndicatorContext 的直接属性（patient_id, encounter_id, settlement_id）
            if hasattr(self._indicator_ctx, name):
                return getattr(self._indicator_ctx, name)

        # 兜底：从 settlement_context 取值
        if self._settlement_ctx is not None:
            return getattr(self._settlement_ctx, name)

        raise AttributeError(
            f"'{type(self).__name__}' object has no attribute '{name}'"
        )


def extract_dimension_filters(ctx: IndicatorContext) -> dict[str, str]:
    """从 IndicatorContext 提取维度值作为 Milvus 标量过滤字典

    遍历上下文中的所有指标，找出 category='dimension' 且 use_in_filter=True 的指标，
    将其 policy_field → normalized_value 收集为过滤字典。
    仅在 ctx 确为 IndicatorContext 时有效，否则返回空字典。

    Args:
        ctx: 已取值的指标上下文

    Returns:
        {policy_field: str_value} 字典，可用于 StructuredPolicyQuery.filters
    """
    if not isinstance(ctx, IndicatorContext):
        return {}

    from src.semantic_layer.registry import get_registry

    registry = get_registry()
    filters: dict[str, str] = {}

    for ind_id, ind_value in ctx.indicators.items():
        definition = registry.get(ind_id)
        if not definition or definition.category != "dimension":
            continue
        if not definition.use_in_filter:
            continue
        if ind_value.value is None:
            continue

        field = definition.policy_field or ind_id
        filters[field] = str(ind_value.value)

    return filters


def normalize_dimension_value(value: Any, category: str) -> str | None:
    """使用注册表字典将原始维度值标准化

    将外部系统原始值（如 '310'）映射为标准显示值（如 '城镇职工基本医疗保险'）。
    匹配策略参见 IndicatorRegistry.normalize_value。

    Args:
        value: 原始值（如 '310', '1', '三级'）
        category: 字典类别（如 '险种类别', '人员类别', '医疗类别', '医院等级'）

    Returns:
        标准化后的显示值，未匹配则返回 None
    """
    from src.semantic_layer.registry import get_registry

    if value is None:
        return None

    registry = get_registry()
    return registry.normalize_value(category, str(value))


def build_milvus_filter_from_context(
    ctx: IndicatorContext,
    question: str = "",
) -> dict[str, Any] | None:
    """使用 PolicyBridge 从指标上下文构建完整的 Milvus 搜索参数

    返回包含 filter_expr、query_text、dimensions_summary 的搜索参数字典。
    仅在 ctx 为 IndicatorContext 且 PolicyBridge 可用时有效。

    Args:
        ctx: 已取值的指标上下文
        question: 用户原始提问（用于向量搜索嵌入）

    Returns:
        PolicyBridge.build_search_query() 的输出，或 None（如果不可用）
    """
    if not isinstance(ctx, IndicatorContext):
        return None

    try:
        from src.semantic_layer.policy_bridge import get_policy_bridge

        bridge = get_policy_bridge()
        return bridge.build_search_query(ctx, question)
    except ImportError:
        return None


def build_structured_query_from_context(
    ctx: IndicatorContext,
    query_name: str = "dynamic_from_context",
    text_must_include_any: list[str] | None = None,
    text_must_include_all: list[str] | None = None,
    psn_type_allow_all: bool = False,
    required: bool = True,
) -> Any | None:
    """将 IndicatorContext 维度值转换为 StructuredPolicyQuery

    使用 extract_dimension_filters 获取维度过滤条件，包装为标准查询对象。
    各策略可在此基础上追加特定过滤条件（如 rule_type）。

    Args:
        ctx: 已取值的指标上下文
        query_name: 查询名称
        text_must_include_any: source_text 至少包含的关键词
        text_must_include_all: source_text 必须全部包含的关键词
        psn_type_allow_all: 是否允许 psn_type 宽松匹配
        required: 是否为必需查询

    Returns:
        StructuredPolicyQuery 实例，无维度值时返回 None
    """
    from src.runtime.policy_qa.structured_policy_retriever import (
        StructuredPolicyQuery,
    )

    filters = extract_dimension_filters(ctx)
    if not filters:
        return None

    return StructuredPolicyQuery(
        query_name=query_name,
        required=required,
        filters=filters,
        text_must_include_any=text_must_include_any or [],
        text_must_include_all=text_must_include_all or [],
        psn_type_allow_all=psn_type_allow_all,
    )
