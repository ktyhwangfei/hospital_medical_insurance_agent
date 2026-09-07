"""治理 Flow PostgreSQL 存储 — Phase 1（Phase 0 契约冻结 §3.2 双表设计）。

governed_flows：草稿/当前态主表（乐观锁 revision）。
governed_flow_revisions：不可变发布证据；(flow_id) WHERE is_active 部分唯一
索引在库级保证单活跃版本；切换用单条 UPDATE 原子完成（回滚只切指针）。
"""
from __future__ import annotations

import json
from typing import Any

from src.config.production import DATABASE_URL
from src.data_platform.storage.postgresql.client import PostgreSQLClient
from src.domain.governed_flow.models import (
    FlowDefinition,
    FlowNotFoundError,
    FlowPublishedRevision,
    FlowRevisionConflictError,
)

GOVERNED_FLOW_TABLE_SCHEMA = """
CREATE TABLE IF NOT EXISTS governed_flows (
    flow_id VARCHAR(128) PRIMARY KEY,
    name VARCHAR(256) NOT NULL,
    owner VARCHAR(128) NOT NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'draft',
    revision INTEGER NOT NULL DEFAULT 1,
    content_hash VARCHAR(64) NOT NULL DEFAULT '',
    definition JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS governed_flow_revisions (
    revision_id VARCHAR(64) PRIMARY KEY,
    flow_id VARCHAR(128) NOT NULL REFERENCES governed_flows(flow_id) ON DELETE CASCADE,
    flow_revision INTEGER NOT NULL,
    content_hash VARCHAR(64) NOT NULL,
    semantic_revision VARCHAR(128) NOT NULL,
    artifact_hash VARCHAR(64) NOT NULL,
    published_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    published_by VARCHAR(128) NOT NULL,
    definition JSONB NOT NULL,
    is_active BOOLEAN NOT NULL DEFAULT FALSE,
    UNIQUE(flow_id, flow_revision)
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_governed_flow_active_revision
    ON governed_flow_revisions(flow_id) WHERE is_active;
CREATE INDEX IF NOT EXISTS idx_governed_flow_revisions_flow
    ON governed_flow_revisions(flow_id, flow_revision DESC);
"""


class PostgresGovernedFlowStorage:
    def __init__(
        self,
        database_url: str | None = None,
        *,
        client: PostgreSQLClient | None = None,
    ) -> None:
        self._database_url = database_url or DATABASE_URL
        self._client = client
        self._schema_ensured = False

    def _get_client(self) -> PostgreSQLClient:
        if self._client is None:
            self._client = PostgreSQLClient(self._database_url)
        if not self._schema_ensured:
            self._client.execute(GOVERNED_FLOW_TABLE_SCHEMA)
            self._schema_ensured = True
        return self._client

    # ── 主表（草稿/当前态）──────────────────────────────────────────

    def create_flow(self, flow: FlowDefinition) -> FlowDefinition:
        client = self._get_client()
        exists = client.execute(
            "SELECT 1 FROM governed_flows WHERE flow_id = %s", (flow.flow_id,)
        )
        if exists:
            raise FlowRevisionConflictError(f"flow {flow.flow_id} 已存在")
        client.execute(
            """
            INSERT INTO governed_flows (flow_id, name, owner, status, revision, content_hash, definition)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            (
                flow.flow_id, flow.name, flow.owner, flow.status.value,
                flow.revision, flow.content_hash,
                json.dumps(flow.model_dump(mode="json"), ensure_ascii=False),
            ),
        )
        return flow.model_copy(deep=True)

    def get_flow(self, flow_id: str) -> FlowDefinition | None:
        client = self._get_client()
        rows = client.execute(
            "SELECT definition FROM governed_flows WHERE flow_id = %s", (flow_id,)
        )
        if not rows:
            return None
        return FlowDefinition.model_validate(rows[0]["definition"])

    def list_flows(self) -> list[FlowDefinition]:
        client = self._get_client()
        rows = client.execute(
            "SELECT definition FROM governed_flows ORDER BY flow_id"
        )
        return [FlowDefinition.model_validate(row["definition"]) for row in rows]

    def update_flow(self, flow: FlowDefinition, expected_revision: int) -> FlowDefinition:
        client = self._get_client()
        rows = client.execute(
            """
            UPDATE governed_flows
            SET name = %s, owner = %s, status = %s, revision = %s,
                content_hash = %s, definition = %s, updated_at = CURRENT_TIMESTAMP
            WHERE flow_id = %s AND revision = %s
            RETURNING revision
            """,
            (
                flow.name, flow.owner, flow.status.value, flow.revision,
                flow.content_hash,
                json.dumps(flow.model_dump(mode="json"), ensure_ascii=False),
                flow.flow_id, expected_revision,
            ),
        )
        if not rows:
            current = client.execute(
                "SELECT revision FROM governed_flows WHERE flow_id = %s", (flow.flow_id,)
            )
            if not current:
                raise FlowNotFoundError(flow.flow_id)
            raise FlowRevisionConflictError(
                f"乐观锁冲突：期望 revision={expected_revision}，实际 {current[0]['revision']}"
            )
        return flow.model_copy(deep=True)

    def delete_flow(self, flow_id: str, expected_revision: int) -> None:
        client = self._get_client()
        rows = client.execute(
            "DELETE FROM governed_flows WHERE flow_id = %s AND revision = %s RETURNING flow_id",
            (flow_id, expected_revision),
        )
        if not rows:
            current = client.execute(
                "SELECT revision FROM governed_flows WHERE flow_id = %s", (flow_id,)
            )
            if not current:
                raise FlowNotFoundError(flow_id)
            raise FlowRevisionConflictError(
                f"乐观锁冲突：期望 revision={expected_revision}，实际 {current[0]['revision']}"
            )

    # ── 发布版本证据（不可变 + 单活跃）───────────────────────────────

    def save_published_revision(self, revision: FlowPublishedRevision) -> None:
        client = self._get_client()
        client.execute(
            """
            UPDATE governed_flow_revisions
            SET is_active = FALSE
            WHERE flow_id = %s AND is_active
            """,
            (revision.flow_id,),
        )
        client.execute(
            """
            INSERT INTO governed_flow_revisions (
                revision_id, flow_id, flow_revision, content_hash,
                semantic_revision, artifact_hash, published_by, definition, is_active
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, TRUE)
            """,
            (
                revision.revision_id, revision.flow_id, revision.flow_revision,
                revision.content_hash, revision.semantic_revision,
                revision.artifact_hash, revision.published_by,
                json.dumps(revision.definition.model_dump(mode="json"), ensure_ascii=False),
            ),
        )

    def _row_to_revision(self, row: dict[str, Any]) -> FlowPublishedRevision:
        return FlowPublishedRevision(
            revision_id=row["revision_id"],
            flow_id=row["flow_id"],
            flow_revision=row["flow_revision"],
            content_hash=row["content_hash"],
            semantic_revision=row["semantic_revision"],
            artifact_hash=row["artifact_hash"],
            published_at=str(row["published_at"]),
            published_by=row["published_by"],
            definition=FlowDefinition.model_validate(row["definition"]),
        )

    def get_published_revision(self, revision_id: str) -> FlowPublishedRevision | None:
        client = self._get_client()
        rows = client.execute(
            """
            SELECT revision_id, flow_id, flow_revision, content_hash,
                   semantic_revision, artifact_hash, published_at, published_by, definition
            FROM governed_flow_revisions WHERE revision_id = %s
            """,
            (revision_id,),
        )
        return self._row_to_revision(rows[0]) if rows else None

    def list_published_revisions(self, flow_id: str) -> list[FlowPublishedRevision]:
        client = self._get_client()
        rows = client.execute(
            """
            SELECT revision_id, flow_id, flow_revision, content_hash,
                   semantic_revision, artifact_hash, published_at, published_by, definition
            FROM governed_flow_revisions WHERE flow_id = %s
            ORDER BY flow_revision
            """,
            (flow_id,),
        )
        return [self._row_to_revision(row) for row in rows]

    def get_active_revision(self, flow_id: str) -> FlowPublishedRevision | None:
        client = self._get_client()
        rows = client.execute(
            """
            SELECT revision_id, flow_id, flow_revision, content_hash,
                   semantic_revision, artifact_hash, published_at, published_by, definition
            FROM governed_flow_revisions WHERE flow_id = %s AND is_active
            """,
            (flow_id,),
        )
        return self._row_to_revision(rows[0]) if rows else None

    def set_active_revision(self, flow_id: str, revision_id: str) -> None:
        """先验归属再切换活跃指针（部分唯一索引兜底并发）。

        必须拆两条语句「先撤旧活跃、再启目标」：单条多行翻转
        `SET is_active = (revision_id = %s)` 逐行更新时目标行先变 TRUE
        而旧行仍 TRUE，瞬态重复触发 uq_governed_flow_active_revision
        （PG 非可延迟索引逐行检查）。两语句间的瞬态空窗方向安全：
        消费侧要求活跃版本存在，空窗即 fail closed，不会出现双活跃。
        """
        client = self._get_client()
        target = client.execute(
            "SELECT flow_id FROM governed_flow_revisions WHERE revision_id = %s",
            (revision_id,),
        )
        if not target:
            raise FlowNotFoundError(f"发布版本 {revision_id} 不存在")
        if target[0]["flow_id"] != flow_id:
            raise FlowNotFoundError(f"发布版本 {revision_id} 不属于 flow {flow_id}")
        client.execute(
            """
            UPDATE governed_flow_revisions
            SET is_active = FALSE
            WHERE flow_id = %s AND is_active AND revision_id <> %s
            """,
            (flow_id, revision_id),
        )
        client.execute(
            """
            UPDATE governed_flow_revisions
            SET is_active = TRUE
            WHERE flow_id = %s AND revision_id = %s
            """,
            (flow_id, revision_id),
        )
