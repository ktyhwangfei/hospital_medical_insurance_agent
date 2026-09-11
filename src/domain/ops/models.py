"""健康运营（Ops Health）领域模型 — #45 P0 问题库 + #50 生命周期 + #53 自动修复。

横跨四类资产（skill/knowledge/data/runtime）的开放问题汇聚层；
「发现」阶段检查器只读产出 FindingDraft，存储按 fingerprint 去重
落库为 OpsFinding（occurrence_count 累计）。「处置」阶段（#50）提供
ignore/reopen 手动流转：带乐观锁 revision 与事件时间线。「解决」阶段
（#53）提供 L1 白名单自动修复：执行幂等动作后强制重跑触发检查器，
验证通过才 resolved，失败累计 occurrence 保持 open；每次修复落
OpsRemediationRun 留痕。诊断与 L2 人工流程随 P1/后续分期扩充。
"""
from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class OpsAssetType(StrEnum):
    """受检资产类型（健康运营横跨四域）。"""

    SKILL = "skill"
    KNOWLEDGE = "knowledge"
    DATA = "data"
    RUNTIME = "runtime"


class OpsSeverity(StrEnum):
    """问题严重度：critical 需立即处理，warning 需排期，info 仅记录。"""

    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


class OpsFindingStatus(StrEnum):
    """问题状态（open 巡检产出；ignored #50 手动忽略；resolved #53 修复验证驱动；waiting_human #54 转人工处理中）。"""

    OPEN = "open"
    RESOLVED = "resolved"
    IGNORED = "ignored"
    WAITING_HUMAN = "waiting_human"


def new_finding_id() -> str:
    return uuid.uuid4().hex


def new_finding_event_id() -> str:
    return uuid.uuid4().hex


def new_remediation_run_id() -> str:
    return uuid.uuid4().hex


def new_inspection_id() -> str:
    return uuid.uuid4().hex


def finding_fingerprint(asset_type: OpsAssetType, asset_id: str, check_id: str) -> str:
    """问题身份键：同一资产上同一检查项的复现问题只累计，不重复建档。"""
    return f"{asset_type.value}:{asset_id}:{check_id}"


class FindingDraft(BaseModel):
    """检查器单次巡检产出的问题草稿（值对象：未落库、无去重与状态字段）。

    payload 只允许脱敏后的安全证据字段（safe_* / 状态码 / 时间戳），
    检查器取数侧负责不带出凭据与原始连接串。
    """

    model_config = ConfigDict(frozen=True)

    asset_type: OpsAssetType
    asset_id: str = Field(min_length=1, max_length=128)
    check_id: str = Field(min_length=1, max_length=64)
    severity: OpsSeverity
    payload: dict[str, Any] = Field(default_factory=dict)


class OpsFinding(BaseModel):
    """资产健康问题（聚合根）：fingerprint 唯一，复现累计 occurrence_count。

    revision 为乐观锁版本，随每次 upsert / 生命周期操作递增。
    """

    model_config = ConfigDict(frozen=True)

    finding_id: str = Field(min_length=1, max_length=64)
    asset_type: OpsAssetType
    asset_id: str = Field(min_length=1, max_length=128)
    check_id: str = Field(min_length=1, max_length=64)
    severity: OpsSeverity
    status: OpsFindingStatus = OpsFindingStatus.OPEN
    fingerprint: str = Field(min_length=1, max_length=256)
    payload: dict[str, Any] = Field(default_factory=dict)
    first_seen_at: datetime
    last_seen_at: datetime
    occurrence_count: int = Field(default=1, ge=1)
    diagnosis: dict[str, Any] | None = None  # P1 诊断报告占位（schema 稳定）
    revision: int = Field(default=1, ge=1)


class OpsFindingPage(BaseModel):
    """问题列表分页结果。"""

    items: list[OpsFinding]
    total: int = Field(ge=0)
    page: int = Field(ge=1)
    page_size: int = Field(ge=1)


class OpsFindingEventType(StrEnum):
    """生命周期流转事件类型（手动操作、#53 修复验证与 #54 人工交接产生）。"""

    IGNORED = "ignored"
    REOPENED = "reopened"
    RESOLVED = "resolved"
    MANUAL_REQUESTED = "manual_requested"
    MANUAL_COMPLETED = "manual_completed"


class OpsFindingEvent(BaseModel):
    """问题生命周期事件（Entity）：一次 ignore/reopen 流转的留痕。

    reason 在 ignore 时必填、reopen 时为空（业务层约束，存储不重复校验）。
    """

    model_config = ConfigDict(frozen=True)

    event_id: str = Field(min_length=1, max_length=64)
    finding_id: str = Field(min_length=1, max_length=64)
    event_type: OpsFindingEventType
    actor: str = Field(min_length=1, max_length=128)
    reason: str | None = Field(default=None, max_length=500)
    created_at: datetime


class OpsFindingDetail(BaseModel):
    """单条问题详情视图：当前状态 + 生命周期事件与修复记录时间线（升序）。"""

    finding: OpsFinding
    events: list[OpsFindingEvent]
    remediations: list["OpsRemediationRun"] = Field(default_factory=list)
    manual_task: "OpsManualHandoff | None" = None  # #54 最新人工确认任务投影


class RemediationRiskLevel(StrEnum):
    """修复动作风险级：L1 幂等可重放、允许自动执行；L2 需人工确认。"""

    L1 = "L1"
    L2 = "L2"


class RemediationRunStatus(StrEnum):
    """修复动作执行状态（动作本身是否执行到位，与验证结果正交）。"""

    SUCCEEDED = "succeeded"
    FAILED = "failed"


class VerificationResult(StrEnum):
    """修复后强制验证结果：重跑触发检查器是否仍产出该问题。"""

    PASSED = "passed"
    FAILED = "failed"


class OpsRemediationRun(BaseModel):
    """一次 L1 自动修复的留痕（Entity）：动作前后证据 + 强制验证结果。

    status 描述动作执行（retry 是否真正跑起来）；verification_result
    描述修复后验证（None = 未验证：动作未执行或检查器自身出错）。
    """

    model_config = ConfigDict(frozen=True)

    run_id: str = Field(min_length=1, max_length=64)
    finding_id: str = Field(min_length=1, max_length=64)
    action: str = Field(min_length=1, max_length=64)
    risk_level: RemediationRiskLevel
    status: RemediationRunStatus
    before_evidence: dict[str, Any] = Field(default_factory=dict)
    after_evidence: dict[str, Any] = Field(default_factory=dict)
    verification_result: VerificationResult | None = None
    created_by: str = Field(min_length=1, max_length=128)
    created_at: datetime


# ── #51 P1-5 LLM 智能诊断 ──


class DiagnosisStatus(StrEnum):
    """诊断结论状态：无 citations 一律落 insufficient_evidence，不驱动动作。"""

    COMPLETE = "complete"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"


class DiagnosisActionLevel(StrEnum):
    """建议动作分级：L1 自动白名单 / L2 人工确认 / L3 禁止（仅提示永不执行）。"""

    L1 = "L1"
    L2 = "L2"
    L3 = "L3"


class DiagnosisCitation(BaseModel):
    """诊断证据引用：只能从证据目录中选取（quote 取自目录，模型不可编造）。"""

    model_config = ConfigDict(frozen=True)

    citation_id: str = Field(min_length=1, max_length=16)
    source: str = Field(min_length=1, max_length=128)
    quote: str = Field(min_length=1, max_length=500)


class DiagnosisAction(BaseModel):
    """分级建议动作（诊断只读产出，执行仍走 #53 白名单 / #54 人工流）。"""

    model_config = ConfigDict(frozen=True)

    level: DiagnosisActionLevel
    description: str = Field(min_length=1, max_length=500)
    citation_ids: list[str] = Field(min_length=1)


class OpsDiagnosisReport(BaseModel):
    """单条 finding 的诊断报告（存入 OpsFinding.diagnosis，最新一份覆盖）。"""

    finding_id: str = Field(min_length=1, max_length=64)
    status: DiagnosisStatus
    root_cause: str | None = Field(default=None, max_length=2000)
    citations: list[DiagnosisCitation] = Field(default_factory=list)
    uncertainties: list[str] = Field(default_factory=list)
    actions: list[DiagnosisAction] = Field(default_factory=list)
    model_route: dict[str, Any] = Field(default_factory=dict)  # scene/model_name 审计
    generated_by: str = Field(min_length=1, max_length=128)
    generated_at: datetime


class OpsDiagnosisResult(BaseModel):
    """一次诊断的结果：刷新后的问题（含新报告）+ 报告本体。"""

    finding: OpsFinding
    report: OpsDiagnosisReport


# ── #52 P1-6 定时巡检调度 ──


class OpsInspectionTrigger(StrEnum):
    """巡检触发方式：manual（页面/接口手动）或 scheduled（周期调度）。"""

    MANUAL = "manual"
    SCHEDULED = "scheduled"


class OpsInspectionStatus(StrEnum):
    """单次巡检运行状态：running 已抢占未收尾 / succeeded / failed。"""

    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class OpsCheckerError(BaseModel):
    """单检查器执行失败记录（不中断整次巡检）。"""

    model_config = ConfigDict(frozen=True)

    check_id: str = Field(min_length=1, max_length=64)
    message: str = Field(min_length=1, max_length=500)


class OpsInspectionRun(BaseModel):
    """一次巡检运行留痕（Entity）：触发方式、起止时间与新发现数。

    手动与定时统一经 claim 抢占写入 running 行：调度行
    active_inspection_id 互斥保证同一时刻至多一条 running，
    结束后回填终态与计数（new_finding_count 只计首见问题）。
    """

    model_config = ConfigDict(frozen=True)

    inspection_id: str = Field(min_length=1, max_length=64)
    trigger_source: OpsInspectionTrigger
    status: OpsInspectionStatus
    triggered_by: str = Field(min_length=1, max_length=128)
    started_at: datetime
    finished_at: datetime | None = None
    finding_count: int = Field(default=0, ge=0)
    new_finding_count: int = Field(default=0, ge=0)
    checker_errors: list[OpsCheckerError] = Field(default_factory=list)


class OpsInspectionScheduleState(BaseModel):
    """单行调度状态：下次巡检时间与当前互斥的运行占位。"""

    next_run_at: datetime
    active_inspection_id: str | None = None


class OpsInspectionSummary(BaseModel):
    """巡检摘要（Portal 顶部摘要条）：周期 + 下次巡检 + 最近一次巡检。"""

    interval_minutes: int = Field(ge=1)
    next_run_at: datetime | None = None
    in_progress: bool = False
    latest: OpsInspectionRun | None = None


# ── #54 P2-8 L2 人工确认修复流 ──


class OpsManualTarget(StrEnum):
    """L2 人工处理跳转目标（按资产类型映射到既有治理页面）。"""

    POLICY_KNOWLEDGE = "policy_knowledge"  # 知识内容修正 → 政策知识审核/重提取管线
    SKILL_DRAFT = "skill_draft"            # skill 草稿修改 → skills 草稿流程
    EXTERNAL = "external"                  # data/runtime 资产：无门户治理页，外部系统处理


def manual_target_for_asset(asset_type: "OpsAssetType") -> OpsManualTarget:
    """资产类型 → 人工处理跳转目标（knowledge/skill 有治理页，其余走外部）。"""
    if asset_type is OpsAssetType.KNOWLEDGE:
        return OpsManualTarget.POLICY_KNOWLEDGE
    if asset_type is OpsAssetType.SKILL:
        return OpsManualTarget.SKILL_DRAFT
    return OpsManualTarget.EXTERNAL


class OpsManualHandoff(BaseModel):
    """L2 人工确认任务的只读投影（源数据在 task_closure 任务表）。"""

    task_id: str = Field(min_length=1, max_length=64)
    status: str  # waiting_human_confirmation | completed
    target: OpsManualTarget
    requested_by: str = Field(min_length=1, max_length=128)
    requested_at: datetime
    note: str | None = Field(default=None, max_length=500)
    handled_by: str | None = Field(default=None, max_length=128)
    handled_at: datetime | None = None
    result_note: str | None = Field(default=None, max_length=500)


class OpsManualResult(BaseModel):
    """人工交接操作（发起/完成）的返回：最新详情 + 任务投影。"""

    detail: OpsFindingDetail
    manual_task: OpsManualHandoff


class DiagnosisUnavailableError(Exception):
    """诊断不可用（模型未配置/调用失败/输出不可解析），不落库不覆盖旧报告。"""

    def __init__(self, reason: str) -> None:
        super().__init__(f"诊断不可用：{reason}")
        self.reason = reason


class OpsFindingNotFoundError(Exception):
    """问题不存在（按 finding_id 查询）。"""

    def __init__(self, finding_id: str) -> None:
        super().__init__(f"问题不存在: {finding_id}")
        self.finding_id = finding_id


class InvalidFindingTransitionError(Exception):
    """非法状态流转（如对已忽略问题再次忽略、对开放问题重开）。"""

    def __init__(self, finding_id: str, action: str, current_status: OpsFindingStatus) -> None:
        super().__init__(
            f"问题 {finding_id} 当前状态 {current_status.value} 不允许执行 {action}"
        )
        self.finding_id = finding_id
        self.action = action
        self.current_status = current_status


class FindingRevisionConflictError(Exception):
    """乐观锁冲突：expected_revision 与库内 revision 不一致（并发流转/巡检刷新）。"""

    def __init__(self, finding_id: str, expected_revision: int, actual_revision: int) -> None:
        super().__init__(
            f"问题 {finding_id} 版本冲突：期望 revision {expected_revision}，实际 {actual_revision}"
        )
        self.finding_id = finding_id
        self.expected_revision = expected_revision
        self.actual_revision = actual_revision


class RemediationNotAllowedError(Exception):
    """该问题的检查项不在 L1 修复白名单内（只允许人工处置）。"""

    def __init__(self, finding_id: str, check_id: str) -> None:
        super().__init__(f"问题 {finding_id} 的检查项 {check_id} 不在自动修复白名单内")
        self.finding_id = finding_id
        self.check_id = check_id


class ManualTaskNotFoundError(Exception):
    """问题没有可操作的人工确认任务（未发起或任务类型不符）。"""

    def __init__(self, finding_id: str) -> None:
        super().__init__(f"问题 {finding_id} 没有等待中的人工确认任务")
        self.finding_id = finding_id


class OpsInspectionNotFoundError(Exception):
    """巡检运行记录不存在（按 inspection_id 查询）。"""

    def __init__(self, inspection_id: str) -> None:
        super().__init__(f"巡检记录不存在: {inspection_id}")
        self.inspection_id = inspection_id


class InspectionInProgressError(Exception):
    """已有巡检正在执行（claim 抢占失败），手动触发被拒绝。"""

    def __init__(self, active_inspection_id: str | None) -> None:
        super().__init__(
            f"巡检 {active_inspection_id or '(未知)'} 正在执行中，请稍后重试"
        )
        self.active_inspection_id = active_inspection_id
