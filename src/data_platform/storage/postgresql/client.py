import os
from contextlib import contextmanager
from typing import Any


class PostgreSQLClient:
    """PostgreSQL connection manager with lazy initialization.

    Does not connect until first use. Supports DATABASE_URL environment variable
    as default connection string.
    """

    _CONNECT_TIMEOUT = int(os.environ.get("POSTGRES_CONNECT_TIMEOUT", "5"))

    def __init__(self, database_url: str | None = None):
        self._database_url = database_url or os.environ.get("DATABASE_URL")
        self._conn = None

    def _ensure_connected(self) -> None:
        if self._conn is not None:
            return
        if not self._database_url:
            msg = "DATABASE_URL is not configured. Set the DATABASE_URL environment variable or pass database_url to the constructor."
            raise RuntimeError(msg)
        import psycopg

        print(f"[STARTUP] PostgreSQLClient: 正在连接 {self._database_url} (超时={self._CONNECT_TIMEOUT}s)", flush=True)
        try:
            self._conn = psycopg.connect(
                self._database_url,
                autocommit=True,
                connect_timeout=self._CONNECT_TIMEOUT,
            )
            print("[STARTUP] PostgreSQLClient: 连接成功", flush=True)
        except psycopg.OperationalError as e:
            print(f"[STARTUP] PostgreSQLClient: 连接失败 (超时={self._CONNECT_TIMEOUT}s) — {e}", flush=True)
            raise

    @contextmanager
    def transaction(self):
        """Transaction context manager. Commits on success, rolls back on error."""
        self._ensure_connected()
        self._conn.execute("BEGIN")
        try:
            yield self._conn
            self._conn.execute("COMMIT")
        except BaseException:
            if self._conn is not None:
                self._conn.execute("ROLLBACK")
            raise

    def execute(self, sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
        """Execute a SQL statement and return rows as dicts (if any)."""
        self._ensure_connected()
        with self._conn.cursor() as cur:
            cur.execute(sql, params)
            if cur.description is None:
                return []
            columns = [col.name for col in cur.description]
            return [dict(zip(columns, row)) for row in cur.fetchall()]

    def execute_many(self, sql: str, params_list: list[tuple[Any, ...]]) -> None:
        """Execute the same SQL with multiple parameter sets."""
        self._ensure_connected()
        with self._conn.cursor() as cur:
            for params in params_list:
                cur.execute(sql, params)

    def health(self) -> bool:
        """Check if the database connection is healthy."""
        try:
            self._ensure_connected()
            with self._conn.cursor() as cur:
                cur.execute("SELECT 1")
                return True
        except Exception:
            return False

    def close(self) -> None:
        """Close the underlying connection if open."""
        if self._conn is not None:
            try:
                self._conn.close()
            except Exception:
                pass
            self._conn = None

    @property
    def is_connected(self) -> bool:
        return self._conn is not None and not self._conn.closed
