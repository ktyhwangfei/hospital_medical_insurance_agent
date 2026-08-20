"""知识变更集存储：内存 + PostgreSQL 双实现（V4.1 §27.2）。"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from threading import RLock
from typing import TYPE_CHECKING, Protocol

from src.knowledge_extension.rule_explanation.change_set_models import KnowledgeChangeSet

if TYPE_CHECKING:
    from src.knowledge_extension.rule_explanation.knowledge_build_models import KnowledgeBuildTask
    from src.knowledge_extension.rule_explanation.knowledge_build_store import KnowledgeBuildStore


class ChangeSetStore(Protocol):
    def save(self, change_set: KnowledgeChangeSet) -> KnowledgeChangeSet: ...
    def get(self, change_set_id: str) -> KnowledgeChangeSet | None: ...
    def list(self, doc_id: str = "") -> list[KnowledgeChangeSet]: ...
    def update_status(
        self, change_set_id: str, status: str, decision: dict | None = None
    ) -> KnowledgeChangeSet | None: ...
    def transition_status(
        self,
        change_set_id: str,
        *,
        allowed_statuses: set[str],
        target_status: str,
        decision: dict | None = None,
    ) -> KnowledgeChangeSet | None: ...

    def transition_status_with_task(
        self,
        change_set_id: str,
        *,
        allowed_statuses: set[str],
        target_status: str,
        decision: dict | None,
        build_store: "KnowledgeBuildStore",
        task: "KnowledgeBuildTask",
    ) -> KnowledgeChangeSet | None: ...


class InMemoryChangeSetStore:
    """测试与本地回退（USE_MEMORY_STORAGE=1）使用。"""

    def __init__(self) -> None:
        self._lock = RLock()
        self._items: dict[str, KnowledgeChangeSet] = {}

    def save(self, change_set: KnowledgeChangeSet) -> KnowledgeChangeSet:
        with self._lock:
            self._items[change_set.change_set_id] = change_set.model_copy(deep=True)
            return change_set.model_copy(deep=True)

    def get(self, change_set_id: str) -> KnowledgeChangeSet | None:
        with self._lock:
            item = self._items.get(change_set_id)
            return item.model_copy(deep=True) if item else None

    def list(self, doc_id: str = "") -> list[KnowledgeChangeSet]:
        with self._lock:
            items = list(self._items.values())
            if doc_id:
                items = [item for item in items if item.doc_id == doc_id]
            return [item.model_copy(deep=True) for item in items]

    def update_status(
        self, change_set_id: str, status: str, decision: dict | None = None
    ) -> KnowledgeChangeSet | None:
        with self._lock:
            item = self._items.get(change_set_id)
            if item is None:
                return None
            return self._save_status_unlocked(item, status, decision)

    def transition_status(
        self,
        change_set_id: str,
        *,
        allowed_statuses: set[str],
        target_status: str,
        decision: dict | None = None,
    ) -> KnowledgeChangeSet | None:
        with self._lock:
            item = self._items.get(change_set_id)
            if item is None or item.status not in allowed_statuses:
                return None
            return self._save_status_unlocked(item, target_status, decision)

    def transition_status_with_task(
        self,
        change_set_id: str,
        *,
        allowed_statuses: set[str],
        target_status: str,
        decision: dict | None,
        build_store: "KnowledgeBuildStore",
        task: "KnowledgeBuildTask",
    ) -> KnowledgeChangeSet | None:
        from src.knowledge_extension.rule_explanation.knowledge_build_store import (
            InMemoryKnowledgeBuildStore,
            _prepare_saved_task,
            _TERMINAL_STATUSES,
        )

        if not isinstance(build_store, InMemoryKnowledgeBuildStore):
            raise TypeError("内存变更集必须与内存构建任务存储配套使用")
        with self._lock, build_store._lock:
            item = self._items.get(change_set_id)
            current_task = build_store._tasks.get(task.task_id)
            if item is None or current_task is None:
                return None
            if item.status not in allowed_statuses and item.status != target_status:
                return None
            saved_task = (
                current_task
                if current_task.status == task.status
                else _prepare_saved_task(current_task, task)
            )
            updated = (
                item
                if item.status == target_status
                else item.model_copy(update={
                    "status": target_status,
                    "review_decision": (
                        decision if decision is not None else item.review_decision
                    ),
                    "updated_at": datetime.now(timezone.utc),
                })
            )
            self._items[change_set_id] = updated
            build_store._tasks[saved_task.task_id] = saved_task
            if saved_task.status in _TERMINAL_STATUSES:
                build_store._release_claims_unlocked(saved_task.task_id)
            return updated.model_copy(deep=True)

    def _save_status_unlocked(
        self,
        item: KnowledgeChangeSet,
        status: str,
        decision: dict | None,
    ) -> KnowledgeChangeSet:
        updated = item.model_copy(update={
            "status": status,
            "review_decision": decision if decision is not None else item.review_decision,
            "updated_at": datetime.now(timezone.utc),
        })
        self._items[item.change_set_id] = updated
        return updated.model_copy(deep=True)


_SCHEMA = """
CREATE TABLE IF NOT EXISTS policy_knowledge_change_sets (
    change_set_id VARCHAR(64) PRIMARY KEY,
    source_document_version_id VARCHAR(128) NOT NULL,
    doc_id VARCHAR(128) NOT NULL,
    doc_title VARCHAR(512) NOT NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'PENDING_REVIEW',
    payload JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_change_set_doc ON policy_knowledge_change_sets(doc_id);
"""


class PostgresChangeSetStore:
    """ChangeSetStore 的 PostgreSQL adapter，懒建表。"""

    def __init__(self, database_url: str | None = None) -> None:
        self._database_url = database_url
        self._client = None

    def _get_client(self):
        if self._client is None:
            from src.config.production import DATABASE_URL
            from src.data_platform.storage.postgresql.client import PostgreSQLClient

            self._client = PostgreSQLClient(self._database_url or DATABASE_URL)
            for statement in _SCHEMA.split(";"):
                if statement.strip():
                    self._client.execute(statement)
        return self._client

    def save(self, change_set: KnowledgeChangeSet) -> KnowledgeChangeSet:
        payload = change_set.model_dump_json()
        self._get_client().execute(
            """INSERT INTO policy_knowledge_change_sets
               (change_set_id, source_document_version_id, doc_id, doc_title, status, payload, created_at, updated_at)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
               ON CONFLICT (change_set_id) DO UPDATE SET
                 status=EXCLUDED.status, payload=EXCLUDED.payload, updated_at=EXCLUDED.updated_at""",
            (
                change_set.change_set_id,
                change_set.source_document_version_id,
                change_set.doc_id,
                change_set.doc_title,
                change_set.status,
                payload,
                change_set.created_at,
                change_set.updated_at,
            ),
        )
        return change_set

    def get(self, change_set_id: str) -> KnowledgeChangeSet | None:
        rows = self._get_client().execute(
            "SELECT payload FROM policy_knowledge_change_sets WHERE change_set_id=%s",
            (change_set_id,),
        )
        return self._parse(rows[0]["payload"]) if rows else None

    def list(self, doc_id: str = "") -> list[KnowledgeChangeSet]:
        if doc_id:
            rows = self._get_client().execute(
                "SELECT payload FROM policy_knowledge_change_sets WHERE doc_id=%s ORDER BY updated_at DESC",
                (doc_id,),
            )
        else:
            rows = self._get_client().execute(
                "SELECT payload FROM policy_knowledge_change_sets ORDER BY updated_at DESC"
            )
        return [self._parse(row["payload"]) for row in rows]

    def update_status(
        self, change_set_id: str, status: str, decision: dict | None = None
    ) -> KnowledgeChangeSet | None:
        change_set = self.get(change_set_id)
        if change_set is None:
            return None
        updated = change_set.model_copy(update={
            "status": status,
            "review_decision": decision if decision is not None else change_set.review_decision,
            "updated_at": datetime.now(timezone.utc),
        })
        return self.save(updated)

    def transition_status(
        self,
        change_set_id: str,
        *,
        allowed_statuses: set[str],
        target_status: str,
        decision: dict | None = None,
    ) -> KnowledgeChangeSet | None:
        current = self.get(change_set_id)
        if current is None or current.status not in allowed_statuses:
            return None
        updated = current.model_copy(update={
            "status": target_status,
            "review_decision": (
                decision if decision is not None else current.review_decision
            ),
            "updated_at": datetime.now(timezone.utc),
        })
        rows = self._get_client().execute(
            """UPDATE policy_knowledge_change_sets
               SET status=%s, payload=%s, updated_at=%s
               WHERE change_set_id=%s AND status=%s
               RETURNING payload""",
            (
                updated.status,
                updated.model_dump_json(),
                updated.updated_at,
                updated.change_set_id,
                current.status,
            ),
        )
        return self._parse(rows[0]["payload"]) if rows else None

    def transition_status_with_task(
        self,
        change_set_id: str,
        *,
        allowed_statuses: set[str],
        target_status: str,
        decision: dict | None,
        build_store: "KnowledgeBuildStore",
        task: "KnowledgeBuildTask",
    ) -> KnowledgeChangeSet | None:
        from src.knowledge_extension.rule_explanation.knowledge_build_store import (
            PostgreSQLKnowledgeBuildStore,
            _prepare_saved_task,
            _TERMINAL_STATUSES,
            _UPDATE_TASK,
        )

        if not isinstance(build_store, PostgreSQLKnowledgeBuildStore):
            raise TypeError("PostgreSQL 变更集必须与 PostgreSQL 构建任务存储配套使用")
        client = self._get_client()
        build_client = build_store._get_client()
        if client._database_url != build_client._database_url:
            raise ValueError("变更集与构建任务必须使用同一 PostgreSQL 数据库")
        with build_store._lock, client.transaction() as connection:
            current_record = build_store._execute_transaction(
                connection,
                "SELECT payload FROM policy_knowledge_change_sets "
                "WHERE change_set_id = %s FOR UPDATE",
                (change_set_id,),
                fetch_one=True,
            )
            task_record = build_store._execute_transaction(
                connection,
                "SELECT payload FROM policy_knowledge_build_tasks "
                "WHERE task_id = %s FOR UPDATE",
                (task.task_id,),
                fetch_one=True,
            )
            if current_record is None or task_record is None:
                return None
            current = self._parse(build_store._record_value(current_record, "payload", 0))
            if current.status not in allowed_statuses and current.status != target_status:
                return None
            current_task = build_store._task_from_payload(
                build_store._record_value(task_record, "payload", 0)
            )
            saved_task = (
                current_task
                if current_task.status == task.status
                else _prepare_saved_task(current_task, task)
            )
            updated = current
            if current.status != target_status:
                updated = current.model_copy(update={
                    "status": target_status,
                    "review_decision": (
                        decision if decision is not None else current.review_decision
                    ),
                    "updated_at": datetime.now(timezone.utc),
                })
                changed_record = build_store._execute_transaction(
                    connection,
                    "UPDATE policy_knowledge_change_sets SET status=%s, payload=%s, "
                    "updated_at=%s WHERE change_set_id=%s AND status=%s RETURNING payload",
                    (
                        updated.status,
                        updated.model_dump_json(),
                        updated.updated_at,
                        updated.change_set_id,
                        current.status,
                    ),
                    fetch_one=True,
                )
                if changed_record is None:
                    raise RuntimeError("变更集状态并发更新失败")
                updated = self._parse(
                    build_store._record_value(changed_record, "payload", 0)
                )
            if current_task.status != saved_task.status:
                saved_record = build_store._execute_transaction(
                    connection,
                    _UPDATE_TASK,
                    (
                        saved_task.status,
                        saved_task.model_dump_json(),
                        saved_task.updated_at,
                        saved_task.task_id,
                        task.updated_at,
                    ),
                    fetch_one=True,
                )
                if saved_record is None:
                    raise RuntimeError("构建任务状态并发更新失败")
            if saved_task.status in _TERMINAL_STATUSES:
                build_store._execute_transaction(
                    connection,
                    "DELETE FROM policy_knowledge_unit_claims WHERE task_id = %s",
                    (saved_task.task_id,),
                )
            return updated

    @staticmethod
    def _parse(payload) -> KnowledgeChangeSet:
        data = json.loads(payload) if isinstance(payload, str) else payload
        return KnowledgeChangeSet.model_validate(data)
