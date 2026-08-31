from datetime import datetime, timedelta, timezone

from src.adapters.insurance_interface.outpatient_polling import (
    SqlServerOutpatientPollingSource,
)
from src.adapters.insurance_interface.outpatient_source import (
    CheckpointKind,
    OutpatientCheckpoint,
    OutpatientSourceMode,
)


END = datetime(2026, 8, 31, 10, tzinfo=timezone.utc)


class _Cursor:
    def __init__(self, connection):
        self.connection = connection
        self.description = []
        self.rows = []

    def execute(self, sql, *params):
        self.connection.executions.append((sql, params))
        if "[dbo].[o_Trade]" in sql:
            self.description = [("T_TradeNo",), ("T_TradeDate",)]
            self.rows = [(trade_no, END - timedelta(minutes=1)) for trade_no in self.connection.trade_nos]
        elif "[dbo].[o_FeeItem]" in sql:
            self.description = [("T_TradeNo",), ("ItemId",), ("ItemNo",)]
            self.rows = [(str(value), "I1", "1") for value in params]
        elif "[dbo].[o_Diagnose]" in sql:
            self.description = [("T_TradeNo",), ("DiagnoseNo",), ("RecipeNo",)]
            self.rows = [(str(value), "D1", "R1") for value in params]
        return self

    def fetchall(self):
        return self.rows


class _Connection:
    def __init__(self, trade_nos=("T1",)):
        self.trade_nos = trade_nos
        self.executions = []
        self.closed = False

    def cursor(self):
        return _Cursor(self)

    def close(self):
        self.closed = True


def test_polling_source_uses_parameterized_trade_window() -> None:
    connection = _Connection()
    source = SqlServerOutpatientPollingSource(lambda: connection, clock=lambda: END)

    batch = source.read_time_window(END - timedelta(hours=2), END)

    trade_sql, params = next(
        execution for execution in connection.executions if "[dbo].[o_Trade]" in execution[0]
    )
    assert "[T_TradeDate] >= ?" in trade_sql
    assert "[T_TradeDate] < ?" in trade_sql
    assert params == (END - timedelta(hours=2), END)
    assert batch.mode is OutpatientSourceMode.SCHEDULED_SQL
    assert batch.checkpoint.kind is CheckpointKind.TIME_WINDOW
    assert batch.window_start == END - timedelta(hours=2)
    assert connection.closed is True


def test_polling_source_chunks_child_queries_to_500_trade_numbers() -> None:
    connection = _Connection(tuple(f"T{i}" for i in range(501)))
    source = SqlServerOutpatientPollingSource(lambda: connection, clock=lambda: END)

    source.read_time_window(END - timedelta(hours=2), END)

    fee_calls = [item for item in connection.executions if "[dbo].[o_FeeItem]" in item[0]]
    diagnosis_calls = [item for item in connection.executions if "[dbo].[o_Diagnose]" in item[0]]
    assert [len(params) for _sql, params in fee_calls] == [500, 1]
    assert [len(params) for _sql, params in diagnosis_calls] == [500, 1]
    assert all(sql.count("?") == len(params) for sql, params in fee_calls + diagnosis_calls)


def test_first_read_is_controlled_baseline_and_next_read_uses_lookback() -> None:
    connection = _Connection()
    source = SqlServerOutpatientPollingSource(
        lambda: connection,
        clock=lambda: END,
        lookback=timedelta(hours=2),
    )

    baseline = source.read(None)
    assert baseline.is_baseline is True
    trade_sql = next(sql for sql, _params in connection.executions if "[dbo].[o_Trade]" in sql)
    assert "T_TradeDate] >=" not in trade_sql

    connection = _Connection()
    source = SqlServerOutpatientPollingSource(
        lambda: connection,
        clock=lambda: END,
        lookback=timedelta(hours=2),
    )
    incremental = source.read(
        OutpatientCheckpoint(CheckpointKind.TIME_WINDOW, (END - timedelta(minutes=5)).isoformat(), END)
    )
    assert incremental.is_baseline is False
    assert incremental.window_start == END - timedelta(hours=2)
