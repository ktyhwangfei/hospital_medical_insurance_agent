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
    last_watermark TIMESTAMPTZ,
    sync_mode VARCHAR(16) NOT NULL DEFAULT 'full',
    lookback_minutes INTEGER NOT NULL DEFAULT 5,
    PRIMARY KEY (source_id, table_name)
);
CREATE TABLE IF NOT EXISTS data_source_sync_events (
    event_id VARCHAR(64) PRIMARY KEY,
    source_id VARCHAR(64) NOT NULL,
    table_name VARCHAR(128) NOT NULL,
    action VARCHAR(16) NOT NULL,
    actor VARCHAR(128) NOT NULL,
    row_count INTEGER,
    note TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_sync_events_source ON data_source_sync_events(source_id, created_at DESC);
ALTER TABLE data_source_sync_tables ADD COLUMN IF NOT EXISTS sync_mode VARCHAR(16) NOT NULL DEFAULT 'full';
ALTER TABLE data_source_sync_tables ADD COLUMN IF NOT EXISTS lookback_minutes INTEGER NOT NULL DEFAULT 5;
ALTER TABLE data_source_sync_tables ADD COLUMN IF NOT EXISTS last_watermark TIMESTAMPTZ;
ALTER TABLE data_source_sync_events ADD COLUMN IF NOT EXISTS note TEXT;
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
                (source_id, table_name, target_table, key_columns, time_column, status, revision,
                 sync_mode, lookback_minutes)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (source_id, table_name) DO UPDATE
            SET target_table = EXCLUDED.target_table,
                key_columns = EXCLUDED.key_columns,
                time_column = EXCLUDED.time_column,
                status = EXCLUDED.status,
                sync_mode = EXCLUDED.sync_mode,
                lookback_minutes = EXCLUDED.lookback_minutes,
                revision = data_source_sync_tables.revision + 1,
                updated_at = CURRENT_TIMESTAMP
            """,
            (
                table.source_id, table.table_name, table.target_table,
                json.dumps(table.key_columns), table.time_column, table.status.value,
                table.revision, table.sync_mode.value, table.lookback_minutes,
            ),
        )
        return table

    def list_tables(self, source_id: str) -> list[SelectedSyncTable]:
        rows = self._get_client().execute(
            """
            SELECT source_id, table_name, target_table, key_columns, time_column, status,
                   revision, last_synced_at, last_row_count, last_error,
                   sync_mode, lookback_minutes, last_watermark
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

    def mark_synced(
        self, source_id: str, table_name: str, row_count: int,
        watermark: str | None = None,
    ) -> None:
        self._get_client().execute(
            """
            UPDATE data_source_sync_tables
            SET last_synced_at = CURRENT_TIMESTAMP, last_row_count = %s, last_error = NULL,
                last_watermark = COALESCE(%s, last_watermark)
            WHERE source_id = %s AND table_name = %s
            """,
            (row_count, watermark, source_id, table_name),
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
        note: str | None = None,
    ) -> None:
        """选表同步治理事件留痕（选表/移除/同步执行）。"""
        import uuid

        self._get_client().execute(
            """
            INSERT INTO data_source_sync_events
                (event_id, source_id, table_name, action, actor, row_count, note)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            (f"ste_{uuid.uuid4().hex[:12]}", source_id, table_name, action, actor, row_count, note),
        )

    def list_events(self, source_id: str, limit: int = 50) -> list[dict]:
        return self._get_client().execute(
            """
            SELECT event_id, table_name, action, actor, row_count, note, created_at
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
            sync_mode=row.get("sync_mode") or "full",
            lookback_minutes=row.get("lookback_minutes") or 5,
            status=row["status"],
            revision=row["revision"],
            last_synced_at=row["last_synced_at"].isoformat() if row.get("last_synced_at") else None,
            last_row_count=row.get("last_row_count"),
            last_error=row.get("last_error"),
            last_watermark=row["last_watermark"].isoformat() if row.get("last_watermark") else None,
        )

    # ── 通用落地表 ──────────────────────────────────────────────────

    def ensure_landing_table(
        self, target_table: str, columns: list[tuple[str, str]], key_columns: list[str] | None = None,
    ) -> None:
        """按探查列清单建落地表（已存在则对齐补列；不动既有列类型）；主键约束供 upsert。"""
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
        # 主键约束（upsert 去重依赖；已存在同名约束则跳过）
        if key_columns:
            constraint = f"pk_{target_table}"
            key_list = ", ".join(quote_ident(c) for c in key_columns)
            try:
                client.execute(
                    f'ALTER TABLE {quote_ident(target_table)} ADD CONSTRAINT {quote_ident(constraint)} PRIMARY KEY ({key_list})'
                )
            except Exception:
                pass  # 约束已存在或数据冲突——由调用方感知

    def upsert_landing_rows(
        self, target_table: str, columns: list[str], rows: list[tuple[Any, ...]],
        key_columns: list[str],
    ) -> int:
        """主键 upsert（增量同步去重）：INSERT ... ON CONFLICT DO UPDATE。"""
        if not rows:
            return 0
        client = self._get_client()
        column_list = ", ".join(quote_ident(c) for c in columns)
        placeholders = ", ".join(["%s"] * len(columns))
        if key_columns:
            key_list = ", ".join(quote_ident(c) for c in key_columns)
            updates = ", ".join(
                f"{quote_ident(c)} = EXCLUDED.{quote_ident(c)}" for c in columns if c not in key_columns
            )
            sql = (
                f"INSERT INTO {quote_ident(target_table)} ({column_list}) VALUES ({placeholders}) "
                f"ON CONFLICT ({key_list}) DO UPDATE SET {updates}"
            )
        else:
            sql = f"INSERT INTO {quote_ident(target_table)} ({column_list}) VALUES ({placeholders})"
        with client.transaction() as connection:
            for row in rows:
                connection.execute(sql, row)
        return len(rows)

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

    # ── 并发互斥（PG advisory lock，按目标表）──────────────────────

    def try_advisory_lock(self, target_table: str) -> bool:
        """尝试取目标表同步锁（worker 顺带跑与手动同步不撞）。"""
        key = abs(hash(target_table)) % (2**31)
        rows = self._get_client().execute(
            "SELECT pg_try_advisory_lock(%s) AS acquired", (key,)
        )
        return bool(rows and rows[0]["acquired"])

    def release_advisory_lock(self, target_table: str) -> None:
        key = abs(hash(target_table)) % (2**31)
        self._get_client().execute("SELECT pg_advisory_unlock(%s)", (key,))

    # ── 结构漂移对齐（Q6）──────────────────────────────────────────

    def align_landing_schema(
        self, target_table: str, columns: list[tuple[str, str]], key_columns: list[str] | None = None,
    ) -> str | None:
        """对齐落地表结构：新增列自动补（返回漂移说明）；删列/改类型不动但告警。"""
        before = {
            row["column_name"]
            for row in self._get_client().execute(
                "SELECT column_name FROM information_schema.columns WHERE table_name = %s",
                (target_table,),
            )
        } if self._landing_exists(target_table) else set()
        self.ensure_landing_table(target_table, columns, key_columns)
        if not before:
            return None
        source_cols = {name for name, _ in columns}
        added = source_cols - before
        dropped = before - source_cols
        notes = []
        if added:
            notes.append(f"新增列已补: {sorted(added)}")
        if dropped:
            notes.append(f"源表删除列（落地保留待清理）: {sorted(dropped)}")
        return "；".join(notes) if notes else None

    def _landing_exists(self, target_table: str) -> bool:
        rows = self._get_client().execute(
            "SELECT COUNT(*) AS n FROM information_schema.tables WHERE table_name = %s",
            (target_table,),
        )
        return bool(rows[0]["n"])
