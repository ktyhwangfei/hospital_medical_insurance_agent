from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    user_id: str
    role: str
    message: str
    patient_id: str | None = None
    encounter_id: str | None = None
    mentioned_skill_ids: list[str] = Field(default_factory=list)


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


class WorkflowListItem(BaseModel):
    workflow_id: str
    scenario: str
    status: str
    patient_id: str | None = None
    patient_name: str | None = None
    error_code: str | None = None
    error_msg: str | None = None
    detected_at: str | None = None
    created_at: str | None = None
    current_step: str | None = None
    steps: list[dict[str, Any]] = Field(default_factory=list)


class TaskStatusResponse(BaseModel):
    task_id: str
    status: str
    confirmed_at: str | None = None


class TaskConfirmResponse(BaseModel):
    task_id: str
    status: str
    confirmed_by: str
    confirmed_at: datetime
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


class SkillStepRequest(BaseModel):
    step_id: str
    tool_id: str
    depends_on: list[str] = Field(default_factory=list)


class SkillCreateRequest(BaseModel):
    skill_id: str
    name: str
    description: str
    owner: str
    steps: list[SkillStepRequest] = Field(default_factory=list)
    intent_keywords: list[str] = Field(default_factory=list)
    required_roles: set[str] = Field(default_factory=set)
    risk_level: str = "low"
    license: str | None = None
    compatibility: str | None = None
    allowed_tools: list[str] = Field(default_factory=list)
    skill_metadata: dict[str, Any] = Field(default_factory=dict)


class SkillUpdateRequest(BaseModel):
    name: str | None = None
    description: str | None = None
    owner: str | None = None
    steps: list[dict[str, Any]] | None = None
    intent_keywords: list[str] | None = None
    required_roles: set[str] | None = None
    enabled: bool | None = None
    risk_level: str | None = None
    license: str | None = None
    compatibility: str | None = None
    allowed_tools: list[str] | None = None
    skill_metadata: dict[str, Any] | None = None


# ═══════════════════════════════════════════════════════════════════════════════
# 知识管理 Schemas
# ═══════════════════════════════════════════════════════════════════════════════


class ErrorCodeCreate(BaseModel):
    error_code: str
    description: str | None = None
    exception_type: str | None = None
    responsible_role: str | None = None
    recommendation: str | None = None


class ErrorCodeUpdate(BaseModel):
    description: str | None = None
    exception_type: str | None = None
    responsible_role: str | None = None
    recommendation: str | None = None


class RuleCreate(BaseModel):
    rule_id: str
    rule_name: str
    category: str | None = None
    scenario: str | None = None
    rule_content: str | None = None
    explanation: str | None = None
    applicable_roles: list[str] | None = None
    risk_level: str | None = 'LOW'
    effective_date: str | None = None
    enabled: bool | None = True


class RuleUpdate(BaseModel):
    rule_name: str | None = None
    category: str | None = None
    scenario: str | None = None
    rule_content: str | None = None
    explanation: str | None = None
    applicable_roles: list[str] | None = None
    risk_level: str | None = None
    effective_date: str | None = None
    enabled: bool | None = None


class AssetCreate(BaseModel):
    asset_id: str
    title: str
    source: str | None = None
    asset_type: str | None = None
    version: str | None = None
    status: str | None = None
    summary: str | None = None
    visibility: dict[str, Any] | None = None
    index_status: str | None = None
    effective_date: str | None = None
    imported_at: str | None = None


class AssetUpdate(BaseModel):
    title: str | None = None
    source: str | None = None
    asset_type: str | None = None
    version: str | None = None
    status: str | None = None
    summary: str | None = None
    visibility: dict[str, Any] | None = None
    index_status: str | None = None


class ChunkCreate(BaseModel):
    chunk_id: str
    text: str
    asset_type: str | None = None
    title: str | None = None
    section: str | None = None
    summary: str | None = None
    tags: list[str] | None = None
    scenario_tags: list[str] | None = None
    visibility: dict[str, Any] | None = None
    locator: str | None = None
    embedding_id: str | None = None


class AppealTemplateCreate(BaseModel):
    template_id: str
    template_name: str
    template_type: str | None = None
    denial_reason_pattern: str | None = None
    content: str
    required_evidence: list[str] | None = None
    applicable_scenarios: list[str] | None = None
    enabled: bool | None = True


class AppealTemplateUpdate(BaseModel):
    template_name: str | None = None
    template_type: str | None = None
    denial_reason_pattern: str | None = None
    content: str | None = None
    required_evidence: list[str] | None = None
    applicable_scenarios: list[str] | None = None
    enabled: bool | None = None


class PromptTemplateCreate(BaseModel):
    template_id: str
    template_name: str
    template_type: str
    scenario: str | None = None
    role: str | None = None
    system_prompt: str | None = None
    user_prompt_template: str | None = None
    variables: list[str] | None = None
    output_format: dict[str, Any] | None = None
    enabled: bool | None = True


class PromptTemplateUpdate(BaseModel):
    template_name: str | None = None
    template_type: str | None = None
    scenario: str | None = None
    role: str | None = None
    system_prompt: str | None = None
    user_prompt_template: str | None = None
    variables: list[str] | None = None
    output_format: dict[str, Any] | None = None
    enabled: bool | None = None


class PromptTemplateRenderRequest(BaseModel):
    template_id: str
    variables: dict[str, str]
