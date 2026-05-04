from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

from src.knowledge_extension.common.models import AuditSummary, KnowledgeExtensionStatus


class TemplateStatus(StrEnum):
    DRAFT = "draft"
    PUBLISHED = "published"
    INACTIVE = "inactive"


class PromptTemplate(BaseModel):
    template_id: str
    scenario: str
    role: str
    output_format: str
    language: str
    risk_level: str
    version: str
    status: TemplateStatus
    content: str
    required_variables: set[str] = Field(default_factory=set)
    requires_citations: bool = True
    requires_uncertainties: bool = True
    blocks_high_risk_actions: bool = True


class TemplateSelectionRequest(BaseModel):
    scenario: str
    role: str
    output_format: str
    language: str
    risk_level: str


class TemplateSelectionResult(BaseModel):
    status: KnowledgeExtensionStatus
    template: PromptTemplate | None = None
    uncertainties: list[str] = Field(default_factory=list)
    audit_events: list[AuditSummary] = Field(default_factory=list)


class TemplateRenderResult(BaseModel):
    status: KnowledgeExtensionStatus
    prompt: str = ""
    uncertainties: list[str] = Field(default_factory=list)
    audit_events: list[AuditSummary] = Field(default_factory=list)
