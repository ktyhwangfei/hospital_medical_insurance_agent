"""不允许开 CDC 时的门诊定时 SQL 读取适配器（支持源表映射）。"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from src.adapters.insurance_interface.outpatient_cdc import SourceContractMismatchError
from src.adapters.insurance_interface.outpatient_source import (
    OUTPATIENT_SOURCE_SPECS,
    CheckpointKind,
    OutpatientCheckpoint,
    OutpatientSourceBatch,
    OutpatientSourceMode,
)
from src.data_platform.outpatient_governance import (
    TIME_FIELD,
    TRADE_NO_FIELD,
    CaptureMapping,
    OutpatientSourceMapping,
    default_source_mapping,
)

TRADE_CAPTURE = "dbo_o_Trade"


@dataclass(frozen=True)
class ResolvedCapture:
    """映射解析后的单表 SQL 构件（执行与预览共用，保证所见即所执行）。"""

    capture: str
    select_sql: str  # SELECT [源列] AS [契约字段], ... FROM [schema].[table]
    key_source_columns: tuple[str, ...]  # ORDER BY 用源列名
    time_source_column: str  # 交易表时间窗口字段（源列名）
    trade_no_source_column: str  # 父子关联字段（源列名）


def resolve_capture(mapping: CaptureMapping) -> ResolvedCapture:
    source_column = mapping.column_map  # 契约字段 → 源列
    select_list = ", ".join(
        f"[{source_column[field]}] AS [{field}]" for field in source_column
    )
    return ResolvedCapture(
        capture=mapping.capture,
        select_sql=(
            f"SELECT {select_list} "
            f"FROM [{mapping.table_schema}].[{mapping.table_name}]"
        ),
        key_source_columns=tuple(source_column[field] for field in mapping.key_fields),
        time_source_column=source_column.get(TIME_FIELD),
        trade_no_source_column=source_column[TRADE_NO_FIELD],
    )


def resolve_mapping(mapping: OutpatientSourceMapping) -> dict[str, ResolvedCapture]:
    return {capture: resolve_capture(item) for capture, item in mapping.captures.items()}


def default_captures() -> dict[str, ResolvedCapture]:
    """历史固定契约（无映射存储行时的回退，逐字等价）。"""
    return resolve_mapping(default_source_mapping("_default"))


def baseline_sql(capture: ResolvedCapture) -> str:
    order_by = ", ".join(f"[{column}]" for column in capture.key_source_columns)
    return f"{capture.select_sql} ORDER BY {order_by}"


def window_sql(capture: ResolvedCapture) -> str:
    if capture.time_source_column is None:
        raise ValueError("时间窗口 SQL 仅适用于已映射 T_TradeDate 的交易表")
    time_column = capture.time_source_column
    return (
        f"{capture.select_sql} "
        f"WHERE [{time_column}] >= ? AND [{time_column}] < ? "
        f"ORDER BY [{time_column}]"
    )


def children_sql(capture: ResolvedCapture, chunk_size: int) -> str:
    placeholders = ", ".join("?" for _ in range(chunk_size))
    return (
        f"{capture.select_sql} "
        f"WHERE [{capture.trade_no_source_column}] IN ({placeholders}) "
        f"ORDER BY [{capture.trade_no_source_column}]"
    )


def probe_outpatient_readiness(
    connection, mapping: OutpatientSourceMapping | None = None
) -> tuple[int, int]:
    """验证映射源表、契约字段和当前账号读取权限。"""
    captures = resolve_mapping(mapping) if mapping else default_captures()
    cursor = connection.cursor()
    try:
        for capture in captures.values():
            cursor.execute(f"SELECT TOP 1 {capture.select_sql[len('SELECT '):]}")
            cursor.fetchone()
    except Exception as exc:
        raise SourceContractMismatchError("门诊源表不可直接读取") from exc
    if mapping:
        field_count = sum(len(item.column_map) for item in mapping.captures.values())
    else:
        field_count = sum(len(spec.columns) for spec in OUTPATIENT_SOURCE_SPECS.values())
    return len(captures), field_count


class SqlServerOutpatientPollingSource:
    def __init__(
        self,
        connection_factory: Callable[[], Any],
        *,
        clock: Callable[[], datetime] | None = None,
        lookback: timedelta = timedelta(hours=2),
        baseline_start: datetime | None = None,
        mapping: OutpatientSourceMapping | None = None,
    ) -> None:
        self._connection_factory = connection_factory
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._lookback = lookback
        self._baseline_start = baseline_start
        self._captures = resolve_mapping(mapping) if mapping else default_captures()

    def read(self, checkpoint: OutpatientCheckpoint | None) -> OutpatientSourceBatch:
        end = _utc(self._clock())
        if checkpoint is None:
            if self._baseline_start is not None:
                return self.read_time_window(_utc(self._baseline_start), end, is_baseline=True)
            return self._read_baseline(end)
        if checkpoint.kind is not CheckpointKind.TIME_WINDOW:
            raise ValueError("scheduled SQL source requires a time-window checkpoint")
        return self.read_time_window(end - self._lookback, end)

    def read_time_window(
        self,
        window_start: datetime,
        window_end: datetime,
        *,
        is_baseline: bool = False,
    ) -> OutpatientSourceBatch:
        connection = self._connection_factory()
        try:
            cursor = connection.cursor()
            trade = self._captures[TRADE_CAPTURE]
            cursor.execute(window_sql(trade), window_start, window_end)
            trades = tuple(_rows_as_dicts(cursor))
            trade_nos = tuple(sorted({
                str(row[TRADE_NO_FIELD])
                for row in trades
                if row.get(TRADE_NO_FIELD) not in (None, "")
            }))
            rows = {
                TRADE_CAPTURE: trades,
                "dbo_o_FeeItem": self._read_children(cursor, "dbo_o_FeeItem", trade_nos),
                "dbo_o_Diagnose": self._read_children(cursor, "dbo_o_Diagnose", trade_nos),
            }
            return _batch(rows, trade_nos, window_start, window_end, is_baseline)
        finally:
            connection.close()

    def _read_baseline(self, observed_at: datetime) -> OutpatientSourceBatch:
        connection = self._connection_factory()
        try:
            cursor = connection.cursor()
            rows = {}
            for capture, resolved in self._captures.items():
                cursor.execute(baseline_sql(resolved))
                rows[capture] = tuple(_rows_as_dicts(cursor))
            trade_rows = rows[TRADE_CAPTURE]
            trade_nos = tuple(sorted({
                str(row[TRADE_NO_FIELD])
                for row in trade_rows
                if row.get(TRADE_NO_FIELD) not in (None, "")
            }))
            return _batch(rows, trade_nos, None, observed_at, True)
        finally:
            connection.close()

    def _read_children(self, cursor, capture: str, trade_nos: tuple[str, ...]):
        if not trade_nos:
            return ()
        resolved = self._captures[capture]
        rows = []
        for start in range(0, len(trade_nos), 500):
            chunk = trade_nos[start:start + 500]
            cursor.execute(children_sql(resolved, len(chunk)), *chunk)
            rows.extend(_rows_as_dicts(cursor))
        return tuple(rows)


def _batch(rows, trade_nos, start, end, is_baseline) -> OutpatientSourceBatch:
    end = _utc(end)
    return OutpatientSourceBatch(
        mode=OutpatientSourceMode.SCHEDULED_SQL,
        checkpoint=OutpatientCheckpoint(
            kind=CheckpointKind.TIME_WINDOW,
            value=end.isoformat(),
            observed_at=end,
        ),
        snapshot_rows=rows,
        scope_trade_nos=frozenset(trade_nos),
        is_baseline=is_baseline,
        window_start=_utc(start) if start is not None else None,
        window_end=end,
    )


def _rows_as_dicts(cursor) -> list[dict[str, Any]]:
    names = [item[0] for item in cursor.description]
    return [dict(zip(names, row)) for row in cursor.fetchall()]


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
