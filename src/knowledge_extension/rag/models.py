from pydantic import BaseModel, Field

from src.knowledge_extension.assets.models import KnowledgeAssetType, KnowledgeChunk
from src.knowledge_extension.common.models import AuditSummary, Citation, KnowledgeExtensionStatus


class RetrievalFilter(BaseModel):
    role: str
    tenant_id: str | None = None
    campus_id: str | None = None
    scenario: str | None = None
    asset_types: set[KnowledgeAssetType] = Field(default_factory=set)


class RetrievalRequest(BaseModel):
    query: str
    filters: RetrievalFilter
    max_results: int = Field(default=5, gt=0, le=50)
    context_budget: int = Field(default=1200, gt=0)
    trace_id: str | None = None


class RetrievalHit(BaseModel):
    chunk: KnowledgeChunk
    score: float
    matched_terms: list[str] = Field(default_factory=list)


class ContextPackage(BaseModel):
    hits: list[RetrievalHit] = Field(default_factory=list)
    citations: list[Citation] = Field(default_factory=list)
    context_text: str = ""
    truncated_count: int = 0


class RetrievalResult(BaseModel):
    status: KnowledgeExtensionStatus
    hits: list[RetrievalHit] = Field(default_factory=list)
    context: ContextPackage = Field(default_factory=ContextPackage)
    citations: list[Citation] = Field(default_factory=list)
    uncertainties: list[str] = Field(default_factory=list)
    audit_events: list[AuditSummary] = Field(default_factory=list)
