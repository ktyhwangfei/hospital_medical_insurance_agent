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
