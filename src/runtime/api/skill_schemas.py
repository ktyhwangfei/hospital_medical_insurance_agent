"""Skill 评测与发布控制面的显式 API DTO。"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


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
