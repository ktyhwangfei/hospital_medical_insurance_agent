from typing import Any

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    user_id: str
    role: str
    message: str
    patient_id: str | None = None
    encounter_id: str | None = None


class AgentResponse(BaseModel):
    scenario: str | None = None
    status: str
    result: dict[str, Any] = Field(default_factory=dict)
    citations: list[dict[str, Any]] = Field(default_factory=list)
    tasks: list[dict[str, Any]] = Field(default_factory=list)
    missing_fields: list[str] = Field(default_factory=list)
    uncertainties: list[str] = Field(default_factory=list)
    blocked_actions: list[str] = Field(default_factory=list)
    audit: dict[str, Any] = Field(default_factory=dict)


class TaskConfirmRequest(BaseModel):
    task_id: str
    action: str
    user_id: str
    reason: str | None = None


class PatientContextResponse(BaseModel):
    patient: dict[str, Any] = Field(default_factory=dict)
    visible_fields: list[str] = Field(default_factory=list)
    encounter_id: str | None = None
    settlement_status: str | None = None
    audit_risks: list[Any] | None = None


class WorkflowStatusResponse(BaseModel):
    workflow_id: str
    status: str


class TaskStatusResponse(BaseModel):
    task_id: str
    status: str


class TaskConfirmResponse(BaseModel):
    task_id: str
    status: str
    confirmed_by: str
    confirmed_at: str
    reason: str | None = None
    result: dict[str, Any] = Field(default_factory=dict)


class ModelTestRequest(BaseModel):
    message: str
    scene: str = "default"


class ModelTestResponse(BaseModel):
    content: str
    model_name: str
    latency_ms: int
    prompt_tokens: int
    completion_tokens: int
