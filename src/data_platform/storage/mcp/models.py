from enum import StrEnum

from pydantic import BaseModel, Field


class McpStorageHealthStatus(StrEnum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"


class McpStorageHealth(BaseModel):
    status: McpStorageHealthStatus
    postgres_available: bool
    redis_available: bool
    details: dict[str, str] = Field(default_factory=dict)
