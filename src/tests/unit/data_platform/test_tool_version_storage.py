from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from typing import Any, Iterator

import pytest

from src.data_platform.storage.tool.in_memory import InMemoryToolVersionStorage
from src.data_platform.storage.tool.ports import ToolVersionConflictError
from src.data_platform.storage.tool.postgres import (
    TOOL_VERSION_TABLE_SCHEMA,
    PostgresToolVersionStorage,
)
from src.domain.tool.models import (
    ToolContractKind,
    ToolDefinition,
    ToolStatus,
    ToolVersion,
)


def _version(
    *,
    version_id: str = "version-1",
    semantic_version: str = "1.0.0",
    status: ToolStatus = ToolStatus.MATERIALIZED,
    name: str = "示例 Tool",
    created_at: datetime | None = None,
) -> ToolVersion:
    return ToolVersion(
        version_id=version_id,
        tool_id="demo_tool",
        semantic_version=semantic_version,
        definition=ToolDefinition(
            tool_id="demo_tool",
            name=name,
            description="用于测试的示例 Tool",
            contract_kind=ToolContractKind.FUNCTION,
            target_ref="src.runtime.policy_qa.settlement_data_provider.create_settlement_data_provider",
        ),
        status=status,
        created_by="tester",
        created_at=created_at or datetime(2026, 8, 5, tzinfo=timezone.utc),
    )


def test_tool_definition_rejects_target_ref_outside_whitelist() -> None:
    with pytest.raises(ValueError, match="白名单目录"):
        ToolDefinition(
            tool_id="demo_tool",
            name="示例 Tool",
            description="用于测试的示例 Tool",
            contract_kind=ToolContractKind.FUNCTION,
            target_ref="src.some_new_module.do_thing",
        )


def test_in_memory_version_storage_rejects_semver_collision() -> None:
    storage = InMemoryToolVersionStorage()
    storage.save_version(_version())

    with pytest.raises(ToolVersionConflictError, match="1.0.0"):
        storage.save_version(_version(version_id="version-2"))


def test_in_memory_save_version_same_id_changed_definition_raises() -> None:
    """同 version_id 重复登记但定义变化 → 显式冲突，禁止静默覆盖（漂移防护）。"""
    storage = InMemoryToolVersionStorage()
    storage.save_version(_version())

    with pytest.raises(ToolVersionConflictError, match="禁止静默"):
        storage.save_version(_version(name="改名后的 Tool"))


def test_in_memory_save_version_same_id_status_progress_allowed() -> None:
    """同 version_id 同内容重复登记幂等，且允许状态推进（draft → materialized）。"""
    storage = InMemoryToolVersionStorage()
    storage.save_version(_version(status=ToolStatus.DRAFT))

    saved = storage.save_version(_version())

    assert saved.status is ToolStatus.MATERIALIZED


def test_in_memory_version_storage_returns_newest_first_and_deep_copies() -> None:
    storage = InMemoryToolVersionStorage()
    older = _version()
    newer = _version(
        version_id="version-2",
        semantic_version="1.1.0",
        created_at=older.created_at + timedelta(minutes=1),
    )
    storage.save_version(older)
    storage.save_version(newer)

    result = storage.list_versions("demo_tool")

    assert [item.version_id for item in result] == ["version-2", "version-1"]
    assert result[0] is not newer


def test_get_latest_materialized_ignores_draft_versions() -> None:
    storage = InMemoryToolVersionStorage()
    storage.save_version(_version(status=ToolStatus.DRAFT))
    storage.save_version(
        _version(version_id="version-2", semantic_version="1.1.0", status=ToolStatus.MATERIALIZED)
    )

    latest = storage.get_latest_materialized("demo_tool")

    assert latest is not None
    assert latest.version_id == "version-2"


def test_version_storage_factory_uses_process_singleton_in_memory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.data_platform.storage.tool.factory import get_tool_version_storage

    monkeypatch.setenv("USE_MEMORY_STORAGE", "1")
    get_tool_version_storage.cache_clear()

    first = get_tool_version_storage()
    second = get_tool_version_storage()

    assert isinstance(first, InMemoryToolVersionStorage)
    assert first is second
    get_tool_version_storage.cache_clear()


def test_postgres_schema_enforces_semantic_version_uniqueness() -> None:
    normalized = " ".join(TOOL_VERSION_TABLE_SCHEMA.split()).lower()

    assert "unique(tool_id, semantic_version)" in normalized


class _FakeClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Any, ...]]] = []

    def execute(self, sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
        self.calls.append((sql, params))
        return []

    @contextmanager
    def transaction(self) -> Iterator[None]:
        yield


class _SingleRowClient:
    """模拟 tool_versions 表只有一行：SELECT 按 WHERE 条件精确匹配返回。"""

    def __init__(self, row: dict[str, Any]) -> None:
        self.row = row
        self.calls: list[tuple[str, tuple[Any, ...]]] = []

    def execute(self, sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
        self.calls.append((sql, params))
        if not sql.lstrip().lower().startswith("select"):
            return []
        if "semantic_version = %s" in sql:
            tool_id, semantic_version = params
            if self.row["tool_id"] == tool_id and self.row["semantic_version"] == semantic_version:
                return [dict(self.row)]
            return []
        if "version_id = %s" in sql:
            version_id = params[-1]
            return [dict(self.row)] if self.row["version_id"] == version_id else []
        return []

    @contextmanager
    def transaction(self) -> Iterator[None]:
        yield


def _existing_row(version: ToolVersion) -> dict[str, Any]:
    return {
        "version_id": version.version_id,
        "tool_id": version.tool_id,
        "semantic_version": version.semantic_version,
        "definition_snapshot": version.definition.model_dump(mode="json"),
        "status": version.status.value,
        "created_by": version.created_by,
        "created_at": version.created_at,
    }


def test_postgres_save_version_same_id_changed_definition_raises() -> None:
    """同 version_id 已登记但定义变化 → 显式冲突，禁止静默保留旧定义。"""
    original = _version()
    client = _SingleRowClient(_existing_row(original))
    storage = PostgresToolVersionStorage(client=client)

    with pytest.raises(ToolVersionConflictError, match="禁止静默"):
        storage.save_version(_version(name="改名后的 Tool"))


def test_postgres_save_version_same_id_changed_semver_raises() -> None:
    """同 version_id 换语义版本（旧进程代码撞 id 场景）→ 显式冲突。"""
    original = _version()
    client = _SingleRowClient(_existing_row(original))
    storage = PostgresToolVersionStorage(client=client)

    with pytest.raises(ToolVersionConflictError, match="禁止静默"):
        storage.save_version(_version(semantic_version="1.1.0"))


def test_postgres_save_version_same_content_is_idempotent() -> None:
    original = _version()
    client = _SingleRowClient(_existing_row(original))
    storage = PostgresToolVersionStorage(client=client)

    saved = storage.save_version(_version())

    assert saved.version_id == original.version_id
    assert any(sql.lstrip().lower().startswith("insert") for sql, _ in client.calls)


def test_postgres_storage_inserts_version_row() -> None:
    client = _FakeClient()
    storage = PostgresToolVersionStorage(client=client)

    storage.save_version(_version())

    statements = [" ".join(sql.split()).lower() for sql, _ in client.calls]
    assert any(sql.startswith("insert into tool_versions") for sql in statements)
