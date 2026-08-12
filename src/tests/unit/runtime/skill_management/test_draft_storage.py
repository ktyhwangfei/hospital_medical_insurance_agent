"""Skill 草稿与定义存储单元测试。

分层：
- 内存实现：完整契约测试（CRUD、乐观锁、软删、唯一性、深拷贝）。
- PostgreSQL 实现：用 FakeClient 验证生成的 SQL/参数正确性（单元层）。
  真实 PG 端到端验证在 Flow 层（参照 ``test_skill_version_storage`` 模式）。
"""

from __future__ import annotations

import time
from contextlib import contextmanager
from typing import Any, Callable, Iterator

import pytest

from src.data_platform.storage.skill.draft_ports import (
    SkillDefinitionConflictError,
    SkillDefinitionNotFoundError,
    SkillDraftConflictError,
    SkillDraftNotFoundError,
)
from src.domain.skill.draft_models import (
    SkillDefinition,
    SkillDraft,
    SkillDraftSourceType,
    SkillDraftStatus,
    SkillLifecycleStatus,
)


def _make_draft(
    draft_id: str = "draft-1",
    *,
    skill_id: str = "demo_skill",
    skill_name: str = "Demo Skill",
    source_type: SkillDraftSourceType = SkillDraftSourceType.TEMPLATE,
    source_skill_id: str | None = None,
    revision: int = 1,
    status: SkillDraftStatus = SkillDraftStatus.EDITING,
    structured_config: dict | None = None,
    raw_files: dict | None = None,
    validation_report: dict | None = None,
    created_by: str = "u-admin",
) -> SkillDraft:
    return SkillDraft(
        draft_id=draft_id,
        skill_id=skill_id,
        skill_name=skill_name,
        source_type=source_type,
        source_skill_id=source_skill_id,
        structured_config=structured_config or {"basic": {"name": skill_name}},
        raw_files=raw_files or {},
        validation_report=validation_report,
        revision=revision,
        status=status,
        created_by=created_by,
    )


def _make_definition(
    skill_id: str = "demo_skill",
    *,
    revision: int = 1,
    lifecycle_status: SkillLifecycleStatus = SkillLifecycleStatus.ENABLED,
    business_action: str = "explain",
    business_object: str = "settlement",
) -> SkillDefinition:
    return SkillDefinition(
        skill_id=skill_id,
        skill_name=f"{skill_id} name",
        business_action=business_action,
        business_object=business_object,
        lifecycle_status=lifecycle_status,
        revision=revision,
    )


# ────────────────────────────────────────────────────────────────────
# SkillDraft 存储契约（子类提供 make_storage fixture）
# ────────────────────────────────────────────────────────────────────


class SkillDraftStorageContract:
    def test_save_and_get_draft(self, make_storage: Callable):
        storage = make_storage()
        saved = storage.save_draft(_make_draft())
        assert saved.draft_id == "draft-1"
        got = storage.get_draft("draft-1")
        assert got == saved
        got.structured_config["injected"] = True  # type: ignore[index]
        assert "injected" not in storage.get_draft("draft-1").structured_config

    def test_save_duplicate_draft_id_conflicts(self, make_storage: Callable):
        storage = make_storage()
        storage.save_draft(_make_draft())
        with pytest.raises(SkillDraftConflictError):
            storage.save_draft(_make_draft())

    def test_update_draft_optimistic_lock(self, make_storage: Callable):
        storage = make_storage()
        storage.save_draft(_make_draft(revision=1))
        result = storage.update_draft(
            _make_draft(
                revision=2,
                structured_config={"basic": {"name": "Renamed"}},
                status=SkillDraftStatus.VALIDATED,
            ),
            expected_revision=1,
        )
        assert result.revision == 2
        assert result.status == SkillDraftStatus.VALIDATED
        assert storage.get_draft("draft-1").revision == 2

    def test_update_draft_stale_revision_conflicts(self, make_storage: Callable):
        storage = make_storage()
        storage.save_draft(_make_draft(revision=1))
        storage.update_draft(_make_draft(revision=2), expected_revision=1)
        with pytest.raises(SkillDraftConflictError):
            storage.update_draft(_make_draft(revision=3), expected_revision=1)

    def test_update_draft_wrong_revision_increment_conflicts(self, make_storage: Callable):
        storage = make_storage()
        storage.save_draft(_make_draft(revision=1))
        with pytest.raises(SkillDraftConflictError):
            storage.update_draft(_make_draft(revision=5), expected_revision=1)

    def test_update_missing_draft_not_found(self, make_storage: Callable):
        storage = make_storage()
        with pytest.raises(SkillDraftNotFoundError):
            storage.update_draft(_make_draft(), expected_revision=1)

    def test_list_drafts_excludes_deleted_by_default(self, make_storage: Callable):
        storage = make_storage()
        storage.save_draft(_make_draft("draft-a", skill_id="a_skill"))
        storage.save_draft(_make_draft("draft-b", skill_id="b_skill"))
        storage.delete_draft("draft-a", expected_revision=1)
        ids = {d.draft_id for d in storage.list_drafts()}
        assert ids == {"draft-b"}
        assert {d.draft_id for d in storage.list_drafts(include_deleted=True)} == {
            "draft-a",
            "draft-b",
        }

    def test_list_drafts_filters_by_skill_and_status(self, make_storage: Callable):
        storage = make_storage()
        storage.save_draft(_make_draft("d1", skill_id="s1", status=SkillDraftStatus.EDITING))
        storage.save_draft(_make_draft("d2", skill_id="s1", status=SkillDraftStatus.VALIDATED))
        storage.save_draft(_make_draft("d3", skill_id="s2", status=SkillDraftStatus.EDITING))
        assert {d.draft_id for d in storage.list_drafts(skill_id="s1")} == {"d1", "d2"}
        assert {d.draft_id for d in storage.list_drafts(status=SkillDraftStatus.VALIDATED)} == {
            "d2"
        }

    def test_list_drafts_ordered_by_updated_at_desc(self, make_storage: Callable):
        storage = make_storage()
        storage.save_draft(_make_draft("d-old", skill_id="s1"))
        time.sleep(0.002)
        storage.save_draft(_make_draft("d-new", skill_id="s2"))
        listed = storage.list_drafts()
        assert listed[0].draft_id == "d-new"

    def test_delete_draft_sets_deleted_at(self, make_storage: Callable):
        storage = make_storage()
        storage.save_draft(_make_draft())
        deleted = storage.delete_draft("draft-1", expected_revision=1)
        assert deleted.deleted_at is not None
        assert storage.get_draft("draft-1") is None

    def test_delete_draft_stale_revision_conflicts(self, make_storage: Callable):
        storage = make_storage()
        storage.save_draft(_make_draft(revision=1))
        storage.update_draft(_make_draft(revision=2), expected_revision=1)
        with pytest.raises(SkillDraftConflictError):
            storage.delete_draft("draft-1", expected_revision=1)

    def test_delete_missing_draft_not_found(self, make_storage: Callable):
        storage = make_storage()
        with pytest.raises(SkillDraftNotFoundError):
            storage.delete_draft("missing", expected_revision=1)

    def test_delete_already_deleted_not_found(self, make_storage: Callable):
        storage = make_storage()
        storage.save_draft(_make_draft())
        storage.delete_draft("draft-1", expected_revision=1)
        with pytest.raises(SkillDraftNotFoundError):
            storage.delete_draft("draft-1", expected_revision=1)

    def test_save_does_not_mutate_caller_copy(self, make_storage: Callable):
        storage = make_storage()
        original = _make_draft()
        storage.save_draft(original)
        original.structured_config["dirty"] = True  # type: ignore[index]
        assert "dirty" not in storage.get_draft("draft-1").structured_config

    def test_preserves_validation_report_and_raw_files(self, make_storage: Callable):
        storage = make_storage()
        storage.save_draft(
            _make_draft(
                raw_files={"scripts/x.py": "print(1)"},
                validation_report={"blocking": [], "warnings": ["w1"]},
            )
        )
        got = storage.get_draft("draft-1")
        assert got.raw_files == {"scripts/x.py": "print(1)"}
        assert got.validation_report == {"blocking": [], "warnings": ["w1"]}

    def test_invalid_skill_id_rejected_at_model_level(self, make_storage: Callable):
        with pytest.raises(ValueError):
            SkillDraft(
                draft_id="d1",
                skill_id="Invalid ID!",
                skill_name="x",
                source_type=SkillDraftSourceType.TEMPLATE,
                created_by="u",
            )


class SkillDefinitionStorageContract:
    def test_save_and_get_definition(self, make_storage: Callable):
        storage = make_storage()
        storage.save_definition(_make_definition())
        got = storage.get_definition("demo_skill")
        assert got is not None
        assert got.skill_id == "demo_skill"
        assert storage.get_definition("demo_skill") is not got

    def test_save_duplicate_skill_id_conflicts(self, make_storage: Callable):
        storage = make_storage()
        storage.save_definition(_make_definition())
        with pytest.raises(SkillDefinitionConflictError):
            storage.save_definition(_make_definition())

    def test_update_definition_optimistic_lock(self, make_storage: Callable):
        storage = make_storage()
        storage.save_definition(_make_definition(revision=1))
        result = storage.update_definition(
            _make_definition(revision=2, lifecycle_status=SkillLifecycleStatus.DISABLED),
            expected_revision=1,
        )
        assert result.revision == 2
        assert result.lifecycle_status == SkillLifecycleStatus.DISABLED

    def test_update_definition_stale_revision_conflicts(self, make_storage: Callable):
        storage = make_storage()
        storage.save_definition(_make_definition(revision=1))
        storage.update_definition(
            _make_definition(revision=2, lifecycle_status=SkillLifecycleStatus.DISABLED),
            expected_revision=1,
        )
        with pytest.raises(SkillDefinitionConflictError):
            storage.update_definition(_make_definition(revision=3), expected_revision=1)

    def test_update_definition_wrong_increment_conflicts(self, make_storage: Callable):
        storage = make_storage()
        storage.save_definition(_make_definition(revision=1))
        with pytest.raises(SkillDefinitionConflictError):
            storage.update_definition(_make_definition(revision=9), expected_revision=1)

    def test_update_missing_definition_not_found(self, make_storage: Callable):
        storage = make_storage()
        with pytest.raises(SkillDefinitionNotFoundError):
            storage.update_definition(_make_definition(), expected_revision=1)

    def test_list_definitions_filtered_by_status(self, make_storage: Callable):
        storage = make_storage()
        storage.save_definition(_make_definition("s1", lifecycle_status=SkillLifecycleStatus.ENABLED))
        storage.save_definition(_make_definition("s2", lifecycle_status=SkillLifecycleStatus.DISABLED))
        storage.save_definition(_make_definition("s3", lifecycle_status=SkillLifecycleStatus.ARCHIVED))
        assert {d.skill_id for d in storage.list_definitions(lifecycle_status=SkillLifecycleStatus.ENABLED)} == {
            "s1"
        }
        assert {d.skill_id for d in storage.list_definitions()} == {"s1", "s2", "s3"}

    def test_get_missing_definition_returns_none(self, make_storage: Callable):
        storage = make_storage()
        assert storage.get_definition("nope") is None


# ────────────────────────────────────────────────────────────────────
# 内存实现绑定（完整契约）
# ────────────────────────────────────────────────────────────────────


class TestInMemorySkillDraftStorage(SkillDraftStorageContract):
    @pytest.fixture
    def make_storage(self) -> Callable:
        from src.data_platform.storage.skill.draft_in_memory import (
            InMemorySkillDraftStorage,
        )

        return lambda: InMemorySkillDraftStorage()


class TestInMemorySkillDefinitionStorage(SkillDefinitionStorageContract):
    @pytest.fixture
    def make_storage(self) -> Callable:
        from src.data_platform.storage.skill.draft_in_memory import (
            InMemorySkillDraftStorage,
        )

        return lambda: InMemorySkillDraftStorage()


# ────────────────────────────────────────────────────────────────────
# PostgreSQL 实现 SQL 正确性测试（FakeClient，不连真实 DB）
# ────────────────────────────────────────────────────────────────────


class _FakeClient:
    """记录所有执行的 SQL/参数；可预设返回行。"""

    def __init__(self, return_rows: list[dict[str, Any]] | None = None) -> None:
        self.calls: list[tuple[str, tuple[Any, ...]]] = []
        self._return_rows = return_rows

    def execute(self, sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
        self.calls.append((sql, params))
        if self._return_rows is not None:
            return self._return_rows
        return []

    @contextmanager
    def transaction(self) -> Iterator[None]:
        yield


def _flatten_sql(sql: str) -> str:
    return " ".join(sql.split()).lower()


def _persisted_draft_row() -> dict[str, Any]:
    return {
        "draft_id": "draft-1",
        "skill_id": "demo_skill",
        "skill_name": "Demo Skill",
        "source_type": "template",
        "source_skill_id": None,
        "structured_config": '{"basic": {"name": "Demo Skill"}}',
        "raw_files": '{"scripts/x.py": "print(1)"}',
        "validation_report": None,
        "status": "editing",
        "revision": 1,
        "created_by": "u-admin",
        "created_at": "2026-08-06T00:00:00+00:00",
        "updated_at": "2026-08-06T00:00:00+00:00",
        "deleted_at": None,
    }


def test_pg_save_draft_uses_atomic_insert_and_returns_persisted_row():
    from src.data_platform.storage.skill.draft_postgres import PostgresSkillDraftStorage

    client = _FakeClient(return_rows=[_persisted_draft_row()])
    storage = PostgresSkillDraftStorage(client=client)
    saved = storage.save_draft(_make_draft(raw_files={"scripts/x.py": "print(1)"}))

    inserts = [c for c in client.calls if _flatten_sql(c[0]).startswith("insert into skill_drafts")]
    assert len(inserts) == 1
    sql, params = inserts[0]
    flattened = _flatten_sql(sql)
    assert "on conflict (draft_id) do nothing" in flattened
    assert "returning *" in flattened
    assert not any(_flatten_sql(call[0]).startswith("select") for call in client.calls)
    # JSONB 字段以 JSON 字符串写入
    assert any(isinstance(p, str) and "scripts/x.py" in p for p in params)
    assert saved.draft_id == "draft-1"
    assert saved.raw_files == {"scripts/x.py": "print(1)"}


def test_pg_save_draft_normalizes_empty_atomic_insert_as_conflict():
    from src.data_platform.storage.skill.draft_postgres import PostgresSkillDraftStorage

    client = _FakeClient(return_rows=[])
    storage = PostgresSkillDraftStorage(client=client)
    with pytest.raises(SkillDraftConflictError):
        storage.save_draft(_make_draft())
    assert not any(_flatten_sql(call[0]).startswith("select") for call in client.calls)


def test_pg_update_draft_uses_optimistic_lock_where_clause():
    from src.data_platform.storage.skill.draft_postgres import PostgresSkillDraftStorage

    # 第一次 UPDATE 命中（返回行），二次查询不应触发
    row = {
        "draft_id": "draft-1", "skill_id": "demo_skill", "skill_name": "Demo",
        "source_type": "template", "source_skill_id": None,
        "structured_config": {}, "raw_files": {}, "validation_report": None,
        "status": "validated", "revision": 2, "created_by": "u-admin",
        "created_at": "2026-08-06T00:00:00+00:00", "updated_at": "2026-08-06T00:00:00+00:00",
        "deleted_at": None,
    }
    client = _FakeClient(return_rows=[row])
    storage = PostgresSkillDraftStorage(client=client)
    storage.update_draft(_make_draft(revision=2), expected_revision=1)
    update_call = next(c for c in client.calls if _flatten_sql(c[0]).startswith("update skill_drafts set"))
    assert "revision = %s" in _flatten_sql(update_call[0])
    assert "deleted_at is null" in _flatten_sql(update_call[0])
    # 参数顺序：expected_revision 在末尾
    assert update_call[1][-1] == 1  # expected_revision
    assert update_call[1][-2] == "draft-1"  # draft_id


def test_pg_update_draft_missing_raises_not_found():
    from src.data_platform.storage.skill.draft_postgres import PostgresSkillDraftStorage

    # UPDATE 未命中（返回空），二次查询也返回空 → NotFound
    client = _FakeClient(return_rows=[])
    storage = PostgresSkillDraftStorage(client=client)
    with pytest.raises(SkillDraftNotFoundError):
        storage.update_draft(_make_draft(revision=2), expected_revision=1)


def test_pg_update_draft_revision_conflict_raises_conflict():
    from src.data_platform.storage.skill.draft_postgres import PostgresSkillDraftStorage

    # UPDATE 未命中，二次查询显示存在且未删除 → Conflict
    def execute(sql, params=()):
        client.calls.append((sql, params))
        s = _flatten_sql(sql)
        if s.startswith("update skill_drafts"):
            return []  # 模拟 revision 不匹配
        if s.startswith("select revision, deleted_at from skill_drafts"):
            return [{"revision": 5, "deleted_at": None}]  # 实际 revision=5
        return []

    client = _FakeClient()
    client.execute = execute  # type: ignore[assignment]
    storage = PostgresSkillDraftStorage(client=client)
    with pytest.raises(SkillDraftConflictError):
        storage.update_draft(_make_draft(revision=2), expected_revision=1)


def test_pg_delete_draft_sets_deleted_at_and_increments_revision():
    row = {
        "draft_id": "draft-1", "skill_id": "demo_skill", "skill_name": "Demo",
        "source_type": "template", "source_skill_id": None,
        "structured_config": {}, "raw_files": {}, "validation_report": None,
        "status": "editing", "revision": 2, "created_by": "u-admin",
        "created_at": "2026-08-06T00:00:00+00:00", "updated_at": "2026-08-06T00:00:00+00:00",
        "deleted_at": "2026-08-06T00:00:01+00:00",
    }
    client = _FakeClient(return_rows=[row])
    from src.data_platform.storage.skill.draft_postgres import PostgresSkillDraftStorage

    storage = PostgresSkillDraftStorage(client=client)
    deleted = storage.delete_draft("draft-1", expected_revision=1)
    assert deleted.deleted_at is not None
    assert deleted.revision == 2
    update_call = next(c for c in client.calls if _flatten_sql(c[0]).startswith("update skill_drafts set"))
    assert "deleted_at = %s" in _flatten_call(update_call)


def _flatten_call(call: tuple[str, tuple]) -> str:
    return _flatten_sql(call[0])


def test_pg_list_drafts_builds_where_with_filters():
    from src.data_platform.storage.skill.draft_postgres import PostgresSkillDraftStorage

    client = _FakeClient(return_rows=[])
    storage = PostgresSkillDraftStorage(client=client)
    storage.list_drafts(skill_id="s1", status=SkillDraftStatus.VALIDATED)
    select_call = next(c for c in client.calls if _flatten_sql(c[0]).startswith("select * from skill_drafts"))
    sql = _flatten_sql(select_call[0])
    assert "deleted_at is null" in sql
    assert "skill_id = %s" in sql
    assert "status = %s" in sql


def test_pg_save_definition_emits_insert():
    from src.data_platform.storage.skill.draft_postgres import PostgresSkillDraftStorage

    client = _FakeClient()
    storage = PostgresSkillDraftStorage(client=client)
    storage.save_definition(_make_definition())
    inserts = [c for c in client.calls if _flatten_sql(c[0]).startswith("insert into skill_definitions")]
    assert len(inserts) == 1


def test_pg_update_definition_uses_optimistic_lock():
    row = {
        "skill_id": "demo_skill", "skill_name": "name", "business_action": "explain",
        "business_object": "settlement", "lifecycle_status": "disabled",
        "semantic_dependency_changed": False, "current_version_id": None,
        "revision": 2, "disabled_at": None, "archived_at": None,
        "created_at": "2026-08-06T00:00:00+00:00", "updated_at": "2026-08-06T00:00:00+00:00",
    }
    client = _FakeClient(return_rows=[row])
    from src.data_platform.storage.skill.draft_postgres import PostgresSkillDraftStorage

    storage = PostgresSkillDraftStorage(client=client)
    storage.update_definition(
        _make_definition(revision=2, lifecycle_status=SkillLifecycleStatus.DISABLED),
        expected_revision=1,
    )
    update_call = next(c for c in client.calls if _flatten_sql(c[0]).startswith("update skill_definitions set"))
    assert "revision = %s" in _flatten_call(update_call)


# ────────────────────────────────────────────────────────────────────
# 工厂单例测试
# ────────────────────────────────────────────────────────────────────


def test_draft_storage_factory_uses_memory_when_flag_set(monkeypatch: pytest.MonkeyPatch):
    from src.data_platform.storage.skill.draft_factory import get_skill_draft_storage
    from src.data_platform.storage.skill.draft_in_memory import (
        InMemorySkillDraftStorage,
    )

    monkeypatch.setenv("USE_MEMORY_STORAGE", "1")
    get_skill_draft_storage.cache_clear()
    first = get_skill_draft_storage()
    second = get_skill_draft_storage()
    assert isinstance(first, InMemorySkillDraftStorage)
    assert first is second  # 进程级单例
    get_skill_draft_storage.cache_clear()


def test_draft_storage_factory_defaults_to_postgres(monkeypatch: pytest.MonkeyPatch):
    from src.data_platform.storage.skill.draft_factory import get_skill_draft_storage
    from src.data_platform.storage.skill.draft_postgres import (
        PostgresSkillDraftStorage,
    )

    monkeypatch.delenv("USE_MEMORY_STORAGE", raising=False)
    get_skill_draft_storage.cache_clear()
    storage = get_skill_draft_storage()
    assert isinstance(storage, PostgresSkillDraftStorage)
    get_skill_draft_storage.cache_clear()
