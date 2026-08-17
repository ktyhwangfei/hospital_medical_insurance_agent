from threading import Event, Thread

import pytest

from src.data_platform.storage.model_governance.in_memory import (
    InMemoryModelGovernanceStorage,
)
from src.data_platform.storage.model_governance.ports import (
    ModelGovernanceConflictError,
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


def test_published_draft_is_read_only_and_next_version_copies_active_content():
    storage = InMemoryModelGovernanceStorage()
    service = ModelGovernanceService(storage)
    approved = _complete_review(service, _prompt("当前生效"))
    service.publish(
        approved.draft_id,
        expected_revision=approved.revision,
        actor="editor",
        environment=GovernanceEnvironment.DEV,
    )
    published_draft = storage.get_draft(approved.draft_id)

    with pytest.raises(ModelGovernanceGateError, match="活动版本不可编辑"):
        service.save_draft(
            approved.draft_id,
            _prompt("被直接修改"),
            expected_revision=published_draft.revision,
            actor="editor",
        )

    next_draft = service.create_next_version(
        "prompt.demo", actor="editor", environment=GovernanceEnvironment.DEV
    )
    assert next_draft.status == GovernanceDraftStatus.EDITING
    assert next_draft.content.system_prompt == "当前生效"
    assert next_draft.draft_id != approved.draft_id
    assert service.list_versions("prompt.demo")[0].version_number == 1
    edited = service.save_draft(
        next_draft.draft_id,
        _prompt("新版本可编辑"),
        expected_revision=next_draft.revision,
        actor="editor",
    )
    assert edited.content.system_prompt == "新版本可编辑"


def test_revalidating_published_draft_does_not_bypass_read_only_gate():
    storage = InMemoryModelGovernanceStorage()
    service = ModelGovernanceService(storage)
    approved = _complete_review(service, _prompt("当前生效"))
    service.publish(
        approved.draft_id,
        expected_revision=approved.revision,
        actor="editor",
        environment=GovernanceEnvironment.DEV,
    )
    revalidated = service.validate_draft(
        approved.draft_id,
        expected_revision=storage.get_draft(approved.draft_id).revision,
    )

    with pytest.raises(ModelGovernanceGateError, match="活动版本不可编辑"):
        service.save_draft(
            approved.draft_id,
            _prompt("绕过后修改"),
            expected_revision=revalidated.revision,
            actor="editor",
        )


def test_publish_revision_gate_wins_over_interleaved_save():
    class PublishDuringReleaseCheckStorage(InMemoryModelGovernanceStorage):
        publish_once = None

        def list_releases(self, asset_id=None, environment=None):
            releases = super().list_releases(asset_id, environment)
            callback, self.publish_once = self.publish_once, None
            if callback is not None:
                callback()
            return releases

    storage = PublishDuringReleaseCheckStorage()
    service = ModelGovernanceService(storage)
    approved = _complete_review(service, _prompt("当前生效"))
    storage.publish_once = lambda: service.publish(
        approved.draft_id,
        expected_revision=approved.revision,
        actor="publisher",
        environment=GovernanceEnvironment.DEV,
    )

    with pytest.raises(ModelGovernanceConflictError, match="revision"):
        service.save_draft(
            approved.draft_id,
            _prompt("并发修改"),
            expected_revision=approved.revision,
            actor="editor",
        )

    assert storage.get_active_release(
        "prompt.demo", GovernanceEnvironment.DEV
    ) is not None
    assert storage.get_draft(approved.draft_id).content.system_prompt == "当前生效"


def test_publish_is_atomic_when_save_arrives_after_old_revision_fence():
    class PausingAtomicPublishStorage(InMemoryModelGovernanceStorage):
        pause_revision = None
        paused = Event()
        resume = Event()

        def _copy(self, value):
            if self.pause_revision is not None and self.pause_revision == getattr(
                value, "revision", None
            ):
                self.pause_revision = None
                self.paused.set()
                assert self.resume.wait(2)
            return super()._copy(value)

    storage = PausingAtomicPublishStorage()
    service = ModelGovernanceService(storage)
    approved = _complete_review(service, _prompt("当前生效"))
    storage.pause_revision = approved.revision + 1
    publish_errors = []
    save_errors = []
    save_started = Event()
    save_finished = Event()

    def publish():
        try:
            service.publish(
                approved.draft_id,
                expected_revision=approved.revision,
                actor="publisher",
                environment=GovernanceEnvironment.DEV,
            )
        except Exception as exc:
            publish_errors.append(exc)

    def save():
        save_started.set()
        try:
            current = storage.get_draft(approved.draft_id)
            service.save_draft(
                approved.draft_id,
                _prompt("fence 后修改"),
                expected_revision=current.revision,
                actor="editor",
            )
        except Exception as exc:
            save_errors.append(exc)
        finally:
            save_finished.set()

    publish_thread = Thread(target=publish)
    publish_thread.start()
    assert storage.paused.wait(2)
    save_thread = Thread(target=save)
    save_thread.start()
    assert save_started.wait(2)
    assert not save_finished.wait(0.05)
    storage.resume.set()
    publish_thread.join(2)
    save_thread.join(2)

    assert not publish_thread.is_alive()
    assert not save_thread.is_alive()
    assert publish_errors == []
    assert len(save_errors) == 1
    assert isinstance(save_errors[0], ModelGovernanceGateError)
    assert storage.get_draft(approved.draft_id).content.system_prompt == "当前生效"


def test_create_next_version_requires_active_release():
    service = ModelGovernanceService(InMemoryModelGovernanceStorage())

    with pytest.raises(ModelGovernanceGateError, match="资产没有可复制的活动版本"):
        service.create_next_version(
            "prompt.demo", actor="editor", environment=GovernanceEnvironment.DEV
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


def test_import_current_assets_is_idempotent_by_asset_id():
    service = ModelGovernanceService(InMemoryModelGovernanceStorage())

    first = service.import_current_assets(actor="editor")
    second = service.import_current_assets(actor="editor")

    assert first.created_count > 0
    assert first.counts.prompt > 0
    assert first.counts.model_profile > 0
    assert first.counts.route_rule > 0
    assert second.created_count == 0
    assert second.skipped_count == first.created_count


def test_current_prompt_projection_matches_all_runtime_templates():
    from src.knowledge_extension.rule_explanation import pipeline_orchestrator
    from src.knowledge_extension.rule_explanation.policy_extract import (
        llm_enhanced_extractor,
    )
    from src.knowledge_extension.rule_explanation.policy_fact import (
        run_policy_fact_extraction,
    )
    from src.model_service.governance_import import build_current_governance_assets
    from src.runtime.intent import prompts as intent_prompts
    from src.runtime.intent.graph import prompts as discrimination_prompts
    from src.runtime.policy_qa import explanation_generator, intent_detector
    from src.semantic_layer import extraction_contract
    from src.skill_infra import unified_router
    from skills.settlement_explain_skill.strategies.pooling_self_pay import strategy

    missing = object()
    expected = {
        "intent.classify": (
            "",
            getattr(intent_prompts, "INTENT_CLASSIFICATION_PROMPT_TEMPLATE", missing),
        ),
        "intent.discriminate": (
            "",
            getattr(
                discrimination_prompts,
                "INTENT_DISCRIMINATION_PROMPT_TEMPLATE",
                missing,
            ),
        ),
        "skill.route": (
            "",
            getattr(unified_router, "SKILL_ROUTING_PROMPT_TEMPLATE", missing),
        ),
        "policy_qa.intent_detect": ("", intent_detector.INTENT_DETECTION_PROMPT),
        "policy_qa.patient_explain": (
            "",
            explanation_generator.EXPLANATION_PROMPTS["患者"],
        ),
        "policy.extract.schema": (
            "",
            getattr(
                extraction_contract,
                "SCHEMA_EXTRACTION_PROMPT_TEMPLATE",
                missing,
            ),
        ),
        "policy.extract.legacy": (
            "",
            getattr(
                pipeline_orchestrator,
                "LEGACY_FACT_EXTRACTION_PROMPT_TEMPLATE",
                missing,
            ),
        ),
        "policy.fact_extract": (
            run_policy_fact_extraction.SYSTEM_PROMPT,
            run_policy_fact_extraction.USER_PROMPT_TEMPLATE,
        ),
        "policy.synonym_discovery": (
            "",
            getattr(
                llm_enhanced_extractor,
                "SYNONYM_DISCOVERY_PROMPT_TEMPLATE",
                missing,
            ),
        ),
        "policy.domain_discovery": (
            "",
            getattr(
                llm_enhanced_extractor,
                "DOMAIN_DISCOVERY_PROMPT_TEMPLATE",
                missing,
            ),
        ),
        "skill.settlement_explain": (
            getattr(
                strategy,
                "SETTLEMENT_EXPLAIN_SYSTEM_PROMPT_TEMPLATE",
                missing,
            ),
            getattr(
                strategy,
                "SETTLEMENT_EXPLAIN_USER_PROMPT_TEMPLATE",
                missing,
            ),
        ),
    }
    prompts = {
        item.asset_id: item
        for item in build_current_governance_assets()
        if isinstance(item, PromptAssetContent)
    }

    assert missing not in {
        template for templates in expected.values() for template in templates
    }
    assert set(prompts) == set(expected)
    for asset_id, (system_prompt, user_prompt) in expected.items():
        assert prompts[asset_id].system_prompt == system_prompt
        assert prompts[asset_id].user_prompt_template == user_prompt
    assert "19 个必填字段" in prompts["policy.extract.legacy"].user_prompt_template


def test_delete_draft_allows_editing_but_rejects_approved():
    storage = InMemoryModelGovernanceStorage()
    service = ModelGovernanceService(storage)
    editing = service.create_draft(_prompt(), actor="editor")

    deleted = service.delete_draft(
        editing.draft_id, expected_revision=editing.revision
    )

    assert deleted == editing
    approved = _complete_review(service, _prompt("另一份提示词"))
    with pytest.raises(ModelGovernanceGateError, match="已审核"):
        service.delete_draft(
            approved.draft_id, expected_revision=approved.revision
        )
