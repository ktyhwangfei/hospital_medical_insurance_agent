"""
意图→指标解析器 - 根据意图和实体返回需要的指标 ID 列表

职责:
1. resolve_for_intent(): 根据意图名称和实体确定需要的指标
2. resolve_dependencies(): 追加指标的依赖项（派生指标依赖的基础指标）

当前实现基于硬编码的意图→指标映射，后续可从 skill 注册表动态发现。
"""
import logging
from typing import Optional

from src.semantic_layer.registry import get_registry

logger = logging.getLogger(__name__)


class IndicatorResolver:
    """
    指标解析器

    将用户意图和实体列表解析为指标需求列表。
    当前支持 policy_explanation（费用解释）场景，后续扩展。
    """

    # 意图 → 所需指标 ID 列表的映射
    # 每个意图对应一组核心业务指标
    INTENT_INDICATOR_MAP: dict[str, list[str]] = {
        "policy_explanation": [
            "deductible_amount",   # 起付金额
            "in_scope_total",      # 医保内总费用
            "pooling_self_pay",    # 统筹自付
        ],
        "settlement_anomaly": [
            "error_code",          # 错误码
            "settlement_status",   # 结算状态
            "insurance_type",      # 险种类别
        ],
        "discharge_quality_control": [
            "diagnosis_code",      # 诊断编码
            "surgery_code",        # 手术编码
            "drg_code",            # DRG 编码
        ],
    }

    # 实体关键词 → 指标 ID 的映射（实体可能是指标别名或业务术语）
    ENTITY_INDICATOR_MAP: dict[str, str] = {
        "统筹自付": "pooling_self_pay",
        "自付": "pooling_self_pay",
        "起付线": "deductible_amount",
        "起付金额": "deductible_amount",
        "门槛费": "deductible_amount",
        "封顶线": "cap_amount",
        "封顶金额": "cap_amount",
        "报销比例": "payment_ratio",
        "支付比例": "payment_ratio",
        "医保内": "in_scope_total",
        "医保内总费用": "in_scope_total",
        "险种类别": "insu_type",
        "医保类型": "insu_type",
        "医院等级": "hosp_lv",
        "人群": "psn_type",
        "结算方式": "setl_type",
    }

    def resolve_for_intent(
        self,
        intent_name: str,
        entities: Optional[list[str]] = None,
    ) -> list[str]:
        """根据意图名称和实体列表解析所需指标

        策略:
        1. 从 INTENT_INDICATOR_MAP 获取意图对应的核心指标
        2. 从实体列表中匹配 ENTITY_INDICATOR_MAP，追加额外的指标
        3. 去重后返回

        Args:
            intent_name: 意图名称（如 "policy_explanation"）
            entities: 实体列表（如 ["统筹自付", "城镇职工"]）

        Returns:
            指标 ID 列表
        """
        # Step 1: 从意图映射获取核心指标
        indicator_ids: list[str] = []
        if intent_name in self.INTENT_INDICATOR_MAP:
            indicator_ids.extend(self.INTENT_INDICATOR_MAP[intent_name])

        # Step 2: 从实体列表匹配额外指标
        if entities:
            for entity in entities:
                if entity in self.ENTITY_INDICATOR_MAP:
                    extra_id = self.ENTITY_INDICATOR_MAP[entity]
                    if extra_id not in indicator_ids:
                        indicator_ids.append(extra_id)

        # Step 3: 如果意图未知，尝试从注册表按关键词搜索
        if not indicator_ids and intent_name:
            registry = get_registry()
            # 使用意图名搜索指标
            matched = registry.search_by_keyword(intent_name)
            indicator_ids = [d.indicator_id for d in matched]

        logger.debug(
            "意图 '%s' 解析为 %d 个指标: %s",
            intent_name,
            len(indicator_ids),
            indicator_ids,
        )
        return indicator_ids

    def resolve_dependencies(self, indicator_ids: list[str]) -> list[str]:
        """解析指标的依赖关系

        对于每个指标，检查其 depends_on 字段并追加其依赖项。
        例如 pooling_self_pay 依赖 in_scope_total 和 deductible_amount。

        Args:
            indicator_ids: 原始指标 ID 列表

        Returns:
            展开依赖后的完整指标 ID 列表（已去重、保持顺序）
        """
        registry = get_registry()
        result: list[str] = []
        seen: set[str] = set()

        def _add_with_deps(ind_id: str) -> None:
            """递归添加指标及其依赖"""
            if ind_id in seen:
                return
            seen.add(ind_id)

            # 先添加依赖项
            definition = registry.get(ind_id)
            if definition and definition.depends_on:
                for dep_id in definition.depends_on:
                    _add_with_deps(dep_id)

            result.append(ind_id)

        for ind_id in indicator_ids:
            _add_with_deps(ind_id)

        logger.debug("依赖解析后: %s → %s", indicator_ids, result)
        return result


# ============================================================
# 全局单例
# ============================================================

_resolver_instance: Optional[IndicatorResolver] = None


def get_resolver() -> IndicatorResolver:
    """获取全局指标解析器单例"""
    global _resolver_instance
    if _resolver_instance is None:
        _resolver_instance = IndicatorResolver()
    return _resolver_instance
