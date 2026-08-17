"""模型治理的内存存储，仅用于显式开启的测试与开发环境。"""

from datetime import datetime, timezone
from threading import RLock

from src.data_platform.storage.model_governance.ports import (
    GovernanceCredentialPrecondition,
    GovernanceReleasePrecondition,
    ModelGovernanceConflictError,
    ModelGovernanceNotFoundError,
)
from src.model_service.governance_assets import (
    GovernanceApproval,
    GovernanceAssetType,
    GovernanceConnectionTest,
    GovernanceCredential,
    GovernanceDraft,
    GovernanceEnvironment,
    GovernanceRelease,
    GovernanceReleaseCredentialBinding,
    GovernanceReleaseStatus,
    GovernanceVersion,
)


class InMemoryModelGovernanceStorage:
    def __init__(self) -> None:
        self._drafts: dict[str, GovernanceDraft] = {}
        self._versions: dict[str, GovernanceVersion] = {}
        self._approvals: dict[str, GovernanceApproval] = {}
        self._releases: dict[str, GovernanceRelease] = {}
        self._credentials: dict[str, GovernanceCredential] = {}
        self._credential_versions: dict[tuple[str, int], GovernanceCredential] = {}
        self._release_credentials: dict[str, GovernanceReleaseCredentialBinding] = {}
        self._connection_tests: dict[str, GovernanceConnectionTest] = {}
        self._lock = RLock()

    @staticmethod
    def _copy(value):
        return value.model_copy(deep=True)

    def put_credential(
        self, credential: GovernanceCredential
    ) -> GovernanceCredential:
        with self._lock:
            self._store_credential(credential)
            return self._copy(credential)

    def _store_credential(self, credential: GovernanceCredential) -> None:
        current = self._credentials.get(credential.credential_id)
        expected_revision = 1 if current is None else current.revision + 1
        history_key = (credential.credential_id, credential.revision)
        if (
            credential.revision != expected_revision
            or history_key in self._credential_versions
        ):
            raise ModelGovernanceConflictError("凭据 revision 已变化")
        stored = self._copy(credential)
        historical = self._copy(credential)
        self._credentials[credential.credential_id] = stored
        self._credential_versions[history_key] = historical

    def get_credential(self, credential_id: str) -> GovernanceCredential:
        with self._lock:
            try:
                return self._copy(self._credentials[credential_id])
            except KeyError as exc:
                raise ModelGovernanceNotFoundError("凭据不存在") from exc

    def get_credential_revision(
        self, credential_id: str, revision: int
    ) -> GovernanceCredential:
        with self._lock:
            try:
                return self._copy(self._credential_versions[(credential_id, revision)])
            except KeyError as exc:
                raise ModelGovernanceNotFoundError("凭据版本不存在") from exc

    def get_release_credential_binding(
        self, release_id: str
    ) -> GovernanceReleaseCredentialBinding:
        with self._lock:
            try:
                return self._copy(self._release_credentials[release_id])
            except KeyError as exc:
                raise ModelGovernanceNotFoundError("发布凭据绑定不存在") from exc

    def save_connection_test(
        self, result: GovernanceConnectionTest
    ) -> GovernanceConnectionTest:
        with self._lock:
            if result.test_id in self._connection_tests:
                raise ModelGovernanceConflictError("连接测试记录已存在")
            self._connection_tests[result.test_id] = self._copy(result)
            return self._copy(result)

    def find_successful_connection_test(
        self,
        asset_id: str,
        content_hash: str,
        credential_fingerprint: str,
    ) -> GovernanceConnectionTest | None:
        with self._lock:
            matches = [
                item
                for item in self._connection_tests.values()
                if item.asset_id == asset_id
                and item.content_hash == content_hash
                and item.credential_fingerprint == credential_fingerprint
                and item.succeeded
            ]
            if not matches:
                return None
            return self._copy(max(matches, key=lambda item: (item.tested_at, item.test_id)))

    def create_draft(self, draft: GovernanceDraft) -> GovernanceDraft:
        with self._lock:
            if draft.draft_id in self._drafts:
                raise ModelGovernanceConflictError("草稿已存在")
            self._drafts[draft.draft_id] = self._copy(draft)
            return self._copy(draft)

    def create_draft_with_credential(
        self,
        draft: GovernanceDraft,
        credential: GovernanceCredential,
    ) -> GovernanceDraft:
        with self._lock:
            if draft.draft_id in self._drafts:
                raise ModelGovernanceConflictError("草稿已存在")
            # 先构造全部副本，任一步失败都不更改已存状态。
            next_draft = self._copy(draft)
            self._store_credential(credential)
            self._drafts[draft.draft_id] = next_draft
            return self._copy(next_draft)

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

    def update_draft_with_credential(
        self,
        draft: GovernanceDraft,
        credential: GovernanceCredential,
        *,
        expected_revision: int,
    ) -> GovernanceDraft:
        with self._lock:
            current_draft = self._drafts.get(draft.draft_id)
            if current_draft is None or current_draft.revision != expected_revision:
                raise ModelGovernanceConflictError("草稿 revision 已变化或草稿不存在")
            if draft.revision != expected_revision + 1:
                raise ModelGovernanceConflictError("草稿 revision 必须递增 1")
            next_draft = self._copy(draft)
            self._store_credential(credential)
            self._drafts[draft.draft_id] = next_draft
            return self._copy(next_draft)

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

    def _check_credential_precondition(
        self, precondition: GovernanceCredentialPrecondition | None
    ) -> None:
        if precondition is None:
            return
        current = self._credentials.get(precondition.credential_id)
        if (
            current is None
            or current.secret_fingerprint != precondition.expected_fingerprint
            or current.revision != precondition.expected_revision
        ):
            raise ModelGovernanceConflictError("模型凭据已变化")

    def _check_release_preconditions(
        self, preconditions: tuple[GovernanceReleasePrecondition, ...]
    ) -> None:
        for precondition in preconditions:
            active = next(
                (
                    item
                    for item in self._releases.values()
                    if item.asset_id == precondition.asset_id
                    and item.environment == precondition.environment
                    and item.status == GovernanceReleaseStatus.ACTIVE
                ),
                None,
            )
            if (
                active is None
                or active.release_id != precondition.expected_release_id
                or active.version_id != precondition.expected_version_id
            ):
                raise ModelGovernanceConflictError("引用的模型发布已变化")

    def _check_credential_binding(
        self,
        release: GovernanceRelease,
        binding: GovernanceReleaseCredentialBinding | None,
    ) -> None:
        if binding is None:
            return
        credential = self._credential_versions.get(
            (binding.credential_id, binding.credential_revision)
        )
        if (
            binding.release_id != release.release_id
            or credential is None
            or credential.secret_fingerprint != binding.credential_fingerprint
        ):
            raise ModelGovernanceConflictError("发布凭据绑定无效")

    def publish(
        self,
        release: GovernanceRelease,
        *,
        credential_precondition: GovernanceCredentialPrecondition | None = None,
        credential_binding: GovernanceReleaseCredentialBinding | None = None,
        referenced_release_preconditions: tuple[
            GovernanceReleasePrecondition, ...
        ] = (),
    ) -> GovernanceRelease:
        with self._lock:
            self._check_credential_precondition(credential_precondition)
            self._check_release_preconditions(referenced_release_preconditions)
            self._check_credential_binding(release, credential_binding)
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
            next_release = self._copy(release)
            next_binding = (
                self._copy(credential_binding)
                if credential_binding is not None
                else None
            )
            result = self._copy(next_release)
            retired = (
                active.model_copy(
                    update={
                        "status": GovernanceReleaseStatus.RETIRED,
                        "retired_at": datetime.now(timezone.utc),
                    },
                    deep=True,
                )
                if active
                else None
            )
            if retired is not None:
                self._releases[active.release_id] = retired
            self._releases[release.release_id] = next_release
            if next_binding is not None:
                self._release_credentials[release.release_id] = next_binding
            return result

    def publish_draft_version(
        self,
        draft: GovernanceDraft,
        version: GovernanceVersion,
        release: GovernanceRelease,
        *,
        expected_revision: int,
        credential_precondition: GovernanceCredentialPrecondition | None = None,
        credential_binding: GovernanceReleaseCredentialBinding | None = None,
        referenced_release_preconditions: tuple[
            GovernanceReleasePrecondition, ...
        ] = (),
    ) -> GovernanceRelease:
        with self._lock:
            current = self._drafts.get(draft.draft_id)
            if current is None or current.revision != expected_revision:
                raise ModelGovernanceConflictError("草稿 revision 已变化或草稿不存在")
            if draft.revision != expected_revision + 1:
                raise ModelGovernanceConflictError("草稿 revision 必须递增 1")
            self._check_credential_precondition(credential_precondition)
            self._check_release_preconditions(referenced_release_preconditions)
            self._check_credential_binding(release, credential_binding)
            if release.release_id in self._releases:
                raise ModelGovernanceConflictError("发布记录已存在")

            existing_version = next(
                (
                    item
                    for item in self._versions.values()
                    if item.asset_id == version.asset_id
                    and item.content_hash == version.content_hash
                ),
                None,
            )
            if existing_version is None and (
                version.version_id in self._versions
                or any(
                    item.asset_id == version.asset_id
                    and item.version_number == version.version_number
                    for item in self._versions.values()
                )
            ):
                raise ModelGovernanceConflictError("版本已存在")
            stored_version = existing_version or version
            if release.version_id != stored_version.version_id:
                raise ModelGovernanceConflictError("发布引用的版本已变化")

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

            next_draft = self._copy(draft)
            next_version = self._copy(version) if existing_version is None else None
            next_release = self._copy(release)
            next_binding = (
                self._copy(credential_binding)
                if credential_binding is not None
                else None
            )
            result = self._copy(next_release)
            retired = (
                active.model_copy(
                    update={
                        "status": GovernanceReleaseStatus.RETIRED,
                        "retired_at": datetime.now(timezone.utc),
                    },
                    deep=True,
                )
                if active
                else None
            )
            self._drafts[draft.draft_id] = next_draft
            if next_version is not None:
                self._versions[version.version_id] = next_version
            if retired is not None:
                self._releases[active.release_id] = retired
            self._releases[release.release_id] = next_release
            if next_binding is not None:
                self._release_credentials[release.release_id] = next_binding
            return result

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
