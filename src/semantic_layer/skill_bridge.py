"""
技能输入桥接 - 将指标上下文转化为技能执行器的输入参数

职责:
1. 根据 skill_id 查找技能所需的指标映射
2. 从 IndicatorContext 中提取对应指标值
3. 组装为技能执行器的输入字典

当前主要服务 settlement_explain_skill 技能。
"""
import logging
from typing import Any, Optional

from src.domain.indicator.models import IndicatorContext
from src.semantic_layer.registry import get_registry

logger = logging.getLogger(__name__)


class SkillBridge:
    """
    技能输入桥接

    将语义层的指标上下文转化为特定技能所需的输入格式。
    每个技能定义了自己的输入 schema，桥接负责映射。
    """

    # 技能 → 输入字段映射
    # key: skill_id
    # value: {skill_input_field: (indicator_id, default_value)}
    SKILL_INPUT_MAP: dict[str, dict[str, tuple[str, Any]]] = {
        "settlement_explain_skill": {
            "settlement_context": ("settlement_context", None),
            "target_fee_item": ("target_fee_item", None),
        },
        "settlement_anomaly_guide": {
            "error_code": ("error_code", ""),
            "settlement_status": ("settlement_status", ""),
        },
    }

    def __init__(self) -> None:
        self._registry = get_registry()

    def build_skill_input(
        self,
        skill_id: str,
        context: IndicatorContext,
        extra_params: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        """为指定技能构建输入参数

        Args:
            skill_id: 技能 ID（如 "settlement_explain_skill"）
            context: 已构建的指标上下文
            extra_params: 额外的非指标参数

        Returns:
            技能执行器的输入字典
        """
        input_map = self.SKILL_INPUT_MAP.get(skill_id, {})

        # 从 context 中提取指标值
        skill_input: dict[str, Any] = {}

        for field_name, (indicator_id, default) in input_map.items():
            if indicator_id and indicator_id in context.indicators:
                ind_value = context.indicators[indicator_id]
                skill_input[field_name] = ind_value.value
            elif default is not None:
                skill_input[field_name] = default

        # 添加额外参数
        if extra_params:
            skill_input.update(extra_params)

        # 对于 settlement_explain_skill，构建完整的结算上下文
        if skill_id == "settlement_explain_skill":
            skill_input = self._build_fee_explanation_input(context, skill_input, extra_params)

        logger.debug(
            "SkillBridge 为 '%s' 构建输入: %s",
            skill_id,
            {k: v for k, v in skill_input.items() if k != "settlement_context"},
        )
        return skill_input

    # ============================================================
    # 专用构建方法
    # ============================================================

    def _build_fee_explanation_input(
        self,
        context: IndicatorContext,
        base_input: dict[str, Any],
        extra_params: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        """构建费用解释技能的输入

        将指标上下文转化为 settlement_explain_skill assembler 所需的
        settlement_context 结构。

        组装逻辑:
        - 从 context.indicators 提取费用相关指标
        - 构建 settlement_context（含 patient_id, fee_items 等）
        - 构建 target_fee_item（需要解释的费用项目）
        """
        # 提取费用指标
        fee_indicators = self._collect_fee_indicators(context)

        settlement_context = {
            "patient_id": context.patient_id,
            "encounter_id": context.encounter_id,
            "settlement_id": context.settlement_id,
            "fee_items": fee_indicators,
            "indicators": {
                ind_id: {
                    "value": ind_val.value,
                    "unit": ind_val.unit,
                    "source": ind_val.source,
                }
                for ind_id, ind_val in context.indicators.items()
            },
        }

        # 构建目标费用项目（从 extra_params 或 context 推断）
        target_fee_item = None
        if extra_params and "target_fee_item" in extra_params:
            target_fee_item = extra_params["target_fee_item"]
        elif extra_params and "entity" in extra_params:
            target_fee_item = extra_params["entity"]

        return {
            "settlement_context": settlement_context,
            "target_fee_item": target_fee_item,
        }

    @staticmethod
    def _collect_fee_indicators(context: IndicatorContext) -> dict[str, float]:
        """从上下文中提取费用数值指标

        提取数值类指标（如 deductible_amount, in_scope_total 等）
        用于构建 fee_items 结构。

        Returns:
            {indicator_name: numeric_value} 的字典
        """
        fee_indicators: dict[str, float] = {}
        for ind_id, ind_value in context.indicators.items():
            if isinstance(ind_value.value, (int, float)):
                fee_indicators[ind_id] = float(ind_value.value)
        return fee_indicators


# ============================================================
# 全局单例
# ============================================================

_bridge_instance: Optional[SkillBridge] = None


def get_skill_bridge() -> SkillBridge:
    """获取全局技能桥接单例"""
    global _bridge_instance
    if _bridge_instance is None:
        _bridge_instance = SkillBridge()
    return _bridge_instance
