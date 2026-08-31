"""Skill 批量评测、端到端数据集与测试环境发布的领域模型。"""

import hashlib
import json
from datetime import datetime, timezone
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from src.domain.skill.regression_models import (
    AnswerQualityAssertions,
    CalculationAssertions,
    CitationAssertions,
    PolicyContentAssertions,
    SafetyAssertions,
)


DEFAULT_ROUTING_SUITE_ID = "EVS_platform_routing"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def canonical_eval_hash(value: object) -> str:
    """对评测快照生成跨运行稳定的 SHA-256。"""
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
        allow_nan=False,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class SkillEvalRunStatus(StrEnum):
    RUNNING = "running"
    PASSED = "passed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    ERROR = "error"


class SkillEvalPartition(StrEnum):
    REGRESSION = "regression"
    BENCHMARK = "benchmark"
    HOLDOUT = "holdout"


class SkillEvalTaskStatus(StrEnum):
    PASSED = "passed"
    FAILED = "failed"
    BLOCKED = "blocked"
    NEEDS_REVIEW = "needs_review"
    INVALID_DATASET = "invalid_dataset"


class SkillEvalDimension(StrEnum):
    ROUTE = "route"
    BEHAVIOR = "behavior"
    CALCULATION = "calculation"
    POLICY_CONTENT = "policy_content"
    CITATION = "citation"
    ANSWER_QUALITY = "answer_quality"
    SAFETY = "safety"


class SkillEvalStage(StrEnum):
    PREFLIGHT = "preflight"
    SETTLEMENT_LOOKUP = "settlement_lookup"
    CONTEXT = "context"
    ROUTING = "routing"
    SKILL_EXECUTION = "skill_execution"
    POLICY_RETRIEVAL = "policy_retrieval"
    CALCULATION = "calculation"
    ANSWER_COMPOSITION = "answer_composition"
    DETERMINISTIC_VERIFICATION = "deterministic_verification"
    JUDGE = "judge"


class SkillEvalFailureOwner(StrEnum):
    AGENT = "agent"
    ENVIRONMENT = "environment"
    DATASET = "dataset"
    EVALUATOR = "evaluator"


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


class SkillEvalTaskInput(BaseModel):
    """端到端任务的最小公开输入。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    question: str = Field(min_length=1, max_length=2000)
    settlement_id: str | None = Field(default=None, max_length=80)
    role: str = Field(default="cashier", min_length=1, max_length=64)


class SkillEvalDataLocator(BaseModel):
    """不暴露物理表或查询语句的业务数据定位。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    resource_type: str = Field(min_length=1, max_length=64)
    resource_id: str = Field(min_length=1, max_length=128)


class SkillEvalEnvironmentRequirement(BaseModel):
    """任务声明的类型化评估环境依赖。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["data_source", "policy", "semantic", "tool", "model", "security"]
    name: str = Field(min_length=1, max_length=128)
    version: str | None = Field(default=None, max_length=128)
    required: bool = True


class RouteAssertions(BaseModel):
    """复用现有路由器时使用的任务级路由断言。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    case_type: Literal["routing"] = "routing"
    expected_skill_id: str | None = Field(default=None, max_length=128)
    minimum_confidence: float = Field(default=0.0, ge=0.0, le=1.0)


SkillEvalExpected = Annotated[
    RouteAssertions
    | CalculationAssertions
    | PolicyContentAssertions
    | CitationAssertions
    | AnswerQualityAssertions
    | SafetyAssertions,
    Field(discriminator="case_type"),
]


class SkillEvalAssertion(BaseModel):
    """一次任务执行上的类型化断言引用。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    assertion_id: str = Field(min_length=1, max_length=80)
    dimension: SkillEvalDimension
    output_adapter: str = Field(min_length=1, max_length=80)
    expected: SkillEvalExpected
    required: bool = True


class TrajectoryPrefix(BaseModel):
    """不含隐藏推理的可恢复执行接力点声明。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    prefix_id: str = Field(min_length=1, max_length=80)
    boundary_kind: Literal["after_settlement_loaded"]
    state_schema_version: Literal["policy_qa_prefix_v1"] = "policy_qa_prefix_v1"


class SkillEvalTask(BaseModel):
    """可版本化的端到端 Skill 评测任务。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    task_id: str = Field(min_length=1, max_length=80)
    suite_id: str = Field(min_length=1, max_length=64)
    target_skill_id: str = Field(min_length=1, max_length=128)
    name: str = Field(min_length=1, max_length=256)
    partition: SkillEvalPartition = SkillEvalPartition.REGRESSION
    input: SkillEvalTaskInput
    data_locators: tuple[SkillEvalDataLocator, ...] = ()
    environment_requirements: tuple[SkillEvalEnvironmentRequirement, ...] = ()
    assertions: tuple[SkillEvalAssertion, ...] = Field(min_length=1)
    trajectory_prefixes: tuple[TrajectoryPrefix, ...] = ()
    required: bool = True
    enabled: bool = True
    source_type: str = Field(default="manual", min_length=1, max_length=64)
    source_ref: str = Field(default="", max_length=256)
    risk_tags: tuple[str, ...] = ()
    business_tags: tuple[str, ...] = ()
    contains_sensitive_data: Literal[False] = False
    revision: int = Field(default=1, ge=1)
    created_by: str = Field(min_length=1, max_length=128)
    updated_by: str = Field(min_length=1, max_length=128)
    created_at: datetime = Field(default_factory=_utc_now)
    updated_at: datetime = Field(default_factory=_utc_now)


class SkillEvalDatasetVersion(BaseModel):
    """冻结任务内容与验证依赖的不可变数据集版本。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    dataset_version_id: str = Field(min_length=1, max_length=80)
    suite_id: str = Field(min_length=1, max_length=64)
    suite_revision: int = Field(ge=1)
    version_number: int = Field(ge=1)
    task_snapshots: tuple[SkillEvalTask, ...] = Field(min_length=1)
    environment_contract_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    evaluator_plan_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    created_by: str = Field(min_length=1, max_length=128)
    created_at: datetime = Field(default_factory=_utc_now)


class SkillEvalEnvironmentSnapshot(BaseModel):
    """Benchmark 使用的脱敏、类型化运行环境快照。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    runtime_version: str = Field(min_length=1, max_length=128)
    data_source_mode: str = Field(min_length=1, max_length=64)
    data_source_version: str | None = Field(default=None, max_length=128)
    skill_artifact_hash: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{64}$",
    )
    policy_version: str | None = Field(default=None, max_length=128)
    semantic_version: str | None = Field(default=None, max_length=128)
    tool_registry_version: str | None = Field(default=None, max_length=128)
    model_routing_version: str | None = Field(default=None, max_length=128)
    prompt_version: str | None = Field(default=None, max_length=128)
    security_policy_version: str | None = Field(default=None, max_length=128)


class SkillEvalGateThresholds(BaseModel):
    """不做跨维度总分的硬门禁阈值。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    required_hard_pass_rate: float = Field(default=1.0, ge=0.0, le=1.0)
    max_new_failures: int = Field(default=0, ge=0)


class SkillEvalBenchmarkStatus(StrEnum):
    ACTIVE = "active"
    ARCHIVED = "archived"


class SkillEvalBenchmark(BaseModel):
    """数据集、环境与验证方案的不可变 Benchmark 定义。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    benchmark_id: str = Field(min_length=1, max_length=80)
    name: str = Field(min_length=1, max_length=256)
    skill_id: str = Field(min_length=1, max_length=128)
    dataset_version_id: str = Field(min_length=1, max_length=80)
    environment_snapshot: SkillEvalEnvironmentSnapshot
    environment_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    evaluator_plan_id: str = Field(default="deterministic_v1", max_length=128)
    evaluator_plan_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    judge_version: str | None = Field(default=None, max_length=128)
    gate_thresholds: SkillEvalGateThresholds = Field(
        default_factory=SkillEvalGateThresholds
    )
    status: SkillEvalBenchmarkStatus = SkillEvalBenchmarkStatus.ACTIVE
    created_by: str = Field(min_length=1, max_length=128)
    created_at: datetime = Field(default_factory=_utc_now)


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


class SkillEvalTrajectoryStep(BaseModel):
    """可公开审计的结构化轨迹步骤，不保存隐藏思维过程。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    task_id: str = Field(min_length=1, max_length=80)
    sequence: int = Field(ge=0)
    stage: SkillEvalStage
    status: Literal["completed", "failed", "blocked", "skipped"]
    action: str = Field(min_length=1, max_length=256)
    observation_summary: str = Field(default="", max_length=1000)
    observation_hash: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{64}$",
    )
    evidence_refs: tuple[str, ...] = ()


class SkillEvalAssertionResult(BaseModel):
    """单条类型化断言的确定性验证结果。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    assertion_id: str = Field(min_length=1, max_length=80)
    dimension: SkillEvalDimension
    status: SkillEvalTaskStatus
    actual_value: str | float | bool | None = None
    failure_codes: tuple[str, ...] = ()
    evidence_refs: tuple[str, ...] = ()


class FailureAttribution(BaseModel):
    """带稳定机器码和证据引用的失败归因。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    task_id: str = Field(min_length=1, max_length=80)
    owner_type: SkillEvalFailureOwner
    stage: SkillEvalStage
    failure_code: str = Field(min_length=1, max_length=128)
    dimension: SkillEvalDimension | None = None
    summary: str = Field(min_length=1, max_length=1000)
    evidence_refs: tuple[str, ...] = ()


class SkillEvalTaskResult(BaseModel):
    """一次端到端任务执行的不可变结果。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    task_id: str = Field(min_length=1, max_length=80)
    status: SkillEvalTaskStatus
    selected_skill_id: str | None = Field(default=None, max_length=128)
    answer_excerpt: str = Field(default="", max_length=2000)
    assertion_results: tuple[SkillEvalAssertionResult, ...] = ()
    trajectory: tuple[SkillEvalTrajectoryStep, ...] = ()
    failure_attributions: tuple[FailureAttribution, ...] = ()
    diagnostic_prefix_id: str | None = Field(default=None, max_length=80)


class FailureCluster(BaseModel):
    """由稳定归因键形成的失败任务集合。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    cluster_id: str = Field(min_length=1, max_length=80)
    cluster_key: str = Field(min_length=1, max_length=512)
    owner_type: SkillEvalFailureOwner
    stage: SkillEvalStage
    failure_code: str = Field(min_length=1, max_length=128)
    dimension: SkillEvalDimension | None = None
    target_skill_id: str = Field(min_length=1, max_length=128)
    task_ids: tuple[str, ...] = Field(min_length=1)
    representative_task_id: str = Field(min_length=1, max_length=80)
    business_tags: tuple[str, ...] = ()


class SkillEvalDimensionSummary(BaseModel):
    """单个评测维度的状态汇总，不参与跨维度平均。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    dimension: SkillEvalDimension
    total: int = Field(ge=0)
    passed: int = Field(ge=0)
    failed: int = Field(ge=0)
    blocked: int = Field(ge=0)
    needs_review: int = Field(ge=0)
    invalid_dataset: int = Field(ge=0)


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
    dataset_version_id: str | None = Field(default=None, max_length=80)
    benchmark_id: str | None = Field(default=None, max_length=80)
    environment_snapshot: SkillEvalEnvironmentSnapshot | None = None
    task_results: tuple[SkillEvalTaskResult, ...] = ()
    trajectory_summary: tuple[SkillEvalTrajectoryStep, ...] = ()
    failure_attributions: tuple[FailureAttribution, ...] = ()
    failure_clusters: tuple[FailureCluster, ...] = ()
    dimension_summary: tuple[SkillEvalDimensionSummary, ...] = ()
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
