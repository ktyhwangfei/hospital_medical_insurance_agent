"""
指标上下文构建器 - 将原始指标值组装为 IndicatorContext

职责:
1. 接收原始键值对和患者/就诊标识
2. 包装为 IndicatorValue 对象
3. 计算整体置信度和质量状态
4. 标记缺失指标
"""
import logging
from datetime import datetime
from typing import Any, Optional

from src.domain.indicator.models import IndicatorContext, IndicatorValue
from src.semantic_layer.registry import get_registry

logger = logging.getLogger(__name__)


class IndicatorContextBuilder:
    """
    指标上下文构建器

    将原始值字典（从 SQL/Adapter 查询获取）和患者信息组装为 IndicatorContext。
    自动计算置信度和质量状态。
    """

    def __init__(self) -> None:
        self._registry = get_registry()

    # ============================================================
    # 核心构建方法
    # ============================================================

    def build_context(
        self,
        indicator_ids: list[str],
        raw_values_dict: dict[str, Any],
        patient_id: str = "",
        encounter_id: str = "",
        settlement_id: str = "",
    ) -> IndicatorContext:
        """构建完整指标上下文

        Args:
            indicator_ids: 期望的指标 ID 列表
            raw_values_dict: 原始值字典 {indicator_id: raw_value}
            patient_id: 患者 ID
            encounter_id: 就诊 ID
            settlement_id: 结算单号

        Returns:
            组装好的 IndicatorContext
        """
        indicators: dict[str, IndicatorValue] = {}
        missing: list[str] = []

        for ind_id in indicator_ids:
            definition = self._registry.get(ind_id)

            if ind_id in raw_values_dict:
                raw_value = raw_values_dict[ind_id]
                # 构建指标值对象
                ind_value = self._build_value(
                    definition_id=ind_id,
                    raw_value=raw_value,
                    settlement_id=settlement_id,
                    definition=definition,
                )
                indicators[ind_id] = ind_value
            else:
                # 记录缺失指标
                missing.append(ind_id)

        # 计算整体质量
        total = len(indicator_ids)
        missing_count = len(missing)
        quality = self._compute_quality(total, missing_count)
        confidence = self._compute_confidence(total, missing_count)

        logger.info(
            "指标上下文构建完成: %d/%d 已取值, %d 缺失, 质量=%s, 置信度=%.2f",
            total - missing_count,
            total,
            missing_count,
            quality,
            confidence,
        )

        return IndicatorContext(
            patient_id=patient_id,
            encounter_id=encounter_id,
            settlement_id=settlement_id,
            indicators=indicators,
            missing_indicators=missing,
            quality=quality,
            confidence=confidence,
        )

    # ============================================================
    # 辅助方法
    # ============================================================

    def _build_value(
        self,
        definition_id: str,
        raw_value: Any,
        settlement_id: str = "",
        definition: Optional[Any] = None,
    ) -> IndicatorValue:
        """将原始值包装为 IndicatorValue

        Args:
            definition_id: 指标 ID
            raw_value: 原始值
            settlement_id: 结算单号（上下文）
            definition: 指标定义（可选，用于获取单位等元数据）

        Returns:
            IndicatorValue 实例
        """
        unit = ""
        if definition:
            unit = definition.unit

        return IndicatorValue(
            definition_id=definition_id,
            value=raw_value,
            raw_value=raw_value,
            unit=unit,
            source="sql",
            confidence=1.0,
            timestamp=datetime.now(),
            context={"settlement_id": settlement_id},
        )

    @staticmethod
    def _compute_quality(total: int, missing_count: int) -> str:
        """根据缺失比例计算质量状态"""
        if missing_count == 0:
            return "complete"
        if missing_count <= total * 0.3:
            return "degraded"
        return "missing"

    @staticmethod
    def _compute_confidence(total: int, missing_count: int) -> float:
        """根据缺失比例计算整体置信度"""
        if total == 0:
            return 0.0
        return max(0.0, 1.0 - (missing_count / total))


# ============================================================
# 全局单例
# ============================================================

_builder_instance: Optional[IndicatorContextBuilder] = None


def get_context_builder() -> IndicatorContextBuilder:
    """获取全局上下文构建器单例"""
    global _builder_instance
    if _builder_instance is None:
        _builder_instance = IndicatorContextBuilder()
    return _builder_instance
