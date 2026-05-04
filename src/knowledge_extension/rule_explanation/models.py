from enum import StrEnum

from pydantic import BaseModel, Field

from src.knowledge_extension.common.models import AuditSummary, Citation, KnowledgeExtensionStatus


class RuleType(StrEnum):
    ERROR_CODE = "error_code"
    POLICY = "policy"
    PRE_AUDIT = "pre_audit"
    DRG_DIP = "drg_dip"
    MEDICAL_RECORD = "medical_record"


class RuleEvidence(BaseModel):
    evidence_id: str
    title: str
    content: str
    citation: Citation | None = None


class RuleExplanationRequest(BaseModel):
    rule_type: RuleType
    rule_code: str
    scenario: str
    role: str
    evidences: list[RuleEvidence] = Field(default_factory=list)


class RuleExplanationResult(BaseModel):
    status: KnowledgeExtensionStatus
    rule_code: str
    meaning: str = ""
    conditions: list[str] = Field(default_factory=list)
    suggestions: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    citations: list[Citation] = Field(default_factory=list)
    uncertainties: list[str] = Field(default_factory=list)
    requires_human_review: bool = False
    review_hint: str = ""
    audit_events: list[AuditSummary] = Field(default_factory=list)
