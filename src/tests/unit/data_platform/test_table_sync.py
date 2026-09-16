"""选表同步测试：类型映射 / 配置模型 / 执行器（fake 连接 + 内存落地）。"""
from __future__ import annotations

import pytest

from src.data_platform.table_sync import (
    SelectedSyncTable,
    pg_column_type,
    quote_ident,
)
from src.data_platform.table_sync_executor import TableSyncExecutor


class _FakeCursor:
    def __init__(self, connection):
        self._conn = connection

    def execute(self, sql, *params):
        self._conn.last_sql = sql
        self._conn.last_params = params

    def fetchall(self):
        return list(self._conn.rows)


class _FakeConnection:
    """模拟 pyodbc 连接：columns 为 (name, type) 清单，rows 为数据行。"""

    def __init__(self, columns, rows):
        self.columns = columns
        self.rows = rows
        self.closed = False
        self.last_sql = None

    def cursor(self):
        outer = self

        class _Cur:
            def execute(self, sql, *params):
                outer.last_sql = sql
                outer._params = params

            def fetchall(self):
                if "sys.columns" in (outer.last_sql or ""):
                    return list(outer.columns)
                return [tuple(r) for r in outer.rows]

        return _Cur()

    def close(self):
        self.closed = True


class _FakeStore:
    """不落 PG 的内存落地（断言用）。"""

    def __init__(self):
        self.landing: dict[str, list[tuple]] = {}
        self.ddl: dict[str, list[tuple[str, str]]] = {}
        self.synced: dict[str, int] = {}
        self.tables: dict[str, SelectedSyncTable] = {}

    def ensure_landing_table(self, target_table, columns):
        self.ddl[target_table] = list(columns)

    def replace_landing_rows(self, target_table, columns, rows):
        self.landing[target_table] = list(rows)
        return len(rows)

    def mark_synced(self, source_id, table_name, row_count):
        self.synced[table_name] = row_count

    def mark_failed(self, source_id, table_name, error):
        raise AssertionError(f"不应失败: {error}")

    def list_tables(self, source_id):
        return list(self.tables.values())


def test_pg_column_type_mapping():
    assert pg_column_type("int") == "BIGINT"
    assert pg_column_type("money") == "NUMERIC"
    assert pg_column_type("datetime") == "TIMESTAMP"
    assert pg_column_type("nvarchar") == "TEXT"
    assert pg_column_type("bit") == "BOOLEAN"


def test_quote_ident_escapes():
    assert quote_ident("mz_trade") == '"mz_trade"'
    assert quote_ident('we"ird') == '"we""ird"'


def test_sync_table_end_to_end_landing():
    """全量直通：探查列 → DDL → DELETE+INSERT 覆盖 → 行数回写配置。"""
    store = _FakeStore()
    table = SelectedSyncTable(
        source_id="bjybdb", table_name="yb_mzjyxx", target_table="yb_mzjyxx",
        key_columns=["jylsh"], time_column="jyrq",
    )
    store.tables["yb_mzjyxx"] = table
    conn = _FakeConnection(
        columns=[("jylsh", "varchar"), ("zje", "numeric"), ("jyrq", "datetime")],
        rows=[("JY001", 100.5, "2024-01-01"), ("JY002", 200.0, "2024-01-02")],
    )
    executor = TableSyncExecutor(store, lambda source_id: conn)

    result = executor.sync_table(table)

    assert result.row_count == 2
    assert store.ddl["yb_mzjyxx"] == [("jylsh", "varchar"), ("zje", "numeric"), ("jyrq", "datetime")]
    assert store.landing["yb_mzjyxx"] == [("JY001", 100.5, "2024-01-01"), ("JY002", 200.0, "2024-01-02")]
    assert store.synced["yb_mzjyxx"] == 2
    assert conn.closed


def test_sync_missing_source_table_fails_closed():
    store = _FakeStore()
    conn = _FakeConnection(columns=[], rows=[])
    executor = TableSyncExecutor(store, lambda source_id: conn)
    table = SelectedSyncTable(
        source_id="bjybdb", table_name="ghost", target_table="ghost",
    )
    with pytest.raises(ValueError, match="不存在"):
        executor.sync_table(table)


def test_sync_all_active_skips_paused():
    store = _FakeStore()
    active = SelectedSyncTable(source_id="s", table_name="t1", target_table="t1")
    paused = SelectedSyncTable(source_id="s", table_name="t2", target_table="t2", status="paused")
    store.tables = {"t1": active, "t2": paused}
    conn = _FakeConnection(columns=[("a", "int")], rows=[(1,)])
    executor = TableSyncExecutor(store, lambda source_id: conn)

    results = executor.sync_all_active("s")

    assert [r.table_name for r in results] == ["t1"]
