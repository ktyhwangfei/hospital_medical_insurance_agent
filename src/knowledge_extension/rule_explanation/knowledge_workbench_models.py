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


class KnowledgeItem(BaseModel):
    """一条可独立选择、测试和追溯的政策知识。"""

    knowledge_id: str
    unit_id: str
    extraction_id: str
    relationship_source: Literal["persisted", "legacy_match"]
    business_sentence: str
    source_text: str
    fields: list[KnowledgeField]
    confidence: KnowledgeConfidence
    citations: list[KnowledgeCitation]


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
    units: list[ApprovedUnit]

