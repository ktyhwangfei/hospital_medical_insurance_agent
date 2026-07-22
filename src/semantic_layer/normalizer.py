"""
语义标准化引擎 - 统一入口，外观模式

将原始指标值标准化为统一格式。

职责:
1. normalize_field(): 字段名映射（原始字段名 → 标准字段名）
2. normalize_value(): 值标准化（原始值 → 标准值，使用字典匹配）
3. build_milvus_filter(): 从指标上下文构建 Milvus 过滤表达式

后续 Phase 将逐步整合:
- DictionaryNormalizer（现有实现，从 Excel 读取）
- McpResultNormalizer（现有实现，MCP 结果标准化）
- SemanticMapper（现有实现，字段映射）
"""
import logging
from typing import Optional

from src.domain.indicator.models import IndicatorContext, IndicatorValue
from src.semantic_layer.registry import get_registry

logger = logging.getLogger(__name__)


class SemanticNormalizer:
    """
    语义标准化引擎

    统一入口，外观模式。当前使用注册表的字典数据进行标准化，
    后续 Phase 逐步委托到 DictionaryNormalizer / McpResultNormalizer / SemanticMapper。
    """

    def normalize_field(
        self,
        raw_field_name: str,
        raw_value: object = None,
    ) -> tuple[str, object]:
        """标准化字段名和值

        字段名映射: 原始数据库字段名 → 标准 indicator_id
        值标准化: 如果字段有关联字典，进行字典匹配

        Args:
            raw_field_name: 原始字段名（如 "bdtczf"）
            raw_value: 原始值（如 "310"）

        Returns:
            (standard_field_name, standard_value) 元组
        """
        # 通过注册表查找指标定义
        registry = get_registry()
        definition = registry.get(raw_field_name)

        standard_name = raw_field_name
        standard_value = raw_value

        if definition and raw_value is not None:
            raw_str = str(raw_value)

            # 如果有字典引用，进行值标准化
            if definition.normalization.dictionary_ref:
                dict_category = definition.normalization.dictionary_ref
                normalized = registry.normalize_value(dict_category, raw_str)
                if normalized:
                    standard_value = normalized

            # 类型转换
            if definition.value_type == "float":
                try:
                    standard_value = float(raw_str)
                except (ValueError, TypeError):
                    pass

        return standard_name, standard_value

    def build_milvus_filter(self, context: IndicatorContext) -> str:
        """从指标上下文构建 Milvus 过滤表达式

        提取维度指标的标准化值，组合为 Milvus 标量过滤表达式。
        格式: "insu_type == '城镇职工基本医疗保险' AND hosp_lv == '三级医院'"

        Args:
            context: 指标上下文

        Returns:
            Milvus 过滤表达式字符串，无维度时返回空字符串
        """
        registry = get_registry()
        conditions = []

        for ind_id, ind_value in context.indicators.items():
            definition = registry.get(ind_id)
            if not definition or definition.category != "dimension":
                continue

            # 跳过没有 policy_field 映射的维度
            if not definition.policy_field:
                continue

            # 构建条件
            value = ind_value.value
            if value is None:
                continue

            # 字符串值加引号
            if isinstance(value, str):
                # 转义单引号
                safe_value = value.replace("'", "\\'")
                conditions.append(f"{definition.policy_field} == '{safe_value}'")
            else:
                conditions.append(f"{definition.policy_field} == {value}")

        if not conditions:
            return ""

        return " AND ".join(conditions)

    def normalize_context(self, context: IndicatorContext) -> IndicatorContext:
        """对整个上下文进行标准化

        对上下文中每个指标值执行字段映射和值标准化。

        Args:
            context: 未标准化的指标上下文

        Returns:
            标准化后的指标上下文
        """
        normalized_indicators: dict[str, IndicatorValue] = {}

        for ind_id, ind_value in context.indicators.items():
            standard_name, standard_value = self.normalize_field(ind_id, ind_value.raw_value)

            # 创建标准化后的指标值
            normalized_value = ind_value.model_copy(deep=True)
            if standard_value is not None:
                normalized_value.value = standard_value
            normalized_indicators[standard_name] = normalized_value

        return context.model_copy(update={"indicators": normalized_indicators})


# ============================================================
# 全局单例
# ============================================================

_normalizer_instance: Optional[SemanticNormalizer] = None


def get_normalizer() -> SemanticNormalizer:
    """获取全局标准化引擎单例"""
    global _normalizer_instance
    if _normalizer_instance is None:
        _normalizer_instance = SemanticNormalizer()
    return _normalizer_instance
