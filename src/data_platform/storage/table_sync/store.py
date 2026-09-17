"""选表同步存储：配置表 + 通用落地表 DDL/写入。"""
from __future__ import annotations

import json
from typing import Any

from src.config.production import DATABASE_URL
from src.data_platform.storage.postgresql.client import PostgreSQLClient
from src.data_platform.table_sync import (
    SelectedSyncTable,
    pg_column_type,
    quote_ident,
    utc_now_iso,
)

SELECTED_TABLE_SCHEMA = """
CREATE TABLE IF NOT EXISTS data_source_sync_tables (
    source_id VARCHAR(64) NOT NULL,
    table_name VARCHAR(128) NOT NULL,
    target_table VARCHAR(128) NOT NULL,
    key_columns JSONB NOT NULL DEFAULT '[]',
    time_column VARCHAR(128),
    status VARCHAR(16) NOT NULL DEFAULT 'active',
    revision INTEGER NOT NULL DEFAULT 1,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_synced_at TIMESTAMPTZ,
    last_row_count INTEGER,
    last_error TEXT,
    PRIMARY KEY (source_id, table_name)
);
CREATE TABLE IF NOT EXISTS data_source_sync_events (
    event_id VARCHAR(64) PRIMARY KEY,
    source_id VARCHAR(64) NOT NULL,
    table_name VARCHAR(128) NOT NULL,
    action VARCHAR(16) NOT NULL,
    actor VARCHAR(128) NOT NULL,
    row_count INTEGER,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_sync_events_source ON data_source_sync_events(source_id, created_at DESC);
"""


class TableSyncStore:
    """选表配置 + 通用落地表读写（DDL 幂等）。"""

    def __init__(self, database_url: str | None = None, *, client: PostgreSQLClient | None = None) -> None:
        self._database_url = database_url or DATABASE_URL
        self._client = client
        self._schema_ensured = False

    def _get_client(self) -> PostgreSQLClient:
        if self._client is None:
            self._client = PostgreSQLClient(self._database_url)
        if not self._schema_ensured:
            self._client.execute(SELECTED_TABLE_SCHEMA)
            self._schema_ensured = True
        return self._client

    # ── 配置 ────────────────────────────────────────────────────────

    def save_table(self, table: SelectedSyncTable) -> SelectedSyncTable:
        self._get_client().execute(
            """
            INSERT INTO data_source_sync_tables
                (source_id, table_name, target_table, key_columns, time_column, status, revision)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (source_id, table_name) DO UPDATE
            SET target_table = EXCLUDED.target_table,
                key_columns = EXCLUDED.key_columns,
                time_column = EXCLUDED.time_column,
                status = EXCLUDED.status,
                revision = data_source_sync_tables.revision + 1,
                updated_at = CURRENT_TIMESTAMP
            """,
            (
                table.source_id, table.table_name, table.target_table,
                json.dumps(table.key_columns), table.time_column, table.status.value,
                table.revision,
            ),
        )
        return table

    def list_tables(self, source_id: str) -> list[SelectedSyncTable]:
        rows = self._get_client().execute(
            """
            SELECT source_id, table_name, target_table, key_columns, time_column, status,
                   revision, last_synced_at, last_row_count, last_error
            FROM data_source_sync_tables WHERE source_id = %s ORDER BY table_name
            """,
            (source_id,),
        )
        return [self._row(row) for row in rows]

    def remove_table(self, source_id: str, table_name: str) -> None:
        self._get_client().execute(
            "DELETE FROM data_source_sync_tables WHERE source_id = %s AND table_name = %s",
            (source_id, table_name),
        )

    def mark_synced(self, source_id: str, table_name: str, row_count: int) -> None:
        self._get_client().execute(
            """
            UPDATE data_source_sync_tables
            SET last_synced_at = CURRENT_TIMESTAMP, last_row_count = %s, last_error = NULL
            WHERE source_id = %s AND table_name = %s
            """,
            (row_count, source_id, table_name),
        )

    def mark_failed(self, source_id: str, table_name: str, error: str) -> None:
        self._get_client().execute(
            """
            UPDATE data_source_sync_tables
            SET last_error = %s WHERE source_id = %s AND table_name = %s
            """,
            (error[:500], source_id, table_name),
        )

    def record_event(
        self,
        source_id: str,
        table_name: str,
        action: str,
        actor: str,
        row_count: int | None = None,
    ) -> None:
        """选表同步治理事件留痕（选表/移除/同步执行）。"""
        import uuid

        self._get_client().execute(
            """
            INSERT INTO data_source_sync_events
                (event_id, source_id, table_name, action, actor, row_count)
            VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (f"ste_{uuid.uuid4().hex[:12]}", source_id, table_name, action, actor, row_count),
        )

    def list_events(self, source_id: str, limit: int = 50) -> list[dict]:
        return self._get_client().execute(
            """
            SELECT event_id, table_name, action, actor, row_count, created_at
            FROM data_source_sync_events WHERE source_id = %s
            ORDER BY created_at DESC LIMIT %s
            """,
            (source_id, limit),
        )

    @staticmethod
    def _row(row: dict) -> SelectedSyncTable:
        keys = row["key_columns"]
        return SelectedSyncTable(
            source_id=row["source_id"],
            table_name=row["table_name"],
            target_table=row["target_table"],
            key_columns=json.loads(keys) if isinstance(keys, str) else (keys or []),
            time_column=row["time_column"],
            status=row["status"],
            revision=row["revision"],
            last_synced_at=row["last_synced_at"].isoformat() if row.get("last_synced_at") else None,
            last_row_count=row.get("last_row_count"),
            last_error=row.get("last_error"),
        )

    # ── 通用落地表 ──────────────────────────────────────────────────

    def ensure_landing_table(self, target_table: str, columns: list[tuple[str, str]]) -> None:
        """按探查列清单建落地表（已存在则对齐补列；不动既有列类型）。"""
        client = self._get_client()
        column_defs = ", ".join(f"{quote_ident(name)} {pg_column_type(sql_type)}" for name, sql_type in columns)
        client.execute(f'CREATE TABLE IF NOT EXISTS {quote_ident(target_table)} ({column_defs})')
        existing = {
            row["column_name"]
            for row in client.execute(
                "SELECT column_name FROM information_schema.columns WHERE table_name = %s",
                (target_table,),
            )
        }
        for name, sql_type in columns:
            if name not in existing:
                client.execute(
                    f'ALTER TABLE {quote_ident(target_table)} ADD COLUMN IF NOT EXISTS {quote_ident(name)} {pg_column_type(sql_type)}'
                )

    def replace_landing_rows(self, target_table: str, columns: list[str], rows: list[tuple[Any, ...]]) -> int:
        """全量覆盖：单事务 DELETE + INSERT，失败整体回滚。"""
        client = self._get_client()
        column_list = ", ".join(quote_ident(c) for c in columns)
        placeholders = ", ".join(["%s"] * len(columns))
        with client.transaction() as cursor:
            cursor.execute(f"DELETE FROM {quote_ident(target_table)}")
            for row in rows:
                cursor.execute(
                    f"INSERT INTO {quote_ident(target_table)} ({column_list}) VALUES ({placeholders})",
                    row,
                )
        return len(rows)

    def landing_row_count(self, target_table: str) -> int:
        rows = self._get_client().execute(
            f"SELECT COUNT(*) AS n FROM {quote_ident(target_table)}"
        )
        return int(rows[0]["n"])
