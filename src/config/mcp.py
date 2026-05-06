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
