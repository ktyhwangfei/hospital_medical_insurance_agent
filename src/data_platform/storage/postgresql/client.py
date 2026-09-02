import os
from contextlib import contextmanager
from threading import RLock
from typing import Any
from urllib.parse import urlsplit


class PostgreSQLClient:
    """PostgreSQL connection manager with lazy initialization.

    Does not connect until first use. Supports DATABASE_URL environment variable
    as default connection string.
    """

    _CONNECT_TIMEOUT = int(os.environ.get("POSTGRES_CONNECT_TIMEOUT", "5"))

    def __init__(self, database_url: str | None = None):
        self._database_url = (
            database_url
            or os.environ.get("DATABASE_URL")
            or self._build_url_from_postgres_env()
        )
        self._conn = None
        # 单连接会被 FastAPI 的工作线程共享；锁必须覆盖完整事务，避免语句串入。
        self._operation_lock = RLock()

    @staticmethod
    def _build_url_from_postgres_env() -> str | None:
        """DATABASE_URL 缺失时，从 POSTGRES_* 分项变量合成连接串。

        与 src/config/production.py 的合成逻辑保持一致，避免 PolicyMetaStore
        等无参构造场景因 .env 未显式写 DATABASE_URL 而连不上。
        """
        host = os.environ.get("POSTGRES_HOST")
        if not host:
            return None
        user = os.environ.get("POSTGRES_USER", "postgres")
        password = os.environ.get("POSTGRES_PASSWORD", "")
        port = os.environ.get("POSTGRES_PORT", "5432")
        db = os.environ.get("POSTGRES_DB", "hospital_mcp")
        return f"postgresql://{user}:{password}@{host}:{port}/{db}"

    def _ensure_connected(self) -> None:
        if self._conn is not None:
            return
        if not self._database_url:
            msg = "DATABASE_URL is not configured. Set the DATABASE_URL environment variable or pass database_url to the constructor."
            raise RuntimeError(msg)

        print(
            f"[STARTUP] PostgreSQLClient: 正在连接 {_safe_database_target(self._database_url)} "
            f"(超时={self._CONNECT_TIMEOUT}s)",
            flush=True,
        )
        
        # 尝试 psycopg (v3) 或回退到 psycopg2
        try:
            import psycopg
            self._conn = psycopg.connect(
                self._database_url,
                autocommit=True,
                connect_timeout=self._CONNECT_TIMEOUT,
            )
            print("[STARTUP] PostgreSQLClient: 使用 psycopg v3 连接成功", flush=True)
        except ImportError:
            print("[STARTUP] PostgreSQLClient: psycopg v3 不可用，尝试 psycopg2...", flush=True)
            import psycopg2
            import psycopg2.extras
            self._conn = psycopg2.connect(
                self._database_url,
                connect_timeout=self._CONNECT_TIMEOUT,
            )
            self._conn.autocommit = True
            print("[STARTUP] PostgreSQLClient: 使用 psycopg2 连接成功", flush=True)
        except Exception as e:
            safe_error = _redact_database_error(e, self._database_url)
            print(
                f"[STARTUP] PostgreSQLClient: 连接失败 "
                f"(超时={self._CONNECT_TIMEOUT}s) — {safe_error}",
                flush=True,
            )
            host_hint = _safe_database_target(self._database_url)
            raise RuntimeError(
                f"知识库数据源(PostgreSQL)不可达：{safe_error}。"
                f"请确认 PostgreSQL 服务已启动（{host_hint}）。"
            ) from e

    @contextmanager
    def transaction(self):
        """Transaction context manager. Commits on success, rolls back on error."""
        with self._operation_lock:
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
        with self._operation_lock:
            self._ensure_connected()
            with self._conn.cursor() as cur:
                cur.execute(sql, params)
                if cur.description is None:
                    return []
                columns = [col.name for col in cur.description]
                return [dict(zip(columns, row)) for row in cur.fetchall()]

    def execute_many(self, sql: str, params_list: list[tuple[Any, ...]]) -> None:
        """Execute the same SQL with multiple parameter sets."""
        with self._operation_lock:
            self._ensure_connected()
            with self._conn.cursor() as cur:
                for params in params_list:
                    cur.execute(sql, params)

    def health(self) -> bool:
        """Check if the database connection is healthy."""
        try:
            with self._operation_lock:
                self._ensure_connected()
                with self._conn.cursor() as cur:
                    cur.execute("SELECT 1")
                    return True
        except Exception:
            return False

    def close(self) -> None:
        """Close the underlying connection if open."""
        with self._operation_lock:
            if self._conn is not None:
                try:
                    self._conn.close()
                except Exception:
                    pass
                self._conn = None

    @property
    def is_connected(self) -> bool:
        return self._conn is not None and not self._conn.closed


def _safe_database_target(database_url: str) -> str:
    parsed = urlsplit(database_url)
    host = parsed.hostname or "configured-host"
    port = f":{parsed.port}" if parsed.port else ""
    database = parsed.path.lstrip("/")
    return f"{host}{port}/{database}" if database else f"{host}{port}"


def _redact_database_error(error: Exception, database_url: str) -> str:
    message = str(error).replace(database_url, "<redacted-database-url>")
    password = urlsplit(database_url).password
    return message.replace(password, "<redacted>") if password else message
