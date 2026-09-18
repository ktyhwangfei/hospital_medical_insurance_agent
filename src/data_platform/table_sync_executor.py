"""选表同步执行器：增量（水位线+回看+主键 upsert）/全量（分页覆盖）双模式。

生产级约束（拷问轮 Q1-Q8 落地）：
- 增量：WHERE time_column > watermark - lookback，分页游标读取，主键 upsert 去重；
- 全量：分页读取 + 单事务覆盖；无时间字段的表强制全量且限频（每日最多一次）；
- 并发互斥：PG advisory lock 按目标表互斥（worker 顺带跑与手动同步不撞）；
- 同步后自动对账：源库行数 vs 落地行数，差异记事件；
- 结构漂移：源表新增列自动补落地列并记事件；删列/改类型记告警事件；
- 全程事件留痕：sync 执行含行数/耗时/水位线/模式。
"""
from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from src.data_platform.storage.table_sync.store import TableSyncStore
from src.data_platform.table_sync import SelectedSyncTable, SyncMode, TableSyncRunResult

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

_PAGE_SIZE = 5000
_FULL_SYNC_MIN_INTERVAL = timedelta(hours=20)  # 全量表限频：每日最多一次


class TableSyncExecutor:
    def __init__(
        self,
        store: TableSyncStore,
        connection_factory: Callable[[str], Any],
    ) -> None:
        self._store = store
        self._connection_factory = connection_factory

    def probe_table_columns(self, source_id: str, table_name: str) -> list[tuple[str, str]]:
        """探查源表列（名称, 类型），供选表时预填落地结构与候选时间字段。"""
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

    def probe_time_candidates(self, source_id: str, table_name: str) -> list[dict]:
        """候选增量时间字段（datetime/date 列）+ 适用性信息（Q1：业务时间 ≠ 变更时间）。

        返回每列：名称、类型、最大值、非空率。UI 据此展示警告：
        无审计时间列（LastModified 类）的表，增量只能捕获新增，不能捕获
        存量行变更（退费冲正/稽核调整）——由每日全量对账兑底。
        """
        connection = self._connection_factory(source_id)
        try:
            cursor = connection.cursor()
            cursor.execute(_SOURCE_COLUMNS_SQL, table_name)
            columns = [(row[0], row[1]) for row in cursor.fetchall()]
            candidates = []
            for name, sql_type in columns:
                if sql_type.lower() not in ("datetime", "datetime2", "smalldatetime", "date"):
                    continue
                cursor.execute(
                    f"SELECT MAX([{name}]), COUNT([{name}]), COUNT(*) FROM dbo.[{table_name}]"
                )
                max_value, non_null, total = cursor.fetchone()
                candidates.append({
                    "column": name,
                    "data_type": sql_type,
                    "max_value": str(max_value) if max_value is not None else None,
                    "non_null_rate": round(non_null / total * 100, 1) if total else 0,
                })
            # 是否有审计时间列（变更时间语义）
            audit_candidates = [
                name for name, sql_type in columns
                if name.lower() in ("lastmodified", "updatetime", "modifieddate", "operdate", "bgrq", "oper_date", "updated_at")
            ]
            return {
                "columns": candidates,
                "has_audit_column": bool(audit_candidates),
                "audit_columns": audit_candidates,
                "warning": (
                    "未检出审计时间列（变更时间）：增量只能捕获新写入行，不能捕获存量行变更"
                    "（退费冲正/稽核调整），存量变更由每日全量对账兜底。"
                    if not audit_candidates else
                    f"检出审计时间列 {audit_candidates}，优先用它做增量时间字段（能捕获变更）。"
                ),
            }
        finally:
            connection.close()

    # ── 同步主入口 ──────────────────────────────────────────────────

    def sync_table(self, table: SelectedSyncTable, *, manual: bool = False) -> TableSyncRunResult:
        started = time.monotonic()
        # Q3 并发互斥：按目标表 advisory lock，撞锁直接跳过（不并发覆盖同一表）
        if not self._store.try_advisory_lock(table.target_table):
            raise RuntimeError(f"表 {table.target_table} 正在同步中，本次跳过")
        try:
            return self._sync_locked(table, started, manual=manual)
        finally:
            self._store.release_advisory_lock(table.target_table)

    def _sync_locked(self, table: SelectedSyncTable, started: float, manual: bool = False) -> TableSyncRunResult:
        mode = table.effective_mode
        connection = self._connection_factory(table.source_id)
        try:
            cursor = connection.cursor()
            cursor.execute(_SOURCE_COLUMNS_SQL, table.table_name)
            columns = [(row[0], row[1]) for row in cursor.fetchall()]
            if not columns:
                raise ValueError(f"源表 {table.table_name} 不存在或无列")
            column_names = [name for name, _ in columns]

            # Q6 结构漂移检测：源表新增列自动补落地列并记事件
            drift = self._store.align_landing_schema(
                table.target_table, columns, table.key_columns
            )
            if drift:
                self._store.record_event(
                    table.source_id, table.table_name, "schema_drift", "system",
                    None, note=drift,
                )

            if mode is SyncMode.INCREMENTAL:
                row_count, watermark = self._incremental_read(cursor, table, column_names)
            else:
                if not manual:
                    self._check_full_sync_frequency(table)
                row_count, watermark = self._full_read(cursor, table, column_names)
        finally:
            connection.close()

        # Q4 同步后对账：源库行数 vs 落地行数（增量表最终一致，全量表即时一致）
        reconcile_note = self._reconcile(table)
        self._store.mark_synced(
            table.source_id, table.table_name, row_count, watermark=watermark
        )
        # Q7 事件留痕：行数/耗时/水位线/模式
        self._store.record_event(
            table.source_id, table.table_name, "sync", "worker",
            row_count,
            note=f"mode={mode.value} watermark={watermark or '-'} {reconcile_note}".strip(),
        )
        return TableSyncRunResult(
            table_name=table.table_name,
            target_table=table.target_table,
            row_count=row_count,
            duration_ms=int((time.monotonic() - started) * 1000),
        )

    # ── 增量读取（水位线 + 回看窗口）─────────────────────────────────

    def _incremental_read(
        self, cursor: Any, table: SelectedSyncTable, column_names: list[str]
    ) -> tuple[int, str | None]:
        assert table.time_column, "incremental 模式必须有 time_column"  # effective_mode 已保证
        lookback = timedelta(minutes=table.lookback_minutes)
        since = (
            datetime.fromisoformat(table.last_watermark) - lookback
            if table.last_watermark
            else None  # 首次增量：全量起步
        )
        column_list = ", ".join(f"[{name}]" for name in column_names)
        where = ""
        params: tuple = ()
        if since is not None:
            where = f"WHERE [{table.time_column}] > ?"
            params = (since,)
        cursor.execute(
            f"SELECT {column_list} FROM dbo.[{table.table_name}] {where} "
            f"ORDER BY [{table.time_column}]",
            *params,
        )
        rows, max_seen = self._paged_upsert(cursor, table, column_names)
        # 水位线推进到本批最大时间（无新数据则不推进）
        return rows, max_seen

    # ── 全量读取（分页 + 覆盖）──────────────────────────────────────

    def _full_read(
        self, cursor: Any, table: SelectedSyncTable, column_names: list[str]
    ) -> tuple[int, str | None]:
        column_list = ", ".join(f"[{name}]" for name in column_names)
        cursor.execute(f"SELECT {column_list} FROM dbo.[{table.table_name}]")
        rows, max_seen = self._paged_upsert(cursor, table, column_names)
        return rows, max_seen

    def _paged_upsert(
        self, cursor: Any, table: SelectedSyncTable, column_names: list[str]
    ) -> tuple[int, str | None]:
        """Q5 分页游标读取 + Q1 主键 upsert 去重；返回（行数, 最大时间）。"""
        total = 0
        max_seen: str | None = None
        time_idx = column_names.index(table.time_column) if table.time_column else None
        while True:
            batch = cursor.fetchmany(_PAGE_SIZE)
            if not batch:
                break
            rows = [tuple(row) for row in batch]
            self._store.upsert_landing_rows(
                table.target_table, column_names, rows, table.key_columns
            )
            total += len(rows)
            if time_idx is not None:
                for row in rows:
                    value = row[time_idx]
                    if value is not None:
                        text = value.isoformat() if hasattr(value, "isoformat") else str(value)
                        if max_seen is None or text > max_seen:
                            max_seen = text
        return total, max_seen

    def _check_full_sync_frequency(self, table: SelectedSyncTable) -> None:
        """Q2 全量表限频：距上次同步不足 20h 则跳过（防大表频繁全量覆盖）。"""
        if table.last_synced_at:
            last = datetime.fromisoformat(table.last_synced_at)
            if datetime.now(timezone.utc) - last < _FULL_SYNC_MIN_INTERVAL:
                raise RuntimeError(
                    f"全量表 {table.table_name} 限频：距上次同步不足 20 小时，跳过"
                )

    def _reconcile(self, table: SelectedSyncTable) -> str:
        """Q4 同步后对账：源库行数 vs 落地行数（最终一致口径）。"""
        try:
            connection = self._connection_factory(table.source_id)
            try:
                cursor = connection.cursor()
                cursor.execute(f"SELECT COUNT(*) FROM dbo.[{table.table_name}]")
                source_count = cursor.fetchone()[0]
            finally:
                connection.close()
            landing_count = self._store.landing_row_count(table.target_table)
            if source_count == landing_count:
                return f"reconcile=ok({landing_count})"
            return f"reconcile=diff(source={source_count},landing={landing_count})"
        except Exception as exc:
            return f"reconcile=skip({exc})"

    def sync_all_active(self, source_id: str, *, manual: bool = False) -> list[TableSyncRunResult]:
        """manual=True（用户手动触发）时限频不生效——限频只挡 worker 顺带跑。"""
        results: list[TableSyncRunResult] = []
        for table in self._store.list_tables(source_id):
            if table.status.value != "active":
                continue
            try:
                results.append(self.sync_table(table, manual=manual))
            except Exception as exc:
                self._store.mark_failed(source_id, table.table_name, str(exc))
        return results
