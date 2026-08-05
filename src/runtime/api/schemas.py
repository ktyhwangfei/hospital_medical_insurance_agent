from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field
from typing import Any, Optional

# ---------------------------------------------------------
# Infra Skill 相关的 Schema
# ---------------------------------------------------------

class InfraSkillItem(BaseModel):
    skill_id: str
    skill_name: str
    business_action: str = ""
    business_object: str = ""
    include_keywords: list[str] = Field(default_factory=list)
    excluded_intents: list[str] = Field(default_factory=list)


class SkillValidationIssueResponse(BaseModel):
    code: str
    message: str
    path: str | None = None


class SkillVersionResponse(BaseModel):
    version_id: str
    skill_id: str
    semantic_version: str
    source_commit: str
    source_path: str
    artifact_hash: str
    manifest_snapshot: dict[str, Any] = Field(default_factory=dict)
    dependency_snapshot: dict[str, Any] = Field(default_factory=dict)
    file_count: int
    validation_status: str
    validation_issues: list[SkillValidationIssueResponse] = Field(default_factory=list)
    created_by: str
    created_at: datetime


class InfraSkillCatalogItem(InfraSkillItem):
    semantic_version: str
    artifact_hash: str
    artifact_status: str
    file_count: int
    registered_version: SkillVersionResponse | None = None


class InfraSkillCatalogResponse(BaseModel):
    items: list[InfraSkillCatalogItem] = Field(default_factory=list)
    page: int
    page_size: int
    total: int


class SkillVersionSyncRequest(BaseModel):
    source_commit: str = Field(min_length=7, max_length=64)
    created_by: str = Field(min_length=1, max_length=128)

class InfraSkillFilesStructure(BaseModel):
    agents: list[str] = Field(default_factory=list)
    schemas: list[str] = Field(default_factory=list)
    templates: list[str] = Field(default_factory=list)
    scripts: list[str] = Field(default_factory=list)
    references: list[str] = Field(default_factory=list)
    tests: list[str] = Field(default_factory=list)
    strategies: list[str] = Field(default_factory=list)

class FieldMappingItem(BaseModel):
    """语义层字段映射条目"""
    label: str = ""
    description: str = ""
    db_source: str = ""


class FieldMappingResponse(BaseModel):
    """技能字段映射汇总"""
    target_field: dict[str, Any] = Field(default_factory=dict)
    settlement_fields: dict[str, FieldMappingItem] = Field(default_factory=dict)
    defaults: dict[str, str] = Field(default_factory=dict)


class InfraSkillDetailResponse(BaseModel):
    skill_id: str
    skill_name: str
    business_action: str = ""
    business_object: str = ""
    include_keywords: list[str] = Field(default_factory=list)
    excluded_intents: list[str] = Field(default_factory=list)
    manifest: dict[str, Any] = Field(default_factory=dict)
    readme: str = ""
    files_structure: InfraSkillFilesStructure = Field(default_factory=InfraSkillFilesStructure)
    field_mapping: FieldMappingResponse | None = None

class SkillRouteTestRequest(BaseModel):
    question: str

class SkillRouteTestResponse(BaseModel):
    question: str
    matched_skill_id: Optional[str] = None
    confidence: float = 0.0
    match_method: str = "none"
    matched_keywords: list[str] = Field(default_factory=list)
    excluded_keywords: list[str] = Field(default_factory=list)
    candidates: list[dict[str, Any]] = Field(default_factory=list)

class SkillExecuteTestRequest(BaseModel):
    question: str
    target_fee_item: Optional[str] = None
    context: dict[str, Any] = Field(default_factory=dict)
    evidence: list[dict[str, Any]] = Field(default_factory=list)
    status: str = "no_policy_matched"

class SkillRefreshResponse(BaseModel):
    """热重载响应"""
    skill_count: int
    skills: list[InfraSkillItem] = Field(default_factory=list)
    message: str = ""

class SkillExecuteTestResponse(BaseModel):
    skill_id: str
    status: str
    result: Any
    warnings: list[str] = Field(default_factory=list)
    citations: list[dict[str, Any]] = Field(default_factory=list)
    uncertainties: list[str] = Field(default_factory=list)
    trace: list[dict[str, Any]] = Field(default_factory=list)
    input_summary: dict[str, Any] = Field(default_factory=dict)
    latency_ms: int | None = None


class InfraSkillOverviewItem(BaseModel):
    skill_id: str
    skill_name: str
    business_action: str = ""
    business_object: str = ""
    loaded: bool = True
    manifest_valid: bool = True
    field_mapping_configured: bool = False
    metric_count: int = 0
    last_test_status: str | None = None
    warnings: list[str] = Field(default_factory=list)


class InfraSkillOverviewResponse(BaseModel):
    skill_count: int
    skills: list[InfraSkillOverviewItem] = Field(default_factory=list)


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
