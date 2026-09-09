"""健康运营问题库 PostgreSQL 存储 — issue #45 P0。

ops_findings 单表：fingerprint 唯一索引承载去重（ON CONFLICT 单语句
upsert，occurrence_count 原子累加）；DDL 遵循 CREATE+ALTER 双写约定，
旧库加列不改表结构（AGENTS.md 已知陷阱）。
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from src.config.production import DATABASE_URL
from src.data_platform.storage.postgresql.client import PostgreSQLClient
from src.domain.ops.models import (
    FindingDraft,
    OpsAssetType,
    OpsFinding,
    OpsFindingPage,
    OpsFindingStatus,
    OpsSeverity,
    finding_fingerprint,
    new_finding_id,
)

OPS_FINDINGS_TABLE_SCHEMA = (
    """CREATE TABLE IF NOT EXISTS ops_findings (
        finding_id VARCHAR(64) PRIMARY KEY,
        asset_type VARCHAR(32) NOT NULL,
        asset_id VARCHAR(128) NOT NULL,
        check_id VARCHAR(64) NOT NULL,
        severity VARCHAR(32) NOT NULL,
        status VARCHAR(32) NOT NULL DEFAULT 'open',
        fingerprint VARCHAR(256) NOT NULL,
        payload JSONB NOT NULL DEFAULT '{}'::jsonb,
        first_seen_at TIMESTAMPTZ NOT NULL,
        last_seen_at TIMESTAMPTZ NOT NULL,
        occurrence_count INTEGER NOT NULL DEFAULT 1 CHECK(occurrence_count >= 1),
        diagnosis JSONB,
        revision INTEGER NOT NULL DEFAULT 1 CHECK(revision >= 1)
    )""",
    "ALTER TABLE ops_findings ADD COLUMN IF NOT EXISTS asset_type VARCHAR(32)",
    "ALTER TABLE ops_findings ADD COLUMN IF NOT EXISTS asset_id VARCHAR(128)",
    "ALTER TABLE ops_findings ADD COLUMN IF NOT EXISTS check_id VARCHAR(64)",
    "ALTER TABLE ops_findings ADD COLUMN IF NOT EXISTS severity VARCHAR(32)",
    "ALTER TABLE ops_findings ADD COLUMN IF NOT EXISTS status VARCHAR(32) DEFAULT 'open'",
    "ALTER TABLE ops_findings ADD COLUMN IF NOT EXISTS fingerprint VARCHAR(256)",
    "ALTER TABLE ops_findings ADD COLUMN IF NOT EXISTS payload JSONB DEFAULT '{}'::jsonb",
    "ALTER TABLE ops_findings ADD COLUMN IF NOT EXISTS first_seen_at TIMESTAMPTZ",
    "ALTER TABLE ops_findings ADD COLUMN IF NOT EXISTS last_seen_at TIMESTAMPTZ",
    "ALTER TABLE ops_findings ADD COLUMN IF NOT EXISTS occurrence_count INTEGER DEFAULT 1",
    "ALTER TABLE ops_findings ADD COLUMN IF NOT EXISTS diagnosis JSONB",
    "ALTER TABLE ops_findings ADD COLUMN IF NOT EXISTS revision INTEGER DEFAULT 1",
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_ops_findings_fingerprint ON ops_findings(fingerprint)",
    "CREATE INDEX IF NOT EXISTS idx_ops_findings_status ON ops_findings(status, last_seen_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_ops_findings_asset ON ops_findings(asset_type, severity)",
)

_FINDING_COLUMNS = (
    "finding_id, asset_type, asset_id, check_id, severity, status, fingerprint, "
    "payload, first_seen_at, last_seen_at, occurrence_count, diagnosis, revision"
)


def _row_to_finding(row: dict[str, Any]) -> OpsFinding:
    return OpsFinding(
        finding_id=row["finding_id"],
        asset_type=OpsAssetType(row["asset_type"]),
        asset_id=row["asset_id"],
        check_id=row["check_id"],
        severity=OpsSeverity(row["severity"]),
        status=OpsFindingStatus(row["status"]),
        fingerprint=row["fingerprint"],
        payload=row["payload"] or {},
        first_seen_at=row["first_seen_at"],
        last_seen_at=row["last_seen_at"],
        occurrence_count=row["occurrence_count"],
        diagnosis=row["diagnosis"],
        revision=row["revision"],
    )


class PostgresOpsFindingStorage:
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
            for statement in OPS_FINDINGS_TABLE_SCHEMA:
                self._client.execute(statement)
            self._schema_ensured = True
        return self._client

    def upsert_finding(self, draft: FindingDraft, *, seen_at: datetime) -> OpsFinding:
        client = self._get_client()
        fingerprint = finding_fingerprint(draft.asset_type, draft.asset_id, draft.check_id)
        rows = client.execute(
            f"""
            INSERT INTO ops_findings (
                finding_id, asset_type, asset_id, check_id, severity, status, fingerprint,
                payload, first_seen_at, last_seen_at, occurrence_count, diagnosis, revision
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (fingerprint) DO UPDATE SET
                severity = EXCLUDED.severity,
                payload = EXCLUDED.payload,
                last_seen_at = EXCLUDED.last_seen_at,
                occurrence_count = ops_findings.occurrence_count + 1,
                revision = ops_findings.revision + 1
            RETURNING {_FINDING_COLUMNS}
            """,
            (
                new_finding_id(),
                draft.asset_type.value, draft.asset_id, draft.check_id,
                draft.severity.value, OpsFindingStatus.OPEN.value, fingerprint,
                json.dumps(draft.payload, ensure_ascii=False),
                seen_at, seen_at, 1, None, 1,
            ),
        )
        return _row_to_finding(rows[0])

    def list_findings(
        self,
        *,
        status: OpsFindingStatus | None = None,
        severity: OpsSeverity | None = None,
        asset_type: OpsAssetType | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> OpsFindingPage:
        client = self._get_client()
        conditions: list[str] = []
        params: list[Any] = []
        if status is not None:
            conditions.append("status = %s")
            params.append(status.value)
        if severity is not None:
            conditions.append("severity = %s")
            params.append(severity.value)
        if asset_type is not None:
            conditions.append("asset_type = %s")
            params.append(asset_type.value)
        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        total = client.execute(
            f"SELECT COUNT(*) AS total FROM ops_findings {where}", tuple(params)
        )[0]["total"]
        rows = client.execute(
            f"""
            SELECT {_FINDING_COLUMNS} FROM ops_findings {where}
            ORDER BY CASE severity WHEN 'critical' THEN 0 WHEN 'warning' THEN 1 ELSE 2 END,
                     last_seen_at DESC
            LIMIT %s OFFSET %s
            """,
            tuple(params) + (page_size, (page - 1) * page_size),
        )
        return OpsFindingPage(
            items=[_row_to_finding(row) for row in rows],
            total=total,
            page=page,
            page_size=page_size,
        )
