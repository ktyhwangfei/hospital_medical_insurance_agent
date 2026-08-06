"""Skill 评测与发布控制面的显式 API DTO。"""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from src.domain.skill.draft_models import SkillDraft


class SkillEvalCaseCreateRequest(BaseModel):
    question_template: str = Field(min_length=1, max_length=2000)
    expected_skill_id: str | None = None
    required: bool = True
    risk_tags: list[str] = Field(default_factory=list)
    business_tags: list[str] = Field(default_factory=list)
    source_type: str = "manual"
    source_ref: str = ""
    contains_sensitive_data: Literal[False] = False


class SkillEvalCaseUpdateRequest(BaseModel):
    question_template: str = Field(min_length=1, max_length=2000)
    expected_skill_id: str | None = None
    required: bool = True
    risk_tags: list[str] = Field(default_factory=list)
    business_tags: list[str] = Field(default_factory=list)
    source_type: str = "manual"
    source_ref: str = ""
    enabled: bool = True
    contains_sensitive_data: Literal[False] = False


class SkillEvalCaseResponse(BaseModel):
    case_id: str
    suite_version: int
    question_template: str
    expected_skill_id: str | None
    required: bool
    risk_tags: list[str]
    business_tags: list[str]
    source_type: str
    source_ref: str
    contains_sensitive_data: bool
    enabled: bool
    created_by: str
    created_at: datetime
    updated_at: datetime


class SkillEvalCaseListResponse(BaseModel):
    items: list[SkillEvalCaseResponse]
    suite_version: int
    total: int


class SkillEvalRunCreateRequest(BaseModel):
    version_id: str = Field(min_length=1, max_length=64)
    baseline_version_id: str | None = Field(default=None, max_length=64)


class SkillEvalMetricsResponse(BaseModel):
    total: int
    passed: int
    required_total: int
    required_passed: int
    top1_accuracy: float
    baseline_top1_accuracy: float
    regression_count: int
    new_false_takeover_count: int
    gate_passed: bool


class SkillEvalResultResponse(BaseModel):
    case_id: str
    expected_skill_id: str | None
    candidate_skill_id: str | None
    baseline_skill_id: str | None
    candidate_confidence: float
    baseline_confidence: float
    candidate_passed: bool
    baseline_passed: bool
    required: bool
    diff: str
    candidate_keywords: list[str]
    baseline_keywords: list[str]


class SkillEvalRunResponse(BaseModel):
    run_id: str
    skill_id: str
    version_id: str
    baseline_version_id: str | None
    suite_version: int
    config_hash: str
    routing_manifest_hash: str
    status: str
    metrics: SkillEvalMetricsResponse
    results: list[SkillEvalResultResponse]
    case_snapshots: list[SkillEvalCaseResponse]
    created_by: str
    created_at: datetime
    completed_at: datetime | None


class SkillEvalRunListResponse(BaseModel):
    items: list[SkillEvalRunResponse]
    total: int


class SkillReleaseCreateRequest(BaseModel):
    version_id: str = Field(min_length=1, max_length=64)
    eval_run_id: str = Field(min_length=1, max_length=64)
    environment: Literal["dev", "test"] = "test"


class SkillReleaseTransitionRequest(BaseModel):
    expected_revision: int = Field(ge=1)


class SkillReleaseApproveRequest(SkillReleaseTransitionRequest):
    reason: str = Field(min_length=1, max_length=1000)


class SkillWorkbenchSummaryResponse(BaseModel):
    total: int
    healthy: int
    needs_evaluation: int
    pending_approval: int
    test_active: int
    updated_at: datetime


class SkillWorkbenchItemResponse(BaseModel):
    skill_id: str
    skill_name: str
    business_action: str
    business_object: str
    semantic_version: str
    artifact_status: str
    validation_status: str
    latest_eval_status: str | None
    test_release_status: str | None
    test_active_version: str | None
    governance_status: str
    attention_reason: str | None


class SkillWorkbenchResponse(BaseModel):
    summary: SkillWorkbenchSummaryResponse
    items: list[SkillWorkbenchItemResponse]
    total: int
    page: int
    page_size: int


class SkillReleaseApprovalSummaryResponse(BaseModel):
    approved_by: str
    approver_role: str
    approved_at: datetime


class SkillReleaseResponse(BaseModel):
    release_id: str
    skill_id: str
    version_id: str
    environment: str
    status: str
    baseline_release_id: str | None
    eval_run_id: str
    artifact_hash: str
    config_hash: str
    rollout_percent: int
    runtime_mode: str
    revision: int
    created_by: str
    created_at: datetime
    activated_at: datetime | None
    retired_at: datetime | None
    approval: SkillReleaseApprovalSummaryResponse | None = None


class SkillReleaseListResponse(BaseModel):
    items: list[SkillReleaseResponse]
    total: int


# ── Skill 草稿管理（P1+）──────────────────────────────────────────


class SkillDraftCreateRequest(BaseModel):
    """从模板创建草稿。"""
    skill_id: str
    skill_name: str
    description: str = ""
    owner: str = ""
    business_action: str = ""
    business_object: str = ""
    include_keywords: list[str] = []
    excluded_intents: list[str] = []


class SkillDraftCopyRequest(BaseModel):
    """复制正式 Skill 为草稿。"""
    new_skill_id: str


class SkillDraftSaveRequest(BaseModel):
    """保存草稿（乐观锁）。"""
    structured_config: dict[str, Any]
    raw_files: dict[str, str] | None = None
    status: str | None = None
    expected_revision: int = Field(ge=1)


class SkillDraftResponse(BaseModel):
    draft_id: str
    skill_id: str
    skill_name: str
    source_type: str
    source_skill_id: str | None = None
    structured_config: dict[str, Any]
    raw_files: dict[str, str]
    validation_report: dict[str, Any] | None = None
    status: str
    revision: int
    created_by: str
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None = None

    @classmethod
    def from_model(cls, draft: SkillDraft) -> "SkillDraftResponse":
        return cls(
            draft_id=draft.draft_id,
            skill_id=draft.skill_id,
            skill_name=draft.skill_name,
            source_type=draft.source_type.value,
            source_skill_id=draft.source_skill_id,
            structured_config=draft.structured_config,
            raw_files=draft.raw_files,
            validation_report=draft.validation_report,
            status=draft.status.value,
            revision=draft.revision,
            created_by=draft.created_by,
            created_at=draft.created_at,
            updated_at=draft.updated_at,
            deleted_at=draft.deleted_at,
        )


class SkillDraftListResponse(BaseModel):
    items: list[SkillDraftResponse]
    total: int


class SkillValidationIssueResponse(BaseModel):
    code: str
    message: str
    severity: str
    path: str | None = None


class SkillDraftValidationResponse(BaseModel):
    draft_id: str
    issues: list[SkillValidationIssueResponse]
    has_blocking: bool
    blocking_ok: bool
    revision: int


class SkillPackageFileResponse(BaseModel):
    path: str
    content: str


class SkillPackagePreviewResponse(BaseModel):
    draft_id: str
    files: list[SkillPackageFileResponse]
    file_count: int
    revision: int


class SkillMaterializeRequest(BaseModel):
    expected_revision: int = Field(ge=1)
    reason: str = Field(min_length=1, max_length=500)
    source_commit: str | None = None


class SkillMaterializeResponse(BaseModel):
    skill_id: str
    version_id: str
    semantic_version: str
    lifecycle_status: str
    artifact_written: bool
    draft_revision: int


class SkillLifecycleTransitionRequest(BaseModel):
    expected_revision: int = Field(ge=1)
    reason: str = Field(min_length=1, max_length=500)


class SkillDefinitionResponse(BaseModel):
    skill_id: str
    skill_name: str
    business_action: str
    business_object: str
    lifecycle_status: str
    semantic_dependency_changed: bool
    current_version_id: str | None = None
    revision: int
    disabled_at: datetime | None = None
    archived_at: datetime | None = None

    @classmethod
    def from_model(cls, d) -> "SkillDefinitionResponse":
        return cls(
            skill_id=d.skill_id,
            skill_name=d.skill_name,
            business_action=d.business_action,
            business_object=d.business_object,
            lifecycle_status=d.lifecycle_status.value,
            semantic_dependency_changed=d.semantic_dependency_changed,
            current_version_id=d.current_version_id,
            revision=d.revision,
            disabled_at=d.disabled_at,
            archived_at=d.archived_at,
        )
