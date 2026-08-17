"""模型治理 API 契约。"""

from typing import Literal

from pydantic import BaseModel, Field

from src.model_service.governance_assets import (
    GovernanceAssetContent,
    GovernanceAssetPreview,
    GovernanceAssetType,
    GovernanceDraft,
    GovernanceEnvironment,
    GovernanceImportResult,
    GovernanceRelease,
    GovernanceVersion,
    PublishedGovernanceAsset,
    PublishedGovernanceSnapshot,
)
from src.runtime.api.schemas import AgentResponse


class ModelGovernancePrincipal(BaseModel):
    user_id: str
    roles: list[str] = Field(default_factory=list)
    permissions: list[str] = Field(default_factory=list)


class CreateGovernanceDraftRequest(BaseModel):
    content: GovernanceAssetContent


class UpdateGovernanceDraftRequest(BaseModel):
    content: GovernanceAssetContent
    expected_revision: int = Field(ge=1)


class GovernanceRevisionRequest(BaseModel):
    expected_revision: int = Field(ge=1)


class PreviewGovernanceDraftRequest(BaseModel):
    variables: dict[str, str] = Field(default_factory=dict)


class ApproveGovernanceDraftRequest(GovernanceRevisionRequest):
    reason: str = Field(min_length=1, max_length=1000)


class PublishGovernanceDraftRequest(GovernanceRevisionRequest):
    environment: GovernanceEnvironment


class GovernanceAssetsResult(BaseModel):
    drafts: list[GovernanceDraft] = Field(default_factory=list)
    published: list[PublishedGovernanceAsset] = Field(default_factory=list)


class GovernanceReleasesResult(BaseModel):
    releases: list[GovernanceRelease] = Field(default_factory=list)


class GovernanceVersionsResult(BaseModel):
    versions: list[GovernanceVersion] = Field(default_factory=list)
    releases: list[GovernanceRelease] = Field(default_factory=list)


class _GovernanceResponse(AgentResponse):
    scenario: Literal["model_governance"] = "model_governance"
    status: Literal["success"] = "success"


class GovernanceDraftResponse(_GovernanceResponse):
    result: GovernanceDraft


class GovernancePreviewResponse(_GovernanceResponse):
    result: GovernanceAssetPreview


class GovernanceReleaseResponse(_GovernanceResponse):
    result: GovernanceRelease


class GovernanceAssetsResponse(_GovernanceResponse):
    result: GovernanceAssetsResult


class GovernanceReleasesResponse(_GovernanceResponse):
    result: GovernanceReleasesResult


class GovernanceVersionsResponse(_GovernanceResponse):
    result: GovernanceVersionsResult


class GovernanceImportResponse(_GovernanceResponse):
    result: GovernanceImportResult


class PublishedGovernanceSnapshotResponse(_GovernanceResponse):
    result: PublishedGovernanceSnapshot


__all__ = [
    "ApproveGovernanceDraftRequest",
    "CreateGovernanceDraftRequest",
    "GovernanceAssetsResponse",
    "GovernanceAssetsResult",
    "GovernanceAssetType",
    "GovernanceDraftResponse",
    "GovernanceEnvironment",
    "GovernanceImportResponse",
    "GovernancePreviewResponse",
    "GovernanceReleaseResponse",
    "GovernanceReleasesResponse",
    "GovernanceReleasesResult",
    "GovernanceRevisionRequest",
    "GovernanceVersionsResponse",
    "GovernanceVersionsResult",
    "ModelGovernancePrincipal",
    "PreviewGovernanceDraftRequest",
    "PublishedGovernanceSnapshotResponse",
    "PublishGovernanceDraftRequest",
    "UpdateGovernanceDraftRequest",
]
