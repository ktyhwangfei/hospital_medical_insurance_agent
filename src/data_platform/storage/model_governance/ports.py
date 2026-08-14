"""模型治理存储契约。"""

from typing import Protocol

from src.model_service.governance_assets import (
    GovernanceApproval,
    GovernanceAssetType,
    GovernanceDraft,
    GovernanceEnvironment,
    GovernanceRelease,
    GovernanceVersion,
)


class ModelGovernanceConflictError(ValueError):
    """治理资产发生并发或唯一性冲突。"""


class ModelGovernanceNotFoundError(LookupError):
    """治理资产不存在。"""


class ModelGovernanceStorage(Protocol):
    def create_draft(self, draft: GovernanceDraft) -> GovernanceDraft: ...

    def update_draft(
        self, draft: GovernanceDraft, *, expected_revision: int
    ) -> GovernanceDraft: ...

    def get_draft(self, draft_id: str) -> GovernanceDraft: ...

    def list_drafts(
        self, asset_type: GovernanceAssetType | None = None
    ) -> list[GovernanceDraft]: ...

    def save_version(self, version: GovernanceVersion) -> GovernanceVersion: ...

    def get_version(self, version_id: str) -> GovernanceVersion: ...

    def list_versions(self, asset_id: str) -> list[GovernanceVersion]: ...

    def save_approval(self, approval: GovernanceApproval) -> GovernanceApproval: ...

    def approve_draft(
        self,
        draft: GovernanceDraft,
        approval: GovernanceApproval,
        *,
        expected_revision: int,
    ) -> GovernanceDraft: ...

    def get_approval(self, approval_id: str) -> GovernanceApproval: ...

    def publish(self, release: GovernanceRelease) -> GovernanceRelease: ...

    def get_release(self, release_id: str) -> GovernanceRelease: ...

    def list_releases(
        self,
        asset_id: str | None = None,
        environment: GovernanceEnvironment | None = None,
    ) -> list[GovernanceRelease]: ...

    def get_active_release(
        self, asset_id: str, environment: GovernanceEnvironment
    ) -> GovernanceRelease | None: ...
