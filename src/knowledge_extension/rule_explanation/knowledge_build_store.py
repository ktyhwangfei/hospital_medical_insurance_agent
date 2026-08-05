"""政策知识构建任务与单元占用存储。"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from datetime import timedelta
from threading import RLock
from typing import TYPE_CHECKING, Any, Protocol

from src.knowledge_extension.rule_explanation.knowledge_build_models import (
    BuildTaskStatus,
    KnowledgeBuildTask,
    UnitBuildClaim,
    utc_now,
)

if TYPE_CHECKING:
    from src.data_platform.storage.postgresql.client import PostgreSQLClient


_TERMINAL_STATUSES: frozenset[BuildTaskStatus] = frozenset(
    {"PUBLISHED", "RETURNED", "REJECTED", "FAILED", "CANCELLED"}
)
_LEGAL_TRANSITIONS: dict[BuildTaskStatus, frozenset[BuildTaskStatus]] = {
    "QUEUED": frozenset({"RUNNING", "FAILED", "CANCELLED"}),
    "RUNNING": frozenset({"WAITING_REVIEW", "FAILED", "CANCELLED"}),
    "WAITING_REVIEW": frozenset(
        {"APPROVED_PENDING_RELEASE", "RETURNED", "REJECTED", "CANCELLED"}
    ),
    "APPROVED_PENDING_RELEASE": frozenset(
        {"PUBLISHED", "RETURNED", "REJECTED"}
    ),
    "PUBLISHED": frozenset(),
    "RETURNED": frozenset(),
    "REJECTED": frozenset(),
    "FAILED": frozenset(),
    "CANCELLED": frozenset(),
}
_IMMUTABLE_TASK_FIELDS = (
    "name",
    "build_mode",
    "semantic_contract_version",
    "pipeline_version",
    "model_scene",
    "config_hash",
    "created_by",
    "rebuild_reason",
)
_IMMUTABLE_UNIT_FIELDS = (
    "doc_id",
    "doc_title",
    "unit_id",
    "unit_revision_id",
    "path",
)


class UnitRevisionClaimed(RuntimeError):
    """政策单元或其修订版已被其他构建任务占用。"""

    def __init__(
        self,
        *,
        doc_id: str,
        unit_id: str,
        unit_revision_id: str,
        task_id: str,
    ) -> None:
        self.doc_id = doc_id
        self.unit_id = unit_id
        self.unit_revision_id = unit_revision_id
        self.task_id = task_id
        super().__init__(
            f"政策单元 {doc_id}/{unit_id}（修订版 {unit_revision_id}）"
            f"已由构建任务 {task_id} 占用"
        )


class KnowledgeBuildTaskNotFound(KeyError):
    """构建任务不存在。"""

    def __init__(self, task_id: str) -> None:
        self.task_id = task_id
        super().__init__(f"构建任务 {task_id} 不存在")


class KnowledgeBuildTaskVersionConflict(RuntimeError):
    """构建任务已被其他请求更新。"""

    def __init__(self, task_id: str) -> None:
        self.task_id = task_id
        super().__init__(f"构建任务 {task_id} 版本冲突，请刷新后重试")


class InvalidKnowledgeBuildTaskTransition(ValueError):
    """构建任务状态迁移不合法。"""

    def __init__(
        self,
        task_id: str,
        current_status: BuildTaskStatus,
        next_status: BuildTaskStatus,
    ) -> None:
        self.task_id = task_id
        self.current_status = current_status
        self.next_status = next_status
        super().__init__(
            f"构建任务 {task_id} 不允许从状态 {current_status} "
            f"迁移到 {next_status}"
        )


class KnowledgeBuildTaskImmutableFieldError(ValueError):
    """构建任务创建后的来源身份字段不可变更。"""

    def __init__(self, task_id: str, field_name: str) -> None:
        self.task_id = task_id
        self.field_name = field_name
        super().__init__(f"构建任务 {task_id} 的不可变字段 {field_name} 不允许修改")


class KnowledgeBuildStore(Protocol):
    def create_with_claims(self, task: KnowledgeBuildTask) -> KnowledgeBuildTask: ...

    def save(self, task: KnowledgeBuildTask) -> KnowledgeBuildTask: ...

    def get(self, task_id: str) -> KnowledgeBuildTask | None: ...

    def list(self) -> list[KnowledgeBuildTask]: ...

    def get_claim(self, doc_id: str, unit_id: str) -> UnitBuildClaim | None: ...

    def release_claims(self, task_id: str) -> None: ...

    def fail_and_release(
        self,
        task_id: str,
        *,
        error_code: str,
        error_message: str,
        result_change_set_id: str | None = None,
    ) -> KnowledgeBuildTask: ...


def _validate_unique_task_units(task: KnowledgeBuildTask) -> None:
    logical_units: set[tuple[str, str]] = set()
    revisions: set[str] = set()
    for unit in task.units:
        logical_key = (unit.doc_id, unit.unit_id)
        if logical_key in logical_units:
            msg = f"任务 {task.task_id} 中存在重复逻辑单元 {unit.doc_id}/{unit.unit_id}"
            raise ValueError(msg)
        if unit.unit_revision_id in revisions:
            msg = (
                f"任务 {task.task_id} 中存在重复单元修订版 "
                f"{unit.unit_revision_id}"
            )
            raise ValueError(msg)
        logical_units.add(logical_key)
        revisions.add(unit.unit_revision_id)


def _prepare_saved_task(
    current: KnowledgeBuildTask,
    snapshot: KnowledgeBuildTask,
) -> KnowledgeBuildTask:
    _validate_immutable_task_fields(current, snapshot)
    if snapshot.updated_at != current.updated_at:
        raise KnowledgeBuildTaskVersionConflict(snapshot.task_id)
    _validate_transition(current, snapshot)
    return _merge_saved_task(current, snapshot)


def _validate_transition(
    current: KnowledgeBuildTask,
    snapshot: KnowledgeBuildTask,
) -> None:
    if (
        snapshot.status != current.status
        and snapshot.status not in _LEGAL_TRANSITIONS[current.status]
    ):
        raise InvalidKnowledgeBuildTaskTransition(
            snapshot.task_id,
            current.status,
            snapshot.status,
        )


def _merge_saved_task(
    current: KnowledgeBuildTask,
    snapshot: KnowledgeBuildTask,
) -> KnowledgeBuildTask:
    updated_at = utc_now()
    if updated_at <= current.updated_at:
        updated_at = current.updated_at + timedelta(microseconds=1)
    return snapshot.model_copy(
        update={"created_at": current.created_at, "updated_at": updated_at},
        deep=True,
    )


def _validate_immutable_task_fields(
    current: KnowledgeBuildTask,
    snapshot: KnowledgeBuildTask,
) -> None:
    for field_name in _IMMUTABLE_TASK_FIELDS:
        if getattr(snapshot, field_name) != getattr(current, field_name):
            raise KnowledgeBuildTaskImmutableFieldError(
                snapshot.task_id,
                field_name,
            )
    if len(snapshot.units) != len(current.units):
        raise KnowledgeBuildTaskImmutableFieldError(snapshot.task_id, "units")
    for index, (current_unit, snapshot_unit) in enumerate(
        zip(current.units, snapshot.units, strict=True)
    ):
        for field_name in _IMMUTABLE_UNIT_FIELDS:
            if getattr(snapshot_unit, field_name) != getattr(current_unit, field_name):
                raise KnowledgeBuildTaskImmutableFieldError(
                    snapshot.task_id,
                    f"units[{index}].{field_name}",
                )


def _require_terminal_task(
    task: KnowledgeBuildTask | None,
    task_id: str,
) -> KnowledgeBuildTask:
    if task is None:
        raise KnowledgeBuildTaskNotFound(task_id)
    if task.status not in _TERMINAL_STATUSES:
        msg = f"构建任务 {task_id} 尚未进入终态，不能释放单元占用"
        raise ValueError(msg)
    return task


def _failed_task(
    current: KnowledgeBuildTask,
    *,
    error_code: str,
    error_message: str,
    result_change_set_id: str | None,
) -> KnowledgeBuildTask:
    failed_units = [
        unit.model_copy(
            update={
                "status": "FAILED",
                "error_code": error_code,
                "error_message": error_message,
            },
            deep=True,
        )
        for unit in current.units
    ]
    failed = current.model_copy(
        update={
            "status": "FAILED",
            "units": failed_units,
            "result_change_set_id": result_change_set_id
            or current.result_change_set_id,
            "finished_at": utc_now(),
        },
        deep=True,
    )
    return _merge_saved_task(current, failed)


class InMemoryKnowledgeBuildStore:
    """线程安全的内存构建任务存储。"""

    def __init__(self) -> None:
        self._lock = RLock()
        self._tasks: dict[str, KnowledgeBuildTask] = {}
        self._claims_by_logical: dict[tuple[str, str], UnitBuildClaim] = {}
        self._claims_by_revision: dict[str, UnitBuildClaim] = {}

    def create_with_claims(self, task: KnowledgeBuildTask) -> KnowledgeBuildTask:
        snapshot = task.model_copy(deep=True)
        with self._lock:
            _validate_unique_task_units(snapshot)
            if snapshot.task_id in self._tasks:
                msg = f"构建任务 {snapshot.task_id} 已存在"
                raise ValueError(msg)

            pending_claims: list[UnitBuildClaim] = []
            for unit in snapshot.units:
                logical_key = (unit.doc_id, unit.unit_id)
                existing = self._claims_by_logical.get(logical_key)
                if existing is None:
                    existing = self._claims_by_revision.get(unit.unit_revision_id)
                if existing is not None:
                    raise UnitRevisionClaimed(
                        doc_id=existing.doc_id,
                        unit_id=existing.unit_id,
                        unit_revision_id=existing.unit_revision_id,
                        task_id=existing.task_id,
                    )
                pending_claims.append(
                    UnitBuildClaim(
                        doc_id=unit.doc_id,
                        unit_id=unit.unit_id,
                        unit_revision_id=unit.unit_revision_id,
                        task_id=snapshot.task_id,
                        claimed_at=utc_now(),
                    )
                )

            self._tasks[snapshot.task_id] = snapshot
            for claim in pending_claims:
                self._claims_by_logical[(claim.doc_id, claim.unit_id)] = claim
                self._claims_by_revision[claim.unit_revision_id] = claim
            return snapshot.model_copy(deep=True)

    def save(self, task: KnowledgeBuildTask) -> KnowledgeBuildTask:
        snapshot = task.model_copy(deep=True)
        with self._lock:
            current = self._tasks.get(snapshot.task_id)
            if current is None:
                raise KnowledgeBuildTaskNotFound(snapshot.task_id)
            saved = _prepare_saved_task(current, snapshot)
            self._tasks[saved.task_id] = saved
            if saved.status in _TERMINAL_STATUSES:
                self._release_claims_unlocked(saved.task_id)
            return saved.model_copy(deep=True)

    def get(self, task_id: str) -> KnowledgeBuildTask | None:
        with self._lock:
            task = self._tasks.get(task_id)
            return task.model_copy(deep=True) if task is not None else None

    def list(self) -> list[KnowledgeBuildTask]:
        with self._lock:
            ordered = sorted(
                self._tasks.values(),
                key=lambda task: task.created_at,
                reverse=True,
            )
            return [task.model_copy(deep=True) for task in ordered]

    def get_claim(self, doc_id: str, unit_id: str) -> UnitBuildClaim | None:
        with self._lock:
            claim = self._claims_by_logical.get((doc_id, unit_id))
            return claim.model_copy(deep=True) if claim is not None else None

    def release_claims(self, task_id: str) -> None:
        with self._lock:
            _require_terminal_task(self._tasks.get(task_id), task_id)
            self._release_claims_unlocked(task_id)

    def fail_and_release(
        self,
        task_id: str,
        *,
        error_code: str,
        error_message: str,
        result_change_set_id: str | None = None,
    ) -> KnowledgeBuildTask:
        with self._lock:
            current = self._tasks.get(task_id)
            if current is None:
                raise KnowledgeBuildTaskNotFound(task_id)
            if current.status in _TERMINAL_STATUSES:
                self._release_claims_unlocked(task_id)
                return current.model_copy(deep=True)
            failed = _failed_task(
                current,
                error_code=error_code,
                error_message=error_message,
                result_change_set_id=result_change_set_id,
            )
            self._tasks[task_id] = failed
            self._release_claims_unlocked(task_id)
            return failed.model_copy(deep=True)

    def _release_claims_unlocked(self, task_id: str) -> None:
        logical_keys = [
            key
            for key, claim in self._claims_by_logical.items()
            if claim.task_id == task_id
        ]
        for logical_key in logical_keys:
            claim = self._claims_by_logical.pop(logical_key)
            self._claims_by_revision.pop(claim.unit_revision_id, None)


_SCHEMA = """
CREATE TABLE IF NOT EXISTS policy_knowledge_build_tasks (
    task_id VARCHAR(64) PRIMARY KEY,
    status VARCHAR(40) NOT NULL,
    payload JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS policy_knowledge_unit_claims (
    doc_id VARCHAR(128) NOT NULL,
    unit_id VARCHAR(128) NOT NULL,
    unit_revision_id VARCHAR(96) NOT NULL UNIQUE,
    task_id VARCHAR(64) NOT NULL,
    claimed_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (doc_id, unit_id)
);
"""


_UPDATE_TASK = """
UPDATE policy_knowledge_build_tasks
SET status = %s,
    payload = %s,
    updated_at = %s
WHERE task_id = %s AND updated_at = %s
RETURNING payload
"""


class PostgreSQLKnowledgeBuildStore:
    """使用唯一约束仲裁并发占用的 PostgreSQL 存储。"""

    def __init__(self, database_url: str | None = None) -> None:
        self._database_url = database_url
        self._client: PostgreSQLClient | None = None
        self._lock = RLock()

    def _get_client(self) -> PostgreSQLClient:
        with self._lock:
            if self._client is None:
                from src.config.production import DATABASE_URL
                from src.data_platform.storage.postgresql.client import PostgreSQLClient

                self._client = PostgreSQLClient(self._database_url or DATABASE_URL)
                for statement in _SCHEMA.split(";"):
                    if statement.strip():
                        self._client.execute(statement)
            return self._client

    def create_with_claims(self, task: KnowledgeBuildTask) -> KnowledgeBuildTask:
        snapshot = task.model_copy(deep=True)
        _validate_unique_task_units(snapshot)
        with self._lock:
            with self._get_client().transaction() as connection:
                self._execute_transaction(
                    connection,
                    """
                    INSERT INTO policy_knowledge_build_tasks
                        (task_id, status, payload, created_at, updated_at)
                    VALUES (%s, %s, %s, %s, %s)
                    """,
                    self._task_params(snapshot),
                )
                for unit in snapshot.units:
                    claimed_at = utc_now()
                    inserted = self._execute_transaction(
                        connection,
                        """
                        INSERT INTO policy_knowledge_unit_claims
                            (doc_id, unit_id, unit_revision_id, task_id, claimed_at)
                        VALUES (%s, %s, %s, %s, %s)
                        ON CONFLICT DO NOTHING
                        RETURNING unit_revision_id
                        """,
                        (
                            unit.doc_id,
                            unit.unit_id,
                            unit.unit_revision_id,
                            snapshot.task_id,
                            claimed_at,
                        ),
                        fetch_one=True,
                    )
                    if inserted is None:
                        existing = self._execute_transaction(
                            connection,
                            """
                            SELECT doc_id, unit_id, unit_revision_id, task_id, claimed_at
                            FROM policy_knowledge_unit_claims
                            WHERE (doc_id = %s AND unit_id = %s)
                               OR unit_revision_id = %s
                            LIMIT 1
                            """,
                            (unit.doc_id, unit.unit_id, unit.unit_revision_id),
                            fetch_one=True,
                        )
                        if existing is None:
                            msg = "单元占用冲突，但未能读取已有占用记录"
                            raise RuntimeError(msg)
                        claim = self._claim_from_record(existing)
                        raise UnitRevisionClaimed(
                            doc_id=claim.doc_id,
                            unit_id=claim.unit_id,
                            unit_revision_id=claim.unit_revision_id,
                            task_id=claim.task_id,
                        )
        return snapshot.model_copy(deep=True)

    def save(self, task: KnowledgeBuildTask) -> KnowledgeBuildTask:
        snapshot = task.model_copy(deep=True)
        with self._lock:
            client = self._get_client()
            with client.transaction() as connection:
                current_record = self._execute_transaction(
                    connection,
                    """
                    SELECT payload
                    FROM policy_knowledge_build_tasks
                    WHERE task_id = %s
                    """,
                    (snapshot.task_id,),
                    fetch_one=True,
                )
                if current_record is None:
                    raise KnowledgeBuildTaskNotFound(snapshot.task_id)
                current = self._task_from_payload(
                    self._record_value(current_record, "payload", 0)
                )
                _validate_immutable_task_fields(current, snapshot)
                if snapshot.updated_at == current.updated_at:
                    _validate_transition(current, snapshot)
                saved = _merge_saved_task(current, snapshot)
                updated_record = self._execute_transaction(
                    connection,
                    _UPDATE_TASK,
                    (
                        saved.status,
                        saved.model_dump_json(),
                        saved.updated_at,
                        saved.task_id,
                        snapshot.updated_at,
                    ),
                    fetch_one=True,
                )
                if updated_record is None:
                    existing = self._execute_transaction(
                        connection,
                        """
                        SELECT task_id
                        FROM policy_knowledge_build_tasks
                        WHERE task_id = %s
                        """,
                        (snapshot.task_id,),
                        fetch_one=True,
                    )
                    if existing is None:
                        raise KnowledgeBuildTaskNotFound(snapshot.task_id)
                    raise KnowledgeBuildTaskVersionConflict(snapshot.task_id)
                saved = self._task_from_payload(
                    self._record_value(updated_record, "payload", 0)
                )
                if saved.status in _TERMINAL_STATUSES:
                    self._execute_transaction(
                        connection,
                        "DELETE FROM policy_knowledge_unit_claims WHERE task_id = %s",
                        (saved.task_id,),
                    )
            return saved.model_copy(deep=True)

    def get(self, task_id: str) -> KnowledgeBuildTask | None:
        with self._lock:
            rows = self._get_client().execute(
                "SELECT payload FROM policy_knowledge_build_tasks WHERE task_id = %s",
                (task_id,),
            )
            return self._task_from_payload(rows[0]["payload"]) if rows else None

    def list(self) -> list[KnowledgeBuildTask]:
        with self._lock:
            rows = self._get_client().execute(
                """
                SELECT payload
                FROM policy_knowledge_build_tasks
                ORDER BY created_at DESC
                """
            )
            return [self._task_from_payload(row["payload"]) for row in rows]

    def get_claim(self, doc_id: str, unit_id: str) -> UnitBuildClaim | None:
        with self._lock:
            rows = self._get_client().execute(
                """
                SELECT doc_id, unit_id, unit_revision_id, task_id, claimed_at
                FROM policy_knowledge_unit_claims
                WHERE doc_id = %s AND unit_id = %s
                """,
                (doc_id, unit_id),
            )
            return UnitBuildClaim.model_validate(rows[0]) if rows else None

    def release_claims(self, task_id: str) -> None:
        with self._lock:
            with self._get_client().transaction() as connection:
                record = self._execute_transaction(
                    connection,
                    """
                    SELECT status
                    FROM policy_knowledge_build_tasks
                    WHERE task_id = %s
                    """,
                    (task_id,),
                    fetch_one=True,
                )
                if record is None:
                    raise KnowledgeBuildTaskNotFound(task_id)
                status = self._record_value(record, "status", 0)
                if status not in _TERMINAL_STATUSES:
                    msg = (
                        f"构建任务 {task_id} 尚未进入终态，"
                        "不能释放单元占用"
                    )
                    raise ValueError(msg)
                self._execute_transaction(
                    connection,
                    "DELETE FROM policy_knowledge_unit_claims WHERE task_id = %s",
                    (task_id,),
                )

    def fail_and_release(
        self,
        task_id: str,
        *,
        error_code: str,
        error_message: str,
        result_change_set_id: str | None = None,
    ) -> KnowledgeBuildTask:
        with self._lock:
            with self._get_client().transaction() as connection:
                current_record = self._execute_transaction(
                    connection,
                    """
                    SELECT payload
                    FROM policy_knowledge_build_tasks
                    WHERE task_id = %s
                    FOR UPDATE
                    """,
                    (task_id,),
                    fetch_one=True,
                )
                if current_record is None:
                    raise KnowledgeBuildTaskNotFound(task_id)
                current = self._task_from_payload(
                    self._record_value(current_record, "payload", 0)
                )
                if current.status in _TERMINAL_STATUSES:
                    failed = current
                else:
                    failed = _failed_task(
                        current,
                        error_code=error_code,
                        error_message=error_message,
                        result_change_set_id=result_change_set_id,
                    )
                    updated_record = self._execute_transaction(
                        connection,
                        _UPDATE_TASK,
                        (
                            failed.status,
                            failed.model_dump_json(),
                            failed.updated_at,
                            failed.task_id,
                            current.updated_at,
                        ),
                        fetch_one=True,
                    )
                    if updated_record is None:
                        raise KnowledgeBuildTaskVersionConflict(task_id)
                    failed = self._task_from_payload(
                        self._record_value(updated_record, "payload", 0)
                    )
                self._execute_transaction(
                    connection,
                    "DELETE FROM policy_knowledge_unit_claims WHERE task_id = %s",
                    (task_id,),
                )
                return failed.model_copy(deep=True)

    @staticmethod
    def _task_params(task: KnowledgeBuildTask) -> tuple[Any, ...]:
        return (
            task.task_id,
            task.status,
            task.model_dump_json(),
            task.created_at,
            task.updated_at,
        )

    @staticmethod
    def _execute_transaction(
        connection: Any,
        sql: str,
        params: tuple[Any, ...],
        *,
        fetch_one: bool = False,
    ) -> Any:
        with connection.cursor() as cursor:
            cursor.execute(sql, params)
            return cursor.fetchone() if fetch_one else None

    @staticmethod
    def _claim_from_record(record: Any) -> UnitBuildClaim:
        if isinstance(record, Mapping):
            return UnitBuildClaim.model_validate(record)
        if isinstance(record, Sequence) and not isinstance(record, (str, bytes)):
            return UnitBuildClaim(
                doc_id=record[0],
                unit_id=record[1],
                unit_revision_id=record[2],
                task_id=record[3],
                claimed_at=record[4],
            )
        msg = "PostgreSQL 返回了无法识别的单元占用记录"
        raise TypeError(msg)

    @staticmethod
    def _record_value(record: Any, field: str, index: int) -> Any:
        if isinstance(record, Mapping):
            return record[field]
        if isinstance(record, Sequence) and not isinstance(record, (str, bytes)):
            return record[index]
        msg = "PostgreSQL 返回了无法识别的记录"
        raise TypeError(msg)

    @staticmethod
    def _task_from_payload(payload: Any) -> KnowledgeBuildTask:
        if isinstance(payload, bytes):
            payload = payload.decode("utf-8")
        data = json.loads(payload) if isinstance(payload, str) else payload
        return KnowledgeBuildTask.model_validate(data).model_copy(deep=True)
