"""Skill 批量评测与测试环境发布的领域模型。"""

from datetime import datetime, timezone
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


DEFAULT_ROUTING_SUITE_ID = "EVS_platform_routing"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class SkillEvalRunStatus(StrEnum):
    RUNNING = "running"
    PASSED = "passed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    ERROR = "error"


class SkillEvalDiff(StrEnum):
    UNCHANGED_PASS = "unchanged_pass"
    UNCHANGED_FAIL = "unchanged_fail"
    NEW_PASS = "new_pass"
    NEW_FAILURE = "new_failure"
    ROUTE_CHANGED = "route_changed"


class SkillReleaseEnvironment(StrEnum):
    DEV = "dev"
    TEST = "test"


class SkillReleaseStatus(StrEnum):
    CANDIDATE = "candidate"
    APPROVAL_PENDING = "approval_pending"
    APPROVED = "approved"
    ACTIVE = "active"
    RETIRED = "retired"


class SkillEvalSuiteScope(StrEnum):
    PLATFORM = "platform"
    SKILL = "skill"


class SkillEvalSuiteStatus(StrEnum):
    ACTIVE = "active"
    INACTIVE = "inactive"


class SkillEvalSuite(BaseModel):
    """可命名、可审计的 Skill 测评用例集合。"""

    model_config = ConfigDict(frozen=True)

    suite_id: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=256)
    scope: SkillEvalSuiteScope
    skill_id: str | None = Field(default=None, max_length=128)
    purpose: str = Field(default="", max_length=1000)
    status: SkillEvalSuiteStatus = SkillEvalSuiteStatus.ACTIVE
    revision: int = Field(default=1, ge=1)
    created_by: str = Field(min_length=1, max_length=128)
    updated_by: str = Field(min_length=1, max_length=128)
    created_at: datetime = Field(default_factory=_utc_now)
    updated_at: datetime = Field(default_factory=_utc_now)

    @model_validator(mode="after")
    def _validate_scope(self) -> "SkillEvalSuite":
        if self.scope == SkillEvalSuiteScope.PLATFORM and self.skill_id is not None:
            raise ValueError("platform 测评集不能设置 skill_id")
        if self.scope == SkillEvalSuiteScope.SKILL and not self.skill_id:
            raise ValueError("skill 测评集必须设置 skill_id")
        return self


class SkillEvalCase(BaseModel):
    """固定、脱敏的路由评测用例。"""

    model_config = ConfigDict(frozen=True)

    case_id: str
    suite_id: str = Field(
        default=DEFAULT_ROUTING_SUITE_ID,
        min_length=1,
        max_length=64,
    )
    suite_version: int = Field(ge=1)
    question_template: str = Field(min_length=1, max_length=2000)
    expected_skill_id: str | None = None
    required: bool = True
    risk_tags: list[str] = Field(default_factory=list)
    business_tags: list[str] = Field(default_factory=list)
    source_type: str = "manual"
    source_ref: str = ""
    contains_sensitive_data: Literal[False] = False
    enabled: bool = True
    created_by: str = Field(min_length=1, max_length=128)
    created_at: datetime = Field(default_factory=_utc_now)
    updated_at: datetime = Field(default_factory=_utc_now)


class SkillEvalResult(BaseModel):
    """单条用例的候选版与基线路由差异。"""

    model_config = ConfigDict(frozen=True)

    case_id: str
    expected_skill_id: str | None = None
    candidate_skill_id: str | None = None
    baseline_skill_id: str | None = None
    candidate_confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    baseline_confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    candidate_passed: bool
    baseline_passed: bool
    required: bool = True
    diff: SkillEvalDiff
    candidate_keywords: list[str] = Field(default_factory=list)
    baseline_keywords: list[str] = Field(default_factory=list)


class SkillEvalMetrics(BaseModel):
    """由服务端计算的发布门禁指标。"""

    model_config = ConfigDict(frozen=True)

    total: int = Field(ge=0)
    passed: int = Field(ge=0)
    required_total: int = Field(ge=0)
    required_passed: int = Field(ge=0)
    top1_accuracy: float = Field(ge=0.0, le=1.0)
    baseline_top1_accuracy: float = Field(ge=0.0, le=1.0)
    regression_count: int = Field(ge=0)
    new_false_takeover_count: int = Field(ge=0)
    gate_passed: bool


class SkillRegressionEvalRecord(BaseModel):
    """单条分型回归用例在一次评测运行中的冻结结果。"""

    model_config = ConfigDict(frozen=True)

    case_id: str
    case_type: str
    candidate_version_id: str
    case_snapshot_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    evaluator_version: str
    passed: bool
    status: str  # passed | failed | blocked_by_evaluator
    failure_codes: list[str] = Field(default_factory=list)
    required: bool = True


class SkillRegressionSummary(BaseModel):
    """回归用例发布门禁汇总（独立于路由 top1 accuracy）。"""

    model_config = ConfigDict(frozen=True)

    total: int = Field(default=0, ge=0)
    passed: int = Field(default=0, ge=0)
    failed: int = Field(default=0, ge=0)
    blocked: int = Field(default=0, ge=0)
    required_total: int = Field(default=0, ge=0)
    required_passed: int = Field(default=0, ge=0)
    required_blocked: int = Field(default=0, ge=0)
    gate_passed: bool


class SkillEvalRun(BaseModel):
    """绑定候选版本、基线和测试集快照的评测运行。"""

    model_config = ConfigDict(frozen=True)

    run_id: str
    skill_id: str
    version_id: str
    baseline_version_id: str | None = None
    suite_version: int = Field(ge=1)
    config_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    routing_manifest_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    status: SkillEvalRunStatus
    metrics: SkillEvalMetrics
    results: list[SkillEvalResult] = Field(default_factory=list)
    case_snapshots: list[SkillEvalCase] = Field(default_factory=list)
    regression_results: list[SkillRegressionEvalRecord] = Field(default_factory=list)
    regression_summary: SkillRegressionSummary | None = None
    created_by: str = Field(min_length=1, max_length=128)
    created_at: datetime = Field(default_factory=_utc_now)
    completed_at: datetime | None = None


class SkillRelease(BaseModel):
    """dev/test 环境中的候选或活动 Skill 发布。"""

    model_config = ConfigDict(frozen=True)

    release_id: str
    skill_id: str
    version_id: str
    environment: SkillReleaseEnvironment
    status: SkillReleaseStatus
    baseline_release_id: str | None = None
    eval_run_id: str
    artifact_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    config_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    rollout_percent: Literal[0, 100] = 0
    runtime_mode: Literal["shadow"] = "shadow"
    revision: int = Field(default=1, ge=1)
    created_by: str = Field(min_length=1, max_length=128)
    created_at: datetime = Field(default_factory=_utc_now)
    activated_at: datetime | None = None
    retired_at: datetime | None = None


class SkillReleaseApproval(BaseModel):
    """冻结制品、评测、配置与基线的人工审批证据。"""

    model_config = ConfigDict(frozen=True)

    approval_id: str
    release_id: str
    artifact_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    eval_run_id: str
    config_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    baseline_release_id: str | None = None
    approved_by: str = Field(min_length=1, max_length=128)
    approver_role: str = Field(min_length=1, max_length=128)
    reason: str = Field(min_length=1, max_length=1000)
    approved_at: datetime = Field(default_factory=_utc_now)
