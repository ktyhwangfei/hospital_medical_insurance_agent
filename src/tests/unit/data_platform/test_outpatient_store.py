from contextlib import contextmanager
from datetime import datetime, timezone
import re

import pytest

from src.adapters.insurance_interface.outpatient_source import (
    CheckpointKind,
    OutpatientChange,
    OutpatientCheckpoint,
    OutpatientSourceBatch,
    OutpatientSourceMode,
)
from src.data_platform.storage.postgresql.outpatient_store import OutpatientPostgresStore
from src.semantic_layer.registry import InMemoryRegistryStore, SemanticRegistry
from src.semantic_layer.seed import seed_semantic_layer


class _FakeCursor:
    def __init__(self, client):
        self.client = client
        self.row = None

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def execute(self, sql, params=()):
        if self.client.fail_on and self.client.fail_on in sql:
            raise RuntimeError("forced write failure")
        self.client.transaction_sql.append((sql, params))
        self.row = None
        if "FROM outpatient_sync_batches" in sql:
            if self.client.existing_batch_id:
                self.row = (
                    self.client.existing_batch_id,
                    self.client.published_at,
                    self.client.existing_row_count,
                )
        elif "INSERT INTO outpatient_sync_batches" in sql:
            self.client.existing_batch_id = params[0]
            self.client.existing_row_count = params[-3]
        elif "SELECT 1 FROM outpatient_sync_checkpoints" in sql:
            self.row = (1,)
        return self

    def fetchone(self):
        return self.row


class _FakeConnection:
    def __init__(self, client):
        self.client = client

    def cursor(self):
        return _FakeCursor(self.client)


class _FakeClient:
    def __init__(self):
        self.schema_sql = []
        self.transaction_sql = []
        self.transaction_count = 0
        self.committed = False
        self.rolled_back = False
        self.fail_on = None
        self.existing_batch_id = None
        self.existing_row_count = 0
        self.published_at = datetime(2026, 8, 28, tzinfo=timezone.utc)

    def execute(self, sql, params=()):
        self.schema_sql.append((sql, params))
        return []

    @contextmanager
    def transaction(self):
        self.transaction_count += 1
        try:
            yield _FakeConnection(self)
            self.committed = True
        except BaseException:
            self.rolled_back = True
            raise


def _change(capture, operation, key_values, **payload):
    payload.update(key_values)
    return OutpatientChange(
        capture_instance=capture,
        source_cursor=b"\x18" + bytes([operation]),
        operation=operation,
        commit_time=datetime(2026, 8, 28, tzinfo=timezone.utc),
        source_key=tuple(key_values.values()),
        payload=payload,
    )


def _changes():
    return (
        _change(
            "dbo_o_Trade", 2, {"T_TradeNo": "T1"},
            T_TradeDate="2026-08-28", T_FeeAll="100", T_FeeIn="80",
        ),
        _change(
            "dbo_o_FeeItem", 4,
            {"T_TradeNo": "T1", "ItemId": "I1", "ItemNo": "1"},
            Fee="100", FeeIn="80",
        ),
        _change(
            "dbo_o_Diagnose", 1,
            {"T_TradeNo": "T1", "DiagnoseNo": "D1", "RecipeNo": "R1"},
            DiagnoseCode="Z00",
        ),
    )


def _batch():
    return OutpatientSourceBatch(
        mode=OutpatientSourceMode.CDC,
        checkpoint=OutpatientCheckpoint(
            CheckpointKind.LSN, "20", datetime(2026, 8, 28, tzinfo=timezone.utc)
        ),
        changes=_changes(),
    )


def test_schema_is_idempotent_and_views_expose_only_fixed_semantic_columns() -> None:
    client = _FakeClient()
    store = OutpatientPostgresStore(client=client)

    store.ensure_schema()

    ddl = "\n".join(sql for sql, _params in client.schema_sql)
    for table in [
        "outpatient_sync_checkpoints", "outpatient_sync_batches", "outpatient_sync_events",
        "outpatient_trade_current", "outpatient_fee_item_current",
        "outpatient_diagnosis_current",
    ]:
        assert f"CREATE TABLE IF NOT EXISTS {table}" in ddl
    assert "ALTER TABLE outpatient_sync_batches ADD COLUMN IF NOT EXISTS semantic_version" in ddl
    assert "ALTER TABLE outpatient_sync_checkpoints ALTER COLUMN last_lsn DROP NOT NULL" in ddl
    assert "batch_key VARCHAR(64)" in ddl
    assert "source_mode VARCHAR(32)" in ddl
    assert "checkpoint_kind VARCHAR(32)" in ddl
    assert "checkpoint_value TEXT" in ddl
    assert "source_cursor BYTEA" in ddl
    assert "SET source_cursor = COALESCE(source_lsn" in ddl
    assert "ALTER COLUMN source_cursor SET NOT NULL" in ddl
    assert "ALTER TABLE outpatient_trade_current ADD COLUMN IF NOT EXISTS settlement_lifecycle" in ddl
    assert 'CREATE OR REPLACE VIEW mz_trade' in ddl
    assert 'AS "T_FeeAll"' in ddl
    assert 'CREATE OR REPLACE VIEW mz_fee_item' in ddl
    assert "P_IDNo" not in ddl
    assert "P_Name" not in ddl
    assert "trade.quality_status <> 'blocked'" in ddl
    assert "JOIN outpatient_trade_current AS trade" in ddl
    registry_store = InMemoryRegistryStore()
    seed_semantic_layer(registry_store)
    registry = SemanticRegistry(registry_store)
    for dataset_code, view_name in [("mz_trade", "mz_trade"), ("mz_fee_item", "mz_fee_item")]:
        view_sql = next(
            sql for sql, _params in client.schema_sql
            if sql.startswith(f"CREATE OR REPLACE VIEW {view_name}")
        )
        assert set(re.findall(r'AS "([^"]+)"', view_sql)) == {
            field.column_name for field in registry.list_fields(dataset_code=dataset_code)
        }


def test_publish_batch_is_atomic_ordered_and_idempotent() -> None:
    client = _FakeClient()
    store = OutpatientPostgresStore(client=client)

    first = store.publish_batch(
        source_id="bjybdb", execution_mode="incremental", batch=_batch(),
        semantic_version="1", quality_summary={"status": "complete"},
    )
    statement_count = len(client.transaction_sql)
    second = store.publish_batch(
        source_id="bjybdb", execution_mode="incremental", batch=_batch(),
        semantic_version="1", quality_summary={"status": "complete"},
    )

    assert client.transaction_count == 2
    assert first.batch_id == second.batch_id
    assert len(client.transaction_sql) == statement_count + 2  # advisory lock + identity lookup
    assert all(statement.count("%s") == len(params) for statement, params in client.transaction_sql)
    sql = [statement for statement, _params in client.transaction_sql[:statement_count]]
    event_sql = next(item for item in sql if "INSERT INTO outpatient_sync_events" in item)
    assert "event_key, source_id, source_mode, capture_instance, source_cursor" in event_sql
    assert "ON CONFLICT (event_key) DO NOTHING" in event_sql
    projection_sql = [item for item in sql if "_current" in item and "INSERT INTO" in item]
    assert len(projection_sql) == 3
    assert all(
        "WHERE EXCLUDED.source_cursor >=" in item
        for item in projection_sql
    )
    delete_call = next(
        params for statement, params in client.transaction_sql
        if "INSERT INTO outpatient_diagnosis_current" in statement
    )
    assert True in delete_call
    assert not any("DELETE FROM" in item for item in sql)
    assert "INSERT INTO outpatient_sync_batches" in sql[-2]
    assert "INSERT INTO outpatient_sync_checkpoints" in sql[-1]
    assert client.committed is True


def test_publish_batch_rolls_back_before_batch_and_checkpoint_on_projection_error() -> None:
    client = _FakeClient()
    client.fail_on = "INSERT INTO outpatient_fee_item_current"
    store = OutpatientPostgresStore(client=client)

    with pytest.raises(RuntimeError, match="forced write failure"):
        store.publish_batch(
            source_id="bjybdb", execution_mode="incremental", batch=_batch(),
            semantic_version="1", quality_summary={},
        )

    sql = [statement for statement, _params in client.transaction_sql]
    assert client.rolled_back is True
    assert not any("INSERT INTO outpatient_sync_batches" in item for item in sql)
    assert not any("INSERT INTO outpatient_sync_checkpoints" in item for item in sql)


def test_window_projection_read_is_parameterized_and_loads_children_by_trade() -> None:
    client = _FakeClient()
    store = OutpatientPostgresStore(client=client)
    start = datetime(2026, 8, 31, 8, tzinfo=timezone.utc)
    end = datetime(2026, 8, 31, 10, tzinfo=timezone.utc)

    store.load_projection_rows_for_window(start, end)

    trade_sql, params = next(
        item for item in client.schema_sql if "FROM outpatient_trade_current" in item[0]
    )
    assert "trade_date >= %s AND trade_date < %s" in trade_sql
    assert params == (start, end)


def test_writable_probe_uses_real_control_table_without_leaving_a_row() -> None:
    client = _FakeClient()
    store = OutpatientPostgresStore(client=client)

    assert store.check_writable() is True

    statements = [sql for sql, _params in client.transaction_sql]
    assert client.transaction_count == 1
    assert "INSERT INTO outpatient_sync_checkpoints" in statements[0]
    assert "SELECT 1 FROM outpatient_sync_checkpoints" in statements[1]
    assert "DELETE FROM outpatient_sync_checkpoints" in statements[2]
    assert client.committed is True
