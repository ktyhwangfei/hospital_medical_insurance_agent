"""
医保政策问答RAG系统 - 编排器

串联6个步骤:
1. 意图识别 (LLM, 非流式)
2. SQL Server查询
3. 问题重写
4. RAG检索 (Milvus, 向量+高级搜索)
5. 费用拆分计算Skill
6. 大模型润色 (基于角色, 流式)
"""

from __future__ import annotations

import logging
from collections.abc import AsyncGenerator
from typing import Any

from src.model_service.gateway import ModelGateway
from src.runtime.policy_qa.explanation_generator import ExplanationGenerator
from src.runtime.policy_qa.fee_decomposition_skill import FeeDecompositionSkill
from src.runtime.policy_qa.intent_detector import IntentDetector
from src.runtime.policy_qa.models import (
    ExplanationContext,
    FeeDecompositionResult,
    PolicyQAIntent,
    PolicyQAIntentResult,
    PolicyQARequest,
    PolicyQAResponse,
    PolicyRule,
    RewrittenQuestion,
    SQLQueryResult,
)
from src.runtime.policy_qa.question_rewriter import QuestionRewriter
from src.runtime.policy_qa.sql_data_fetcher import SQLDataFetcher

logger = logging.getLogger(__name__)


class PolicyQAOrchestrator:
    """
    政策问答编排器

    串联6个步骤，yield SSE事件
    """

    def __init__(
        self,
        model_gateway: ModelGateway,
        sql_fetcher: SQLDataFetcher | None = None,
        question_rewriter: QuestionRewriter | None = None,
        search_engine: Any | None = None,  # MilvusPolicyRetriever
        fee_skill: FeeDecompositionSkill | None = None,
        explanation_generator: ExplanationGenerator | None = None,
    ):
        self.model_gateway = model_gateway
        self.sql_fetcher = sql_fetcher
        self.question_rewriter = question_rewriter
        self.search_engine = search_engine
        self.fee_skill = fee_skill
        self.explanation_generator = explanation_generator
        # 意图识别器（使用模型网关）
        self.intent_detector = IntentDetector(model_gateway=model_gateway)

    async def process(
        self,
        request: PolicyQARequest,
    ) -> AsyncGenerator[PolicyQAResponse, None]:
        """
        处理政策问答请求，yield SSE事件

        Args:
            request: 政策问答请求

        Yields:
            PolicyQAResponse: SSE事件
        """
        context = ExplanationContext(question=request.question)

        try:
            # Step 1: 意图识别
            yield PolicyQAResponse(step="intent", status="running")
            intent_result = await self._detect_intent(request)
            context.intent = intent_result
            yield PolicyQAResponse(
                step="intent",
                status="done",
                detail={
                    "intent": intent_result.intent.value,
                    "settlement_id": intent_result.settlement_id,
                    "confidence": intent_result.confidence,
                },
            )

            # Step 2: SQL Server查询
            yield PolicyQAResponse(step="sql_query", status="running")
            sql_result = await self._fetch_sql_data(intent_result.settlement_id)
            context.sql_result = sql_result
            yield PolicyQAResponse(
                step="sql_query",
                status="done",
                detail={
                    "tables": [
                        "yb_zyfdxx",
                        "yb_zyfymx",
                        "yb_dyxxnd",
                        "yb_dyxxzy",
                        "yb_brdjxx",
                    ]
                },
            )

            # Step 3: 问题重写（传递意图和目标费用项信息）
            yield PolicyQAResponse(step="rewrite", status="running")
            rewritten = await self._rewrite_question(
                request.question,
                sql_result,
                intent_result.intent,
                target_fee_item=intent_result.target_fee_item,
            )
            context.rewritten_question = rewritten
            yield PolicyQAResponse(
                step="rewrite",
                status="done",
                detail={
                    "rewritten_question": rewritten.rewritten,
                    "search_query": rewritten.search_query,
                    "explanation_context": rewritten.explanation_context,
                    "warnings": rewritten.warnings,
                },
            )

            # Step 4: RAG检索（传递意图信息用于定向检索）
            yield PolicyQAResponse(step="search", status="running")
            policy_rules = await self._search_policy_rules(
                rewritten.search_query or rewritten.rewritten,
                sql_result,
                intent=intent_result.intent,
                target_fee_item=intent_result.target_fee_item,
            )
            context.policy_rules = policy_rules
            yield PolicyQAResponse(
                step="search",
                status="done",
                detail={"rules_count": len(policy_rules)},
            )

            # Step 5: 费用拆分计算Skill
            yield PolicyQAResponse(step="decomposition", status="running")
            decomposition = await self._calculate_decomposition(sql_result, policy_rules)
            context.decomposition = decomposition
            yield PolicyQAResponse(
                step="decomposition",
                status="done",
                detail=self._serialize_decomposition(decomposition),
            )

            # Step 6: 大模型润色 (流式)
            yield PolicyQAResponse(step="explain", status="running")
            async for chunk in self._generate_explanation(context):
                yield PolicyQAResponse(
                    step="explain",
                    status="streaming",
                    chunk=chunk,
                )
            yield PolicyQAResponse(step="explain", status="done")

        except Exception as e:
            logger.exception("PolicyQA processing failed")
            yield PolicyQAResponse(
                step="error",
                status="error",
                error=str(e),
            )

    async def _detect_intent(self, request: PolicyQARequest) -> PolicyQAIntentResult:
        """
        意图识别

        使用LLM识别用户意图，降级到关键词匹配
        """
        try:
            result = await self.intent_detector.detect(request.question)
            # 设置settlement_id
            result.settlement_id = request.settlement_id
            return result
        except Exception as e:
            logger.warning(f"Intent detection failed, using default: {e}")
            return PolicyQAIntentResult(
                intent=PolicyQAIntent.FEE_DECOMPOSITION,
                settlement_id=request.settlement_id,
                need_patient_data=True,
                query_type="费用分解",
                confidence=0.6,
            )

    async def _fetch_sql_data(self, settlement_id: str) -> SQLQueryResult:
        """
        SQL Server数据获取

        查询所有相关表：待遇分解、费用明细、年度累计、住院信息、患者登记
        """
        if self.sql_fetcher is None:
            logger.warning("SQL fetcher not configured, returning empty result")
            return SQLQueryResult()

        try:
            # 调用SQL数据获取器查询所有表
            result = await self.sql_fetcher.fetch_all_tables(settlement_id)
            logger.info(
                f"Fetched SQL data for settlement_id={settlement_id}: "
                f"treatment={bool(result.yb_zyfdxx)}, "
                f"fees={len(result.yb_zyfymx)}, "
                f"patient={bool(result.yb_brdjxx)}"
            )
            return result
        except Exception as e:
            logger.exception(f"Failed to fetch SQL data for settlement_id={settlement_id}")
            return SQLQueryResult()

    async def _rewrite_question(
        self,
        question: str,
        sql_result: SQLQueryResult,
        intent=None,
        target_fee_item: str | None = None,
    ) -> RewrittenQuestion:
        """
        问题重写

        基于SQL结果+意图重写问题，注入患者上下文并生成精准检索查询。
        """
        print(f"\n[REWRITE] ====== 问题重写 ======", flush=True)
        print(f"[REWRITE] 原始问题: {question}", flush=True)
        print(f"[REWRITE] 意图: {intent.value if intent else 'None'}", flush=True)
        print(f"[REWRITE] SQL结果: yb_brdjxx={sql_result.yb_brdjxx}", flush=True)
        print(f"[REWRITE] SQL结果: yb_dyxxzy={sql_result.yb_dyxxzy}", flush=True)
        
        if self.question_rewriter is None:
            print(f"[REWRITE] 问题重写器未配置，返回原始问题", flush=True)
            return RewrittenQuestion(original=question, rewritten=question)

        try:
            # 调用问题重写器，基于SQL结果+意图+目标费用项重写问题
            result = await self.question_rewriter.rewrite(
                question,
                sql_result,
                intent=intent,
                target_fee_item=target_fee_item,
            )
            print(f"[REWRITE] 重写结果:", flush=True)
            print(f"[REWRITE]   original: {result.original}", flush=True)
            print(f"[REWRITE]   rewritten: {result.rewritten}", flush=True)
            print(f"[REWRITE]   semantic_mappings: {result.semantic_mappings}", flush=True)
            print(f"[REWRITE] ====== 问题重写完成 ======\n", flush=True)
            return result
        except Exception as e:
            print(f"[REWRITE] 重写失败: {e}", flush=True)
            logger.exception("Failed to rewrite question")
            return RewrittenQuestion(original=question, rewritten=question)

    async def _search_policy_rules(
        self,
        question: str,
        sql_result: SQLQueryResult,
        intent=None,
        target_fee_item: str | None = None,
    ) -> list[PolicyRule]:
        """
        RAG检索

        Milvus向量+高级搜索，使用重写后的问题进行检索
        使用SQL结果中的标准化后的insu_type、psn_type等参数进行过滤
        根据意图定向检索特定类型的规则
        """
        print(f"\n[SEARCH] ====== 政策规则检索 ======", flush=True)
        print(f"[SEARCH] 搜索问题: {question[:100]}...", flush=True)
        print(f"[SEARCH] 意图: {intent.value if intent else 'None'}", flush=True)
        
        if self.search_engine is None:
            print(f"[SEARCH] 搜索引擎未配置，返回空", flush=True)
            return []

        try:
            # 从 SQL 结果提取过滤参数（已标准化）
            insu_type = sql_result.yb_brdjxx.get("fund_type", "")
            psn_type = sql_result.yb_brdjxx.get("PER_TYPE", "")
            med_type = sql_result.yb_brdjxx.get("yllb", "")
            
            print(f"[SEARCH] 过滤参数 (已标准化):", flush=True)
            print(f"[SEARCH]   insu_type: {insu_type} (原始: {sql_result.yb_brdjxx.get('fund_type_raw', '')})", flush=True)
            print(f"[SEARCH]   psn_type: {psn_type} (原始: {sql_result.yb_brdjxx.get('PER_TYPE_raw', '')})", flush=True)
            print(f"[SEARCH]   med_type: {med_type} (原始: {sql_result.yb_brdjxx.get('yllb_raw', '')})", flush=True)

            # 调用搜索引擎
            print(f"[SEARCH] 使用 PolicyRulesSearchEngine.search()", flush=True)
            
            # 构建过滤表达式（使用标准化后的值）
            expr_parts = []
            if insu_type:
                expr_parts.append(f'insu_type == "{insu_type}"')
            if psn_type:
                # 人群标签：匹配具体类型或"全部"
                expr_parts.append(f'(psn_type == "{psn_type}" or psn_type == "全部")')
            
            # 根据目标费用项或意图添加 rule_type 过滤
            if target_fee_item == "pooling_self_pay":
                expr_parts.append(
                    '('
                    'rule_type == "统筹分段" or '
                    'rule_type == "支付比例" or '
                    'rule_type == "退休优惠" or '
                    'rule_type == "人员系数"'
                    ')'
                )
            elif intent:
                from src.runtime.policy_qa.models import PolicyQAIntent
                if intent == PolicyQAIntent.DEDUCTIBLE:
                    expr_parts.append('(rule_type == "起付线" or rule_type == "起付线标准")')
                elif intent == PolicyQAIntent.PAYMENT_RATIO:
                    expr_parts.append('(rule_type == "统筹分段" or rule_type == "支付比例")')
                elif intent == PolicyQAIntent.CAP_AMOUNT:
                    expr_parts.append('(rule_type == "封顶线" or rule_type == "最高支付限额")')
            
            expr = " and ".join(expr_parts) if expr_parts else None
            print(f"[SEARCH] 过滤表达式: {expr}", flush=True)
            
            search_results = self.search_engine.search(
                question=question,
                top_k=10,
                expr=expr,
            )
            
            # 如果过滤后没有结果，尝试放宽条件（只按 psn_type 过滤）
            if len(search_results) == 0 and insu_type:
                print(f"[SEARCH] 过滤后无结果，放宽 insu_type 过滤条件", flush=True)
                expr_parts = []
                if psn_type:
                    expr_parts.append(f'(psn_type == "{psn_type}" or psn_type == "全部")')
                expr = " and ".join(expr_parts) if expr_parts else None
                print(f"[SEARCH] 放宽后过滤表达式: {expr}", flush=True)
                
                search_results = self.search_engine.search(
                    question=question,
                    top_k=10,
                    expr=expr,
                )

            print(f"[SEARCH] 原始搜索结果: {len(search_results)} 条", flush=True)
            
            # 打印前3条搜索结果
            for i, hit in enumerate(search_results[:3]):
                if hasattr(hit, 'entity'):
                    entity = hit.entity or {}
                    score = hit.score or 0.0
                else:
                    entity = hit
                    score = entity.get("score", 0.0)
                print(f"[SEARCH]   [{i}] rule_type={entity.get('rule_type', entity.get('fact_type', ''))}, insu_type={entity.get('insu_type', '')}, psn_type={entity.get('psn_type', '')}, score={score:.4f}", flush=True)

            # 转换为 PolicyRule
            policy_rules = []
            for hit in search_results:
                # 处理 SearchHit 对象或 dict
                if hasattr(hit, 'entity'):
                    entity = hit.entity or {}
                    score = hit.score or 0.0
                else:
                    entity = hit
                    score = entity.get("score", 0.0)
                
                rule = PolicyRule(
                    rule_id=entity.get("rule_id", entity.get("fact_id", "")),
                    fact_id=entity.get("fact_id", ""),
                    policy_id=entity.get("policy_id", ""),
                    clause_id=entity.get("clause_id", ""),
                    source_text=entity.get("source_text", entity.get("evidence_text", "")),
                    insu_type=entity.get("insu_type", entity.get("insurance_type", "")),
                    med_type=entity.get("med_type", entity.get("service_type", "")),
                    hosp_lv=entity.get("hosp_lv", entity.get("hospital_level", "")),
                    psn_type=entity.get("psn_type", entity.get("population", "")),
                    payment_ratio=str(entity.get("payment_ratio", entity.get("ratio", ""))),
                    deductible_amount=str(entity.get("deductible_amount", "")),
                    cap_amount=str(entity.get("cap_amount", "")),
                    amount_band=str(entity.get("amount_band", entity.get("amount", ""))),
                    rule_type=entity.get("rule_type", entity.get("fact_type", "")),
                    rule_value=entity.get("rule_value", ""),
                    score=score,
                )
                policy_rules.append(rule)

            print(f"[SEARCH] 转换后 PolicyRule: {len(policy_rules)} 条", flush=True)
            
            # 打印转换后的规则摘要
            for i, rule in enumerate(policy_rules[:3]):
                print(f"[SEARCH]   [{i}] rule_id={rule.rule_id}, rule_type={rule.rule_type}, insu_type={rule.insu_type}, psn_type={rule.psn_type}, payment_ratio={rule.payment_ratio}", flush=True)
            
            print(f"[SEARCH] ====== 检索完成 ======\n", flush=True)
            return policy_rules

        except Exception as e:
            print(f"[SEARCH] 检索失败: {e}", flush=True)
            logger.exception("Failed to search policy rules")
            return []

    async def _calculate_decomposition(
        self,
        sql_result: SQLQueryResult,
        policy_rules: list[PolicyRule],
    ) -> FeeDecompositionResult:
        """
        费用拆分计算Skill

        待遇分解 + 费用分解 + 溯源证据
        """
        print(f"\n[DECOMPOSE] ====== 费用分解 ======", flush=True)
        print(f"[DECOMPOSE] SQL结果: yb_zyfdxx={sql_result.yb_zyfdxx}", flush=True)
        print(f"[DECOMPOSE] 政策规则数量: {len(policy_rules)}", flush=True)
        
        if self.fee_skill is None:
            print(f"[DECOMPOSE] 费用分解技能未配置，返回空", flush=True)
            return FeeDecompositionResult()

        try:
            # 调用费用分解技能
            result = self.fee_skill.decompose(
                sql_results=sql_result,
                policy_rules=policy_rules,
            )
            print(f"[DECOMPOSE] 分解结果:", flush=True)
            print(f"[DECOMPOSE]   总费用: {result.treatment.total_fee.value:,.2f}", flush=True)
            print(f"[DECOMPOSE]   医保内: {result.treatment.in_scope.value:,.2f}", flush=True)
            print(f"[DECOMPOSE]   起付线: {result.treatment.deductible.value:,.2f}", flush=True)
            print(f"[DECOMPOSE]   统筹支付: {result.treatment.pooling_payment.value:,.2f}", flush=True)
            print(f"[DECOMPOSE]   统筹自付: {result.treatment.pooling_self_pay.value:,.2f}", flush=True)
            print(f"[DECOMPOSE]   大额支付: {result.treatment.major_payment.value:,.2f}", flush=True)
            print(f"[DECOMPOSE]   大额自付: {result.treatment.major_self_pay.value:,.2f}", flush=True)
            print(f"[DECOMPOSE]   个人应负: {result.treatment.personal_liability.value:,.2f}", flush=True)
            print(f"[DECOMPOSE]   医保外: {result.treatment.out_of_scope.value:,.2f}", flush=True)
            print(f"[DECOMPOSE]   溯源证据: {len(result.evidence)} 条", flush=True)
            print(f"[DECOMPOSE] ====== 分解完成 ======\n", flush=True)
            return result

        except Exception as e:
            print(f"[DECOMPOSE] 分解失败: {e}", flush=True)
            logger.exception("Failed to calculate decomposition")
            return FeeDecompositionResult()

    async def _generate_explanation(
        self, context: ExplanationContext
    ):
        """
        解释生成

        大模型基于角色润色，流式输出
        """
        if self.explanation_generator is None:
            logger.warning("Explanation generator not configured, yielding placeholder")
            yield self._generate_placeholder_explanation(context)
            return

        try:
            # 调用解释生成器（流式）
            async for chunk in self.explanation_generator.generate(context):
                yield chunk

        except Exception as e:
            logger.exception("Explanation generation failed")
            yield f"生成解释时出错: {str(e)}"

    def _generate_placeholder_explanation(self, context: ExplanationContext) -> str:
        """
        生成占位符解释（当解释生成器不可用时）

        Args:
            context: 解释上下文

        Returns:
            占位符文本
        """
        decomposition = context.decomposition
        lines = []
        lines.append(f"您的总费用为{decomposition.treatment.total_fee.value:,.2f}元。")
        lines.append(f"其中医保内费用{decomposition.treatment.in_scope.value:,.2f}元，")
        lines.append(f"医保报销{decomposition.treatment.pooling_payment.value:,.2f}元，")
        lines.append(f"个人需要支付{decomposition.treatment.personal_liability.value:,.2f}元。")
        lines.append("")
        lines.append("具体费用构成:")
        lines.append(f"- 起付线: {decomposition.treatment.deductible.value:,.2f}元")
        lines.append(f"- 统筹支付: {decomposition.treatment.pooling_payment.value:,.2f}元")
        lines.append(f"- 统筹自付: {decomposition.treatment.pooling_self_pay.value:,.2f}元")
        lines.append(f"- 大额支付: {decomposition.treatment.major_payment.value:,.2f}元")
        lines.append(f"- 大额自付: {decomposition.treatment.major_self_pay.value:,.2f}元")
        lines.append(f"- 医保外: {decomposition.treatment.out_of_scope.value:,.2f}元")
        return "\n".join(lines)

    def _serialize_decomposition(
        self, decomposition: FeeDecompositionResult
    ) -> dict[str, Any]:
        """序列化费用分解结果为JSON"""
        return {
            "treatment": {
                "total_fee": decomposition.treatment.total_fee.value,
                "in_scope": decomposition.treatment.in_scope.value,
                "deductible": decomposition.treatment.deductible.value,
                "pooling_self_pay": decomposition.treatment.pooling_self_pay.value,
                "pooling_payment": decomposition.treatment.pooling_payment.value,
                "major_payment": decomposition.treatment.major_payment.value,
                "major_self_pay": decomposition.treatment.major_self_pay.value,
                "personal_liability": decomposition.treatment.personal_liability.value,
                "out_of_scope": decomposition.treatment.out_of_scope.value,
            },
            "fees": {
                "total_amount": decomposition.fees.total_amount,
                "in_scope_total": decomposition.fees.in_scope_total,
                "out_of_scope_total": decomposition.fees.out_of_scope_total,
                "categories": [
                    {
                        "category": cat.category,
                        "total_amount": cat.total_amount,
                        "in_scope_amount": cat.in_scope_amount,
                        "out_of_scope_amount": cat.out_of_scope_amount,
                    }
                    for cat in decomposition.fees.categories
                ],
            },
            "segments": {
                "total_pay": decomposition.segments.total_pay,
                "segments": [
                    {
                        "lower": seg.lower,
                        "upper": seg.upper,
                        "amount": seg.amount,
                        "base_ratio": seg.base_ratio,
                        "person_ratio": seg.person_ratio,
                        "actual_ratio": seg.actual_ratio,
                        "pay": seg.pay,
                        "calculation": seg.calculation,
                        "rule_id": seg.rule_id,
                        "policy_source": seg.policy_source,
                    }
                    for seg in decomposition.segments.segments
                ],
            },
            "evidence_count": len(decomposition.evidence),
        }
