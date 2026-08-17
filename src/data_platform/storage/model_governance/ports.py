"""模型治理存储契约。"""

from typing import Protocol

from src.model_service.governance_assets import (
    GovernanceApproval,
    GovernanceAssetType,
    GovernanceConnectionTest,
    GovernanceCredential,
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
    def put_credential(
        self, credential: GovernanceCredential
    ) -> GovernanceCredential: ...

    def get_credential(self, credential_id: str) -> GovernanceCredential: ...

    def save_connection_test(
        self, result: GovernanceConnectionTest
    ) -> GovernanceConnectionTest: ...

    def find_successful_connection_test(
        self,
        asset_id: str,
        content_hash: str,
        credential_fingerprint: str,
    ) -> GovernanceConnectionTest | None: ...

    def create_draft(self, draft: GovernanceDraft) -> GovernanceDraft: ...

    def update_draft(
        self, draft: GovernanceDraft, *, expected_revision: int
    ) -> GovernanceDraft: ...

    def get_draft(self, draft_id: str) -> GovernanceDraft: ...

    def delete_draft(
        self, draft_id: str, *, expected_revision: int
    ) -> GovernanceDraft: ...

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

    def publish_draft_version(
        self,
        draft: GovernanceDraft,
        version: GovernanceVersion,
        release: GovernanceRelease,
        *,
        expected_revision: int,
    ) -> GovernanceRelease: ...

    def get_release(self, release_id: str) -> GovernanceRelease: ...

    def list_releases(
        self,
        asset_id: str | None = None,
        environment: GovernanceEnvironment | None = None,
    ) -> list[GovernanceRelease]: ...

    def get_active_release(
        self, asset_id: str, environment: GovernanceEnvironment
    ) -> GovernanceRelease | None: ...
