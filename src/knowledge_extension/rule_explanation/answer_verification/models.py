"""知识答案验证领域模型与规则知识源端口。

答案验证（KnowledgeAnswerVerification）：以 ``qa_turn_id`` 为句柄，验证政策问答
（Policy QA）回答的引用真实性与结论与结构化知识的一致性。五个一等验证维度独立
断言、独立失败码；确定性优先，LLM 仅用于非门禁的支撑性辅助审查，fail-closed。

MVU-1 范围：验证领域模型 + 引用真实性（citation_authenticity）核心。
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any, Literal, Protocol

from pydantic import BaseModel, Field


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class KnowledgeAnswerVerificationDimension(StrEnum):
    """答案验证维度：五个一等维度，独立断言、独立失败码。"""

    CITATION_AUTHENTICITY = "citation_authenticity"        # 引用真实性
    CITATION_SUPPORT = "citation_support"                  # 引用支撑性
    CONCLUSION_CONSISTENCY = "conclusion_consistency"      # 结论一致性
    CALCULATION_CONSISTENCY = "calculation_consistency"    # 计算一致性
    COVERAGE_COMPLETENESS = "coverage_completeness"        # 覆盖完整性


class KnowledgeAnswerVerificationStatus(StrEnum):
    """答案验证状态：fail-closed，绝不伪造通过。"""

    PASSED = "passed"
    FAILED = "failed"
    NOT_EVALUABLE = "not_evaluable"                # 上下文/证据不足，无法形成结论
    BLOCKED_BY_EVALUATOR = "blocked_by_evaluator"  # 依赖不可用（模型/知识源），不通过
    REVIEW_REQUIRED = "review_required"            # 仅能辅助支撑，需人工复核


class CitationLinkMethod(StrEnum):
    """引用关联方法：前三级可产生强通过；向量仅候选发现，不单独证明真实性。"""

    INTERNAL_ID_MATCH = "internal_id_match"                        # 内部证据 rule_id + hash 命中知识源
    NORMALIZED_EXACT_MATCH = "normalized_exact_match"              # 归一化后 excerpt 为 source_text 连续片段
    METADATA_CONSTRAINED_MATCH = "metadata_constrained_match"      # title 映射 + 原文包含 + 规则条件一致
    VECTOR_CANDIDATE_FALLBACK = "vector_candidate_fallback"        # 仅候选发现，必须再经文本/元数据一致
    UNVERIFIED = "unverified"                                      # 找不回原文，fail-closed


class AnswerCitation(BaseModel):
    """待验证的公开引用（对应 ``PolicyQAPublicResult.citations`` 的 title + excerpt）。"""

    title: str = ""
    excerpt: str


class AnswerEvidenceRef(BaseModel):
    """内部证据引用（对应 ``StructuredPolicyEvidence`` 的血缘字段；仅服务端验证使用，不回显）。"""

    evidence_id: str = ""
    rule_id: str = ""
    rule_instance_key: str = ""
    policy_id: str = ""
    clause_id: str = ""
    query_name: str = ""
    source_text: str = ""
    source_text_hash: str = ""
    rule_value: str = ""
    payment_ratio: str = ""
    amount_band: str = ""
    psn_type: str = ""


class QueryPlanItem(BaseModel):
    """一次结构化查询计划及命中情况（覆盖完整性验证输入）。"""

    query_name: str
    required: bool = True
    hit_count: int = 0


class KnowledgeAnswerVerificationInput(BaseModel):
    """答案验证内部信封：以 ``qa_turn_id`` 为句柄，含公开结果快照 + 内部证据血缘。"""

    qa_turn_id: str
    question: str = ""
    answer: str = ""
    answer_status: Literal["complete", "partial", "unavailable"] = "unavailable"
    citations: list[AnswerCitation] = Field(default_factory=list)
    internal_evidence: list[AnswerEvidenceRef] = Field(default_factory=list)
    release_rules_collection: str | None = None
    release_facts_collection: str | None = None
    context: dict[str, Any] = Field(default_factory=dict)  # 归一化结算上下文快照
    scenario: str = ""  # 支持场景标记（如 pooling_self_pay）；空 = 未声明 → 覆盖完整性 not_evaluable
    planned_queries: list[QueryPlanItem] = Field(default_factory=list)
    missing_required_rules: list[str] = Field(default_factory=list)
    calculation_trace: dict[str, Any] | None = None  # 内部计算轨迹（SkillResult.calculation_trace）
    created_at: datetime = Field(default_factory=utc_now)


class RuleRecord(BaseModel):
    """规则知识源中的一条规则记录：引用真实性验证的确定性比对对象。"""

    rule_id: str
    rule_instance_key: str = ""
    policy_id: str = ""
    clause_id: str = ""
    title: str = ""
    source_text: str = ""
    source_text_hash: str = ""
    rule_value: str = ""
    payment_ratio: str = ""
    amount_band: str = ""
    psn_type: str = ""
    query_name: str = ""


class RuleKnowledgePort(Protocol):
    """规则知识源端口：引用真实性验证的确定性数据来源。

    实现应指向当前 release 的 rules collection（Milvus）或等效权威知识源。
    ``find_similar_rules`` 仅用于候选发现，不得单独作为真实性证明。
    """

    def get_rule_by_id(self, rule_id: str) -> RuleRecord | None: ...
    def find_rules_by_text(self, text: str, *, limit: int = 5) -> list[RuleRecord]: ...
    def find_similar_rules(self, text: str, *, limit: int = 5) -> list[RuleRecord]: ...
    def find_rules_by_title(self, title: str, *, limit: int = 5) -> list[RuleRecord]: ...


class CitationVerification(BaseModel):
    """单条引用的验证结果。"""

    citation_index: int
    title: str
    excerpt: str
    link_method: CitationLinkMethod
    verified: bool
    matched_rule_id: str | None = None
    failures: list[KnowledgeAnswerEvalFailure] = Field(default_factory=list)


@dataclass(frozen=True)
class KnowledgeAnswerEvalFailure:
    """单条验证失败：稳定错误码 + 中文说明（对齐 SkillRegressionEvalFailure 约定）。"""

    code: str
    message: str = ""


class KnowledgeAnswerDimensionResult(BaseModel):
    """单个维度的验证结果。"""

    dimension: KnowledgeAnswerVerificationDimension
    status: KnowledgeAnswerVerificationStatus
    failures: list[KnowledgeAnswerEvalFailure] = Field(default_factory=list)
    details: dict[str, Any] = Field(default_factory=dict)


class KnowledgeAnswerVerificationResult(BaseModel):
    """一次答案验证的完整结果。"""

    verification_id: str
    qa_turn_id: str
    status: KnowledgeAnswerVerificationStatus
    dimensions: dict[str, KnowledgeAnswerDimensionResult] = Field(default_factory=dict)
    evaluated_at: datetime = Field(default_factory=utc_now)
