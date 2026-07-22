from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any

from .business_data_client import MockBusinessDataClient
from .context_requirement import analyze_context_requirement
from .semantic_mapping import SemanticMapper
from .question_rewriter import rewrite_question

from .milvus_retriever import MilvusPolicyRetriever
from .query_understanding import understand_query
from .reranker import RuleBasedReranker
from .explanation_planner import ExplanationPlanner


@dataclass
class ContextualPolicyQAResult:
    original_question: str
    rewritten_question: str
    case_context: dict[str, Any]
    answer: str
    trace: dict[str, Any]
    warnings: list[str]


class ContextualPolicyQA:
    """
    业务上下文增强问答：
    原问题 -> 查询业务上下文 -> 语义对齐 -> 问题重写 -> 政策检索解释。
    """

    def __init__(
        self,
        *,
        business_client: MockBusinessDataClient | None = None,
        semantic_mapper: SemanticMapper | None = None,
        retriever: MilvusPolicyRetriever | None = None,
        reranker: RuleBasedReranker | None = None,
        planner: ExplanationPlanner | None = None,
        embedding_kind: str = "sentence_transformer",
        host: str = "127.0.0.1",
        port: str = "19530",
    ):
        self.business_client = business_client or MockBusinessDataClient()
        self.semantic_mapper = semantic_mapper or SemanticMapper()
        self.retriever = retriever or MilvusPolicyRetriever(
            host=host,
            port=port,
            embedding_kind=embedding_kind,
        )
        self.reranker = reranker or RuleBasedReranker()
        self.planner = planner or ExplanationPlanner()

    def answer(
        self,
        question: str,
        *,
        settlement_id: str | None = None,
        person_id: str | None = None,
        visit_id: str | None = None,
        top_k: int = 10,
    ) -> ContextualPolicyQAResult:
        requirement = analyze_context_requirement(question)

        raw_context = self.business_client.get_case_context_raw(
            settlement_id=settlement_id,
            person_id=person_id,
            visit_id=visit_id,
            question=question,
        )

        context = self.semantic_mapper.normalize_case_context(
            raw_context,
            target_object=requirement.target_object,
            target_amount=requirement.target_value,
            required_fields=requirement.required_fields,
        )

        warnings: list[str] = []

        if context.missing_fields:
            warnings.append(
                "业务上下文字段缺失: " + ", ".join(context.missing_fields)
            )

        rewritten_question = rewrite_question(question, context)

        sq = understand_query(rewritten_question)

        # 用标准化 CaseContext 强制覆盖 QueryUnderstanding 的关键字段，
        # 避免自然语言识别与业务数据不一致。
        if context.population:
            sq.population = context.population
        if context.insurance_type:
            # 当前 SearchQuery 暂未含 insurance_type，后续可加
            pass
        if context.service_type:
            sq.service_type = context.service_type
        if context.hospital_level:
            sq.hospital_level = context.hospital_level
        if context.admission_order:
            # 1950 这类解释需要 deductible + formula，不能只过滤 admission_order=>=2。
            # 因此只在非计算解释时强制 admission_order。
            if not sq.need_calculation_explanation:
                sq.admission_order = context.admission_order

        if context.target_amount is not None:
            sq.target_value = context.target_amount

        # 宽召回：不要让 retriever 内部 QueryUnderstanding 误过滤
        nodes = self.retriever.search_nodes(
            rewritten_question,
            top_k=top_k,
        )

        facts = self.retriever.search_facts(
            rewritten_question,
            top_k=top_k * 3,
            expr='derived == false',
        )

        raw_result = {
            "nodes": nodes,
            "facts": facts,
        }

        reranked_facts = self.reranker.rerank_facts(raw_result["facts"], sq)
        reranked_nodes = self.reranker.rerank_nodes(raw_result["nodes"], sq)

        evidence = self.reranker.pick_evidence(
            sq,
            reranked_facts,
            reranked_nodes,
        )

        trace = self.planner.build(evidence)

        context_prefix = self._build_context_prefix(context)

        answer = trace.final_explanation

        if context_prefix:
            answer = context_prefix + "\n\n" + answer

        return ContextualPolicyQAResult(
            original_question=question,
            rewritten_question=rewritten_question,
            case_context=asdict(context),
            answer=answer,
            trace=asdict(trace),
            warnings=warnings + evidence.warnings,
        )

    def _build_context_prefix(self, context) -> str:
        items = []

        if context.population == "adult":
            items.append("成人")
        elif context.population == "student_child":
            items.append("学生儿童")

        if context.insurance_type == "urban_rural_resident":
            items.append("城乡居民医保")
        elif context.insurance_type:
            items.append(context.insurance_type)

        if context.hospital_level:
            items.append(f"{context.hospital_level}医疗机构")

        if context.service_type == "inpatient":
            items.append("住院")
        elif context.service_type:
            items.append(context.service_type)

        if context.admission_order == "1":
            items.append("本年度首次住院")
        elif context.admission_order in ["2", ">=2"]:
            items.append("本年度第二次及以后住院")

        if not items:
            return ""

        return "根据本次结算信息：" + "，".join(items) + "。"
