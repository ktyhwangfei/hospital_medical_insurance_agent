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
