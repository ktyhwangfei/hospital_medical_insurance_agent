"""选表同步执行器：从源库全列读取 → 通用落地表全量覆盖。

复用数据治理中心的受控连接（凭据库 + 连接工厂），只读源库。
"""
from __future__ import annotations

import time
from typing import Any, Callable

from src.data_platform.storage.table_sync.store import TableSyncStore
from src.data_platform.table_sync import SelectedSyncTable, TableSyncRunResult

# 源表列清单（含类型，供落地 DDL 与 SELECT 列序）
_SOURCE_COLUMNS_SQL = """
    SELECT c.name, t.name
    FROM sys.tables tb
    JOIN sys.columns c ON c.object_id = tb.object_id
    JOIN sys.types t ON t.user_type_id = c.user_type_id
    WHERE tb.name = ?
    ORDER BY c.column_id
"""

_SOURCE_PK_SQL = """
    SELECT c.name
    FROM sys.tables tb
    JOIN sys.indexes i ON i.object_id = tb.object_id AND i.is_primary_key = 1
    JOIN sys.index_columns ic ON ic.object_id = tb.object_id AND ic.index_id = i.index_id
    JOIN sys.columns c ON c.object_id = tb.object_id AND c.column_id = ic.column_id
    WHERE tb.name = ?
    ORDER BY ic.key_ordinal
"""


class TableSyncExecutor:
    def __init__(
        self,
        store: TableSyncStore,
        connection_factory: Callable[[str], Any],
    ) -> None:
        self._store = store
        self._connection_factory = connection_factory

    def probe_table_columns(self, source_id: str, table_name: str) -> list[tuple[str, str]]:
        """探查源表列（名称, 类型），供选表时预填落地结构。"""
        connection = self._connection_factory(source_id)
        try:
            cursor = connection.cursor()
            cursor.execute(_SOURCE_COLUMNS_SQL, table_name)
            return [(row[0], row[1]) for row in cursor.fetchall()]
        finally:
            connection.close()

    def probe_table_keys(self, source_id: str, table_name: str) -> list[str]:
        connection = self._connection_factory(source_id)
        try:
            cursor = connection.cursor()
            cursor.execute(_SOURCE_PK_SQL, table_name)
            return [row[0] for row in cursor.fetchall()]
        finally:
            connection.close()

    def sync_table(self, table: SelectedSyncTable) -> TableSyncRunResult:
        """全量直通同步一张表：探查列 → 落地 DDL 对齐 → DELETE+INSERT 覆盖。"""
        started = time.monotonic()
        connection = self._connection_factory(table.source_id)
        try:
            cursor = connection.cursor()
            cursor.execute(_SOURCE_COLUMNS_SQL, table.table_name)
            columns = [(row[0], row[1]) for row in cursor.fetchall()]
            if not columns:
                raise ValueError(f"源表 {table.table_name} 不存在或无列")
            column_names = [name for name, _ in columns]
            column_list = ", ".join(f"[{name}]" for name in column_names)
            cursor.execute(f"SELECT {column_list} FROM dbo.[{table.table_name}]")
            # pyodbc Row 不是 sequence，psycopg 侧需原生 tuple
            rows = [tuple(row) for row in cursor.fetchall()]
        finally:
            connection.close()

        self._store.ensure_landing_table(table.target_table, columns)
        row_count = self._store.replace_landing_rows(table.target_table, column_names, rows)
        self._store.mark_synced(table.source_id, table.table_name, row_count)
        return TableSyncRunResult(
            table_name=table.table_name,
            target_table=table.target_table,
            row_count=row_count,
            duration_ms=int((time.monotonic() - started) * 1000),
        )

    def sync_all_active(self, source_id: str) -> list[TableSyncRunResult]:
        results: list[TableSyncRunResult] = []
        for table in self._store.list_tables(source_id):
            if table.status.value != "active":
                continue
            try:
                results.append(self.sync_table(table))
            except Exception as exc:
                self._store.mark_failed(source_id, table.table_name, str(exc))
        return results
