from contextlib import contextmanager
from typing import Any

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

    @contextmanager
    def transaction(self):
        raise RuntimeError(self._reason)
        yield

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

    def _connect(self):
        try:
            import psycopg
        except ImportError as exc:
            raise RuntimeError("driver_not_installed") from exc
        return psycopg.connect(self._dsn, connect_timeout=self._connect_timeout_seconds)

    def execute(self, statement: SqlStatement) -> QueryResult:
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(statement.sql, statement.params)
                return QueryResult(rowcount=cursor.rowcount if cursor.rowcount >= 0 else 0)

    def fetch_one(self, statement: SqlStatement) -> dict[str, Any] | None:
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(statement.sql, statement.params)
                row = cursor.fetchone()
                if row is None:
                    return None
                columns = [column.name for column in cursor.description]
                return dict(zip(columns, row, strict=True))

    def fetch_all(self, statement: SqlStatement) -> list[dict[str, Any]]:
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(statement.sql, statement.params)
                rows = cursor.fetchall()
                columns = [column.name for column in cursor.description]
                return [dict(zip(columns, row, strict=True)) for row in rows]

    @contextmanager
    def transaction(self):
        with self._connect() as connection:
            with connection.transaction():
                yield

    def health(self) -> DatabaseHealth:
        try:
            self.fetch_one(SqlStatement(sql="select 1 as ok"))
        except RuntimeError as exc:
            return DatabaseHealth(status=DatabaseHealthStatus.UNHEALTHY, backend=self._backend, available=False, details={"reason": str(exc)})
        except Exception as exc:
            return DatabaseHealth(status=DatabaseHealthStatus.UNHEALTHY, backend=self._backend, available=False, details={"reason": "connection_failed", "error": exc.__class__.__name__})
        return DatabaseHealth(status=DatabaseHealthStatus.HEALTHY, backend=self._backend, available=True, details={"reason": "connected"})
