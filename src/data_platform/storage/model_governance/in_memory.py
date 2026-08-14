"""模型治理的内存存储，仅用于显式开启的测试与开发环境。"""

from datetime import datetime, timezone
from threading import RLock

from src.data_platform.storage.model_governance.ports import (
    ModelGovernanceConflictError,
    ModelGovernanceNotFoundError,
)
from src.model_service.governance_assets import (
    GovernanceApproval,
    GovernanceAssetType,
    GovernanceDraft,
    GovernanceEnvironment,
    GovernanceRelease,
    GovernanceReleaseStatus,
    GovernanceVersion,
)


class InMemoryModelGovernanceStorage:
    def __init__(self) -> None:
        self._drafts: dict[str, GovernanceDraft] = {}
        self._versions: dict[str, GovernanceVersion] = {}
        self._approvals: dict[str, GovernanceApproval] = {}
        self._releases: dict[str, GovernanceRelease] = {}
        self._lock = RLock()

    @staticmethod
    def _copy(value):
        return value.model_copy(deep=True)

    def create_draft(self, draft: GovernanceDraft) -> GovernanceDraft:
        with self._lock:
            if draft.draft_id in self._drafts:
                raise ModelGovernanceConflictError("草稿已存在")
            self._drafts[draft.draft_id] = self._copy(draft)
            return self._copy(draft)

    def update_draft(
        self, draft: GovernanceDraft, *, expected_revision: int
    ) -> GovernanceDraft:
        with self._lock:
            current = self._drafts.get(draft.draft_id)
            if current is None:
                raise ModelGovernanceNotFoundError("草稿不存在")
            if current.revision != expected_revision:
                raise ModelGovernanceConflictError("草稿 revision 已变化")
            if draft.revision != expected_revision + 1:
                raise ModelGovernanceConflictError("草稿 revision 必须递增 1")
            self._drafts[draft.draft_id] = self._copy(draft)
            return self._copy(draft)

    def get_draft(self, draft_id: str) -> GovernanceDraft:
        with self._lock:
            try:
                return self._copy(self._drafts[draft_id])
            except KeyError as exc:
                raise ModelGovernanceNotFoundError("草稿不存在") from exc

    def delete_draft(
        self, draft_id: str, *, expected_revision: int
    ) -> GovernanceDraft:
        with self._lock:
            current = self._drafts.get(draft_id)
            if current is None:
                raise ModelGovernanceNotFoundError("草稿不存在")
            if current.revision != expected_revision:
                raise ModelGovernanceConflictError("草稿 revision 已变化")
            del self._drafts[draft_id]
            return self._copy(current)

    def list_drafts(
        self, asset_type: GovernanceAssetType | None = None
    ) -> list[GovernanceDraft]:
        with self._lock:
            items = [
                draft
                for draft in self._drafts.values()
                if asset_type is None or draft.asset_type == asset_type
            ]
            return [self._copy(item) for item in sorted(items, key=lambda x: x.updated_at, reverse=True)]

    def save_version(self, version: GovernanceVersion) -> GovernanceVersion:
        with self._lock:
            for existing in self._versions.values():
                if (
                    existing.asset_id == version.asset_id
                    and existing.content_hash == version.content_hash
                ):
                    return self._copy(existing)
            if version.version_id in self._versions or any(
                item.asset_id == version.asset_id
                and item.version_number == version.version_number
                for item in self._versions.values()
            ):
                raise ModelGovernanceConflictError("版本已存在")
            self._versions[version.version_id] = self._copy(version)
            return self._copy(version)

    def get_version(self, version_id: str) -> GovernanceVersion:
        with self._lock:
            try:
                return self._copy(self._versions[version_id])
            except KeyError as exc:
                raise ModelGovernanceNotFoundError("版本不存在") from exc

    def list_versions(self, asset_id: str) -> list[GovernanceVersion]:
        with self._lock:
            items = [item for item in self._versions.values() if item.asset_id == asset_id]
            return [self._copy(item) for item in sorted(items, key=lambda x: x.version_number, reverse=True)]

    def save_approval(self, approval: GovernanceApproval) -> GovernanceApproval:
        with self._lock:
            if approval.approval_id in self._approvals:
                raise ModelGovernanceConflictError("审批记录已存在")
            self._approvals[approval.approval_id] = self._copy(approval)
            return self._copy(approval)

    def approve_draft(
        self,
        draft: GovernanceDraft,
        approval: GovernanceApproval,
        *,
        expected_revision: int,
    ) -> GovernanceDraft:
        with self._lock:
            current = self._drafts.get(draft.draft_id)
            if current is None:
                raise ModelGovernanceNotFoundError("草稿不存在")
            if current.revision != expected_revision:
                raise ModelGovernanceConflictError("草稿 revision 已变化")
            if draft.revision != expected_revision + 1:
                raise ModelGovernanceConflictError("草稿 revision 必须递增 1")
            if approval.approval_id in self._approvals:
                raise ModelGovernanceConflictError("审批记录已存在")
            self._approvals[approval.approval_id] = self._copy(approval)
            self._drafts[draft.draft_id] = self._copy(draft)
            return self._copy(draft)

    def get_approval(self, approval_id: str) -> GovernanceApproval:
        with self._lock:
            try:
                return self._copy(self._approvals[approval_id])
            except KeyError as exc:
                raise ModelGovernanceNotFoundError("审批记录不存在") from exc

    def publish(self, release: GovernanceRelease) -> GovernanceRelease:
        with self._lock:
            if release.release_id in self._releases:
                raise ModelGovernanceConflictError("发布记录已存在")
            active = next(
                (
                    item
                    for item in self._releases.values()
                    if item.asset_id == release.asset_id
                    and item.environment == release.environment
                    and item.status == GovernanceReleaseStatus.ACTIVE
                ),
                None,
            )
            active_id = active.release_id if active else None
            if active_id != release.previous_release_id:
                raise ModelGovernanceConflictError("发布基线已变化")
            if active:
                self._releases[active.release_id] = active.model_copy(
                    update={
                        "status": GovernanceReleaseStatus.RETIRED,
                        "retired_at": datetime.now(timezone.utc),
                    },
                    deep=True,
                )
            self._releases[release.release_id] = self._copy(release)
            return self._copy(release)

    def get_release(self, release_id: str) -> GovernanceRelease:
        with self._lock:
            try:
                return self._copy(self._releases[release_id])
            except KeyError as exc:
                raise ModelGovernanceNotFoundError("发布记录不存在") from exc

    def list_releases(
        self,
        asset_id: str | None = None,
        environment: GovernanceEnvironment | None = None,
    ) -> list[GovernanceRelease]:
        with self._lock:
            items = [
                item
                for item in self._releases.values()
                if (asset_id is None or item.asset_id == asset_id)
                and (environment is None or item.environment == environment)
            ]
            items.sort(key=lambda item: (item.created_at, item.release_id), reverse=True)
            return [self._copy(item) for item in items]

    def get_active_release(
        self, asset_id: str, environment: GovernanceEnvironment
    ) -> GovernanceRelease | None:
        with self._lock:
            for item in self._releases.values():
                if (
                    item.asset_id == asset_id
                    and item.environment == environment
                    and item.status == GovernanceReleaseStatus.ACTIVE
                ):
                    return self._copy(item)
            return None
