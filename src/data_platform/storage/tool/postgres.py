"""PostgreSQL Tool 版本存储。"""

from __future__ import annotations

import json
from typing import Any

from src.config.production import DATABASE_URL
from src.data_platform.storage.postgresql.client import PostgreSQLClient
from src.data_platform.storage.tool.ports import ToolVersionConflictError
from src.domain.tool.models import ToolDefinition, ToolStatus, ToolVersion


TOOL_VERSION_TABLE_SCHEMA = """
CREATE TABLE IF NOT EXISTS tool_versions (
    version_id VARCHAR(64) PRIMARY KEY,
    tool_id VARCHAR(128) NOT NULL,
    semantic_version VARCHAR(64) NOT NULL,
    definition_snapshot JSONB NOT NULL DEFAULT '{}',
    status VARCHAR(32) NOT NULL DEFAULT 'draft',
    created_by VARCHAR(128) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(tool_id, semantic_version)
);
CREATE INDEX IF NOT EXISTS idx_tool_versions_tool_created
    ON tool_versions(tool_id, created_at DESC);
"""


class PostgresToolVersionStorage:
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
            self._client.execute(TOOL_VERSION_TABLE_SCHEMA)
            self._schema_ensured = True
        return self._client

    def save_version(self, version: ToolVersion) -> ToolVersion:
        existing = self._find_by_semantic_version(version.tool_id, version.semantic_version)
        if existing is not None and existing.version_id != version.version_id:
            raise ToolVersionConflictError(
                f"Tool {version.tool_id} 的语义版本 {version.semantic_version} 已绑定其他制品"
            )

        existing_by_id = self._find_by_version_id(version.version_id)
        if existing_by_id is not None and (
            existing_by_id.tool_id != version.tool_id
            or existing_by_id.semantic_version != version.semantic_version
            or existing_by_id.definition != version.definition
        ):
            raise ToolVersionConflictError(
                f"Tool 版本 {version.version_id} 已登记且内容不一致，"
                "内容变化必须登记新版本，禁止静默覆盖"
            )

        client = self._get_client()
        insert_sql = """
            INSERT INTO tool_versions (
                version_id, tool_id, semantic_version, definition_snapshot,
                status, created_by, created_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (version_id) DO UPDATE SET status = EXCLUDED.status
            RETURNING *
        """
        params = (
            version.version_id,
            version.tool_id,
            version.semantic_version,
            json.dumps(version.definition.model_dump(mode="json"), ensure_ascii=False),
            version.status.value,
            version.created_by,
            version.created_at,
        )
        rows = client.execute(insert_sql, params)
        return version if not rows else self._row_to_version(rows[0])

    def get_version(self, tool_id: str, version_id: str) -> ToolVersion | None:
        rows = self._get_client().execute(
            "SELECT * FROM tool_versions WHERE tool_id = %s AND version_id = %s",
            (tool_id, version_id),
        )
        return None if not rows else self._row_to_version(rows[0])

    def _find_by_semantic_version(
        self, tool_id: str, semantic_version: str
    ) -> ToolVersion | None:
        rows = self._get_client().execute(
            "SELECT * FROM tool_versions WHERE tool_id = %s AND semantic_version = %s",
            (tool_id, semantic_version),
        )
        return None if not rows else self._row_to_version(rows[0])

    def _find_by_version_id(self, version_id: str) -> ToolVersion | None:
        rows = self._get_client().execute(
            "SELECT * FROM tool_versions WHERE version_id = %s",
            (version_id,),
        )
        return None if not rows else self._row_to_version(rows[0])

    def list_versions(self, tool_id: str) -> list[ToolVersion]:
        rows = self._get_client().execute(
            "SELECT * FROM tool_versions WHERE tool_id = %s ORDER BY created_at DESC",
            (tool_id,),
        )
        return [self._row_to_version(row) for row in rows]

    def get_latest_materialized(self, tool_id: str) -> ToolVersion | None:
        rows = self._get_client().execute(
            "SELECT * FROM tool_versions WHERE tool_id = %s AND status = %s "
            "ORDER BY created_at DESC LIMIT 1",
            (tool_id, ToolStatus.MATERIALIZED.value),
        )
        return None if not rows else self._row_to_version(rows[0])

    @staticmethod
    def _json_value(value: object, default: object) -> object:
        if value is None:
            return default
        return json.loads(value) if isinstance(value, str) else value

    @classmethod
    def _row_to_version(cls, row: dict[str, Any]) -> ToolVersion:
        definition_snapshot = cls._json_value(row.get("definition_snapshot"), {})
        return ToolVersion(
            version_id=row["version_id"],
            tool_id=row["tool_id"],
            semantic_version=row["semantic_version"],
            definition=ToolDefinition(**definition_snapshot),
            status=row["status"],
            created_by=row["created_by"],
            created_at=row["created_at"],
        )
