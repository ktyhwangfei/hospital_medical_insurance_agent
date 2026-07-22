"""
政策检索桥接 - 将指标上下文转化为 Milvus 检索参数

职责:
1. 从指标上下文中提取维度指标的值
2. 构建 Milvus 标量过滤表达式
3. 从指标值构建嵌入文本
4. 组装结构化的搜索查询，用于 MilvusPolicyRetriever
"""
import logging
from typing import Any, Optional

from src.domain.indicator.models import IndicatorContext
from src.semantic_layer.normalizer import get_normalizer
from src.semantic_layer.registry import get_registry

logger = logging.getLogger(__name__)


class PolicyBridge:
    """
    政策检索桥接

    将语义层的指标上下文转化为 Milvus 检索所需的参数结构。
    当前支持 build_search_query 生成 Milvus 搜索参数。
    """

    def __init__(self) -> None:
        self._registry = get_registry()
        self._normalizer = get_normalizer()

    def build_search_query(
        self,
        context: IndicatorContext,
        question: str = "",
    ) -> dict[str, Any]:
        """构建 Milvus 搜索查询参数

        从指标上下文中提取维度指标用于标量过滤，
        从数值/条件指标构建嵌入文本，
        返回结构化的搜索参数字典。

        Args:
            context: 已取值并标准化的指标上下文
            question: 用户原始提问（用于向量搜索）

        Returns:
            Milvus 搜索参数字典，包含:
            - collection_name: 目标集合名
            - query_text: 嵌入查询文本
            - filter_expr: 标量过滤表达式
            - top_k: 返回条数
            - output_fields: 需返回的字段
            - dimensions_summary: 维度指标摘要（用于日志/调试）
        """
        # Step 1: 构建标量过滤表达式
        filter_expr = self._normalizer.build_milvus_filter(context)

        # Step 2: 构建嵌入查询文本
        query_text = self._build_embedding_text(context, question)

        # Step 3: 提取维度指标摘要
        dimensions_summary = self._extract_dimensions_summary(context)

        search_query: dict[str, Any] = {
            "collection_name": "policy_rules",
            "query_text": query_text,
            "top_k": 10,
            "output_fields": [
                "rule_id",
                "rule_type",
                "rule_value",
                "insu_type",
                "hosp_lv",
                "psn_type",
                "source_text",
                "policy_id",
            ],
            "dimensions_summary": dimensions_summary,
        }

        if filter_expr:
            search_query["filter_expr"] = filter_expr

        logger.debug("PolicyBridge 搜索查询: filter=%s, text=%s", filter_expr, query_text[:50])
        return search_query

    # ============================================================
    # 辅助方法
    # ============================================================

    def _build_embedding_text(self, context: IndicatorContext, question: str) -> str:
        """构建嵌入查询文本

        组合用户问题和指标上下文中的关键信息，
        用于 Milvus 向量相似度搜索。

        Args:
            context: 指标上下文
            question: 用户原始提问

        Returns:
            嵌入查询文本
        """
        parts: list[str] = []

        if question:
            parts.append(question)

        # 添加维度和数值指标作为上下文
        context_parts = []
        for ind_id, ind_value in context.indicators.items():
            definition = self._registry.get(ind_id)
            if not definition:
                continue

            # 维度指标使用嵌入模板
            if definition.use_in_embedding and definition.embedding_template:
                if ind_value.value is not None:
                    context_parts.append(
                        definition.embedding_template.format(value=ind_value.value)
                    )
            # 数值指标直接添加
            elif definition.category == "numeric" and ind_value.value is not None:
                context_parts.append(f"{definition.name}={ind_value.value}{ind_value.unit}")

        if context_parts:
            parts.append(" | ".join(context_parts))

        return " ".join(parts)

    def _extract_dimensions_summary(self, context: IndicatorContext) -> dict[str, str]:
        """提取维度指标值摘要

        用于调试日志和后续分析。

        Returns:
            {indicator_id: standard_value} 的字典
        """
        summary: dict[str, str] = {}
        for ind_id, ind_value in context.indicators.items():
            definition = self._registry.get(ind_id)
            if definition and definition.category == "dimension" and ind_value.value is not None:
                summary[ind_id] = str(ind_value.value)
        return summary


# ============================================================
# 全局单例
# ============================================================

_bridge_instance: Optional[PolicyBridge] = None


def get_policy_bridge() -> PolicyBridge:
    """获取全局政策检索桥接单例"""
    global _bridge_instance
    if _bridge_instance is None:
        _bridge_instance = PolicyBridge()
    return _bridge_instance
