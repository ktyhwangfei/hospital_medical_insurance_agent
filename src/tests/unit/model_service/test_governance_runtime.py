import pytest
from pydantic import SecretStr

from src.data_platform.storage.model_governance.in_memory import (
    InMemoryModelGovernanceStorage,
)
from src.model_service.governance_assets import (
    GovernanceAssetType,
    GovernanceEnvironment,
    GovernanceRelease,
    GovernanceReleaseStatus,
    ModelProfileAssetContent,
    PromptAssetContent,
    PromptVariable,
    RouteRuleAssetContent,
)
from src.model_service import governance_runtime
from src.model_service.governance_runtime import (
    GovernanceRuntimeError,
    current_environment,
    render_governed_prompt,
)
from src.model_service.governance_service import ModelGovernanceService


def _publish_prompt(
    storage: InMemoryModelGovernanceStorage,
    *,
    system_prompt: str,
    user_prompt: str,
) -> None:
    service = ModelGovernanceService(storage)
    draft = service.create_draft(
        PromptAssetContent(
            asset_id="prompt.demo",
            name="demo",
            scene="test",
            system_prompt=system_prompt,
            user_prompt_template=user_prompt,
            variables=[PromptVariable(name="question")],
        ),
        actor="editor",
    )
    validated = service.validate_draft(draft.draft_id, expected_revision=draft.revision)
    pending = service.request_review(
        draft.draft_id,
        expected_revision=validated.revision,
        actor="editor",
    )
    approved = service.approve(
        draft.draft_id,
        expected_revision=pending.revision,
        actor="reviewer",
        reason="test",
    )
    service.publish(
        draft.draft_id,
        expected_revision=approved.revision,
        actor="editor",
        environment=GovernanceEnvironment.DEV,
    )


def test_prompt_uses_code_fallback_until_release_then_active_version():
    storage = InMemoryModelGovernanceStorage()

    fallback = render_governed_prompt(
        "prompt.demo",
        variables={"question": "Q"},
        fallback_system="fallback system",
        fallback_user="fallback {question}",
        storage=storage,
        environment=GovernanceEnvironment.DEV,
    )
    assert fallback.rendered_system_prompt == "fallback system"
    assert fallback.rendered_user_prompt == "fallback Q"

    _publish_prompt(
        storage,
        system_prompt="active system",
        user_prompt="active {question}",
    )
    active = render_governed_prompt(
        "prompt.demo",
        variables={"question": "Q"},
        fallback_system="fallback system",
        fallback_user="fallback {question}",
        storage=storage,
        environment=GovernanceEnvironment.DEV,
    )
    assert active.rendered_system_prompt == "active system"
    assert active.rendered_user_prompt == "active Q"


def test_prompt_with_damaged_active_release_fails_closed():
    storage = InMemoryModelGovernanceStorage()
    storage.publish(
        GovernanceRelease(
            release_id="release-missing",
            asset_id="prompt.demo",
            asset_type=GovernanceAssetType.PROMPT,
            version_id="missing-version",
            environment=GovernanceEnvironment.DEV,
            created_by="test",
        )
    )

    with pytest.raises(GovernanceRuntimeError, match="prompt.demo"):
        render_governed_prompt(
            "prompt.demo",
            variables={"question": "Q"},
            fallback_system="fallback system",
            fallback_user="fallback {question}",
            storage=storage,
            environment=GovernanceEnvironment.DEV,
        )


def test_current_environment_defaults_to_dev_and_rejects_unknown(monkeypatch):
    monkeypatch.delenv("MODEL_GOVERNANCE_ENV", raising=False)
    assert current_environment() == GovernanceEnvironment.DEV

    monkeypatch.setenv("MODEL_GOVERNANCE_ENV", "prod")
    with pytest.raises(GovernanceRuntimeError, match="prod"):
        current_environment()


def _publish_model(
    storage: InMemoryModelGovernanceStorage,
    *,
    asset_id: str,
    model_name: str,
    api_key: str,
) -> None:
    service = ModelGovernanceService(storage)
    content = ModelProfileAssetContent(
        asset_id=asset_id,
        name=asset_id,
        base_url=f"https://{asset_id}.example.test/v1",
        model_name=model_name,
        credential_ref=f"credential.{asset_id}",
        timeout_seconds=17,
        temperature=0.25,
        max_tokens=777,
    )
    draft = service.create_draft_with_credential(
        content,
        content.credential_ref,
        api_key,
        actor="editor",
    )
    validated = service.validate_draft(draft.draft_id, expected_revision=draft.revision)
    pending = service.request_review(
        draft.draft_id, expected_revision=validated.revision, actor="editor"
    )
    approved = service.approve(
        draft.draft_id,
        expected_revision=pending.revision,
        actor="reviewer",
        reason="test",
    )
    service.record_connection_test(
        draft_id=draft.draft_id,
        actor="editor",
        succeeded=True,
        latency_ms=1,
        safe_message="连接成功",
    )
    service.publish(
        draft.draft_id,
        expected_revision=approved.revision,
        actor="publisher",
        environment=GovernanceEnvironment.DEV,
    )


def _publish_route(
    storage: InMemoryModelGovernanceStorage,
    *,
    profile_id: str,
    fallbacks: list[str] | None = None,
) -> None:
    service = ModelGovernanceService(storage)
    content = RouteRuleAssetContent(
        asset_id="route.demo",
        name="demo route",
        scene="policy_qa",
        model_type="llm",
        profile_id=profile_id,
        fallback_profile_ids=fallbacks or [],
    )
    draft = service.create_draft(content, actor="editor")
    validated = service.validate_draft(draft.draft_id, expected_revision=draft.revision)
    pending = service.request_review(
        draft.draft_id, expected_revision=validated.revision, actor="editor"
    )
    approved = service.approve(
        draft.draft_id,
        expected_revision=pending.revision,
        actor="reviewer",
        reason="test",
    )
    service.publish(
        draft.draft_id,
        expected_revision=approved.revision,
        actor="publisher",
        environment=GovernanceEnvironment.DEV,
    )


def test_governed_route_returns_none_without_matching_active_route(monkeypatch):
    monkeypatch.setenv(
        "MODEL_GOVERNANCE_MASTER_KEY",
        "MDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDA=",
    )
    storage = InMemoryModelGovernanceStorage()

    assert governance_runtime.resolve_governed_route(
        "policy_qa",
        "llm",
        storage=storage,
        environment=GovernanceEnvironment.DEV,
    ) is None


def test_governed_route_uses_active_model_and_bound_credential_revision(monkeypatch):
    monkeypatch.setenv(
        "MODEL_GOVERNANCE_MASTER_KEY",
        "MDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDA=",
    )
    storage = InMemoryModelGovernanceStorage()
    _publish_model(storage, asset_id="model.primary", model_name="governed-v1", api_key="sk-v1")
    _publish_route(storage, profile_id="model.primary")

    from src.model_service.governance_secrets import GovernanceCredentialVault

    GovernanceCredentialVault(storage).put(
        "credential.model.primary",
        "sk-rotated",
        base_url="https://model.primary.example.test/v1",
        actor="editor",
    )

    route = governance_runtime.resolve_governed_route(
        "policy_qa",
        "llm",
        storage=storage,
        environment=GovernanceEnvironment.DEV,
    )

    assert route is not None
    assert route.primary.model_name == "governed-v1"
    assert route.primary.api_key == SecretStr("sk-v1")
    assert route.primary.timeout_seconds == 17
    assert route.primary.temperature == 0.25
    assert route.primary.max_tokens == 777


def test_governed_route_resolves_fallback_chain(monkeypatch):
    monkeypatch.setenv(
        "MODEL_GOVERNANCE_MASTER_KEY",
        "MDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDA=",
    )
    storage = InMemoryModelGovernanceStorage()
    _publish_model(storage, asset_id="model.primary", model_name="primary", api_key="sk-primary")
    _publish_model(storage, asset_id="model.backup", model_name="backup", api_key="sk-backup")
    _publish_route(
        storage,
        profile_id="model.primary",
        fallbacks=["model.backup"],
    )

    route = governance_runtime.resolve_governed_route(
        "policy_qa",
        "llm",
        storage=storage,
        environment=GovernanceEnvironment.DEV,
    )

    assert route is not None
    assert [profile.model_name for profile in route.fallbacks] == ["backup"]


def test_governed_route_with_damaged_active_route_fails_closed(monkeypatch):
    monkeypatch.setenv(
        "MODEL_GOVERNANCE_MASTER_KEY",
        "MDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDA=",
    )
    storage = InMemoryModelGovernanceStorage()
    storage.publish(
        GovernanceRelease(
            release_id="release-broken-route",
            asset_id="route.broken",
            asset_type=GovernanceAssetType.ROUTE_RULE,
            version_id="missing-route-version",
            environment=GovernanceEnvironment.DEV,
            status=GovernanceReleaseStatus.ACTIVE,
            created_by="test",
        )
    )

    with pytest.raises(GovernanceRuntimeError, match="治理路由"):
        governance_runtime.resolve_governed_route(
            "policy_qa",
            "llm",
            storage=storage,
            environment=GovernanceEnvironment.DEV,
        )
