import sys
from types import SimpleNamespace

import pytest

from src.data_platform.persistence.executors import PsycopgDatabaseExecutor, UnavailableDatabaseExecutor
from src.data_platform.persistence.models import DatabaseBackend, DatabaseHealthStatus, SqlStatement


class FakeCursor:
    def __init__(self, description=None, one=None, rows=None, rowcount=1):
        self.description = description
        self._one = one
        self._rows = rows or []
        self.rowcount = rowcount
        self.executed: list[tuple[str, object]] = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return None

    def execute(self, sql, params=None):
        self.executed.append((sql, params))

    def fetchone(self):
        return self._one

    def fetchall(self):
        return self._rows


class FakeTransaction:
    def __init__(self, connection):
        self.connection = connection

    def __enter__(self):
        self.connection.transaction_enter_count += 1
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.connection.transaction_exit_count += 1
        return None


class FakeConnection:
    def __init__(self, cursors):
        self._cursors = list(cursors)
        self.cursor_count = 0
        self.enter_count = 0
        self.exit_count = 0
        self.transaction_enter_count = 0
        self.transaction_exit_count = 0

    def __enter__(self):
        self.enter_count += 1
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.exit_count += 1
        return None

    def cursor(self):
        cursor = self._cursors[self.cursor_count]
        self.cursor_count += 1
        return cursor

    def transaction(self):
        return FakeTransaction(self)


class FakePsycopg:
    def __init__(self, connections=None, error=None):
        self._connections = list(connections or [])
        self._error = error
        self.connect_calls: list[tuple[str, int]] = []

    def connect(self, dsn, connect_timeout):
        self.connect_calls.append((dsn, connect_timeout))
        if self._error is not None:
            raise self._error
        return self._connections.pop(0)


def install_fake_psycopg(monkeypatch, fake):
    monkeypatch.setitem(sys.modules, "psycopg", fake)


def columns(*names):
    return [SimpleNamespace(name=name) for name in names]


def test_unavailable_executor_reports_driver_not_installed():
    executor = UnavailableDatabaseExecutor(DatabaseBackend.POSTGRESQL, "driver_not_installed")

    health = executor.health()

    assert health.status == DatabaseHealthStatus.UNHEALTHY
    assert health.backend == DatabaseBackend.POSTGRESQL
    assert health.available is False
    assert health.details["reason"] == "driver_not_installed"


def test_unavailable_executor_raises_on_query():
    executor = UnavailableDatabaseExecutor(DatabaseBackend.POSTGRESQL, "driver_not_installed")

    try:
        executor.fetch_one(SqlStatement(sql="select 1"))
    except RuntimeError as exc:
        assert "driver_not_installed" in str(exc)
    else:
        raise AssertionError("expected RuntimeError")


def test_unavailable_executor_transaction_raises_stable_reason():
    executor = UnavailableDatabaseExecutor(DatabaseBackend.POSTGRESQL, "driver_not_installed")

    with pytest.raises(RuntimeError, match="driver_not_installed"):
        with executor.transaction():
            raise AssertionError("transaction should not enter")


def test_psycopg_executor_fetch_one_converts_row_to_dict(monkeypatch):
    cursor = FakeCursor(description=columns("id", "name"), one=("P001", "张三"))
    fake = FakePsycopg([FakeConnection([cursor])])
    install_fake_psycopg(monkeypatch, fake)
    executor = PsycopgDatabaseExecutor("postgresql://user:password@localhost/db")

    result = executor.fetch_one(SqlStatement(sql="select id, name from patients", params=("P001",)))

    assert result == {"id": "P001", "name": "张三"}
    assert cursor.executed == [("select id, name from patients", ("P001",))]


def test_psycopg_executor_fetch_all_converts_rows_to_dicts(monkeypatch):
    cursor = FakeCursor(description=columns("id", "amount"), rows=[("F001", 10), ("F002", 20)])
    fake = FakePsycopg([FakeConnection([cursor])])
    install_fake_psycopg(monkeypatch, fake)
    executor = PsycopgDatabaseExecutor("postgresql://user:password@localhost/db")

    result = executor.fetch_all(SqlStatement(sql="select id, amount from fees"))

    assert result == [{"id": "F001", "amount": 10}, {"id": "F002", "amount": 20}]


def test_psycopg_executor_fetch_one_requires_columns(monkeypatch):
    cursor = FakeCursor(description=None, one=(1,))
    fake = FakePsycopg([FakeConnection([cursor])])
    install_fake_psycopg(monkeypatch, fake)
    executor = PsycopgDatabaseExecutor("postgresql://user:password@localhost/db")

    with pytest.raises(RuntimeError, match="query_returned_no_columns"):
        executor.fetch_one(SqlStatement(sql="select 1"))


def test_psycopg_executor_fetch_all_requires_columns(monkeypatch):
    cursor = FakeCursor(description=None, rows=[(1,)])
    fake = FakePsycopg([FakeConnection([cursor])])
    install_fake_psycopg(monkeypatch, fake)
    executor = PsycopgDatabaseExecutor("postgresql://user:password@localhost/db")

    with pytest.raises(RuntimeError, match="query_returned_no_columns"):
        executor.fetch_all(SqlStatement(sql="select 1"))


def test_psycopg_executor_health_does_not_leak_sensitive_runtime_error(monkeypatch):
    fake = FakePsycopg(error=RuntimeError("failed to connect postgresql://user:secret@localhost/db password=secret"))
    install_fake_psycopg(monkeypatch, fake)
    executor = PsycopgDatabaseExecutor("postgresql://user:secret@localhost/db")

    health = executor.health()

    assert health.status == DatabaseHealthStatus.UNHEALTHY
    assert health.details == {"reason": "runtime_error"}
    assert "secret" not in str(health.details)


def test_psycopg_executor_health_preserves_allowed_runtime_error(monkeypatch):
    cursor = FakeCursor(description=None, one=(1,))
    fake = FakePsycopg([FakeConnection([cursor])])
    install_fake_psycopg(monkeypatch, fake)
    executor = PsycopgDatabaseExecutor("postgresql://user:password@localhost/db")

    health = executor.health()

    assert health.status == DatabaseHealthStatus.UNHEALTHY
    assert health.details == {"reason": "query_returned_no_columns"}


def test_psycopg_executor_transaction_reuses_connection_for_execute(monkeypatch):
    first_cursor = FakeCursor(rowcount=3)
    second_cursor = FakeCursor(rowcount=4)
    connection = FakeConnection([first_cursor, second_cursor])
    fake = FakePsycopg([connection])
    install_fake_psycopg(monkeypatch, fake)
    executor = PsycopgDatabaseExecutor("postgresql://user:password@localhost/db")

    with executor.transaction():
        first = executor.execute(SqlStatement(sql="insert into a values (%s)", params=(1,)))
        second = executor.execute(SqlStatement(sql="insert into a values (%s)", params=(2,)))

    assert first.rowcount == 3
    assert second.rowcount == 4
    assert len(fake.connect_calls) == 1
    assert connection.cursor_count == 2
    assert connection.transaction_enter_count == 1
    assert connection.transaction_exit_count == 1


def test_psycopg_executor_nested_transaction_raises(monkeypatch):
    connection = FakeConnection([FakeCursor()])
    fake = FakePsycopg([connection])
    install_fake_psycopg(monkeypatch, fake)
    executor = PsycopgDatabaseExecutor("postgresql://user:password@localhost/db")

    with executor.transaction():
        with pytest.raises(RuntimeError, match="transaction_already_active"):
            with executor.transaction():
                raise AssertionError("nested transaction should not enter")
