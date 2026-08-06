"""政策知识三栏工作台的类型化读取模型。"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class KnowledgeCitation(BaseModel):
    """知识到政策原文的最小可追溯引用。"""

    source_id: str
    source_type: Literal["policy_document"] = "policy_document"
    title: str
    unit_id: str
    extraction_id: str
    evidence: str


class KnowledgeEvidence(BaseModel):
    """字段级多证据锚点（V4.1 §4.6/§14.1：一条规则可关联多个证据）。"""

    evidence_id: str
    document_version_id: str
    unit_id: str
    clause_path: str | None = None
    page_no: int | None = None
    exact_quote: str
    start_offset: int | None = None
    end_offset: int | None = None
    evidence_role: str = "主结论证据"


class RuleValidity(BaseModel):
    """规则生效范围（V4.1 §4.2：参与政策匹配，非纯展示）。"""

    region: str | None = None
    start_date: str | None = None
    end_date: str | None = None
    policy_version: str | None = None


class RuleVariant(BaseModel):
    """决策表分支：分级/分档/区间规则的一个分支（V4.1 §4.3）。"""

    variant_id: str
    conditions: list[dict[str, Any]] = Field(default_factory=list)
    result_value: Any = None
    result_unit: str | None = None


class SemanticBinding(BaseModel):
    """政策字段到统一语义字段/值域/指标的对齐状态（V4.1 §8.5）。"""

    policy_field: str
    semantic_field: str | None = None
    concept: str | None = None
    value_domain: str | None = None
    status: str = "UNMAPPED"  # UNMAPPED / SUGGESTED / CONFIRMED / CONFLICT / INVALID


class KnowledgeField(BaseModel):
    """结构化知识中的一个来源字段。"""

    field_code: str
    field_name: str
    raw_value: Any


class KnowledgeConfidence(BaseModel):
    """可解释的知识可信度；没有证据的维度保持为空。"""

    completeness: float = Field(ge=0, le=1)
    accuracy: float | None = Field(default=None, ge=0, le=1)
    source_fidelity: float = Field(ge=0, le=1)
    model_confidence: float = Field(ge=0, le=1)
    value_domain_compliance: float | None = Field(default=None, ge=0, le=1)
    overall: float = Field(ge=0, le=1)
    uncertainties: list[str] = Field(default_factory=list)


class StandardizedField(BaseModel):
    """政策来源字段到统一标准指标和值域的对齐结果。"""

    source_field: str
    source_value: Any
    status: Literal["mapped", "unmapped", "not_applicable", "invalid"]
    metric_code: str | None = None
    metric_name: str | None = None
    value_domain: str | None = None
    standard_value: Any | None = None
    binding_id: str | None = None


class KnowledgeItem(BaseModel):
    """一条可独立选择、测试和追溯的政策知识。"""

    knowledge_id: str
    unit_id: str
    extraction_id: str
    relationship_source: Literal["persisted", "legacy_match"]
    business_sentence: str
    source_text: str
    fields: list[KnowledgeField]
    standardized_fields: list[StandardizedField] = Field(default_factory=list)
    confidence: KnowledgeConfidence
    citations: list[KnowledgeCitation]
    # 人工评审结论（中栏评审 → 通过后进入第三栏标化）；默认待评审。
    review_status: Literal["pending", "approved", "rejected"] = "pending"
    review_note: str | None = None
    # —— V4.1 政策规则单元契约（S1）——
    rule_group_id: str | None = None          # 同源规则组（同一 unit+extraction 的规则共享）
    topic_concept: str | None = None          # 业务主题概念编码，如 DEDUCTIBLE / PAYMENT_RATIO / CAP
    rule_type_enum: str | None = None         # FIXED_STANDARD / RATIO / TIERED / DECISION_TABLE / ELIGIBILITY / ...
    rule_type_label: str | None = None        # 中文类型（固定标准/资格条件/...）
    validity: RuleValidity | None = None      # 生效范围（未识别时 None → 前端显示“尚未识别”）
    variants: list[RuleVariant] = Field(default_factory=list)          # 决策表分支（阶段一为空）
    evidences: list[KnowledgeEvidence] = Field(default_factory=list)    # 多证据锚点（由 citations 派生）
    semantic_bindings: list[SemanticBinding] = Field(default_factory=list)  # 由 standardized_fields 派生


class ApprovedUnit(BaseModel):
    """单元页审核通过、允许进入知识页的政策单元。"""

    unit_id: str
    doc_id: str
    doc_title: str
    path: list[str]
    source_text: str
    order_no: int
    status: Literal["reviewed", "published"]
    knowledge_count: int
    knowledge: list[KnowledgeItem]


class KnowledgeWorkbenchDocument(BaseModel):
    """一个政策文档的 Unit×Knowledge 工作台读取结果。"""

    doc_id: str
    doc_title: str
    contract_version: str | None = None
    units: list[ApprovedUnit]


class WorkbenchDocumentSummary(BaseModel):
    """知识工作台文档选择器条目。"""

    doc_id: str
    doc_title: str
    approved_unit_count: int
    knowledge_count: int


class WorkbenchDocumentList(BaseModel):
    items: list[WorkbenchDocumentSummary]
    total: int
