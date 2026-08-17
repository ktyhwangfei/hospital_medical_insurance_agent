import pytest

from src.data_platform.storage.model_governance.in_memory import (
    InMemoryModelGovernanceStorage,
)
from src.model_service.governance_assets import (
    GovernanceAssetType,
    GovernanceEnvironment,
    GovernanceRelease,
    PromptAssetContent,
    PromptVariable,
)
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
