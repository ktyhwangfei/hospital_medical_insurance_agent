"""已发布知识快照存储：内存 + PostgreSQL 双实现（V4.1 §27.4）。"""
from __future__ import annotations

from typing import Protocol

from src.knowledge_extension.rule_explanation.published_snapshot_models import PublishedSnapshot


class PublishedSnapshotStore(Protocol):
    def save(self, snapshot: PublishedSnapshot) -> PublishedSnapshot: ...
    def get(self, snapshot_id: str) -> PublishedSnapshot | None: ...
    def list(self, active_only: bool = False) -> list[PublishedSnapshot]: ...


class InMemoryPublishedSnapshotStore:
    """测试与本地回退使用。"""

    def __init__(self) -> None:
        self._items: dict[str, PublishedSnapshot] = {}

    def save(self, snapshot: PublishedSnapshot) -> PublishedSnapshot:
        self._items[snapshot.snapshot_id] = snapshot.model_copy(deep=True)
        return snapshot.model_copy(deep=True)

    def get(self, snapshot_id: str) -> PublishedSnapshot | None:
        item = self._items.get(snapshot_id)
        return item.model_copy(deep=True) if item else None

    def list(self, active_only: bool = False) -> list[PublishedSnapshot]:
        items = list(self._items.values())
        if active_only:
            items = [item for item in items if item.replaced_by is None]
        return [item.model_copy(deep=True) for item in items]


_SCHEMA = """
CREATE TABLE IF NOT EXISTS published_knowledge_snapshots (
    snapshot_id VARCHAR(64) PRIMARY KEY,
    doc_id VARCHAR(128),
    policy_scope JSONB NOT NULL DEFAULT '{}'::jsonb,
    semantic_contract_version VARCHAR(64),
    rules_collection VARCHAR(256) NOT NULL,
    facts_collection VARCHAR(256) NOT NULL,
    source_change_set_id VARCHAR(64),
    immutable BOOLEAN NOT NULL DEFAULT TRUE,
    published_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    published_by VARCHAR(128) NOT NULL,
    rollback_of VARCHAR(64),
    replaced_by VARCHAR(64)
);
CREATE INDEX IF NOT EXISTS idx_snapshot_active ON published_knowledge_snapshots(replaced_by);
"""


class PostgresPublishedSnapshotStore:
    """PublishedSnapshotStore 的 PostgreSQL adapter，懒建表。"""

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

    def save(self, snapshot: PublishedSnapshot) -> PublishedSnapshot:
        self._get_client().execute(
            """INSERT INTO published_knowledge_snapshots
               (snapshot_id, doc_id, policy_scope, semantic_contract_version, rules_collection,
                facts_collection, source_change_set_id, immutable, published_at, published_by,
                rollback_of, replaced_by)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
               ON CONFLICT (snapshot_id) DO UPDATE SET
                 published_by=EXCLUDED.published_by, rollback_of=EXCLUDED.rollback_of,
                 replaced_by=EXCLUDED.replaced_by""",
            (
                snapshot.snapshot_id,
                snapshot.doc_id,
                __import__("json").dumps(snapshot.policy_scope, ensure_ascii=False),
                snapshot.semantic_contract_version,
                snapshot.rules_collection,
                snapshot.facts_collection,
                snapshot.source_change_set_id,
                snapshot.immutable,
                snapshot.published_at,
                snapshot.published_by,
                snapshot.rollback_of,
                snapshot.replaced_by,
            ),
        )
        return snapshot

    def get(self, snapshot_id: str) -> PublishedSnapshot | None:
        rows = self._get_client().execute(
            "SELECT * FROM published_knowledge_snapshots WHERE snapshot_id=%s",
            (snapshot_id,),
        )
        return self._row(rows[0]) if rows else None

    def list(self, active_only: bool = False) -> list[PublishedSnapshot]:
        sql = "SELECT * FROM published_knowledge_snapshots"
        if active_only:
            sql += " WHERE replaced_by IS NULL"
        sql += " ORDER BY published_at DESC"
        return [self._row(row) for row in self._get_client().execute(sql)]

    @staticmethod
    def _row(row: dict) -> PublishedSnapshot:
        result = dict(row)
        if isinstance(result.get("policy_scope"), str):
            result["policy_scope"] = __import__("json").loads(result["policy_scope"])
        return PublishedSnapshot(**result)
