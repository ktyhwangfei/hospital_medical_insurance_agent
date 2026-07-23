"""
policy-fee-explanation 装配器（轻量调度器）。

不包含解释逻辑。根据 target_fee_item 选择对应 Strategy，委托执行。
所有解释逻辑由 strategies/ 下各 Strategy 负责。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .strategies.registry import get_strategy
from .strategies.semantic_utils import make_llm_readable


@dataclass
class SkillResult:
    """技能执行的标准输出结果。"""
    patient_answer: str
    office_answer: str
    calculation_trace: dict
    ratio_explanation: dict = None
    explanation_completeness: dict = None
    warnings: list[str] = None
    definition: dict = None
    policy_status: str = "no_policy_matched"
    policy_status_message: str = ""
    target_fee_item: str = "pooling_self_pay"
    target_field: str = "basic_pooling_self_pay"
    llm_readable_context: str = ""

    def __post_init__(self):
        if self.ratio_explanation is None:
            self.ratio_explanation = {}
        if self.explanation_completeness is None:
            self.explanation_completeness = {}
        if self.warnings is None:
            self.warnings = []
        if self.definition is None:
            self.definition = {}


class BenefitPoolingSelfPayAssembler:
    """
    医保费用解释装配器（调度器）。

    不包含解释逻辑。根据 target_fee_item 选择对应 Strategy 执行。
    新增费用项时只需：
    1. 创建 strategies/<fee_item>/ 目录 + strategy.py + YAML 配置
    2. 在 strategies/registry.py 注册
    3. 无需修改本文件
    """

    SKILL_DIR = Path(__file__).parent

    _FEE_ITEM_MAP = {
        "pooling_self_pay": {"label": "统筹自付", "field": "basic_pooling_self_pay", "amount_field": "basic_pooling_self_pay"},
        "deductible": {"label": "起付线", "field": "deductible", "amount_field": "deductible"},
        "large_amount_self_pay": {"label": "大额自付", "field": "large_amount_self_pay", "amount_field": "large_amount_self_pay"},
        "pooling_payment": {"label": "统筹支付", "field": "basic_pooling_payment", "amount_field": "basic_pooling_payment"},
        "personal_total_pay": {"label": "个人总支付", "field": "personal_total_pay", "amount_field": "personal_total_pay"},
    }

    @classmethod
    def _get_fee_label(cls, target_fee_item: str) -> str:
        return cls._FEE_ITEM_MAP.get(target_fee_item, {}).get("label", "统筹自付")

    @classmethod
    def _get_fee_field(cls, target_fee_item: str) -> str:
        return cls._FEE_ITEM_MAP.get(target_fee_item, {}).get("field", "basic_pooling_self_pay")

    @classmethod
    def _get_fee_amount(cls, ctx: Any, target_fee_item: str) -> float:
        field = cls._get_fee_field(target_fee_item)
        return getattr(ctx, field, 0) or 0

    def build_policy_queries(self, target_fee_item: str = "pooling_self_pay") -> list[Any]:
        """根据费用项返回对应的结构化政策查询计划。"""
        strategy = get_strategy(target_fee_item)
        return strategy.build_policy_queries()

    def execute(
        self,
        settlement_context: Any,
        policy_evidence: list[dict] | None = None,
        policy_status: str = "no_policy_matched",
        target_fee_item: str = "pooling_self_pay",
    ) -> SkillResult:
        """
        主入口（兼容旧接口）：从 settlement_context 解释费用。

        Args:
            settlement_context: 结算上下文对象（属性式访问）
            policy_evidence: 政策检索证据列表
            policy_status: 政策匹配状态
            target_fee_item: 目标费用项 (pooling_self_pay/deductible/...)

        Returns:
            SkillResult 标准化输出
        """
        evidence = policy_evidence or []
        strategy = get_strategy(target_fee_item)

        # 仅向后兼容模式，不传入 IndicatorContext
        result = strategy.execute(settlement_context, evidence, policy_status)

        skill_result = self._build_result(result, evidence, policy_status, target_fee_item)
        # A-轻：版本准入守卫 —— 校验 skill 声明的指标均来自已发布版本（阶段3锁定对skill生效）
        dep_warnings = self._verify_skill_dependencies()
        if dep_warnings:
            skill_result.warnings.extend(dep_warnings)
        return skill_result

    def _verify_skill_dependencies(self) -> list[str]:
        """校验 skill 声明的指标都在已发布版本中。

        数据源（settlement_data_provider 的 SQL）不经语义层，此处为版本准入守卫：
        遍历 _FACT_FIELD_MAP 声明的语义层编码，确认对应对象已发布且指标在最新已发布
        版本快照中。缺失/未发布时返回警告列表（空=全部通过）。

        默认仅警告不拒绝；后续可经 STRICT_SKILL_LOCKING 升级为硬拒绝。
        """
        from collections import defaultdict
        try:
            from src.semantic_layer.registry import get_semantic_registry
            reg = get_semantic_registry()
        except Exception:
            return []  # 语义层不可用时跳过校验，不阻断 skill

        by_obj: dict[str, list[str]] = defaultdict(list)
        for code in self._FACT_FIELD_MAP:
            obj, _, _ = code.partition(".")
            by_obj[obj].append(code)
        warnings: list[str] = []
        for obj_code, codes in by_obj.items():
            versions = reg.list_object_versions(obj_code)
            if not versions:
                warnings.append(f"[版本守卫] 对象 {obj_code} 未发布，指标未经版本控制")
                continue
            latest = versions[-1]
            published = {m.metric_code for m in latest.metrics}
            for code in codes:
                if code not in published:
                    warnings.append(
                        f"[版本守卫] {code} 不在已发布版本 {obj_code}@{latest.version}")
        return warnings

    def execute_with_context(
        self,
        indicator_context: Any,
        target_fee_item: str = "pooling_self_pay",
        policy_evidence: list[dict] | None = None,
        policy_status: str = "no_policy_matched",
        settlement_context: Any = None,
    ) -> SkillResult:
        """
        语义层增强入口：接受 IndicatorContext 并执行费用解释。

        优先从 indicator_context 提取所有维度和费用信息。
        settlement_context 作为可选兜底（当 indicator_context 未覆盖某些字段时）。

        Args:
            indicator_context: 来自语义层的 IndicatorContext 实例
            target_fee_item: 目标费用项
            policy_evidence: 可选的政策检索证据（从未检索则拼接空列表）
            policy_status: 政策匹配状态
            settlement_context: 可选兜底（兼容未覆盖字段）

        Returns:
            SkillResult 标准化输出
        """
        evidence = policy_evidence or []
        strategy = get_strategy(target_fee_item)

        # 标准化上下文中的维度值
        normalized_ctx = self._normalize_context(indicator_context)

        # 使用 settlement_context 作为兜底（如果提供）
        fallback_ctx = settlement_context or normalized_ctx

        # 传入 indicator_context 让 Strategy 使用语义层增强
        result = strategy.execute(
            fallback_ctx,
            evidence,
            policy_status,
            indicator_context=normalized_ctx,
        )

        return self._build_result(result, evidence, policy_status, target_fee_item)

    @staticmethod
    def _normalize_context(context: Any) -> Any:
        """标准化指标上下文的维度值

        使用 SemanticNormalizer 对所有指标执行字段映射和值标准化，
        确保原始代码值（如 '310'）被转换为标准显示值（如 '城镇职工基本医疗保险'）。

        Args:
            context: 原始的 IndicatorContext（值可能未标准化）

        Returns:
            标准化后的 IndicatorContext，或原样返回（如果不是 IndicatorContext）
        """
        from src.domain.indicator.models import IndicatorContext
        from src.semantic_layer.normalizer import get_normalizer

        if not isinstance(context, IndicatorContext):
            return context

        normalizer = get_normalizer()
        return normalizer.normalize_context(context)

    @staticmethod
    def _build_result(
        result: Any,
        evidence: list[dict],
        policy_status: str,
        target_fee_item: str,
    ) -> SkillResult:
        """将 StrategyResult 包装为 SkillResult"""
        status_messages = {
            "full_policy_matched": "已匹配完整政策依据。",
            "partial_policy_matched": "仅匹配部分政策依据，解释可能不完整。",
            "no_policy_matched": "未匹配政策依据，仅展示真实结算字段，不能作为完整政策解释。",
        }

        return SkillResult(
            patient_answer=result.patient_answer,
            office_answer=result.office_answer,
            calculation_trace=result.calculation_trace,
            definition=result.definition,
            explanation_completeness=result.completeness,
            warnings=result.warnings,
            policy_status=policy_status,
            policy_status_message=status_messages.get(policy_status, ""),
            target_fee_item=target_fee_item,
            target_field=result.target_field,
        )


    def execute_via_registry(self, business_facts: dict, question: str,
                             target_fee_item: str | None = None, **kwargs):
        """
        Execute skill using pre-built Business Facts from Semantic Registry.

        This is the new execution path (A-重) — Skill receives standardized facts
        built by BusinessFactsBuilder (经已发布版本锁定)，instead of calling MCPs
        directly for data retrieval.

        Args:
            business_facts: Standardized BusinessFactsResponse.facts dict
            question: User's natural language question
            target_fee_item: 目标费用项（调用方已检测时传入，否则按 question 推断）
            **kwargs: Additional context (policy_evidence, policy_status)
        """
        ctx = self._build_context_from_facts(business_facts)
        tfi = target_fee_item or self._detect_target_from_question(question)
        return self.execute(settlement_context=ctx, target_fee_item=tfi, **kwargs)

    @staticmethod
    def _detect_target_from_question(question: str) -> str:
        """Quick heuristic to map a user question to a target fee item."""
        q = question.lower()
        if any(kw in q for kw in ("起付线", "门槛费", " deductible", "deductible")):
            return "deductible"
        if any(kw in q for kw in ("大额", "large")):
            return "large_amount_self_pay"
        if any(kw in q for kw in ("统筹支付", "pooling_payment")):
            return "pooling_payment"
        if any(kw in q for kw in ("总支付", "total", "personal")):
            return "personal_total_pay"
        # default: 统筹自付
        return "pooling_self_pay"

    # 语义层 metric_code → skill 内部语义名映射。
    # facts 由 Builder 生成，结构为 {object_code: {metric_short_name: value}}，
    # metric key 为 metric_code 去掉对象前缀的短名。此映射把语义层编码转译为
    # calculator / fact_builder 使用的内部语义名字段（skill 内部实现细节）。
    _FACT_FIELD_MAP: dict[str, str] = {
        "zydyxx.bcqfje": "deductible",
        "zydyxx.bcybnje": "medical_insurance_inner_amount",
        "zyfdxx.bdtczfje": "basic_pooling_payment",
        "zyfdxx.bdtczf": "basic_pooling_self_pay",
        "zyfdxx.bddezfje": "large_amount_payment",
        "zyfdxx.bddezf": "large_amount_self_pay",
        "zyfdxx.bdgryf": "personal_total_pay",
        "zyjyxx.rylb": "person_type",
        "djxx.fund_type": "insurance_type",
        "djxx.yllb": "service_type",
        "djxx.hospital_level": "hospital_level",
    }

    def _build_context_from_facts(self, facts: dict) -> dict:
        """从语义层 Business Facts 构建 skill 内部上下文（语义名字段）。

        facts 结构：{object_code: {metric_short_name: value}}（由 Builder 生成）。
        返回 {内部语义名: value}，供 calculator / fact_builder 消费。
        """
        ctx: dict[str, Any] = {}
        for metric_code, internal_field in self._FACT_FIELD_MAP.items():
            obj_code, _, short = metric_code.partition(".")
            obj_facts = facts.get(obj_code, {})
            ctx[internal_field] = obj_facts.get(short)
        # hospital_level：语义层暂无对应指标（gap），保留占位
        ctx["hospital_level"] = None
        return ctx


# ── 动态加载入口 ────────────────────────────────────────────────

def load() -> BenefitPoolingSelfPayAssembler:
    """SkillLoader 入口。"""
    return BenefitPoolingSelfPayAssembler()
