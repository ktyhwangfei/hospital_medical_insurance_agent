"""健康运营服务 — 巡检编排、问题查询、生命周期流转与 L1 自动修复（#45/#50/#53）。"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Callable

from pydantic import BaseModel, Field, computed_field

from src.data_platform.storage.ops.ops_ports import OpsFindingStorage
from src.domain.ops.models import (
    FindingDraft,
    InvalidFindingTransitionError,
    OpsAssetType,
    OpsCheckerError,
    OpsFinding,
    OpsFindingDetail,
    OpsFindingEvent,
    OpsFindingEventType,
    OpsFindingPage,
    OpsFindingStatus,
    OpsInspectionTrigger,
    OpsRemediationRun,
    OpsSeverity,
    RemediationNotAllowedError,
    RemediationRunStatus,
    VerificationResult,
    finding_fingerprint,
    new_finding_event_id,
    new_remediation_run_id,
)
from src.runtime.ops.checkers import OPS_CHECKS, GovernanceStatusReader
from src.runtime.ops.remediation import (
    RemediationSpec,
    default_remediation_whitelist,
)

logger = logging.getLogger(__name__)

# 巡检复现时自动复活 resolved 问题的系统操作者（ignored 不复活，#50 规则）
INSPECTION_ACTOR = "system:ops-inspector"


class OpsInspectionResult(BaseModel):
    """一次巡检的结果快照。

    new_finding_count 为首见问题数（occurrence_count == 1）；
    inspection_id / trigger_source 由调度层（#52）回填——直接调用
    run_inspection（未经调度器）时为空，不落运行留痕。
    """

    checked_at: datetime
    check_count: int = Field(ge=1)
    finding_count: int = Field(ge=0)
    findings: list[OpsFinding]
    checker_errors: list[OpsCheckerError]
    inspection_id: str | None = None
    trigger_source: OpsInspectionTrigger | None = None

    @computed_field  # type: ignore[prop-decorator]
    @property
    def new_finding_count(self) -> int:
        """本次巡检的首见问题数（复现累计不算新发现）。"""
        return sum(1 for finding in self.findings if finding.occurrence_count == 1)


class OpsRemediationResult(BaseModel):
    """一次 L1 自动修复的结果：修复留痕 + 刷新后的问题详情。"""

    run: OpsRemediationRun
    detail: OpsFindingDetail


class OpsHealthService:
    """巡检编排：逐检查器只读取数 → 问题库 fingerprint 去重落库。"""

    def __init__(
        self,
        storage: OpsFindingStorage,
        reader_factory: Callable[[], GovernanceStatusReader],
        remediation_whitelist: tuple[RemediationSpec, ...] | None = None,
    ) -> None:
        self._storage = storage
        self._reader_factory = reader_factory
        self._remediations = {
            spec.check_id: spec
            for spec in (remediation_whitelist or default_remediation_whitelist())
        }

    def run_inspection(self, *, now: datetime | None = None) -> OpsInspectionResult:
        checked_at = now or datetime.now(timezone.utc)
        reader = self._reader_factory()
        findings: list[OpsFinding] = []
        errors: list[OpsCheckerError] = []
        for spec in OPS_CHECKS:
            try:
                drafts = spec.runner(reader, checked_at)
            except Exception as exc:  # 检查器只读，单点故障不拖垮整次巡检
                logger.warning("ops 检查器 %s 执行失败: %s", spec.check_id, exc)
                errors.append(OpsCheckerError(check_id=spec.check_id, message=str(exc)))
                continue
            for draft in drafts:
                findings.append(self._record_recurrence(draft, seen_at=checked_at))
        return OpsInspectionResult(
            checked_at=checked_at,
            check_count=len(OPS_CHECKS),
            finding_count=len(findings),
            findings=findings,
            checker_errors=errors,
        )

    def _record_recurrence(self, draft: FindingDraft, *, seen_at: datetime) -> OpsFinding:
        """落库一次检查产出：resolved 问题复现自动复活；ignored 不复活。"""
        finding = self._storage.upsert_finding(draft, seen_at=seen_at)
        if finding.status is not OpsFindingStatus.RESOLVED:
            return finding
        try:
            return self._storage.transition_finding(
                finding.finding_id,
                expected_revision=finding.revision,
                new_status=OpsFindingStatus.OPEN,
                event=self._build_event(
                    finding.finding_id,
                    OpsFindingEventType.REOPENED,
                    INSPECTION_ACTOR,
                    "修复后巡检再次发现该问题，自动重开",
                    occurred_at=seen_at,
                ),
            )
        except Exception:  # 版本冲突等并发场景：留待下次巡检，不阻塞整次巡检
            logger.warning("resolved 问题 %s 复现重开失败，留待下次巡检", finding.finding_id)
            return finding

    def list_findings(
        self,
        *,
        status: OpsFindingStatus | None = None,
        severity: OpsSeverity | None = None,
        asset_type: OpsAssetType | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> OpsFindingPage:
        return self._storage.list_findings(
            status=status,
            severity=severity,
            asset_type=asset_type,
            page=page,
            page_size=page_size,
        )

    # ── #50 生命周期：详情 + ignore/reopen 流转 ──

    def get_finding_detail(self, finding_id: str) -> OpsFindingDetail:
        """单条问题详情：当前状态 + 生命周期事件与修复留痕时间线。"""
        finding = self._storage.get_finding(finding_id)
        return OpsFindingDetail(
            finding=finding,
            events=self._storage.list_finding_events(finding_id),
            remediations=self._storage.list_remediation_runs(finding_id),
        )

    def ignore_finding(
        self,
        finding_id: str,
        *,
        expected_revision: int,
        reason: str,
        actor: str,
    ) -> OpsFindingDetail:
        """忽略开放问题（必填原因）：open → ignored。"""
        current = self._storage.get_finding(finding_id)
        if current.status != OpsFindingStatus.OPEN:
            raise InvalidFindingTransitionError(finding_id, "ignore", current.status)
        updated = self._storage.transition_finding(
            finding_id,
            expected_revision=expected_revision,
            new_status=OpsFindingStatus.IGNORED,
            event=self._build_event(
                finding_id, OpsFindingEventType.IGNORED, actor, reason,
                occurred_at=datetime.now(timezone.utc),
            ),
        )
        return self.get_finding_detail(updated.finding_id)

    def reopen_finding(
        self,
        finding_id: str,
        *,
        expected_revision: int,
        actor: str,
    ) -> OpsFindingDetail:
        """重开已忽略/已解决问题：ignored|resolved → open。"""
        current = self._storage.get_finding(finding_id)
        if current.status == OpsFindingStatus.OPEN:
            raise InvalidFindingTransitionError(finding_id, "reopen", current.status)
        updated = self._storage.transition_finding(
            finding_id,
            expected_revision=expected_revision,
            new_status=OpsFindingStatus.OPEN,
            event=self._build_event(
                finding_id, OpsFindingEventType.REOPENED, actor, None,
                occurred_at=datetime.now(timezone.utc),
            ),
        )
        return self.get_finding_detail(updated.finding_id)

    # ── #53 L1 自动修复：白名单动作 + 强制验证闭环 ──

    def list_remediation_actions(self) -> list[RemediationSpec]:
        """当前修复白名单（Portal 据此决定是否展示「执行修复」入口）。"""
        return sorted(self._remediations.values(), key=lambda spec: spec.check_id)

    def remediate_finding(
        self,
        finding_id: str,
        *,
        expected_revision: int,
        actor: str,
    ) -> OpsRemediationResult:
        """对开放问题执行白名单 L1 动作，并强制重跑触发检查器验证。

        - 动作执行成功 + 验证通过（检查器不再产出该问题）→ open → resolved；
        - 动作执行成功 + 验证未通过 → 累计 occurrence、刷新证据，保持 open；
        - 动作未能发起（前置条件不满足等）→ 只落 failed 留痕，不改问题状态。
        """
        now = datetime.now(timezone.utc)
        finding = self._storage.get_finding(finding_id)
        if finding.status != OpsFindingStatus.OPEN:
            raise InvalidFindingTransitionError(finding_id, "remediate", finding.status)
        spec = self._remediations.get(finding.check_id)
        if spec is None:
            raise RemediationNotAllowedError(finding_id, finding.check_id)

        outcome = spec.executor(finding, actor)
        verification: VerificationResult | None = None
        still_open_draft: FindingDraft | None = None
        after_evidence = dict(outcome.after_evidence)
        if outcome.executed:
            still_open_draft = self._verify_remediation(finding, after_evidence)
            if "verification_error" not in after_evidence:
                verification = (
                    VerificationResult.FAILED if still_open_draft else VerificationResult.PASSED
                )

        run = self._storage.insert_remediation_run(OpsRemediationRun(
            run_id=new_remediation_run_id(),
            finding_id=finding_id,
            action=spec.action_id,
            risk_level=spec.risk_level,
            status=RemediationRunStatus.SUCCEEDED if outcome.executed else RemediationRunStatus.FAILED,
            before_evidence=outcome.before_evidence,
            after_evidence=after_evidence,
            verification_result=verification,
            created_by=actor,
            created_at=now,
        ))

        if verification is VerificationResult.PASSED:
            self._storage.transition_finding(
                finding_id,
                expected_revision=expected_revision,
                new_status=OpsFindingStatus.RESOLVED,
                event=self._build_event(
                    finding_id,
                    OpsFindingEventType.RESOLVED,
                    actor,
                    f"L1 修复动作 {spec.action_id} 验证通过",
                    occurred_at=now,
                ),
            )
        elif still_open_draft is not None:
            # 验证未通过：问题保持 open，复现计数与证据按最新检查结果累计
            self._storage.upsert_finding(still_open_draft, seen_at=now)

        return OpsRemediationResult(run=run, detail=self.get_finding_detail(finding_id))

    def _verify_remediation(
        self,
        finding: OpsFinding,
        after_evidence: dict,
    ) -> FindingDraft | None:
        """重跑触发检查器：仍产出该问题则返回对应草稿，否则 None。

        检查器自身执行失败时不给出验证结论（verification_error 记入
        after_evidence），问题状态保持不变，留待下次巡检或人工重试。
        """
        check = next((c for c in OPS_CHECKS if c.check_id == finding.check_id), None)
        if check is None:
            after_evidence["verification_error"] = f"触发检查器 {finding.check_id} 已下线"
            return None
        try:
            drafts = check.runner(self._reader_factory(), datetime.now(timezone.utc))
        except Exception as exc:
            after_evidence["verification_error"] = str(exc)
            return None
        for draft in drafts:
            if finding_fingerprint(draft.asset_type, draft.asset_id, draft.check_id) == finding.fingerprint:
                return draft
        return None

    @staticmethod
    def _build_event(
        finding_id: str,
        event_type: OpsFindingEventType,
        actor: str,
        reason: str | None,
        *,
        occurred_at: datetime,
    ) -> OpsFindingEvent:
        return OpsFindingEvent(
            event_id=new_finding_event_id(),
            finding_id=finding_id,
            event_type=event_type,
            actor=actor,
            reason=reason,
            created_at=occurred_at,
        )
