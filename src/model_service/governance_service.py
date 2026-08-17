"""提示词、模型档案与路由规则的治理生命周期。"""

from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import NAMESPACE_URL, uuid4, uuid5

from src.data_platform.storage.model_governance.ports import (
    GovernanceCredentialPrecondition,
    GovernanceReleasePrecondition,
    ModelGovernanceConflictError,
    ModelGovernanceNotFoundError,
    ModelGovernanceStorage,
)
from src.model_service.governance_assets import (
    GovernanceApproval,
    GovernanceAssetContent,
    GovernanceAssetPreview,
    GovernanceAssetType,
    GovernanceConnectionTest,
    GovernanceCredential,
    GovernanceDraft,
    GovernanceDraftStatus,
    GovernanceEnvironment,
    GovernanceImportCounts,
    GovernanceImportResult,
    GovernanceRelease,
    GovernanceReleaseCredentialBinding,
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
from src.model_service.governance_secrets import (
    GovernanceCredentialVault,
    probe_model_connection,
)


class ModelGovernanceGateError(ValueError):
    """治理生命周期前置条件未满足。"""


@dataclass(frozen=True)
class _PublishRequirements:
    credential: GovernanceCredential | None = None
    credential_precondition: GovernanceCredentialPrecondition | None = None
    referenced_releases: tuple[GovernanceReleasePrecondition, ...] = ()


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
        return self._storage.create_draft(self._new_draft(content, actor=actor))

    def create_draft_with_credential(
        self,
        content: GovernanceAssetContent,
        credential_id: str,
        api_key: str,
        *,
        actor: str,
    ) -> GovernanceDraft:
        self._require_matching_model_credential(content, credential_id)
        draft = self._new_draft(content, actor=actor)
        credential = GovernanceCredentialVault(self._storage).seal(
            credential_id,
            api_key,
            base_url=content.base_url,
            actor=actor,
        )
        return self._storage.create_draft_with_credential(draft, credential)

    def _new_draft(
        self, content: GovernanceAssetContent, *, actor: str
    ) -> GovernanceDraft:
        now = self._now()
        return GovernanceDraft(
            draft_id=str(uuid4()),
            asset_id=content.asset_id,
            asset_type=self._asset_type(content),
            content=content,
            created_by=actor,
            last_edited_by=actor,
            created_at=now,
            updated_at=now,
        )

    @staticmethod
    def _require_matching_model_credential(
        content: GovernanceAssetContent, credential_id: str
    ) -> None:
        if (
            not isinstance(content, ModelProfileAssetContent)
            or content.credential_ref != credential_id
        ):
            raise ModelGovernanceGateError("凭据必须绑定匹配的模型资产")

    def save_draft(
        self,
        draft_id: str,
        content: GovernanceAssetContent,
        *,
        expected_revision: int,
        actor: str,
    ) -> GovernanceDraft:
        draft = self._changed_draft(
            draft_id,
            content,
            expected_revision=expected_revision,
            actor=actor,
        )
        return self._storage.update_draft(
            draft,
            expected_revision=expected_revision,
        )

    def save_draft_with_credential(
        self,
        draft_id: str,
        content: GovernanceAssetContent,
        credential_id: str,
        api_key: str,
        *,
        expected_revision: int,
        actor: str,
    ) -> GovernanceDraft:
        self._require_matching_model_credential(content, credential_id)
        draft = self._changed_draft(
            draft_id,
            content,
            expected_revision=expected_revision,
            actor=actor,
        )
        credential = GovernanceCredentialVault(self._storage).seal(
            credential_id,
            api_key,
            base_url=content.base_url,
            actor=actor,
        )
        return self._storage.update_draft_with_credential(
            draft,
            credential,
            expected_revision=expected_revision,
        )

    def _changed_draft(
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
        return draft.model_copy(
            update={
                "content": content,
                "status": GovernanceDraftStatus.EDITING,
                "revision": draft.revision + 1,
                "validation_issues": [],
                "last_edited_by": actor,
                "updated_at": self._now(),
            },
            deep=True,
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

    def _active_profile_precondition(
        self,
        profile_id: str,
        environment: GovernanceEnvironment,
    ) -> GovernanceReleasePrecondition | None:
        release = self._storage.get_active_release(profile_id, environment)
        if release is None:
            return None
        content = self._storage.get_version(release.version_id).content
        if not isinstance(content, ModelProfileAssetContent) or not content.enabled:
            return None
        return GovernanceReleasePrecondition(
            asset_id=profile_id,
            environment=environment,
            expected_release_id=release.release_id,
            expected_version_id=release.version_id,
        )

    def _target_publish_requirements(
        self,
        content: GovernanceAssetContent,
        environment: GovernanceEnvironment,
        *,
        rollback_release_id: str | None = None,
    ) -> _PublishRequirements:
        if isinstance(content, ModelProfileAssetContent) and content.enabled:
            try:
                if rollback_release_id is None:
                    credential = self._storage.get_credential(content.credential_ref)
                    credential_precondition = GovernanceCredentialPrecondition(
                        credential_id=credential.credential_id,
                        expected_fingerprint=credential.secret_fingerprint,
                        expected_revision=credential.revision,
                    )
                else:
                    binding = self._storage.get_release_credential_binding(
                        rollback_release_id
                    )
                    if binding.credential_id != content.credential_ref:
                        raise ModelGovernanceNotFoundError("发布凭据绑定不匹配")
                    credential = self._storage.get_credential_revision(
                        binding.credential_id, binding.credential_revision
                    )
                    if (
                        credential.secret_fingerprint
                        != binding.credential_fingerprint
                    ):
                        raise ModelGovernanceNotFoundError("发布凭据版本不匹配")
                    credential_precondition = None
            except ModelGovernanceNotFoundError as exc:
                raise ModelGovernanceGateError(
                    "模型必须先通过当前配置的连接测试"
                ) from exc
            GovernanceCredentialVault(self._storage).reveal_credential(
                credential, base_url=content.base_url
            )
            tested = self._storage.find_successful_connection_test(
                content.asset_id,
                content_hash(content),
                credential.secret_fingerprint,
            )
            if tested is None:
                raise ModelGovernanceGateError(
                    "模型必须先通过当前配置的连接测试"
                )
            return _PublishRequirements(
                credential=credential,
                credential_precondition=credential_precondition,
            )
        if isinstance(content, RouteRuleAssetContent):
            for release in self._storage.list_releases(environment=environment):
                if (
                    release.status != GovernanceReleaseStatus.ACTIVE
                    or release.asset_type != GovernanceAssetType.ROUTE_RULE
                    or release.asset_id == content.asset_id
                ):
                    continue
                active_route = self._storage.get_version(release.version_id).content
                if (
                    isinstance(active_route, RouteRuleAssetContent)
                    and active_route.scene == content.scene
                    and active_route.model_type == content.model_type
                ):
                    raise ModelGovernanceGateError("同环境治理路由键已存在")
            referenced: list[GovernanceReleasePrecondition] = []
            for profile_id in dict.fromkeys(
                [content.profile_id, *content.fallback_profile_ids]
            ):
                precondition = self._active_profile_precondition(
                    profile_id, environment
                )
                if precondition is None:
                    raise ModelGovernanceGateError(
                        "路由引用的模型档案未在目标环境发布"
                    )
                referenced.append(precondition)
            return _PublishRequirements(referenced_releases=tuple(referenced))
        return _PublishRequirements()

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

    def record_connection_test(
        self,
        *,
        draft_id: str,
        actor: str,
        succeeded: bool,
        latency_ms: int,
        safe_message: str,
        content_digest: str | None = None,
        credential_fingerprint: str | None = None,
    ) -> GovernanceConnectionTest:
        draft = self._storage.get_draft(draft_id)
        if not isinstance(draft.content, ModelProfileAssetContent):
            raise ModelGovernanceGateError("连接测试仅支持模型草稿")
        credential = self._storage.get_credential(draft.content.credential_ref)
        return self._storage.save_connection_test(
            GovernanceConnectionTest(
                test_id=uuid4(),
                asset_id=draft.asset_id,
                content_hash=content_digest or content_hash(draft.content),
                credential_fingerprint=(
                    credential_fingerprint or credential.secret_fingerprint
                ),
                succeeded=succeeded,
                latency_ms=latency_ms,
                safe_message=safe_message,
                tested_by=actor,
            )
        )

    def test_connection(
        self, draft_id: str, *, actor: str
    ) -> GovernanceConnectionTest:
        draft = self._storage.get_draft(draft_id)
        if not isinstance(draft.content, ModelProfileAssetContent):
            raise ModelGovernanceGateError("连接测试仅支持模型草稿")
        credential = self._storage.get_credential(draft.content.credential_ref)
        api_key = GovernanceCredentialVault(self._storage).reveal_credential(
            credential, base_url=draft.content.base_url
        )
        probe = probe_model_connection(draft.content, api_key)
        return self.record_connection_test(
            draft_id=draft_id,
            actor=actor,
            succeeded=probe.succeeded,
            latency_ms=probe.latency_ms,
            safe_message=probe.safe_message,
            content_digest=content_hash(draft.content),
            credential_fingerprint=credential.secret_fingerprint,
        )

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
        for version in self._storage.list_versions(draft.asset_id):
            approval = self._storage.get_approval(version.approval_id)
            if approval.draft_id == draft.draft_id:
                raise ModelGovernanceGateError("已产出版本的草稿不能删除")
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
        digest = content_hash(draft.content)
        requirements = self._target_publish_requirements(
            draft.content, environment
        )

        approval_id = str(uuid5(NAMESPACE_URL, f"{draft.draft_id}:{digest}"))
        approval = self._storage.get_approval(approval_id)
        if approval.content_hash != digest:
            raise ModelGovernanceGateError("草稿内容与审核记录不一致")
        version_id = str(uuid5(NAMESPACE_URL, f"{draft.asset_id}:{digest}"))
        active = self._storage.get_active_release(draft.asset_id, environment)
        if active and active.version_id == version_id:
            if requirements.credential is None:
                return active
            try:
                active_binding = self._storage.get_release_credential_binding(
                    active.release_id
                )
            except ModelGovernanceNotFoundError:
                active_binding = None
            if (
                active_binding is not None
                and active_binding.credential_id
                == requirements.credential.credential_id
                and active_binding.credential_revision
                == requirements.credential.revision
                and active_binding.credential_fingerprint
                == requirements.credential.secret_fingerprint
            ):
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
        credential_binding = (
            GovernanceReleaseCredentialBinding(
                release_id=release.release_id,
                credential_id=requirements.credential.credential_id,
                credential_revision=requirements.credential.revision,
                credential_fingerprint=requirements.credential.secret_fingerprint,
            )
            if requirements.credential is not None
            else None
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
            credential_precondition=requirements.credential_precondition,
            credential_binding=credential_binding,
            referenced_release_preconditions=requirements.referenced_releases,
        )

    def rollback(self, release_id: str, *, actor: str) -> GovernanceRelease:
        target = self._storage.get_release(release_id)
        active = self._storage.get_active_release(target.asset_id, target.environment)
        if active is None:
            raise ModelGovernanceGateError("该资产当前没有活动发布")
        if active.version_id == target.version_id:
            raise ModelGovernanceGateError("目标版本已是当前活动版本")
        target_content = self._storage.get_version(target.version_id).content
        requirements = self._target_publish_requirements(
            target_content,
            target.environment,
            rollback_release_id=target.release_id,
        )
        release = GovernanceRelease(
            release_id=str(uuid4()),
            asset_id=target.asset_id,
            asset_type=target.asset_type,
            version_id=target.version_id,
            environment=target.environment,
            previous_release_id=active.release_id,
            created_by=actor,
        )
        credential_binding = (
            GovernanceReleaseCredentialBinding(
                release_id=release.release_id,
                credential_id=requirements.credential.credential_id,
                credential_revision=requirements.credential.revision,
                credential_fingerprint=requirements.credential.secret_fingerprint,
            )
            if requirements.credential is not None
            else None
        )
        return self._storage.publish(
            release,
            credential_precondition=requirements.credential_precondition,
            credential_binding=credential_binding,
            referenced_release_preconditions=requirements.referenced_releases,
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
                    runtime_status=GovernanceRuntimeStatus.GOVERNED_ACTIVE,
                )
            )
        return PublishedGovernanceSnapshot(environment=environment, assets=assets)
