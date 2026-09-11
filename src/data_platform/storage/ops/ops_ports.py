"""健康运营问题库存储端口 — ports/adapter，默认 PostgreSQL，可回退内存。"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Protocol

from src.domain.ops.models import (
    FindingDraft,
    OpsAssetType,
    OpsCheckerError,
    OpsFinding,
    OpsFindingEvent,
    OpsFindingPage,
    OpsFindingStatus,
    OpsInspectionRun,
    OpsInspectionScheduleState,
    OpsInspectionStatus,
    OpsInspectionTrigger,
    OpsRemediationRun,
    OpsSeverity,
)

class OpsFindingStorage(Protocol):
    """问题库存储契约。

    upsert_finding 语义（fingerprint 去重）：
    - 首见：插入 status=open、occurrence_count=1；
    - 复现：occurrence_count+1、last_seen_at=seen_at、payload/severity 刷新为
      最新证据，status 与 diagnosis 不动（生命周期归 #50，诊断归 P1）。

    transition_finding 语义（#50 生命周期）：
    - 仅当库内 revision == expected_revision 时更新 status 并 revision+1，
      同事务追加一条事件留痕（事件由服务层构造，存储不校验状态机合法性）；
    - revision 不一致抛 FindingRevisionConflictError，问题不存在抛
      OpsFindingNotFoundError；状态机合法性由服务层前置校验。

    修复留痕语义（#53 自动修复）：
    - insert_remediation_run 追加一行 OpsRemediationRun（run_id 由服务层
      生成，存储不查重不校验）；list_remediation_runs 按 created_at 升序
      返回该问题的全部修复记录。

    诊断语义（#51 P1-5）：
    - save_diagnosis 覆盖写入 diagnosis 列（最新一份报告），不动 status
      与 revision（诊断只读、不驱动生命周期），问题不存在抛 NotFound。

    巡检调度语义（#52 P1-6，复用门诊同步 claim_due_job 模式）：
    - claim_inspection 抢占一次巡检：manual 立即到期，scheduled 需
      next_run_at 到期且无运行中巡检（active_inspection_id 互斥）；
      抢占成功写入 running 运行行并占用调度行，必须以 complete_inspection
      收尾；未到期或已被占用返回 None（不抛错）。
    - complete_inspection 回填终态（succeeded/failed）、起止计数，并释放
      调度行、推进 next_run_at（由调度层按周期计算传入）。
    """

    def upsert_finding(self, draft: FindingDraft, *, seen_at: datetime) -> OpsFinding: ...

    def list_findings(
        self,
        *,
        status: OpsFindingStatus | None = None,
        severity: OpsSeverity | None = None,
        asset_type: OpsAssetType | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> OpsFindingPage: ...

    def get_finding(self, finding_id: str) -> OpsFinding:
        """按 finding_id 取单条；不存在抛 OpsFindingNotFoundError。"""
        ...

    def transition_finding(
        self,
        finding_id: str,
        *,
        expected_revision: int,
        new_status: OpsFindingStatus,
        event: OpsFindingEvent,
    ) -> OpsFinding:
        """乐观锁状态流转：status 更新 + revision+1 + 事件留痕（原子）。"""
        ...

    def list_finding_events(self, finding_id: str) -> list[OpsFindingEvent]:
        """生命周期事件时间线（created_at 升序）。"""
        ...

    def insert_remediation_run(self, run: OpsRemediationRun) -> OpsRemediationRun:
        """追加一条修复留痕（#53）。"""
        ...

    def list_remediation_runs(self, finding_id: str) -> list[OpsRemediationRun]:
        """该问题的修复记录时间线（created_at 升序）。"""
        ...

    def save_diagnosis(self, finding_id: str, diagnosis: dict[str, Any]) -> OpsFinding:
        """覆盖写入诊断报告（#51）：不动 status 与 revision。"""
        ...

    def claim_inspection(
        self,
        now: datetime,
        *,
        trigger_source: OpsInspectionTrigger,
        triggered_by: str,
    ) -> OpsInspectionRun | None:
        """抢占一次巡检（#52）：成功返回 running 运行行，None=未到期/执行中。"""
        ...

    def complete_inspection(
        self,
        inspection_id: str,
        *,
        finished_at: datetime,
        status: OpsInspectionStatus,
        finding_count: int,
        new_finding_count: int,
        checker_errors: list[OpsCheckerError],
        next_run_at: datetime,
    ) -> OpsInspectionRun:
        """回填巡检终态并释放调度占位、推进 next_run_at。"""
        ...

    def get_inspection(self, inspection_id: str) -> OpsInspectionRun:
        """按 inspection_id 取单条运行记录；不存在抛 OpsInspectionNotFoundError。"""
        ...

    def get_latest_inspection(self) -> OpsInspectionRun | None:
        """最近一次巡检运行（含 running）；无记录返回 None。"""
        ...

    def get_inspection_schedule(self) -> OpsInspectionScheduleState:
        """调度行当前状态（next_run_at + active 占位）。"""
        ...
