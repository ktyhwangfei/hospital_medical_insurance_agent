"""提示词、模型档案与路由规则的治理生命周期。"""

from datetime import datetime, timezone
from uuid import NAMESPACE_URL, uuid4, uuid5

from src.data_platform.storage.model_governance.ports import (
    ModelGovernanceConflictError,
    ModelGovernanceStorage,
)
from src.model_service.governance_assets import (
    GovernanceApproval,
    GovernanceAssetContent,
    GovernanceAssetPreview,
    GovernanceAssetType,
    GovernanceDraft,
    GovernanceDraftStatus,
    GovernanceEnvironment,
    GovernanceImportCounts,
    GovernanceImportResult,
    GovernanceRelease,
    GovernanceReleaseStatus,
    GovernanceRuntimeStatus,
    GovernanceValidationError,
    GovernanceValidationIssue,
    GovernanceVersion,
    ModelProfileAssetContent,
    PublishedGovernanceAsset,
    PublishedGovernanceSnapshot,
    RouteRuleAssetContent,
    content_hash,
    preview_asset,
    validate_asset,
)


class ModelGovernanceGateError(ValueError):
    """治理生命周期前置条件未满足。"""


class ModelGovernanceService:
    def __init__(self, storage: ModelGovernanceStorage) -> None:
        self._storage = storage

    @staticmethod
    def _now() -> datetime:
        return datetime.now(timezone.utc)

    @staticmethod
    def _asset_type(content: GovernanceAssetContent) -> GovernanceAssetType:
        return GovernanceAssetType(content.asset_type)

    def _current(self, draft_id: str, expected_revision: int) -> GovernanceDraft:
        draft = self._storage.get_draft(draft_id)
        if draft.revision != expected_revision:
            raise ModelGovernanceConflictError("草稿 revision 已变化")
        return draft

    def create_draft(
        self, content: GovernanceAssetContent, *, actor: str
    ) -> GovernanceDraft:
        now = self._now()
        return self._storage.create_draft(
            GovernanceDraft(
                draft_id=str(uuid4()),
                asset_id=content.asset_id,
                asset_type=self._asset_type(content),
                content=content,
                created_by=actor,
                last_edited_by=actor,
                created_at=now,
                updated_at=now,
            )
        )

    def save_draft(
        self,
        draft_id: str,
        content: GovernanceAssetContent,
        *,
        expected_revision: int,
        actor: str,
    ) -> GovernanceDraft:
        draft = self._current(draft_id, expected_revision)
        if content.asset_id != draft.asset_id or self._asset_type(content) != draft.asset_type:
            raise ModelGovernanceGateError("草稿不能变更资产标识或类型")
        digest = content_hash(draft.content)
        for release in self._storage.list_releases(draft.asset_id):
            if release.status != GovernanceReleaseStatus.ACTIVE:
                continue
            version = self._storage.get_version(release.version_id)
            approval = self._storage.get_approval(version.approval_id)
            if version.content_hash == digest and approval.draft_id == draft.draft_id:
                raise ModelGovernanceGateError("活动版本不可编辑，请新建版本")
        return self._storage.update_draft(
            draft.model_copy(
                update={
                    "content": content,
                    "status": GovernanceDraftStatus.EDITING,
                    "revision": draft.revision + 1,
                    "validation_issues": [],
                    "last_edited_by": actor,
                    "updated_at": self._now(),
                },
                deep=True,
            ),
            expected_revision=expected_revision,
        )

    def _profile_is_published(
        self,
        profile_id: str,
        environment: GovernanceEnvironment | None = None,
    ) -> bool:
        releases = self._storage.list_releases(profile_id, environment)
        for release in releases:
            if release.status != GovernanceReleaseStatus.ACTIVE:
                continue
            content = self._storage.get_version(release.version_id).content
            if isinstance(content, ModelProfileAssetContent) and content.enabled:
                return True
        return False

    def _validation_issues(
        self, content: GovernanceAssetContent
    ) -> list[GovernanceValidationIssue]:
        issues = validate_asset(content)
        if isinstance(content, RouteRuleAssetContent):
            profile_ids = [content.profile_id, *content.fallback_profile_ids]
            for profile_id in profile_ids:
                if not self._profile_is_published(profile_id):
                    issues.append(
                        GovernanceValidationIssue(
                            code="MODEL_PROFILE_NOT_PUBLISHED",
                            message=f"模型档案未发布或已停用: {profile_id}",
                            path="profile_id",
                        )
                    )
        return issues

    def validate_draft(
        self, draft_id: str, *, expected_revision: int
    ) -> GovernanceDraft:
        draft = self._current(draft_id, expected_revision)
        issues = self._validation_issues(draft.content)
        status = (
            GovernanceDraftStatus.EDITING
            if issues
            else GovernanceDraftStatus.VALIDATED
        )
        return self._storage.update_draft(
            draft.model_copy(
                update={
                    "status": status,
                    "revision": draft.revision + 1,
                    "validation_issues": issues,
                    "updated_at": self._now(),
                },
                deep=True,
            ),
            expected_revision=expected_revision,
        )

    def preview(
        self, draft_id: str, variables: dict[str, str] | None = None
    ) -> GovernanceAssetPreview:
        draft = self._storage.get_draft(draft_id)
        issues = self._validation_issues(draft.content)
        if issues:
            raise GovernanceValidationError("；".join(issue.message for issue in issues))
        return preview_asset(draft.content, variables)

    def list_drafts(
        self, asset_type: GovernanceAssetType | None = None
    ) -> list[GovernanceDraft]:
        return self._storage.list_drafts(asset_type)

    def list_releases(
        self,
        asset_id: str | None = None,
        environment: GovernanceEnvironment | None = None,
    ) -> list[GovernanceRelease]:
        return self._storage.list_releases(asset_id, environment)

    def list_versions(self, asset_id: str) -> list[GovernanceVersion]:
        return self._storage.list_versions(asset_id)

    def create_next_version(
        self,
        asset_id: str,
        *,
        actor: str,
        environment: GovernanceEnvironment,
    ) -> GovernanceDraft:
        active = self._storage.get_active_release(asset_id, environment)
        if active is None:
            raise ModelGovernanceGateError("资产没有可复制的活动版本")
        return self.create_draft(
            self._storage.get_version(active.version_id).content,
            actor=actor,
        )

    def import_current_assets(self, *, actor: str) -> GovernanceImportResult:
        from src.model_service.governance_import import build_current_governance_assets

        existing = {draft.asset_id for draft in self._storage.list_drafts()}
        assets = build_current_governance_assets()
        created: list[GovernanceDraft] = []
        counts = {asset_type.value: 0 for asset_type in GovernanceAssetType}
        for content in assets:
            if content.asset_id in existing:
                continue
            draft = self.create_draft(content, actor=actor)
            created.append(draft)
            existing.add(content.asset_id)
            counts[draft.asset_type.value] += 1
        return GovernanceImportResult(
            drafts=created,
            created_count=len(created),
            skipped_count=len(assets) - len(created),
            counts=GovernanceImportCounts(**counts),
        )

    def delete_draft(
        self, draft_id: str, *, expected_revision: int
    ) -> GovernanceDraft:
        draft = self._current(draft_id, expected_revision)
        if draft.status == GovernanceDraftStatus.APPROVED:
            raise ModelGovernanceGateError("已审核草稿不能删除")
        if self._storage.list_versions(draft.asset_id):
            raise ModelGovernanceGateError("已有版本的草稿不能删除")
        return self._storage.delete_draft(
            draft_id, expected_revision=expected_revision
        )

    def request_review(
        self,
        draft_id: str,
        *,
        expected_revision: int,
        actor: str,
    ) -> GovernanceDraft:
        draft = self._current(draft_id, expected_revision)
        if draft.status != GovernanceDraftStatus.VALIDATED:
            raise ModelGovernanceGateError("草稿必须先通过校验")
        return self._storage.update_draft(
            draft.model_copy(
                update={
                    "status": GovernanceDraftStatus.REVIEW_PENDING,
                    "revision": draft.revision + 1,
                    "updated_at": self._now(),
                },
                deep=True,
            ),
            expected_revision=expected_revision,
        )

    def approve(
        self,
        draft_id: str,
        *,
        expected_revision: int,
        actor: str,
        reason: str,
    ) -> GovernanceDraft:
        draft = self._current(draft_id, expected_revision)
        if draft.status != GovernanceDraftStatus.REVIEW_PENDING:
            raise ModelGovernanceGateError("草稿未提交审核")
        if actor == draft.last_edited_by:
            raise ModelGovernanceGateError("编辑人不能审核自己的内容")
        digest = content_hash(draft.content)
        approval = GovernanceApproval(
            approval_id=str(uuid5(NAMESPACE_URL, f"{draft.draft_id}:{digest}")),
            draft_id=draft.draft_id,
            asset_id=draft.asset_id,
            content_hash=digest,
            approved_by=actor,
            reason=reason,
        )
        return self._storage.approve_draft(
            draft.model_copy(
                update={
                    "status": GovernanceDraftStatus.APPROVED,
                    "revision": draft.revision + 1,
                    "updated_at": self._now(),
                },
                deep=True,
            ),
            approval,
            expected_revision=expected_revision,
        )

    def publish(
        self,
        draft_id: str,
        *,
        expected_revision: int,
        actor: str,
        environment: GovernanceEnvironment,
    ) -> GovernanceRelease:
        draft = self._current(draft_id, expected_revision)
        if draft.status != GovernanceDraftStatus.APPROVED:
            raise ModelGovernanceGateError("草稿必须先完成审核")
        if isinstance(draft.content, RouteRuleAssetContent):
            profile_ids = [draft.content.profile_id, *draft.content.fallback_profile_ids]
            if any(
                not self._profile_is_published(profile_id, environment)
                for profile_id in profile_ids
            ):
                raise ModelGovernanceGateError("路由引用的模型档案未在目标环境发布")

        digest = content_hash(draft.content)
        approval_id = str(uuid5(NAMESPACE_URL, f"{draft.draft_id}:{digest}"))
        approval = self._storage.get_approval(approval_id)
        if approval.content_hash != digest:
            raise ModelGovernanceGateError("草稿内容与审核记录不一致")
        version_id = str(uuid5(NAMESPACE_URL, f"{draft.asset_id}:{digest}"))
        active = self._storage.get_active_release(draft.asset_id, environment)
        if active and active.version_id == version_id:
            return active
        versions = self._storage.list_versions(draft.asset_id)
        version = GovernanceVersion(
            version_id=version_id,
            asset_id=draft.asset_id,
            asset_type=draft.asset_type,
            version_number=max((item.version_number for item in versions), default=0) + 1,
            content=draft.content,
            content_hash=digest,
            approval_id=approval.approval_id,
            created_by=actor,
        )
        release = GovernanceRelease(
            release_id=str(uuid4()),
            asset_id=draft.asset_id,
            asset_type=draft.asset_type,
            version_id=version_id,
            environment=environment,
            previous_release_id=active.release_id if active else None,
            created_by=actor,
        )
        published_draft = draft.model_copy(
            update={
                "revision": draft.revision + 1,
                "updated_at": self._now(),
            },
            deep=True,
        )
        return self._storage.publish_draft_version(
            published_draft,
            version,
            release,
            expected_revision=expected_revision,
        )

    def rollback(self, release_id: str, *, actor: str) -> GovernanceRelease:
        target = self._storage.get_release(release_id)
        active = self._storage.get_active_release(target.asset_id, target.environment)
        if active is None:
            raise ModelGovernanceGateError("该资产当前没有活动发布")
        if active.version_id == target.version_id:
            raise ModelGovernanceGateError("目标版本已是当前活动版本")
        return self._storage.publish(
            GovernanceRelease(
                release_id=str(uuid4()),
                asset_id=target.asset_id,
                asset_type=target.asset_type,
                version_id=target.version_id,
                environment=target.environment,
                previous_release_id=active.release_id,
                created_by=actor,
            )
        )

    def published_snapshot(
        self, environment: GovernanceEnvironment
    ) -> PublishedGovernanceSnapshot:
        releases = [
            release
            for release in self._storage.list_releases(environment=environment)
            if release.status == GovernanceReleaseStatus.ACTIVE
        ]
        assets = []
        for release in sorted(releases, key=lambda item: item.asset_id):
            version = self._storage.get_version(release.version_id)
            assets.append(
                PublishedGovernanceAsset(
                    asset_id=release.asset_id,
                    asset_type=release.asset_type,
                    version_id=version.version_id,
                    release_id=release.release_id,
                    content_hash=version.content_hash,
                    content=version.content,
                    runtime_status=GovernanceRuntimeStatus.NOT_CONNECTED,
                )
            )
        return PublishedGovernanceSnapshot(environment=environment, assets=assets)
