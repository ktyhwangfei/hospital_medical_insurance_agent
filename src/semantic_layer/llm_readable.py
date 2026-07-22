"""
LLM 可读化生成器 - 将指标定义和值转化为自然语言描述

用于 LLM 提示词中动态注入语义层信息，使大模型能够理解当前可用的数据指标。
包含两个核心能力:
1. generate_indicator_summary: 当前上下文中的指标值摘要
2. generate_available_indicators: 系统可用的指标定义列表
3. generate_policy_context: 政策检索场景的完整上下文描述
"""
import logging
from typing import Optional

from src.domain.indicator.models import IndicatorContext, IndicatorDefinition
from src.semantic_layer.registry import get_registry

logger = logging.getLogger(__name__)


class LLMReadableGenerator:
    """
    LLM 可读化生成器

    将结构化的指标数据转化为大语言模型易于理解的自然语言描述。
    用于增强 LLM 对当前业务上下文的感知能力。
    """

    def __init__(self) -> None:
        self._registry = get_registry()

    # ============================================================
    # 核心生成方法
    # ============================================================

    def generate_indicator_summary(self, context: IndicatorContext) -> str:
        """生成当前上下文的指标值摘要

        示例输出:
            "当前患者(patient_P001)的指标取值:
             - 起付金额: 650元 (来源: SQL查询, 置信度: 1.0)
             - 险种类别: 城镇职工 (来源: 适配器, 置信度: 1.0)
             - 医院等级: 三级医院 (来源: 适配器, 置信度: 1.0)
             整体置信度: 1.00, 数据质量: 完整"

        Args:
            context: 已构建的指标上下文

        Returns:
            自然语言描述
        """
        if not context.indicators:
            return "当前无可用指标数据。"

        lines: list[str] = []
        patient_info = f"患者({context.patient_id})" if context.patient_id else "当前"
        lines.append(f"{patient_info}的指标取值:")

        for ind_id, ind_value in context.indicators.items():
            definition = self._registry.get(ind_id)
            name = definition.name if definition else ind_id

            value_str = self._format_value(ind_value.value, ind_value.unit)
            source_map = {
                "sql": "SQL查询",
                "adapter": "适配器",
                "milvus": "Milvus检索",
                "derived": "派生计算",
            }
            source_str = source_map.get(ind_value.source, ind_value.source)

            lines.append(
                f" - {name}({ind_id}): {value_str} "
                f"(来源: {source_str}, 置信度: {ind_value.confidence:.1f})"
            )

        if context.missing_indicators:
            missing_names = []
            for mid in context.missing_indicators:
                definition = self._registry.get(mid)
                name = definition.name if definition else mid
                missing_names.append(f"{name}({mid})")
            lines.append(f" - 缺失指标: {', '.join(missing_names)}")

        quality_map = {"complete": "完整", "degraded": "降级", "missing": "缺失"}
        quality_str = quality_map.get(context.quality, context.quality)
        lines.append(f"整体置信度: {context.confidence:.2f}, 数据质量: {quality_str}")

        return "\n".join(lines)

    def generate_available_indicators(self) -> str:
        """生成所有可用指标的描述列表

        用于 LLM 了解系统能力边界，辅助意图理解和数据分析。

        示例输出:
            "当前可用指标 (共 19 个):
            维度指标:
             - insu_type: 险种类别 (城镇职工/城乡居民/超转人员/生育保险)
             - hosp_lv: 医疗机构等级 (一级医院/二级医院/三级医院)
            数值指标:
             - deductible_amount: 起付金额 (单位: 元)
             - payment_ratio: 支付比例 (单位: %)
            条件指标:
             - amount_band: 金额分段"

        Returns:
            按分类组织的指标列表
        """
        definitions = self._registry.list_all()
        if not definitions:
            return "当前无可用指标。请先运行 datamodel1_importer 导入指标定义。"

        # 按分类组织
        by_category: dict[str, list[IndicatorDefinition]] = {}
        for d in definitions:
            cat = d.category
            if cat not in by_category:
                by_category[cat] = []
            by_category[cat].append(d)

        lines: list[str] = []
        lines.append(f"当前可用指标 (共 {len(definitions)} 个):")

        category_names = {
            "dimension": "维度指标（用于过滤和路由）",
            "numeric": "数值指标（用于对标和计算）",
            "condition": "条件指标（规则适用条件）",
            "meta": "元指标（规则属性）",
        }

        for cat in ["dimension", "numeric", "condition", "meta"]:
            items = by_category.get(cat, [])
            if not items:
                continue
            cat_name = category_names.get(cat, cat)
            lines.append(f"\n{cat_name}:")

            for d in sorted(items, key=lambda x: x.indicator_id):
                unit_str = f" (单位: {d.unit})" if d.unit else ""
                tags_str = f" 标签: {', '.join(d.semantic_tags)}" if d.semantic_tags else ""
                lines.append(f" - {d.indicator_id}: {d.name}{unit_str}{tags_str}")

        return "\n".join(lines)

    def generate_policy_context(self, context: IndicatorContext) -> str:
        """生成政策检索场景的上下文描述

        用于 LLM 提示词中的政策检索前缀，帮助 LLM 理解当前
        患者的基础信息和指标取值。

        Args:
            context: 指标上下文

        Returns:
            格式化的政策上下文提示词
        """
        if not context.indicators:
            return ""

        lines: list[str] = ["【患者医保政策查询上下文】"]

        if context.patient_id:
            lines.append(f"患者ID: {context.patient_id}")

        # 提取关键维度指标
        key_dimensions = ["insu_type", "hosp_lv", "psn_type", "med_type"]
        for dim_id in key_dimensions:
            ind_value = context.indicators.get(dim_id)
            if ind_value and ind_value.value:
                definition = self._registry.get(dim_id)
                name = definition.name if definition else dim_id
                lines.append(f"{name}: {ind_value.value}")

        # 提取关键数值指标
        key_numerics = ["deductible_amount", "payment_ratio", "cap_amount"]
        for num_id in key_numerics:
            ind_value = context.indicators.get(num_id)
            if ind_value and ind_value.value is not None:
                definition = self._registry.get(num_id)
                name = definition.name if definition else num_id
                unit = ind_value.unit or (definition.unit if definition else "")
                value_str = self._format_value(ind_value.value, unit)
                lines.append(f"{name}: {value_str}")

        if context.missing_indicators:
            missing_names = []
            for mid in context.missing_indicators:
                definition = self._registry.get(mid)
                name = definition.name if definition else mid
                missing_names.append(name)
            lines.append(f"未获取到的信息: {', '.join(missing_names)}")

        return "\n".join(lines)

    # ============================================================
    # 辅助方法
    # ============================================================

    @staticmethod
    def _format_value(value: object, unit: str) -> str:
        """格式化值的显示"""
        if value is None:
            return "无"
        if isinstance(value, float):
            # 整数显示的 float 去掉小数
            if value == int(value):
                return f"{int(value)}{unit}"
            return f"{value:.2f}{unit}"
        return f"{value}{unit}"


# ============================================================
# 全局单例
# ============================================================

_generator_instance: Optional[LLMReadableGenerator] = None


def get_llm_readable_generator() -> LLMReadableGenerator:
    """获取全局 LLM 可读化生成器单例"""
    global _generator_instance
    if _generator_instance is None:
        _generator_instance = LLMReadableGenerator()
    return _generator_instance
