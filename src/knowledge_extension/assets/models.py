from enum import StrEnum

from pydantic import BaseModel, Field

from src.knowledge_extension.common.models import AuditSummary, Degradation, VisibilityScope


class KnowledgeAssetType(StrEnum):
    POLICY = "policy"
    INTERNAL_POLICY = "internal_policy"
    ERROR_CODE = "error_code"
    AUDIT_RULE = "audit_rule"
    APPEAL_TEMPLATE = "appeal_template"
    BUSINESS_GUIDE = "business_guide"


class KnowledgeAssetStatus(StrEnum):
    DRAFT = "draft"
    PUBLISHED = "published"
    INACTIVE = "inactive"
    EXPIRED = "expired"


class IndexStatus(StrEnum):
    NOT_INDEXED = "not_indexed"
    INDEXING = "indexing"
    INDEXED = "indexed"
    FAILED = "failed"
    REBUILD_REQUIRED = "rebuild_required"


class KnowledgeAsset(BaseModel):
    asset_id: str
    asset_type: KnowledgeAssetType
    title: str
    summary: str
    source: str
    version: str
    status: KnowledgeAssetStatus
    effective_date: str | None = None
    expired_date: str | None = None
    imported_at: str
    visibility: VisibilityScope = Field(default_factory=VisibilityScope)
    index_status: IndexStatus = IndexStatus.NOT_INDEXED


class KnowledgeChunk(BaseModel):
    chunk_id: str
    asset_id: str
    asset_version: str
    title: str
    asset_type: KnowledgeAssetType
    section: str
    text: str
    summary: str
    tags: set[str] = Field(default_factory=set)
    scenario_tags: set[str] = Field(default_factory=set)
    visibility: VisibilityScope = Field(default_factory=VisibilityScope)
    locator: str | None = None
    index_status: IndexStatus = IndexStatus.INDEXED


class AssetQuery(BaseModel):
    role: str
    tenant_id: str | None = None
    campus_id: str | None = None
    scenario: str | None = None
    asset_types: set[KnowledgeAssetType] = Field(default_factory=set)
    include_inactive: bool = False


class AssetWriteResult(Degradation):
    asset_id: str | None = None


class AssetRepositorySnapshot(BaseModel):
    assets: list[KnowledgeAsset]
    chunks: list[KnowledgeChunk]
    audit_events: list[AuditSummary]
