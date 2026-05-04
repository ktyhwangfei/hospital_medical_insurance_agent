from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class AdapterCallStatus(str, Enum):
    SUCCESS = "success"
    FAILED = "failed"


class DataQualityStatus(str, Enum):
    COMPLETE = "complete"
    DEGRADED = "degraded"
    MISSING = "missing"


class AdapterCallContext(BaseModel):
    workflow_id: str | None = None
    step_id: str | None = None
    user_id: str | None = None
    role: str | None = None
    input_summary: dict[str, Any] = Field(default_factory=dict)


class AdapterCallResult(BaseModel):
    status: AdapterCallStatus
    source_system: str
    source_record_id: str | None = None
    capability: str
    data: dict[str, Any] = Field(default_factory=dict)
    data_quality: DataQualityStatus = DataQualityStatus.COMPLETE
    collected_at: str | None = None
    workflow_id: str | None = None
    step_id: str | None = None
    input_summary: dict[str, Any] = Field(default_factory=dict)
    output_summary: dict[str, Any] = Field(default_factory=dict)
    error_type: str | None = None
    message: str | None = None


class AdapterError(Exception):
    def __init__(self, message: str, error_type: str, source_system: str):
        super().__init__(message)
        self.error_type = error_type
        self.source_system = source_system
