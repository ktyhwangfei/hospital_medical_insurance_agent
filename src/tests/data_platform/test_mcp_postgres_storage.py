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
