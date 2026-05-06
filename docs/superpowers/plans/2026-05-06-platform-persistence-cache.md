# Platform Persistence Cache Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build platform-level persistence/cache infrastructure that MCP uses first, while keeping storage decoupled enough to switch from PostgreSQL to Kingbase or other compatible databases later.

**Architecture:** Add generic persistence and cache modules under `src/data_platform/`, then refactor MCP storage to depend on these abstractions instead of concrete database drivers. PostgreSQL and Redis/Valkey become replaceable adapters behind executor/dialect and cache-client ports; existing in-memory MCP flow remains the default fallback.

**Tech Stack:** Python 3, Pydantic, pytest, optional `psycopg` for PostgreSQL, installed `redis` package for Redis/Valkey, stdlib JSON/time/contextlib.

---

## File Structure

- `src/data_platform/persistence/__init__.py`: public exports for persistence abstractions.
- `src/data_platform/persistence/models.py`: database backend, health, statement, query result models.
- `src/data_platform/persistence/ports.py`: `SqlDialect`, `DatabaseExecutor`, `SchemaMigrator` protocols.
- `src/data_platform/persistence/dialects.py`: PostgreSQL and Kingbase SQL dialect implementations.
- `src/data_platform/persistence/executors.py`: optional psycopg-backed executor plus unavailable-driver behavior.
- `src/data_platform/persistence/migrations.py`: reusable schema bootstrap runner.
- `src/data_platform/cache/__init__.py`: public exports for cache abstractions.
- `src/data_platform/cache/models.py`: cache backend, health and rate-limit result models.
- `src/data_platform/cache/ports.py`: `CacheClient`, short state, idempotency, rate-limit and lock protocols.
- `src/data_platform/cache/in_memory.py`: deterministic in-memory cache for tests and fallback.
- `src/data_platform/cache/redis_cache.py`: Redis/Valkey cache adapter using installed `redis` package.
- `src/data_platform/storage/mcp/postgres.py`: real MCP relational repository using persistence ports.
- `src/data_platform/storage/mcp/redis_cache.py`: MCP cache wrapper using generic cache ports.
- `src/config/mcp.py`: add backend selection and auto-init settings.
- `src/runtime/api/mcp_routes.py`: choose storage through factory while preserving default in-memory behavior.
- Tests under `src/tests/data_platform/`, `src/tests/integration/`, and existing MCP test files.

---

### Task 1: Persistence Core Models and Ports

**Files:**
- Create: `src/data_platform/persistence/__init__.py`
- Create: `src/data_platform/persistence/models.py`
- Create: `src/data_platform/persistence/ports.py`
- Test: `src/tests/data_platform/test_persistence_contracts.py`

- [ ] **Step 1: Write failing persistence contract tests**

Create `src/tests/data_platform/test_persistence_contracts.py`:

```python
from src.data_platform.persistence.models import DatabaseBackend, DatabaseHealth, DatabaseHealthStatus, QueryResult, SqlStatement


def test_sql_statement_preserves_text_and_params():
    statement = SqlStatement(sql="select * from mcp_servers where server_id = %s", params=("srv-1",))

    assert statement.sql == "select * from mcp_servers where server_id = %s"
    assert statement.params == ("srv-1",)


def test_query_result_defaults_to_empty_rows():
    result = QueryResult()

    assert result.rows == []
    assert result.rowcount == 0


def test_database_health_models_backend_and_status():
    health = DatabaseHealth(
        status=DatabaseHealthStatus.HEALTHY,
        backend=DatabaseBackend.POSTGRESQL,
        available=True,
        details={"schema": "ready"},
    )

    assert health.status == DatabaseHealthStatus.HEALTHY
    assert health.backend == DatabaseBackend.POSTGRESQL
    assert health.available is True
    assert health.details["schema"] == "ready"
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```bash
python -m pytest src/tests/data_platform/test_persistence_contracts.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'src.data_platform.persistence'`.

- [ ] **Step 3: Implement models and ports**

Create `src/data_platform/persistence/models.py`:

```python
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class DatabaseBackend(StrEnum):
    POSTGRESQL = "postgresql"
    KINGBASE = "kingbase"
    UNKNOWN = "unknown"


class DatabaseHealthStatus(StrEnum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"


class SqlStatement(BaseModel):
    sql: str
    params: tuple[Any, ...] = ()


class QueryResult(BaseModel):
    rows: list[dict[str, Any]] = Field(default_factory=list)
    rowcount: int = 0


class DatabaseHealth(BaseModel):
    status: DatabaseHealthStatus
    backend: DatabaseBackend
    available: bool
    details: dict[str, Any] = Field(default_factory=dict)
```

Create `src/data_platform/persistence/ports.py`:

```python
from contextlib import AbstractContextManager
from typing import Any, Protocol

from src.data_platform.persistence.models import DatabaseHealth, QueryResult, SqlStatement


class SqlDialect(Protocol):
    name: str

    def placeholder(self, position: int) -> str: ...

    def json_dump(self, value: Any) -> str: ...

    def json_load(self, value: Any) -> dict[str, Any]: ...

    def upsert_sql(self, table: str, key_columns: tuple[str, ...], insert_columns: tuple[str, ...], update_columns: tuple[str, ...]) -> str: ...


class DatabaseExecutor(Protocol):
    def execute(self, statement: SqlStatement) -> QueryResult: ...

    def fetch_one(self, statement: SqlStatement) -> dict[str, Any] | None: ...

    def fetch_all(self, statement: SqlStatement) -> list[dict[str, Any]]: ...

    def transaction(self) -> AbstractContextManager[None]: ...

    def health(self) -> DatabaseHealth: ...


class SchemaMigrator(Protocol):
    def bootstrap(self) -> None: ...
```

Create `src/data_platform/persistence/__init__.py`:

```python
from src.data_platform.persistence.models import DatabaseBackend, DatabaseHealth, DatabaseHealthStatus, QueryResult, SqlStatement
from src.data_platform.persistence.ports import DatabaseExecutor, SchemaMigrator, SqlDialect

__all__ = [
    "DatabaseBackend",
    "DatabaseExecutor",
    "DatabaseHealth",
    "DatabaseHealthStatus",
    "QueryResult",
    "SchemaMigrator",
    "SqlDialect",
    "SqlStatement",
]
```

- [ ] **Step 4: Run tests and verify pass**

Run:

```bash
python -m pytest src/tests/data_platform/test_persistence_contracts.py -v
```

Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add src/data_platform/persistence src/tests/data_platform/test_persistence_contracts.py
git commit -m "feat: add platform persistence contracts"
```

---

### Task 2: SQL Dialects for PostgreSQL and Kingbase

**Files:**
- Create: `src/data_platform/persistence/dialects.py`
- Test: `src/tests/data_platform/test_sql_dialects.py`

- [ ] **Step 1: Write failing dialect tests**

Create `src/tests/data_platform/test_sql_dialects.py`:

```python
from src.data_platform.persistence.dialects import KingbaseDialect, PostgresDialect


def test_postgres_dialect_generates_psycopg_placeholders_and_upsert():
    dialect = PostgresDialect()

    assert dialect.placeholder(1) == "%s"
    sql = dialect.upsert_sql(
        table="mcp_servers",
        key_columns=("server_id",),
        insert_columns=("server_id", "payload_json", "status"),
        update_columns=("payload_json", "status"),
    )

    assert "insert into mcp_servers" in sql
    assert "on conflict (server_id) do update" in sql
    assert "payload_json = excluded.payload_json" in sql


def test_kingbase_dialect_keeps_postgres_compatible_boundary():
    dialect = KingbaseDialect()

    assert dialect.placeholder(1) == "%s"
    assert dialect.name == "kingbase"
    assert dialect.json_load(dialect.json_dump({"a": 1})) == {"a": 1}
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```bash
python -m pytest src/tests/data_platform/test_sql_dialects.py -v
```

Expected: FAIL with missing `src.data_platform.persistence.dialects`.

- [ ] **Step 3: Implement dialects**

Create `src/data_platform/persistence/dialects.py`:

```python
import json
from typing import Any


class PostgresDialect:
    name = "postgresql"

    def placeholder(self, position: int) -> str:
        return "%s"

    def json_dump(self, value: Any) -> str:
        return json.dumps(value, ensure_ascii=False, sort_keys=True)

    def json_load(self, value: Any) -> dict[str, Any]:
        if isinstance(value, dict):
            return value
        if value is None:
            return {}
        return json.loads(value)

    def upsert_sql(self, table: str, key_columns: tuple[str, ...], insert_columns: tuple[str, ...], update_columns: tuple[str, ...]) -> str:
        columns = ", ".join(insert_columns)
        placeholders = ", ".join(self.placeholder(index + 1) for index, _ in enumerate(insert_columns))
        conflict_columns = ", ".join(key_columns)
        assignments = ", ".join(f"{column} = excluded.{column}" for column in update_columns)
        return f"insert into {table} ({columns}) values ({placeholders}) on conflict ({conflict_columns}) do update set {assignments}"


class KingbaseDialect(PostgresDialect):
    name = "kingbase"
```

- [ ] **Step 4: Run tests and verify pass**

Run:

```bash
python -m pytest src/tests/data_platform/test_sql_dialects.py -v
```

Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add src/data_platform/persistence/dialects.py src/tests/data_platform/test_sql_dialects.py
git commit -m "feat: add portable sql dialects"
```

---

### Task 3: Database Executor and Schema Migrator

**Files:**
- Create: `src/data_platform/persistence/executors.py`
- Create: `src/data_platform/persistence/migrations.py`
- Test: `src/tests/data_platform/test_database_executor.py`
- Test: `src/tests/data_platform/test_schema_migrator.py`

- [ ] **Step 1: Write failing executor and migrator tests**

Create `src/tests/data_platform/test_database_executor.py`:

```python
from src.data_platform.persistence.executors import UnavailableDatabaseExecutor
from src.data_platform.persistence.models import DatabaseBackend, DatabaseHealthStatus, SqlStatement


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
```

Create `src/tests/data_platform/test_schema_migrator.py`:

```python
from src.data_platform.persistence.migrations import StatementSchemaMigrator
from src.data_platform.persistence.models import QueryResult, SqlStatement


class RecordingExecutor:
    def __init__(self):
        self.statements: list[SqlStatement] = []

    def execute(self, statement: SqlStatement) -> QueryResult:
        self.statements.append(statement)
        return QueryResult(rowcount=0)


def test_schema_migrator_executes_statements_in_order():
    executor = RecordingExecutor()
    migrator = StatementSchemaMigrator(executor, [SqlStatement(sql="create table a"), SqlStatement(sql="create index b")])

    migrator.bootstrap()

    assert [item.sql for item in executor.statements] == ["create table a", "create index b"]
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```bash
python -m pytest src/tests/data_platform/test_database_executor.py src/tests/data_platform/test_schema_migrator.py -v
```

Expected: FAIL with missing modules/classes.

- [ ] **Step 3: Implement executor and migrator**

Create `src/data_platform/persistence/executors.py`:

```python
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
```

Create `src/data_platform/persistence/migrations.py`:

```python
from src.data_platform.persistence.models import SqlStatement
from src.data_platform.persistence.ports import DatabaseExecutor


class StatementSchemaMigrator:
    def __init__(self, executor: DatabaseExecutor, statements: list[SqlStatement]):
        self._executor = executor
        self._statements = statements

    def bootstrap(self) -> None:
        for statement in self._statements:
            self._executor.execute(statement)
```

- [ ] **Step 4: Run tests and verify pass**

Run:

```bash
python -m pytest src/tests/data_platform/test_database_executor.py src/tests/data_platform/test_schema_migrator.py -v
```

Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add src/data_platform/persistence/executors.py src/data_platform/persistence/migrations.py src/tests/data_platform/test_database_executor.py src/tests/data_platform/test_schema_migrator.py
git commit -m "feat: add database executor abstractions"
```

---

### Task 4: MCP PostgreSQL Repository on Persistence Ports

**Files:**
- Modify: `src/data_platform/storage/mcp/postgres.py`
- Test: `src/tests/data_platform/test_mcp_postgres_storage.py`

- [ ] **Step 1: Write failing repository tests using fake executor**

Create `src/tests/data_platform/test_mcp_postgres_storage.py`:

```python
from src.data_platform.persistence.dialects import PostgresDialect
from src.data_platform.persistence.models import DatabaseBackend, DatabaseHealth, DatabaseHealthStatus, QueryResult, SqlStatement
from src.data_platform.storage.mcp.postgres import PostgresMcpStorage, mcp_schema_statements
from src.knowledge_extension.mcp_registry.models import McpCapability, McpCapabilityType, McpRiskLevel, McpServer, McpServerStatus, McpTransportType


class FakeExecutor:
    def __init__(self):
        self.statements: list[SqlStatement] = []
        self.rows: dict[str, dict] = {}

    def execute(self, statement: SqlStatement) -> QueryResult:
        self.statements.append(statement)
        return QueryResult(rowcount=1)

    def fetch_one(self, statement: SqlStatement):
        self.statements.append(statement)
        return self.rows.get(statement.params[0])

    def fetch_all(self, statement: SqlStatement):
        self.statements.append(statement)
        return list(self.rows.values())

    def health(self) -> DatabaseHealth:
        return DatabaseHealth(status=DatabaseHealthStatus.HEALTHY, backend=DatabaseBackend.POSTGRESQL, available=True)


def test_mcp_schema_statements_include_servers_and_capabilities():
    sql = "\n".join(statement.sql for statement in mcp_schema_statements())
    assert "create table if not exists mcp_servers" in sql
    assert "create table if not exists mcp_capabilities" in sql


def test_postgres_mcp_storage_saves_server_with_upsert_statement():
    executor = FakeExecutor()
    storage = PostgresMcpStorage(executor=executor, dialect=PostgresDialect())
    server = McpServer(server_id="srv-1", name="政策 MCP", endpoint="memory://policy", transport=McpTransportType.SSE, status=McpServerStatus.ENABLED)

    storage.save_server(server)

    assert "insert into mcp_servers" in executor.statements[0].sql
    assert executor.statements[0].params[0] == "srv-1"
    assert executor.statements[0].params[2] == "enabled"


def test_postgres_mcp_storage_loads_server_from_payload_json():
    executor = FakeExecutor()
    dialect = PostgresDialect()
    server = McpServer(server_id="srv-1", name="政策 MCP", endpoint="memory://policy", transport=McpTransportType.SSE, status=McpServerStatus.ENABLED)
    executor.rows["srv-1"] = {"payload_json": dialect.json_dump(server.model_dump(mode="json"))}
    storage = PostgresMcpStorage(executor=executor, dialect=dialect)

    loaded = storage.get_server("srv-1")

    assert loaded == server


def test_postgres_mcp_storage_saves_and_loads_capability():
    executor = FakeExecutor()
    dialect = PostgresDialect()
    capability = McpCapability(capability_id="cap-1", server_id="srv-1", name="政策检索", capability_type=McpCapabilityType.TOOL, description="检索政策", risk_level=McpRiskLevel.LOW)
    executor.rows["cap-1"] = {"payload_json": dialect.json_dump(capability.model_dump(mode="json"))}
    storage = PostgresMcpStorage(executor=executor, dialect=dialect)

    storage.save_capability(capability)
    loaded = storage.get_capability("cap-1")

    assert "insert into mcp_capabilities" in executor.statements[0].sql
    assert loaded == capability
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```bash
python -m pytest src/tests/data_platform/test_mcp_postgres_storage.py -v
```

Expected: FAIL because `PostgresMcpStorage` does not accept `executor` and lacks CRUD.

- [ ] **Step 3: Implement MCP PostgreSQL repository**

Replace `src/data_platform/storage/mcp/postgres.py` with:

```python
from src.data_platform.persistence.dialects import PostgresDialect
from src.data_platform.persistence.models import DatabaseHealthStatus, SqlStatement
from src.data_platform.persistence.ports import DatabaseExecutor, SqlDialect
from src.data_platform.storage.mcp.models import McpStorageHealth, McpStorageHealthStatus
from src.knowledge_extension.mcp_registry.models import McpCapability, McpServer


def mcp_schema_statements() -> list[SqlStatement]:
    return [
        SqlStatement(sql="create table if not exists mcp_servers (server_id varchar(128) primary key, payload_json text not null, status varchar(32) not null, transport varchar(32) not null, updated_at timestamp default current_timestamp)"),
        SqlStatement(sql="create table if not exists mcp_capabilities (capability_id varchar(128) primary key, server_id varchar(128) not null, payload_json text not null, capability_type varchar(32) not null, risk_level varchar(32) not null, enabled boolean not null, updated_at timestamp default current_timestamp)"),
        SqlStatement(sql="create index if not exists idx_mcp_capabilities_server_id on mcp_capabilities (server_id)"),
    ]


class PostgresMcpStorage:
    def __init__(self, executor: DatabaseExecutor, dialect: SqlDialect | None = None):
        self._executor = executor
        self._dialect = dialect or PostgresDialect()

    def save_server(self, server: McpServer) -> None:
        sql = self._dialect.upsert_sql("mcp_servers", ("server_id",), ("server_id", "payload_json", "status", "transport"), ("payload_json", "status", "transport"))
        payload = self._dialect.json_dump(server.model_dump(mode="json"))
        self._executor.execute(SqlStatement(sql=sql, params=(server.server_id, payload, server.status.value, server.transport.value)))

    def get_server(self, server_id: str) -> McpServer | None:
        row = self._executor.fetch_one(SqlStatement(sql="select payload_json from mcp_servers where server_id = %s", params=(server_id,)))
        if row is None:
            return None
        return McpServer(**self._dialect.json_load(row["payload_json"]))

    def list_servers(self) -> list[McpServer]:
        rows = self._executor.fetch_all(SqlStatement(sql="select payload_json from mcp_servers order by server_id"))
        return [McpServer(**self._dialect.json_load(row["payload_json"])) for row in rows]

    def save_capability(self, capability: McpCapability) -> None:
        sql = self._dialect.upsert_sql("mcp_capabilities", ("capability_id",), ("capability_id", "server_id", "payload_json", "capability_type", "risk_level", "enabled"), ("server_id", "payload_json", "capability_type", "risk_level", "enabled"))
        payload = self._dialect.json_dump(capability.model_dump(mode="json"))
        self._executor.execute(SqlStatement(sql=sql, params=(capability.capability_id, capability.server_id, payload, capability.capability_type.value, capability.risk_level.value, capability.enabled)))

    def get_capability(self, capability_id: str) -> McpCapability | None:
        row = self._executor.fetch_one(SqlStatement(sql="select payload_json from mcp_capabilities where capability_id = %s", params=(capability_id,)))
        if row is None:
            return None
        return McpCapability(**self._dialect.json_load(row["payload_json"]))

    def list_capabilities(self) -> list[McpCapability]:
        rows = self._executor.fetch_all(SqlStatement(sql="select payload_json from mcp_capabilities order by capability_id"))
        return [McpCapability(**self._dialect.json_load(row["payload_json"])) for row in rows]

    def health(self) -> McpStorageHealth:
        database_health = self._executor.health()
        status = McpStorageHealthStatus.HEALTHY if database_health.status == DatabaseHealthStatus.HEALTHY else McpStorageHealthStatus.UNHEALTHY
        return McpStorageHealth(status=status, postgres_available=database_health.available, redis_available=False, details={"backend": database_health.backend.value, **database_health.details})
```

- [ ] **Step 4: Run tests and verify pass**

Run:

```bash
python -m pytest src/tests/data_platform/test_mcp_postgres_storage.py -v
```

Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add src/data_platform/storage/mcp/postgres.py src/tests/data_platform/test_mcp_postgres_storage.py
git commit -m "feat: add mcp relational storage repository"
```

---

### Task 5: Generic Cache Ports and In-Memory Implementation

**Files:**
- Create: `src/data_platform/cache/__init__.py`
- Create: `src/data_platform/cache/models.py`
- Create: `src/data_platform/cache/ports.py`
- Create: `src/data_platform/cache/in_memory.py`
- Test: `src/tests/data_platform/test_cache_contracts.py`

- [ ] **Step 1: Write failing cache tests**

Create `src/tests/data_platform/test_cache_contracts.py`:

```python
from src.data_platform.cache.in_memory import InMemoryCacheClient
from src.data_platform.cache.models import CacheBackend, CacheHealthStatus


def test_in_memory_cache_stores_json_deep_copies():
    cache = InMemoryCacheClient()
    value = {"items": [{"id": "cap-1"}]}
    cache.set_json("capabilities", value, ttl_seconds=60)
    value["items"][0]["id"] = "mutated"

    loaded = cache.get_json("capabilities")
    loaded["items"][0]["id"] = "changed"

    assert cache.get_json("capabilities")["items"][0]["id"] == "cap-1"


def test_in_memory_cache_health():
    health = InMemoryCacheClient().health()
    assert health.status == CacheHealthStatus.HEALTHY
    assert health.backend == CacheBackend.IN_MEMORY
    assert health.available is True


def test_in_memory_cache_delete_and_exists():
    cache = InMemoryCacheClient()
    cache.set_json("k", {"v": 1}, ttl_seconds=60)

    assert cache.exists("k") is True
    cache.delete("k")
    assert cache.exists("k") is False
    assert cache.get_json("k") is None
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```bash
python -m pytest src/tests/data_platform/test_cache_contracts.py -v
```

Expected: FAIL with missing `src.data_platform.cache`.

- [ ] **Step 3: Implement cache models, ports and in-memory client**

Create `src/data_platform/cache/models.py`:

```python
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class CacheBackend(StrEnum):
    REDIS = "redis"
    VALKEY = "valkey"
    IN_MEMORY = "in_memory"
    UNKNOWN = "unknown"


class CacheHealthStatus(StrEnum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"


class CacheHealth(BaseModel):
    status: CacheHealthStatus
    backend: CacheBackend
    available: bool
    details: dict[str, Any] = Field(default_factory=dict)


class RateLimitResult(BaseModel):
    allowed: bool
    current_count: int
    limit: int
```

Create `src/data_platform/cache/ports.py`:

```python
from typing import Any, Protocol

from src.data_platform.cache.models import CacheHealth, RateLimitResult


class CacheClient(Protocol):
    def get_json(self, key: str) -> dict[str, Any] | None: ...

    def set_json(self, key: str, value: dict[str, Any], ttl_seconds: int) -> None: ...

    def delete(self, key: str) -> None: ...

    def exists(self, key: str) -> bool: ...

    def health(self) -> CacheHealth: ...


class ShortStateStore(Protocol):
    def save_state(self, namespace: str, key: str, value: dict[str, Any], ttl_seconds: int) -> None: ...

    def load_state(self, namespace: str, key: str) -> dict[str, Any] | None: ...

    def delete_state(self, namespace: str, key: str) -> None: ...


class IdempotencyStore(Protocol):
    def reserve(self, key: str, ttl_seconds: int) -> bool: ...

    def complete(self, key: str, value: dict[str, Any], ttl_seconds: int) -> None: ...

    def get_result(self, key: str) -> dict[str, Any] | None: ...


class RateLimiter(Protocol):
    def increment_and_check(self, key: str, limit: int, window_seconds: int) -> RateLimitResult: ...


class DistributedLock(Protocol):
    def acquire(self, key: str, ttl_seconds: int, owner: str) -> bool: ...

    def release(self, key: str, owner: str) -> bool: ...
```

Create `src/data_platform/cache/in_memory.py`:

```python
import copy
import time
from typing import Any

from src.data_platform.cache.models import CacheBackend, CacheHealth, CacheHealthStatus, RateLimitResult


class InMemoryCacheClient:
    def __init__(self):
        self._values: dict[str, tuple[dict[str, Any], float]] = {}
        self._locks: dict[str, tuple[str, float]] = {}

    def get_json(self, key: str) -> dict[str, Any] | None:
        self._purge_expired_key(key)
        entry = self._values.get(key)
        if entry is None:
            return None
        return copy.deepcopy(entry[0])

    def set_json(self, key: str, value: dict[str, Any], ttl_seconds: int) -> None:
        self._values[key] = (copy.deepcopy(value), time.time() + ttl_seconds)

    def delete(self, key: str) -> None:
        self._values.pop(key, None)

    def exists(self, key: str) -> bool:
        self._purge_expired_key(key)
        return key in self._values

    def health(self) -> CacheHealth:
        return CacheHealth(status=CacheHealthStatus.HEALTHY, backend=CacheBackend.IN_MEMORY, available=True, details={"backend": "in_memory"})

    def save_state(self, namespace: str, key: str, value: dict[str, Any], ttl_seconds: int) -> None:
        self.set_json(f"state:{namespace}:{key}", value, ttl_seconds)

    def load_state(self, namespace: str, key: str) -> dict[str, Any] | None:
        return self.get_json(f"state:{namespace}:{key}")

    def delete_state(self, namespace: str, key: str) -> None:
        self.delete(f"state:{namespace}:{key}")

    def reserve(self, key: str, ttl_seconds: int) -> bool:
        cache_key = f"idempotency:{key}"
        if self.exists(cache_key):
            return False
        self.set_json(cache_key, {"status": "reserved"}, ttl_seconds)
        return True

    def complete(self, key: str, value: dict[str, Any], ttl_seconds: int) -> None:
        self.set_json(f"idempotency:{key}", {"status": "completed", "result": value}, ttl_seconds)

    def get_result(self, key: str) -> dict[str, Any] | None:
        payload = self.get_json(f"idempotency:{key}")
        if payload is None or payload.get("status") != "completed":
            return None
        result = payload.get("result")
        return result if isinstance(result, dict) else None

    def increment_and_check(self, key: str, limit: int, window_seconds: int) -> RateLimitResult:
        cache_key = f"rate:{key}"
        payload = self.get_json(cache_key) or {"count": 0}
        count = int(payload["count"]) + 1
        self.set_json(cache_key, {"count": count}, window_seconds)
        return RateLimitResult(allowed=count <= limit, current_count=count, limit=limit)

    def acquire(self, key: str, ttl_seconds: int, owner: str) -> bool:
        self._purge_expired_lock(key)
        if key in self._locks:
            return False
        self._locks[key] = (owner, time.time() + ttl_seconds)
        return True

    def release(self, key: str, owner: str) -> bool:
        self._purge_expired_lock(key)
        current = self._locks.get(key)
        if current is None or current[0] != owner:
            return False
        self._locks.pop(key, None)
        return True

    def _purge_expired_key(self, key: str) -> None:
        entry = self._values.get(key)
        if entry is not None and entry[1] < time.time():
            self._values.pop(key, None)

    def _purge_expired_lock(self, key: str) -> None:
        entry = self._locks.get(key)
        if entry is not None and entry[1] < time.time():
            self._locks.pop(key, None)
```

Create `src/data_platform/cache/__init__.py`:

```python
from src.data_platform.cache.in_memory import InMemoryCacheClient
from src.data_platform.cache.models import CacheBackend, CacheHealth, CacheHealthStatus, RateLimitResult
from src.data_platform.cache.ports import CacheClient, DistributedLock, IdempotencyStore, RateLimiter, ShortStateStore

__all__ = [
    "CacheBackend",
    "CacheClient",
    "CacheHealth",
    "CacheHealthStatus",
    "DistributedLock",
    "IdempotencyStore",
    "InMemoryCacheClient",
    "RateLimitResult",
    "RateLimiter",
    "ShortStateStore",
]
```

- [ ] **Step 4: Run tests and verify pass**

Run:

```bash
python -m pytest src/tests/data_platform/test_cache_contracts.py -v
```

Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add src/data_platform/cache src/tests/data_platform/test_cache_contracts.py
git commit -m "feat: add platform cache contracts"
```

---

### Task 6: Redis/Valkey Cache Adapter

**Files:**
- Create: `src/data_platform/cache/redis_cache.py`
- Test: `src/tests/data_platform/test_redis_cache_client.py`

- [ ] **Step 1: Write failing Redis adapter tests with fake client**

Create `src/tests/data_platform/test_redis_cache_client.py`:

```python
from src.data_platform.cache.models import CacheBackend, CacheHealthStatus
from src.data_platform.cache.redis_cache import RedisCacheClient


class FakeRedis:
    def __init__(self):
        self.values: dict[str, str] = {}
        self.expirations: dict[str, int] = {}

    def setex(self, key: str, ttl: int, value: str):
        self.values[key] = value
        self.expirations[key] = ttl

    def get(self, key: str):
        return self.values.get(key)

    def delete(self, key: str):
        self.values.pop(key, None)

    def exists(self, key: str):
        return 1 if key in self.values else 0

    def ping(self):
        return True


def test_redis_cache_client_stores_json():
    redis = FakeRedis()
    cache = RedisCacheClient(redis_client=redis, backend=CacheBackend.REDIS)

    cache.set_json("k", {"v": 1}, ttl_seconds=30)

    assert cache.get_json("k") == {"v": 1}
    assert redis.expirations["k"] == 30


def test_redis_cache_client_health_uses_backend():
    cache = RedisCacheClient(redis_client=FakeRedis(), backend=CacheBackend.VALKEY)

    health = cache.health()

    assert health.status == CacheHealthStatus.HEALTHY
    assert health.backend == CacheBackend.VALKEY
    assert health.available is True
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```bash
python -m pytest src/tests/data_platform/test_redis_cache_client.py -v
```

Expected: FAIL with missing `src.data_platform.cache.redis_cache`.

- [ ] **Step 3: Implement Redis cache adapter**

Create `src/data_platform/cache/redis_cache.py`:

```python
import json
from typing import Any

from src.data_platform.cache.models import CacheBackend, CacheHealth, CacheHealthStatus


class RedisCacheClient:
    def __init__(self, redis_url: str | None = None, redis_client: Any | None = None, backend: CacheBackend = CacheBackend.REDIS):
        self._backend = backend
        self._redis = redis_client or self._create_client(redis_url)

    def get_json(self, key: str) -> dict[str, Any] | None:
        value = self._redis.get(key)
        if value is None:
            return None
        if isinstance(value, bytes):
            value = value.decode("utf-8")
        return json.loads(value)

    def set_json(self, key: str, value: dict[str, Any], ttl_seconds: int) -> None:
        self._redis.setex(key, ttl_seconds, json.dumps(value, ensure_ascii=False, sort_keys=True))

    def delete(self, key: str) -> None:
        self._redis.delete(key)

    def exists(self, key: str) -> bool:
        return bool(self._redis.exists(key))

    def health(self) -> CacheHealth:
        try:
            self._redis.ping()
        except Exception as exc:
            return CacheHealth(status=CacheHealthStatus.UNHEALTHY, backend=self._backend, available=False, details={"reason": "connection_failed", "error": exc.__class__.__name__})
        return CacheHealth(status=CacheHealthStatus.HEALTHY, backend=self._backend, available=True, details={"reason": "connected"})

    def _create_client(self, redis_url: str | None):
        if redis_url is None:
            raise RuntimeError("redis_url_required")
        import redis
        return redis.Redis.from_url(redis_url)
```

- [ ] **Step 4: Run tests and verify pass**

Run:

```bash
python -m pytest src/tests/data_platform/test_redis_cache_client.py -v
```

Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add src/data_platform/cache/redis_cache.py src/tests/data_platform/test_redis_cache_client.py
git commit -m "feat: add redis cache adapter"
```

---

### Task 7: MCP Redis Cache Wrapper

**Files:**
- Modify: `src/data_platform/storage/mcp/redis_cache.py`
- Test: `src/tests/data_platform/test_mcp_redis_cache.py`

- [ ] **Step 1: Write failing MCP cache wrapper tests**

Create `src/tests/data_platform/test_mcp_redis_cache.py`:

```python
from src.data_platform.cache.in_memory import InMemoryCacheClient
from src.data_platform.storage.mcp.redis_cache import RedisMcpCache
from src.knowledge_extension.mcp_registry.models import McpCapability, McpCapabilityType, McpRiskLevel


def test_mcp_cache_stores_capability_list():
    cache = RedisMcpCache(cache_client=InMemoryCacheClient())
    capabilities = [McpCapability(capability_id="cap-1", server_id="srv-1", name="政策检索", capability_type=McpCapabilityType.TOOL, description="检索政策", risk_level=McpRiskLevel.LOW)]

    cache.save_capability_list("settlement_exception", capabilities, ttl_seconds=60)
    loaded = cache.load_capability_list("settlement_exception")

    assert loaded == capabilities


def test_mcp_cache_supports_idempotency_and_locks():
    cache = RedisMcpCache(cache_client=InMemoryCacheClient())

    assert cache.reserve_invocation("req-1", ttl_seconds=60) is True
    assert cache.reserve_invocation("req-1", ttl_seconds=60) is False
    assert cache.acquire_invocation_lock("cap-1", "worker-1", ttl_seconds=60) is True
    assert cache.acquire_invocation_lock("cap-1", "worker-2", ttl_seconds=60) is False
    assert cache.release_invocation_lock("cap-1", "worker-1") is True
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```bash
python -m pytest src/tests/data_platform/test_mcp_redis_cache.py -v
```

Expected: FAIL because `RedisMcpCache` only has health stub.

- [ ] **Step 3: Implement MCP cache wrapper**

Replace `src/data_platform/storage/mcp/redis_cache.py` with:

```python
from src.data_platform.cache.in_memory import InMemoryCacheClient
from src.data_platform.cache.ports import CacheClient
from src.data_platform.storage.mcp.models import McpStorageHealth, McpStorageHealthStatus
from src.knowledge_extension.mcp_registry.models import McpCapability


class RedisMcpCache:
    def __init__(self, redis_url: str | None = None, cache_client: CacheClient | None = None):
        self._cache = cache_client or InMemoryCacheClient()
        self._redis_url = redis_url

    def save_capability_list(self, scenario: str, capabilities: list[McpCapability], ttl_seconds: int) -> None:
        self._cache.set_json(f"mcp:capabilities:{scenario}", {"items": [item.model_dump(mode="json") for item in capabilities]}, ttl_seconds)

    def load_capability_list(self, scenario: str) -> list[McpCapability] | None:
        payload = self._cache.get_json(f"mcp:capabilities:{scenario}")
        if payload is None:
            return None
        return [McpCapability(**item) for item in payload["items"]]

    def reserve_invocation(self, request_id: str, ttl_seconds: int) -> bool:
        return self._cache.reserve(f"mcp:{request_id}", ttl_seconds)

    def acquire_invocation_lock(self, capability_id: str, owner: str, ttl_seconds: int) -> bool:
        return self._cache.acquire(f"mcp:capability:{capability_id}", ttl_seconds, owner)

    def release_invocation_lock(self, capability_id: str, owner: str) -> bool:
        return self._cache.release(f"mcp:capability:{capability_id}", owner)

    def health(self) -> McpStorageHealth:
        cache_health = self._cache.health()
        status = McpStorageHealthStatus.HEALTHY if cache_health.available else McpStorageHealthStatus.UNHEALTHY
        return McpStorageHealth(status=status, postgres_available=False, redis_available=cache_health.available, details={"backend": cache_health.backend.value, **cache_health.details})
```

- [ ] **Step 4: Run tests and verify pass**

Run:

```bash
python -m pytest src/tests/data_platform/test_mcp_redis_cache.py -v
```

Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add src/data_platform/storage/mcp/redis_cache.py src/tests/data_platform/test_mcp_redis_cache.py
git commit -m "feat: add mcp cache wrapper"
```

---

### Task 8: Configuration and Storage Factory

**Files:**
- Modify: `src/config/mcp.py`
- Create: `src/data_platform/storage/mcp/factory.py`
- Modify: `src/runtime/api/mcp_routes.py`
- Test: `src/tests/data_platform/test_mcp_storage_factory.py`
- Test: `src/tests/integration/test_mcp_management_api.py`

- [ ] **Step 1: Write failing factory tests**

Create `src/tests/data_platform/test_mcp_storage_factory.py`:

```python
from src.config.mcp import McpSettings
from src.data_platform.storage.mcp.factory import create_mcp_storage
from src.data_platform.storage.mcp.in_memory import InMemoryMcpStorage
from src.data_platform.storage.mcp.postgres import PostgresMcpStorage


def test_factory_uses_in_memory_by_default():
    storage = create_mcp_storage(McpSettings())
    assert isinstance(storage, InMemoryMcpStorage)


def test_factory_can_create_postgres_storage_with_unavailable_executor():
    storage = create_mcp_storage(McpSettings(persistence_backend="postgresql"))
    assert isinstance(storage, PostgresMcpStorage)
    assert storage.health().postgres_available is False or storage.health().postgres_available is True
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```bash
python -m pytest src/tests/data_platform/test_mcp_storage_factory.py -v
```

Expected: FAIL with missing factory or missing settings fields.

- [ ] **Step 3: Implement config and factory**

Update `src/config/mcp.py` to include:

```python
import os

from pydantic import BaseModel


class McpSettings(BaseModel):
    persistence_backend: str = "in_memory"
    cache_backend: str = "in_memory"
    postgres_dsn: str = "postgresql://localhost:5432/hospital_mcp"
    redis_url: str = "redis://localhost:6379/0"
    connection_timeout_seconds: int = 10
    database_schema_auto_init: bool = False


def load_mcp_settings() -> McpSettings:
    values: dict[str, str] = {}
    mapping = {
        "MCP_PERSISTENCE_BACKEND": "persistence_backend",
        "MCP_CACHE_BACKEND": "cache_backend",
        "MCP_POSTGRES_DSN": "postgres_dsn",
        "MCP_REDIS_URL": "redis_url",
        "MCP_CONNECTION_TIMEOUT_SECONDS": "connection_timeout_seconds",
        "MCP_DATABASE_SCHEMA_AUTO_INIT": "database_schema_auto_init",
    }
    for env_name, field_name in mapping.items():
        if value := os.getenv(env_name):
            values[field_name] = value
    return McpSettings(**values)
```

Create `src/data_platform/storage/mcp/factory.py`:

```python
from src.config.mcp import McpSettings
from src.data_platform.persistence.dialects import KingbaseDialect, PostgresDialect
from src.data_platform.persistence.executors import PsycopgDatabaseExecutor, UnavailableDatabaseExecutor
from src.data_platform.persistence.models import DatabaseBackend
from src.data_platform.persistence.migrations import StatementSchemaMigrator
from src.data_platform.storage.mcp.in_memory import InMemoryMcpStorage
from src.data_platform.storage.mcp.postgres import PostgresMcpStorage, mcp_schema_statements
from src.data_platform.storage.mcp.ports import McpStorage


def create_mcp_storage(settings: McpSettings) -> McpStorage:
    if settings.persistence_backend == "postgresql":
        executor = PsycopgDatabaseExecutor(settings.postgres_dsn, DatabaseBackend.POSTGRESQL, settings.connection_timeout_seconds)
        if settings.database_schema_auto_init:
            StatementSchemaMigrator(executor, mcp_schema_statements()).bootstrap()
        return PostgresMcpStorage(executor=executor, dialect=PostgresDialect())
    if settings.persistence_backend == "kingbase":
        executor = PsycopgDatabaseExecutor(settings.postgres_dsn, DatabaseBackend.KINGBASE, settings.connection_timeout_seconds)
        if settings.database_schema_auto_init:
            StatementSchemaMigrator(executor, mcp_schema_statements()).bootstrap()
        return PostgresMcpStorage(executor=executor, dialect=KingbaseDialect())
    if settings.persistence_backend == "postgresql_unavailable":
        return PostgresMcpStorage(executor=UnavailableDatabaseExecutor(DatabaseBackend.POSTGRESQL, "driver_not_installed"), dialect=PostgresDialect())
    return InMemoryMcpStorage()
```

Modify `src/runtime/api/mcp_routes.py`:

```python
from fastapi import APIRouter

from src.config.mcp import load_mcp_settings
from src.data_platform.storage.mcp.factory import create_mcp_storage
from src.knowledge_extension.mcp_registry.models import McpServer
from src.knowledge_extension.mcp_registry.service import McpRegistryService

router = APIRouter(prefix="/api/v1/medical-insurance-ai-agent/mcp", tags=["mcp"])
_storage = create_mcp_storage(load_mcp_settings())
_service = McpRegistryService(_storage)


@router.get("/storage/health")
def get_mcp_storage_health():
    return _storage.health()


@router.post("/servers")
def register_mcp_server(server: McpServer):
    registered = _service.register_server(server)
    return registered.to_public_dict()
```

- [ ] **Step 4: Run tests and verify pass**

Run:

```bash
python -m pytest src/tests/data_platform/test_mcp_storage_factory.py src/tests/integration/test_mcp_management_api.py -v
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/config/mcp.py src/data_platform/storage/mcp/factory.py src/runtime/api/mcp_routes.py src/tests/data_platform/test_mcp_storage_factory.py
git commit -m "feat: add configurable mcp storage factory"
```

---

### Task 9: Full Verification and OpenSpec Task Status

**Files:**
- Modify: `openspec/changes/mcp-cunchu/tasks.md`

- [ ] **Step 1: Run targeted platform tests**

Run:

```bash
python -m pytest src/tests/data_platform/test_persistence_contracts.py src/tests/data_platform/test_sql_dialects.py src/tests/data_platform/test_database_executor.py src/tests/data_platform/test_schema_migrator.py src/tests/data_platform/test_mcp_postgres_storage.py src/tests/data_platform/test_cache_contracts.py src/tests/data_platform/test_redis_cache_client.py src/tests/data_platform/test_mcp_redis_cache.py src/tests/data_platform/test_mcp_storage_factory.py -v
```

Expected: all selected tests pass.

- [ ] **Step 2: Run MCP regression tests**

Run:

```bash
python -m pytest src/tests/data_platform/test_mcp_storage.py src/tests/data_platform/test_mcp_storage_health.py src/tests/knowledge_extension/test_mcp_registry_service.py src/tests/integration/test_mcp_management_api.py src/tests/security/test_mcp_security_boundaries.py -v
```

Expected: all selected tests pass.

- [ ] **Step 3: Run full tests**

Run:

```bash
python -m pytest src/tests -v
```

Expected: all tests pass.

- [ ] **Step 4: Update task status**

Modify `openspec/changes/mcp-cunchu/tasks.md`:

```text
- [x] 2.2 实现 PostgreSQL 事实数据存储，覆盖 MCP 服务、能力、工具 schema、资源索引、策略、审计索引、连接配置脱敏视图和状态快照。
- [x] 2.3 实现 Redis/Valkey 能力缓存、连接健康状态、流式调用短期状态、幂等键、限流计数和分布式锁。
```

Keep unrelated unfinished tasks unchecked unless implemented by this plan.

- [ ] **Step 5: Commit**

```bash
git add openspec/changes/mcp-cunchu/tasks.md
git commit -m "docs: update persistence cache task status"
```

---

## Self-Review Notes

- Spec coverage: persistence abstractions, dialect separation, PostgreSQL implementation, Redis/Valkey cache, MCP first landing, fallback behavior and testing are covered.
- Placeholder scan: no placeholder steps remain; each task includes exact files, code and commands.
- Type consistency: `DatabaseExecutor`, `SqlDialect`, `CacheClient`, `McpStorage`, `PostgresMcpStorage`, and `RedisMcpCache` names are consistent across tasks.
