"""Workflow 治理配置 PostgreSQL 存储（默认实现）。

表按 (workflow_id, hospital_code) 唯一；列新增遵循 CREATE + ALTER 双写
（旧库因 CREATE TABLE IF NOT EXISTS 不重建，漏 ALTER 会 UndefinedColumn）。
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

from src.data_platform.storage.postgresql.client import PostgreSQLClient
from src.domain.workflow.models import WorkflowConfigOverride

_SCHEMA = """
CREATE TABLE IF NOT EXISTS workflow_config (
    workflow_id VARCHAR(64) NOT NULL,
    hospital_code VARCHAR(64) NOT NULL DEFAULT '',
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    intent_keywords JSONB,
    updated_by VARCHAR(128) NOT NULL DEFAULT '',
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (workflow_id, hospital_code)
);
ALTER TABLE workflow_config ADD COLUMN IF NOT EXISTS enabled BOOLEAN NOT NULL DEFAULT TRUE;
ALTER TABLE workflow_config ADD COLUMN IF NOT EXISTS intent_keywords JSONB;
ALTER TABLE workflow_config ADD COLUMN IF NOT EXISTS updated_by VARCHAR(128) NOT NULL DEFAULT '';
ALTER TABLE workflow_config ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP;
"""

_UPSERT = """
INSERT INTO workflow_config(workflow_id, hospital_code, enabled, intent_keywords, updated_by, updated_at)
VALUES (%s, %s, %s, %s, %s, %s)
ON CONFLICT(workflow_id, hospital_code) DO UPDATE SET
    enabled = EXCLUDED.enabled,
    intent_keywords = EXCLUDED.intent_keywords,
    updated_by = EXCLUDED.updated_by,
    updated_at = EXCLUDED.updated_at
"""

_SELECT = """
SELECT workflow_id, hospital_code, enabled, intent_keywords, updated_by, updated_at
FROM workflow_config
"""


def _row_to_override(row: dict) -> WorkflowConfigOverride:
    keywords = row.get("intent_keywords")
    if isinstance(keywords, str):
        keywords = json.loads(keywords)
    updated_at = row.get("updated_at")
    if isinstance(updated_at, str):
        updated_at = datetime.fromisoformat(updated_at)
    return WorkflowConfigOverride(
        workflow_id=row["workflow_id"],
        hospital_code=row.get("hospital_code") or "",
        enabled=bool(row.get("enabled", True)),
        intent_keywords=keywords,
        updated_by=row.get("updated_by") or "",
        updated_at=updated_at or datetime.now(timezone.utc),
    )


class PostgresWorkflowConfigStorage:
    def __init__(self, database_url: str | None = None) -> None:
        self._client = PostgreSQLClient(database_url)
        self._client.execute(_SCHEMA)

    def list_overrides(self) -> list[WorkflowConfigOverride]:
        rows = self._client.execute(_SELECT)
        return [_row_to_override(row) for row in rows]

    def upsert_override(self, override: WorkflowConfigOverride) -> WorkflowConfigOverride:
        self._client.execute(
            _UPSERT,
            (
                override.workflow_id,
                override.hospital_code,
                override.enabled,
                None
                if override.intent_keywords is None
                else json.dumps(override.intent_keywords, ensure_ascii=False),
                override.updated_by,
                override.updated_at,
            ),
        )
        rows = self._client.execute(
            _SELECT + " WHERE workflow_id = %s AND hospital_code = %s",
            (override.workflow_id, override.hospital_code),
        )
        return _row_to_override(rows[0])
