from contextlib import AbstractContextManager, contextmanager
from types import TracebackType
from typing import Any, Iterator

from src.data_platform.persistence.models import DatabaseBackend, DatabaseHealth, DatabaseHealthStatus, QueryResult, SqlStatement


class UnavailableDatabaseExecutor:
    def __init__(self, backend: DatabaseBackend, reason: str):
        self._backend = backend
        self._reason = reason

    def execute(self, statement: SqlStatement) -> QueryResult:
        raise RuntimeError(self._reason)

    def fetch_one(self, statement: SqlStatement) -> dict[str, Any] | None:
        raise RuntimeError(self._reason)

    def fetch_all(self, statement: SqlStatement) -> list[dict[str, Any]]:
        raise RuntimeError(self._reason)

    class _UnavailableTransaction(AbstractContextManager[None]):
        def __init__(self, reason: str):
            self._reason = reason

        def __enter__(self) -> None:
            raise RuntimeError(self._reason)

        def __exit__(self, exc_type: type[BaseException] | None, exc_value: BaseException | None, traceback: TracebackType | None) -> None:
            return None

    def transaction(self) -> AbstractContextManager[None]:
        return self._UnavailableTransaction(self._reason)

    def health(self) -> DatabaseHealth:
        return DatabaseHealth(
            status=DatabaseHealthStatus.UNHEALTHY,
            backend=self._backend,
            available=False,
            details={"reason": self._reason},
        )


class PsycopgDatabaseExecutor:
    def __init__(self, dsn: str, backend: DatabaseBackend = DatabaseBackend.POSTGRESQL, connect_timeout_seconds: int = 10):
        self._dsn = dsn
        self._backend = backend
        self._connect_timeout_seconds = connect_timeout_seconds
        self._transaction_connection: Any | None = None

    def _connect(self):
        try:
            import psycopg
        except ImportError as exc:
            raise RuntimeError("driver_not_installed") from exc
        return psycopg.connect(self._dsn, connect_timeout=self._connect_timeout_seconds)

    def _active_connection(self) -> Any | None:
        return self._transaction_connection

    def _columns(self, cursor: Any) -> list[str]:
        if cursor.description is None:
            raise RuntimeError("query_returned_no_columns")
        return [column.name for column in cursor.description]

    def execute(self, statement: SqlStatement) -> QueryResult:
        active_connection = self._active_connection()
        if active_connection is not None:
            with active_connection.cursor() as cursor:
                cursor.execute(statement.sql, statement.params)
                return QueryResult(rowcount=cursor.rowcount if cursor.rowcount >= 0 else 0)
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(statement.sql, statement.params)
                return QueryResult(rowcount=cursor.rowcount if cursor.rowcount >= 0 else 0)

    def fetch_one(self, statement: SqlStatement) -> dict[str, Any] | None:
        active_connection = self._active_connection()
        if active_connection is not None:
            with active_connection.cursor() as cursor:
                cursor.execute(statement.sql, statement.params)
                row = cursor.fetchone()
                if row is None:
                    return None
                columns = self._columns(cursor)
                return dict(zip(columns, row, strict=True))
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(statement.sql, statement.params)
                row = cursor.fetchone()
                if row is None:
                    return None
                columns = self._columns(cursor)
                return dict(zip(columns, row, strict=True))

    def fetch_all(self, statement: SqlStatement) -> list[dict[str, Any]]:
        active_connection = self._active_connection()
        if active_connection is not None:
            with active_connection.cursor() as cursor:
                cursor.execute(statement.sql, statement.params)
                rows = cursor.fetchall()
                columns = self._columns(cursor)
                return [dict(zip(columns, row, strict=True)) for row in rows]
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(statement.sql, statement.params)
                rows = cursor.fetchall()
                columns = self._columns(cursor)
                return [dict(zip(columns, row, strict=True)) for row in rows]

    @contextmanager
    def transaction(self) -> Iterator[None]:
        if self._transaction_connection is not None:
            raise RuntimeError("transaction_already_active")
        with self._connect() as connection:
            self._transaction_connection = connection
            try:
                with connection.transaction():
                    yield
            finally:
                self._transaction_connection = None

    def _health_runtime_reason(self, reason: str) -> str:
        allowed_reasons = {"driver_not_installed", "query_returned_no_columns", "transaction_already_active"}
        if reason in allowed_reasons:
            return reason
        return "runtime_error"

    def health(self) -> DatabaseHealth:
        try:
            self.fetch_one(SqlStatement(sql="select 1 as ok"))
        except RuntimeError as exc:
            return DatabaseHealth(status=DatabaseHealthStatus.UNHEALTHY, backend=self._backend, available=False, details={"reason": self._health_runtime_reason(str(exc))})
        except Exception as exc:
            return DatabaseHealth(status=DatabaseHealthStatus.UNHEALTHY, backend=self._backend, available=False, details={"reason": "connection_failed", "error": exc.__class__.__name__})
        return DatabaseHealth(status=DatabaseHealthStatus.HEALTHY, backend=self._backend, available=True, details={"reason": "connected"})
