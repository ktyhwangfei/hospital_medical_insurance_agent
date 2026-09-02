"""不允许开 CDC 时的门诊固定 SQL 时间窗读取适配器。"""
from __future__ import annotations

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


def probe_outpatient_readiness(connection) -> tuple[int, int]:
    """验证固定门诊三表、契约字段和当前账号读取权限。"""
    cursor = connection.cursor()
    try:
        for spec in OUTPATIENT_SOURCE_SPECS.values():
            columns = ", ".join(f"[{column}]" for column in spec.columns)
            cursor.execute(
                f"SELECT TOP 1 {columns} FROM [dbo].[{spec.table_name}]"
            )
            cursor.fetchone()
    except Exception as exc:
        raise SourceContractMismatchError("门诊源表不可直接读取") from exc
    return len(OUTPATIENT_SOURCE_SPECS), sum(
        len(spec.columns) for spec in OUTPATIENT_SOURCE_SPECS.values()
    )


class SqlServerOutpatientPollingSource:
    def __init__(
        self,
        connection_factory: Callable[[], Any],
        *,
        clock: Callable[[], datetime] | None = None,
        lookback: timedelta = timedelta(hours=2),
        baseline_start: datetime | None = None,
    ) -> None:
        self._connection_factory = connection_factory
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._lookback = lookback
        self._baseline_start = baseline_start

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
            trade_spec = OUTPATIENT_SOURCE_SPECS["dbo_o_Trade"]
            columns = ", ".join(f"[{column}]" for column in trade_spec.columns)
            cursor.execute(
                f"SELECT {columns} FROM [dbo].[{trade_spec.table_name}] "
                "WHERE [T_TradeDate] >= ? AND [T_TradeDate] < ? "
                "ORDER BY [T_TradeDate], [T_TradeNo]",
                window_start,
                window_end,
            )
            trades = tuple(_rows_as_dicts(cursor))
            trade_nos = tuple(sorted({
                str(row["T_TradeNo"])
                for row in trades
                if row.get("T_TradeNo") not in (None, "")
            }))
            rows = {
                "dbo_o_Trade": trades,
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
            for capture, spec in OUTPATIENT_SOURCE_SPECS.items():
                columns = ", ".join(f"[{column}]" for column in spec.columns)
                order_by = ", ".join(f"[{column}]" for column in spec.key_columns)
                cursor.execute(
                    f"SELECT {columns} FROM [dbo].[{spec.table_name}] ORDER BY {order_by}"
                )
                rows[capture] = tuple(_rows_as_dicts(cursor))
            trade_nos = tuple(sorted({
                str(row["T_TradeNo"])
                for row in rows["dbo_o_Trade"]
                if row.get("T_TradeNo") not in (None, "")
            }))
            return _batch(rows, trade_nos, None, observed_at, True)
        finally:
            connection.close()

    @staticmethod
    def _read_children(cursor, capture: str, trade_nos: tuple[str, ...]):
        if not trade_nos:
            return ()
        spec = OUTPATIENT_SOURCE_SPECS[capture]
        columns = ", ".join(f"[{column}]" for column in spec.columns)
        rows = []
        for start in range(0, len(trade_nos), 500):
            chunk = trade_nos[start:start + 500]
            placeholders = ", ".join("?" for _ in chunk)
            cursor.execute(
                f"SELECT {columns} FROM [dbo].[{spec.table_name}] "
                f"WHERE [T_TradeNo] IN ({placeholders}) ORDER BY [T_TradeNo]",
                *chunk,
            )
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
