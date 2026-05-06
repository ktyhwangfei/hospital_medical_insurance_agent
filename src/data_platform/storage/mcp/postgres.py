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
        row = self._executor.fetch_one(SqlStatement(sql=f"select payload_json from mcp_servers where server_id = {self._dialect.placeholder(1)}", params=(server_id,)))
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
        row = self._executor.fetch_one(SqlStatement(sql=f"select payload_json from mcp_capabilities where capability_id = {self._dialect.placeholder(1)}", params=(capability_id,)))
        if row is None:
            return None
        return McpCapability(**self._dialect.json_load(row["payload_json"]))

    def list_capabilities(self) -> list[McpCapability]:
        rows = self._executor.fetch_all(SqlStatement(sql="select payload_json from mcp_capabilities order by capability_id"))
        return [McpCapability(**self._dialect.json_load(row["payload_json"])) for row in rows]

    def health(self) -> McpStorageHealth:
        try:
            database_health = self._executor.health()
        except Exception:
            return McpStorageHealth(status=McpStorageHealthStatus.UNHEALTHY, postgres_available=False, redis_available=False)
        status_map = {
            DatabaseHealthStatus.HEALTHY: McpStorageHealthStatus.HEALTHY,
            DatabaseHealthStatus.DEGRADED: McpStorageHealthStatus.DEGRADED,
        }
        status = status_map.get(database_health.status, McpStorageHealthStatus.UNHEALTHY)
        safe_details = {k: str(v) for k, v in database_health.details.items()}
        return McpStorageHealth(status=status, postgres_available=database_health.available, redis_available=False, details={"backend": database_health.backend.value, **safe_details})
