"""模型治理 API 契约。"""

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, Field, SecretStr

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
    PromptAssetContent,
    PublishedGovernanceAsset,
    PublishedGovernanceSnapshot,
    RouteRuleAssetContent,
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


class PromptGovernanceBaseline(PromptAssetContent):
    runtime_status: Literal["fallback_static"] = "fallback_static"


class ModelProfileGovernanceBaseline(ModelProfileAssetContent):
    runtime_status: Literal["fallback_static"] = "fallback_static"


class RouteRuleGovernanceBaseline(RouteRuleAssetContent):
    runtime_status: Literal["fallback_static"] = "fallback_static"


GovernanceBaseline = Annotated[
    PromptGovernanceBaseline
    | ModelProfileGovernanceBaseline
    | RouteRuleGovernanceBaseline,
    Field(discriminator="asset_type"),
]


class GovernanceAssetsResult(BaseModel):
    baselines: list[GovernanceBaseline] = Field(default_factory=list)
    drafts: list[GovernanceDraft] = Field(default_factory=list)
    published: list[PublishedGovernanceAsset] = Field(default_factory=list)


class GovernanceReleasesResult(BaseModel):
    releases: list[GovernanceRelease] = Field(default_factory=list)


class GovernanceVersionsResult(BaseModel):
    versions: list[GovernanceVersion] = Field(default_factory=list)
    releases: list[GovernanceRelease] = Field(default_factory=list)


class GovernanceConnectionTestResult(BaseModel):
    status: Literal["success", "failure"]
    latency_ms: int = Field(ge=0)
    safe_message: str
    tested_at: datetime
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")


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


class GovernanceConnectionTestResponse(_GovernanceResponse):
    result: GovernanceConnectionTestResult


class GovernanceImportResponse(_GovernanceResponse):
    result: GovernanceImportResult


class PublishedGovernanceSnapshotResponse(_GovernanceResponse):
    result: PublishedGovernanceSnapshot


__all__ = [
    "ApproveGovernanceDraftRequest",
    "CreateGovernanceDraftRequest",
    "GovernanceAssetsResponse",
    "GovernanceAssetsResult",
    "GovernanceBaseline",
    "GovernanceAssetType",
    "GovernanceDraftResponse",
    "GovernanceConnectionTestResponse",
    "GovernanceConnectionTestResult",
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
    "ModelProfileGovernanceBaseline",
    "PreviewGovernanceDraftRequest",
    "PromptGovernanceBaseline",
    "PublishedGovernanceSnapshotResponse",
    "PublishGovernanceDraftRequest",
    "RouteRuleGovernanceBaseline",
    "UpdateGovernanceDraftRequest",
]
