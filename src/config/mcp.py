import os

from pydantic import BaseModel, Field


class McpSettings(BaseModel):
    postgres_dsn: str = Field(default_factory=lambda: os.getenv("MCP_POSTGRES_DSN", "postgresql://localhost:5432/hospital_mcp"))
    redis_url: str = Field(default_factory=lambda: os.getenv("MCP_REDIS_URL", "redis://localhost:6379/0"))
    connection_timeout_seconds: int = Field(default_factory=lambda: int(os.getenv("MCP_CONNECTION_TIMEOUT_SECONDS", "10")))
