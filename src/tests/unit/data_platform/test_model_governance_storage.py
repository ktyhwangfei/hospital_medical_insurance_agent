from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

import pytest

from src.model_service.governance_assets import (
    GovernanceApproval,
    GovernanceAssetType,
    GovernanceDraft,
    GovernanceCredential,
    GovernanceConnectionTest,
    GovernanceEnvironment,
    GovernanceRelease,
    GovernanceReleaseStatus,
    GovernanceVersion,
    PromptAssetContent,
    PromptVariable,
    content_hash,
)


NOW = datetime(2026, 8, 14, tzinfo=timezone.utc)


def _content(system_prompt: str = "只输出事实") -> PromptAssetContent:
    return PromptAssetContent(
        asset_id="prompt.demo",
        name="演示提示词",
        scene="policy_qa",
        system_prompt=system_prompt,
        user_prompt_template="问题：{question}",
        variables=[PromptVariable(name="question")],
    )


def _draft(*, revision: int = 1) -> GovernanceDraft:
    content = _content()
    return GovernanceDraft(
        draft_id="draft-1",
        asset_id=content.asset_id,
        asset_type=GovernanceAssetType.PROMPT,
        content=content,
        revision=revision,
        created_by="editor",
        last_edited_by="editor",
        created_at=NOW,
        updated_at=NOW,
    )


def _version(
    version_id: str,
    number: int,
    *,
    system_prompt: str = "只输出事实",
) -> GovernanceVersion:
    content = _content(system_prompt)
    return GovernanceVersion(
        version_id=version_id,
        asset_id=content.asset_id,
        asset_type=GovernanceAssetType.PROMPT,
        version_number=number,
        content=content,
        content_hash=content_hash(content),
        approval_id=f"approval-{number}",
        created_by="editor",
        created_at=NOW + timedelta(minutes=number),
    )


def _release(
    release_id: str,
    version_id: str,
    *,
    previous_release_id: str | None = None,
) -> GovernanceRelease:
    return GovernanceRelease(
        release_id=release_id,
        asset_id="prompt.demo",
        asset_type=GovernanceAssetType.PROMPT,
        version_id=version_id,
        environment=GovernanceEnvironment.DEV,
        previous_release_id=previous_release_id,
        created_by="editor",
        created_at=NOW,
    )


def test_in_memory_storage_rejects_stale_revision_and_returns_copies():
    from src.data_platform.storage.model_governance.in_memory import (
        InMemoryModelGovernanceStorage,
    )
    from src.data_platform.storage.model_governance.ports import (
        ModelGovernanceConflictError,
    )

    storage = InMemoryModelGovernanceStorage()
    created = storage.create_draft(_draft())
    updated = storage.update_draft(
        created.model_copy(update={"revision": 2}), expected_revision=1
    )

    assert updated.revision == 2
    assert storage.get_draft(created.draft_id) is not updated
    with pytest.raises(ModelGovernanceConflictError, match="revision"):
        storage.update_draft(
            updated.model_copy(update={"revision": 3}), expected_revision=1
        )


def test_in_memory_storage_deletes_only_matching_revision():
    from src.data_platform.storage.model_governance.in_memory import (
        InMemoryModelGovernanceStorage,
    )
    from src.data_platform.storage.model_governance.ports import (
        ModelGovernanceConflictError,
        ModelGovernanceNotFoundError,
    )

    storage = InMemoryModelGovernanceStorage()
    draft = storage.create_draft(_draft())

    with pytest.raises(ModelGovernanceConflictError, match="revision"):
        storage.delete_draft(draft.draft_id, expected_revision=2)
    assert storage.delete_draft(draft.draft_id, expected_revision=1) == draft
    with pytest.raises(ModelGovernanceNotFoundError):
        storage.get_draft(draft.draft_id)


def test_in_memory_storage_versions_are_idempotent_by_asset_and_hash():
    from src.data_platform.storage.model_governance.in_memory import (
        InMemoryModelGovernanceStorage,
    )

    storage = InMemoryModelGovernanceStorage()
    first = _version("version-1", 1)

    assert storage.save_version(first) == first
    duplicate = storage.save_version(
        first.model_copy(update={"version_id": "version-duplicate"})
    )
    assert duplicate.version_id == "version-1"
    assert storage.list_versions("prompt.demo") == [first]


def test_publish_retires_previous_and_rejects_changed_baseline():
    from src.data_platform.storage.model_governance.in_memory import (
        InMemoryModelGovernanceStorage,
    )
    from src.data_platform.storage.model_governance.ports import (
        ModelGovernanceConflictError,
    )

    storage = InMemoryModelGovernanceStorage()
    first = storage.publish(_release("release-1", "version-1"))
    second = storage.publish(
        _release(
            "release-2",
            "version-2",
            previous_release_id=first.release_id,
        )
    )

    assert storage.get_active_release("prompt.demo", GovernanceEnvironment.DEV) == second
    assert storage.get_release(first.release_id).status == GovernanceReleaseStatus.RETIRED
    with pytest.raises(ModelGovernanceConflictError, match="基线"):
        storage.publish(
            _release(
                "release-3",
                "version-3",
                previous_release_id=first.release_id,
            )
        )


def test_storage_keeps_approval_and_lists_releases_newest_first():
    from src.data_platform.storage.model_governance.in_memory import (
        InMemoryModelGovernanceStorage,
    )

    storage = InMemoryModelGovernanceStorage()
    approval = GovernanceApproval(
        approval_id="approval-1",
        draft_id="draft-1",
        asset_id="prompt.demo",
        content_hash="a" * 64,
        approved_by="reviewer",
        reason="审核通过",
        approved_at=NOW,
    )
    storage.save_approval(approval)
    storage.publish(_release("release-1", "version-1"))
    storage.publish(
        _release("release-2", "version-2", previous_release_id="release-1")
    )

    assert storage.get_approval("approval-1") == approval
    assert [item.release_id for item in storage.list_releases("prompt.demo")] == [
        "release-2",
        "release-1",
    ]


def test_approval_and_draft_transition_are_atomic_on_revision_conflict():
    from src.data_platform.storage.model_governance.in_memory import (
        InMemoryModelGovernanceStorage,
    )
    from src.data_platform.storage.model_governance.ports import (
        ModelGovernanceConflictError,
        ModelGovernanceNotFoundError,
    )

    storage = InMemoryModelGovernanceStorage()
    current = storage.create_draft(_draft())
    approval = GovernanceApproval(
        approval_id="approval-atomic",
        draft_id=current.draft_id,
        asset_id=current.asset_id,
        content_hash="b" * 64,
        approved_by="reviewer",
        reason="审核通过",
        approved_at=NOW,
    )

    with pytest.raises(ModelGovernanceConflictError, match="revision"):
        storage.approve_draft(
            current.model_copy(update={"revision": 2}),
            approval,
            expected_revision=2,
        )
    with pytest.raises(ModelGovernanceNotFoundError):
        storage.get_approval(approval.approval_id)


def test_publish_draft_version_is_atomic_on_revision_conflict():
    from src.data_platform.storage.model_governance.in_memory import (
        InMemoryModelGovernanceStorage,
    )
    from src.data_platform.storage.model_governance.ports import (
        ModelGovernanceConflictError,
        ModelGovernanceNotFoundError,
    )

    storage = InMemoryModelGovernanceStorage()
    current = storage.create_draft(_draft())
    version = _version("version-1", 1)
    release = _release("release-1", version.version_id)

    with pytest.raises(ModelGovernanceConflictError, match="revision"):
        storage.publish_draft_version(
            current.model_copy(update={"revision": 2}),
            version,
            release,
            expected_revision=2,
        )

    assert storage.get_draft(current.draft_id) == current
    assert storage.list_versions(current.asset_id) == []
    with pytest.raises(ModelGovernanceNotFoundError):
        storage.get_release(release.release_id)


def test_postgres_atomic_publish_preserves_infrastructure_errors():
    from src.data_platform.storage.model_governance.postgres import (
        PostgresModelGovernanceStorage,
    )

    class FailingClient:
        is_connected = True

        @contextmanager
        def transaction(self):
            yield

        def execute(self, sql, params=()):
            raise RuntimeError("database offline")

    storage = PostgresModelGovernanceStorage("postgresql://unused")
    storage._client = FailingClient()

    with pytest.raises(RuntimeError, match="database offline"):
        storage.publish_draft_version(
            _draft(revision=2),
            _version("version-1", 1),
            _release("release-1", "version-1"),
            expected_revision=1,
        )


def test_postgres_atomic_publish_maps_constraint_errors_to_conflict():
    from src.data_platform.storage.model_governance.ports import (
        ModelGovernanceConflictError,
    )
    from src.data_platform.storage.model_governance.postgres import (
        PostgresModelGovernanceStorage,
    )

    class ConstraintError(RuntimeError):
        sqlstate = "23505"

    class FailingClient:
        is_connected = True

        @contextmanager
        def transaction(self):
            yield

        def execute(self, sql, params=()):
            raise ConstraintError("duplicate key")

    storage = PostgresModelGovernanceStorage("postgresql://unused")
    storage._client = FailingClient()

    with pytest.raises(ModelGovernanceConflictError, match="发布记录或版本已存在"):
        storage.publish_draft_version(
            _draft(revision=2),
            _version("version-1", 1),
            _release("release-1", "version-1"),
            expected_revision=1,
        )


def test_postgres_schema_has_revision_and_unique_active_release():
    from src.data_platform.storage.model_governance.postgres import (
        MODEL_GOVERNANCE_TABLE_SCHEMA,
    )

    normalized = " ".join(MODEL_GOVERNANCE_TABLE_SCHEMA.split()).lower()
    assert "model_governance_drafts" in normalized
    assert "revision integer not null" in normalized
    assert "model_governance_versions" in normalized
    assert "model_governance_approvals" in normalized
    assert "model_governance_releases" in normalized
    assert "model_governance_credentials" in normalized
    assert "model_governance_connection_tests" in normalized
    assert "idx_governance_connection_success" in normalized
    assert "where status = 'active'" in normalized


def test_in_memory_storage_keeps_credentials_and_matching_successful_tests():
    from src.data_platform.storage.model_governance.in_memory import (
        InMemoryModelGovernanceStorage,
    )

    storage = InMemoryModelGovernanceStorage()
    credential = GovernanceCredential(
        credential_id="credential.demo",
        encrypted_api_key="encrypted-value",
        secret_fingerprint="a" * 64,
        revision=1,
        updated_by="editor",
        updated_at=NOW,
    )
    failed = GovernanceConnectionTest(
        test_id="00000000-0000-0000-0000-000000000001",
        asset_id="model.demo",
        content_hash="b" * 64,
        credential_fingerprint=credential.secret_fingerprint,
        succeeded=False,
        latency_ms=10,
        safe_message="认证失败",
        tested_by="editor",
        tested_at=NOW,
    )
    succeeded = failed.model_copy(
        update={
            "test_id": "00000000-0000-0000-0000-000000000002",
            "succeeded": True,
            "safe_message": "连接成功",
            "tested_at": NOW + timedelta(seconds=1),
        }
    )

    assert storage.put_credential(credential) == credential
    assert storage.get_credential(credential.credential_id) == credential
    storage.save_connection_test(failed)
    storage.save_connection_test(succeeded)

    assert storage.find_successful_connection_test(
        "model.demo", "b" * 64, "a" * 64
    ) == succeeded
    assert storage.find_successful_connection_test(
        "model.demo", "c" * 64, "a" * 64
    ) is None


def test_in_memory_atomic_credential_update_leaves_both_records_unchanged_on_conflict():
    from src.data_platform.storage.model_governance.in_memory import (
        InMemoryModelGovernanceStorage,
    )
    from src.data_platform.storage.model_governance.ports import (
        ModelGovernanceConflictError,
    )

    storage = InMemoryModelGovernanceStorage()
    draft = storage.create_draft(_draft())
    original = GovernanceCredential(
        credential_id="credential.demo",
        encrypted_api_key="encrypted-original",
        secret_fingerprint="a" * 64,
        revision=1,
        updated_by="editor",
        updated_at=NOW,
    )
    storage.put_credential(original)
    changed_draft = draft.model_copy(
        update={"revision": 2, "content": _content("changed")}
    )
    stale_credential = original.model_copy(
        update={"encrypted_api_key": "encrypted-changed"}
    )

    with pytest.raises(ModelGovernanceConflictError, match="credential|revision|凭据"):
        storage.update_draft_with_credential(
            changed_draft,
            stale_credential,
            expected_revision=1,
        )

    assert storage.get_draft(draft.draft_id) == draft
    assert storage.get_credential(original.credential_id) == original


def test_factory_uses_explicit_memory_and_defaults_to_lazy_postgres(monkeypatch):
    from src.data_platform.storage.model_governance.factory import (
        get_model_governance_storage,
    )
    from src.data_platform.storage.model_governance.in_memory import (
        InMemoryModelGovernanceStorage,
    )
    from src.data_platform.storage.model_governance.postgres import (
        PostgresModelGovernanceStorage,
    )

    monkeypatch.setenv("USE_MEMORY_STORAGE", "1")
    get_model_governance_storage.cache_clear()
    memory = get_model_governance_storage()
    assert isinstance(memory, InMemoryModelGovernanceStorage)
    assert get_model_governance_storage() is memory

    monkeypatch.delenv("USE_MEMORY_STORAGE", raising=False)
    get_model_governance_storage.cache_clear()
    postgres = get_model_governance_storage()
    assert isinstance(postgres, PostgresModelGovernanceStorage)
    assert postgres.is_connected is False
    get_model_governance_storage.cache_clear()
