from datetime import datetime, timedelta, timezone

import pytest

from src.adapters.insurance_interface.outpatient_cdc import SourceContractMismatchError
from src.adapters.insurance_interface.outpatient_polling import (
    SqlServerOutpatientPollingSource,
    probe_outpatient_readiness,
)
from src.adapters.insurance_interface.outpatient_source import (
    OUTPATIENT_SOURCE_SPECS,
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
        if self.connection.fail_table and f"[{self.connection.fail_table}]" in sql:
            raise RuntimeError("raw database error")
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

    def fetchone(self):
        return self.rows[0] if self.rows else None


class _Connection:
    def __init__(self, trade_nos=("T1",), fail_table=None):
        self.trade_nos = trade_nos
        self.fail_table = fail_table
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


def test_readiness_probe_reads_all_three_tables_and_contract_columns() -> None:
    connection = _Connection()

    table_count, column_count = probe_outpatient_readiness(connection)

    assert table_count == 3
    assert column_count == 117
    probes = [sql for sql, _params in connection.executions if sql.startswith("SELECT TOP 1")]
    assert len(probes) == 3
    for spec in OUTPATIENT_SOURCE_SPECS.values():
        sql = next(item for item in probes if f"[dbo].[{spec.table_name}]" in item)
        assert all(f"[{column}]" in sql for column in spec.columns)


def test_readiness_probe_hides_raw_table_error() -> None:
    connection = _Connection(fail_table="o_FeeItem")

    with pytest.raises(SourceContractMismatchError, match="门诊源表不可直接读取") as caught:
        probe_outpatient_readiness(connection)

    assert "raw database error" not in str(caught.value)


# ---- 源表映射（真实医院表名/列名 → 契约字段别名）----

from datetime import datetime as _dt  # noqa: E402

from src.adapters.insurance_interface.outpatient_polling import (  # noqa: E402
    SqlServerOutpatientPollingSource,
    baseline_sql,
    children_sql,
    probe_outpatient_readiness,
    resolve_capture,
    window_sql,
)
from src.data_platform.outpatient_governance import (  # noqa: E402
    CaptureMapping,
    OutpatientSourceMapping,
)


def _custom_mapping() -> OutpatientSourceMapping:
    """医院 HIS 自定义表名：交易表 his.MZ_JYLS，时间字段列名 JY_RQ，交易号列名 JYLSH。"""
    now = _dt(2026, 9, 1, tzinfo=timezone.utc)
    trade = CaptureMapping(
        capture="dbo_o_Trade", table_schema="his", table_name="MZ_JYLS",
        key_fields=("T_TradeNo",),
        column_map={"T_TradeNo": "JYLSH", "T_TradeDate": "JY_RQ", "T_State": "ZT"},
    )
    fee = CaptureMapping(
        capture="dbo_o_FeeItem", table_schema="his", table_name="MZ_SFMX",
        key_fields=("T_TradeNo", "ItemId", "ItemNo"),
        column_map={"T_TradeNo": "JYLSH", "ItemId": "MX_ID", "ItemNo": "XM_NO"},
    )
    diagnose = CaptureMapping(
        capture="dbo_o_Diagnose", table_schema="his", table_name="MZ_ZD",
        key_fields=("T_TradeNo", "DiagnoseNo"),
        column_map={"T_TradeNo": "JYLSH", "DiagnoseNo": "ZD_ID"},
    )
    return OutpatientSourceMapping(
        source_id="his-prod", captures={
            "dbo_o_Trade": trade, "dbo_o_FeeItem": fee, "dbo_o_Diagnose": diagnose,
        },
        revision=1, created_at=now, updated_at=now,
    )


def test_window_sql_uses_source_time_column_and_contract_alias() -> None:
    mapping = _custom_mapping()
    resolved = resolve_capture(mapping.captures["dbo_o_Trade"])

    sql = window_sql(resolved)

    assert "[his].[MZ_JYLS]" in sql
    assert "[JY_RQ] >= ? AND [JY_RQ] < ?" in sql
    assert "[JYLSH] AS [T_TradeNo]" in sql
    assert "[JY_RQ] AS [T_TradeDate]" in sql
    assert "[T_TradeDate]" not in sql.replace("AS [T_TradeDate]", "")  # WHERE/ORDER BY 不用别名


def test_baseline_and_children_sql_use_mapping() -> None:
    mapping = _custom_mapping()
    fee = resolve_capture(mapping.captures["dbo_o_FeeItem"])

    assert baseline_sql(fee) == (
        "SELECT [JYLSH] AS [T_TradeNo], [MX_ID] AS [ItemId], [XM_NO] AS [ItemNo] "
        "FROM [his].[MZ_SFMX] ORDER BY [JYLSH], [MX_ID], [XM_NO]"
    )
    assert children_sql(fee, 2) == (
        "SELECT [JYLSH] AS [T_TradeNo], [MX_ID] AS [ItemId], [XM_NO] AS [ItemNo] "
        "FROM [his].[MZ_SFMX] WHERE [JYLSH] IN (?, ?) ORDER BY [JYLSH]"
    )


def test_polling_source_reads_custom_tables_under_contract_names() -> None:
    connection = _CustomConnection()
    source = SqlServerOutpatientPollingSource(
        lambda: connection, clock=lambda: END, mapping=_custom_mapping()
    )

    batch = source.read_time_window(END - timedelta(hours=2), END)

    trade_sql = next(sql for sql, _ in connection.executions if "MZ_JYLS" in sql)
    assert "[JY_RQ] >= ?" in trade_sql
    # 读取结果以契约字段名暴露，下游语义层无感
    trade_row = batch.snapshot_rows["dbo_o_Trade"][0]
    assert trade_row["T_TradeNo"] == "T1"
    assert trade_row["T_TradeDate"] == END
    child_sql = next(sql for sql, _ in connection.executions if "MZ_SFMX" in sql)
    assert "WHERE [JYLSH] IN" in child_sql
    assert batch.scope_trade_nos == frozenset({"T1"})


def test_probe_with_mapping_counts_mapped_fields() -> None:
    connection = _CustomConnection()

    table_count, field_count = probe_outpatient_readiness(connection, _custom_mapping())

    assert table_count == 3
    assert field_count == 8  # 3+3+2 个映射字段
    assert all("FROM [his]." in sql for sql, _ in connection.executions)


def test_window_sql_rejects_capture_without_time_field() -> None:
    mapping = _custom_mapping()
    fee = resolve_capture(mapping.captures["dbo_o_FeeItem"])

    with pytest.raises(ValueError, match="T_TradeDate"):
        window_sql(fee)


class _CustomCursor:
    def __init__(self, connection):
        self.connection = connection
        self.description = []
        self.rows = []

    def execute(self, sql, *params):
        self.connection.executions.append((sql, params))
        if "[his].[MZ_JYLS]" in sql:
            # 源列名返回数据，验证别名改写为契约字段名（SQL Server 对别名列返回别名）
            self.description = [("T_TradeNo",), ("T_TradeDate",), ("T_State",)]
            self.rows = [("T1", END, 3)]
        elif "[his].[MZ_SFMX]" in sql:
            self.description = [("T_TradeNo",), ("ItemId",), ("ItemNo",)]
            self.rows = [(str(value), "I1", "N1") for value in params]
        elif "[his].[MZ_ZD]" in sql:
            self.description = [("T_TradeNo",), ("DiagnoseNo",)]
            self.rows = [(str(value), "D1") for value in params]
        return self

    def fetchall(self):
        return self.rows

    def fetchone(self):
        return self.rows[0] if self.rows else None


class _CustomConnection:
    def __init__(self):
        self.executions = []
        self.closed = False

    def cursor(self):
        return _CustomCursor(self)

    def close(self):
        self.closed = True
