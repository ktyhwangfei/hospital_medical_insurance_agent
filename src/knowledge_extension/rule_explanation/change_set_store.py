"""知识变更集存储：内存 + PostgreSQL 双实现（V4.1 §27.2）。"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from threading import RLock
from typing import Protocol

from src.knowledge_extension.rule_explanation.change_set_models import KnowledgeChangeSet


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

    @staticmethod
    def _parse(payload) -> KnowledgeChangeSet:
        data = json.loads(payload) if isinstance(payload, str) else payload
        return KnowledgeChangeSet.model_validate(data)
