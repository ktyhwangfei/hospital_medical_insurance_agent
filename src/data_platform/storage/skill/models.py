from enum import StrEnum

from pydantic import BaseModel, Field


class SkillStorageHealthStatus(StrEnum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"


class SkillStorageHealth(BaseModel):
    status: SkillStorageHealthStatus
    details: dict[str, str] = Field(default_factory=dict)
