"""人工决策任务存储：内存 + PostgreSQL 双实现（V4.1 §4.5）。"""
from __future__ import annotations

from typing import Protocol

from src.knowledge_extension.rule_explanation.decision_task_models import DecisionTask


class DecisionTaskStore(Protocol):
    def save(self, task: DecisionTask) -> DecisionTask: ...
    def get(self, task_id: str) -> DecisionTask | None: ...
    def list(self, status: str = "", task_type: str = "", scope: str = "") -> list[DecisionTask]: ...


class InMemoryDecisionTaskStore:
    """测试与本地回退使用。"""

    def __init__(self) -> None:
        self._items: dict[str, DecisionTask] = {}

    def save(self, task: DecisionTask) -> DecisionTask:
        self._items[task.task_id] = task.model_copy(deep=True)
        return task.model_copy(deep=True)

    def get(self, task_id: str) -> DecisionTask | None:
        item = self._items.get(task_id)
        return item.model_copy(deep=True) if item else None

    def list(self, status: str = "", task_type: str = "", scope: str = "") -> list[DecisionTask]:
        items = list(self._items.values())
        if status:
            items = [item for item in items if item.status == status]
        if task_type:
            items = [item for item in items if item.task_type == task_type]
        if scope:
            items = [item for item in items if item.blocking_scope == scope]
        items.sort(key=lambda item: item.created_at, reverse=True)
        return [item.model_copy(deep=True) for item in items]


_SCHEMA = """
CREATE TABLE IF NOT EXISTS policy_knowledge_decision_tasks (
    task_id VARCHAR(64) PRIMARY KEY,
    task_type VARCHAR(64) NOT NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'PENDING',
    blocking_scope VARCHAR(128),
    payload JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_decision_task_status ON policy_knowledge_decision_tasks(status);
CREATE INDEX IF NOT EXISTS idx_decision_task_scope ON policy_knowledge_decision_tasks(blocking_scope);
"""


class PostgresDecisionTaskStore:
    """DecisionTaskStore 的 PostgreSQL adapter，懒建表。"""

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

    def save(self, task: DecisionTask) -> DecisionTask:
        payload = task.model_dump_json()
        self._get_client().execute(
            """INSERT INTO policy_knowledge_decision_tasks
               (task_id, task_type, status, blocking_scope, payload, created_at)
               VALUES (%s, %s, %s, %s, %s, %s)
               ON CONFLICT (task_id) DO UPDATE SET
                 status=EXCLUDED.status, blocking_scope=EXCLUDED.blocking_scope, payload=EXCLUDED.payload""",
            (
                task.task_id, task.task_type, task.status, task.blocking_scope,
                payload, task.created_at,
            ),
        )
        return task

    def get(self, task_id: str) -> DecisionTask | None:
        rows = self._get_client().execute(
            "SELECT payload FROM policy_knowledge_decision_tasks WHERE task_id=%s",
            (task_id,),
        )
        return self._parse(rows[0]["payload"]) if rows else None

    def list(self, status: str = "", task_type: str = "", scope: str = "") -> list[DecisionTask]:
        conditions = []
        params: list[str] = []
        if status:
            conditions.append("status=%s")
            params.append(status)
        if task_type:
            conditions.append("task_type=%s")
            params.append(task_type)
        if scope:
            conditions.append("blocking_scope=%s")
            params.append(scope)
        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        rows = self._get_client().execute(
            f"SELECT payload FROM policy_knowledge_decision_tasks {where} ORDER BY created_at DESC",
            tuple(params),
        )
        return [self._parse(row["payload"]) for row in rows]

    @staticmethod
    def _parse(payload) -> DecisionTask:
        import json
        data = json.loads(payload) if isinstance(payload, str) else payload
        return DecisionTask.model_validate(data)
