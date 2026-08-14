import pytest

from src.data_platform.storage.model_governance.in_memory import (
    InMemoryModelGovernanceStorage,
)
from src.model_service.governance_assets import (
    GovernanceDraftStatus,
    GovernanceEnvironment,
    GovernanceReleaseStatus,
    GovernanceRuntimeStatus,
    PromptAssetContent,
    PromptVariable,
    RouteRuleAssetContent,
)
from src.model_service.governance_service import (
    ModelGovernanceGateError,
    ModelGovernanceService,
)


def _prompt(system_prompt: str = "只输出事实") -> PromptAssetContent:
    return PromptAssetContent(
        asset_id="prompt.demo",
        name="演示提示词",
        scene="policy_qa",
        system_prompt=system_prompt,
        user_prompt_template="问题：{question}",
        variables=[PromptVariable(name="question")],
    )


def _complete_review(
    service: ModelGovernanceService, content: PromptAssetContent
):
    draft = service.create_draft(content, actor="editor")
    validated = service.validate_draft(draft.draft_id, expected_revision=draft.revision)
    pending = service.request_review(
        draft.draft_id, expected_revision=validated.revision, actor="editor"
    )
    return service.approve(
        draft.draft_id,
        expected_revision=pending.revision,
        actor="reviewer",
        reason="审核通过",
    )


def test_publish_requires_validation_and_different_reviewer():
    service = ModelGovernanceService(InMemoryModelGovernanceStorage())
    draft = service.create_draft(_prompt(), actor="editor")

    with pytest.raises(ModelGovernanceGateError, match="校验"):
        service.request_review(
            draft.draft_id, expected_revision=draft.revision, actor="editor"
        )
    validated = service.validate_draft(
        draft.draft_id, expected_revision=draft.revision
    )
    pending = service.request_review(
        draft.draft_id, expected_revision=validated.revision, actor="editor"
    )
    with pytest.raises(ModelGovernanceGateError, match="不能审核自己"):
        service.approve(
            draft.draft_id,
            expected_revision=pending.revision,
            actor="editor",
            reason="自审",
        )

    approved = service.approve(
        draft.draft_id,
        expected_revision=pending.revision,
        actor="reviewer",
        reason="通过",
    )
    release = service.publish(
        approved.draft_id,
        expected_revision=approved.revision,
        actor="editor",
        environment=GovernanceEnvironment.DEV,
    )

    assert release.status == GovernanceReleaseStatus.ACTIVE
    snapshot = service.published_snapshot(GovernanceEnvironment.DEV)
    assert snapshot.assets[0].runtime_status == GovernanceRuntimeStatus.NOT_CONNECTED
    assert snapshot.assets[0].content == _prompt()


def test_route_validation_requires_published_enabled_model_profile():
    service = ModelGovernanceService(InMemoryModelGovernanceStorage())
    route = service.create_draft(
        RouteRuleAssetContent(
            asset_id="route.demo",
            name="演示路由",
            scene="policy_qa",
            profile_id="profile.missing",
        ),
        actor="editor",
    )

    result = service.validate_draft(
        route.draft_id, expected_revision=route.revision
    )

    assert result.status == GovernanceDraftStatus.EDITING
    assert result.validation_issues[0].code == "MODEL_PROFILE_NOT_PUBLISHED"


def test_save_resets_validation_and_publish_rejects_changed_content():
    service = ModelGovernanceService(InMemoryModelGovernanceStorage())
    approved = _complete_review(service, _prompt())
    edited = service.save_draft(
        approved.draft_id,
        _prompt("只输出可追溯事实"),
        expected_revision=approved.revision,
        actor="editor",
    )

    assert edited.status == GovernanceDraftStatus.EDITING
    with pytest.raises(ModelGovernanceGateError, match="审核"):
        service.publish(
            edited.draft_id,
            expected_revision=edited.revision,
            actor="editor",
            environment=GovernanceEnvironment.DEV,
        )


def test_rollback_creates_new_release_for_immutable_old_version():
    storage = InMemoryModelGovernanceStorage()
    service = ModelGovernanceService(storage)
    first = _complete_review(service, _prompt())
    first_release = service.publish(
        first.draft_id,
        expected_revision=first.revision,
        actor="editor",
        environment=GovernanceEnvironment.DEV,
    )
    second = _complete_review(service, _prompt("仅输出可引用事实"))
    second_release = service.publish(
        second.draft_id,
        expected_revision=second.revision,
        actor="editor",
        environment=GovernanceEnvironment.DEV,
    )

    rollback = service.rollback(first_release.release_id, actor="operator")

    assert rollback.release_id not in {
        first_release.release_id,
        second_release.release_id,
    }
    assert rollback.version_id == first_release.version_id
    assert rollback.previous_release_id == second_release.release_id
    assert storage.get_active_release(
        "prompt.demo", GovernanceEnvironment.DEV
    ) == rollback

