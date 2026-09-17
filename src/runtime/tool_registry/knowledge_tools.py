"""知识类 Tool 登记：包装 policy_qa 既有知识检索能力。

三类知识 Tool：向量政策检索（structured_policy_retriever）、结构化可信问题匹配
（QuestionLibraryService）、综合检索（先结构化后向量的两级融合）。
真实逻辑均在 src/runtime/policy_qa/knowledge_lookup.py，本层只做登记与薄包装。
"""

from __future__ import annotations

from src.domain.tool.models import (
    ToolContractKind,
    ToolDefinition,
    ToolRiskLevel,
    ToolStatus,
    ToolVersion,
)
from src.runtime.policy_qa.knowledge_lookup import (
    comprehensive_knowledge_lookup,
    match_trusted_question,
    retrieve_policy_evidence_for_fact,
)
from src.runtime.tool_registry.service import ToolRegistryService

TOOL_RETRIEVE_POLICY_EVIDENCE = "tool_retrieve_policy_evidence"
TOOL_MATCH_TRUSTED_QUESTION = "tool_match_trusted_question"
TOOL_COMPREHENSIVE_KNOWLEDGE_LOOKUP = "tool_comprehensive_knowledge_lookup"


def register_knowledge_tools(registry: ToolRegistryService) -> None:
    registry.register(
        ToolVersion(
            version_id="tv_retrieve_policy_evidence_2",
            tool_id=TOOL_RETRIEVE_POLICY_EVIDENCE,
            semantic_version="1.1.0",
            definition=ToolDefinition(
                tool_id=TOOL_RETRIEVE_POLICY_EVIDENCE,
                name="检索政策证据（向量）",
                description="按结算事实适用性维度返回带引用的政策证据（Milvus 结构化检索）",
                contract_kind=ToolContractKind.FUNCTION,
                target_ref="src.runtime.policy_qa.knowledge_lookup.retrieve_policy_evidence_for_fact",
                risk_level=ToolRiskLevel.LOW,
                tags=["知识类", "向量检索"],
                input_schema={
                    "settlement_fact": {
                        "type": "object",
                        "required": True,
                        "description": "结算事实（上游 tool_get_settlement_fact 输出），取适用性维度检索政策",
                    },
                },
                output_schema={
                    "policy_status": {"type": "string", "description": "政策命中状态（full/partial/no_policy_matched）"},
                    "evidence": {"type": "array<object>", "description": "政策证据列表（rule_id/原文/支付比例/金额分段/适用理由/有效期）"},
                    "evidence_count": {"type": "integer", "description": "证据条数"},
                    "missing_required_rules": {"type": "array<string>", "description": "缺失的必需规则类型，供证据不足判定"},
                },
                execution_detail=(
                    "Milvus 标量查询（非向量召回），集合为发布产物 policy_rules_*（dynamic field 开启）：\n"
                    "  client.query(collection, filter=<expr>, output_fields=[rule_id/source_text/payment_ratio/...], limit=top_k)\n"
                    "expr 模板（按结算事实适用性维度拼装）：\n"
                    "  insu_type like \"%<险种>%\" and (med_type == \"<医疗类别>\" or med_type == \"\")\n"
                    "  and (hosp_lv == \"<医院等级>\" or hosp_lv == \"\")\n"
                    "  and effective_date <= \"<结算日期>\" and (expiry_date == \"9999-12-31\" or expiry_date >= \"<结算日期>\")\n"
                    "  and ((amount_band_min == 0 and amount_band_max == 0) or (amount_band_min <= <总金额> and (amount_band_max >= <总金额> or amount_band_max == -1)))\n"
                    "字段不在集合 schema 时跳过该过滤片段（旧集合兼容）；带关键词过滤时候选池 max(top_k, 200) 先取足再过滤。"
                ),
            ),
            status=ToolStatus.MATERIALIZED,
        ),
        implementation=retrieve_policy_evidence_for_fact,
    )

    registry.register(
        ToolVersion(
            version_id="tv_match_trusted_question_2",
            tool_id=TOOL_MATCH_TRUSTED_QUESTION,
            semantic_version="1.1.0",
            definition=ToolDefinition(
                tool_id=TOOL_MATCH_TRUSTED_QUESTION,
                name="匹配可信问题（结构化）",
                description="可信问题库归一化精确命中返回标准问题，否则返回澄清候选（不确定不执行）",
                contract_kind=ToolContractKind.FUNCTION,
                target_ref="src.runtime.policy_qa.knowledge_lookup.match_trusted_question",
                risk_level=ToolRiskLevel.LOW,
                tags=["知识类", "结构化匹配"],
                input_schema={
                    "question": {
                        "type": "string",
                        "required": True,
                        "description": "用户自然语言问题（归一化后与可信问题库精确匹配）",
                    },
                },
                output_schema={
                    "kind": {"type": "string", "description": "匹配结果类型（hit=命中 / clarify=需澄清）"},
                    "question_id": {"type": "string|null", "description": "命中的可信问题 ID，未命中为 null"},
                    "standard_question": {"type": "string|null", "description": "标准问题文本，未命中为 null"},
                    "candidates": {"type": "array<object>", "description": "澄清候选列表（question_id/标准问题/得分/匹配文本）"},
                },
                execution_detail=(
                    "归一化精确匹配（Python 内存匹配，非 SQL LIKE）：\n"
                    "  normalize(text) = NFKC 折叠（全角→半角）+ 转小写 + 去标点空白（[\\W_]+）\n"
                    "  命中集合 = { normalize(q.standard_question), normalize(同义表达)... | q 为 published 状态 }\n"
                    "  normalize(用户问题) ∈ 命中集合 → hit；否则按同义文本相似度召回 candidates 降序 → clarify\n"
                    "存储：PostgreSQL question_library（trusted_questions 表，含 synonyms）；不确定不执行是硬约束。"
                ),
            ),
            status=ToolStatus.MATERIALIZED,
        ),
        implementation=match_trusted_question,
    )

    registry.register(
        ToolVersion(
            version_id="tv_comprehensive_knowledge_lookup_2",
            tool_id=TOOL_COMPREHENSIVE_KNOWLEDGE_LOOKUP,
            semantic_version="1.1.0",
            definition=ToolDefinition(
                tool_id=TOOL_COMPREHENSIVE_KNOWLEDGE_LOOKUP,
                name="综合知识检索",
                description="先可信问题库结构化命中、未命中降级向量政策证据，并附澄清候选（两级融合）",
                contract_kind=ToolContractKind.FUNCTION,
                target_ref="src.runtime.policy_qa.knowledge_lookup.comprehensive_knowledge_lookup",
                risk_level=ToolRiskLevel.LOW,
                tags=["知识类", "综合检索"],
                input_schema={
                    "question": {
                        "type": "string",
                        "required": True,
                        "description": "用户自然语言问题，先结构化命中后向量降级",
                    },
                    "settlement_fact": {
                        "type": "object",
                        "required": False,
                        "description": "结算事实，向量降级检索时提供适用性维度（命中可信问题时可缺）",
                    },
                },
                output_schema={
                    "lookup_kind": {"type": "string", "description": "命中路径（structured_hit=可信问题库 / vector_evidence=向量证据）"},
                    "answer_source": {"type": "string", "description": "答案来源（trusted_question_library / structured_policy_retriever）"},
                    "question_id": {"type": "string|null", "description": "命中的可信问题 ID，非结构化命中为 null"},
                    "standard_question": {"type": "string|null", "description": "标准问题文本，非结构化命中为 null"},
                    "evidence": {"type": "array<object>", "description": "向量检索的政策证据列表（结构化命中时为空）"},
                    "evidence_count": {"type": "integer", "description": "证据条数"},
                    "policy_status": {"type": "string", "description": "政策命中状态（仅向量降级时返回）"},
                    "clarify_candidates": {"type": "array<object>", "description": "澄清候选列表，供上层追问"},
                },
                execution_detail=(
                    "两级融合编排（优先级硬约束：确定性优先于向量）：\n"
                    "  1) tool_match_trusted_question：归一化精确匹配（见其执行细节），命中即返回 structured_hit；\n"
                    "  2) 未命中 → tool_retrieve_policy_evidence：Milvus 标量 expr 检索（见其执行细节），\n"
                    "     同时把第 1 级的澄清候选一并返回供上层追问（answer_source=structured_policy_retriever）。"
                ),
            ),
            status=ToolStatus.MATERIALIZED,
        ),
        implementation=comprehensive_knowledge_lookup,
    )
