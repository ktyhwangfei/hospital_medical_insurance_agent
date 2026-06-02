"""
医保政策问答RAG系统 - 解释生成

核心目标: 把金额和政策规则关联，形成"金额→政策条文→计算过程→结论"的因果解释链。

例如：
  "统筹自付 4,962.67 元" → "根据《城镇职工医保办法》第X条，退休人员起付线以上至3万元部分
   自付比例为15%，退休人员享受60%优惠，实际自付9%" → "29,350 × 15% × 60% = 2,641.50 元"
"""

from __future__ import annotations

import logging
from collections.abc import AsyncGenerator
from typing import Any

from src.model_service.gateway import ModelGateway
from src.model_service.models import Message
from src.runtime.policy_qa.models import ExplanationContext, FeeDecompositionResult

logger = logging.getLogger(__name__)

# 解释生成Prompt模板 - 核心要求: 每个金额必须关联到具体的政策规则
EXPLANATION_PROMPTS = {
    "患者": """你是一个医保政策解释助手，需要用通俗易懂的语言向患者解释费用构成。

【核心要求】每个金额数字都必须说明"根据哪条政策规则计算得出"。

用户问题: {question}

费用分解结果:
{decomposition_text}

政策依据（每条规则对应一个金额）:
{policy_text}

请按以下结构解释:
1. 患者基本情况（险种、人员类别、医疗类别）
2. 总费用及医保报销情况
3. 个人需要支付多少
4. 【重点】为什么是这个金额——逐段说明:
   - 第一段: 金额是多少，根据哪条政策，基础比例是多少，人员优惠是多少，实际比例是多少
   - 第二段: ...（同上）
   - ...
5. 总结: 退休人员/在职人员享受的优惠政策

注意:
- 使用简单易懂的语言
- 每个数字都要引用具体的政策条文
- 说明"基础比例 × 人员系数 = 实际比例"的计算过程
- 让患者明白自己的费用构成和政策依据""",

    "收费员": """你是一个医保政策解释助手，需要向收费员详细解释费用构成。

【核心要求】每个金额数字都必须说明"根据哪条政策规则计算得出"。

用户问题: {question}

费用分解结果:
{decomposition_text}

政策依据（每条规则对应一个金额）:
{policy_text}

请按以下结构解释:
1. 患者基本情况（险种、人员类别、医疗类别）
2. 费用分解明细（甲类/乙类/丙类）
3. 待遇分解明细（统筹/大额/个人）
4. 【重点】分段计算过程——逐段说明:
   - 段范围、段内金额、基础比例、人员系数、实际比例、自付金额
   - 每段都必须引用对应的政策条文
5. 政策依据汇总
6. 便于收费员向患者解释的话术

注意:
- 使用专业术语
- 详细说明计算过程
- 每段计算都必须引用政策条文
- 提供政策依据""",

    "医生": """你是一个医保政策解释助手，需要向医生解释费用构成。

【核心要求】每个金额数字都必须说明"根据哪条政策规则计算得出"。

用户问题: {question}

费用分解结果:
{decomposition_text}

政策依据:
{policy_text}

请从医生角度解释:
1. 费用构成（哪些是医保内，哪些是医保外）
2. 分段计算明细——每段的比例和金额，以及对应的政策依据
3. 哪些项目影响了报销比例
4. 如何优化费用结构

注意:
- 关注医保内/外费用
- 分析费用结构
- 提供优化建议""",

    "医保管理员": """你是一个医保政策解释助手，需要向医保管理员详细解释费用构成。

【核心要求】每个金额数字都必须说明"根据哪条政策规则计算得出"。

用户问题: {question}

费用分解结果:
{decomposition_text}

政策依据:
{policy_text}

请从医保管理角度详细解释:
1. 费用分解明细
2. 待遇分解明细
3. 【重点】分段计算过程——逐段说明金额、比例、政策依据
4. 政策依据
5. 合规性分析

注意:
- 使用专业术语
- 详细说明计算过程
- 每段都必须引用政策条文
- 分析合规性""",
}


class ExplanationGenerator:
    """
    解释生成器

    核心能力: 把分段计算结果中的每一段，与对应的政策规则关联，
    形成"金额→政策条文→计算过程"的因果解释链。
    """

    def __init__(self, model_gateway: ModelGateway | None = None):
        self.model_gateway = model_gateway

    async def generate(
        self,
        context: ExplanationContext,
    ):
        """
        生成解释

        Args:
            context: 解释上下文

        Yields:
            解释文本块
        """
        try:
            # 如果没有模型网关，返回占位符
            if self.model_gateway is None:
                yield self._generate_placeholder(context)
                return

            # 准备Prompt
            prompt = self._build_prompt(context)

            # 调用模型（流式）- generate_stream返回同步Iterator，用普通for遍历
            messages = [Message(role="user", content=prompt)]
            for chunk in self.model_gateway.generate_stream(
                messages=messages,
                model_type="explanation_generation",
                scene="policy_qa",
            ):
                if chunk.content:
                    yield chunk.content

        except Exception as e:
            logger.exception("Explanation generation failed")
            yield f"生成解释时出错: {str(e)}"

    def _build_prompt(self, context: ExplanationContext) -> str:
        """
        构建Prompt

        核心: 把分段计算中的每一段与对应的政策规则关联，形成因果链。
        """
        # 获取用户角色
        user_role = context.user_role
        if user_role not in EXPLANATION_PROMPTS:
            user_role = "患者"

        # 准备分解文本（含政策关联）
        decomposition_text = self._format_decomposition(context.decomposition)

        # 准备政策文本（按分段组织）
        policy_text = self._format_policy_rules_with_segments(
            context.decomposition, context.policy_rules
        )

        # 构建Prompt
        prompt = EXPLANATION_PROMPTS[user_role].format(
            question=context.question,
            decomposition_text=decomposition_text,
            policy_text=policy_text,
        )

        return prompt

    def _format_decomposition(self, decomposition: FeeDecompositionResult) -> str:
        """
        格式化费用分解结果

        核心改进: 每段计算都关联到对应的政策规则。
        """
        lines = []

        # 待遇分解
        lines.append("【待遇分解】")
        lines.append(f"总费用: {decomposition.treatment.total_fee.value:,.2f}元")
        lines.append(f"医保内: {decomposition.treatment.in_scope.value:,.2f}元")
        lines.append(f"起付线: {decomposition.treatment.deductible.value:,.2f}元")
        lines.append(f"统筹支付: {decomposition.treatment.pooling_payment.value:,.2f}元")
        lines.append(f"统筹自付: {decomposition.treatment.pooling_self_pay.value:,.2f}元")
        lines.append(f"大额支付: {decomposition.treatment.major_payment.value:,.2f}元")
        lines.append(f"大额自付: {decomposition.treatment.major_self_pay.value:,.2f}元")
        lines.append(f"个人应负: {decomposition.treatment.personal_liability.value:,.2f}元")
        lines.append(f"医保外: {decomposition.treatment.out_of_scope.value:,.2f}元")
        lines.append("")

        # 分段计算（核心：每段关联政策规则）
        lines.append("【分段计算明细】")
        for i, seg in enumerate(decomposition.segments.segments, 1):
            lines.append(f"第{i}段: {seg.lower:,.0f}-{seg.upper:,.0f}元")
            lines.append(f"  段内金额: {seg.amount:,.2f}元")
            lines.append(f"  基础自付比例: {seg.base_ratio:.0%}")
            lines.append(f"  人员系数: {seg.person_ratio:.0%}")
            lines.append(f"  实际自付比例: {seg.actual_ratio:.0%}")
            lines.append(f"  该段自付: {seg.pay:,.2f}元")
            lines.append(f"  计算: {seg.calculation}")
            if seg.policy_source:
                lines.append(f"  政策依据: {seg.policy_source}")
            if seg.rule_id:
                lines.append(f"  规则ID: {seg.rule_id}")
            lines.append("")
        lines.append(f"【统筹自付合计】{decomposition.segments.total_pay:,.2f}元")
        lines.append("")

        # 费用分解
        lines.append("【费用分解】")
        for cat in decomposition.fees.categories:
            lines.append(f"{cat.category}: {cat.total_amount:,.2f}元 (医保内: {cat.in_scope_amount:,.2f}元, 医保外: {cat.out_of_scope_amount:,.2f}元)")
        lines.append("")

        return "\n".join(lines)

    def _format_policy_rules_with_segments(
        self, decomposition: FeeDecompositionResult, policy_rules: list
    ) -> str:
        """
        格式化政策规则，按分段组织

        核心: 把政策规则与分段计算关联，形成"规则→金额"的映射。
        """
        lines = []

        # 1. 分段对应规则
        if decomposition.segments.segments:
            lines.append("【分段对应政策规则】")
            for i, seg in enumerate(decomposition.segments.segments, 1):
                lines.append(f"第{i}段 ({seg.lower:,.0f}-{seg.upper:,.0f}元):")
                lines.append(f"  基础比例: {seg.base_ratio:.0%}")
                lines.append(f"  实际比例: {seg.actual_ratio:.0%} (基础比例 × 人员系数)")
                lines.append(f"  自付金额: {seg.pay:,.2f}元")
                if seg.policy_source:
                    lines.append(f"  政策条文: {seg.policy_source}")
                else:
                    # 从 policy_rules 中查找匹配的规则
                    matching_rule = self._find_matching_rule(seg, policy_rules)
                    if matching_rule:
                        lines.append(f"  政策条文: {matching_rule.source_text}")
                lines.append("")

        # 2. 其他相关规则（起付线、封顶线等）
        other_rules = [r for r in policy_rules if r.rule_type != "统筹分段"]
        if other_rules:
            lines.append("【其他相关政策】")
            for i, rule in enumerate(other_rules[:5], 1):
                lines.append(f"{i}. [{rule.rule_type}] {rule.source_text}")
                if rule.payment_ratio:
                    lines.append(f"   支付比例: {rule.payment_ratio}")
                if rule.deductible_amount:
                    lines.append(f"   起付线: {rule.deductible_amount}")
                if rule.cap_amount:
                    lines.append(f"   封顶线: {rule.cap_amount}")
            lines.append("")

        if not lines:
            return "暂无政策依据"

        return "\n".join(lines)

    def _find_matching_rule(self, seg, policy_rules: list):
        """
        查找与分段匹配的政策规则
        """
        for rule in policy_rules:
            if rule.rule_type == "统筹分段":
                # 尝试匹配 rule_id
                if seg.rule_id and rule.rule_id == seg.rule_id:
                    return rule
                # 或者匹配 payment_ratio
                try:
                    rule_ratio = float(rule.payment_ratio.replace("%", "")) / 100 if "%" in rule.payment_ratio else float(rule.payment_ratio)
                    if abs(rule_ratio - seg.base_ratio) < 0.001:
                        return rule
                except (ValueError, TypeError):
                    continue
        return None

    def _format_policy_rules(self, policy_rules: list) -> str:
        """
        格式化政策规则（兼容旧接口）
        """
        if not policy_rules:
            return "暂无政策依据"

        lines = []
        for i, rule in enumerate(policy_rules[:5], 1):
            lines.append(f"{i}. [{rule.rule_type}] {rule.source_text}")

        return "\n".join(lines)

    def _generate_placeholder(self, context: ExplanationContext) -> str:
        """
        生成占位符解释（根据用户问题生成个性化回答）

        核心改进: 基于实际分段计算结果和政策规则生成解释，
        而不是硬编码文本。
        """
        if context.intent.target_fee_item == "pooling_self_pay":
            return self._generate_pooling_self_pay_placeholder(context)

        decomposition = context.decomposition
        question = context.question
        policy_rules = context.policy_rules

        # 构建基于实际数据的解释
        lines = []

        # 1. 患者基本情况
        lines.append("根据您的医保信息和政策规则，为您解释费用构成：")
        lines.append("")

        # 2. 总览
        lines.append(f"【费用概览】")
        lines.append(f"- 总费用：{decomposition.treatment.total_fee.value:,.2f} 元")
        lines.append(f"- 医保内：{decomposition.treatment.in_scope.value:,.2f} 元")
        lines.append(f"- 医保外：{decomposition.treatment.out_of_scope.value:,.2f} 元")
        lines.append("")

        # 3. 统筹自付分段解释（核心）
        if "统筹自付" in question or "自付" in question:
            lines.append(f"【统筹自付详解】")
            lines.append(f"您的统筹自付金额为 {decomposition.treatment.pooling_self_pay.value:,.2f} 元。")
            lines.append("")
            lines.append("这笔费用的计算依据如下：")
            lines.append("")

            # 逐段解释
            for i, seg in enumerate(decomposition.segments.segments, 1):
                lines.append(f"第{i}段：{seg.lower:,.0f}-{seg.upper:,.0f} 元")
                lines.append(f"  - 段内金额：{seg.amount:,.2f} 元")
                lines.append(f"  - 基础自付比例：{seg.base_ratio:.0%}")
                lines.append(f"  - 人员系数：{seg.person_ratio:.0%}")
                lines.append(f"  - 实际自付比例：{seg.actual_ratio:.0%}")
                lines.append(f"  - 该段自付：{seg.pay:,.2f} 元")
                lines.append(f"  - 计算：{seg.calculation}")
                if seg.policy_source:
                    lines.append(f"  - 政策依据：{seg.policy_source}")
                lines.append("")

            lines.append(f"合计：{decomposition.segments.total_pay:,.2f} 元")
            lines.append("")

            # 人员优惠说明
            if decomposition.segments.segments:
                first_seg = decomposition.segments.segments[0]
                if first_seg.person_ratio < 1.0:
                    lines.append(f"【优惠政策】")
                    lines.append(f"您属于退休人员，享受基础自付比例 {first_seg.person_ratio:.0%} 的优惠，")
                    lines.append(f"即实际自付比例 = 基础比例 × {first_seg.person_ratio:.0%}。")
                    lines.append("")

        # 4. 起付线解释
        elif "起付线" in question:
            lines.append(f"【起付线详解】")
            lines.append(f"您的起付线金额为 {decomposition.treatment.deductible.value:,.2f} 元。")
            lines.append("")
            lines.append("起付线是指医保基金开始支付前，需要个人先行承担的费用额度。")
            lines.append("")
            # 查找起付线规则
            deductible_rule = self._find_rule_by_type(policy_rules, "起付线")
            if deductible_rule:
                lines.append(f"政策依据：{deductible_rule.source_text}")
            lines.append("")

        # 5. 报销比例解释
        elif "报销" in question or "比例" in question:
            lines.append(f"【报销比例详解】")
            lines.append(f"本次住院的医保报销情况：")
            lines.append(f"- 统筹支付：{decomposition.treatment.pooling_payment.value:,.2f} 元")
            lines.append(f"- 大额支付：{decomposition.treatment.major_payment.value:,.2f} 元")
            lines.append(f"- 合计报销：{decomposition.treatment.pooling_payment.value + decomposition.treatment.major_payment.value:,.2f} 元")
            lines.append("")
            lines.append("报销比例根据以下因素确定：")
            for i, seg in enumerate(decomposition.segments.segments, 1):
                lines.append(f"- 第{i}段 ({seg.lower:,.0f}-{seg.upper:,.0f}元): 基础比例 {seg.base_ratio:.0%}, 实际比例 {seg.actual_ratio:.0%}")
            lines.append("")

        # 6. 通用回答
        else:
            lines.append(f"【费用构成】")
            lines.append(f"- 总费用：{decomposition.treatment.total_fee.value:,.2f} 元")
            lines.append(f"- 医保内：{decomposition.treatment.in_scope.value:,.2f} 元")
            lines.append(f"- 医保外：{decomposition.treatment.out_of_scope.value:,.2f} 元")
            lines.append("")
            lines.append(f"【医保报销】")
            lines.append(f"- 统筹支付：{decomposition.treatment.pooling_payment.value:,.2f} 元")
            lines.append(f"- 大额支付：{decomposition.treatment.major_payment.value:,.2f} 元")
            lines.append("")
            lines.append(f"【个人承担】")
            lines.append(f"- 起付线：{decomposition.treatment.deductible.value:,.2f} 元")
            lines.append(f"- 统筹自付：{decomposition.treatment.pooling_self_pay.value:,.2f} 元")
            lines.append(f"- 大额自付：{decomposition.treatment.major_self_pay.value:,.2f} 元")
            lines.append(f"- 个人应负：{decomposition.treatment.personal_liability.value:,.2f} 元")
            lines.append("")

        lines.append("如果您对这笔费用有疑问，建议咨询医院医保办或当地医保局。")
        return "\n".join(lines)

    def _generate_pooling_self_pay_placeholder(self, context: ExplanationContext) -> str:
        """基于结构化事实生成统筹自付确定性解释。"""
        decomposition = context.decomposition
        treatment = decomposition.treatment
        segments = decomposition.segments
        pooling_self_pay = treatment.pooling_self_pay
        authoritative_amount = (
            segments.authoritative_amount
            if segments.authoritative_amount is not None
            else pooling_self_pay.value
        )

        lines = [
            "根据本次结算业务库和已检索到的统筹分段规则，为您解释“统筹自付”金额：",
            "",
            "【业务库结算金额】",
            f"- 业务库已结算的统筹自付金额为 {pooling_self_pay.value:,.2f} 元。",
        ]
        if pooling_self_pay.source:
            lines.append(f"- 金额来源：{pooling_self_pay.source}")
        if treatment.deductible.source:
            lines.append(
                f"- 起付线：{treatment.deductible.value:,.2f} 元，来源：{treatment.deductible.source}"
            )
        lines.append("")

        if segments.warnings:
            lines.append("【数据口径提示】")
            for warning in segments.warnings:
                lines.append(f"- {warning}")
            lines.append("")

        if not segments.segments:
            lines.append("【统筹分段计算】")
            lines.append("未检索到完整的统筹分段政策规则，无法稳定解释计算过程。")
            lines.append("不确定性：缺少统筹分段比例政策依据。")
            return "\n".join(lines)

        lines.append("【统筹分段计算】")
        for index, segment in enumerate(segments.segments, 1):
            lines.append(f"第{index}段：{segment.lower:,.0f}-{segment.upper:,.0f} 元")
            lines.append(f"- 段内金额：{segment.amount:,.2f} 元")
            lines.append(f"- 基础自付比例：{segment.base_ratio:.0%}")
            lines.append(f"- 退休人员系数：{segment.person_ratio:.0%}")
            lines.append(f"- 实际自付比例：{segment.actual_ratio:.0%}")
            lines.append(f"- 该段统筹自付：{segment.pay:,.2f} 元")
            if segment.calculation:
                lines.append(f"- 计算：{segment.calculation}")
            if segment.policy_source:
                lines.append(f"- 政策依据：{segment.policy_source}")
            lines.append("")

        lines.append("【政策解释计算与业务库对账】")
        lines.append(f"- 政策解释计算合计：{segments.total_pay:,.2f} 元")
        lines.append(f"- 业务库金额：{authoritative_amount:,.2f} 元")
        if segments.reconciliation_difference is not None:
            lines.append(f"- 差异：{segments.reconciliation_difference:,.2f} 元")
        lines.append(f"- 容差：{segments.reconciliation_tolerance:,.2f} 元")
        if segments.reconciliation_message:
            lines.append(f"- 对账结论：{segments.reconciliation_message}")

        return "\n".join(lines)

    def _find_rule_by_type(self, policy_rules: list, rule_type: str):
        """查找指定类型的政策规则"""
        for rule in policy_rules:
            if rule.rule_type == rule_type:
                return rule
        return None
