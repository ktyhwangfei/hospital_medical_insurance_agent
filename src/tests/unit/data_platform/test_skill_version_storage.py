from datetime import datetime, timedelta, timezone
from contextlib import contextmanager
from typing import Any, Iterator

import pytest

from src.data_platform.storage.skill.version_in_memory import InMemorySkillVersionStorage
from src.data_platform.storage.skill.version_ports import SkillVersionConflictError
from src.data_platform.storage.skill.version_postgres import (
    SKILL_VERSION_TABLE_SCHEMA,
    PostgresSkillVersionStorage,
)
from src.domain.skill.version_models import SkillVersion


def _version(
    artifact_hash: str = "a" * 64,
    *,
    version_id: str = "version-1",
    semantic_version: str = "1.0.0",
    created_at: datetime | None = None,
) -> SkillVersion:
    return SkillVersion(
        version_id=version_id,
        skill_id="demo_skill",
        semantic_version=semantic_version,
        source_commit="abc1234",
        source_path="demo_skill",
        artifact_hash=artifact_hash,
        manifest_snapshot={"skill_id": "demo_skill", "skill_name": "Demo Skill"},
        dependency_snapshot={"required_mcp": ["demo-server"]},
        file_count=3,
        created_by="tester",
        created_at=created_at or datetime(2026, 8, 5, tzinfo=timezone.utc),
    )


def test_in_memory_version_storage_is_idempotent_by_artifact() -> None:
    storage = InMemorySkillVersionStorage()
    version = _version()

    assert storage.save_version(version) == version
    assert storage.save_version(version.model_copy(update={"version_id": "other"})) == version
    assert storage.list_versions("demo_skill") == [version]


def test_in_memory_version_storage_rejects_semver_collision() -> None:
    storage = InMemorySkillVersionStorage()
    storage.save_version(_version())

    with pytest.raises(SkillVersionConflictError, match="1.0.0"):
        storage.save_version(_version("b" * 64, version_id="version-2"))


def test_in_memory_version_storage_returns_newest_first_and_deep_copies() -> None:
    storage = InMemorySkillVersionStorage()
    older = _version()
    newer = _version(
        "b" * 64,
        version_id="version-2",
        semantic_version="1.1.0",
        created_at=older.created_at + timedelta(minutes=1),
    )
    storage.save_version(older)
    storage.save_version(newer)

    result = storage.list_versions("demo_skill")

    assert [item.version_id for item in result] == ["version-2", "version-1"]
    assert result[0] is not newer
    assert storage.get_version("demo_skill", "version-2") is not newer


def test_postgres_schema_enforces_version_and_artifact_uniqueness() -> None:
    normalized = " ".join(SKILL_VERSION_TABLE_SCHEMA.split()).lower()

    assert "references skills(skill_id)" in normalized
    assert "unique(skill_id, semantic_version)" in normalized
    assert "unique(skill_id, artifact_hash)" in normalized


class _FakeClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Any, ...]]] = []

    def execute(self, sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
        self.calls.append((sql, params))
        return []

    @contextmanager
    def transaction(self) -> Iterator[None]:
        yield


def test_postgres_storage_creates_parent_identity_before_version() -> None:
    client = _FakeClient()
    storage = PostgresSkillVersionStorage(client=client)

    storage.save_version(_version())

    statements = [" ".join(sql.split()).lower() for sql, _ in client.calls]
    parent_index = next(i for i, sql in enumerate(statements) if sql.startswith("insert into skills"))
    version_index = next(i for i, sql in enumerate(statements) if sql.startswith("insert into skill_versions"))
    assert parent_index < version_index
    parent_sql, parent_params = client.calls[parent_index]
    assert "risk_level" in parent_sql.lower()
    assert parent_params[4] == "low"


def test_version_storage_factory_uses_process_singleton_in_memory(monkeypatch: pytest.MonkeyPatch) -> None:
    from src.data_platform.storage.skill.version_factory import get_skill_version_storage

    monkeypatch.setenv("USE_MEMORY_STORAGE", "1")
    get_skill_version_storage.cache_clear()

    first = get_skill_version_storage()
    second = get_skill_version_storage()

    assert isinstance(first, InMemorySkillVersionStorage)
    assert first is second
    get_skill_version_storage.cache_clear()
