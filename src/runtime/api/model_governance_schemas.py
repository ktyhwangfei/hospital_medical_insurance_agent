"""模型治理 API 契约。"""

from typing import Literal

from pydantic import BaseModel, Field, SecretStr, model_validator

from src.model_service.governance_assets import (
    GovernanceAssetContent,
    GovernanceAssetPreview,
    GovernanceAssetType,
    GovernanceDraft,
    GovernanceEnvironment,
    GovernanceImportResult,
    GovernanceRelease,
    GovernanceVersion,
    ModelProfileAssetContent,
    PublishedGovernanceAsset,
    PublishedGovernanceSnapshot,
)
from src.runtime.api.schemas import AgentResponse


class ModelGovernancePrincipal(BaseModel):
    user_id: str
    roles: list[str] = Field(default_factory=list)
    permissions: list[str] = Field(default_factory=list)


class ModelCredentialInput(BaseModel):
    credential_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{2,127}$")
    api_key: SecretStr = Field(min_length=1, max_length=4096)


class _GovernanceDraftContentRequest(BaseModel):
    content: GovernanceAssetContent
    credential: ModelCredentialInput | None = None

    @model_validator(mode="after")
    def credential_matches_model(self):
        if self.credential is None:
            return self
        if not isinstance(self.content, ModelProfileAssetContent):
            raise ValueError("只有模型资产可以提交凭据")
        if self.content.credential_ref != self.credential.credential_id:
            raise ValueError("credential_ref 必须与 credential_id 一致")
        return self


class CreateGovernanceDraftRequest(_GovernanceDraftContentRequest):
    pass


class UpdateGovernanceDraftRequest(_GovernanceDraftContentRequest):
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
    baselines: list[GovernanceAssetContent] = Field(default_factory=list)
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
    "ModelCredentialInput",
    "PreviewGovernanceDraftRequest",
    "PublishedGovernanceSnapshotResponse",
    "PublishGovernanceDraftRequest",
    "UpdateGovernanceDraftRequest",
]
