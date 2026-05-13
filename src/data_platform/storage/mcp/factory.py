import logging

from src.config.mcp import McpSettings
from src.data_platform.cache import create_cache_client_optional
from src.data_platform.cache.config import CACHE_TTL_MCP, CACHE_ENABLED_MCP
from src.data_platform.persistence.dialects import KingbaseDialect, PostgresDialect
from src.data_platform.persistence.executors import PsycopgDatabaseExecutor, UnavailableDatabaseExecutor
from src.data_platform.persistence.models import DatabaseBackend
from src.data_platform.persistence.migrations import StatementSchemaMigrator
from src.data_platform.storage.mcp.cached import CachedMcpStorage
from src.data_platform.storage.mcp.in_memory import InMemoryMcpStorage
from src.data_platform.storage.mcp.postgres import PostgresMcpStorage, mcp_schema_statements
from src.data_platform.storage.mcp.ports import McpStorage

logger = logging.getLogger(__name__)


def create_mcp_storage(settings: McpSettings) -> McpStorage:
    """创建 MCP 存储实例。

    持久化后端由 ``settings.persistence_backend`` 决定：
    - ``"postgresql"`` / ``"kingbase"`` / ``"postgresql_unavailable"`` → PostgreSQL
    - 其他值 → InMemory

    当持久化后端为 PostgreSQL 时，若满足以下任一条件，则使用
    ``CachedMcpStorage`` 包装以实现读穿透缓存：
    - ``settings.cache_backend == "redis"``
    - ``CACHE_ENABLED_MCP == "1"``（环境变量，默认启用）
    """
    if settings.persistence_backend == "postgresql":
        executor = PsycopgDatabaseExecutor(
            settings.postgres_dsn, DatabaseBackend.POSTGRESQL, settings.connection_timeout_seconds
        )
        if settings.database_schema_auto_init:
            StatementSchemaMigrator(executor, mcp_schema_statements()).bootstrap()
        storage: McpStorage = PostgresMcpStorage(executor=executor, dialect=PostgresDialect())
    elif settings.persistence_backend == "kingbase":
        executor = PsycopgDatabaseExecutor(
            settings.postgres_dsn, DatabaseBackend.KINGBASE, settings.connection_timeout_seconds
        )
        if settings.database_schema_auto_init:
            StatementSchemaMigrator(executor, mcp_schema_statements()).bootstrap()
        storage = PostgresMcpStorage(executor=executor, dialect=KingbaseDialect())
    elif settings.persistence_backend == "postgresql_unavailable":
        storage = PostgresMcpStorage(
            executor=UnavailableDatabaseExecutor(DatabaseBackend.POSTGRESQL, "driver_not_installed"),
            dialect=PostgresDialect(),
        )
    else:
        return InMemoryMcpStorage()

    # 条件包裹读穿透缓存（仅针对 PostgreSQL 后端）
    cache = create_cache_client_optional()
    cache_enabled = (settings.cache_backend == "redis") or (CACHE_ENABLED_MCP == "1")
    if cache is not None and cache_enabled:
        logger.info("Wrapping PostgresMcpStorage with CachedMcpStorage")
        return CachedMcpStorage(underlying=storage, cache=cache, ttl=CACHE_TTL_MCP)

    return storage
