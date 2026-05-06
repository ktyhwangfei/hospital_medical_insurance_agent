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
