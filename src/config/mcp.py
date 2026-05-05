import os

from pydantic import BaseModel


class McpSettings(BaseModel):
    postgres_dsn: str = "postgresql://localhost:5432/hospital_mcp"
    redis_url: str = "redis://localhost:6379/0"
    connection_timeout_seconds: int = 10


def load_mcp_settings() -> McpSettings:
    values: dict[str, str] = {}
    if postgres_dsn := os.getenv("MCP_POSTGRES_DSN"):
        values["postgres_dsn"] = postgres_dsn
    if redis_url := os.getenv("MCP_REDIS_URL"):
        values["redis_url"] = redis_url
    if connection_timeout_seconds := os.getenv("MCP_CONNECTION_TIMEOUT_SECONDS"):
        values["connection_timeout_seconds"] = connection_timeout_seconds
    return McpSettings(**values)
