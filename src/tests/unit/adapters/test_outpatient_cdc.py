from datetime import datetime, timezone

import pytest

from src.adapters.insurance_interface.outpatient_cdc import (
    OUTPATIENT_SOURCE_SPECS,
    CdcRetentionGapError,
    SourceContractMismatchError,
    SqlServerOutpatientCdcSource,
)


class _FakeCursor:
    def __init__(self, connection):
        self.connection = connection
        self.description = []
        self.rows = []

    def execute(self, sql, *params):
        self.connection.calls.append((sql, params))
        self.rows = []
        if "INFORMATION_SCHEMA.COLUMNS" in sql:
            self.description = [("TABLE_NAME",), ("COLUMN_NAME",)]
            self.rows = [
                (spec.table_name, column)
                for capture, spec in OUTPATIENT_SOURCE_SPECS.items()
                for column in spec.columns
                if (capture, column) != self.connection.missing_column
            ]
        elif "fn_cdc_get_max_lsn" in sql:
            self.description = [("max_lsn",)]
            self.rows = [(self.connection.max_lsn,)]
        elif "fn_cdc_get_min_lsn" in sql:
            self.description = [("min_lsn",)]
            self.rows = [(self.connection.min_lsn[params[0]],)]
        elif "fn_cdc_increment_lsn" in sql:
            self.description = [("from_lsn",)]
            self.rows = [(self.connection.incremented_lsn,)]
        elif "fn_cdc_get_all_changes_" in sql:
            capture, spec = next(
                (capture, spec)
                for capture, spec in OUTPATIENT_SOURCE_SPECS.items()
                if capture in sql
            )
            self.description = [
                ("start_lsn",), ("seqval",), ("operation",), ("commit_time",),
                *((column,) for column in spec.columns),
            ]
            values = _values(spec, capture)
            self.rows = [
                (b"\x18", bytes([operation]), operation, self.connection.commit_time, *values)
                for operation in (1, 2, 3, 4)
            ]
        else:
            capture, spec = next(
                (capture, spec)
                for capture, spec in OUTPATIENT_SOURCE_SPECS.items()
                if f"[dbo].[{spec.table_name}]" in sql
            )
            self.description = [(column,) for column in spec.columns]
            self.rows = [tuple(_values(spec, capture))]
        return self

    def fetchone(self):
        return self.rows[0] if self.rows else None

    def fetchall(self):
        return self.rows


class _FakeConnection:
    def __init__(self):
        self.calls = []
        self.max_lsn = b"\x20"
        self.incremented_lsn = b"\x11"
        self.min_lsn = {capture: b"\x10" for capture in OUTPATIENT_SOURCE_SPECS}
        self.commit_time = datetime(2026, 8, 28, tzinfo=timezone.utc)
        self.missing_column = None
        self.closed = False

    def cursor(self):
        return _FakeCursor(self)

    def close(self):
        self.closed = True


def _values(spec, capture):
    fixed = {
        "T_TradeNo": f"{capture}-trade", "ItemId": "item", "ItemNo": "1",
        "DiagnoseNo": "diagnosis", "RecipeNo": "recipe",
    }
    return [fixed.get(column, f"{capture}:{column}") for column in spec.columns]


def _payloads(result):
    if hasattr(result, "changes"):
        return [change.payload for change in result.changes]
    return [row for rows in result.rows_by_capture.values() for row in rows]


def test_snapshot_uses_one_max_lsn_then_reads_all_whitelisted_tables() -> None:
    connection = _FakeConnection()
    result = SqlServerOutpatientCdcSource(lambda: connection).read_snapshot()

    assert result.checkpoint_lsn == b"\x20"
    assert set(result.rows_by_capture) == set(OUTPATIENT_SOURCE_SPECS)
    max_call = next(i for i, (sql, _params) in enumerate(connection.calls) if "get_max_lsn" in sql)
    table_calls = [
        i for i, (sql, _params) in enumerate(connection.calls)
        if any(f"[dbo].[{spec.table_name}]" in sql for spec in OUTPATIENT_SOURCE_SPECS.values())
    ]
    assert max_call < min(table_calls)
    assert connection.closed is True
    _assert_no_sensitive_payload(_payloads(result))


def test_incremental_reads_after_images_with_one_shared_lsn_window() -> None:
    connection = _FakeConnection()
    result = SqlServerOutpatientCdcSource(lambda: connection).read_changes(b"\x10")

    assert (result.from_lsn, result.to_lsn) == (b"\x11", b"\x20")
    assert {change.operation for change in result.changes} == {1, 2, 4}
    assert len(result.changes) == 9
    assert all(change.commit_time == connection.commit_time for change in result.changes)
    assert all(change.source_key for change in result.changes)
    cdc_calls = [call for call in connection.calls if "fn_cdc_get_all_changes_" in call[0]]
    assert len(cdc_calls) == 3
    assert all(params == (b"\x11", b"\x20") for _sql, params in cdc_calls)
    _assert_no_sensitive_payload(_payloads(result))


def test_incremental_fails_closed_when_checkpoint_falls_out_of_retention() -> None:
    connection = _FakeConnection()
    connection.min_lsn["dbo_o_FeeItem"] = b"\x20"

    with pytest.raises(CdcRetentionGapError) as exc_info:
        SqlServerOutpatientCdcSource(lambda: connection).read_changes(b"\x10")

    assert exc_info.value.error_code == "cdc_retention_gap"


def test_source_contract_mismatch_names_the_missing_whitelisted_column() -> None:
    connection = _FakeConnection()
    connection.missing_column = ("dbo_o_Trade", "T_FeeAll")

    with pytest.raises(SourceContractMismatchError) as exc_info:
        SqlServerOutpatientCdcSource(lambda: connection).read_snapshot()

    assert exc_info.value.error_code == "source_contract_mismatch"
    assert "o_Trade.T_FeeAll" in str(exc_info.value)


def _assert_no_sensitive_payload(payloads) -> None:
    forbidden = {"P_IDNo", "P_ICNo", "P_Name", "P_Birthday", "P_CardNo", "HisName", "HisCode"}
    for payload in payloads:
        assert forbidden.isdisjoint(payload)
        if "ItemId" in payload:
            assert "RecipeNo" not in payload
