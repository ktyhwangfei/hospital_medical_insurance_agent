from threading import Event, Thread

import pytest

from src.data_platform.storage.model_governance.in_memory import (
    InMemoryModelGovernanceStorage,
)
from src.data_platform.storage.model_governance.ports import (
    ModelGovernanceConflictError,
)
from src.model_service.governance_assets import (
    GovernanceAssetContent,
    GovernanceDraftStatus,
    GovernanceEnvironment,
    GovernanceRelease,
    GovernanceReleaseStatus,
    GovernanceRuntimeStatus,
    GovernanceVersion,
    ModelProfileAssetContent,
    PromptAssetContent,
    PromptVariable,
    RouteRuleAssetContent,
    content_hash,
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


def _complete_review(service: ModelGovernanceService, content: GovernanceAssetContent):
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


def _model_profile(**changes) -> ModelProfileAssetContent:
    values = {
        "asset_id": "model.demo",
        "name": "演示模型",
        "base_url": "https://models.example.test/v1",
        "model_name": "demo-model",
        "credential_ref": "credential.demo",
        "temperature": 0.2,
        "max_tokens": 1024,
    }
    values.update(changes)
    return ModelProfileAssetContent(**values)


def _approved_model(service: ModelGovernanceService, content: ModelProfileAssetContent):
    draft = service.create_draft_with_credential(
        content,
        content.credential_ref,
        "sk-current",
        actor="editor",
    )
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


def test_connection_test_never_sends_credential_to_unapproved_endpoint(monkeypatch):
    monkeypatch.setenv(
        "MODEL_GOVERNANCE_MASTER_KEY",
        "MDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDA=",
    )
    storage = InMemoryModelGovernanceStorage()
    service = ModelGovernanceService(storage)
    _approved_model(service, _model_profile())
    attack = service.create_draft(
        _model_profile(
            asset_id="model.attack",
            name="攻击草稿",
            base_url="https://collector.attacker.test/v1",
        ),
        actor="attacker",
    )
    calls = []

    class SpyProvider:
        def __init__(self, base_url, api_key, *, timeout):
            calls.append((base_url, api_key, timeout))

        def invoke(self, request):
            raise AssertionError("不应向未授权端点发送凭据")

    monkeypatch.setattr(
        "src.model_service.governance_secrets.OpenAICompatibleProvider", SpyProvider
    )
    from src.model_service.governance_secrets import GovernanceSecretError

    with pytest.raises(GovernanceSecretError, match="端点"):
        service.test_connection(attack.draft_id, actor="attacker")
    assert calls == []


def test_probe_rejects_empty_model_response(monkeypatch):
    from src.model_service.governance_secrets import probe_model_connection
    from src.model_service.models import ModelResponse, TokenUsage

    monkeypatch.setattr(
        "src.model_service.governance_secrets.OpenAICompatibleProvider.invoke",
        lambda self, request: ModelResponse(
            content="",
            model_name=request.model_type,
            usage=TokenUsage(prompt_tokens=1, completion_tokens=0),
            finish_reason="stop",
        ),
    )

    result = probe_model_connection(_model_profile(), "sk-test")

    assert result.succeeded is False
    assert result.safe_message == "连接失败"


def test_probe_rejects_error_shaped_http_200(monkeypatch):
    from src.model_service.governance_secrets import probe_model_connection

    class ErrorResponse:
        status_code = 200
        text = '{"error":{"message":"invalid key"}}'

        @staticmethod
        def json():
            return {"error": {"message": "invalid key"}}

    class FakeClient:
        def __init__(self, *, timeout):
            self.timeout = timeout

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def post(self, *args, **kwargs):
            return ErrorResponse()

    monkeypatch.setattr("src.model_service.providers.openai_compatible.httpx.Client", FakeClient)

    result = probe_model_connection(_model_profile(), "sk-test")

    assert result.succeeded is False
    assert result.safe_message == "连接失败"


def test_probe_rejects_unknown_http_200_payload(monkeypatch):
    from src.model_service.governance_secrets import probe_model_connection

    class UnknownResponse:
        status_code = 200
        text = '{"message":"invalid api key"}'

        @staticmethod
        def json():
            return {"message": "invalid api key"}

    class FakeClient:
        def __init__(self, *, timeout):
            self.timeout = timeout

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def post(self, *args, **kwargs):
            return UnknownResponse()

    monkeypatch.setattr("src.model_service.providers.openai_compatible.httpx.Client", FakeClient)

    result = probe_model_connection(_model_profile(), "sk-test")

    assert result.succeeded is False
    assert result.safe_message == "连接失败"


def test_model_publish_requires_matching_successful_connection_test(monkeypatch):
    monkeypatch.setenv(
        "MODEL_GOVERNANCE_MASTER_KEY",
        "MDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDA=",
    )
    storage = InMemoryModelGovernanceStorage()
    service = ModelGovernanceService(storage)
    approved = _approved_model(service, _model_profile())

    with pytest.raises(ModelGovernanceGateError, match="连接测试"):
        service.publish(
            approved.draft_id,
            expected_revision=approved.revision,
            actor="publisher",
            environment=GovernanceEnvironment.DEV,
        )

    failed = service.record_connection_test(
        draft_id=approved.draft_id,
        actor="editor",
        succeeded=False,
        latency_ms=12,
        safe_message="认证失败",
    )
    assert failed.succeeded is False
    with pytest.raises(ModelGovernanceGateError, match="连接测试"):
        service.publish(
            approved.draft_id,
            expected_revision=approved.revision,
            actor="publisher",
            environment=GovernanceEnvironment.DEV,
        )

    tested = service.record_connection_test(
        draft_id=approved.draft_id,
        actor="editor",
        succeeded=True,
        latency_ms=9,
        safe_message="连接成功",
    )
    assert tested.content_hash == content_hash(approved.content)
    assert tested.credential_fingerprint == storage.get_credential(
        approved.content.credential_ref
    ).secret_fingerprint

    release = service.publish(
        approved.draft_id,
        expected_revision=approved.revision,
        actor="publisher",
        environment=GovernanceEnvironment.DEV,
    )
    assert release.status == GovernanceReleaseStatus.ACTIVE


@pytest.mark.parametrize(
    "change",
    [
        {"base_url": "https://other.example.test/v1"},
        {"model_name": "other-model"},
    ],
)
def test_model_content_change_invalidates_connection_test(monkeypatch, change):
    monkeypatch.setenv(
        "MODEL_GOVERNANCE_MASTER_KEY",
        "MDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDA=",
    )
    service = ModelGovernanceService(InMemoryModelGovernanceStorage())
    approved = _approved_model(service, _model_profile())
    service.record_connection_test(
        draft_id=approved.draft_id,
        actor="editor",
        succeeded=True,
        latency_ms=8,
        safe_message="连接成功",
    )
    edited = service.save_draft(
        approved.draft_id,
        approved.content.model_copy(update=change),
        expected_revision=approved.revision,
        actor="editor",
    )
    validated = service.validate_draft(edited.draft_id, expected_revision=edited.revision)
    pending = service.request_review(
        edited.draft_id, expected_revision=validated.revision, actor="editor"
    )
    reapproved = service.approve(
        edited.draft_id,
        expected_revision=pending.revision,
        actor="reviewer",
        reason="再次审核",
    )

    from src.model_service.governance_secrets import GovernanceSecretError

    expected_error = GovernanceSecretError if "base_url" in change else ModelGovernanceGateError
    expected_message = "端点" if "base_url" in change else "连接测试"
    with pytest.raises(expected_error, match=expected_message):
        service.publish(
            reapproved.draft_id,
            expected_revision=reapproved.revision,
            actor="publisher",
            environment=GovernanceEnvironment.DEV,
        )


def test_model_secret_change_invalidates_connection_test(monkeypatch):
    monkeypatch.setenv(
        "MODEL_GOVERNANCE_MASTER_KEY",
        "MDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDA=",
    )
    storage = InMemoryModelGovernanceStorage()
    service = ModelGovernanceService(storage)
    approved = _approved_model(service, _model_profile())
    service.record_connection_test(
        draft_id=approved.draft_id,
        actor="editor",
        succeeded=True,
        latency_ms=8,
        safe_message="连接成功",
    )
    from src.model_service.governance_secrets import GovernanceCredentialVault

    GovernanceCredentialVault(storage).put(
        approved.content.credential_ref,
        "sk-replaced",
        base_url=approved.content.base_url,
        actor="editor",
    )

    with pytest.raises(ModelGovernanceGateError, match="连接测试"):
        service.publish(
            approved.draft_id,
            expected_revision=approved.revision,
            actor="publisher",
            environment=GovernanceEnvironment.DEV,
        )


def test_model_publish_rejects_key_rotated_after_gate_before_atomic_commit(
    monkeypatch,
):
    monkeypatch.setenv(
        "MODEL_GOVERNANCE_MASTER_KEY",
        "MDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDA=",
    )

    class RotateBeforeCommitStorage(InMemoryModelGovernanceStorage):
        rotate_once = None

        def publish_draft_version(self, *args, **kwargs):
            callback, self.rotate_once = self.rotate_once, None
            if callback is not None:
                callback()
            return super().publish_draft_version(*args, **kwargs)

    storage = RotateBeforeCommitStorage()
    service = ModelGovernanceService(storage)
    approved = _approved_model(service, _model_profile())
    service.record_connection_test(
        draft_id=approved.draft_id,
        actor="editor",
        succeeded=True,
        latency_ms=8,
        safe_message="连接成功",
    )
    from src.model_service.governance_secrets import GovernanceCredentialVault

    storage.rotate_once = lambda: GovernanceCredentialVault(storage).put(
        "credential.demo",
        "sk-raced",
        base_url=approved.content.base_url,
        actor="editor",
    )

    with pytest.raises(ModelGovernanceConflictError, match="凭据"):
        service.publish(
            approved.draft_id,
            expected_revision=approved.revision,
            actor="publisher",
            environment=GovernanceEnvironment.DEV,
        )
    assert storage.get_active_release(
        approved.asset_id, GovernanceEnvironment.DEV
    ) is None


def test_model_release_keeps_tested_credential_revision_after_rotation(monkeypatch):
    monkeypatch.setenv(
        "MODEL_GOVERNANCE_MASTER_KEY",
        "MDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDA=",
    )
    storage = InMemoryModelGovernanceStorage()
    service = ModelGovernanceService(storage)
    approved = _approved_model(service, _model_profile())
    service.record_connection_test(
        draft_id=approved.draft_id,
        actor="editor",
        succeeded=True,
        latency_ms=8,
        safe_message="连接成功",
    )
    release = service.publish(
        approved.draft_id,
        expected_revision=approved.revision,
        actor="publisher",
        environment=GovernanceEnvironment.DEV,
    )
    from src.model_service.governance_secrets import GovernanceCredentialVault

    vault = GovernanceCredentialVault(storage)
    vault.put(
        "credential.demo",
        "sk-rotated-without-test",
        base_url=approved.content.base_url,
        actor="editor",
    )

    binding = storage.get_release_credential_binding(release.release_id)
    historical = storage.get_credential_revision(
        binding.credential_id, binding.credential_revision
    )
    assert binding.credential_fingerprint == historical.secret_fingerprint
    assert vault.reveal_credential(
        historical, base_url=approved.content.base_url
    ) == "sk-current"
    assert "encrypted_api_key" not in binding.model_dump_json()


def test_same_content_credential_release_records_new_source_draft(monkeypatch):
    monkeypatch.setenv(
        "MODEL_GOVERNANCE_MASTER_KEY",
        "MDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDA=",
    )
    storage = InMemoryModelGovernanceStorage()
    service = ModelGovernanceService(storage)
    first = _approved_model(service, _model_profile())
    service.record_connection_test(
        draft_id=first.draft_id,
        actor="editor",
        succeeded=True,
        latency_ms=8,
        safe_message="连接成功",
    )
    first_release = service.publish(
        first.draft_id,
        expected_revision=first.revision,
        actor="publisher",
        environment=GovernanceEnvironment.DEV,
    )

    second_draft = service.create_draft_with_credential(
        first.content,
        first.content.credential_ref,
        "sk-next",
        actor="editor",
    )
    validated = service.validate_draft(
        second_draft.draft_id, expected_revision=second_draft.revision
    )
    pending = service.request_review(
        second_draft.draft_id,
        expected_revision=validated.revision,
        actor="editor",
    )
    approved = service.approve(
        second_draft.draft_id,
        expected_revision=pending.revision,
        actor="reviewer",
        reason="换用新凭据",
    )
    service.record_connection_test(
        draft_id=approved.draft_id,
        actor="editor",
        succeeded=True,
        latency_ms=7,
        safe_message="连接成功",
    )
    second_release = service.publish(
        approved.draft_id,
        expected_revision=approved.revision,
        actor="publisher",
        environment=GovernanceEnvironment.DEV,
    )

    assert second_release.version_id == first_release.version_id
    assert first_release.source_draft_id == first.draft_id
    assert second_release.source_draft_id == approved.draft_id


def test_disabled_model_can_publish_without_connection_test(monkeypatch):
    monkeypatch.setenv(
        "MODEL_GOVERNANCE_MASTER_KEY",
        "MDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDA=",
    )
    service = ModelGovernanceService(InMemoryModelGovernanceStorage())
    approved = _approved_model(service, _model_profile(enabled=False))

    release = service.publish(
        approved.draft_id,
        expected_revision=approved.revision,
        actor="publisher",
        environment=GovernanceEnvironment.DEV,
    )
    assert release.status == GovernanceReleaseStatus.ACTIVE


def test_model_publish_fails_closed_when_master_key_cannot_decrypt(monkeypatch):
    monkeypatch.setenv(
        "MODEL_GOVERNANCE_MASTER_KEY",
        "MDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDA=",
    )
    service = ModelGovernanceService(InMemoryModelGovernanceStorage())
    approved = _approved_model(service, _model_profile())
    service.record_connection_test(
        draft_id=approved.draft_id,
        actor="editor",
        succeeded=True,
        latency_ms=8,
        safe_message="连接成功",
    )
    monkeypatch.setenv("MODEL_GOVERNANCE_MASTER_KEY", "invalid-key")
    from src.model_service.governance_secrets import GovernanceSecretError

    with pytest.raises(GovernanceSecretError):
        service.publish(
            approved.draft_id,
            expected_revision=approved.revision,
            actor="publisher",
            environment=GovernanceEnvironment.DEV,
        )


def _seed_version(
    storage: InMemoryModelGovernanceStorage,
    content: GovernanceAssetContent,
    *,
    number: int,
) -> GovernanceVersion:
    version = GovernanceVersion(
        version_id=f"version-{content.asset_id}-{number}",
        asset_id=content.asset_id,
        asset_type=content.asset_type,
        version_number=number,
        content=content,
        content_hash=content_hash(content),
        approval_id=f"approval-{content.asset_id}-{number}",
        created_by="publisher",
    )
    return storage.save_version(version)


def _seed_release(
    storage: InMemoryModelGovernanceStorage,
    version: GovernanceVersion,
    *,
    previous_release_id: str | None = None,
) -> GovernanceRelease:
    return storage.publish(
        GovernanceRelease(
            release_id=f"release-{version.version_id}",
            asset_id=version.asset_id,
            asset_type=version.asset_type,
            version_id=version.version_id,
            environment=GovernanceEnvironment.DEV,
            previous_release_id=previous_release_id,
            created_by="publisher",
        )
    )


def test_rollback_enabled_model_uses_target_release_credential_binding(monkeypatch):
    monkeypatch.setenv(
        "MODEL_GOVERNANCE_MASTER_KEY",
        "MDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDA=",
    )
    storage = InMemoryModelGovernanceStorage()
    service = ModelGovernanceService(storage)
    approved = _approved_model(service, _model_profile())
    service.record_connection_test(
        draft_id=approved.draft_id,
        actor="editor",
        succeeded=True,
        latency_ms=7,
        safe_message="连接成功",
    )
    target_release = service.publish(
        approved.draft_id,
        expected_revision=approved.revision,
        actor="publisher",
        environment=GovernanceEnvironment.DEV,
    )
    disabled = _complete_review(service, _model_profile(enabled=False))
    service.publish(
        disabled.draft_id,
        expected_revision=disabled.revision,
        actor="publisher",
        environment=GovernanceEnvironment.DEV,
    )
    from src.model_service.governance_secrets import GovernanceCredentialVault

    GovernanceCredentialVault(storage).put(
        "credential.demo",
        "sk-new-untested",
        base_url=approved.content.base_url,
        actor="editor",
    )

    rollback = service.rollback(target_release.release_id, actor="publisher")

    assert storage.get_release_credential_binding(
        rollback.release_id
    ).model_dump(exclude={"release_id"}) == storage.get_release_credential_binding(
        target_release.release_id
    ).model_dump(exclude={"release_id"})


def test_rollback_route_rechecks_enabled_models_in_target_environment():
    storage = InMemoryModelGovernanceStorage()
    service = ModelGovernanceService(storage)
    disabled_model = _model_profile(enabled=False)
    model_version = _seed_version(storage, disabled_model, number=1)
    _seed_release(storage, model_version)
    target_route = RouteRuleAssetContent(
        asset_id="route.demo",
        name="旧路由",
        scene="policy_qa",
        profile_id=disabled_model.asset_id,
    )
    target_version = _seed_version(storage, target_route, number=1)
    target_release = _seed_release(storage, target_version)
    active_version = _seed_version(
        storage,
        target_route.model_copy(update={"name": "当前路由"}),
        number=2,
    )
    _seed_release(
        storage,
        active_version,
        previous_release_id=target_release.release_id,
    )

    with pytest.raises(ModelGovernanceGateError, match="未在目标环境发布"):
        service.rollback(target_release.release_id, actor="publisher")


def test_route_publish_rejects_referenced_model_changed_after_gate(monkeypatch):
    monkeypatch.setenv(
        "MODEL_GOVERNANCE_MASTER_KEY",
        "MDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDA=",
    )

    class ChangeModelBeforeCommitStorage(InMemoryModelGovernanceStorage):
        change_once = None

        def publish_draft_version(self, *args, **kwargs):
            callback, self.change_once = self.change_once, None
            if callback is not None:
                callback()
            return super().publish_draft_version(*args, **kwargs)

    storage = ChangeModelBeforeCommitStorage()
    service = ModelGovernanceService(storage)
    model = _approved_model(service, _model_profile())
    service.record_connection_test(
        draft_id=model.draft_id,
        actor="editor",
        succeeded=True,
        latency_ms=5,
        safe_message="连接成功",
    )
    model_release = service.publish(
        model.draft_id,
        expected_revision=model.revision,
        actor="publisher",
        environment=GovernanceEnvironment.DEV,
    )
    route = _complete_review(
        service,
        RouteRuleAssetContent(
            asset_id="route.race",
            name="竞态路由",
            scene="policy_qa",
            profile_id=model.asset_id,
        ),
    )
    disabled_version = _seed_version(
        storage, _model_profile(enabled=False), number=2
    )
    storage.change_once = lambda: super(
        ChangeModelBeforeCommitStorage, storage
    ).publish(
        GovernanceRelease(
            release_id="release-disabled-race",
            asset_id=model.asset_id,
            asset_type=model.asset_type,
            version_id=disabled_version.version_id,
            environment=GovernanceEnvironment.DEV,
            previous_release_id=model_release.release_id,
            created_by="attacker",
        )
    )

    with pytest.raises(ModelGovernanceConflictError, match="引用的模型"):
        service.publish(
            route.draft_id,
            expected_revision=route.revision,
            actor="publisher",
            environment=GovernanceEnvironment.DEV,
        )
    assert storage.get_active_release("route.race", GovernanceEnvironment.DEV) is None


def test_route_rollback_rejects_referenced_model_changed_after_gate(monkeypatch):
    monkeypatch.setenv(
        "MODEL_GOVERNANCE_MASTER_KEY",
        "MDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDA=",
    )

    class ChangeModelBeforeRollbackStorage(InMemoryModelGovernanceStorage):
        change_once = None

        def publish(self, *args, **kwargs):
            callback, self.change_once = self.change_once, None
            if callback is not None:
                callback()
            return super().publish(*args, **kwargs)

    storage = ChangeModelBeforeRollbackStorage()
    service = ModelGovernanceService(storage)
    model = _approved_model(service, _model_profile())
    service.record_connection_test(
        draft_id=model.draft_id,
        actor="editor",
        succeeded=True,
        latency_ms=5,
        safe_message="连接成功",
    )
    model_release = service.publish(
        model.draft_id,
        expected_revision=model.revision,
        actor="publisher",
        environment=GovernanceEnvironment.DEV,
    )
    route_content = RouteRuleAssetContent(
        asset_id="route.rollback-race",
        name="旧路由",
        scene="policy_qa",
        profile_id=model.asset_id,
    )
    first = _complete_review(service, route_content)
    first_release = service.publish(
        first.draft_id,
        expected_revision=first.revision,
        actor="publisher",
        environment=GovernanceEnvironment.DEV,
    )
    second = _complete_review(
        service, route_content.model_copy(update={"name": "当前路由"})
    )
    service.publish(
        second.draft_id,
        expected_revision=second.revision,
        actor="publisher",
        environment=GovernanceEnvironment.DEV,
    )
    disabled_version = _seed_version(
        storage, _model_profile(enabled=False), number=2
    )
    storage.change_once = lambda: super(
        ChangeModelBeforeRollbackStorage, storage
    ).publish(
        GovernanceRelease(
            release_id="release-disabled-rollback-race",
            asset_id=model.asset_id,
            asset_type=model.asset_type,
            version_id=disabled_version.version_id,
            environment=GovernanceEnvironment.DEV,
            previous_release_id=model_release.release_id,
            created_by="attacker",
        )
    )

    with pytest.raises(ModelGovernanceConflictError, match="引用的模型"):
        service.rollback(first_release.release_id, actor="publisher")


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
    assert snapshot.assets[0].runtime_status == GovernanceRuntimeStatus.GOVERNED_ACTIVE
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


def test_storage_rejects_duplicate_active_route_key():
    storage = InMemoryModelGovernanceStorage()
    first = _seed_version(
        storage,
        RouteRuleAssetContent(
            asset_id="route.first",
            name="first",
            scene="policy_qa",
            profile_id="model.demo",
        ),
        number=1,
    )
    second = _seed_version(
        storage,
        RouteRuleAssetContent(
            asset_id="route.second",
            name="second",
            scene="policy_qa",
            profile_id="model.demo",
        ),
        number=1,
    )
    _seed_release(storage, first)

    with pytest.raises(ModelGovernanceConflictError, match="路由"):
        _seed_release(storage, second)


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
    from src.model_service.governance_assets import _prompt_fields
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
            *strategy.load_settlement_explain_prompt_templates(),
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
    # 声明的变量必须覆盖模板全部占位符，防止 UNDECLARED_TEMPLATE_VARIABLE 回归
    for item in prompts.values():
        fields, issues = _prompt_fields(
            f"{item.system_prompt}\n{item.user_prompt_template}"
        )
        assert not issues, f"{item.asset_id} 模板含不安全字段: {issues}"
        declared = {variable.name for variable in item.variables}
        assert fields <= declared, (
            f"{item.asset_id} 模板占位符 {sorted(fields - declared)} 未声明"
        )


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
