"""
医保政策问答RAG系统 - 解释生成

核心目标: 把金额和政策规则关联，形成"金额→政策条文→计算过程→结论"的因果解释链。

例如：
  "统筹自付 4,962.67 元" → "根据《城镇职工医保办法》第X条，退休人员起付线以上至3万元部分
   自付比例为15%，退休人员享受60%优惠，实际自付9%" → "29,350 × 15% × 60% = 2,641.50 元"
"""

from __future__ import annotations

import logging

from src.model_service.gateway import ModelGateway
from src.model_service.governance_runtime import (
    GovernanceRuntimeError,
    render_governed_prompt,
)
from src.model_service.models import Message
from src.runtime.policy_qa.models import ExplanationContext, FeeDecompositionResult

logger = logging.getLogger(__name__)


def _safe_money(value) -> str:
    """安全格式化金额：null/空 → '未获取'。"""
    if value is None or value == '':
        return '未获取'
    try:
        return f'{float(value):,.2f}'
    except (ValueError, TypeError):
        return '未获取'


# ── 解释生成 Prompt 模板 ─────────────────────────────────────────
# 核心原则：用户问什么只答什么，不展开无关内容

EXPLANATION_PROMPTS = {
    "患者": """你是医保政策解释助手。面向患者，必须简短、通俗。

【铁律】
1. 只回答用户问题。用户只问了 X，你就只解释 X。禁止解释其他费用项。
2. 禁止介绍医保报销流程。禁止展开大额支付、医保外费用，除非它们直接导致 X 的金额变化。
3. 禁止使用"首先/其次/最后/综上所述"等长篇结构。

用户问题: {question}

费用数据（仅使用与问题相关的部分）:
{decomposition_text}

政策依据:
{policy_text}

{RAG_MISS_NOTE}

请用 3 段以内回答:
- 第1段: 一句话直接回答（"您的统筹自付是 X 元，原因如下："）
- 第2段: 简要说明关键计算（只列与问题直接相关的金额和比例，不要列全部）
- 第3段: 一句话总结 + 引用 1 条政策依据
- 如果没有政策依据，第3段改为"以上解释基于结算数据，建议咨询医保办确认"

禁止：
- 列出所有费用项
- 介绍医保报销流程
- 超出用户问题的解释""",

}


class ExplanationGenerator:
    """
    解释生成器

    核心能力: 把分段计算结果中的每一段，与对应的政策规则关联，
    形成"金额→政策条文→计算过程"的因果解释链。

    【输出契约（P2 说明）】
    - 唯一出口：orchestrator 的 answer_generation 步骤通过 `generate_answer` 获取
      单一 answer，经 PolicyQAResponse 透出。
    - 模式（mode 属性，供前端标注回答来源）：llm（真实模型）/ dummy（调试降级模板，
      基于真实结算数据）/ fallback（无网关占位）。
    - 任何模式下输出必须是自然语言文本；异常时兜底回退占位模板。
    """

    def __init__(self, model_gateway: ModelGateway | None = None):
        self.model_gateway = model_gateway
        # 解释生成模式（供前端标注回答来源）：
        # - "llm"    ：接入真实 LLM，回答由模型生成（需人工核对）
        # - "dummy"  ：调试模式（MODEL_BASE_URL=dummy），固定 mock 不可用 →
        #              统一降级为基于真实结算数据的模板解释（见 generate_answer）
        # - "fallback"：无模型网关，仅占位模板
        if model_gateway is None:
            self.mode = "fallback"
        else:
            cfg = getattr(model_gateway, "_config", None)
            base_url = getattr(cfg, "base_url", "") or ""
            self.mode = "dummy" if base_url == "dummy" else "llm"

    def _is_dummy(self) -> bool:
        """是否处于 dummy 调试模式（无真实 LLM 可用）。"""
        return self.mode == "dummy"

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
                model_type="llm",
                scene="policy_qa",
            ):
                if chunk.content:
                    yield chunk.content

        except GovernanceRuntimeError:
            raise
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

        # RAG 未命中提示
        if context.rag_miss:
            rag_miss_note = (
                "⚠️ 注意：本次检索未找到与用户问题直接匹配的政策规则。"
                "请基于结算数据（费用分解结果）进行解释，并在回答中明确告知用户"
                "「未检索到相关政策条文，以下解释基于系统已有结算数据」。"
                "不要编造政策条文。"
            )
        else:
            rag_miss_note = ""

        # 构建Prompt
        rendered = render_governed_prompt(
            "policy_qa.patient_explain",
            variables={
                "question": context.question,
                "decomposition_text": decomposition_text,
                "policy_text": policy_text,
                "RAG_MISS_NOTE": rag_miss_note,
            },
            fallback_system="",
            fallback_user=EXPLANATION_PROMPTS[user_role],
        )
        return "\n\n".join(
            filter(None, [rendered.rendered_system_prompt, rendered.rendered_user_prompt])
        )

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

        兼容 SkillPolicyRule (tool_interfaces) 和域 PolicyRule (models)，
        使用 getattr 回退链: source_text → evidence_text → title。
        """
        def _rule_text(rule) -> str:
            """安全获取规则文本，兼容 SkillPolicyRule 和域 PolicyRule"""
            return (getattr(rule, 'source_text', None)
                    or getattr(rule, 'evidence_text', '')
                    or getattr(rule, 'title', '')
                    or '')

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
                        lines.append(f"  政策条文: {_rule_text(matching_rule)}")
                lines.append("")

        # 2. 其他相关规则（起付线、封顶线等）
        other_rules = [r for r in policy_rules if getattr(r, 'rule_type', '') != "统筹分段"]
        if other_rules:
            lines.append("【其他相关政策】")
            for i, rule in enumerate(other_rules[:5], 1):
                lines.append(f"{i}. [{getattr(rule, 'rule_type', '')}] {_rule_text(rule)}")
                payment_ratio = getattr(rule, 'payment_ratio', '')
                if payment_ratio:
                    lines.append(f"   支付比例: {payment_ratio}")
                deductible = getattr(rule, 'deductible_amount', '')
                if deductible:
                    lines.append(f"   起付线: {deductible}")
                cap = getattr(rule, 'cap_amount', '')
                if cap:
                    lines.append(f"   封顶线: {cap}")
            lines.append("")

        if not lines:
            return "暂无政策依据"

        return "\n".join(lines)

    def _find_matching_rule(self, seg, policy_rules: list):
        """
        查找与分段匹配的政策规则

        兼容 SkillPolicyRule (tool_interfaces) 和域 PolicyRule (models)。
        优先 rule_id 匹配，其次 payment_ratio 匹配，最后按 rule_type 返回首条。
        """
        for rule in policy_rules:
            if getattr(rule, 'rule_type', '') == "统筹分段":
                # 尝试匹配 rule_id（仅域 PolicyRule 有此字段）
                rule_id = getattr(rule, 'rule_id', None)
                if seg.rule_id and rule_id == seg.rule_id:
                    return rule
                # 或者匹配 payment_ratio（仅域 PolicyRule 有此字段）
                payment_ratio = getattr(rule, 'payment_ratio', None)
                if payment_ratio:
                    try:
                        ratio_str = str(payment_ratio)
                        rule_ratio = float(ratio_str.replace("%", "")) / 100 if "%" in ratio_str else float(ratio_str)
                        if abs(rule_ratio - seg.base_ratio) < 0.001:
                            return rule
                    except (ValueError, TypeError):
                        continue
        # 宽松回退：返回第一条 rule_type == "统筹分段" 的规则
        for rule in policy_rules:
            if getattr(rule, 'rule_type', '') == "统筹分段":
                return rule
        return None

    def _format_policy_rules(self, policy_rules: list) -> str:
        """
        格式化政策规则（兼容旧接口）

        兼容 SkillPolicyRule 和域 PolicyRule。
        """
        if not policy_rules:
            return "暂无政策依据"

        lines = []
        for i, rule in enumerate(policy_rules[:5], 1):
            rule_text = (getattr(rule, 'source_text', None)
                         or getattr(rule, 'evidence_text', '')
                         or getattr(rule, 'title', '')
                         or '')
            lines.append(f"{i}. [{getattr(rule, 'rule_type', '')}] {rule_text}")

        return "\n".join(lines)

    def _generate_placeholder(self, context: ExplanationContext) -> str:
        """
        生成占位符解释（根据用户问题生成个性化回答）

        核心改进: 基于实际分段计算结果和政策规则生成解释，
        而不是硬编码文本。输出单一自然语言答案。
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
        lines.append(f"- 总费用：{_safe_money(decomposition.treatment.total_fee.value)} 元")
        lines.append(f"- 医保内：{_safe_money(decomposition.treatment.in_scope.value)} 元")
        lines.append(f"- 医保外：{_safe_money(decomposition.treatment.out_of_scope.value)} 元")
        lines.append("")

        # 3. 统筹自付分段解释（核心）
        if "统筹自付" in question or "自付" in question:
            lines.append(f"【统筹自付详解】")
            lines.append(f"您的统筹自付金额为 {_safe_money(decomposition.treatment.pooling_self_pay.value)} 元。")
            lines.append("")
            lines.append("这笔费用的计算依据如下：")
            lines.append("")

            # 逐段解释
            for i, seg in enumerate(decomposition.segments.segments, 1):
                lines.append(f"第{i}段：{seg.lower:,.0f}-{seg.upper:,.0f} 元")
                lines.append(f"  - 段内金额：{_safe_money(seg.amount)} 元")
                lines.append(f"  - 基础自付比例：{seg.base_ratio:.0%}")
                lines.append(f"  - 人员系数：{seg.person_ratio:.0%}")
                lines.append(f"  - 实际自付比例：{seg.actual_ratio:.0%}")
                lines.append(f"  - 该段自付：{_safe_money(seg.pay)} 元")
                lines.append(f"  - 计算：{seg.calculation}")
                if seg.policy_source:
                    lines.append(f"  - 政策依据：{seg.policy_source}")
                lines.append("")

            lines.append(f"合计：{_safe_money(decomposition.segments.total_pay)} 元")
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
            lines.append(f"您的起付线金额为 {_safe_money(decomposition.treatment.deductible.value)} 元。")
            lines.append("")
            lines.append("起付线是指医保基金开始支付前，需要个人先行承担的费用额度。")
            lines.append("")
            # 查找起付线规则
            deductible_rule = self._find_rule_by_type(policy_rules, "起付线")
            if deductible_rule:
                rule_text = (getattr(deductible_rule, 'source_text', None)
                             or getattr(deductible_rule, 'evidence_text', '')
                             or getattr(deductible_rule, 'title', '')
                             or '')
                lines.append(f"政策依据：{rule_text}")
            lines.append("")

        # 5. 报销比例解释
        elif "报销" in question or "比例" in question:
            lines.append(f"【报销比例详解】")
            lines.append(f"本次住院的医保报销情况：")
            lines.append(f"- 统筹支付：{_safe_money(decomposition.treatment.pooling_payment.value)} 元")
            lines.append(f"- 大额支付：{_safe_money(decomposition.treatment.major_payment.value)} 元")
            lines.append(f"- 合计报销：{_safe_money(decomposition.treatment.pooling_payment.value + decomposition.treatment.major_payment.value)} 元")
            lines.append("")
            lines.append("报销比例根据以下因素确定：")
            for i, seg in enumerate(decomposition.segments.segments, 1):
                lines.append(f"- 第{i}段 ({_safe_money(seg.lower)}-{_safe_money(seg.upper)}元): 基础比例 {seg.base_ratio:.0%}, 实际比例 {seg.actual_ratio:.0%}")
            lines.append("")

        # 6. 通用回答
        else:
            lines.append(f"【费用构成】")
            lines.append(f"- 总费用：{_safe_money(decomposition.treatment.total_fee.value)} 元")
            lines.append(f"- 医保内：{_safe_money(decomposition.treatment.in_scope.value)} 元")
            lines.append(f"- 医保外：{_safe_money(decomposition.treatment.out_of_scope.value)} 元")
            lines.append("")
            lines.append(f"【医保报销】")
            lines.append(f"- 统筹支付：{_safe_money(decomposition.treatment.pooling_payment.value)} 元")
            lines.append(f"- 大额支付：{_safe_money(decomposition.treatment.major_payment.value)} 元")
            lines.append("")
            lines.append(f"【个人承担】")
            lines.append(f"- 起付线：{_safe_money(decomposition.treatment.deductible.value)} 元")
            lines.append(f"- 统筹自付：{_safe_money(decomposition.treatment.pooling_self_pay.value)} 元")
            lines.append(f"- 大额自付：{_safe_money(decomposition.treatment.major_self_pay.value)} 元")
            lines.append(f"- 个人应负：{_safe_money(decomposition.treatment.personal_liability.value)} 元")
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

        explanation_context = context.rewritten_question.explanation_context or {}
        patient_context_parts = []
        if explanation_context.get("fund_type"):
            patient_context_parts.append(str(explanation_context["fund_type"]))
        if explanation_context.get("medical_type"):
            patient_context_parts.append(str(explanation_context["medical_type"]))
        if explanation_context.get("person_type"):
            patient_context_parts.append(str(explanation_context["person_type"]))
        if explanation_context.get("year"):
            patient_context_parts.append(f"{explanation_context['year']}年度")

        lines = [
            "根据本次结算业务库和已检索到的统筹分段规则，为您解释“统筹自付”金额：",
            "",
        ]
        if patient_context_parts:
            lines.extend([
                "【患者与结算上下文】",
                f"- 本次上下文：{'、'.join(patient_context_parts)}。",
                "",
            ])
        lines.extend([
            "【业务库结算金额】",
            f"- 业务库已结算的统筹自付金额为 {_safe_money(pooling_self_pay.value)} 元。",
            "- 业务库金额为本次结算的权威金额，政策解释计算值仅用于解释和复核。",
        ])
        if treatment.deductible.value is not None and treatment.deductible.value != 0:
            lines.append(
                f"- 起付线：{_safe_money(treatment.deductible.value)} 元。"
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
            lines.append(f"第{index}段：{_safe_money(segment.lower)}-{_safe_money(segment.upper)} 元")
            lines.append(f"- 段内金额：{_safe_money(segment.amount)} 元")
            lines.append(f"- 基础自付比例：{segment.base_ratio:.0%}")
            lines.append(f"- 退休人员系数：{segment.person_ratio:.0%}")
            lines.append(f"- 实际自付比例：{segment.actual_ratio:.0%}")
            lines.append(f"- 该段统筹自付：{_safe_money(segment.pay)} 元")
            if segment.calculation:
                lines.append(f"- 计算：{segment.calculation}")
            if segment.policy_source:
                lines.append(f"- 政策依据：{segment.policy_source}")
            lines.append("")

        lines.append("【政策解释计算与业务库对账】")
        lines.append(f"- 政策解释计算合计：{_safe_money(segments.total_pay)} 元")
        lines.append(f"- 业务库金额：{_safe_money(authoritative_amount)} 元")
        if segments.reconciliation_difference is not None:
            lines.append(f"- 差异：{_safe_money(segments.reconciliation_difference)} 元")
        lines.append(f"- 容差：{_safe_money(segments.reconciliation_tolerance)} 元")
        if segments.reconciliation_message:
            lines.append(f"- 对账结论：{segments.reconciliation_message}")

        return "\n".join(lines)

    def _find_rule_by_type(self, policy_rules: list, rule_type: str):
        """查找指定类型的政策规则（兼容 SkillPolicyRule 和域 PolicyRule）"""
        for rule in policy_rules:
            if getattr(rule, 'rule_type', '') == rule_type:
                return rule
        return None

    async def generate_answer(
        self,
        context: ExplanationContext,
    ) -> str:
        """生成单一政策解释答案。

        价值门控：当结算数据不足以给出可靠回答（金额缺失/为 0）时，
        不生成无价值解释，改为明确的「建议咨询医保办/当地医保局」引导回复。
        """
        # 价值门控：数据不足 → 直接引导咨询，不生成含糊回答
        if not self._has_valuable_data(context):
            return self._refusal_reply()

        def _quality_gated(candidate: str) -> str:
            """生成后质量检查：含"未获取/待定"等缺失标记 → 拒绝回答。"""
            if not candidate.strip() or self._text_has_missing_markers(candidate):
                return self._refusal_reply()
            return candidate

        if self.model_gateway is None:
            return _quality_gated(self._generate_placeholder(context))

        # ★ dummy 调试模式：model_gateway 返回固定 mock（写死金额，换结算单即错），
        # 不可作为回答。统一降级为基于真实结算数据（decomposition）的模板解释。
        if self.mode == "dummy":
            return _quality_gated(self._generate_placeholder(context))

        try:
            decomposition_text = self._format_decomposition(context.decomposition)
            policy_text = self._format_policy_rules_with_segments(
                context.decomposition, context.policy_rules
            )
            rag_miss_note = (
                "⚠️ 注意：本次检索未找到与用户问题直接匹配的政策规则。"
                "请基于结算数据进行解释，并在回答中明确告知用户"
                "「未检索到相关政策条文，以下解释基于系统已有结算数据」。"
                "不要编造政策条文。"
            ) if context.rag_miss else ""

            rendered = render_governed_prompt(
                "policy_qa.patient_explain",
                variables={
                    "question": context.question,
                    "decomposition_text": decomposition_text,
                    "policy_text": policy_text,
                    "RAG_MISS_NOTE": rag_miss_note,
                },
                fallback_system="",
                fallback_user=EXPLANATION_PROMPTS["患者"],
            )
            messages = []
            if rendered.rendered_system_prompt:
                messages.append(Message(role="system", content=rendered.rendered_system_prompt))
            messages.append(Message(role="user", content=rendered.rendered_user_prompt or ""))
            result = self.model_gateway.generate(
                messages=messages,
                model_type="llm",
                scene="policy_qa",
            )

            content = result.content.strip()
            if content.startswith("{"):
                return _quality_gated(self._generate_placeholder(context))
            return _quality_gated(content)

        except GovernanceRuntimeError:
            raise
        except Exception:
            logger.exception("Answer generation failed, falling back to placeholder")
            return _quality_gated(self._generate_placeholder(context))

    # ── 回答价值门控 ─────────────────────────────────────────────

    @staticmethod
    def _has_valuable_data(context: ExplanationContext) -> bool:
        """判断结算数据是否足以给出有价值的回答。

        判定规则：
        1. treatment 关键金额任一可用（>0）—— 无数据拒绝；
        2. 「统筹自付」类问题必须已完成分段计算（存在 pay>0 的分段）——
           否则无法解释"为什么这么多"，半成品（未获取）直接拒绝。
        """
        decomposition = context.decomposition
        if decomposition is None or decomposition.treatment is None:
            return False
        try:
            values = [
                decomposition.treatment.total_fee.value,
                decomposition.treatment.in_scope.value,
                decomposition.treatment.pooling_self_pay.value,
                decomposition.treatment.pooling_payment.value,
                decomposition.treatment.personal_liability.value,
            ]
        except AttributeError:
            return False
        if not any(isinstance(v, (int, float)) and v > 0 for v in values):
            return False

        # 统筹自付类问题：必须存在计算出的分段（pay > 0），否则拒绝
        if context.intent.target_fee_item == "pooling_self_pay":
            segments = decomposition.segments
            if segments is None or not segments.segments:
                return False
            if not any(getattr(s, "pay", 0) and s.pay > 0 for s in segments.segments):
                return False

        return True

    @staticmethod
    def _text_has_missing_markers(text: str) -> bool:
        """回答文本是否含"未获取"等缺失标记（半成品回答直接拒绝）。"""
        return "未获取" in text or "待定" in text

    @staticmethod
    def _refusal_reply() -> str:
        """数据不足/存在风险时的标准引导回复（不编造、不猜测）。"""
        return (
            "当前无法基于已有结算数据给出准确、可靠的费用解释。\n\n"
            "为避免误导，本系统不生成猜测性回答。建议您：\n"
            "- 携带医保结算单前往医院医保办（收费窗口）咨询；\n"
            "- 或拨打当地医保局服务热线 / 咨询当地医保经办机构。\n\n"
            "本回答仅供参考，不作为报销或结算依据。"
        )
