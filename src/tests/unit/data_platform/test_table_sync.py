"""选表同步测试：增量（水位线+回看+upsert）/全量限频/互斥锁/对账/漂移。"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from src.data_platform.table_sync import (
    SelectedSyncTable,
    SyncMode,
    pg_column_type,
    quote_ident,
)
from src.data_platform.table_sync_executor import TableSyncExecutor


class _FakeCursor:
    """模拟 pyodbc cursor：按 SQL 内容路由到列清单或数据行。"""

    def __init__(self, connection):
        self._conn = connection
        self._buffer: list = []

    def execute(self, sql, *params):
        self._conn.last_sql = sql
        self._conn.last_params = params
        self._conn.sql_history.append((sql, params))
        if "sys.columns" in sql:
            self._buffer = list(self._conn.columns)
        elif "COUNT(*)" in sql:
            self._buffer = [(self._conn.source_count,)]
        else:
            self._buffer = list(self._conn.rows)
        return self

    def fetchall(self):
        return list(self._buffer)

    def fetchmany(self, size):
        batch, self._buffer = self._buffer[:size], self._buffer[size:]
        return batch

    def fetchone(self):
        return self._buffer[0] if self._buffer else None


class _FakeConnection:
    def __init__(self, columns, rows, source_count=0):
        self.columns = columns
        self.rows = rows
        self.source_count = source_count
        self.closed = False
        self.last_sql = None
        self.last_params = None
        self.sql_history: list[tuple[str, tuple]] = []

    def cursor(self):
        return _FakeCursor(self)

    def close(self):
        self.closed = True


class _FakeStore:
    def __init__(self):
        self.landing: list[tuple] = []
        self.events: list[dict] = []
        self.synced: dict = {}
        self.locked: set[str] = set()
        self.tables: dict[str, SelectedSyncTable] = {}
        self._schema: set[str] = set()
        self.landing_count = 0

    # 并发互斥
    def try_advisory_lock(self, target):
        if target in self.locked:
            return False
        self.locked.add(target)
        return True

    def release_advisory_lock(self, target):
        self.locked.discard(target)

    # 结构对齐
    def align_landing_schema(self, target, columns, key_columns=None):
        self._schema = {name for name, _ in columns}
        return None

    def ensure_landing_table(self, target, columns, key_columns=None):
        self._schema = {name for name, _ in columns}

    # 写入
    def upsert_landing_rows(self, target, columns, rows, key_columns):
        self.landing.extend(rows)
        self.landing_count += len(rows)
        return len(rows)

    def replace_landing_rows(self, target, columns, rows):
        self.landing = list(rows)
        return len(rows)

    def landing_row_count(self, target):
        return self.landing_count

    # 状态
    def mark_synced(self, source_id, table_name, row_count, watermark=None):
        self.synced[table_name] = {"row_count": row_count, "watermark": watermark}

    def mark_failed(self, source_id, table_name, error):
        raise AssertionError(f"不应失败: {error}")

    def record_event(self, source_id, table_name, action, actor, row_count=None, note=None):
        self.events.append({"table": table_name, "action": action, "row_count": row_count, "note": note})

    def list_tables(self, source_id):
        return list(self.tables.values())


def test_pg_column_type_mapping():
    assert pg_column_type("int") == "BIGINT"
    assert pg_column_type("money") == "NUMERIC"
    assert pg_column_type("datetime") == "TIMESTAMP"
    assert pg_column_type("nvarchar") == "TEXT"


def test_quote_ident_escapes():
    assert quote_ident("mz_trade") == '"mz_trade"'
    assert quote_ident('we"ird') == '"we""ird"'


def test_effective_mode_full_when_no_time_column():
    table = SelectedSyncTable(
        source_id="s", table_name="t", target_table="t",
        sync_mode="incremental", time_column=None,
    )
    assert table.effective_mode == SyncMode.FULL


def test_incremental_read_uses_watermark_lookback():
    """增量：WHERE time > watermark - lookback；upsert 写入；水位线推进到本批最大。"""
    store = _FakeStore()
    now = datetime(2026, 9, 16, 12, 0, tzinfo=timezone.utc)
    conn = _FakeConnection(
        columns=[("id", "int"), ("jyrq", "datetime")],
        rows=[(1, now - timedelta(minutes=3)), (2, now)],
        source_count=2,
    )
    executor = TableSyncExecutor(store, lambda source_id: conn)
    table = SelectedSyncTable(
        source_id="s", table_name="yb_mzjyxx", target_table="yb_mzjyxx",
        key_columns=["id"], time_column="jyrq", sync_mode="incremental",
        lookback_minutes=5, last_watermark=(now - timedelta(minutes=10)).isoformat(),
    )
    result = executor.sync_table(table)

    # 回看窗口：watermark - 5min（找含时间列的增量读取 SQL）
    sync_sql = [sql for sql, _ in conn.sql_history if '[jyrq]' in sql][0]
    sync_params = [p for sql, p in conn.sql_history if '[jyrq]' in sql][0]
    assert "WHERE [jyrq] > ?" in sync_sql
    assert sync_params[0] == now - timedelta(minutes=15)
    assert result.row_count == 2
    assert store.synced["yb_mzjyxx"]["watermark"] == now.isoformat()
    assert store.landing_count == 2


def test_incremental_first_run_reads_all():
    """首次增量（无水位线）：不带 WHERE 全量起步。"""
    store = _FakeStore()
    conn = _FakeConnection(
        columns=[("id", "int"), ("jyrq", "datetime")],
        rows=[(1, datetime(2026, 9, 16))],
        source_count=1,
    )
    executor = TableSyncExecutor(store, lambda source_id: conn)
    table = SelectedSyncTable(
        source_id="s", table_name="t", target_table="t",
        key_columns=["id"], time_column="jyrq", sync_mode="incremental",
    )
    executor.sync_table(table)
    assert "WHERE" not in (conn.last_sql or "")


def test_advisory_lock_prevents_concurrent_sync():
    """同一目标表并发同步时后者跳过。"""
    store = _FakeStore()
    store.locked.add("t")  # 模拟已有同步在跑
    conn = _FakeConnection(columns=[("id", "int")], rows=[])
    executor = TableSyncExecutor(store, lambda source_id: conn)
    table = SelectedSyncTable(source_id="s", table_name="t", target_table="t")
    with pytest.raises(RuntimeError, match="正在同步"):
        executor.sync_table(table)


def test_full_sync_frequency_limited():
    """全量表限频：距上次同步不足 20h 跳过。"""
    store = _FakeStore()
    conn = _FakeConnection(columns=[("id", "int")], rows=[], source_count=0)
    executor = TableSyncExecutor(store, lambda source_id: conn)
    table = SelectedSyncTable(
        source_id="s", table_name="t", target_table="t",
        sync_mode="full",
        last_synced_at=datetime.now(timezone.utc).isoformat(),
    )
    with pytest.raises(RuntimeError, match="限频"):
        executor.sync_table(table)


def test_sync_events_recorded_with_mode_and_watermark():
    """同步执行记事件（行数/模式/水位线/对账结果）。"""
    store = _FakeStore()
    conn = _FakeConnection(
        columns=[("id", "int"), ("jyrq", "datetime")],
        rows=[(1, datetime(2026, 9, 16))],
        source_count=1,
    )
    executor = TableSyncExecutor(store, lambda source_id: conn)
    table = SelectedSyncTable(
        source_id="s", table_name="t", target_table="t",
        key_columns=["id"], time_column="jyrq", sync_mode="incremental",
    )
    executor.sync_table(table)
    sync_events = [e for e in store.events if e["action"] == "sync"]
    assert len(sync_events) == 1
    assert sync_events[0]["row_count"] == 1
    assert "mode=incremental" in sync_events[0]["note"]
    assert "reconcile=ok" in sync_events[0]["note"]
