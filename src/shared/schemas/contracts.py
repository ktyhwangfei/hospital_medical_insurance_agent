from typing import Any

from pydantic import BaseModel, Field


class Citation(BaseModel):
    source_type: str
    source_id: str
    summary: str


class AuditEvent(BaseModel):
    event_type: str
    workflow_id: str | None = None
    step_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class RuntimeTask(BaseModel):
    task_id: str
    task_type: str
    status: str
    description: str
    responsible_role: str | None = None
    workflow_id: str | None = None
    updated_at: str | None = None


class StreamErrorEvent(BaseModel):
    error_code: str
    message: str
    audit_event: AuditEvent = Field(default_factory=lambda: AuditEvent(event_type="stream_error"))


class ErrorDetail(BaseModel):
    error_code: str
    message: str
    audit_event: dict[str, Any] = Field(default_factory=dict)
