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
            version_id="tv_retrieve_policy_evidence_1",
            tool_id=TOOL_RETRIEVE_POLICY_EVIDENCE,
            semantic_version="1.0.0",
            definition=ToolDefinition(
                tool_id=TOOL_RETRIEVE_POLICY_EVIDENCE,
                name="检索政策证据（向量）",
                description="按结算事实适用性维度返回带引用的政策证据（Milvus 结构化检索）",
                contract_kind=ToolContractKind.FUNCTION,
                target_ref="src.runtime.policy_qa.knowledge_lookup.retrieve_policy_evidence_for_fact",
                risk_level=ToolRiskLevel.LOW,
                tags=["知识类", "向量检索"],
            ),
            status=ToolStatus.MATERIALIZED,
        ),
        implementation=retrieve_policy_evidence_for_fact,
    )

    registry.register(
        ToolVersion(
            version_id="tv_match_trusted_question_1",
            tool_id=TOOL_MATCH_TRUSTED_QUESTION,
            semantic_version="1.0.0",
            definition=ToolDefinition(
                tool_id=TOOL_MATCH_TRUSTED_QUESTION,
                name="匹配可信问题（结构化）",
                description="可信问题库归一化精确命中返回标准问题，否则返回澄清候选（不确定不执行）",
                contract_kind=ToolContractKind.FUNCTION,
                target_ref="src.runtime.policy_qa.knowledge_lookup.match_trusted_question",
                risk_level=ToolRiskLevel.LOW,
                tags=["知识类", "结构化匹配"],
            ),
            status=ToolStatus.MATERIALIZED,
        ),
        implementation=match_trusted_question,
    )

    registry.register(
        ToolVersion(
            version_id="tv_comprehensive_knowledge_lookup_1",
            tool_id=TOOL_COMPREHENSIVE_KNOWLEDGE_LOOKUP,
            semantic_version="1.0.0",
            definition=ToolDefinition(
                tool_id=TOOL_COMPREHENSIVE_KNOWLEDGE_LOOKUP,
                name="综合知识检索",
                description="先可信问题库结构化命中、未命中降级向量政策证据，并附澄清候选（两级融合）",
                contract_kind=ToolContractKind.FUNCTION,
                target_ref="src.runtime.policy_qa.knowledge_lookup.comprehensive_knowledge_lookup",
                risk_level=ToolRiskLevel.LOW,
                tags=["知识类", "综合检索"],
            ),
            status=ToolStatus.MATERIALIZED,
        ),
        implementation=comprehensive_knowledge_lookup,
    )
