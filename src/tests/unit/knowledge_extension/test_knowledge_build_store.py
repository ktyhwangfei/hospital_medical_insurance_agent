"""知识构建任务存储的单元测试。"""

from __future__ import annotations

from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from threading import Barrier, Lock
from time import sleep

import pytest
from pydantic import ValidationError

from src.knowledge_extension.rule_explanation.knowledge_build_models import (
    KnowledgeBuildTask,
    KnowledgeBuildTaskUnit,
)
from src.knowledge_extension.rule_explanation.knowledge_build_store import (
    InMemoryKnowledgeBuildStore,
    PostgreSQLKnowledgeBuildStore,
    UnitRevisionClaimed,
)


def _make_unit(
    *,
    doc_id: str = "doc-1",
    unit_id: str = "unit-1",
    revision_id: str = "revision-1",
) -> KnowledgeBuildTaskUnit:
    return KnowledgeBuildTaskUnit(
        doc_id=doc_id,
        doc_title=f"政策 {doc_id}",
        unit_id=unit_id,
        unit_revision_id=revision_id,
        path=["第一章"],
    )


def _make_task(
    task_id: str,
    *,
    units: list[KnowledgeBuildTaskUnit] | None = None,
    created_at: datetime | None = None,
) -> KnowledgeBuildTask:
    values = {
        "task_id": task_id,
        "name": f"构建任务 {task_id}",
        "status": "QUEUED",
        "build_mode": "INITIAL",
        "semantic_contract_version": "contract-v1",
        "pipeline_version": "pipeline-v1",
        "model_scene": "policy_knowledge_build",
        "config_hash": "config-hash",
        "created_by": "tester",
        "units": units or [_make_unit()],
    }
    if created_at is not None:
        values["created_at"] = created_at
        values["updated_at"] = created_at
    return KnowledgeBuildTask.model_validate(values)


_STATUS_PATHS: dict[str, list[str]] = {
    "QUEUED": [],
    "RUNNING": ["RUNNING"],
    "WAITING_REVIEW": ["RUNNING", "WAITING_REVIEW"],
    "APPROVED_PENDING_RELEASE": [
        "RUNNING",
        "WAITING_REVIEW",
        "APPROVED_PENDING_RELEASE",
    ],
    "PUBLISHED": [
        "RUNNING",
        "WAITING_REVIEW",
        "APPROVED_PENDING_RELEASE",
        "PUBLISHED",
    ],
    "RETURNED": ["RUNNING", "WAITING_REVIEW", "RETURNED"],
    "REJECTED": ["RUNNING", "WAITING_REVIEW", "REJECTED"],
    "FAILED": ["FAILED"],
    "CANCELLED": ["CANCELLED"],
}


def _move_to_status(
    store: InMemoryKnowledgeBuildStore,
    task: KnowledgeBuildTask,
    status: str,
) -> KnowledgeBuildTask:
    current = task
    for next_status in _STATUS_PATHS[status]:
        current = store.save(current.model_copy(update={"status": next_status}))
    return current


@pytest.mark.parametrize(
    "field_name",
    ["created_at", "updated_at", "started_at", "finished_at"],
)
def test_task_rejects_naive_timestamps(field_name: str) -> None:
    values = _make_task("task-naive-time").model_dump()
    values[field_name] = datetime(2026, 8, 5)

    with pytest.raises(ValidationError):
        KnowledgeBuildTask.model_validate(values)


def test_only_one_task_can_claim_same_revision() -> None:
    store = InMemoryKnowledgeBuildStore()
    store.create_with_claims(_make_task("task-1"))

    with pytest.raises(UnitRevisionClaimed) as caught:
        store.create_with_claims(_make_task("task-2"))

    assert caught.value.doc_id == "doc-1"
    assert caught.value.unit_id == "unit-1"
    assert caught.value.unit_revision_id == "revision-1"
    assert caught.value.task_id == "task-1"
    assert "task-1" in str(caught.value)
    assert store.get("task-2") is None


def test_concurrent_submissions_to_same_revision_yield_one_success() -> None:
    store = InMemoryKnowledgeBuildStore()
    barrier = Barrier(2)

    def submit(task_id: str) -> str:
        barrier.wait()
        try:
            store.create_with_claims(_make_task(task_id))
        except UnitRevisionClaimed:
            return "conflict"
        return "success"

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(submit, ["task-1", "task-2"]))

    assert sorted(results) == ["conflict", "success"]
    assert len(store.list()) == 1
    assert store.get_claim("doc-1", "unit-1") is not None


def test_different_revisions_of_same_logical_unit_conflict() -> None:
    store = InMemoryKnowledgeBuildStore()
    store.create_with_claims(_make_task("task-1"))

    with pytest.raises(UnitRevisionClaimed) as caught:
        store.create_with_claims(
            _make_task(
                "task-2",
                units=[_make_unit(revision_id="revision-2")],
            )
        )

    assert caught.value.task_id == "task-1"
    assert caught.value.unit_revision_id == "revision-1"


def test_same_unit_id_in_different_documents_can_be_claimed() -> None:
    store = InMemoryKnowledgeBuildStore()

    store.create_with_claims(_make_task("task-1"))
    store.create_with_claims(
        _make_task(
            "task-2",
            units=[
                _make_unit(
                    doc_id="doc-2",
                    unit_id="unit-1",
                    revision_id="revision-2",
                )
            ],
        )
    )

    assert store.get_claim("doc-1", "unit-1").task_id == "task-1"
    assert store.get_claim("doc-2", "unit-1").task_id == "task-2"


def test_duplicate_logical_units_inside_task_leave_no_state() -> None:
    store = InMemoryKnowledgeBuildStore()
    task = _make_task(
        "task-duplicate",
        units=[
            _make_unit(revision_id="revision-1"),
            _make_unit(revision_id="revision-2"),
        ],
    )

    with pytest.raises(ValueError, match="重复"):
        store.create_with_claims(task)

    assert store.get("task-duplicate") is None
    assert store.get_claim("doc-1", "unit-1") is None


def test_conflict_on_second_unit_leaves_no_partial_task_or_claim() -> None:
    store = InMemoryKnowledgeBuildStore()
    occupied = _make_unit(
        doc_id="doc-2",
        unit_id="unit-2",
        revision_id="revision-2",
    )
    store.create_with_claims(_make_task("existing-task", units=[occupied]))
    new_first = _make_unit(
        doc_id="doc-1",
        unit_id="unit-1",
        revision_id="revision-1",
    )

    with pytest.raises(UnitRevisionClaimed):
        store.create_with_claims(
            _make_task("new-task", units=[new_first, occupied.model_copy(deep=True)])
        )

    assert store.get("new-task") is None
    assert store.get_claim("doc-1", "unit-1") is None
    assert store.get_claim("doc-2", "unit-2").task_id == "existing-task"


@pytest.mark.parametrize("status", ["WAITING_REVIEW", "APPROVED_PENDING_RELEASE"])
def test_review_statuses_retain_claims(status: str) -> None:
    store = InMemoryKnowledgeBuildStore()
    task = store.create_with_claims(_make_task("task-1"))

    _move_to_status(store, task, status)

    assert store.get_claim("doc-1", "unit-1").task_id == "task-1"


@pytest.mark.parametrize(
    "status",
    ["PUBLISHED", "RETURNED", "REJECTED", "FAILED", "CANCELLED"],
)
def test_terminal_status_releases_claims_but_keeps_history(status: str) -> None:
    store = InMemoryKnowledgeBuildStore()
    task = store.create_with_claims(_make_task("task-1"))

    _move_to_status(store, task, status)

    assert store.get_claim("doc-1", "unit-1") is None
    assert store.get("task-1").status == status


def test_save_rejects_unknown_task() -> None:
    store = InMemoryKnowledgeBuildStore()

    with pytest.raises(KeyError):
        store.save(_make_task("missing-task"))

    assert store.list() == []


def test_save_uses_cas_and_preserves_created_at_and_claims() -> None:
    store = InMemoryKnowledgeBuildStore()
    original = store.create_with_claims(_make_task("task-1"))
    forged_created_at = original.created_at - timedelta(days=1)

    saved = store.save(
        original.model_copy(
            update={"status": "RUNNING", "created_at": forged_created_at}
        )
    )

    assert saved.created_at == original.created_at
    assert saved.updated_at > original.updated_at
    with pytest.raises(RuntimeError) as caught:
        store.save(original.model_copy(update={"status": "FAILED"}))
    assert caught.type.__name__ == "KnowledgeBuildTaskVersionConflict"
    assert store.get("task-1") == saved
    assert store.get_claim("doc-1", "unit-1").task_id == "task-1"


@pytest.mark.parametrize(
    ("current_status", "next_status"),
    [
        ("QUEUED", "RUNNING"),
        ("QUEUED", "FAILED"),
        ("QUEUED", "CANCELLED"),
        ("RUNNING", "WAITING_REVIEW"),
        ("RUNNING", "FAILED"),
        ("RUNNING", "CANCELLED"),
        ("WAITING_REVIEW", "APPROVED_PENDING_RELEASE"),
        ("WAITING_REVIEW", "RETURNED"),
        ("WAITING_REVIEW", "REJECTED"),
        ("WAITING_REVIEW", "CANCELLED"),
        ("APPROVED_PENDING_RELEASE", "PUBLISHED"),
        ("APPROVED_PENDING_RELEASE", "RETURNED"),
        ("APPROVED_PENDING_RELEASE", "REJECTED"),
    ],
)
def test_save_allows_planned_status_transitions(
    current_status: str,
    next_status: str,
) -> None:
    store = InMemoryKnowledgeBuildStore()
    task = store.create_with_claims(_make_task("task-1"))
    current = _move_to_status(store, task, current_status)

    saved = store.save(current.model_copy(update={"status": next_status}))

    assert saved.status == next_status


@pytest.mark.parametrize("status", list(_STATUS_PATHS))
def test_save_allows_same_status(status: str) -> None:
    store = InMemoryKnowledgeBuildStore()
    task = store.create_with_claims(_make_task("task-1"))
    current = _move_to_status(store, task, status)

    saved = store.save(current.model_copy(deep=True))

    assert saved.status == status


@pytest.mark.parametrize(
    ("current_status", "next_status"),
    [
        ("QUEUED", "WAITING_REVIEW"),
        ("RUNNING", "PUBLISHED"),
        ("WAITING_REVIEW", "PUBLISHED"),
        ("APPROVED_PENDING_RELEASE", "FAILED"),
        ("FAILED", "RUNNING"),
        ("PUBLISHED", "RETURNED"),
    ],
)
def test_illegal_status_transition_leaves_task_and_claims_unchanged(
    current_status: str,
    next_status: str,
) -> None:
    store = InMemoryKnowledgeBuildStore()
    task = store.create_with_claims(_make_task("task-1"))
    current = _move_to_status(store, task, current_status)
    claim_before = store.get_claim("doc-1", "unit-1")

    with pytest.raises(ValueError, match="状态"):
        store.save(current.model_copy(update={"status": next_status}))

    assert store.get("task-1") == current
    assert store.get_claim("doc-1", "unit-1") == claim_before


def test_release_claims_requires_existing_terminal_task() -> None:
    store = InMemoryKnowledgeBuildStore()
    task = store.create_with_claims(_make_task("task-1"))

    with pytest.raises(ValueError, match="终态"):
        store.release_claims("task-1")
    assert store.get_claim("doc-1", "unit-1").task_id == "task-1"
    with pytest.raises(KeyError):
        store.release_claims("missing-task")
    assert store.get_claim("doc-1", "unit-1").task_id == "task-1"

    terminal = store.save(task.model_copy(update={"status": "FAILED"}))
    store.release_claims(terminal.task_id)
    assert store.get(terminal.task_id) == terminal


def test_returned_objects_are_deep_copies() -> None:
    store = InMemoryKnowledgeBuildStore()
    created = store.create_with_claims(_make_task("task-1"))
    created.units[0].path.append("外部修改")
    fetched = store.get("task-1")
    fetched.units[0].candidate_result_ids.append("candidate-1")
    fetched.result_summary["added"] = 1
    listed = store.list()
    listed[0].units[0].path.append("列表修改")
    claim = store.get_claim("doc-1", "unit-1")
    claim.task_id = "mutated"

    stored = store.get("task-1")
    assert stored.units[0].path == ["第一章"]
    assert stored.units[0].candidate_result_ids == []
    assert stored.result_summary == {}
    assert store.get_claim("doc-1", "unit-1").task_id == "task-1"


def test_list_returns_newest_task_first() -> None:
    store = InMemoryKnowledgeBuildStore()
    now = datetime.now(timezone.utc)
    store.create_with_claims(
        _make_task(
            "older",
            units=[_make_unit(doc_id="doc-1", revision_id="revision-1")],
            created_at=now,
        )
    )
    store.create_with_claims(
        _make_task(
            "newer",
            units=[_make_unit(doc_id="doc-2", revision_id="revision-2")],
            created_at=now + timedelta(seconds=1),
        )
    )

    assert [task.task_id for task in store.list()] == ["newer", "older"]


class _FakeCursor:
    def __init__(self, client: "_FakePostgreSQLClient") -> None:
        self._client = client
        self._row = None

    def __enter__(self) -> "_FakeCursor":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def execute(self, sql: str, params: tuple[object, ...] = ()) -> None:
        self._client.transaction_statements.append((sql, params))
        self._row = self._client.execute_in_transaction(sql, params)

    def fetchone(self):
        return self._row


class _FakeConnection:
    def __init__(self, client: "_FakePostgreSQLClient") -> None:
        self._client = client

    def cursor(self) -> _FakeCursor:
        return _FakeCursor(self._client)


class _FakePostgreSQLClient:
    def __init__(self) -> None:
        self.execute_statements: list[tuple[str, tuple[object, ...]]] = []
        self.transaction_statements: list[tuple[str, tuple[object, ...]]] = []
        self.transaction_count = 0
        self.rollback_count = 0
        self.transaction_delay = 0.0
        self.active_transactions = 0
        self.max_active_transactions = 0
        self.fail_claim_delete = False
        self.tasks: dict[str, dict[str, object]] = {}
        self.claims: dict[tuple[str, str], dict[str, object]] = {}
        self._transaction_guard = Lock()

    def execute(
        self, sql: str, params: tuple[object, ...] = ()
    ) -> list[dict[str, object]]:
        self.execute_statements.append((sql, params))
        normalized = self._normalize(sql)
        if normalized.startswith("CREATE TABLE"):
            return []
        if normalized.startswith("INSERT INTO POLICY_KNOWLEDGE_BUILD_TASKS"):
            self._write_task(params, allow_update="ON CONFLICT" in normalized)
            return []
        if (
            normalized.startswith("SELECT PAYLOAD")
            and "WHERE TASK_ID = %S" in normalized
        ):
            task = self.tasks.get(str(params[0]))
            return [{"payload": task["payload"]}] if task else []
        if (
            normalized.startswith("SELECT PAYLOAD")
            and "ORDER BY CREATED_AT DESC" in normalized
        ):
            ordered = sorted(
                self.tasks.values(),
                key=lambda task: task["created_at"],
                reverse=True,
            )
            return [{"payload": task["payload"]} for task in ordered]
        if normalized.startswith(
            "SELECT DOC_ID, UNIT_ID, UNIT_REVISION_ID, TASK_ID, CLAIMED_AT"
        ):
            claim = self.claims.get((str(params[0]), str(params[1])))
            return [deepcopy(claim)] if claim else []
        if normalized.startswith("DELETE FROM POLICY_KNOWLEDGE_UNIT_CLAIMS"):
            self._delete_claims(str(params[0]))
            return []
        raise AssertionError(f"假 PostgreSQLClient 未支持该 SQL: {normalized}")

    def execute_in_transaction(
        self,
        sql: str,
        params: tuple[object, ...],
    ) -> tuple[object, ...] | None:
        normalized = self._normalize(sql)
        if normalized.startswith("INSERT INTO POLICY_KNOWLEDGE_BUILD_TASKS"):
            self._write_task(params, allow_update="ON CONFLICT" in normalized)
            return None
        if normalized.startswith("INSERT INTO POLICY_KNOWLEDGE_UNIT_CLAIMS"):
            doc_id, unit_id, revision_id, task_id, claimed_at = params
            logical_key = (str(doc_id), str(unit_id))
            revision_exists = any(
                claim["unit_revision_id"] == revision_id
                for claim in self.claims.values()
            )
            if logical_key in self.claims or revision_exists:
                return None
            self.claims[logical_key] = {
                "doc_id": doc_id,
                "unit_id": unit_id,
                "unit_revision_id": revision_id,
                "task_id": task_id,
                "claimed_at": claimed_at,
            }
            return (revision_id,)
        if normalized.startswith(
            "SELECT DOC_ID, UNIT_ID, UNIT_REVISION_ID, TASK_ID, CLAIMED_AT"
        ):
            logical_key = (str(params[0]), str(params[1]))
            claim = self.claims.get(logical_key)
            if claim is None:
                claim = next(
                    (
                        item
                        for item in self.claims.values()
                        if item["unit_revision_id"] == params[2]
                    ),
                    None,
                )
            if claim is None:
                return None
            return (
                claim["doc_id"],
                claim["unit_id"],
                claim["unit_revision_id"],
                claim["task_id"],
                claim["claimed_at"],
            )
        if (
            normalized.startswith("SELECT PAYLOAD")
            and "WHERE TASK_ID = %S" in normalized
        ):
            task = self.tasks.get(str(params[0]))
            return (task["payload"],) if task else None
        if normalized.startswith("UPDATE POLICY_KNOWLEDGE_BUILD_TASKS"):
            status, payload, updated_at, task_id, expected_updated_at = params
            task = self.tasks.get(str(task_id))
            if task is None or task["updated_at"] != expected_updated_at:
                return None
            task.update(
                {"status": status, "payload": payload, "updated_at": updated_at}
            )
            return (payload,)
        if normalized.startswith("SELECT TASK_ID"):
            task_id = str(params[0])
            return (task_id,) if task_id in self.tasks else None
        if normalized.startswith("SELECT STATUS"):
            task = self.tasks.get(str(params[0]))
            return (task["status"],) if task else None
        if normalized.startswith("DELETE FROM POLICY_KNOWLEDGE_UNIT_CLAIMS"):
            self._delete_claims(str(params[0]))
            return None
        raise AssertionError(f"假事务连接未支持该 SQL: {normalized}")

    def _write_task(
        self,
        params: tuple[object, ...],
        *,
        allow_update: bool,
    ) -> None:
        task_id, status, payload, created_at, updated_at = params
        key = str(task_id)
        if key in self.tasks and not allow_update:
            raise RuntimeError(f"重复任务 {task_id}")
        self.tasks[key] = {
            "task_id": task_id,
            "status": status,
            "payload": payload,
            "created_at": created_at,
            "updated_at": updated_at,
        }

    def _delete_claims(self, task_id: str) -> None:
        if self.fail_claim_delete:
            raise RuntimeError("注入的 claim 删除失败")
        keys = [
            key
            for key, claim in self.claims.items()
            if claim["task_id"] == task_id
        ]
        for key in keys:
            del self.claims[key]

    @staticmethod
    def _normalize(sql: str) -> str:
        return " ".join(sql.split()).upper()

    @contextmanager
    def transaction(self):
        task_snapshot = deepcopy(self.tasks)
        claim_snapshot = deepcopy(self.claims)
        self.transaction_count += 1
        with self._transaction_guard:
            self.active_transactions += 1
            self.max_active_transactions = max(
                self.max_active_transactions,
                self.active_transactions,
            )
        try:
            sleep(self.transaction_delay)
            yield _FakeConnection(self)
        except BaseException:
            self.tasks = task_snapshot
            self.claims = claim_snapshot
            self.rollback_count += 1
            raise
        finally:
            with self._transaction_guard:
                self.active_transactions -= 1


def _postgres_store(
    monkeypatch: pytest.MonkeyPatch,
    fake: _FakePostgreSQLClient,
) -> PostgreSQLKnowledgeBuildStore:
    from src.data_platform.storage.postgresql import client as client_module

    monkeypatch.setattr(client_module, "PostgreSQLClient", lambda _url: fake)
    return PostgreSQLKnowledgeBuildStore("postgresql://test")


def test_postgresql_store_serializes_shared_client_transactions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _FakePostgreSQLClient()
    fake.transaction_delay = 0.05
    store = _postgres_store(monkeypatch, fake)
    barrier = Barrier(2)

    def submit(task: KnowledgeBuildTask) -> None:
        barrier.wait()
        store.create_with_claims(task)

    tasks = [
        _make_task(
            "task-1",
            units=[_make_unit(doc_id="doc-1", revision_id="revision-1")],
        ),
        _make_task(
            "task-2",
            units=[_make_unit(doc_id="doc-2", revision_id="revision-2")],
        ),
    ]
    with ThreadPoolExecutor(max_workers=2) as executor:
        list(executor.map(submit, tasks))

    assert fake.max_active_transactions == 1


def test_postgresql_schema_has_logical_and_revision_constraints(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _FakePostgreSQLClient()
    store = _postgres_store(monkeypatch, fake)

    assert store.get("missing") is None

    schema = "\n".join(sql for sql, _ in fake.execute_statements)
    assert "CREATE TABLE IF NOT EXISTS policy_knowledge_build_tasks" in schema
    assert "CREATE TABLE IF NOT EXISTS policy_knowledge_unit_claims" in schema
    assert "PRIMARY KEY (doc_id, unit_id)" in schema
    assert "unit_revision_id VARCHAR(96) NOT NULL UNIQUE" in schema


def test_postgresql_create_claims_in_one_transaction_with_atomic_insert(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _FakePostgreSQLClient()
    store = _postgres_store(monkeypatch, fake)

    created = store.create_with_claims(_make_task("task-1"))

    transaction_sql = "\n".join(sql for sql, _ in fake.transaction_statements)
    assert created.task_id == "task-1"
    assert fake.transaction_count == 1
    assert "INSERT INTO policy_knowledge_build_tasks" in transaction_sql
    assert "INSERT INTO policy_knowledge_unit_claims" in transaction_sql
    assert "ON CONFLICT DO NOTHING" in transaction_sql
    assert "RETURNING unit_revision_id" in transaction_sql


def test_postgresql_claim_conflict_raises_existing_task_and_rolls_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _FakePostgreSQLClient()
    store = _postgres_store(monkeypatch, fake)
    store.create_with_claims(
        _make_task(
            "existing-task",
            units=[_make_unit(revision_id="revision-existing")],
        )
    )

    with pytest.raises(UnitRevisionClaimed) as caught:
        store.create_with_claims(_make_task("new-task"))

    assert caught.value.task_id == "existing-task"
    assert caught.value.unit_revision_id == "revision-existing"
    assert fake.rollback_count == 1
    assert store.get("new-task") is None


def test_postgresql_terminal_save_updates_task_and_deletes_claims_together(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _FakePostgreSQLClient()
    store = _postgres_store(monkeypatch, fake)
    created = store.create_with_claims(_make_task("task-1"))
    transaction_count = fake.transaction_count

    saved = store.save(created.model_copy(update={"status": "FAILED"}))

    transaction_sql = "\n".join(sql for sql, _ in fake.transaction_statements)
    assert saved.status == "FAILED"
    assert fake.transaction_count == transaction_count + 1
    assert "policy_knowledge_build_tasks" in transaction_sql
    assert "DELETE FROM policy_knowledge_unit_claims" in transaction_sql


def test_postgresql_save_rejects_unknown_task(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _FakePostgreSQLClient()
    store = _postgres_store(monkeypatch, fake)

    with pytest.raises(KeyError):
        store.save(_make_task("missing-task"))

    assert store.get("missing-task") is None


def test_postgresql_save_uses_cas_and_preserves_created_at_and_claim(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _FakePostgreSQLClient()
    store = _postgres_store(monkeypatch, fake)
    original = store.create_with_claims(_make_task("task-1"))

    saved = store.save(
        original.model_copy(
            update={
                "status": "RUNNING",
                "created_at": original.created_at - timedelta(days=1),
            }
        )
    )

    assert saved.created_at == original.created_at
    assert saved.updated_at > original.updated_at
    with pytest.raises(RuntimeError) as caught:
        store.save(original.model_copy(update={"status": "FAILED"}))
    assert caught.type.__name__ == "KnowledgeBuildTaskVersionConflict"
    assert store.get("task-1") == saved
    assert store.get_claim("doc-1", "unit-1").task_id == "task-1"
    transaction_sql = "\n".join(sql for sql, _ in fake.transaction_statements)
    assert "UPDATE policy_knowledge_build_tasks" in transaction_sql
    assert "WHERE task_id = %s AND updated_at = %s" in transaction_sql
    assert "RETURNING payload" in transaction_sql
    assert "ON CONFLICT (task_id) DO UPDATE" not in transaction_sql


def test_postgresql_illegal_transition_leaves_state_unchanged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _FakePostgreSQLClient()
    store = _postgres_store(monkeypatch, fake)
    original = store.create_with_claims(_make_task("task-1"))

    with pytest.raises(ValueError, match="状态"):
        store.save(original.model_copy(update={"status": "WAITING_REVIEW"}))

    assert store.get("task-1") == original
    assert store.get_claim("doc-1", "unit-1").task_id == "task-1"


def test_postgresql_second_claim_conflict_rolls_back_task_and_first_claim(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _FakePostgreSQLClient()
    store = _postgres_store(monkeypatch, fake)
    occupied = _make_unit(
        doc_id="doc-2",
        unit_id="unit-2",
        revision_id="revision-2",
    )
    store.create_with_claims(_make_task("existing-task", units=[occupied]))

    with pytest.raises(UnitRevisionClaimed):
        store.create_with_claims(
            _make_task(
                "new-task",
                units=[
                    _make_unit(
                        doc_id="doc-1",
                        unit_id="unit-1",
                        revision_id="revision-1",
                    ),
                    occupied.model_copy(deep=True),
                ],
            )
        )

    assert store.get("new-task") is None
    assert store.get_claim("doc-1", "unit-1") is None
    assert store.get_claim("doc-2", "unit-2").task_id == "existing-task"


def test_postgresql_terminal_save_failure_rolls_back_task_and_claims(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _FakePostgreSQLClient()
    store = _postgres_store(monkeypatch, fake)
    original = store.create_with_claims(_make_task("task-1"))
    fake.fail_claim_delete = True

    with pytest.raises(RuntimeError, match="claim"):
        store.save(original.model_copy(update={"status": "FAILED"}))

    fake.fail_claim_delete = False
    assert store.get("task-1") == original
    assert store.get_claim("doc-1", "unit-1").task_id == "task-1"


def test_postgresql_release_claims_requires_existing_terminal_task(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _FakePostgreSQLClient()
    store = _postgres_store(monkeypatch, fake)
    original = store.create_with_claims(_make_task("task-1"))

    with pytest.raises(ValueError, match="终态"):
        store.release_claims("task-1")
    assert store.get_claim("doc-1", "unit-1").task_id == "task-1"
    with pytest.raises(KeyError):
        store.release_claims("missing-task")
    assert store.get_claim("doc-1", "unit-1").task_id == "task-1"

    terminal = store.save(original.model_copy(update={"status": "FAILED"}))
    store.release_claims(terminal.task_id)
    assert store.get(terminal.task_id) == terminal


def _store_for_backend(
    backend: str,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[
    InMemoryKnowledgeBuildStore | PostgreSQLKnowledgeBuildStore,
    _FakePostgreSQLClient | None,
]:
    if backend == "memory":
        return InMemoryKnowledgeBuildStore(), None
    fake = _FakePostgreSQLClient()
    return _postgres_store(monkeypatch, fake), fake


@pytest.mark.parametrize("backend", ["memory", "postgresql"])
@pytest.mark.parametrize(
    ("field_name", "new_value"),
    [
        ("name", "被篡改的任务名"),
        ("build_mode", "REBUILD"),
        ("semantic_contract_version", "contract-v2"),
        ("pipeline_version", "pipeline-v2"),
        ("model_scene", "other_scene"),
        ("config_hash", "other-config-hash"),
        ("created_by", "other-user"),
        ("rebuild_reason", "人工重建"),
    ],
)
def test_save_rejects_frozen_top_level_field_changes(
    backend: str,
    field_name: str,
    new_value: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, _fake = _store_for_backend(backend, monkeypatch)
    original = store.create_with_claims(_make_task("task-1"))
    claim_before = store.get_claim("doc-1", "unit-1")

    with pytest.raises(ValueError) as caught:
        store.save(original.model_copy(update={field_name: new_value}, deep=True))

    assert caught.type.__name__ == "KnowledgeBuildTaskImmutableFieldError"
    assert getattr(caught.value, "field_name") == field_name
    assert store.get("task-1") == original
    assert store.get_claim("doc-1", "unit-1") == claim_before


@pytest.mark.parametrize("backend", ["memory", "postgresql"])
@pytest.mark.parametrize(
    ("field_name", "new_value"),
    [
        ("doc_id", "doc-other"),
        ("doc_title", "其他政策"),
        ("unit_id", "unit-other"),
        ("unit_revision_id", "revision-other"),
        ("path", ["第二章"]),
    ],
)
def test_save_rejects_unit_source_identity_changes(
    backend: str,
    field_name: str,
    new_value: str | list[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, _fake = _store_for_backend(backend, monkeypatch)
    original = store.create_with_claims(_make_task("task-1"))
    claim_before = store.get_claim("doc-1", "unit-1")
    changed_unit = original.units[0].model_copy(
        update={field_name: new_value},
        deep=True,
    )

    with pytest.raises(ValueError) as caught:
        store.save(original.model_copy(update={"units": [changed_unit]}, deep=True))

    expected_field = f"units[0].{field_name}"
    assert caught.type.__name__ == "KnowledgeBuildTaskImmutableFieldError"
    assert getattr(caught.value, "field_name") == expected_field
    assert store.get("task-1") == original
    assert store.get_claim("doc-1", "unit-1") == claim_before


@pytest.mark.parametrize("backend", ["memory", "postgresql"])
@pytest.mark.parametrize("mutation", ["remove", "reorder"])
def test_save_rejects_unit_selection_or_order_changes(
    backend: str,
    mutation: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, _fake = _store_for_backend(backend, monkeypatch)
    units = [
        _make_unit(
            doc_id="doc-1",
            unit_id="unit-1",
            revision_id="revision-1",
        ),
        _make_unit(
            doc_id="doc-2",
            unit_id="unit-2",
            revision_id="revision-2",
        ),
    ]
    original = store.create_with_claims(_make_task("task-1", units=units))
    changed_units = original.units[:1]
    expected_field = "units"
    if mutation == "reorder":
        changed_units = list(reversed(original.units))
        expected_field = "units[0].doc_id"

    with pytest.raises(ValueError) as caught:
        store.save(original.model_copy(update={"units": changed_units}, deep=True))

    assert caught.type.__name__ == "KnowledgeBuildTaskImmutableFieldError"
    assert getattr(caught.value, "field_name") == expected_field
    assert store.get("task-1") == original
    assert store.get_claim("doc-1", "unit-1").task_id == "task-1"
    assert store.get_claim("doc-2", "unit-2").task_id == "task-1"


@pytest.mark.parametrize("backend", ["memory", "postgresql"])
def test_save_allows_mutable_progress_result_and_unit_fields(
    backend: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, _fake = _store_for_backend(backend, monkeypatch)
    original = store.create_with_claims(_make_task("task-1"))
    started_at = datetime.now(timezone.utc)
    finished_at = started_at + timedelta(seconds=1)
    changed_unit = original.units[0].model_copy(
        update={
            "status": "FAILED",
            "candidate_result_ids": ["candidate-1"],
            "error_code": "BUILD_FAILED",
            "error_message": "模型输出无效",
        },
        deep=True,
    )
    changed = original.model_copy(
        update={
            "status": "RUNNING",
            "units": [changed_unit],
            "processed_units": 1,
            "result_change_set_id": "change-set-1",
            "result_summary": {"failed": 1},
            "issue_count": 1,
            "started_at": started_at,
            "finished_at": finished_at,
        },
        deep=True,
    )

    saved = store.save(changed)

    assert saved.status == "RUNNING"
    assert saved.units == [changed_unit]
    assert saved.processed_units == 1
    assert saved.result_change_set_id == "change-set-1"
    assert saved.result_summary == {"failed": 1}
    assert saved.issue_count == 1
    assert saved.started_at == started_at
    assert saved.finished_at == finished_at
    claim = store.get_claim("doc-1", "unit-1")
    assert claim.unit_revision_id == "revision-1"
    assert claim.task_id == "task-1"


@pytest.mark.parametrize("backend", ["memory", "postgresql"])
def test_fail_and_release_uses_latest_task_and_atomically_releases_claims(
    backend: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, _fake = _store_for_backend(backend, monkeypatch)
    created = store.create_with_claims(_make_task("task-failure"))
    running = store.save(created.model_copy(update={"status": "RUNNING"}))

    failed = store.fail_and_release(
        created.task_id,
        error_code="KnowledgeBuildTaskVersionConflict",
        error_message="concurrent update",
        result_change_set_id="CS_partial_candidate",
    )

    assert running.updated_at != created.updated_at
    assert failed.status == "FAILED"
    assert failed.result_change_set_id == "CS_partial_candidate"
    assert failed.finished_at is not None
    assert failed.finished_at.tzinfo is not None
    assert [unit.status for unit in failed.units] == ["FAILED"]
    assert [unit.error_code for unit in failed.units] == [
        "KnowledgeBuildTaskVersionConflict"
    ]
    assert [unit.error_message for unit in failed.units] == ["concurrent update"]
    assert store.get(created.task_id) == failed
    assert store.get_claim("doc-1", "unit-1") is None


def test_postgresql_fail_and_release_rolls_back_task_when_claim_delete_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _FakePostgreSQLClient()
    store = _postgres_store(monkeypatch, fake)
    created = store.create_with_claims(_make_task("task-failure"))
    running = store.save(created.model_copy(update={"status": "RUNNING"}))
    fake.fail_claim_delete = True

    with pytest.raises(RuntimeError, match="claim"):
        store.fail_and_release(
            created.task_id,
            error_code="RuntimeError",
            error_message="build failed",
        )

    fake.fail_claim_delete = False
    assert store.get(created.task_id) == running
    assert store.get_claim("doc-1", "unit-1").task_id == created.task_id


@pytest.mark.parametrize("backend", ["memory", "postgresql"])
@pytest.mark.parametrize(
    "later_status",
    ["WAITING_REVIEW", "APPROVED_PENDING_RELEASE"],
)
def test_fail_and_release_preserves_concurrently_advanced_task_and_claim(
    backend: str,
    later_status: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, _fake = _store_for_backend(backend, monkeypatch)
    created = store.create_with_claims(_make_task("task-advanced"))
    advanced = _move_to_status(store, created, later_status)
    claim_before = store.get_claim("doc-1", "unit-1")

    result = store.fail_and_release(
        created.task_id,
        error_code="RuntimeError",
        error_message="stale worker failure",
        result_change_set_id="CS_stale_failure",
    )

    assert result == advanced
    assert store.get(created.task_id) == advanced
    assert store.get_claim("doc-1", "unit-1") == claim_before
